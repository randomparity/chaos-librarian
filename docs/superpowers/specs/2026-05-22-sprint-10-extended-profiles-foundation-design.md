# Sprint 10 - Extended Profiles Foundation

**Status:** design, pending implementation plan.
**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md)
("Sprint 10 - Extended Profiles", "Mutation Pipeline", and
"Mutation Model").
**Predecessor:** Sprint 9 (`feat/sprint-9`) adds the consumer-neutral adapter
and comparison reports. Sprint 10 gives that adapter a clearly labeled malformed
media surface without making corruption the default.
**Target branch:** `feat/sprint-10`.

## Goal

Sprint 10 establishes the extended-profile foundation while shipping exactly one
concrete opt-in malformed-media profile.

The sprint ships:

1. A top-level scenario profile marker, starting with `"malformed-media"`.
2. One explicit timeline action, `corrupt_container_header`.
3. Deterministic byte-level corruption for materialize, run, and run replay.
4. Contract metadata that labels corrupted versions and records corruption audit
   evidence.
5. One fixture scenario that produces intentionally malformed media.
6. GitHub issues for the deferred Sprint 10 requirements.

Exit criteria:

- Corruption is impossible unless the scenario explicitly opts in with
  `profiles: ["malformed-media"]`.
- A malformed-media fixture materializes successfully and records whether
  post-corruption `ffprobe` failed or still parsed the file.
- Replay reproduces the same logical corruption event: corruptor, byte range,
  seed material, and replacement-byte stream.
- Fast CI can exclude this profile by selecting scenarios without profile labels.

## Decisions Resolved In Brainstorming

1. **Foundation sprint, not broad profile sprint.** Sprint 10 creates the
   profile contract and dispatch lane, then ships one profile. Public-domain/TTS
   sources, performance profiles, network lag, duplicate/variant expansion,
   broader fuzz generation, and the full corruption catalog are deferred to
   filed issues.

2. **Explicit timeline action.** `corrupt_container_header` is a normal scenario
   timeline event. There is no profile generator and no hidden background
   randomness. This preserves the source design rule that mutations are explicit
   scenario events.

3. **Small shared profile contract module.** Add `contract/profiles.py` for
   shared enums and metadata models used by scenario, manifest, reports, and
   materialization contracts. It is not exported as a standalone schema artifact;
   the public wire surface remains the existing generated schemas.

4. **Malformed-media profile label.** Corruption actions require
   `profiles: ["malformed-media"]`. Missing opt-in is a validation error, not a
   materializer preflight error, so bad scenarios fail with exit code `3`.

5. **Corruption mutates bytes and allocates a new version.** Header corruption is
   a byte-changing media mutation. The engine allocates a new `version_id`, binds
   it as current, and records corruption intent. Materialize later fills the
   content hash and probe outcome evidence.

6. **Header corruptor is deterministic without new RNG draws.** The corruptor
   overwrites the first N bytes with a deterministic byte stream derived from
   `(resolved_seed, event_id, target_asset_id, corruptor_name)`. This avoids a
   materializer-only RNG stream while still making replay evidence explicit.

7. **Probe outcome is evidence, not the success gate.** The corruption handler
   attempts `ffprobe` after mutation. A parse/subprocess failure records
   `probe_outcome="failed_expected"` and leaves `probed=None`. A successful
   probe records `probe_outcome="still_probeable"` and stores the returned probe
   facts on the corrupted version. Both outcomes are successful malformed-media
   runs; actual corruptor failures use `CORRUPTION_FAILED`.

8. **No new dependencies.** Use `hashlib` and existing file I/O only. The header
   corruptor does not require FFmpeg beyond the existing phase-A synthesis and
   probe tooling.

9. **Reports surface corruption.** The current version's corruption metadata is
   visible through both `manifest.current.json` and per-asset reports. Consumers
   do not have to infer malformed intent from missing probe facts.

10. **Deferred work is tracked.** The source spec's deferred Sprint 10
    requirements are filed as issues #70 through #75 and referenced below.

## Scope

### In Scope

- Add `profiles` to `Scenario`.
- Add `ProfileName.MALFORMED_MEDIA`.
- Add `TimelineActionName.CORRUPT_CONTAINER_HEADER`.
- Add `CorruptContainerHeaderEvent` with:
  - `target: str`
  - `bytes: int = 64`
- Validate `bytes` as `1 <= bytes <= 4096`.
- Validate that corruption actions require `"malformed-media"` in
  `Scenario.profiles`.
- Extend lifecycle validation so corruption requires a currently placed asset
  and is rejected while a slow copy is pending for that asset.
- Add corruption metadata to `ManifestVersion`.
- Add corruption metadata to `AssetSnapshot`.
- Add `CorruptionAction` records to `MaterializationReport`.
- Add a `materializer/corruption.py` dispatcher and hook it into materialize,
  wall-clock run, and run replay phase-B dispatch.
- Add a malformed-media fixture.
- Update contract docs and schema references.

### Out Of Scope

- Profile generation from a named seed.
- Open-ended fuzzing.
- Public-domain downloads or TTS.
- Performance-scale scenario packs.
- Network filesystem lag simulation.
- Duplicate/variant expansion scenarios.
- Corruption actions beyond container-header corruption.
- Corrupting sidecars.
- Making corruption part of any default first-pack scenario.
- Changing adapter matching semantics.

## Deferred Issues

The source spec allows Sprint 10 to split across multiple PRs. The following
requirements are intentionally deferred and tracked:

- #70 - Public-domain and TTS content source hooks.
- #71 - Larger performance profiles.
- #72 - Network filesystem lag profile.
- #73 - Duplicate and variant expansion pack.
- #74 - Fuzz and randomized profile generation with replay guarantees.
- #75 - Expanded corruption interceptor catalog.

## Architecture

Add a focused corruption lane beside the existing stdlib and media phase-B
dispatchers:

```text
src/chaos_librarian/
  contract/
    profiles.py          # shared profile/corruption enums and metadata models
    scenario.py          # + profiles, + corrupt_container_header event
    manifest.py          # ManifestVersion.corruption
    materialization.py   # CorruptionAction, MaterializationReport.corruption_actions
    reports.py           # AssetSnapshot.corruption

  engine/
    context.py            # EngineEventContext(resolved_seed)
    events.py            # plan-only handler allocates corrupted output version
    version_history.py   # includes corrupt_container_header as version-affecting

  materializer/
    actions.py           # _CORRUPTION_ACTIONS, SUPPORTED_S10_ACTIONS
    corruption.py        # deterministic byte overwrite + probe expectation
    run.py               # phase-B dispatch routes corruption actions
    wall_clock.py        # same dispatch route for run mode
    replay.py            # same dispatch route for run replay
    manifest_build.py    # stamps corrupted version hash/probe evidence

  validation/
    rules/profile_opt_in.py        # corruption requires explicit profile label
    rules/timeline_lifecycle.py    # corruption requires placed target
```

The engine remains pure and filesystem-free. It records intent and allocates
logical IDs. The materializer owns real bytes, hashes, probe attempts, and audit
records.

## Contract Changes

### Schema Versions

Implementation bumps these constants:

```python
SCENARIO_SCHEMA_VERSION: 6 -> 7
MANIFEST_SCHEMA_VERSION: 4 -> 5
MATERIALIZATION_SCHEMA_VERSION: 5 -> 6
ASSET_REPORT_SCHEMA_VERSION: 4 -> 5
```

`JournalEntry` stays at schema version `1`. The new action uses the existing
atomic journal shape and state-delta dictionary. `ReplayBundle` stays at schema
version `5`; corruption evidence is already captured through the scenario,
journal digest, manifests, materialization report, and deterministic file bytes.

### Profile Models

`contract/profiles.py` owns shared names:

```python
class ProfileName(enum.StrEnum):
    MALFORMED_MEDIA = "malformed-media"


class CorruptionProbeOutcome(enum.StrEnum):
    FAILED_EXPECTED = "failed_expected"
    STILL_PROBEABLE = "still_probeable"


class CorruptionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: ProfileName
    event_id: str
    corruptor: str
    byte_start: int
    byte_count: int
    seed_material: str
```

`CorruptionRecord` is shared by manifest and report models. Materialization adds
runtime-only fields such as hashes and probe outcome in `CorruptionAction`.

### Scenario

`Scenario` gains:

```python
profiles: tuple[ProfileName, ...] = Field(default_factory=tuple)
```

`TimelineActionName` gains:

```python
CORRUPT_CONTAINER_HEADER = "corrupt_container_header"
```

New event:

```python
class CorruptContainerHeaderEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.CORRUPT_CONTAINER_HEADER] = (
        TimelineActionName.CORRUPT_CONTAINER_HEADER
    )
    target: str
    bytes: int = Field(default=64, ge=1, le=4096)
```

The discriminated `TimelineEvent` union includes the new event.

### Manifest

`ManifestVersion` gains:

```python
corruption: CorruptionRecord | None = None
```

Plan-only runs set `corruption` on the output version with `content_hash=None`
and `probed=None`. Materialize and run fill `content_hash` after byte mutation.
When post-corruption probe fails, `probed` remains `None`; when probing still
succeeds, `probed` carries the returned `ProbedMedia`.

### Asset Reports

`AssetSnapshot` gains:

```python
corruption: CorruptionRecord | None = None
```

`engine/reports.py` copies snapshot evidence from the currently bound
`ManifestVersion`. Because the serialized `Manifest` carries every version and
does not carry `WorldState._asset_to_version`, `_snapshot_for` must resolve the
current version as the `ManifestVersion` for that asset with the greatest
`index`. It must not use the first version row for an asset. `_snapshot_for`
sets `content_hash`, `probed`, and `corruption` from that resolved version for
both `initial` and `current` snapshots. A model-only round-trip is not
sufficient; report-builder tests must prove the fields are emitted into
`reports/assets/<asset_id>.json`.

Materialize, wall-clock run, and run replay success finalizers rebuild
per-entity reports from the final augmented `manifest.current.json` before
writing `reports/`. They must not persist the plan-time `PlanArtifacts.reports`
after phase A or phase B has added `content_hash`, `probed`, or corruption
evidence. The persisted asset report for a corrupted asset must match
`manifest.current.json` for `current.content_hash`, `current.probed`, and
`current.corruption`.

`derive_version_history` treats `corrupt_container_header` as version-affecting.
Add `TimelineActionName.CORRUPT_CONTAINER_HEADER` to
`_VERSION_AFFECTING_ACTIONS` and add `_PRESERVED_DELTA_KEYS` for that action
with `profile`, `corruptor`, `byte_start`, `byte_count`, and `seed_material`.
The derived `VersionHistoryEntry` preserves the input/output version IDs and
copies only those corruption delta fields into `state_delta_summary`.

### Materialization Report

Add:

```python
class CorruptionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: Literal[TimelineActionName.CORRUPT_CONTAINER_HEADER]
    target_asset_id: str
    input_path: str
    output_path: str
    input_version_id: str | None = None
    output_version_id: str
    input_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    output_content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    corruptor: str
    byte_start: int
    byte_count: int
    seed_material: str
    probe_outcome: CorruptionProbeOutcome
    probe_error_tail: str | None = None
    duration_ns: int
```

`MaterializationReport` gains:

```python
corruption_actions: list[CorruptionAction] = Field(default_factory=list)
```

Add `FailureStage.CORRUPTION` and `Outcome.CORRUPTION_FAILED` for cases where
the corruptor cannot safely apply: missing file, file shorter than the requested
byte range, atomic write failure, hash failure, or unexpected internal errors.
`materializer/errors.py` adds `CorruptionActionError` with
`error_code="E_MATERIALIZE_CORRUPTION_FAILED"`. The public CLI shape does not
change: `materialize` and `run` still exit `5`, use the existing materialization
error envelope, and include `materialization_report_path` when a run directory
was allocated.

## Engine Semantics

Add a small engine event context so handlers can use deterministic run inputs
without expanding the positional handler signature for every future addition:

```python
@dataclass(frozen=True, slots=True)
class EngineEventContext:
    run_id: uuid.UUID
    scenario_id: str
    resolved_seed: int
```

The context replaces the current separate `run_id` and `scenario_id` handler
arguments; it does not add a new positional parameter. The public engine-internal
shape is:

```python
apply_event(state, resolved, ids, ctx)
_Handler = Callable[
    [WorldState, ResolvedEvent, IdAllocator, EngineEventContext],
    tuple[JournalEntry, ...],
]
```

`run_plan` constructs
`EngineEventContext(run_id=run_id, scenario_id=parsed.scenario_id, resolved_seed=resolved_seed)`
after seed and run ID resolution and passes it into `apply_event`.
`step_fixture` constructs the same context from `replay.json`, the parsed
scenario ID, and `bundle.resolved_seed`, then passes it into both step
advancement and `_recover_cursor` journal regeneration. `apply_event` passes the
same context to each handler. Direct event unit tests use an explicit fixed
context with a fixed UUID and scenario ID.

Plan replay, run replay, and step recovery all reuse the recorded concrete seed
from the bundle. They never resolve a fresh seed from the scenario literal, so
`seed: random` fixtures regenerate the same corruption `seed_material`.

`corrupt_container_header` is an atomic event. The handler:

1. Requires the target asset to have a current location and current version.
2. Allocates a new `version_id`.
3. Rebinds the asset to the new version without changing path or location ID.
4. Sets `ManifestVersion.corruption` using `ctx.resolved_seed`:
   - `profile="malformed-media"`
   - `event_id`
   - `corruptor="container_header_v1"`
   - `byte_start=0`
   - `byte_count=<event.bytes>`
   - `seed_material="container_header_v1:<resolved_seed>:<event_id>:<asset_id>"`
5. Emits an atomic journal entry with:
   - `target_ids=[asset_id]`
   - `input_version_ids=[old_version_id]`
   - `output_version_ids=[new_version_id]`
   - `state_delta` keys:
     `input_path`, `output_path`, `corruptor`, `byte_start`, `byte_count`,
     `seed_material`, and `profile`.

The output path is the same as the input path. This mirrors in-place media
mutations such as `edit_metadata`: logically new bytes, same visible file path.

## Materializer Semantics

`materializer/corruption.py` exposes `_CorruptionContext` and
`apply_corruption_action(ctx: _CorruptionContext, entry: JournalEntry) -> CorruptionAction`.
`_CorruptionContext` mirrors `_MediaContext`: it carries `library_root`,
`resolved_seed`, `post_phase_b_versions`, and any probe/capability state needed
by the helper. The dispatch state in materialize, wall-clock run, and run replay
also carries `corruption_actions: list[CorruptionAction]`.

The handler:

1. Reads `input_path` and `output_path` from `entry.state_delta`.
2. Hashes the input file.
3. Verifies the file is at least `byte_count` bytes long.
4. Reads the current bytes.
5. Replaces bytes `[0:byte_count]` with deterministic replacement bytes.
6. Writes through a sibling temp path and atomically replaces the output path.
7. Hashes the output file.
8. Attempts `probe_file(output_path)` after mutation.
9. Records `probe_outcome="failed_expected"` and `probe_error_tail` if probing
   raises `ProbeParseError`.
10. Records `probe_outcome="still_probeable"` and keeps the returned
    `ProbedMedia` if probing succeeds.
11. Stashes `(output_content_hash, probed_or_none)` for `augment_versions`.
12. Raises `CorruptionActionError` for missing input files, files shorter than
    `byte_count`, read failures, temp/write/replace failures, input/output hash
    failures, or unexpected internal errors.
13. Returns `CorruptionAction`.

The deterministic replacement bytes are generated by repeatedly hashing:

```text
sha256("container_header_v1:<resolved_seed>:<event_id>:<asset_id>:<block_index>")
```

until enough bytes are available. This is deterministic, platform-independent,
and does not introduce unrecorded random draws.

`materialize`, `run`, and run replay all route corruption actions through the
same helper. Batch materialize applies the action immediately in phase B. Wall
clock `run` applies it when the event becomes due, just like other atomic media
mutations.

Every successful corruption dispatch appends the returned `CorruptionAction` to
the active `corruption_actions` list. `build_report(...)`, success finalizers,
and phase-B failure finalizers accept and serialize that list. If a later phase-B
event fails, the failure report preserves corruption actions that completed
before the failing event.

`CorruptionActionError` is caught by the same phase-B finalization layer as
filesystem and media action errors, but maps to `Outcome.CORRUPTION_FAILED` and
`FailureStage.CORRUPTION`. Materialize, wall-clock run, and run replay use this
mapping consistently.

There is no no-probe success branch in Sprint 10. Missing or unusable `ffprobe`
is handled by the existing materializer capability gates before phase B, not by
`CorruptionProbeOutcome`.

Replay comparisons have two modes:

- Existing `replay --against` remains strict same-toolchain comparison. It
  compares full manifests, normalized journal/replay metadata, `library/` bytes,
  output hashes, and normalized `materialization.json` corruption audit
  evidence. The materialization normalizer compares `corruption_actions` fields
  `event_id`, `action`, `target_asset_id`, `input_path`, `output_path`,
  `input_version_id`, `output_version_id`, `input_content_hash`,
  `output_content_hash`, `corruptor`, `byte_start`, `byte_count`,
  `seed_material`, `probe_outcome`, and `probe_error_tail`. It ignores volatile
  fields such as `duration_ns`, run timestamps, platform/toolchain version
  strings, and wall-clock duration metadata.
- Cross-toolchain comparison is a separate corruption-evidence comparison used
  by tests and docs. It does not change `replay --against`. It compares
  canonicalized manifests plus deterministic `CorruptionAction` fields: event
  ID, target asset, output version ID, corruptor, byte range, and seed material.
  It records but does not fail on `probe_outcome`, `probe_error_tail`,
  `output_content_hash`, `duration_ns`, or `library/` byte differences because
  those values are descriptive across toolchains.

## Validation

Add `E_PROFILE_REQUIRED`:

- Fires when a timeline event with `action: corrupt_container_header` appears
  and `Scenario.profiles` does not include `"malformed-media"`.
- Severity is error; CLI exits `3`.
- Message should include the event ID and required profile.

Existing rules cover or are extended for:

- Unknown target: existing `E_TARGET_UNKNOWN`.
- Deleted target or pending slow copy: existing lifecycle invalid path, extended
  to include `corrupt_container_header`.
- Path containment: no new author-supplied path, because corruption uses the
  target's current path from the journal.

Materializer preflight switches from `SUPPORTED_S7_ACTIONS` to
`SUPPORTED_S10_ACTIONS` so valid corruption events are not rejected after
semantic validation passes.

## CLI And Fixture Behavior

The public CLI shape does not change.

Valid example:

```yaml
schema_version: 7
scenario_id: malformed-container-header
seed: 110
duration_scale: short
profiles:
  - malformed-media

library:
  roots:
    - id: movies_hd
      path: movies-hd

works:
  - id: work_broken
    title: Broken Header
    variants:
      - id: variant_hd
        label: hd
        bundle:
          id: bundle_hd
          assets:
            - id: asset_main
              role: primary_video
              container: mkv
              duration_seconds: 4
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - codec: aac
                  channels: stereo
                  language: eng

timeline:
  - id: corrupt_header_001
    at: 1s
    action: corrupt_container_header
    target: asset_main
    bytes: 64
```

This command exits `0`:

```bash
chaos-librarian materialize \
  tests/fixtures/scenarios/malformed-container-header.yaml \
  --out /tmp/malformed-run
```

It writes `materialization.json` with one `corruption_actions` entry and writes
`manifest.current.json` with a current version carrying corruption metadata.

The same scenario without `profiles: ["malformed-media"]` exits `3` during
validation and writes no run directory.

## Documentation

Update:

- `docs/specs/chaos-librarian-design.md` to mention that Sprint 10 foundation
  chose explicit corruption events and filed issues for the rest of the source
  spec's extended-profile list.
- `docs/contract/schema-reference.md` for the schema bumps.
- `docs/contract/fixture-layout.md` to note that corrupted fixtures remain
  normal run directories with labeled manifests/reports.
- `docs/contract/integration-recipes.md` with a short malformed-media recipe.

Do not add voom-v2-specific guidance. Consumers choose whether their exporter
records a failed probe, omits probe facts, or records only path/hash evidence.

## Testing

Contract tests:

- `Scenario` accepts `profiles=["malformed-media"]`.
- `Scenario` rejects unknown profile values.
- `CorruptContainerHeaderEvent` round-trips with default `bytes=64`.
- `CorruptContainerHeaderEvent` rejects `bytes=0` and `bytes=4097`.
- `CorruptionProbeOutcome` accepts only `FAILED_EXPECTED` and
  `STILL_PROBEABLE`.
- `CorruptionAction` rejects malformed `input_content_hash` and
  `output_content_hash` values that do not match `sha256:<64 lowercase hex>`.
- `ManifestVersion` round-trips corruption metadata.
- `AssetSnapshot` round-trips corruption metadata.
- `MaterializationReport` round-trips `corruption_actions`.
- Schema export includes the bumped versions and no drift.
- Asset report builder tests construct a current manifest with an initial
  version plus a corrupted output version and prove `current.version_id`,
  `current.content_hash`, `current.probed`, and `current.corruption` come from
  the greatest-index version, not the first version row.
- Asset report builder tests prove the asset `version_history` includes the
  corruption event and its preserved summary fields.

Validation tests:

- Corruption without `"malformed-media"` emits `E_PROFILE_REQUIRED`.
- Corruption with the profile passes validation.
- Corruption after `delete_file` emits lifecycle invalid.
- Corruption during a pending slow copy emits lifecycle invalid.
- Corruption targeting an unknown asset emits `E_TARGET_UNKNOWN`.

Engine tests:

- Plan-only corruption allocates a new version.
- Current location path does not change.
- Journal state delta contains the corruption metadata fields.
- Direct event tests pass `EngineEventContext(run_id=<fixed UUID>,
  scenario_id=<fixed id>, resolved_seed=42)`.
- `apply_event` and handler signatures stay within the project positional
  parameter limit after introducing `EngineEventContext`.
- A `seed: random` replay preserves the same `seed_material` because it uses the
  recorded resolved seed.
- A malformed-media fixture created with `plan --steps 0` and advanced with
  `step --next 1` produces the same corruption journal entry and `seed_material`
  as a full `run_plan`.
- A malformed-media fixture stepped once, persisted, and recovered regenerates
  the existing corruption journal entry byte-identically during cursor recovery.
- A `seed: random` malformed-media fixture stepped from `--steps 0` uses
  `bundle.resolved_seed`, not a newly resolved seed.
- `derive_version_history` includes `corrupt_container_header` with input/output
  version IDs and a `state_delta_summary` containing `profile`, `corruptor`,
  `byte_start`, `byte_count`, and `seed_material`.
- Same scenario and seed produce identical plan artifacts.

Materializer tests:

- Header corruptor changes bytes deterministically.
- Header corruptor does not change file length.
- Corruption action records input and output hashes.
- Expected post-corruption probe failure does not make the run fail.
- Probe success records `STILL_PROBEABLE`, stores probe facts, and succeeds.
- Actual corruptor application failure raises `CorruptionActionError`, writes
  `outcome="corruption_failed"` and `stage="corruption"`, and preserves prior
  phase-B audit records.
- Missing input files and files shorter than the requested `bytes` raise
  `CorruptionActionError`.
- Materialize writes manifest/report corruption metadata.
- Materialize writes exactly one `corruption_actions` record for the fixture.
- Materialize persists asset report JSON generated after manifest augmentation,
  so `reports/assets/<asset_id>.json` matches `manifest.current.json` for
  current hash, probe facts, corruption metadata, and corruption version history.

Wall-clock and replay tests:

- `run` applies corruption only when the event is due.
- `run` writes `corruption_actions` for due corruption events and omits future
  corruption events that were not reached before the duration ended.
- Wall-clock run persists asset report JSON generated after manifest
  augmentation for due corruption events.
- Same-toolchain run replay reproduces the same corrupted output hash and
  `probe_outcome`.
- Same-toolchain `replay --against` remains strict and catches manifest,
  normalized journal/replay metadata, `library/` bytes, output hash, and
  `probe_outcome` divergence.
- Same-toolchain `replay --against` reports divergence when only
  `materialization.json.corruption_actions` deterministic audit fields differ,
  including `probe_outcome`, `input_content_hash`, or `output_content_hash`.
- Same-toolchain `replay --against` ignores volatile materialization fields such
  as `duration_ns` so replay does not fail solely due to timing drift.
- Run replay persists asset report JSON generated after manifest augmentation.
- Cross-toolchain corruption-evidence comparison uses canonicalized manifests
  plus deterministic `CorruptionAction` evidence, excluding `probe_outcome`,
  `probe_error_tail`, `output_content_hash`, `duration_ns`, and `library/`
  bytes.
- Cross-toolchain replay tolerates diagnostic probe-outcome drift, including
  `failed_expected` versus `still_probeable`.
- Run replay writes all corruption action evidence fields, including diagnostic
  `probe_outcome`.
- Wall-clock run and run replay map corruption action failures to
  `outcome="corruption_failed"` and `stage="corruption"`.
- Journal digest remains stable after stripping wall-clock fields.

CLI tests:

- Valid malformed-media materialize exits `0`.
- Missing profile exits `3` and creates no run directory.
- Corruption application failure exits `5` with
  `error_code="E_MATERIALIZE_CORRUPTION_FAILED"` and
  `materialization_report_path` in the existing error envelope.
- Missing-file and short-file corruption failures exit `5`, emit
  `E_MATERIALIZE_CORRUPTION_FAILED`, include `materialization_report_path`, and
  write `outcome="corruption_failed"` with `stage="corruption"`.

## Risks And Mitigations

- **Accidental corruption in ordinary fixtures.** The explicit `profiles` gate
  makes corruption impossible in scenarios that are not labeled.

- **Probe behavior varies by container/tool version.** Probe outcome is recorded
  evidence, not the materialize success criterion. This preserves the existing
  materialize/run rule that hashes and probe facts are descriptive across
  toolchains.

- **Hidden randomness.** The corruptor uses deterministic hash expansion, not a
  materializer-local RNG draw.

- **Schema churn.** The sprint bumps only schemas that expose new data. There is
  no standalone profile schema and no generator contract.

- **Adapter confusion.** Corruption is labeled in manifests and reports. The
  adapter remains consumer-neutral and does not infer application policy from
  malformed media.

## Alternatives Rejected

1. **Profile generator.** A generator could emit many scenarios quickly, but it
   would hide mutation choices behind a new expansion layer. That conflicts with
   the existing explicit timeline model and belongs with issue #74.

2. **Malformed subtitle-only profile.** Smaller, but it would not establish the
   corruption interceptor lane the source spec calls for.

3. **Treat post-corruption probe failure as `media_failed`.** That would make
   successful malformed-media fixtures look like materializer failures. The
   profile's purpose is to produce bad media intentionally.

4. **No scenario profile marker.** A new action alone is explicit, but a profile
   marker gives CI and humans a simple way to include or exclude extended
   profile scenarios.

5. **Corrupt sidecars in Sprint 10.** Sidecar corruption has different consumer
   expectations and can land with the broader corruption catalog in issue #75.
