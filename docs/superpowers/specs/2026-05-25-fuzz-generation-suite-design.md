# Fuzz Generation Suite Design

**Status:** design for implementation.
**Target branch:** `feat/fuzz-generation-suite`.
**Source context:** discussion on improving `fuzz-smoke` and
`fuzz-regression` utilization.

## Goal

Improve fuzz and auto-generation coverage without turning replay into a hidden
random system.

The current generator is deterministic and useful, but it underuses the
published profile ceilings and mostly exercises shallow combinations. This
design expands generation in three directions:

1. Broader timeline coverage for materialize-safe behavior.
2. A deterministic regression suite with lane-specific scenarios.
3. Property-based stress tests for generator and execution invariants.

The public output remains normal scenario YAML with explicit timeline events.
Every generated scenario must validate before it is written.

## Current State

`src/chaos_librarian/generation.py` currently supports:

- `fuzz-smoke`: 2 works, 6 timeline events.
- `fuzz-regression`: 8 works, 32 timeline events.
- One library root.
- One variant, one bundle, and one primary video asset per work.
- Event families: `move_asset`, `rename_file`, `edit_metadata`,
  `create_sidecar`, and `update_sidecar`.

The published static ceilings are higher:

| Budget | `fuzz-smoke` | Current smoke | `fuzz-regression` | Current regression |
| --- | ---: | ---: | ---: | ---: |
| Works | 3 | 2 | 12 | 8 |
| Variants | 4 | 2 | 18 | 8 |
| Bundles | 4 | 2 | 18 | 8 |
| Assets | 4 | 2 | 18 | 8 |
| Sidecars | 8 | seed-dependent | 54 | seed-dependent |
| Timeline events | 12 | 6 | 80 | 32 |

The first implementation intentionally avoided deletion, add-after-delete,
slow-copy, network lag, malformed media, filesystem artifacts, and negative
oracle behavior. Those deferrals were correct for the initial contract. They
now leave useful engine and consumer surfaces under-covered.

## Design Summary

Use a hybrid fuzzing model:

1. Public deterministic generation is coverage-led.
2. Internal tests use property-based generation to stress invariants.
3. `fuzz-smoke` remains one small materialize-safe scenario.
4. `fuzz-regression` becomes a deterministic suite of lane-specific scenarios.

The generator should deliberately construct content properties first, then emit
legal timeline events against that planned library. Randomness still exists, but
it is bounded by lane contracts and lifecycle state.

## Profiles And Lanes

`fuzz-smoke` stays a fast local and optional CI profile. It should remain
materialize-safe and should not emit actions requiring extra opt-in labels such
as `malformed-media`, `negative-oracle`, `filesystem-artifacts`, or
`network-fs-lag`.

`fuzz-regression` becomes a suite. Each lane is deterministic for
`(profile, lane, seed, profile_version)` and declares the profile labels needed
by its timeline.

Published static fuzz budgets remain per generated scenario. The regression
suite can exceed the old single-scenario aggregate if every lane is materialized
in one job, so CI must shard or select lanes explicitly instead of treating the
suite as one unbounded run.

Initial lane enum values:

| Lane | Profile labels | Purpose | Default execution |
| --- | --- | --- | --- |
| `smoke` | `fuzz-smoke` | Small materialize-safe coverage for local and optional fast CI. | validate, plan, replay, materialize |
| `core-fs` | `fuzz-regression` | Move, rename, add/delete, archive, move between roots, slow copy. | validate, plan, replay, materialize |
| `media-rewrite` | `fuzz-regression` | Reencode video/audio, remux, metadata edits, codec/container variation. | validate, plan, replay, materialize |
| `sidecar-subtitle` | `fuzz-regression` | Create/update/remove sidecars, extract/embed subtitles, NFO/poster/subtitle mix. | validate, plan, replay, materialize |
| `malformed` | `fuzz-regression`, `malformed-media` | Header corruption, truncation, packet corruption, invalid duration metadata. | validate, plan, replay, materialize where capabilities allow |
| `negative-oracle` | `fuzz-regression`, `negative-oracle` | Wrong oracle hash cases that consumers must detect. | validate, plan, replay, materialize/run in negative-oracle lanes |
| `filesystem-artifact` | `fuzz-regression`, `filesystem-artifacts` | Mtime perturbation and filesystem-observable artifacts. | validate, plan, replay, materialize/run |
| `network-lag` | `fuzz-regression`, `network-fs-lag` | Lag windows for delayed visibility, delayed rename, and held handles. | validate, plan, replay, run |

Lane names are public generation metadata. They do not change execution
semantics by themselves; existing `profiles` labels continue to gate special
actions.

## CLI

Extend the existing `generate` command with a lane option:

```bash
chaos-librarian generate \
  --profile fuzz-regression \
  --lane media-rewrite \
  --seed 457 \
  --out scenario.yaml \
  --json
```

Rules:

- `--lane` defaults to `smoke` for `fuzz-smoke`.
- `--lane` is required for `fuzz-regression`.
- Unsupported lane/profile pairs fail before output is written.
- The JSON summary includes `lane`.
- Generated scenario IDs include lane identity, for example
  `fuzz-regression-media-rewrite-seed-457`.

Do not add `generate-suite` in the first implementation. Tests can use a small
manifest helper first. Add a public suite command later only if users need it.

## Scenario Metadata

Add lane identity to the generated scenario metadata:

```yaml
generation:
  generator: chaos-librarian
  profile: fuzz-regression
  lane: media-rewrite
  profile_version: 2
  seed: 457
  budgets:
    works: 12
    variants: 18
    bundles: 18
    assets: 18
    sidecars: 54
    timeline_events: 80
```

Contract changes:

- Add a dedicated `FuzzLaneName` enum and
  `lane: FuzzLaneName` to `ScenarioGeneration`.
- Bump `FUZZ_GENERATION_PROFILE_VERSION` from `1` to `2`.
- Bump `SCENARIO_SCHEMA_VERSION` because `generation.lane` is a new required
  field when a `generation` block is present.
- Regenerate `schemas/scenario.schema.json`.
- Keep budget ceilings unchanged.
- Validate lane/profile pairing in `Scenario`.
- Update every checked-in scenario fixture to the new top-level
  `schema_version`.
- Regenerate or replace existing checked-in generated fixtures so they also add
  `generation.lane` and no committed `generation.profile_version: 1` scenario
  remains.

The lane enum makes lane identity part of the public scenario contract. This is
intentional: replay bundles embed generated scenario source, and downstream
consumers may report lane identity when a generated case fails.

Generated `profiles` order should be deterministic: the fuzz profile first,
then any required opt-in labels in a fixed enum/order table.

Do not add generated coverage summaries to the public schema yet. Tests can
derive coverage from emitted YAML.

## Generation Pipeline

Generation should become a two-stage process.

### 1. Content Plan

Create a planned library before timeline generation. The content planner
chooses:

- Root layout, including archive/root-move targets where needed.
- Works, variants, bundles, and assets.
- Containers: `mkv`, `mp4`, and lane-specific remux targets.
- Video codecs: existing supported codecs plus `hevc` where valid.
- Video sources and resolutions.
- Audio sources, channel layouts, and language choices.
- Subtitle modes and sidecar kinds.
- Durations that stay within materialize and CI budgets.

The content planner should aim for heterogeneous properties, not uniform random
choice. For example, a media lane should guarantee at least one container remux,
one video reencode, one audio reencode, and one metadata rewrite over distinct
or intentionally repeated assets.

### 2. Timeline Plan

Each lane owns a required action set and optional weighted action pool. The
timeline planner:

- Emits required events first or reserves slots for them.
- Fills remaining slots with weighted legal actions.
- Tracks placed/unplaced assets.
- Tracks current asset paths and root locations.
- Tracks sidecar paths, sidecar kinds, and embedded subtitle state.
- Tracks pending slow copies and lag windows.
- Adds required opt-in profile labels as lane configuration, not as hidden
  post-processing.

Every emitted event remains explicit YAML. The engine, materializer, and replay
commands do not call the generator.

After timeline construction and before YAML serialization, the generator must
derive coverage from the planned content and emitted events. If required lane
cells are missing, generation fails as a generator bug with profile, lane, seed,
and missing cells. It must not write an under-covered scenario.

## Coverage-Led Generation

Coverage-led generation means each lane has explicit coverage expectations. A
valid lane output is not just "some random scenario"; it must hit the cells that
make the lane useful.

Examples:

- `core-fs`: at least one move, rename, archive or root move, slow-copy pair,
  delete/add recovery path where lifecycle allows.
- `media-rewrite`: at least one video reencode, audio reencode, remux, and
  metadata edit.
- `sidecar-subtitle`: at least one subtitle sidecar, one NFO or poster sidecar,
  one sidecar update, one sidecar removal, and one extract/embed cycle.
- `malformed`: at least two corruption families across different assets.
- `network-lag`: at least one lag start/commit pair for each contract-supported
  network lag effect. Provider capability affects run coverage, not generated
  YAML.

The exact scenario can vary by seed, but the lane's purpose should not disappear
because of an unlucky random draw.

## Property-Based Testing

Property-based tests should exercise generator and execution invariants without
becoming user-facing fixtures.

Candidate properties:

- Generated YAML validates for all supported profile/lane pairs and many seeds.
- Re-generating the same `(profile, lane, seed)` yields byte-identical YAML.
- Different seeds usually produce different YAML.
- Generated paths remain under declared library roots.
- Profile-gated actions include their required profile labels.
- Timelines are lifecycle-valid unless a test intentionally targets invalid
  fixture generation.
- `plan` followed by `replay` remains stable for generated scenarios.
- Materialize preflight accepts or rejects lanes according to the supported
  action/profile matrix.
- Generated coverage for each lane meets required action/content cells.

Property tests should use small sizes by default and may mark heavier cases for
extended runs. They must use deterministic Hypothesis settings with a fixed
deadline policy, bounded example counts, and no dependence on wall-clock time or
installed media tools unless the test is explicitly marked as an integration
case. Failures should print profile, lane, seed, and a reduced scenario or
reproduction command.

## CI Seed Manifest

Use a committed seed manifest for deterministic CI coverage:

```yaml
fuzz_smoke:
  - lane: smoke
    seed: 123
    gates: [validate, plan, replay, materialize]
fuzz_regression:
  - lane: core-fs
    seed: 456
    gates: [validate, plan, replay, materialize]
  - lane: media-rewrite
    seed: 457
    gates: [validate, plan, replay, materialize]
  - lane: sidecar-subtitle
    seed: 458
    gates: [validate, plan, replay, materialize]
  - lane: malformed
    seed: 459
    gates: [validate, plan, replay, materialize]
  - lane: negative-oracle
    seed: 460
    gates: [validate, plan, replay, materialize, run]
  - lane: filesystem-artifact
    seed: 461
    gates: [validate, plan, replay, materialize, run]
  - lane: network-lag
    seed: 462
    gates: [validate, plan, replay, run]
```

CI should regenerate these scenarios from the current generator and run:

- `validate`, `plan`, and `replay` for all lanes.
- `materialize` for materialize-safe and capability-supported lanes.
- `run` for lanes that need wall-clock or network behavior, with unsupported
  provider capabilities reported as visible skips rather than changing generated
  scenarios.
- Aggregate materialized bytes and wall-clock time must be controlled by the
  manifest gates and CI sharding. A lane can use the per-scenario
  `fuzz-regression` budget, but no CI tier should accidentally multiply that
  budget by every lane without an explicit opt-in.

Keep one or two generated YAML fixtures committed for docs and replay
regression. Use the manifest for broader generator drift detection. Add a test
that regenerates each committed generated fixture from its metadata and fails on
byte drift, matching the existing schema drift pattern.

## Errors

Generation failures should be loud and actionable:

- Unknown lane: list supported lanes for the selected profile.
- Missing lane for `fuzz-regression`: list required lane options.
- Lane/profile mismatch: name both values and the supported pairings.
- Lane coverage failure: report profile, lane, seed, and missing required cells.
- Generated validation failure: report lane, seed, and validation issues.
- Budget overflow: report lane, seed, budget dimension, actual count, and limit.
- Output path collision: preserve current non-overwriting behavior.

Capability skips do not belong in generation. The generated scenario should
declare requirements through existing profile labels; execution commands decide
whether a local environment can run them.

## Success Criteria

Implementation is successful when:

- `generate --profile fuzz-smoke --seed 123` still emits one small
  materialize-safe scenario.
- `generate --profile fuzz-regression --lane <lane> --seed <seed>` emits valid
  deterministic YAML for every lane above.
- Generated regression lanes collectively cover materialize-safe timeline
  families, malformed media, negative oracle, filesystem artifacts, and network
  lag.
- Lane outputs stay within published fuzz-regression static budgets.
- The seed manifest can regenerate the suite and pass the selected CI gates.
- Property-based tests cover generator invariants across many seeds.
- Replay never calls the generator.

## Out Of Scope

- Hidden runtime random mutations during `plan`, `materialize`, `run`, or
  `replay`.
- Open-ended unbounded fuzzing.
- A public `generate-suite` command in the first implementation.
- Persisting coverage summaries in scenario or replay-bundle schemas.
- Changing performance profile budgets.
- Adding new execution semantics for profile labels.
