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

- Type `int`, `min=1`, `max=10000`, default `1`.
- The `max` is a typo guard against runaway disk writes, not a coverage policy;
  CI breadth is controlled by the seed manifest and sharding, as in the
  fuzz-generation-suite design. The error names the limit.

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

Properties this guarantees:

- **Determinism:** the item list is a pure function of `(profile, lane, seed,
  count)`.
- **No collisions:** `seed_i` is strictly increasing, so every item has a unique
  `seed_i`; the generated `scenario_id = f"{profile}-{lane}-seed-{seed}"` is
  therefore unique, and so is its `<scenario_id>.yaml` file name. The
  implementation still asserts uniqueness of the planned file-name set and fails
  loudly if a future change breaks it.
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

## Write Semantics (all-or-nothing within the process)

Batch writing is staged so a generator bug never leaves a half-written directory:

1. **Generate + validate all** items in memory (each via the existing
   `generate_scenario`, which validates). Any failure aborts the whole command
   before any file is written; the error names profile, lane, and seed.
2. **Pre-check collisions:** compute every target path and fail loudly (writing
   nothing) if any already exists.
3. **Write all** via the existing `write_generated_scenario` (atomic temp-file +
   `os.link`, non-overwriting).

Residual edge: a concurrent process could create one of the target files between
step 2 and step 3. `write_generated_scenario`'s `os.link` is atomic and raises
`FileExistsError`, so the batch fails loudly mid-write rather than overwriting,
but earlier files in that batch remain on disk. This TOCTOU window is documented,
not closed; closing it would require directory locking that the single-scenario
path also lacks. The failure message names the colliding path.

Memory cost of step 1 is bounded by `max=10000` × per-scenario YAML size (a few
KB), i.e. tens of MB worst case — acceptable for a developer/CI tool.

## Output

### Human output

- `--count == 1`: unchanged — `generate: wrote <path>`.
- `--count > 1`: one `generate: wrote <path>` line per scenario in the planned
  order, then a final `generate: wrote N scenarios to <dir>` line.

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

All batch errors are loud and actionable and write nothing partial at the
pre-write stages:

- `--count` out of range: Typer reports the `min`/`max`.
- `--out` not an existing directory when `count > 1`: name the path and the
  requirement.
- `--lane is required for fuzz-regression` when `count == 1`: unchanged.
- lane/profile mismatch: unchanged.
- generated scenario fails validation (generator bug): name profile, lane, seed,
  and the validation issues; nothing written.
- target file collision: name the colliding path.

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
