# Issue #74 - Fuzz Profile Generation

**Status:** design for implementation.
**GitHub issue:** [#74](https://github.com/randomparity/chaos-librarian/issues/74)
**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md)
("Design Principles", "Replay Bundle", "Reproducibility Guarantees", and
"Sprint 10 - Extended Profiles").
**Target implementation branch:** `feat/issue-74-fuzz-profiles`.

## Goal

Add bounded, deterministic fuzz profile generation without introducing hidden
runtime randomness. Generated scenarios are normal scenario YAML: their timelines
are explicit, their generator seed and profile metadata are serialized, and
existing `plan`, `materialize`, `run`, and `replay` commands consume them without
a special replay path.

This design closes the issue by specifying:

1. Fuzz profile labels and CI bounds.
2. A deterministic `generate` CLI command.
3. Scenario-embedded generation metadata.
4. Replay and serialization guarantees.
5. The first generated fuzz profile fixtures.

## Context

Sprint 10 intentionally kept malformed-media mutations explicit in scenario
timelines and deferred profile generation. The project already has deterministic
RNG streams, schema-validated scenario YAML, replay bundles that embed the
scenario source, and performance profile budgets. The missing piece is a contract
for creating randomized scenario inputs while preserving the same explicit
timeline and replay model.

The generator must not become a second execution engine. It writes source
scenarios only. Once a scenario has been emitted, every existing command treats it
the same way it treats a hand-authored fixture.

## Profile Labels

Add these profile labels to `ProfileName`:

| Profile label | Purpose | CI status |
| --- | --- | --- |
| `fuzz-smoke` | Small generated mutation scenarios. | Optional fast job or local command. |
| `fuzz-regression` | Broader deterministic coverage. | Scheduled or maintainer dispatch. |

The labels are independent of `malformed-media`, `network-fs-lag`, and
performance profiles. The first implementation emits one fuzz label per scenario
and no malformed-media, lag, negative-oracle, or filesystem-artifact interceptor
labels.

Add a dedicated `FuzzProfileName` enum for generator-facing fields. It contains
the same two string values as the fuzz entries in `ProfileName`, but prevents the
exported `generation.profile` schema from accepting unrelated profile labels.

## CI Bounds

Fuzz profiles are bounded both by the generator and by validation. A generated
scenario that exceeds the selected profile budget is invalid even if the command
that wrote it is not `chaos-librarian generate`.

| Budget | `fuzz-smoke` | `fuzz-regression` |
| --- | ---: | ---: |
| Works | 3 | 12 |
| Variants | 4 | 18 |
| Bundles | 4 | 18 |
| Media assets | 4 | 18 |
| Sidecars | 8 | 54 |
| Timeline events | 12 | 80 |
| Materialized bytes under `library/` | 75 MB | 250 MB |
| Wall-clock run duration | 2 minutes | 10 minutes |
| Minimum free disk before run | 500 MB | 1 GB |

Byte budgets use decimal units. The static YAML ceilings are enforced during
scenario validation. Materialized-byte, wall-clock-duration, and free-disk
ceilings are CI/run preconditions because they depend on the selected execution
mode and local toolchain.

Fast CI may run `fuzz-smoke` in a separate, explicitly selectable job. Fast CI
must not run `fuzz-regression` by default. Extended CI may run both labels and
must keep capability skips visible. Disk capacity is not a skip reason after a CI
tier opts into a fuzz profile; the job should fail during setup with an
actionable message.

## CLI Surface

Add a new command after `validate` in the registered CLI order:

```bash
chaos-librarian generate --profile fuzz-smoke --seed 123 --out scenario.yaml --json
```

Arguments and options:

| Option | Required | Behavior |
| --- | --- | --- |
| `--profile` | yes | One of `fuzz-smoke` or `fuzz-regression`. |
| `--seed` | yes | Non-negative integer. `random` is not accepted by the generator. |
| `--out` | yes | Destination scenario YAML path. Parent must exist; path must not already exist. |
| `--json` | no | Emits `ok`, path, profile, seed, scenario ID, and sha256. |

The command writes YAML only. It does not plan, materialize, run, or create a
replay bundle. Users get a replay bundle by passing the generated scenario to the
existing execution commands.

The write is atomic and non-overwriting: render bytes in memory, write to a
sibling temporary file, fsync and close it, then install it with an exclusive
same-directory link operation that fails if the destination exists. A failed
write cleans up the temporary file and leaves no partial scenario at `--out`.

## Scenario Metadata

`Scenario` gains an optional `generation` block:

```yaml
generation:
  generator: chaos-librarian
  profile: fuzz-smoke
  profile_version: 1
  seed: 123
  budgets:
    works: 3
    variants: 4
    bundles: 4
    assets: 4
    sidecars: 8
    timeline_events: 12
```

Contract model:

```python
class FuzzProfileName(enum.StrEnum):
    FUZZ_SMOKE = "fuzz-smoke"
    FUZZ_REGRESSION = "fuzz-regression"


class GenerationBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    works: int = Field(ge=0)
    variants: int = Field(ge=0)
    bundles: int = Field(ge=0)
    assets: int = Field(ge=0)
    sidecars: int = Field(ge=0)
    timeline_events: int = Field(ge=0)


class ScenarioGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generator: Literal["chaos-librarian"] = "chaos-librarian"
    profile: FuzzProfileName
    profile_version: int = Field(ge=1)
    seed: int = Field(ge=0)
    budgets: GenerationBudget
```

`Scenario` validation enforces these generation-specific invariants:

- `generation.profile` must be `fuzz-smoke` or `fuzz-regression`.
- `generation.profile` must also appear in top-level `profiles`.
- `seed` must be a concrete integer, not `random`.
- `seed` must equal `generation.seed`.
- `generation.budgets` must equal the canonical limits for
  `generation.profile` and `profile_version`.

The generator writes `schema_version: 10`, so `SCENARIO_SCHEMA_VERSION` is bumped
from `9` to `10` and `schemas/scenario.schema.json` is regenerated. Existing
hand-authored scenarios without `generation` remain valid after their schema
version is bumped with the fixture corpus.

## Generation Algorithm

The generator is pure Python and uses the existing deterministic RNG stream
pattern. It has no dependency on FFmpeg, ffprobe, local filesystem probing, or
wall-clock time.

For a fixed `(profile, seed, profile_version)` tuple, output YAML is
byte-identical across runs and platforms. The YAML key order is stable and the
serializer does not emit comments, timestamps, anchors, or aliases.

First implementation event families:

- `move_asset`
- `rename_file`
- `edit_metadata`
- `create_sidecar` with `kind: nfo`
- `update_sidecar` for generator-created NFO sidecars

The first implementation intentionally avoids deletion, add-after-delete,
slow-copy, network lag, and corruption events. Those actions have stronger
lifecycle and live-observer semantics and can be added after the base generator
contract is proven.

Path generation uses unique event-indexed paths under the scenario's declared
library root. The generator tracks current asset paths and created sidecar paths
while building YAML so it never emits known path duplicates, unknown sidecar
references, or events targeting a deleted asset.

## Serialization And Replay

Generation output is replayable at two layers:

1. Re-running `generate` with the same profile and seed reproduces the same YAML
   bytes.
2. Running `plan`, `materialize`, or `run` on that YAML produces the normal replay
   bundle, whose `scenario` field embeds the emitted YAML source verbatim.

Replay never calls the generator. It reuses the scenario source already stored in
`replay.json`. This avoids a version-skew problem where replay behavior changes
because the generator changed after the original run.

The `generation` block is provenance and reproducibility metadata, not an
instruction for execution. The engine and materializer do not branch on it except
through existing profile-budget validation.

## Fixtures

Add two generated fixture scenarios:

```text
tests/fixtures/scenarios/fuzz-smoke-seed-123.yaml
tests/fixtures/scenarios/fuzz-regression-seed-456.yaml
```

Both fixtures are committed source YAML, not materialized outputs. They are
loaded by the existing sample-scenario validation corpus. The smoke fixture is
small enough for local materialize checks; the regression fixture is intended for
plan and validation coverage by default, with materialize/run coverage reserved
for extended CI.

## Documentation

Update:

- `docs/specs/chaos-librarian-design.md` with a Fuzz Profile Generation Policy
  and a Sprint 10 deliverable that points to it.
- `docs/contract/cli-reference.md` with the new command.
- `docs/contract/integration-recipes.md` with a Fuzz Profile Generation recipe
  and CI guidance.
- `docs/developer/testing.md` with fuzz profile testing guidance.

Add docs tests that keep the profile labels, command name, replay guarantee, and
CI bounds discoverable.

## Verification Expectations

Implementation should include:

- Contract tests for the two profile labels and `generation` model validation.
- Generator unit tests proving same seed/profile emits byte-identical YAML and
  different seeds emit different YAML.
- CLI tests for `generate --help`, required options, existing-output rejection,
  JSON output, and generated YAML validation.
- Validation tests proving `fuzz-smoke` and `fuzz-regression` static budgets are
  enforced.
- Plan/replay tests proving a generated fixture can be planned and replayed
  without calling the generator.
- Docs tests for the policy and CLI recipe.
- Schema drift check after regenerating `schemas/scenario.schema.json`.

## Out Of Scope

- Open-ended fuzzing without named bounds.
- Hidden background mutations during `plan`, `materialize`, `run`, or `replay`.
- `seed: random` generator mode.
- Generator output that depends on installed media tools.
- Fuzzing malformed-media, network-lag, or negative-oracle interceptors.
- New materialization report or replay-bundle schema fields.
- CI workflow changes beyond documentation and tests.
