# Issue 104 Batch Scenario Generation Design

**Status:** design for implementation.
**Target branch:** `feat/generate-batch-104`.
**Source context:** GitHub issue #104 "Scenario Fuzzing & Auto-Generation".
**Supersedes the open CLI questions in:**
[`2026-05-25-fuzz-generation-suite-design.md`](2026-05-25-fuzz-generation-suite-design.md)
(which deferred "a public suite command" to a later change). This is that change.

## Problem

Issue #104 asks for a `generate` subcommand that "produces hundreds of
combinations to find edge cases" in one invocation, parameterised by
`--profile`, `--count`, `--seed`, `--out`, and `--timeline-weight`.

The single-scenario `generate` command already shipped on a different, deliberate
foundation: the **coverage-led lane** architecture from the fuzz-generation-suite
design. That design explicitly rejected open-ended weighted fuzzing and
explicitly deferred a batch/suite command. Issue #104's literal flag list
(`--timeline-weight`, named "timeline strategies" such as `heavy-churn`,
`heavy-corruption`, `sidecar-focused`, `network-lag`) substantially duplicates
the existing **lanes**, which already partition timeline coverage by action
family.

This design reconciles the two: it delivers the batch capability #104 needs by
**layering a `--count` batch mode onto the existing lane architecture**, and does
not add the overlapping `--timeline-weight` knob. The reconciliation decision and
its rejected alternatives are recorded in
[ADR 0001](../../adr/0001-batch-generate-seed-and-lane-distribution.md).

## Goals

- Generate N deterministic scenarios from one `generate` invocation via a new
  `--count N` option, written into a directory `--out`.
- Preserve the existing single-file `generate` contract exactly when `--count`
  is 1 (the default): same CLI surface, same JSON summary shape, same output
  path semantics, same exit codes.
- Make batch output fully deterministic: `(profile, seed, count[, lane])`
  determines the exact set of file names and file bytes.
- Keep every generated scenario individually reproducible with the existing
  single-file `generate --profile P --lane L --seed S` invocation.
- Cover batch-specific edge cases in tests.

## Non-Goals

- No `--timeline-weight` option and no named "timeline strategies". Lanes are the
  shipped, tested mechanism for action-family emphasis; adding a parallel knob
  would create two overlapping coverage controls. See ADR 0001 "Considered &
  rejected".
- No `--validate` flag. Generation already runs the full validation pipeline on
  every scenario before writing it (`generation._validate_generated_yaml`); a
  flag would be redundant and could imply validation is otherwise skipped.
- No `--plan` flag. Generated files are ordinary scenario YAML; users pipe them
  into the existing `plan` / `materialize` commands. Adding per-scenario run-dir
  orchestration to `generate` would duplicate those commands.
- No Pydantic model or JSON Schema changes. Batch generation is a CLI and
  orchestration layer over the unchanged single-scenario generator. The
  `ScenarioGeneration` metadata block and all `schemas/*.json` artifacts are
  untouched.
- No new execution semantics, no runtime randomness in `plan`/`materialize`/
  `run`/`replay`. Replay still never calls the generator.

## CLI Surface

Extend the existing command with one option:

```bash
chaos-librarian generate \
  --profile fuzz-regression \
  --count 9 \
  --seed 42 \
  --out ./generated/ \
  --json

chaos-librarian generate \
  --profile fuzz-smoke \
  --count 20 \
  --seed 42 \
  --out ./generated/
```

`--count N`:

- Type `int`, `min=1`, `max=1000`, default `1`.
- The `max` is a runaway guard against typos producing a flood of files and
  wall-clock (each scenario runs the full validation pipeline), not a coverage
  policy; CI breadth is controlled by the seed manifest and sharding, as in the
  fuzz-generation-suite design. The error names the limit. (The issue's examples
  use `--count 20` and `--count 5`; 1000 leaves ample headroom.)

`--out`:

- When `--count == 1`: `--out` is a **new file path**, exactly as today. Validated
  by the existing `validate_new_out_path` rules (must not exist; parent must be
  an existing directory).
- When `--count > 1`: `--out` is an **existing directory**. It is not created.
  Each scenario is written into it as `<scenario_id>.yaml`. If `--out` does not
  exist or is not a directory, the command fails before writing anything.

`--profile`, `--lane`, `--seed`, `--json`: unchanged in meaning.

### Lane resolution with `--count`

| profile | `--lane` | `--count` | behaviour |
| --- | --- | --- | --- |
| `fuzz-smoke` | omitted | any | all items use lane `smoke` |
| `fuzz-smoke` | `smoke` | any | all items use lane `smoke` |
| `fuzz-smoke` | other | any | error (exit 2), as today |
| `fuzz-regression` | `L` | any | all items use lane `L` |
| `fuzz-regression` | omitted | `1` | **error (exit 2): `--lane is required`**, as today |
| `fuzz-regression` | omitted | `>1` | items cycle the canonical lane order |

The `--count == 1` rows are byte-for-byte identical to current behaviour, so no
committed contract test changes. The relaxation — `--lane` becomes optional for
`fuzz-regression` only when `--count > 1` — is additive: inputs that previously
errored now succeed. Rationale: a single scenario has no natural lane to pick
(hence still required), but a batch sweeps the suite.

## Batch Plan

A pure helper computes the batch before any I/O:

```
plan_generation_batch(profile, lane, seed, count) -> tuple[GenerationItem, ...]
```

where `GenerationItem = (lane: FuzzLaneName, seed: int)`.

Rules (for item index `i` in `0 .. count-1`):

- `seed_i = seed + i`.
- `lane_i`:
  - if `--lane L` was supplied: `lane_i = L`.
  - else if `profile == fuzz-smoke`: `lane_i = smoke`.
  - else (`fuzz-regression`, no lane, `count > 1`):
    `lane_i = CANONICAL_FUZZ_LANES[fuzz-regression][i % len]`.

### Single source of truth for `scenario_id`

The `scenario_id` format (`f"{profile}-{lane}-seed-{seed}"`) is currently inlined
in `generation._generate_scenario_yaml_unvalidated`. This design extracts it into
a shared pure helper in `generation.py`:

```
scenario_id_for(profile, lane, seed) -> str
```

Both the single-scenario generator and the batch path planner call it, so the
file name and the `scenario_id` embedded in the YAML cannot drift. Because it is
pure and needs no generation, the batch can compute every target path from the
plan *before* generating anything (used by the collision pre-check below). After
each scenario is generated, the implementation asserts
`generated.scenario.scenario_id == scenario_id_for(profile, lane_i, seed_i)` as a
guard; a mismatch is a generator bug and aborts the batch.

The target file name is `f"{scenario_id_for(profile, lane_i, seed_i)}.yaml"`. It
is traversal-safe by construction: `profile` and `lane` are `StrEnum` values
(fixed lowercase/`-` charset) and `seed` is an `int >= 0`, so the name contains
no path separators or `..`.

Properties this guarantees:

- **Determinism:** the item list, the file-name set, and each file's bytes are
  pure functions of `(profile, lane, seed, count)`.
- **No collisions:** `seed_i` is strictly increasing, so every item has a unique
  `seed_i`, hence a unique `scenario_id` and a unique `<scenario_id>.yaml` name.
  The planner asserts uniqueness of the computed file-name set and fails loudly
  if a future change breaks it.
- **Individual reproducibility:** item `i` is exactly what
  `generate --profile P --lane lane_i --seed seed_i` produces as a single file.

### Canonical lane order

`CANONICAL_FUZZ_LANES` is a new `Final` mapping in `contract/profiles.py` giving a
fixed tuple ordering per profile. For `fuzz-regression` the order matches the
fuzz-generation-suite spec table:

```
core-fs, media-rewrite, sidecar-subtitle, malformed,
negative-oracle, filesystem-artifact, network-lag,
tv-topology, music-topology
```

The order is part of the batch reproducibility contract. A unit test asserts
`frozenset(CANONICAL_FUZZ_LANES[p]) == FUZZ_LANES_BY_PROFILE[p]` for every
profile, so the ordered tuple and the existing frozenset cannot drift apart when
lanes are added or removed.

## Write Semantics (rollback on failure)

The batch is not a true atomic filesystem transaction (POSIX gives no
multi-file commit), but it is made *self-cleaning*: on any failure, files this
invocation created are removed, so the directory is left as it was found and the
command can simply be re-run. Writes are streamed one scenario at a time, so
peak memory holds a single scenario, not the whole batch.

1. **Plan + pre-check (no generation yet).** Compute the `(lane_i, seed_i)` list
   and, via `scenario_id_for`, every target path. Fail loudly, writing nothing,
   if `--out` is not an existing directory, if the planned file-name set is not
   unique (generator-bug guard), or if any target path already exists.
2. **Generate → validate → write, per item, tracking what was written.** For
   each item: `generate_scenario` (which validates), assert its `scenario_id`
   matches the precomputed one, then `write_generated_scenario` (atomic
   temp-file + `os.link`, non-overwriting). Append the path to a written-list
   only after the link succeeds.
3. **Rollback on any failure in step 2.** If generation, validation, the
   `scenario_id` assertion, or any write raises — including a concurrent
   collision (`FileExistsError` from `os.link`), `ENOSPC`, `EACCES`, or an
   `fsync` failure — best-effort `unlink(missing_ok=True)` every path in the
   written-list, then emit a rollback notice to stderr naming the removed paths
   (`generate: rolled back N partially written files: ...`) and re-raise wrapped
   with the failing profile/lane/seed (and the colliding path for collisions).
   The rollback notice is required so the streamed per-item "wrote" lines (see
   "Output") cannot end as stale success claims for files that no longer exist:
   stdout shows what was written, stderr shows what was then removed.

Failure-mode table for step 2:

| failure | when | on-disk result after rollback |
| --- | --- | --- |
| generator bug / validation fail | any item | nothing (earlier files unlinked) |
| `scenario_id` mismatch assert | any item | nothing (earlier files unlinked) |
| concurrent `FileExistsError` | any item | earlier files unlinked; the pre-existing colliding file is **not** touched |
| `ENOSPC` / `EACCES` / `fsync` | any item | earlier files unlinked (best effort) |

Residual edge: rollback is best-effort. If the process is hard-killed
(`SIGKILL`, power loss) mid-batch, files already linked remain and a re-run will
fail the step-1 collision check until the directory is cleaned. This is the same
durability boundary the single-scenario path already has; it is documented, not
closed. The non-overwriting `os.link` guarantees the batch never destroys
pre-existing files even mid-failure.

Peak memory is one generated scenario plus the `O(count)` lightweight write
records (path + a small per-scenario summary). Measured `fuzz-regression`
scenarios are ~10 KB, so even at `--count 1000` the transient footprint is a few
tens of MB; the full `Scenario` model is not retained across items.

## Output

### Human output

- `--count == 1`: unchanged — `generate: wrote <path>`.
- `--count > 1` (non-`--json` only): one `generate: wrote <path>` line per
  scenario (to stdout) in the planned order as each write succeeds — this doubles
  as progress for long runs — then a final `generate: wrote N scenarios to <dir>`
  line on success. On failure, rollback (step 3 above) removes those files and
  prints a `generate: rolled back N partially written files: ...` notice to
  stderr, so the final output reflects the true on-disk state (an
  empty/unchanged directory).
- Under `--json` these per-item progress lines are **suppressed** so stdout
  carries exactly the one summary object (see below); the rollback notice on
  failure still goes to stderr, which does not corrupt stdout.

### JSON output (`--json`)

- `--count == 1`: unchanged — the existing flat single-object summary from
  `generated_scenario_summary` (`ok`, `lane`, `profile`, `scenario_id`,
  `scenario_path`, `seed`, `sha256`).
- `--count > 1`: a JSON object

  ```json
  {
    "ok": true,
    "count": 9,
    "out_dir": "<resolved absolute dir>",
    "scenarios": [ <per-scenario summary>, ... ]
  }
  ```

  where each element is the same flat summary shape as the single case, and the
  list is sorted by `scenario_path` for stable, diffable output.

Under `--json`, stdout contains exactly this one object and nothing else (no
per-item progress lines), so `json.loads(stdout)` succeeds just as it does for
`count == 1`. The summary JSON is emitted only on success (`"ok"` is always
`true` when present). On failure the command writes no JSON: it exits non-zero
with the human stderr lines above, exactly as the `count == 1` path does today.
Scripts should treat a non-zero exit as failure rather than expecting an
`ok: false` object.

## "Works in both materialize and plan modes" (acceptance criterion)

Generated scenarios are ordinary scenario YAML and already plan and materialize;
the fuzz-generation-suite lanes were designed to run in both, and
`tests/cli/test_generate_replay.py` already exercises plan→replay on a generated
lane scenario. This design adds a unit test that a batch-generated file `plan`s
successfully (no media tools required). `materialize` of generated scenarios
stays in the existing env-gated integration suite (it needs ffmpeg and is gated
in CI); this design does not un-gate it.

## Edge-case test coverage (acceptance criterion)

The issue lists "empty timeline, single asset, max budgets". Those are properties
of the **single-scenario generator**, fixed by each lane's budget contract — they
are not configurable through the batch layer, and existing
`tests/test_generation*.py` property tests already exercise the generator's
content range and budget ceilings. The batch layer's own edge cases, which this
design does add tests for:

- `count == 1`: byte-identical to current single-file behaviour (file `--out`,
  flat JSON summary, existing exit codes).
- `count == len(lanes)` for `fuzz-regression` with no `--lane`: one scenario per
  lane, each lane present exactly once.
- `count > len(lanes)`: lanes cycle; the second pass over a lane uses a different
  derived seed and therefore a different `scenario_id`/file (no collision).
- `count > 1` with explicit `--lane`: all items in that lane, increasing seeds.
- `fuzz-smoke` with `count > 1`: all items lane `smoke`, increasing seeds.
- determinism: same `(profile, seed, count)` → identical file-name set and
  identical bytes per file across two runs into separate directories.
- `--out` is a missing path or a regular file when `count > 1`: error, nothing
  written.
- a target file already exists in `--out`: error, nothing written for that batch.
- `fuzz-regression` with no `--lane` and `count == 1`: still errors (contract
  preserved).

Where a literal issue edge ("empty timeline") is unreachable because every lane
has `timeline_events > 0`, the spec records it as N/A by lane contract rather
than adding a test that cannot fire — surfacing the gap instead of hiding it.

## Errors

All batch errors are loud and actionable; any failure rolls back files this
invocation wrote (see "Write Semantics"):

- `--count` out of range: Typer reports the `min`/`max`.
- `--out` not an existing directory when `count > 1`: name the path and the
  requirement; nothing written.
- `--lane is required for fuzz-regression` when `count == 1`: unchanged.
- lane/profile mismatch: unchanged.
- target path already exists at the step-1 pre-check: name the colliding path;
  nothing written.
- generated scenario fails validation (generator bug): name profile, lane, seed,
  and the validation issues; partial batch rolled back.
- mid-batch concurrent collision / `ENOSPC` / `EACCES`: name the failing
  scenario (and colliding path); partial batch rolled back best-effort.

## Success Criteria

- `generate --profile fuzz-smoke --seed 123 --out s.yaml [--json]` is
  byte-identical to its current behaviour (no `--count`).
- `generate --profile P --count N --seed S --out DIR/` writes exactly N validated
  scenario files into `DIR/`, deterministically named, for both profiles.
- Re-running the same `(profile, seed, count[, lane])` into a fresh directory
  yields the same file names and byte-identical contents.
- For `fuzz-regression` with no `--lane`, items cycle the canonical lane order;
  with `--lane L`, all items are lane `L`.
- Each batch item equals the single-file output of `generate --lane lane_i
  --seed seed_i`.
- A batch-generated scenario `plan`s successfully.
- ruff, ty, pytest, and the schema drift gate stay green (no schema change).
