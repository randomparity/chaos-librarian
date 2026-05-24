# Issue 75 Corruption Interceptor Catalog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the opt-in interceptor catalog requested by GitHub issue #75:
file truncation, packet-range corruption, invalid duration metadata, mtime-only
changes, and intentionally wrong oracle hashes, while documenting the already
implemented held-handle and delayed-commit primitives.

**Architecture:** Keep author-facing behavior explicit: each new behavior is a
timeline action gated by a profile label. Reuse the existing phase-B dispatcher
shape, but split byte transforms and evidence helpers so
`materializer/phase_b/corruption.py` stays a dispatcher instead of becoming a
large mixed-purpose file. Preserve the existing adapter behavior for negative
oracle hashes: the built-in compare command should still report a hash mismatch;
the new audit record explains that the mismatch was intentional.

**Tech Stack:** Python 3.13, Pydantic v2, Typer, pytest, ruff, ty, existing
ffmpeg/ffprobe tooling. No new dependencies.

---

## Source Inputs

**GitHub issue:** [#75](https://github.com/randomparity/chaos-librarian/issues/75)

**Issue request:** Sprint 10 shipped one malformed-media corruptor and deferred
the broader interceptor catalog: truncation, packet-range corruption, invalid
duration metadata, held-open files, mtime-only changes, delayed commits, and
intentionally wrong oracle hashes as explicit opt-in behaviors with replay
evidence.

**Design pointer:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md)
near the "Mutation Pipeline" future interceptor list.

**Current-state finding:** `main` already contains the Sprint 10
`corrupt_container_header` implementation and the issue #72 network-lag
implementation. Do not add duplicate held-open or delayed-commit actions.
Document and fixture these existing entries as part of the catalog instead.

**Execution branch:** Create or switch to `feat/gh-issue-75` before editing
code. Do not implement on `main` or `master`.

## Design Decisions Baked Into This Plan

1. Keep `corrupt_container_header`; add sibling explicit actions instead of
   replacing the scenario contract with a generic `interceptor` action.
2. `malformed-media` gates byte/media corruption actions:
   `corrupt_container_header`, `truncate_file`, `corrupt_packet_range`, and
   `write_invalid_duration_metadata`.
3. Add `filesystem-artifacts` for `touch_mtime`; mtime-only changes are watcher
   artifacts, not malformed media.
4. Add `negative-oracle` for `wrong_oracle_hash`; it deliberately falsifies
   manifest `content_hash` and must never be hidden by adapter comparison.
5. Held-open files and delayed commits stay under existing `network-fs-lag`:
   `network_lag_start.effect=held_handle`,
   `network_lag_start.effect=delayed_visibility`, and
   `network_lag_start.effect=delayed_rename`.
6. `write_invalid_duration_metadata` is a metadata-tag corruption. It writes an
   invalid `duration` tag through ffmpeg copy/remux and records whether ffprobe
   still reports a duration. It does not promise a container-internal duration
   atom edit across every muxer.
7. `corrupt_packet_range` uses ffprobe packet positions. If ffprobe returns no
   packet `pos`/`size` evidence for the requested stream and packet range, phase
   B fails with `E_MATERIALIZE_CORRUPTION_FAILED` rather than guessing bytes.
8. `wrong_oracle_hash` allocates a new manifest version with unchanged file
   bytes. Phase B stamps a deterministic false `content_hash` on that version
   and records both actual and reported hashes in `oracle_hash_actions`.
9. Schema-version bumps:
   - `SCENARIO_SCHEMA_VERSION`: 8 -> 9
   - `MANIFEST_SCHEMA_VERSION`: 5 -> 6
   - `ASSET_REPORT_SCHEMA_VERSION`: 5 -> 6
   - `MATERIALIZATION_SCHEMA_VERSION`: 8 -> 9
   - No journal schema bump; new actions fit the existing atomic entry shape.
   - No replay-bundle schema bump; replay evidence is already carried by the
     embedded scenario, journal digest, manifest, and materialization report.

## File Structure

### Create

```text
src/chaos_librarian/materializer/phase_b/corruption_bytes.py
  Pure byte transforms: replacement bytes, hash bytes, truncate, overwrite range.

src/chaos_librarian/materializer/phase_b/packet_probe.py
  ffprobe packet range resolver used only by corrupt_packet_range.

src/chaos_librarian/materializer/phase_b/oracle_hash.py
  Deterministic false-hash generation and phase-B wrong-oracle action helper.

tests/materializer/test_packet_probe.py
tests/materializer/test_oracle_hash.py

tests/fixtures/scenarios/interceptor-catalog.yaml
tests/fixtures/scenarios/interceptor-catalog-run.yaml
tests/fixtures/scenarios/negative-oracle-hash.yaml
tests/fixtures/scenarios/invalid/truncate-file-missing-profile.yaml
tests/fixtures/scenarios/invalid/touch-mtime-missing-profile.yaml
tests/fixtures/scenarios/invalid/wrong-oracle-hash-missing-profile.yaml
```

### Modify

```text
src/chaos_librarian/contract/__init__.py
src/chaos_librarian/contract/profiles.py
src/chaos_librarian/contract/scenario.py
src/chaos_librarian/contract/manifest.py
src/chaos_librarian/contract/reports.py
src/chaos_librarian/contract/materialization.py
src/chaos_librarian/contract/canonicalize.py

src/chaos_librarian/engine/events.py
src/chaos_librarian/engine/version_history.py

src/chaos_librarian/materializer/actions.py
src/chaos_librarian/materializer/preflight.py
src/chaos_librarian/materializer/manifest_build.py
src/chaos_librarian/materializer/run.py
src/chaos_librarian/materializer/phase_b/__init__.py
src/chaos_librarian/materializer/phase_b/corruption.py
src/chaos_librarian/materializer/wall_clock.py
src/chaos_librarian/materializer/replay.py
src/chaos_librarian/materializer/persistence/finalize.py
src/chaos_librarian/materializer/persistence/reports.py

src/chaos_librarian/validation/rules/profile_opt_in.py
src/chaos_librarian/validation/rules/timeline_lifecycle.py

tests/contract/test_contract_constants.py
tests/contract/test_scenario.py
tests/contract/test_manifest.py
tests/contract/test_reports.py
tests/contract/test_materialization.py
tests/engine/test_events_media.py
tests/materializer/test_actions.py
tests/materializer/test_corruption.py
tests/materializer/test_preflight.py
tests/materializer/test_phase_b.py
tests/materializer/test_run_sprint10.py
tests/materializer/test_replay.py
tests/materializer/test_wall_clock.py
tests/validation/rules/test_profile_opt_in.py
tests/validation/rules/test_timeline_lifecycle.py
tests/integration/test_materialize_sprint10_real.py
tests/adapter/test_compare_final_state.py

schemas/*.schema.json
docs/specs/chaos-librarian-design.md
docs/contract/schema-reference.md
docs/contract/integration-recipes.md
```

## Task 1: Contract Models And Schema Bumps

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/profiles.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/contract/manifest.py`
- Modify: `src/chaos_librarian/contract/reports.py`
- Modify: `src/chaos_librarian/contract/materialization.py`
- Modify: `tests/contract/test_contract_constants.py`
- Modify: `tests/contract/test_scenario.py`
- Modify: `tests/contract/test_manifest.py`
- Modify: `tests/contract/test_reports.py`
- Modify: `tests/contract/test_materialization.py`

- [ ] **Step 1: Write failing schema-version tests**

Update the constants tests to expect:

```python
def test_scenario_schema_version_bumped_to_9():
    assert SCENARIO_SCHEMA_VERSION == 9


def test_manifest_schema_version_bumped_to_6():
    assert MANIFEST_SCHEMA_VERSION == 6


def test_asset_report_schema_version_bumped_to_6():
    assert ASSET_REPORT_SCHEMA_VERSION == 6


def test_materialization_schema_version_bumped_to_9():
    assert MATERIALIZATION_SCHEMA_VERSION == 9
```

Run:

```bash
uv run pytest tests/contract/test_contract_constants.py -q
```

Expected: fails on the four old version constants.

- [ ] **Step 2: Write failing scenario contract tests**

Add tests that validate these payloads at `schema_version: 9`:

```python
{
    "id": "truncate_001",
    "at": "1s",
    "action": "truncate_file",
    "target": "a1",
    "keep_bytes": 64,
}
{
    "id": "packet_corrupt_001",
    "at": "2s",
    "action": "corrupt_packet_range",
    "target": "a1",
    "stream": "video",
    "packet_start": 0,
    "packet_count": 2,
}
{
    "id": "duration_bad_001",
    "at": "3s",
    "action": "write_invalid_duration_metadata",
    "target": "a1",
    "value": "not-a-duration",
}
{
    "id": "mtime_001",
    "at": "4s",
    "action": "touch_mtime",
    "target": "a1",
    "offset": "2s",
}
{
    "id": "wrong_hash_001",
    "at": "5s",
    "action": "wrong_oracle_hash",
    "target": "a1",
}
```

Also add negative tests:

```python
truncate_file keep_bytes=0 -> ValidationError
corrupt_packet_range packet_start=-1 -> ValidationError
corrupt_packet_range packet_count=0 -> ValidationError
touch_mtime offset="" -> ValidationError
wrong_oracle_hash with unexpected field "bytes" -> ValidationError
```

Run:

```bash
uv run pytest tests/contract/test_scenario.py -q
```

Expected: fails because the new actions and profiles are undefined.

- [ ] **Step 3: Write failing materialization contract tests**

Add tests for:

```python
FilesystemAction(
    event_id="mtime_001",
    action=TimelineActionName.TOUCH_MTIME,
    target_asset_id="asset_main",
    from_path="movies-hd/asset_main.mkv",
    to_path="movies-hd/asset_main.mkv",
    temp_path=None,
    content_hash="sha256:" + "0" * 64,
    mtime_before_ns=1_000_000_000,
    mtime_after_ns=3_000_000_000,
    duration_ns=10,
)
```

and:

```python
OracleHashAction(
    event_id="wrong_hash_001",
    action=TimelineActionName.WRONG_ORACLE_HASH,
    target_asset_id="asset_main",
    input_path="movies-hd/asset_main.mkv",
    output_path="movies-hd/asset_main.mkv",
    input_version_id="version_0001",
    output_version_id="version_0002",
    actual_content_hash="sha256:" + "1" * 64,
    reported_content_hash="sha256:" + "2" * 64,
    seed_material="wrong_oracle_hash_v1:42:wrong_hash_001:asset_main",
    duration_ns=10,
)
```

Extend `CorruptionAction` round-trip coverage for:

```python
action="truncate_file"
corruptor="truncate_file_v1"
input_size_bytes=128
output_size_bytes=64
byte_start=64
byte_count=64
```

and:

```python
action="corrupt_packet_range"
corruptor="packet_range_v1"
stream="video"
packet_start=0
packet_count=2
byte_start=4096
byte_count=2048
```

Run:

```bash
uv run pytest tests/contract/test_materialization.py -q
```

Expected: fails because action enums, optional mtime fields,
`OracleHashAction`, and expanded `CorruptionAction` are missing.

- [ ] **Step 4: Implement contract updates**

Update `ProfileName`:

```python
FILESYSTEM_ARTIFACTS = "filesystem-artifacts"
NEGATIVE_ORACLE = "negative-oracle"
```

Update `TimelineActionName`:

```python
TRUNCATE_FILE = "truncate_file"
CORRUPT_PACKET_RANGE = "corrupt_packet_range"
WRITE_INVALID_DURATION_METADATA = "write_invalid_duration_metadata"
TOUCH_MTIME = "touch_mtime"
WRONG_ORACLE_HASH = "wrong_oracle_hash"
```

Add a scenario enum:

```python
class PacketStreamKind(enum.StrEnum):
    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"
```

Add frozen event models with `extra="forbid"` through `_TimelineEventBase`:

```python
class TruncateFileEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.TRUNCATE_FILE] = TimelineActionName.TRUNCATE_FILE
    target: str
    keep_bytes: int = Field(ge=1)


class CorruptPacketRangeEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.CORRUPT_PACKET_RANGE] = (
        TimelineActionName.CORRUPT_PACKET_RANGE
    )
    target: str
    stream: PacketStreamKind = PacketStreamKind.VIDEO
    packet_start: int = Field(ge=0)
    packet_count: int = Field(default=1, ge=1, le=128)


class WriteInvalidDurationMetadataEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.WRITE_INVALID_DURATION_METADATA] = (
        TimelineActionName.WRITE_INVALID_DURATION_METADATA
    )
    target: str
    value: str = Field(default="not-a-duration", min_length=1, max_length=128)


class TouchMtimeEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.TOUCH_MTIME] = TimelineActionName.TOUCH_MTIME
    target: str
    offset: str = Field(min_length=1)


class WrongOracleHashEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.WRONG_ORACLE_HASH] = TimelineActionName.WRONG_ORACLE_HASH
    target: str
```

Update `Scenario.schema_version` to `Literal[9]` and add the five event models
to `TimelineEvent`.

Update `CorruptionRecord` so plan-only manifests can represent both concrete
byte ranges and materializer-resolved ranges:

```python
profile: ProfileName
event_id: str
corruptor: str
byte_start: int | None = None
byte_count: int | None = None
seed_material: str | None = None
stream: str | None = None
packet_start: int | None = None
packet_count: int | None = None
metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
```

Update `CorruptionAction` with the same optional range fields plus:

```python
action: Literal[
    TimelineActionName.CORRUPT_CONTAINER_HEADER,
    TimelineActionName.TRUNCATE_FILE,
    TimelineActionName.CORRUPT_PACKET_RANGE,
    TimelineActionName.WRITE_INVALID_DURATION_METADATA,
]
input_size_bytes: int
output_size_bytes: int
stream: str | None = None
packet_start: int | None = None
packet_count: int | None = None
metadata: dict[str, str | int | float | bool] = Field(default_factory=dict)
```

Extend `FilesystemAction`:

```python
content_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
mtime_before_ns: int | None = None
mtime_after_ns: int | None = None
```

Add `OracleHashAction` and `MaterializationReport.oracle_hash_actions`.

- [ ] **Step 5: Run contract tests**

Run:

```bash
uv run pytest tests/contract/test_contract_constants.py tests/contract/test_scenario.py tests/contract/test_manifest.py tests/contract/test_reports.py tests/contract/test_materialization.py -q
```

Expected: pass before moving to engine work.

- [ ] **Step 6: Commit contract changes**

```bash
git add src/chaos_librarian/contract tests/contract
git commit -m "feat: add interceptor catalog contracts"
```

## Task 2: Validation Rules And Invalid Corpus

**Files:**
- Modify: `src/chaos_librarian/validation/rules/profile_opt_in.py`
- Modify: `src/chaos_librarian/validation/rules/timeline_lifecycle.py`
- Modify: `tests/validation/rules/test_profile_opt_in.py`
- Modify: `tests/validation/rules/test_timeline_lifecycle.py`
- Create: `tests/fixtures/scenarios/invalid/truncate-file-missing-profile.yaml`
- Create: `tests/fixtures/scenarios/invalid/touch-mtime-missing-profile.yaml`
- Create: `tests/fixtures/scenarios/invalid/wrong-oracle-hash-missing-profile.yaml`

- [ ] **Step 1: Add profile opt-in tests**

Add cases asserting:

```python
truncate_file without malformed-media -> E_PROFILE_REQUIRED
corrupt_packet_range without malformed-media -> E_PROFILE_REQUIRED
write_invalid_duration_metadata without malformed-media -> E_PROFILE_REQUIRED
touch_mtime without filesystem-artifacts -> E_PROFILE_REQUIRED
wrong_oracle_hash without negative-oracle -> E_PROFILE_REQUIRED
```

Add matching positive cases with the required profile present.

Run:

```bash
uv run pytest tests/validation/rules/test_profile_opt_in.py -q
```

Expected: fails until the rule maps the new actions.

- [ ] **Step 2: Add lifecycle tests**

Add lifecycle tests proving all new target-dependent actions reject an unplaced
asset after `delete_file`, and that these actions reject while a slow copy is
pending:

```python
truncate_file
corrupt_packet_range
write_invalid_duration_metadata
touch_mtime
wrong_oracle_hash
```

`touch_mtime` and `wrong_oracle_hash` should be pending-slow-copy forbidden
because the materializer reads the target path at phase B.

Run:

```bash
uv run pytest tests/validation/rules/test_timeline_lifecycle.py -q
```

Expected: fails until lifecycle sets include the new actions.

- [ ] **Step 3: Implement profile and lifecycle rules**

In `profile_opt_in.py`, replace the current branch-specific conditionals with
a mapping so the rule stays flat as catalog entries grow:

```python
_REQUIRED_PROFILES_BY_ACTION: Final[dict[str, str]] = {
    TimelineActionName.CORRUPT_CONTAINER_HEADER.value: ProfileName.MALFORMED_MEDIA.value,
    TimelineActionName.TRUNCATE_FILE.value: ProfileName.MALFORMED_MEDIA.value,
    TimelineActionName.CORRUPT_PACKET_RANGE.value: ProfileName.MALFORMED_MEDIA.value,
    TimelineActionName.WRITE_INVALID_DURATION_METADATA.value: ProfileName.MALFORMED_MEDIA.value,
    TimelineActionName.TOUCH_MTIME.value: ProfileName.FILESYSTEM_ARTIFACTS.value,
    TimelineActionName.WRONG_ORACLE_HASH.value: ProfileName.NEGATIVE_ORACLE.value,
    TimelineActionName.NETWORK_LAG_START.value: ProfileName.NETWORK_FS_LAG.value,
    TimelineActionName.NETWORK_LAG_COMMIT.value: ProfileName.NETWORK_FS_LAG.value,
}
```

In `timeline_lifecycle.py`, add the five new actions to
`_LOCATION_DEPENDENT_PASSTHROUGH` and `_PATH_MUTATING_PASSTHROUGH`.

- [ ] **Step 4: Add invalid corpus fixtures**

Each invalid fixture must start with the expected marker:

```yaml
# expected: E_PROFILE_REQUIRED
```

Use otherwise valid minimal scenarios with one missing-profile event:

```yaml
action: truncate_file
keep_bytes: 64
```

```yaml
action: touch_mtime
offset: 2s
```

```yaml
action: wrong_oracle_hash
```

- [ ] **Step 5: Run validation tests**

```bash
uv run pytest tests/validation/rules/test_profile_opt_in.py tests/validation/rules/test_timeline_lifecycle.py tests/validation/test_invalid_corpus.py -q
```

Expected: pass.

- [ ] **Step 6: Commit validation changes**

```bash
git add src/chaos_librarian/validation tests/validation tests/fixtures/scenarios/invalid
git commit -m "feat: validate interceptor profile gates"
```

## Task 3: Engine Journal And Version History

**Files:**
- Modify: `src/chaos_librarian/engine/events.py`
- Modify: `src/chaos_librarian/engine/version_history.py`
- Modify: `tests/engine/test_events_media.py`

- [ ] **Step 1: Add failing engine tests**

Add tests that each action emits an atomic journal entry with deterministic
state delta.

Expected deltas:

```python
truncate_file:
{
    "input_path": "movies-hd/a0.mkv",
    "output_path": "movies-hd/a0.mkv",
    "profile": "malformed-media",
    "corruptor": "truncate_file_v1",
    "keep_bytes": 64,
    "seed_material": "truncate_file_v1:42:truncate_001:a0",
}
```

```python
corrupt_packet_range:
{
    "input_path": "movies-hd/a0.mkv",
    "output_path": "movies-hd/a0.mkv",
    "profile": "malformed-media",
    "corruptor": "packet_range_v1",
    "stream": "video",
    "packet_start": 0,
    "packet_count": 2,
    "seed_material": "packet_range_v1:42:packet_corrupt_001:a0",
}
```

```python
write_invalid_duration_metadata:
{
    "input_path": "movies-hd/a0.mkv",
    "output_path": "movies-hd/a0.mkv",
    "profile": "malformed-media",
    "corruptor": "invalid_duration_metadata_v1",
    "value": "not-a-duration",
    "seed_material": "invalid_duration_metadata_v1:42:duration_bad_001:a0",
}
```

```python
touch_mtime:
{
    "path": "movies-hd/a0.mkv",
    "profile": "filesystem-artifacts",
    "offset": "2s",
}
```

```python
wrong_oracle_hash:
{
    "input_path": "movies-hd/a0.mkv",
    "output_path": "movies-hd/a0.mkv",
    "profile": "negative-oracle",
    "algorithm": "sha256",
    "seed_material": "wrong_oracle_hash_v1:42:wrong_hash_001:a0",
}
```

Assert version allocation:

```python
truncate_file -> new version with CorruptionRecord(corruptor="truncate_file_v1")
corrupt_packet_range -> new version with CorruptionRecord(corruptor="packet_range_v1")
write_invalid_duration_metadata -> new version with CorruptionRecord(...)
wrong_oracle_hash -> new version with no CorruptionRecord
touch_mtime -> no new version
```

Run:

```bash
uv run pytest tests/engine/test_events_media.py -q
```

Expected: fails until handlers exist.

- [ ] **Step 2: Implement state-delta contract keys**

Add entries to `_STATE_DELTA_KEYS` for the five new actions. Keep the keys
identical to the expected deltas above so the parametrized state-delta contract
test fails if a future edit silently drops evidence.

- [ ] **Step 3: Implement engine handlers**

Add small helpers:

```python
def _seed_material(corruptor: str, ctx: EngineEventContext, event_id: str, target: str) -> str:
    return f"{corruptor}:{ctx.resolved_seed}:{event_id}:{target}"
```

```python
def _bind_corruption_version(
    state: WorldState,
    ids: IdAllocator,
    *,
    target: str,
    record: CorruptionRecord,
) -> tuple[str, str]:
    prior_version_id = state.version_id_for_asset(target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    state.bind_version(
        target,
        ManifestVersion(
            id=new_version_id,
            asset_id=target,
            index=prior_version.index + 1,
            corruption=record,
        ),
    )
    return prior_version_id, new_version_id
```

Implement handlers:

```python
_handle_truncate_file
_handle_corrupt_packet_range
_handle_write_invalid_duration_metadata
_handle_touch_mtime
_handle_wrong_oracle_hash
```

Register them in `_HANDLERS`.

- [ ] **Step 4: Update version history**

Add version-affecting actions:

```python
TRUNCATE_FILE
CORRUPT_PACKET_RANGE
WRITE_INVALID_DURATION_METADATA
WRONG_ORACLE_HASH
```

Preserve these delta keys:

```python
truncate_file: profile, corruptor, keep_bytes, seed_material
corrupt_packet_range: profile, corruptor, stream, packet_start, packet_count, seed_material
write_invalid_duration_metadata: profile, corruptor, value, seed_material
wrong_oracle_hash: profile, algorithm, seed_material
```

Do not add `touch_mtime` to version history.

- [ ] **Step 5: Run engine tests**

```bash
uv run pytest tests/engine/test_events_media.py tests/engine/test_version_history.py -q
```

Expected: pass.

- [ ] **Step 6: Commit engine changes**

```bash
git add src/chaos_librarian/engine tests/engine
git commit -m "feat: emit interceptor journal evidence"
```

## Task 4: Phase-B Corruption Handlers

**Files:**
- Create: `src/chaos_librarian/materializer/phase_b/corruption_bytes.py`
- Create: `src/chaos_librarian/materializer/phase_b/packet_probe.py`
- Modify: `src/chaos_librarian/materializer/phase_b/corruption.py`
- Modify: `src/chaos_librarian/materializer/phase_b/__init__.py`
- Modify: `src/chaos_librarian/materializer/actions.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Modify: `tests/materializer/test_actions.py`
- Modify: `tests/materializer/test_corruption.py`
- Modify: `tests/materializer/test_preflight.py`
- Create: `tests/materializer/test_packet_probe.py`

- [ ] **Step 1: Extract byte helpers with existing tests still green**

Move these pure helpers from `corruption.py` to `corruption_bytes.py`:

```python
replacement_bytes(seed_material: str, byte_count: int) -> bytes
hash_bytes(data: bytes) -> str
hash_file(path: Path) -> str
temp_sibling(output_path: Path, resolved_seed: int) -> Path
overwrite_range(data: bytes, *, byte_start: int, byte_count: int, seed_material: str) -> bytes
truncate_bytes(data: bytes, *, keep_bytes: int) -> bytes
```

Add tests:

```python
overwrite_range preserves length and only changes requested slice
truncate_bytes rejects keep_bytes >= len(data)
truncate_bytes returns exactly keep_bytes bytes
```

Run:

```bash
uv run pytest tests/materializer/test_corruption.py -q
```

Expected: pass before adding new behavior.

- [ ] **Step 2: Add packet probe tests**

In `test_packet_probe.py`, monkeypatch the subprocess runner used by the helper
and cover:

```python
video packets with pos/size resolve byte_start and byte_count
audio stream selection uses "a:0"
missing packet pos raises CorruptionActionError-compatible ValueError
requested packet range past available packets raises ValueError
```

The helper API should be:

```python
resolve_packet_byte_range(
    path: Path,
    *,
    stream: str,
    packet_start: int,
    packet_count: int,
) -> tuple[int, int]
```

Run:

```bash
uv run pytest tests/materializer/test_packet_probe.py -q
```

Expected: fails until helper exists.

- [ ] **Step 3: Implement packet probe helper**

Use ffprobe JSON:

```bash
ffprobe -v error -select_streams v:0 -show_packets \
  -show_entries packet=pos,size -of json <path>
```

Map stream values:

```python
video -> v:0
audio -> a:0
subtitle -> s:0
```

Parse only packets where both `pos` and `size` are decimal integers. For a
range, return:

```python
byte_start = first_packet_pos
byte_count = (last_packet_pos + last_packet_size) - first_packet_pos
```

Do not guess if packets are missing usable positions.

- [ ] **Step 4: Add failing corruption handler tests**

Extend `test_corruption.py` with:

```python
test_truncate_file_shortens_bytes_and_records_hashes
test_truncate_file_rejects_keep_bytes_equal_to_size
test_packet_range_corruption_uses_resolved_packet_range
test_packet_range_corruption_records_packet_evidence
test_invalid_duration_metadata_invokes_ffmpeg_copy_with_duration_tag
test_invalid_duration_metadata_records_probe_duration_before_and_after
```

Monkeypatch `probe_file`, `run_ffmpeg`, and `resolve_packet_byte_range`; do not
require real ffmpeg in these unit tests.

- [ ] **Step 5: Implement corruption dispatcher**

Expand `CorruptionPhaseBContext`:

```python
ffmpeg_version: str
invocations: list[ToolInvocation]
post_phase_b_versions: dict[str, tuple[str, ProbedMedia | None]]
```

Update `make_corruption_phase_b_context` and
`make_phase_b_state` to pass `ffmpeg_version` and `invocations`.

Implement a dispatcher table:

```python
_HANDLERS: Final[dict[TimelineActionName, _Handler]] = {
    TimelineActionName.CORRUPT_CONTAINER_HEADER: _apply_corrupt_container_header,
    TimelineActionName.TRUNCATE_FILE: _apply_truncate_file,
    TimelineActionName.CORRUPT_PACKET_RANGE: _apply_corrupt_packet_range,
    TimelineActionName.WRITE_INVALID_DURATION_METADATA: _apply_invalid_duration_metadata,
}
```

Each handler must:

1. Read `input_path` from `entry.state_delta`.
2. Write to a temp sibling.
3. Atomically `replace` the final path.
4. Compute actual input/output hashes and sizes.
5. Probe output using existing `_probe_corrupted_output`.
6. Stamp `ctx.post_phase_b_versions[output_version_id]`.
7. Return a `CorruptionAction` with replay evidence.

`write_invalid_duration_metadata` should run:

```bash
ffmpeg -hide_banner -y -i <input> -map 0 -c copy \
  -metadata duration=<value> <temp_output>
```

Append the invocation to `ctx.invocations`; on non-zero exit, raise
`CorruptionActionError` with the stderr tail.

- [ ] **Step 6: Wire supported action sets**

Add the three new malformed-media actions to:

```python
_CORRUPTION_ACTIONS
SUPPORTED_S10_ACTIONS
supports_corruption_action
```

Update `test_actions.py` so the action-set ownership tests expect the expanded
corruption-action set and `SUPPORTED_S10_ACTIONS` partition.

Add a preflight test proving `preflight_timeline` accepts
`truncate_file`, `corrupt_packet_range`, and
`write_invalid_duration_metadata`. Without this, the handlers can exist but
`materialize` and `run` will still reject the scenario before phase B.

Run:

```bash
uv run pytest tests/materializer/test_actions.py tests/materializer/test_corruption.py tests/materializer/test_packet_probe.py tests/materializer/test_preflight.py -q
```

Expected: pass.

- [ ] **Step 7: Commit corruption handlers**

```bash
git add src/chaos_librarian/materializer tests/materializer
git commit -m "feat: add malformed media corruption handlers"
```

## Task 5: Filesystem Mtime Action And Catalog Fixtures

**Files:**
- Modify: `src/chaos_librarian/materializer/phase_b/filesystem.py`
- Modify: `src/chaos_librarian/materializer/phase_b/__init__.py`
- Modify: `src/chaos_librarian/materializer/actions.py`
- Modify: `tests/materializer/test_actions.py`
- Modify: `tests/materializer/test_filesystem.py`
- Modify: `tests/materializer/test_preflight.py`
- Modify: `tests/materializer/test_wall_clock.py`
- Create: `tests/fixtures/scenarios/interceptor-catalog.yaml`
- Create: `tests/fixtures/scenarios/interceptor-catalog-run.yaml`

- [ ] **Step 1: Add failing filesystem action and preflight tests**

Add a unit test for `touch_mtime`:

```python
asset.write_bytes(b"same bytes")
before_hash = sha256(asset.read_bytes())
before_mtime_ns = asset.stat().st_mtime_ns
dispatch touch_mtime offset=2s
after_hash == before_hash
after_mtime_ns == before_mtime_ns + 2_000_000_000
FilesystemAction.content_hash == before_hash
FilesystemAction.mtime_before_ns == before_mtime_ns
FilesystemAction.mtime_after_ns == after_mtime_ns
```

Add a preflight test proving a scenario with `touch_mtime` is accepted by
`preflight_timeline`; the materializer must not reject the action before the
phase-B filesystem dispatcher sees it.

Run:

```bash
uv run pytest tests/materializer/test_filesystem.py tests/materializer/test_preflight.py -q
```

Expected: fails until filesystem dispatch supports the action.

- [ ] **Step 2: Implement mtime dispatch**

Add `TOUCH_MTIME` to the materializer action set that feeds
`SUPPORTED_S10_ACTIONS`, update `test_actions.py` for the expanded partition,
and add it to `supports_filesystem_action`. In the handler:

1. Resolve `path` under `ctx.library_root`.
2. Parse `offset` with `parse_duration`.
3. Read bytes and hash before changing metadata.
4. Get `stat().st_atime_ns` and `stat().st_mtime_ns`.
5. Call `Path.touch` is not precise enough; use:

```python
os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + offset_ns))
```

6. Return `FilesystemAction` with `from_path == to_path == path`, content hash,
   and mtime evidence.

- [ ] **Step 3: Add catalog fixtures**

Create `tests/fixtures/scenarios/interceptor-catalog.yaml` as the
static-materialize-safe smoke fixture. It must not contain `network_lag_*`
events because `materialize` intentionally rejects network lag unless the
wall-clock `run` command is used:

```yaml
schema_version: 9
scenario_id: interceptor-catalog
seed: 115
duration_scale: short
profiles:
  - malformed-media
  - filesystem-artifacts
library:
  roots:
    - id: movies_hd
      path: movies-hd
...
timeline:
  - id: truncate_001
    at: 1s
    action: truncate_file
    target: asset_main
    keep_bytes: 64
  - id: mtime_001
    at: 2s
    action: touch_mtime
    target: asset_main
    offset: 2s
```

Create `tests/fixtures/scenarios/interceptor-catalog-run.yaml` for the
wall-clock-only `network-fs-lag` entries:

```yaml
schema_version: 9
scenario_id: interceptor-catalog-run
seed: 117
duration_scale: short
profiles:
  - network-fs-lag
library:
  roots:
    - id: movies_hd
      path: movies-hd
...
timeline:
  - id: rename_001
    at: 1s
    action: rename_file
    target: asset_main
    to: movies-hd/catalog-renamed.mkv
  - id: delayed_rename_start
    at: 1s
    action: network_lag_start
    effect: delayed_rename
    target: asset_main
    after: rename_001
    duration: 1s
  - id: delayed_rename_commit
    at: 2s
    action: network_lag_commit
    for: delayed_rename_start
  - id: rename_for_held
    at: 3s
    action: rename_file
    target: asset_main
    to: movies-hd/catalog-held.mkv
  - id: held_handle_start
    at: 3s
    action: network_lag_start
    effect: held_handle
    target: asset_main
    after: rename_for_held
    duration: 1s
  - id: held_handle_commit
    at: 4s
    action: network_lag_commit
    for: held_handle_start
  - id: delete_for_visibility
    at: 5s
    action: delete_file
    target: asset_main
  - id: restore_for_visibility
    at: 6s
    action: add_file
    target: asset_main
    to: movies-hd/catalog-restored.mkv
  - id: delayed_visibility_start
    at: 6s
    action: network_lag_start
    effect: delayed_visibility
    target: asset_main
    after: restore_for_visibility
    duration: 1s
  - id: delayed_visibility_commit
    at: 7s
    action: network_lag_commit
    for: delayed_visibility_start
```

Use a small asset fixture shape copied from
`tests/fixtures/scenarios/malformed-container-header.yaml` in both fixtures.
Do not include `corrupt_packet_range` or `write_invalid_duration_metadata` in
these general smoke fixtures; those need real ffprobe/ffmpeg details and are
covered by unit and integration tests.

- [ ] **Step 4: Add catalog assertions**

In `test_wall_clock.py`, add a fake-clock test that runs
`interceptor-catalog-run.yaml` and asserts:

```python
materialization_report.network_lag_actions contains delayed_rename evidence
materialization_report.network_lag_actions contains delayed_visibility evidence
materialization_report.network_lag_actions contains held_handle evidence
held_handle evidence has enforced is False
```

Keep the `touch_mtime` evidence assertion in the filesystem unit test and the
real static-materialize integration test; the wall-clock fixture is only for
the network-lag catalog entries.

- [ ] **Step 5: Run filesystem and wall-clock tests**

```bash
uv run pytest tests/materializer/test_actions.py tests/materializer/test_filesystem.py tests/materializer/test_preflight.py tests/materializer/test_wall_clock.py tests/contract/test_sample_scenarios.py -q
```

Expected: pass.

- [ ] **Step 6: Commit filesystem catalog work**

```bash
git add src/chaos_librarian/materializer tests/materializer tests/fixtures/scenarios/interceptor-catalog.yaml tests/fixtures/scenarios/interceptor-catalog-run.yaml
git commit -m "feat: add mtime interceptor evidence"
```

## Task 6: Negative Oracle Hash

**Files:**
- Create: `src/chaos_librarian/materializer/phase_b/oracle_hash.py`
- Modify: `src/chaos_librarian/materializer/phase_b/__init__.py`
- Modify: `src/chaos_librarian/materializer/manifest_build.py`
- Modify: `src/chaos_librarian/materializer/actions.py`
- Modify: `src/chaos_librarian/materializer/run.py`
- Modify: `src/chaos_librarian/materializer/wall_clock.py`
- Modify: `src/chaos_librarian/materializer/persistence/reports.py`
- Modify: `src/chaos_librarian/materializer/persistence/finalize.py`
- Modify: `tests/materializer/test_oracle_hash.py`
- Modify: `tests/materializer/test_actions.py`
- Modify: `tests/materializer/test_phase_b.py`
- Modify: `tests/materializer/test_preflight.py`
- Modify: `tests/materializer/test_run_sprint10.py`
- Modify: `tests/adapter/test_compare_final_state.py`
- Create: `tests/fixtures/scenarios/negative-oracle-hash.yaml`

- [ ] **Step 1: Add failing false-hash unit tests**

Create tests:

```python
false_hash_for(seed_material, actual_hash) is deterministic
false_hash_for(seed_material, actual_hash) != actual_hash
apply_wrong_oracle_hash records actual and reported hash
apply_wrong_oracle_hash does not modify file bytes
apply_wrong_oracle_hash wraps file/hash failures in CorruptionActionError
apply_wrong_oracle_hash preserves current probed metadata for output version
apply_wrong_oracle_hash can run after prior phase-B mutation on same asset
```

Run:

```bash
uv run pytest tests/materializer/test_oracle_hash.py -q
```

Expected: fails until helper exists.

- [ ] **Step 2: Implement false-hash helper**

Use deterministic hash expansion:

```python
def false_hash_for(seed_material: str, actual_hash: str) -> str:
    suffix = hashlib.sha256(f"{seed_material}:{actual_hash}".encode()).hexdigest()
    candidate = f"sha256:{suffix}"
    if candidate != actual_hash:
        return candidate
    fallback = hashlib.sha256(f"{seed_material}:{actual_hash}:fallback".encode()).hexdigest()
    return f"sha256:{fallback}"
```

`apply_wrong_oracle_hash` should:

1. Read `input_path`.
2. Compute `actual_content_hash`.
3. Compute `reported_content_hash`.
4. Resolve the input version's current `ProbedMedia | None` through
   `ctx.version_probe_lookup`.
5. Add `output_version_id -> (reported_content_hash, input_probed)` to a new
   `ctx.post_phase_b_oracle_hashes` map.
6. Return `OracleHashAction`.

- [ ] **Step 3: Wire phase-B state**

Extend `PhaseBState`:

```python
oracle_hash_ctx: OracleHashPhaseBContext
oracle_hash_actions: list[OracleHashAction]
```

Update direct `PhaseBState(...)` construction in `test_phase_b.py` and
wall-clock `_DispatchState` construction in `wall_clock.py` in this same task.
Do not wait for Task 7; otherwise the repo has a broken intermediate state as
soon as `PhaseBState` gains the new required context.

Create `OracleHashPhaseBContext` in `oracle_hash.py`:

```python
library_root: Path
post_phase_b_oracle_hashes: dict[str, tuple[str, ProbedMedia | None]]
version_probe_lookup: Callable[[str], ProbedMedia | None]
```

Add it in `make_phase_b_state` the same way `corruption_ctx` is built.
The lookup must resolve the input version's current probe facts from, in
order:

1. `state.oracle_hash_ctx.post_phase_b_oracle_hashes`
2. `state.corruption_ctx.post_phase_b_versions`
3. `state.media_ctx.post_phase_b_versions`
4. the phase-A-stamped `manifest.versions`

This avoids losing `probed` metadata on the new false-hash version, and it
keeps `wrong_oracle_hash` executable after an earlier phase-B mutation on the
same asset.

Add `WRONG_ORACLE_HASH` to the materializer action set that feeds
`SUPPORTED_S10_ACTIONS`, update `test_actions.py` for the expanded partition,
and add a preflight test proving
`preflight_timeline` accepts it.

Dispatch `WRONG_ORACLE_HASH` before the generic unsupported error. The helper
should wrap failures in `CorruptionActionError` so existing phase-B cleanup,
failure-report, and `Outcome.CORRUPTION_FAILED` paths still run; do not let raw
`OSError`, `KeyError`, or hashing exceptions escape the dispatcher.

Extend `test_phase_b.py` to prove dispatch routes `WRONG_ORACLE_HASH` into
`oracle_hash_actions` and `augment_phase_b_outputs` stamps
`oracle_hash_ctx.post_phase_b_oracle_hashes`.

Update `apply_wrong_oracle_hash` and `augment_phase_b_outputs`:

```python
input_probed = ctx.version_probe_lookup(input_version_id)
ctx.post_phase_b_oracle_hashes[output_version_id] = (reported_content_hash, input_probed)
augment_versions(manifest, state.oracle_hash_ctx.post_phase_b_oracle_hashes)
```

Thread `oracle_hash_actions` through static materialize reporting in this task,
before the integration test below:

```python
build_report(..., oracle_hash_actions=state.oracle_hash_actions)
finalize_success(..., oracle_hash_actions=phase_b_state.oracle_hash_actions)
finalize_failure_phase_b(..., oracle_hash_actions=phase_b_state.oracle_hash_actions)
```

Update `build_report(...)` and `MaterializationReport` callers so partial
`oracle_hash_actions` are preserved on static materialize phase-B failures.

- [ ] **Step 4: Add materialize integration test**

Use `tests/fixtures/scenarios/negative-oracle-hash.yaml`:

```yaml
schema_version: 9
scenario_id: negative-oracle-hash
seed: 116
duration_scale: short
profiles:
  - negative-oracle
...
timeline:
  - id: wrong_hash_001
    at: 1s
    action: wrong_oracle_hash
    target: asset_main
```

Assert:

```python
report["oracle_hash_actions"][0]["actual_content_hash"] !=
    report["oracle_hash_actions"][0]["reported_content_hash"]
manifest current version content_hash == reported_content_hash
manifest current version probed is not None
actual sha256 of file == actual_content_hash
```

- [ ] **Step 5: Add adapter negative test**

In `test_compare_final_state.py`, load or build a fixture where the oracle
manifest carries `reported_content_hash` and the observed state carries
`actual_content_hash`.

Assert:

```python
report.ok is False
report.findings[0].code == DivergenceCode.HASH_MISMATCH
```

Do not special-case `negative-oracle` in compare. The point is to prove
consumers surface a mismatch.

- [ ] **Step 6: Run tests**

```bash
uv run pytest tests/materializer/test_actions.py tests/materializer/test_oracle_hash.py tests/materializer/test_phase_b.py tests/materializer/test_preflight.py tests/materializer/test_run_sprint10.py tests/materializer/test_wall_clock.py::test_timeline_drained_early_idles_until_duration tests/adapter/test_compare_final_state.py -q
```

Expected: pass.

- [ ] **Step 7: Commit negative oracle work**

```bash
git add src/chaos_librarian/materializer tests/materializer tests/adapter tests/fixtures/scenarios/negative-oracle-hash.yaml
git commit -m "feat: add negative oracle hash interceptor"
```

## Task 7: Run Replay And Strict Replay Comparison

**Files:**
- Modify: `src/chaos_librarian/materializer/replay.py`
- Modify: `src/chaos_librarian/materializer/wall_clock.py`
- Modify: `src/chaos_librarian/contract/canonicalize.py`
- Modify: `tests/materializer/test_replay.py`
- Modify: `tests/materializer/test_wall_clock.py`
- Modify: `tests/integration/test_materialize_sprint10_real.py`

- [ ] **Step 1: Add run replay tests**

Extend replay tests to cover:

```python
run replay reproduces truncate_file corruption_actions evidence
run replay reproduces touch_mtime filesystem_actions evidence
run replay reproduces wrong_oracle_hash oracle_hash_actions evidence
```

For wrong-oracle replay, assert the replayed manifest carries the same
`reported_content_hash` as the source run.

- [ ] **Step 2: Update run and replay report construction**

Where `build_report(...)` is called for wall-clock run and run replay, pass:

```python
oracle_hash_actions=state.oracle_hash_actions
```

Ensure run and replay failure paths preserve partial `oracle_hash_actions` the
same way they already preserve partial `corruption_actions`. Static materialize
report plumbing was added in Task 6 so the negative-oracle integration test can
pass before replay work starts.

For wall-clock `run`, continue passing `network_lag_actions=state.network_lag_actions`.
Static materialize and run replay should leave `network_lag_actions` at the
existing default empty list; this plan does not add network-lag run-replay
support.

- [ ] **Step 3: Update canonical evidence helper**

Rename or extend `corruption_evidence(...)` to include:

```python
"corruption_actions": [...]
"oracle_hash_actions": [...]
"filesystem_metadata_actions": [
    action for action in report.filesystem_actions
    if action.action is TimelineActionName.TOUCH_MTIME
]
"network_lag_actions": [...]
```

Keep the existing function name if changing callers would add churn; otherwise
use `interceptor_evidence(...)` and update all call sites in one commit.

- [ ] **Step 4: Add real integration coverage**

Extend `tests/integration/test_materialize_sprint10_real.py` with:

```python
test_interceptor_catalog_fixture_materializes_real_truncate_and_mtime
test_packet_range_corruption_records_real_packet_evidence
test_invalid_duration_metadata_records_real_probe_evidence
test_negative_oracle_fixture_records_actual_and_reported_hash
```

The interceptor-catalog materialize test must use
`tests/fixtures/scenarios/interceptor-catalog.yaml`, not
`interceptor-catalog-run.yaml`; the latter contains `network_lag_*` events and
belongs to wall-clock `run` coverage.

Build the packet-range and invalid-duration scenarios inline from the same
small generated-media shape as the fixture. Skip only if the existing
ffmpeg/ffprobe capability checks cannot produce packet `pos`/`size` evidence;
otherwise assert the real `materialization.json.corruption_actions` record has
the resolved packet byte range or invalid-duration probe metadata.

Skip only when ffmpeg/ffprobe do not meet existing minimums. Do not add new
tool requirements.

- [ ] **Step 5: Run replay and integration tests**

```bash
uv run pytest tests/materializer/test_replay.py tests/materializer/test_wall_clock.py tests/integration/test_materialize_sprint10_real.py -q
```

Expected: pass or skip only the existing real-ffmpeg integration tests when
tools are unavailable.

- [ ] **Step 6: Commit replay work**

```bash
git add src/chaos_librarian/materializer src/chaos_librarian/contract/canonicalize.py tests/materializer tests/integration
git commit -m "feat: replay interceptor audit evidence"
```

## Task 8: Schemas, Docs, And Final Verification

**Files:**
- Modify: `schemas/*.schema.json`
- Modify: `docs/specs/chaos-librarian-design.md`
- Modify: `docs/contract/schema-reference.md`
- Modify: `docs/contract/integration-recipes.md`

- [ ] **Step 1: Update design docs**

In `docs/specs/chaos-librarian-design.md`, update the future interceptor list:

```text
Implemented catalog:
- corrupt_container_header: malformed-media
- truncate_file: malformed-media
- corrupt_packet_range: malformed-media
- write_invalid_duration_metadata: malformed-media
- touch_mtime: filesystem-artifacts
- network_lag_start/network_lag_commit delayed_visibility/delayed_rename: network-fs-lag
- network_lag_start/network_lag_commit held_handle: network-fs-lag
- wrong_oracle_hash: negative-oracle
```

Clarify that invalid duration metadata is tag-level corruption, and that
negative-oracle fixtures intentionally make compare report `HASH_MISMATCH`.

- [ ] **Step 2: Update contract docs**

In `schema-reference.md`, add:

```text
Scenario v9: interceptor catalog actions and two new profile labels.
Manifest v6: CorruptionRecord supports optional concrete byte ranges plus
packet/metadata evidence.
Materialization v9: OracleHashAction and mtime evidence on FilesystemAction.
Asset report v6: current snapshot carries widened corruption metadata.
```

In `integration-recipes.md`, add one recipe for:

```bash
uv run chaos-librarian materialize tests/fixtures/scenarios/interceptor-catalog.yaml --out /tmp/interceptors --json
```

Add a separate wall-clock recipe for the network-lag catalog fixture:

```bash
uv run chaos-librarian run tests/fixtures/scenarios/interceptor-catalog-run.yaml --out /tmp/interceptors-run --duration 2s --speed 10x --json
```

and one negative-oracle compare recipe explaining that a hash mismatch is
expected evidence for consumer validation.

- [ ] **Step 3: Regenerate schemas**

```bash
uv run python -m chaos_librarian.schema_export --write
uv run python -m chaos_librarian.schema_export --check
```

Expected: `--check` passes after generated files are committed.

- [ ] **Step 4: Run focused verification**

```bash
uv run pytest tests/contract tests/validation/rules/test_profile_opt_in.py tests/validation/rules/test_timeline_lifecycle.py tests/materializer/test_actions.py tests/materializer/test_corruption.py tests/materializer/test_packet_probe.py tests/materializer/test_oracle_hash.py tests/materializer/test_phase_b.py tests/materializer/test_replay.py tests/materializer/test_wall_clock.py tests/adapter/test_compare_final_state.py -q
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Expected: all pass with zero warnings.

- [ ] **Step 5: Run real-tool integration when available**

```bash
uv run pytest tests/integration/test_materialize_sprint10_real.py -q
```

Expected: pass if ffmpeg/ffprobe meet minimums; otherwise skip with the existing
capability reason.

- [ ] **Step 6: Commit docs and schemas**

```bash
git add schemas docs tests/fixtures/scenarios
git commit -m "docs: document interceptor catalog"
```

## Self-Review Checklist

- [ ] Every issue #75 requested behavior is covered:
  truncation, packet-range corruption, invalid duration metadata, held-open
  files, mtime-only changes, delayed commits, intentionally wrong oracle hashes.
- [ ] Held-open files and delayed commits are not duplicated; they are covered
  by existing `network-fs-lag` actions and new catalog docs/fixtures.
- [ ] Every new behavior is explicit opt-in through a profile and a timeline
  action/effect.
- [ ] Replay evidence exists in `materialization.json` for every behavior.
- [ ] The built-in adapter compare still reports negative-oracle hash mismatch.
- [ ] Contract model edits are followed by generated schema updates.
- [ ] No new dependency is introduced.
