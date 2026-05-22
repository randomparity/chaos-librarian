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
- A malformed-media fixture materializes successfully even when post-corruption
  `ffprobe` fails.
- Replay reproduces the same corrupted bytes for the same scenario, seed, and
  event.
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

7. **Probe failure is expected success.** The corruption handler attempts
   `ffprobe` after mutation. A parse/subprocess failure is recorded as the
   expected malformed-media outcome and does not change the run outcome to
   `media_failed`. If `ffprobe` still succeeds, materialize fails with a
   corruption error because the first profile did not produce malformed media.

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
    NOT_RUN = "not_run"


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
When post-corruption probe fails as expected, `probed` remains `None`.

### Asset Reports

`AssetSnapshot` gains:

```python
corruption: CorruptionRecord | None = None
```

`VersionHistoryEntry` already carries version-affecting actions through
`state_delta_summary`; `corrupt_container_header` joins that derived history.

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
    input_content_hash: str
    output_content_hash: str
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
the corruptor cannot safely apply or where the output remains probeable.

## Engine Semantics

`corrupt_container_header` is an atomic event. The handler:

1. Requires the target asset to have a current location and current version.
2. Allocates a new `version_id`.
3. Rebinds the asset to the new version without changing path or location ID.
4. Sets `ManifestVersion.corruption` with:
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

`materializer/corruption.py` exposes
`apply_corruption_action(ctx: _CorruptionContext, entry: JournalEntry) -> CorruptionAction`.

The handler:

1. Reads `input_path` and `output_path` from `entry.state_delta`.
2. Hashes the input file.
3. Verifies the file is at least `byte_count` bytes long.
4. Reads the current bytes.
5. Replaces bytes `[0:byte_count]` with deterministic replacement bytes.
6. Writes through a sibling temp path and atomically replaces the output path.
7. Hashes the output file.
8. Attempts `probe_file(output_path)`.
9. Treats `ProbeParseError` as expected and records
   `probe_outcome="failed_expected"`.
10. Fails with `Outcome.CORRUPTION_FAILED` if probing still succeeds.
11. Stashes `(output_content_hash, None)` for `augment_versions`.
12. Returns `CorruptionAction`.

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
- `ManifestVersion` round-trips corruption metadata.
- `AssetSnapshot` round-trips corruption metadata.
- `MaterializationReport` round-trips `corruption_actions`.
- Schema export includes the bumped versions and no drift.

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
- Same scenario and seed produce identical plan artifacts.

Materializer tests:

- Header corruptor changes bytes deterministically.
- Header corruptor does not change file length.
- Corruption action records input and output hashes.
- Expected post-corruption probe failure does not make the run fail.
- Probe success after corruption is treated as `CORRUPTION_FAILED`.
- Materialize writes manifest/report corruption metadata.

Wall-clock and replay tests:

- `run` applies corruption only when the event is due.
- Completed run replay reproduces the same corrupted output hash.
- Journal digest remains stable after stripping wall-clock fields.

CLI tests:

- Valid malformed-media materialize exits `0`.
- Missing profile exits `3` and creates no run directory.
- Corruption application failure exits `5` with the existing error envelope.

## Risks And Mitigations

- **Accidental corruption in ordinary fixtures.** The explicit `profiles` gate
  makes corruption impossible in scenarios that are not labeled.

- **Probe behavior varies by container/tool version.** The first fixture uses a
  short MKV synthesized by the existing pipeline. Tests assert that the chosen
  byte range produces an expected probe failure on the supported toolchain.

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
