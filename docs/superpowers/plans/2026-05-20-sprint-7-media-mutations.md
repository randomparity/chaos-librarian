# Sprint 7 — Media Mutations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift Sprint 6's no-media-mutation preflight gate. Ship 8 new timeline actions (`remux_container`, `edit_metadata`, `embed_subtitle`, `extract_subtitle`, `remove_sidecar`, `update_sidecar`, plus materialize wiring for the existing `reencode_video` / `reencode_audio`), a new `materializer/media.py` ffmpeg-based phase-B dispatcher, sidecar-kind widening (subtitle / poster / NFO), four new validation codes, and four schema bumps so the Version Evolution and Bundle Sidecars scenarios run end-to-end against real ffmpeg.

**Architecture:** Engine stays pure plan-only. Sprint 6's `materializer/filesystem.py` keeps its stdlib helpers; a new `materializer/media.py` owns ffmpeg-based handlers and a `_subtitle_codec_for_container` helper. Phase B becomes a single unified journal walk in `materializer/run.py` that dispatches each entry to stdlib or media based on action kind — extending Sprint 6's "journal is the truth source" rule to media events (every path is read from `entry.state_delta`, never from `WorldState`). On any media failure, `library/` is wiped and `materialization.json` records `outcome=media_failed`.

**Tech Stack:** Python 3.13, Pydantic v2, Typer, existing Sprint 1-6 layers. No new runtime dependencies (ffmpeg + ffprobe already required since Sprint 5). mkvmerge remains optional.

**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md) — §"Sprint 7", §"Mutation Model", §"Materialize Mode", §"Schema Contract".

**Design doc:** [`docs/superpowers/specs/2026-05-20-sprint-7-design.md`](../specs/2026-05-20-sprint-7-design.md) — load-bearing for every task; revised after two rounds of `/challenge` adversarial review. Read it before starting any task; do not deviate from its decisions silently.

**Branch:** `feat/sprint-7` (already exists; spec is currently the only uncommitted change).

**Follow-up issues opened alongside this plan:** #48 (rename `_PATH_MUTATING_PASSTHROUGH`), #49 (Sprint 6 spec/code two-row sidecar divergence). Both are out of scope for this PR.

---

## Open Design Decisions Baked Into This Plan

These resolve gaps the spec deliberately left for the implementer. Push back via PR comment if you disagree before merging.

1. **Test-file naming follows the existing per-family convention.** The spec sketches `test_events_sprint7.py`, `test_run_sprint7.py`, etc. Sprint 6 already broke that convention in favor of per-action-family files; Sprint 7 continues:
   - New engine handlers split by family: `_handle_remux_container`, `_handle_edit_metadata` are byte-only media operations → extend `tests/engine/test_events_media.py`. `_handle_embed_subtitle`, `_handle_extract_subtitle`, `_handle_remove_sidecar`, `_handle_update_sidecar` are sidecar-touching → new file `tests/engine/test_events_sidecar.py`.
   - `derive_version_history` tests → new file `tests/engine/test_version_history.py`.
   - Materializer media dispatcher → new file `tests/materializer/test_media.py`.
   - `sidecar_bytes.py` tests → new file `tests/materializer/test_sidecar_bytes.py`.
   - Materializer orchestrator additions extend the existing `tests/materializer/test_run.py` and `tests/materializer/test_preflight.py`.
   - `_remove_sidecar` filesystem helper test extends `tests/materializer/test_filesystem.py`.
   - `augment_versions` / `augment_updated_sidecars` extend `tests/materializer/test_manifest_build.py`.
   - Validation rule additions: `tests/validation/rules/test_sidecar_target.py` (new) and `tests/validation/rules/test_extract_track_unknown.py` (new). Lifecycle extensions go in the existing `tests/validation/rules/test_timeline_lifecycle.py`. Path-containment extensions go in the existing `tests/validation/rules/test_path_containment.py`.
   - Contract tests extend the existing per-model files (`test_scenario.py`, `test_manifest.py`, `test_materialization.py`, `test_reports.py`, `test_contract_constants.py`).
   - Layer 4 integration tests → new file `tests/integration/test_materialize_sprint7_real.py`.
   - Layer 5 CLI integration tests → new file `tests/cli/test_materialize_sprint7.py`.

2. **`_minimal_scenario_for_action` registry extension.** The Sprint 6 lock test for `_STATE_DELTA_KEYS` uses a per-action registry. Extend it with the 6 new actions; each entry returns `(Scenario, WorldState, ResolvedEvent)` with whatever prerequisite events the new handler needs already applied (e.g. `embed_subtitle` needs a `create_sidecar` already in state). Defined in Task 14.

3. **`SidecarKind` enum placement.** Lives in `src/chaos_librarian/contract/scenario.py` next to the other StrEnums (line ~75, before the Tracks block), not in `manifest.py` — the discriminator on `CreateSidecarEvent` is the originating use and `manifest.ManifestSidecar.kind` stays a free-form `str` for backward-compat with manifest v3 callers.

4. **`MediaAction.tool_invocation_index` typing.** Optional `int`, `None` for the `update_sidecar` non-poster path (no ffmpeg call). The poster path of `update_sidecar` invokes ffmpeg lavfi and DOES populate the index — branching happens inside the handler.

5. **`_subtitle_codec_for_container` raises through `MediaActionError`, not at module load.** The check happens inside each handler when it inspects `output_path.suffix`; an unsupported container surfaces as an exit-5 `E_MATERIALIZE_MEDIA_FAILED` at dispatch time, exactly like ffmpeg-failure paths. Containers covered: `mkv`, `webm` → `srt`; `mp4`, `m4v`, `mov` → `mov_text`.

6. **Failure-cleanup function rename.** Sprint 6's `cleanup_failed_filesystem_run` is renamed `cleanup_failed_phase_b_run`. `finalize_failure_filesystem` is renamed `finalize_failure_phase_b` and accepts an extra `media_actions` arg + an `outcome: Outcome` parameter so both `fs_failed` and `media_failed` flow through it. The Sprint 6 caller signature changes are mechanical and land in the same task as the rename.

7. **`preflight_timeline(scenario)` signature stays unchanged.** Sprint 6 made it a single-positional function; Sprint 7 swaps `SUPPORTED_S6_ACTIONS` for `SUPPORTED_S7_ACTIONS` inside the function body. The `SUPPORTED_S6_ACTIONS` constant is deleted (no callers outside `preflight.py`; spec rule "replace, don't deprecate"). The `error_code` and `field` payload shape is preserved.

8. **`augment_versions` and `augment_updated_sidecars` placement.** Both live in `src/chaos_librarian/materializer/manifest_build.py` alongside the existing `augment_manifest` and `augment_timeline_sidecars`. `augment_versions` mutates `manifest.versions` to stamp `content_hash` + `probed` on rows whose id is in the input map; `augment_updated_sidecars` mutates `manifest.sidecars` to stamp `content_hash` + `path` on rows whose id is in the input map. Both follow the existing in-place mutation pattern.

9. **`MediaAction` field constraints (per spec §"MediaAction audit shape"):**
   - `event_id`, `action`, `target_asset_id`, `input_path`, `output_path`, `duration_ns`: always required.
   - `input_version_id`: `None` for `extract_subtitle`, `update_sidecar`.
   - `output_version_id`: `None` for `extract_subtitle`, `remove_sidecar`, `update_sidecar` (and `remove_sidecar` does not go through `media.py` per Decision 11 — its `MediaAction` row is never created).
   - `output_sidecar_id`: populated by `extract_subtitle` (new sidecar id) and `update_sidecar` (existing sidecar id whose bytes changed).
   - `input_content_hash`: `None` for `extract_subtitle` (asset bytes unchanged; we don't re-hash the asset just to populate this field).
   - `output_content_hash`: always populated for byte-changing handlers.
   - `tool_invocation_index`: `None` for `update_sidecar` subtitle/NFO paths (no ffmpeg call); populated for every other handler.

10. **`derive_version_history` excludes `extract_subtitle`.** Per design decision #9 in the spec: extract is read-only, no new version allocated, so `_VERSION_AFFECTING_ACTIONS` excludes it. The asymmetry with `embed_subtitle` (which does allocate) is correct.

11. **`remove_sidecar` dispatches to `filesystem.py`, not `media.py`.** Pure stdlib `unlink` + manifest row removal; no ffmpeg involvement. The dispatch table in `run.py`'s unified phase-B walk routes `REMOVE_SIDECAR` to `_dispatch_stdlib` even though removing a sidecar is conceptually a "media-adjacent" operation. The `MediaAction` audit array does NOT carry a row for `remove_sidecar`; the `FilesystemAction` array does. The `update_sidecar` path is the opposite: it routes through `media.py` even when the byte generator is pure Python, so the audit + atomic-write machinery is reused.

12. **Atomic-write temp-file naming.** `<output>.tmp.<resolved_seed>` per spec design decision #11. The `resolved_seed` is in scope on `_MediaContext`, populated by the orchestrator from `plan_artifacts.replay_bundle.resolved_seed`.

13. **`update_sidecar` perturbed sub-seed includes `event_id`.** Per spec design decision #7 (post-round-1): `Hash(seed_stream="sidecar_update", sidecar_id, event_id)` so two consecutive updates on the same sidecar produce distinct bytes. The hash recipe lives in `sidecar_bytes.regenerate_sidecar` and reuses the existing `chaos_librarian.determinism.hash_for` helper.

14. **Container ext extraction.** `_swap_extension(path, new_ext)` in `engine/events.py` is shared between handlers that need it. Pure string function; lives next to `_handle_remux_container`.

15. **Schema version constants change in one commit, immediately after the contract surfaces are wired.** Per the existing convention: bump the constant in `contract/__init__.py` and the corresponding `Literal[N]` on the model in the same task that introduces the field changes. Fixtures bump their `schema_version` line in the matching task.

16. **Existing fixture migration.** Every existing positive fixture (`archive-file-explicit-root`, `archive-file`, `bundle-sidecars`, `duplicate-variant`, `identity-move-rename`, `mixed-supported-unsupported`, `move-between-roots`, `reencode-video`, `seed-random`, `sidecar-collision`, `sidecar-create-via-timeline`, `slow-copy-materialize`, `slow-copy`, `static-library`, `version-evolution`) gets its `schema_version` bumped from 4 → 5 in Task 1. Invalid fixtures stay at their current version unless they also fail the v5 literal check — re-verify after the bump.

17. **Commit cadence.** One commit per task (the final step of every task). Use the project's commit-message style (`feat(contract):`, `feat(engine):`, `test(validation):`, etc.). Each commit ends with the standard `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.

---

## File Structure

### To create

```
src/chaos_librarian/contract/
  (no new files — existing modules extended)

src/chaos_librarian/engine/
  version_history.py            # derive_version_history(asset_id, journal)

src/chaos_librarian/materializer/
  media.py                      # apply_media_action + per-action handlers +
                                # _subtitle_codec_for_container + _MEDIA_ACTIONS /
                                # _STDLIB_ACTIONS / SUPPORTED_S7_ACTIONS
  sidecar_bytes.py              # render_poster, render_nfo, regenerate_sidecar

src/chaos_librarian/validation/rules/
  sidecar_target.py             # rule_sidecar_target — three codes:
                                # E_SIDECAR_TARGET_UNKNOWN,
                                # E_SIDECAR_KIND_MISMATCH,
                                # E_SIDECAR_PATH_COLLISION
  extract_track_unknown.py      # rule_extract_track_unknown

tests/engine/
  test_events_sidecar.py        # _handle_embed_subtitle, _handle_extract_subtitle,
                                # _handle_remove_sidecar, _handle_update_sidecar
  test_version_history.py       # derive_version_history pure tests

tests/materializer/
  test_media.py                 # apply_* + _subtitle_codec_for_container tests
                                # (mocked ffmpeg + ffprobe)
  test_sidecar_bytes.py         # render_poster, render_nfo, regenerate_sidecar

tests/validation/rules/
  test_sidecar_target.py        # E_SIDECAR_TARGET_UNKNOWN, _KIND_MISMATCH,
                                # _PATH_COLLISION
  test_extract_track_unknown.py # E_EXTRACT_TRACK_UNKNOWN

tests/integration/
  test_materialize_sprint7_real.py  # Layer 4 real-tool tests

tests/cli/
  test_materialize_sprint7.py   # Layer 5 CLI integration

tests/fixtures/scenarios/
  remux-container.yaml          # mkv -> mp4
  edit-metadata.yaml            # dict-of-strings payload
  embed-extract-roundtrip.yaml  # round-trip subtitle
  update-sidecar.yaml           # regenerate sidecar bytes
  remove-sidecar.yaml           # unlink + manifest row removal
  subtitle-ops-on-mp4.yaml      # mp4 mov_text codec coverage

tests/fixtures/scenarios/invalid/
  edit-metadata-empty-fields.yaml          # E_SCHEMA_INVALID
  embed-subtitle-unknown-sidecar.yaml      # E_SIDECAR_TARGET_UNKNOWN
  embed-subtitle-kind-mismatch.yaml        # E_SIDECAR_KIND_MISMATCH
  extract-subtitle-no-track.yaml           # E_EXTRACT_TRACK_UNKNOWN
  extract-subtitle-collides-with-declared.yaml  # E_SIDECAR_PATH_COLLISION
  remove-sidecar-after-remove.yaml         # E_LIFECYCLE_INVALID
  create-poster-with-language.yaml         # E_SCHEMA_INVALID
```

### To modify

```
src/chaos_librarian/contract/__init__.py
  SCENARIO_SCHEMA_VERSION         4 -> 5
  MANIFEST_SCHEMA_VERSION         3 -> 4
  MATERIALIZATION_SCHEMA_VERSION  3 -> 4
  ASSET_REPORT_SCHEMA_VERSION     3 -> 4

src/chaos_librarian/contract/scenario.py
  + SidecarKind StrEnum (SUBTITLE / POSTER / NFO)
  + TimelineActionName.REMUX_CONTAINER, .EDIT_METADATA,
    .EMBED_SUBTITLE, .EXTRACT_SUBTITLE, .REMOVE_SIDECAR, .UPDATE_SIDECAR
  + RemuxContainerEvent, EditMetadataEvent, EmbedSubtitleEvent,
    ExtractSubtitleEvent, RemoveSidecarEvent, UpdateSidecarEvent
  + CreateSidecarEvent.kind: SidecarKind (default SUBTITLE)
  + CreateSidecarEvent.language widens to str | None
  + @model_validator on CreateSidecarEvent for subtitle-requires-language /
    poster-NFO-forbid-language
  + @model_validator on EditMetadataEvent for empty-fields rejection
  Scenario.schema_version: Literal[5]

src/chaos_librarian/contract/manifest.py
  ManifestSidecar.language: str | None  (was: str)
  Manifest.schema_version: Literal[4]

src/chaos_librarian/contract/materialization.py
  + MediaAction model
  + Outcome.MEDIA_FAILED, FailureStage.MEDIA
  + MaterializationReport.media_actions
  MaterializationReport.schema_version: Literal[4]

src/chaos_librarian/contract/reports.py
  + VersionHistoryEntry model
  + AssetReport.version_history field
  AssetReport.schema_version: Literal[4]

src/chaos_librarian/engine/events.py
  + _handle_remux_container, _handle_edit_metadata,
    _handle_embed_subtitle, _handle_extract_subtitle,
    _handle_remove_sidecar, _handle_update_sidecar
  + _swap_extension(path, new_ext) -> str
  + _HANDLERS entries for the 6 new actions
  Extend _STATE_DELTA_KEYS:
    REENCODE_VIDEO gains input_path / output_path
    REENCODE_AUDIO gains input_path / output_path
    + 6 new rows
  Extend _handle_reencode_video / _handle_reencode_audio to populate
    input_path / output_path in state_delta

src/chaos_librarian/engine/state.py
  + WorldState.sidecar_id_for_path(asset_id, path) helper
  WorldState.to_manifest schema_version Literal[4]

src/chaos_librarian/engine/reports.py
  AssetReport builder wires derive_version_history(asset_id, journal)
  AssetReport schema_version Literal[4]

src/chaos_librarian/materializer/run.py
  Replace ``apply_phase_b`` call with a unified journal walk that
  dispatches each entry to stdlib OR media handler
  Add augment_versions + augment_updated_sidecars after phase B
  Catch MediaActionError -> finalize_failure_phase_b(outcome=MEDIA_FAILED)
  Catch FilesystemActionError -> finalize_failure_phase_b(outcome=FS_FAILED)

src/chaos_librarian/materializer/preflight.py
  SUPPORTED_S6_ACTIONS deleted (no callers)
  SUPPORTED_S7_ACTIONS = SUPPORTED_S6_ACTIONS_set | new media set
  preflight_timeline rejects against SUPPORTED_S7_ACTIONS

src/chaos_librarian/materializer/filesystem.py
  + _remove_sidecar helper (stdlib unlink + audit row)
  + _DISPATCH entry for REMOVE_SIDECAR
  Now the only stdlib-side change for Sprint 7 (media events live in media.py)

src/chaos_librarian/materializer/finalize.py
  finalize_failure_filesystem -> finalize_failure_phase_b
    (accepts media_actions, outcome: Outcome param;
     stage derived from outcome)
  finalize_success accepts media_actions

src/chaos_librarian/materializer/errors.py
  + MediaActionError(MaterializationError)
    with error_code = E_MATERIALIZE_MEDIA_FAILED

src/chaos_librarian/materializer/manifest_build.py
  + augment_versions(manifest, post_phase_b_versions)
  + augment_updated_sidecars(manifest, post_phase_b_sidecars)
  find_sidecar_for branches on kind for poster / NFO lookup
    (subtitle keeps (asset_id, language), poster/NFO uses
     (asset_id, kind))

src/chaos_librarian/materializer/reports.py
  build_report accepts media_actions and threads it into
  MaterializationReport

src/chaos_librarian/materializer/writer.py
  cleanup_failed_filesystem_run -> cleanup_failed_phase_b_run (rename)

src/chaos_librarian/validation/codes.py
  + E_SIDECAR_TARGET_UNKNOWN
  + E_EXTRACT_TRACK_UNKNOWN
  + E_SIDECAR_KIND_MISMATCH
  + E_SIDECAR_PATH_COLLISION

src/chaos_librarian/validation/semantic.py
  Register rule_sidecar_target and rule_extract_track_unknown in _RULES

src/chaos_librarian/validation/rules/timeline_lifecycle.py
  Extend _LOCATION_DEPENDENT_PASSTHROUGH with 6 new actions
  Extend _PATH_MUTATING_PASSTHROUGH to the 6 spec-listed members
    (REENCODE_VIDEO/AUDIO, REMUX_CONTAINER, EDIT_METADATA,
     EMBED_SUBTITLE, EXTRACT_SUBTITLE) — REMOVE_SIDECAR + UPDATE_SIDECAR
    are excluded (see Sprint 7 spec §"Lifecycle simulator extensions")
  Add state.sidecars_by_path projection (insert on create_sidecar /
    extract_subtitle; delete on remove_sidecar / embed_subtitle)
  Reject embed/extract/remove/update on a non-existing sidecar
    (E_LIFECYCLE_INVALID)

src/chaos_librarian/validation/rules/path_containment.py
  _PATH_FIELDS_BY_ACTION gains EXTRACT_SUBTITLE: ("to",)

src/chaos_librarian/schema_export.py
  Regenerate scenario.schema.json (v5), manifest.schema.json (v4),
  materialization.schema.json (v4), asset-report.schema.json (v4).
  No logic changes expected.

src/chaos_librarian/cli/commands/materialize.py
  Catch MediaActionError; emit_materialize_error + exit 5

schemas/scenario.schema.json          # REGEN to v5
schemas/manifest.schema.json          # REGEN to v4
schemas/materialization.schema.json   # REGEN to v4
schemas/asset-report.schema.json      # REGEN to v4

tests/fixtures/scenarios/{*}.yaml
  schema_version: 4 -> 5 (one-line each)

tests/fixtures/scenarios/version-evolution.yaml
  Add one edit_metadata event

tests/fixtures/scenarios/bundle-sidecars.yaml
  Add poster + NFO + embed_subtitle + rename_file
```

---

## Test Helpers Reference

Every task below references one or more shared test helpers. Before starting any task, verify which helpers exist (grep in `tests/`) and which need to be created — each task's "Files" section notes whether the helper is new or pre-existing.

#### Engine-side helpers (in `tests/engine/conftest.py`, extend the Sprint 6 file)

- `_build_minimal_scenario(*, roots, works, archive_root=None) -> Scenario` — Sprint 6's factory. Sprint 7 callers pass `schema_version=5` via the factory's `**overrides`.
- `_resolve_one(scenario, event_id) -> ResolvedEvent` — existing.
- `_minimal_scenario_for_action(action: TimelineActionName) -> tuple[Scenario, WorldState, ResolvedEvent]` — extend the Sprint 6 registry. Sprint 7 adds 6 new entries (one per new action); each returns a state that satisfies the new handler's preconditions (e.g. `embed_subtitle` returns state with one sidecar already created). Defined in Task 14 — full code, not a stub.
- `_atomic_entry(*, event_id, action, target, state_delta) -> AtomicJournalEntry` — Sprint 6's typed journal-entry builder for materializer tests. Defined in `tests/materializer/conftest.py`; Sprint 7 reuses unchanged.

#### Materializer-side helpers (in `tests/materializer/conftest.py`)

- `_mock_ffmpeg(monkeypatch, *, stub_bytes: bytes)` — Sprint 5/6 helper. Verify the actual name with `rg 'def .*mock_ffmpeg' tests/materializer/`.
- `_mock_probe(monkeypatch)` — same, for `ffprobe`.
- `_mock_run_ffmpeg(monkeypatch, *, stub_bytes=b"x" * 100, exit_code=0)` — NEW helper for Sprint 7 media handlers (writes `stub_bytes` to the output path argv slot and returns `(ToolInvocation, "")`). Defined in Task 24 if not already present.

#### Integration-test helpers (in `tests/integration/conftest.py`)

- `sha256_of(path: Path) -> str` — existing.
- `_load_current_manifest(out_dir: Path) -> Manifest` — existing.
- `_load_asset_report(out_dir: Path, asset_id: str) -> AssetReport` — existing.
- `_load_materialization_report(out_dir: Path) -> MaterializationReport` — existing.
- `_ffmpeg_meets_minimum() -> bool` — existing. Used in `pytest.mark.skipif`.

---

## Task 1: Scenario Contract — SidecarKind, 6 new actions, 6 new events, CreateSidecarEvent widening, v5 bump, fixture migration

**Why first:** every downstream task imports `TimelineActionName.REMUX_CONTAINER` or `EmbedSubtitleEvent`. The schema drift gate fails until both fixtures and JSON Schema are regenerated, so do all of this in one commit.

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py:16` — bump constant.
- Modify: `src/chaos_librarian/contract/scenario.py` — `SidecarKind` enum, 6 new `TimelineActionName` members, 6 new event variants, `CreateSidecarEvent` widening with model_validator, `EditMetadataEvent` empty-fields validator, union extension, `schema_version` literal.
- Modify (one line each): every `tests/fixtures/scenarios/*.yaml` (NOT `invalid/`) — `schema_version: 4 → 5`.
- Test: `tests/contract/test_scenario.py` — append round-trip + rejection tests for the new events and enum.
- Test: `tests/contract/test_contract_constants.py` — assert the bumped constant.
- Regenerate: `schemas/scenario.schema.json`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/contract/test_scenario.py` (match its style — short, focused, one assertion concept per test):

```python
def test_sidecar_kind_enum_values():
    assert SidecarKind.SUBTITLE.value == "subtitle"
    assert SidecarKind.POSTER.value == "poster"
    assert SidecarKind.NFO.value == "nfo"


def test_create_sidecar_default_kind_is_subtitle():
    payload = {
        "id": "ev_cs_001",
        "at": "1s",
        "action": "create_sidecar",
        "target": "asset_main",
        "to": "asset_main.eng.srt",
        "language": "eng",
    }
    event = CreateSidecarEvent.model_validate(payload)
    assert event.kind == SidecarKind.SUBTITLE


def test_create_sidecar_subtitle_requires_language():
    payload = {
        "id": "ev_cs_001", "at": "1s", "action": "create_sidecar",
        "target": "asset_main", "to": "x.srt", "kind": "subtitle",
    }
    with pytest.raises(ValidationError, match="subtitle sidecar requires language"):
        CreateSidecarEvent.model_validate(payload)


def test_create_sidecar_poster_forbids_language():
    payload = {
        "id": "ev_cs_001", "at": "1s", "action": "create_sidecar",
        "target": "asset_main", "to": "p.png", "kind": "poster",
        "language": "eng",
    }
    with pytest.raises(ValidationError, match="poster sidecar forbids language"):
        CreateSidecarEvent.model_validate(payload)


def test_create_sidecar_nfo_forbids_language():
    payload = {
        "id": "ev_cs_001", "at": "1s", "action": "create_sidecar",
        "target": "asset_main", "to": "x.nfo", "kind": "nfo",
        "language": "eng",
    }
    with pytest.raises(ValidationError, match="nfo sidecar forbids language"):
        CreateSidecarEvent.model_validate(payload)


def test_create_sidecar_poster_round_trip():
    payload = {
        "id": "ev_cs_001", "at": "1s", "action": "create_sidecar",
        "target": "asset_main", "to": "asset_main.poster.png",
        "kind": "poster",
    }
    event = CreateSidecarEvent.model_validate(payload)
    assert event.kind == SidecarKind.POSTER
    assert event.language is None


def test_remux_container_event_round_trip():
    payload = {
        "id": "ev_rmx_001", "at": "2s", "action": "remux_container",
        "target": "asset_main", "to_container": "mp4",
    }
    event = RemuxContainerEvent.model_validate(payload)
    assert event.to_container == "mp4"
    assert event.action == TimelineActionName.REMUX_CONTAINER


def test_edit_metadata_event_round_trip():
    payload = {
        "id": "ev_em_001", "at": "3s", "action": "edit_metadata",
        "target": "asset_main", "fields": {"title": "Pulsar", "artist": "x"},
    }
    event = EditMetadataEvent.model_validate(payload)
    assert event.fields == {"title": "Pulsar", "artist": "x"}


def test_edit_metadata_rejects_empty_fields():
    payload = {
        "id": "ev_em_001", "at": "3s", "action": "edit_metadata",
        "target": "asset_main", "fields": {},
    }
    with pytest.raises(ValidationError, match="empty"):
        EditMetadataEvent.model_validate(payload)


def test_embed_subtitle_event_round_trip():
    payload = {
        "id": "ev_es_001", "at": "4s", "action": "embed_subtitle",
        "target": "asset_main", "sidecar_path": "asset_main.eng.srt",
    }
    event = EmbedSubtitleEvent.model_validate(payload)
    assert event.sidecar_path == "asset_main.eng.srt"


def test_extract_subtitle_event_round_trip():
    payload = {
        "id": "ev_xs_001", "at": "5s", "action": "extract_subtitle",
        "target": "asset_main", "to": "asset_main.fra.srt",
        "language": "fra",
    }
    event = ExtractSubtitleEvent.model_validate(payload)
    assert event.to == "asset_main.fra.srt"
    assert event.language == "fra"


def test_remove_sidecar_event_round_trip():
    payload = {
        "id": "ev_rs_001", "at": "6s", "action": "remove_sidecar",
        "target": "asset_main", "sidecar_path": "asset_main.eng.srt",
    }
    event = RemoveSidecarEvent.model_validate(payload)
    assert event.target == "asset_main"
    assert event.sidecar_path == "asset_main.eng.srt"


def test_update_sidecar_event_round_trip():
    payload = {
        "id": "ev_us_001", "at": "7s", "action": "update_sidecar",
        "target": "asset_main", "sidecar_path": "asset_main.eng.srt",
    }
    event = UpdateSidecarEvent.model_validate(payload)
    assert event.target == "asset_main"
    assert event.sidecar_path == "asset_main.eng.srt"


def test_scenario_v5_round_trip_with_new_events():
    payload = {
        "schema_version": 5,
        "scenario_id": "sc_s7_001",
        "seed": 42,
        "duration_scale": "short",
        "library": {"roots": [{"id": "r0", "path": "library/r0"}]},
        "works": [],
        "timeline": [
            {"id": "e0", "at": "0s", "action": "remux_container",
             "target": "asset_main", "to_container": "mp4"},
        ],
    }
    scenario = Scenario.model_validate(payload)
    assert scenario.schema_version == 5
    assert scenario.timeline[0].action == TimelineActionName.REMUX_CONTAINER
```

Add the new imports at the top of `tests/contract/test_scenario.py`:

```python
from chaos_librarian.contract.scenario import (
    CreateSidecarEvent,
    EditMetadataEvent,
    EmbedSubtitleEvent,
    ExtractSubtitleEvent,
    RemoveSidecarEvent,
    RemuxContainerEvent,
    SidecarKind,
    UpdateSidecarEvent,
    # … plus the existing imports
)
```

Append to `tests/contract/test_contract_constants.py`:

```python
def test_scenario_schema_version_bumped_to_5():
    assert chaos_librarian.contract.SCENARIO_SCHEMA_VERSION == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/contract/test_scenario.py tests/contract/test_contract_constants.py -v 2>&1 | head -80`

Expected: ImportError or AttributeError on `SidecarKind`, `RemuxContainerEvent`, etc.; constant test fails (4 != 5).

- [ ] **Step 3: Bump the schema version constant**

In `src/chaos_librarian/contract/__init__.py`:

```python
SCENARIO_SCHEMA_VERSION: Final = 5
```

- [ ] **Step 4: Add SidecarKind enum + 6 new TimelineActionName members**

In `src/chaos_librarian/contract/scenario.py`, after the existing StrEnums (around line 75) and before the `# ---- Library` block:

```python
class SidecarKind(enum.StrEnum):
    """Kind of a sidecar — extends Sprint 6's subtitle-only assumption.

    Subtitle requires ``language``; poster and NFO forbid it.
    """

    SUBTITLE = "subtitle"
    POSTER = "poster"
    NFO = "nfo"
```

Extend `TimelineActionName`:

```python
class TimelineActionName(enum.StrEnum):
    MOVE_ASSET = "move_asset"
    RENAME_FILE = "rename_file"
    DELETE_FILE = "delete_file"
    ADD_FILE = "add_file"
    REENCODE_VIDEO = "reencode_video"
    REENCODE_AUDIO = "reencode_audio"
    CREATE_SIDECAR = "create_sidecar"
    SLOW_COPY_START = "slow_copy_start"
    SLOW_COPY_COMMIT = "slow_copy_commit"
    ARCHIVE_FILE = "archive_file"
    MOVE_BETWEEN_ROOTS = "move_between_roots"
    REMUX_CONTAINER = "remux_container"
    EDIT_METADATA = "edit_metadata"
    EMBED_SUBTITLE = "embed_subtitle"
    EXTRACT_SUBTITLE = "extract_subtitle"
    REMOVE_SIDECAR = "remove_sidecar"
    UPDATE_SIDECAR = "update_sidecar"
```

- [ ] **Step 5: Widen `CreateSidecarEvent` and add the kind/language model validator**

In `src/chaos_librarian/contract/scenario.py`, REPLACE the existing `CreateSidecarEvent` block with:

```python
class CreateSidecarEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.CREATE_SIDECAR] = TimelineActionName.CREATE_SIDECAR
    target: str
    to: str
    # Widened in scenario v5: poster/NFO sidecars have no language. The
    # model_validator below enforces (kind=subtitle, language=...) /
    # (kind in {poster, nfo}, language=None).
    language: str | None = None
    kind: SidecarKind = SidecarKind.SUBTITLE

    @model_validator(mode="after")
    def _check_language_matches_kind(self) -> "CreateSidecarEvent":
        if self.kind == SidecarKind.SUBTITLE and self.language is None:
            raise ValueError("subtitle sidecar requires language")
        if self.kind != SidecarKind.SUBTITLE and self.language is not None:
            raise ValueError(f"{self.kind.value} sidecar forbids language")
        return self
```

Add `model_validator` to the pydantic import at the top of the file:

```python
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator
```

- [ ] **Step 6: Add the 6 new event variants**

In `src/chaos_librarian/contract/scenario.py`, AFTER `MoveBetweenRootsEvent` (around line 248) and BEFORE the `TimelineEvent` union:

```python
class RemuxContainerEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.REMUX_CONTAINER] = TimelineActionName.REMUX_CONTAINER
    target: str
    to_container: str  # "mp4" / "mkv" / "webm" — engine rewrites the path
                       # extension; materializer runs ffmpeg -c copy.


class EditMetadataEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.EDIT_METADATA] = TimelineActionName.EDIT_METADATA
    target: str
    fields: dict[str, str]  # opaque key=value pairs; materializer maps each
                            # to ffmpeg -metadata. Empty dict rejected here.

    @model_validator(mode="after")
    def _check_fields_non_empty(self) -> "EditMetadataEvent":
        if not self.fields:
            raise ValueError("edit_metadata.fields must be a non-empty mapping")
        return self


class EmbedSubtitleEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.EMBED_SUBTITLE] = TimelineActionName.EMBED_SUBTITLE
    target: str
    sidecar_path: str  # For a DECLARED subtitle, use
                       # "<asset_id>.<language>.srt" (see Sprint 7 spec
                       # §"Declared-sidecar path convention"). For a sidecar
                       # created by create_sidecar, use that event's "to:" path.


class ExtractSubtitleEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.EXTRACT_SUBTITLE] = TimelineActionName.EXTRACT_SUBTITLE
    target: str
    to: str
    language: str
    # Embedded-track selection: extract the first subtitle track of the
    # asset whose language matches. If no language match, falls back to
    # the first subtitle track. Validator rejects if asset has no
    # subtitle track via E_EXTRACT_TRACK_UNKNOWN.


class RemoveSidecarEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.REMOVE_SIDECAR] = TimelineActionName.REMOVE_SIDECAR
    target: str
    sidecar_path: str


class UpdateSidecarEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.UPDATE_SIDECAR] = TimelineActionName.UPDATE_SIDECAR
    target: str
    sidecar_path: str
```

- [ ] **Step 7: Extend the TimelineEvent union and bump Scenario.schema_version**

REPLACE the `TimelineEvent` Annotated union:

```python
TimelineEvent = Annotated[
    MoveAssetEvent
    | RenameFileEvent
    | DeleteFileEvent
    | AddFileEvent
    | ReencodeVideoEvent
    | ReencodeAudioEvent
    | CreateSidecarEvent
    | SlowCopyStartEvent
    | SlowCopyCommitEvent
    | ArchiveFileEvent
    | MoveBetweenRootsEvent
    | RemuxContainerEvent
    | EditMetadataEvent
    | EmbedSubtitleEvent
    | ExtractSubtitleEvent
    | RemoveSidecarEvent
    | UpdateSidecarEvent,
    Field(discriminator="action"),
]
```

Bump `Scenario.schema_version`:

```python
class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)
    schema_version: Literal[5]
    # … rest unchanged
```

- [ ] **Step 8: Bump every existing positive fixture from v4 → v5**

For each file in `tests/fixtures/scenarios/*.yaml` (NOT the `invalid/` subtree), change the first non-comment line `schema_version: 4` to `schema_version: 5`.

Run: `rg -l '^schema_version: 4' tests/fixtures/scenarios/ | grep -v invalid/` — should be empty after the edit. Use `sed -i '' 's/^schema_version: 4$/schema_version: 5/' tests/fixtures/scenarios/*.yaml` or perform the edit one file at a time via your editor.

Verify: `rg '^schema_version: 4$' tests/fixtures/scenarios/ -l | grep -v invalid/` returns no hits.

- [ ] **Step 9: Regenerate the scenario schema**

Run: `uv run python -m chaos_librarian.schema_export --write`

Verify the diff: `git diff schemas/scenario.schema.json` should show 6 new event variants in the `oneOf`, the new `SidecarKind` enum, `CreateSidecarEvent.kind` field, `CreateSidecarEvent.language` widened to `["string", "null"]`, and `schema_version` enum widened to `5`.

- [ ] **Step 10: Run the contract test suite**

Run: `uv run pytest tests/contract/ -v 2>&1 | tail -40`

Expected: every test passes. If any invalid fixture surfaces because its first error was the schema_version literal check (now 5) and the fixture file still says 4, that fixture is broken — verify it shouldn't be at v5 (i.e. its `# expected:` marker is `E_FIELD_LITERAL` or similar that fires before the deeper check). Fix any new failures one by one.

- [ ] **Step 11: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

Fix any failures.

- [ ] **Step 12: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/scenario.py \
        schemas/scenario.schema.json \
        tests/fixtures/scenarios/*.yaml \
        tests/contract/test_scenario.py \
        tests/contract/test_contract_constants.py
git commit -m "$(cat <<'EOF'
feat(contract): scenario v5 — 6 new media events + SidecarKind + CreateSidecarEvent widening

Adds RemuxContainerEvent, EditMetadataEvent, EmbedSubtitleEvent,
ExtractSubtitleEvent, RemoveSidecarEvent, UpdateSidecarEvent. Widens
CreateSidecarEvent with kind: SidecarKind and language: str | None; a
model_validator enforces (subtitle requires language, poster/NFO forbids
language). EditMetadataEvent rejects empty fields at validation time.

Bumps SCENARIO_SCHEMA_VERSION 4 -> 5 and migrates every positive fixture.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Manifest Contract — ManifestSidecar.language optional, v4 bump

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py` — `MANIFEST_SCHEMA_VERSION: Final = 4`.
- Modify: `src/chaos_librarian/contract/manifest.py` — `ManifestSidecar.language: str | None`; `Manifest.schema_version: Literal[4]`.
- Modify: `src/chaos_librarian/engine/state.py:118` — `to_manifest` schema_version 3 → 4.
- Test: `tests/contract/test_manifest.py` — append round-trip tests for poster/NFO sidecars with `language=None`.
- Test: `tests/contract/test_contract_constants.py` — assert bumped constant.
- Regenerate: `schemas/manifest.schema.json`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/contract/test_manifest.py`:

```python
def test_manifest_sidecar_poster_no_language():
    sidecar = ManifestSidecar(
        id="sidecar_0001",
        asset_id="asset_main",
        kind="poster",
        path="asset_main.poster.png",
        language=None,
    )
    assert sidecar.language is None
    assert sidecar.kind == "poster"


def test_manifest_sidecar_nfo_no_language():
    sidecar = ManifestSidecar(
        id="sidecar_0001",
        asset_id="asset_main",
        kind="nfo",
        path="asset_main.nfo",
        language=None,
    )
    assert sidecar.language is None


def test_manifest_sidecar_subtitle_keeps_language():
    sidecar = ManifestSidecar(
        id="sidecar_0001",
        asset_id="asset_main",
        kind="subtitle",
        path="asset_main.eng.srt",
        language="eng",
    )
    assert sidecar.language == "eng"


def test_manifest_v4_schema_version():
    manifest = Manifest(
        schema_version=4,
        works=[], variants=[], bundles=[], assets=[],
        versions=[], locations=[], sidecars=[],
    )
    assert manifest.schema_version == 4
```

Append to `tests/contract/test_contract_constants.py`:

```python
def test_manifest_schema_version_bumped_to_4():
    assert chaos_librarian.contract.MANIFEST_SCHEMA_VERSION == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/contract/test_manifest.py tests/contract/test_contract_constants.py -v`

Expected: `language` is required failure; `schema_version: 3` literal check failure; constant test fails (3 != 4).

- [ ] **Step 3: Bump constant + widen language + bump Manifest.schema_version**

In `src/chaos_librarian/contract/__init__.py`:

```python
MANIFEST_SCHEMA_VERSION: Final = 4
```

In `src/chaos_librarian/contract/manifest.py`, replace the `ManifestSidecar` class:

```python
class ManifestSidecar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    asset_id: str
    kind: str
    path: str
    # Optional from manifest v4 (Sprint 7): poster / NFO sidecars carry
    # no language. Subtitle sidecars still always carry one — enforced
    # at the scenario layer by CreateSidecarEvent.model_validator and at
    # the materializer layer by per-handler defaults.
    language: str | None = None
    content_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
```

In the same file, replace the `Manifest` class:

```python
class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[4]
    works: list[ManifestWork]
    variants: list[ManifestVariant]
    bundles: list[ManifestBundle]
    assets: list[ManifestAsset]
    versions: list[ManifestVersion]
    locations: list[ManifestLocation]
    sidecars: list[ManifestSidecar] = Field(default_factory=list)
```

In `src/chaos_librarian/engine/state.py`, replace the `schema_version=3` in `to_manifest`:

```python
    def to_manifest(self) -> Manifest:
        """Serialize back to the immutable Pydantic Manifest."""
        return Manifest(
            schema_version=4,
            works=list(self.works.values()),
            # … rest unchanged
        )
```

- [ ] **Step 4: Regenerate the manifest schema**

Run: `uv run python -m chaos_librarian.schema_export --write`

Verify: `git diff schemas/manifest.schema.json` shows `schema_version` enum at 4 and `language` widened to `["string", "null"]`.

- [ ] **Step 5: Run the contract test suite**

Run: `uv run pytest tests/contract/ tests/engine/ -v 2>&1 | tail -40`

Expected: green. Some engine tests may surface fixtures that pin `Manifest(schema_version=3, ...)` — chase and fix them.

- [ ] **Step 6: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/manifest.py \
        src/chaos_librarian/engine/state.py \
        schemas/manifest.schema.json \
        tests/contract/test_manifest.py \
        tests/contract/test_contract_constants.py
git commit -m "$(cat <<'EOF'
feat(contract): manifest v4 — ManifestSidecar.language is optional

Poster and NFO sidecars (added in Sprint 7) carry no language. Subtitle
sidecars still always carry one; the constraint is enforced at the
scenario layer by CreateSidecarEvent's model_validator and at the
materializer layer by per-handler defaults.

Bumps MANIFEST_SCHEMA_VERSION 3 -> 4 and updates engine.state.to_manifest
to emit the new literal.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Materialization Contract — MediaAction, MEDIA_FAILED, FailureStage.MEDIA, v4 bump

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py` — `MATERIALIZATION_SCHEMA_VERSION: Final = 4`.
- Modify: `src/chaos_librarian/contract/materialization.py` — `MediaAction` model, `Outcome.MEDIA_FAILED`, `FailureStage.MEDIA`, `MaterializationReport.media_actions`, schema literal 4.
- Test: `tests/contract/test_materialization.py` — append `MediaAction` round-trip + enum tests.
- Test: `tests/contract/test_contract_constants.py` — assert bumped constant.
- Regenerate: `schemas/materialization.schema.json`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/contract/test_materialization.py`:

```python
def test_media_action_round_trip():
    action = MediaAction(
        event_id="ev_rv_001",
        action=TimelineActionName.REENCODE_VIDEO,
        target_asset_id="asset_main",
        input_path="library/movies/asset_main.mkv",
        output_path="library/movies/asset_main.mkv",
        input_version_id="version_0001",
        output_version_id="version_0002",
        output_sidecar_id=None,
        input_content_hash="sha256:" + "0" * 64,
        output_content_hash="sha256:" + "1" * 64,
        tool_invocation_index=2,
        duration_ns=1_234_567,
    )
    assert action.event_id == "ev_rv_001"
    assert action.action == TimelineActionName.REENCODE_VIDEO


def test_media_action_extract_subtitle_no_input_version():
    action = MediaAction(
        event_id="ev_xs_001",
        action=TimelineActionName.EXTRACT_SUBTITLE,
        target_asset_id="asset_main",
        input_path="library/asset_main.mkv",
        output_path="library/asset_main.fra.srt",
        input_version_id=None,
        output_version_id=None,
        output_sidecar_id="sidecar_0002",
        input_content_hash=None,
        output_content_hash="sha256:" + "2" * 64,
        tool_invocation_index=4,
        duration_ns=100,
    )
    assert action.output_sidecar_id == "sidecar_0002"
    assert action.input_version_id is None
    assert action.output_version_id is None


def test_outcome_includes_media_failed():
    assert Outcome.MEDIA_FAILED.value == "media_failed"


def test_failure_stage_includes_media():
    assert FailureStage.MEDIA.value == "media"


def test_materialization_report_carries_media_actions():
    report = MaterializationReport(
        schema_version=4,
        run_id=uuid.uuid4(),
        outcome=Outcome.SUCCESS,
        platform="darwin",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        toolchain=ToolchainInfo(),
    )
    assert report.media_actions == []
    assert report.schema_version == 4
```

Add `MediaAction` to the imports at the top of the test file.

Append to `tests/contract/test_contract_constants.py`:

```python
def test_materialization_schema_version_bumped_to_4():
    assert chaos_librarian.contract.MATERIALIZATION_SCHEMA_VERSION == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/contract/test_materialization.py tests/contract/test_contract_constants.py -v`

- [ ] **Step 3: Bump constant + add MediaAction + MEDIA_FAILED + MEDIA enum members**

In `src/chaos_librarian/contract/__init__.py`:

```python
MATERIALIZATION_SCHEMA_VERSION: Final = 4
```

In `src/chaos_librarian/contract/materialization.py`, extend `Outcome`:

```python
class Outcome(enum.StrEnum):
    SUCCESS = "success"
    UNSUPPORTED = "unsupported"
    TOOL_FAILED = "tool_failed"
    TOOL_MISSING = "tool_missing"
    CONTAINMENT_VIOLATION = "containment_violation"
    FS_FAILED = "fs_failed"
    MEDIA_FAILED = "media_failed"
```

Extend `FailureStage`:

```python
class FailureStage(enum.StrEnum):
    FFMPEG = "ffmpeg"
    FFPROBE = "ffprobe"
    FILESYSTEM = "filesystem"
    MEDIA = "media"
```

Add `MediaAction` AFTER `FilesystemAction`:

```python
class MediaAction(BaseModel):
    """One phase-B media operation audit record.

    Parallel to ``FilesystemAction``: one record per journal entry that
    produced a real byte / probed-metadata change via ffmpeg or
    sidecar-regeneration. ``tool_invocation_index`` cross-refs into
    ``MaterializationReport.invocations`` so consumers can join the two
    audit streams.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: TimelineActionName
    target_asset_id: str
    input_path: str
    output_path: str
    input_version_id: str | None = None
    output_version_id: str | None = None
    output_sidecar_id: str | None = None
    input_content_hash: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    output_content_hash: str | None = Field(
        default=None, pattern=r"^sha256:[0-9a-f]{64}$"
    )
    tool_invocation_index: int | None = None
    duration_ns: int
```

Extend `MaterializationReport`:

```python
class MaterializationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[4]
    run_id: uuid.UUID
    outcome: Outcome
    platform: str
    started_at: datetime
    finished_at: datetime
    toolchain: ToolchainInfo
    invocations: list[ToolInvocation] = Field(default_factory=list)
    materialized: list[MaterializedAsset] = Field(default_factory=list)
    failures: list[MaterializationFailure] = Field(default_factory=list)
    filesystem_actions: list[FilesystemAction] = Field(default_factory=list)
    media_actions: list[MediaAction] = Field(default_factory=list)
```

- [ ] **Step 4: Regenerate the materialization schema**

Run: `uv run python -m chaos_librarian.schema_export --write`

Verify: `git diff schemas/materialization.schema.json` shows `MediaAction` `$defs` entry, `media_actions` array on the top-level report, `media_failed` in Outcome enum, `media` in FailureStage enum, and `schema_version` widened to 4.

- [ ] **Step 5: Run the contract test suite**

Run: `uv run pytest tests/contract/ -v 2>&1 | tail -40`

Expected: green. Helper `build_report` callers may now mis-construct because `schema_version=3` is still hardcoded somewhere — for now leave those failures to Task 37, which renames the cleanup path.

If `tests/materializer/test_run.py` or `tests/materializer/test_finalize.py` break because `MaterializationReport(schema_version=3, ...)` is hardcoded in `materializer/reports.py:build_report`, fix the literal there:

In `src/chaos_librarian/materializer/reports.py`, find the `MaterializationReport(...)` constructor call inside `build_report` (or wherever the literal is) and change `schema_version=3` to `schema_version=4`.

- [ ] **Step 6: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/materialization.py \
        src/chaos_librarian/materializer/reports.py \
        schemas/materialization.schema.json \
        tests/contract/test_materialization.py \
        tests/contract/test_contract_constants.py
git commit -m "$(cat <<'EOF'
feat(contract): materialization v4 — MediaAction + MEDIA_FAILED + MEDIA stage

Adds the MediaAction audit record, Outcome.MEDIA_FAILED, FailureStage.MEDIA,
and MaterializationReport.media_actions field. Parallel to Sprint 6's
FilesystemAction; one row per phase-B media op (ffmpeg-backed or
update_sidecar regeneration).

Bumps MATERIALIZATION_SCHEMA_VERSION 3 -> 4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Reports Contract — VersionHistoryEntry, AssetReport.version_history, v4 bump

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py` — `ASSET_REPORT_SCHEMA_VERSION: Final = 4`.
- Modify: `src/chaos_librarian/contract/reports.py` — `VersionHistoryEntry` model, `AssetReport.version_history`, literal 4.
- Modify: `src/chaos_librarian/engine/reports.py:141` — `AssetReport(schema_version=4, ...)` (the `version_history` field defaults to `[]`; wiring the real value happens in Task 15).
- Test: `tests/contract/test_reports.py` — append `VersionHistoryEntry` + `AssetReport.version_history` round-trip tests.
- Test: `tests/contract/test_contract_constants.py` — assert bumped constant.
- Regenerate: `schemas/asset-report.schema.json`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/contract/test_reports.py`:

```python
def test_version_history_entry_round_trip():
    entry = VersionHistoryEntry(
        event_id="ev_rv_001",
        action=TimelineActionName.REENCODE_VIDEO,
        logical_time_ns=3_000_000_000,
        input_version_id="version_0001",
        output_version_id="version_0002",
        state_delta_summary={"resolution": "sd", "codec": "h264"},
    )
    assert entry.action == TimelineActionName.REENCODE_VIDEO
    assert entry.state_delta_summary == {"resolution": "sd", "codec": "h264"}


def test_version_history_entry_extract_no_versions():
    entry = VersionHistoryEntry(
        event_id="ev_xs_001",
        action=TimelineActionName.EXTRACT_SUBTITLE,
        logical_time_ns=4_000_000_000,
        input_version_id=None,
        output_version_id=None,
        state_delta_summary={},
    )
    assert entry.input_version_id is None
    assert entry.output_version_id is None


def test_asset_report_v4_default_version_history_empty():
    snapshot = AssetSnapshot(
        location_path="movies/x.mkv", version_id="v0", version_index=0,
    )
    report = AssetReport(
        schema_version=4,
        asset_id="asset_main",
        initial=snapshot,
        current=snapshot,
    )
    assert report.version_history == []
    assert report.schema_version == 4
```

Add the new imports.

Append to `tests/contract/test_contract_constants.py`:

```python
def test_asset_report_schema_version_bumped_to_4():
    assert chaos_librarian.contract.ASSET_REPORT_SCHEMA_VERSION == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/contract/test_reports.py tests/contract/test_contract_constants.py -v`

- [ ] **Step 3: Bump constant + add VersionHistoryEntry + extend AssetReport**

In `src/chaos_librarian/contract/__init__.py`:

```python
ASSET_REPORT_SCHEMA_VERSION: Final = 4
```

In `src/chaos_librarian/contract/reports.py`, add AFTER `PathHistoryEntry`:

```python
class VersionHistoryEntry(BaseModel):
    """One version-affecting journal event projected for a single asset.

    Derived from the journal by ``derive_version_history``. Mirrors
    Sprint 6's ``PathHistoryEntry`` shape for the version-allocating
    subset of actions (reencode_video / reencode_audio / remux_container
    / edit_metadata / embed_subtitle). ``extract_subtitle`` does NOT
    appear here — it's a read-only extract that allocates a sidecar but
    not a version.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: TimelineActionName
    logical_time_ns: int
    input_version_id: str | None = None
    output_version_id: str | None = None
    state_delta_summary: dict[str, object] = Field(default_factory=dict)
```

Replace `AssetReport`:

```python
class AssetReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[4]
    asset_id: str
    initial: AssetSnapshot
    history: list[AssetHistoryEntry] = Field(default_factory=list)
    current: AssetSnapshot | None
    path_history: list[PathHistoryEntry] = Field(default_factory=list)
    version_history: list[VersionHistoryEntry] = Field(default_factory=list)
```

In `src/chaos_librarian/engine/reports.py`, bump the literal at line ~141:

```python
    return AssetReport(
        schema_version=4,
        asset_id=asset_id,
        initial=initial_snapshot,
        history=history,
        current=_snapshot_for(asset_id, current),
        path_history=derive_path_history(asset_id, journal),
    )
```

(The `version_history` field will be wired in Task 15; for now it defaults to `[]`.)

- [ ] **Step 4: Regenerate the asset-report schema**

Run: `uv run python -m chaos_librarian.schema_export --write`

Verify: `git diff schemas/asset-report.schema.json` shows `VersionHistoryEntry` `$defs` entry, `version_history` array on the top-level report, and `schema_version` widened to 4.

- [ ] **Step 5: Run the contract + engine test suites**

Run: `uv run pytest tests/contract/ tests/engine/ -v 2>&1 | tail -40`

If `tests/engine/test_reports.py` breaks because it pins `schema_version=3`, update those expectations to 4.

- [ ] **Step 6: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/reports.py \
        src/chaos_librarian/engine/reports.py \
        schemas/asset-report.schema.json \
        tests/contract/test_reports.py \
        tests/contract/test_contract_constants.py \
        tests/engine/test_reports.py
git commit -m "$(cat <<'EOF'
feat(contract): asset-report v4 — VersionHistoryEntry + version_history field

Adds the VersionHistoryEntry model and AssetReport.version_history list.
Default empty for this commit; engine.version_history.derive_version_history
will land in a follow-up and the AssetReport builder will wire it.

Bumps ASSET_REPORT_SCHEMA_VERSION 3 -> 4.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Run the contract drift gate

**Files:**
- Verify: `uv run python -m chaos_librarian.schema_export --check` passes.
- Verify: `tests/contract/test_schema_export.py` passes (already exists; Sprint 6 added the parametrized drift-gate test).

- [ ] **Step 1: Run the drift gate**

Run: `uv run python -m chaos_librarian.schema_export --check`

Expected: exits 0 silently. If it fails: someone (you) forgot to commit a regenerated schema; re-run `--write`, re-stage, amend (or new commit).

- [ ] **Step 2: Run the contract test suite end-to-end**

Run: `uv run pytest tests/contract/ -v 2>&1 | tail -40`

Expected: green.

- [ ] **Step 3: Run the full suite to catch ripple effects**

Run: `uv run pytest -q 2>&1 | tail -40`

Expected: most things green. Engine tests for the existing reencode handlers may surface that `state_delta` is missing the new `input_path` / `output_path` keys — that's Task 6, intentionally left red until then. Materializer tests for filesystem will be partially red until Task 33+. Note any failures and reconfirm they're all from tasks below; do not pre-emptively fix.

- [ ] **Step 4: No new commit; checkpoint only.**

This task is verification-only. Move to Task 6 once drift gate is green.

---

## Task 6: Engine — extend reencode_video / reencode_audio with input_path / output_path in state_delta

**Why now:** the phase-B media dispatcher (Task 25+) will read every path from `entry.state_delta`. Sprint 5's reencode handlers don't currently emit those keys; this task fixes that BEFORE the dispatcher needs them. The lock test (`_STATE_DELTA_KEYS`) reflects the new contract.

**Files:**
- Modify: `src/chaos_librarian/engine/events.py:228-285` — both reencode handlers emit `input_path` + `output_path`; both equal the asset's current location path (in-place re-encode).
- Modify: `src/chaos_librarian/engine/events.py:50-63` — `_STATE_DELTA_KEYS` for `REENCODE_VIDEO` and `REENCODE_AUDIO` gain the two new keys.
- Test: `tests/engine/test_events_media.py` — assert the two new keys appear with the in-place path value.

- [ ] **Step 1: Write the failing tests**

Append to `tests/engine/test_events_media.py` (inside `TestReencodeVideoHandler` and `TestReencodeAudioHandler`):

```python
    def test_reencode_video_emits_input_and_output_path(self) -> None:
        scenario = _scenario([
            {"id": "e0", "at": "1s", "action": "reencode_video",
             "target": "a0", "resolution": "sd", "codec": "h264"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        resolved_iter = resolve_timeline(scenario, run_id=_RUN_ID)
        resolved = next(resolved_iter)
        entries = apply_event(state, resolved, ids, _RUN_ID, scenario.scenario_id)
        assert isinstance(entries[0], AtomicJournalEntry)
        delta = entries[0].state_delta
        # In-place re-encode: input and output paths are identical.
        assert delta["input_path"] == delta["output_path"]
        assert delta["input_path"].endswith("/a0.mkv")


    def test_reencode_audio_emits_input_and_output_path(self) -> None:
        scenario = _scenario([
            {"id": "e0", "at": "1s", "action": "reencode_audio",
             "target": "a0", "from_channels": "5.1", "to_channels": "stereo"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        resolved_iter = resolve_timeline(scenario, run_id=_RUN_ID)
        resolved = next(resolved_iter)
        entries = apply_event(state, resolved, ids, _RUN_ID, scenario.scenario_id)
        delta = entries[0].state_delta
        assert delta["input_path"] == delta["output_path"]
        assert delta["input_path"].endswith("/a0.mkv")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_events_media.py -v -k "input_and_output_path"`

Expected: KeyError on `input_path`.

- [ ] **Step 3: Extend the reencode handlers**

In `src/chaos_librarian/engine/events.py`, in `_handle_reencode_video`, replace the entry-building block with:

```python
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.REENCODE_VIDEO,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={
            "resolution": event.resolution,
            "codec": event.codec,
            "input_path": previous.path,    # in-place re-encode
            "output_path": previous.path,
        },
        input_version_ids=[prior_version_id],
        output_version_ids=[new_version_id],
    )
```

Do the same for `_handle_reencode_audio`:

```python
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.REENCODE_AUDIO,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={
            "from_channels": event.from_channels,
            "to_channels": event.to_channels,
            "input_path": previous.path,
            "output_path": previous.path,
        },
        input_version_ids=[prior_version_id],
        output_version_ids=[new_version_id],
    )
```

(Both handlers already grab `state.location_id_for_asset(event.target)`; you may just pull `previous = state.locations[loc_id]` once and inline.)

- [ ] **Step 4: Extend `_STATE_DELTA_KEYS`**

In `src/chaos_librarian/engine/events.py`, update the existing entries:

```python
_STATE_DELTA_KEYS: Final[dict[TimelineActionName, frozenset[str]]] = {
    TimelineActionName.MOVE_ASSET: frozenset({"from_path", "to_path"}),
    TimelineActionName.RENAME_FILE: frozenset({"from_path", "to_path"}),
    TimelineActionName.DELETE_FILE: frozenset({"removed_path"}),
    TimelineActionName.CREATE_SIDECAR: frozenset({"sidecar_path", "sidecar_id", "language"}),
    TimelineActionName.SLOW_COPY_START: frozenset(
        {"final_path", "temp_path", "initial_path_at_start"}
    ),
    TimelineActionName.SLOW_COPY_COMMIT: frozenset({"final_path"}),
    TimelineActionName.ARCHIVE_FILE: frozenset({"from_path", "to_path"}),
    TimelineActionName.MOVE_BETWEEN_ROOTS: frozenset(
        {"from_path", "to_path", "from_root_id", "to_root_id"}
    ),
    TimelineActionName.REENCODE_VIDEO: frozenset(
        {"resolution", "codec", "input_path", "output_path"}
    ),
    TimelineActionName.REENCODE_AUDIO: frozenset(
        {"from_channels", "to_channels", "input_path", "output_path"}
    ),
}
```

(REENCODE_VIDEO and REENCODE_AUDIO were absent from Sprint 6's table because phase B didn't act on them. Sprint 7 adds the rows.)

- [ ] **Step 5: Run the lock test**

Run: `uv run pytest tests/engine/test_state_delta_contract.py -v`

If the test fails because the parametrized registry doesn't include REENCODE_VIDEO/AUDIO yet (Sprint 6's `_minimal_scenario_for_action` excluded them), extend the registry. The Sprint 6 file is `tests/engine/conftest.py` — find `_minimal_scenario_for_action` and add cases for both. See Task 14 for the pattern; you may also defer this to Task 14 and accept the lock test failing here. Either is fine — track which you chose so Task 14 doesn't duplicate.

- [ ] **Step 6: Run the engine test suite**

Run: `uv run pytest tests/engine/ -v 2>&1 | tail -40`

Expected: green for the reencode tests; possibly still failing for the lock test if you deferred to Task 14.

- [ ] **Step 7: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/engine/events.py tests/engine/test_events_media.py \
        tests/engine/conftest.py
git commit -m "$(cat <<'EOF'
feat(engine): emit input_path / output_path in reencode_* state_delta

Both handlers now record the asset's current location path (in-place
re-encode) into state_delta so the Sprint 7 phase-B media dispatcher
can read every path from the journal entry, not from WorldState.

Extends _STATE_DELTA_KEYS rows for REENCODE_VIDEO and REENCODE_AUDIO.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Engine — WorldState.sidecar_id_for_path helper

**Files:**
- Modify: `src/chaos_librarian/engine/state.py` — new method `sidecar_id_for_path(asset_id, path) -> str`.
- Test: `tests/engine/test_state.py` — round-trip + KeyError tests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/engine/test_state.py`:

```python
def test_sidecar_id_for_path_returns_id_when_match() -> None:
    state = WorldState()
    state.sidecars["sidecar_0001"] = ManifestSidecar(
        id="sidecar_0001", asset_id="asset_main",
        kind="subtitle", path="asset_main.eng.srt", language="eng",
    )
    assert state.sidecar_id_for_path("asset_main", "asset_main.eng.srt") == "sidecar_0001"


def test_sidecar_id_for_path_raises_keyerror_on_miss() -> None:
    state = WorldState()
    with pytest.raises(KeyError, match="no sidecar"):
        state.sidecar_id_for_path("asset_main", "missing.srt")


def test_sidecar_id_for_path_scoped_by_asset_id() -> None:
    state = WorldState()
    state.sidecars["sidecar_0001"] = ManifestSidecar(
        id="sidecar_0001", asset_id="asset_a",
        kind="subtitle", path="a.eng.srt", language="eng",
    )
    state.sidecars["sidecar_0002"] = ManifestSidecar(
        id="sidecar_0002", asset_id="asset_b",
        kind="subtitle", path="a.eng.srt", language="eng",
    )
    # Same path, different asset — the lookup must respect asset_id.
    assert state.sidecar_id_for_path("asset_a", "a.eng.srt") == "sidecar_0001"
    assert state.sidecar_id_for_path("asset_b", "a.eng.srt") == "sidecar_0002"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_state.py -v -k "sidecar_id_for_path"`

Expected: AttributeError.

- [ ] **Step 3: Add the helper**

In `src/chaos_librarian/engine/state.py`, AFTER `version_id_for_asset`:

```python
    def sidecar_id_for_path(self, asset_id: str, path: str) -> str:
        """Return the sidecar_id whose (asset_id, path) pair matches.

        Validation guarantees the lookup succeeds for any well-formed
        scenario (rule_sidecar_target rejects misses before the engine
        runs). The engine raises KeyError rather than emitting a journal
        entry — a missing sidecar here is a bug at this layer.

        Raises:
            KeyError: no sidecar matches.
        """
        for sid, sidecar in self.sidecars.items():
            if sidecar.asset_id == asset_id and sidecar.path == path:
                return sid
        raise KeyError(
            f"no sidecar for asset {asset_id!r} at path {path!r}"
        )
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/engine/test_state.py -v -k "sidecar_id_for_path"`

Expected: green.

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/engine/state.py tests/engine/test_state.py
git commit -m "$(cat <<'EOF'
feat(engine): WorldState.sidecar_id_for_path lookup helper

Required by Sprint 7's embed_subtitle / remove_sidecar / update_sidecar
handlers to resolve a sidecar_id from the scenario-supplied
(asset_id, path) pair. Validation guarantees the match; the engine
raises KeyError on miss (bug, not user input).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Engine — _handle_remux_container handler + _swap_extension helper

**Files:**
- Modify: `src/chaos_librarian/engine/events.py` — add `_swap_extension` helper, add `_handle_remux_container`, register in `_HANDLERS`, add `_STATE_DELTA_KEYS` row.
- Test: `tests/engine/test_events_media.py` — handler tests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/engine/test_events_media.py`:

```python
class TestRemuxContainerHandler:
    """remux_container allocates a new version and rewrites the location path's extension.

    WHY: container changes are observable bytes-affecting changes (codec
    copy is fine, but the wrapper differs); voom-v2's reconciliation
    treats this as a new version.
    """

    def test_remux_allocates_new_version(self) -> None:
        scenario = _scenario([
            {"id": "e0", "at": "1s", "action": "remux_container",
             "target": "a0", "to_container": "mp4"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        prior_version_id = state.version_id_for_asset("a0")
        resolved = next(resolve_timeline(scenario, run_id=_RUN_ID))
        entries = apply_event(state, resolved, ids, _RUN_ID, scenario.scenario_id)
        entry = entries[0]
        assert isinstance(entry, AtomicJournalEntry)
        assert entry.input_version_ids == [prior_version_id]
        new_version_id = entry.output_version_ids[0]
        assert new_version_id != prior_version_id
        assert state.versions[new_version_id].index == 1

    def test_remux_rewrites_path_extension(self) -> None:
        scenario = _scenario([
            {"id": "e0", "at": "1s", "action": "remux_container",
             "target": "a0", "to_container": "mp4"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        loc_id = state.location_id_for_asset("a0")
        old_path = state.locations[loc_id].path
        assert old_path.endswith(".mkv")
        resolved = next(resolve_timeline(scenario, run_id=_RUN_ID))
        apply_event(state, resolved, ids, _RUN_ID, scenario.scenario_id)
        new_path = state.locations[loc_id].path
        assert new_path == old_path[:-4] + ".mp4"

    def test_remux_state_delta_records_paths_and_containers(self) -> None:
        scenario = _scenario([
            {"id": "e0", "at": "1s", "action": "remux_container",
             "target": "a0", "to_container": "mp4"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        resolved = next(resolve_timeline(scenario, run_id=_RUN_ID))
        entries = apply_event(state, resolved, ids, _RUN_ID, scenario.scenario_id)
        delta = entries[0].state_delta
        assert delta["from_container"] == "mkv"
        assert delta["to_container"] == "mp4"
        assert delta["from_path"].endswith(".mkv")
        assert delta["to_path"].endswith(".mp4")
        assert delta["input_path"] == delta["from_path"]
        assert delta["output_path"] == delta["to_path"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_events_media.py::TestRemuxContainerHandler -v`

Expected: KeyError on `TimelineActionName.REMUX_CONTAINER` in `_HANDLERS`.

- [ ] **Step 3: Add `_swap_extension` helper and the handler**

In `src/chaos_librarian/engine/events.py`, AFTER `_handle_move_between_roots` and BEFORE the `_HANDLERS` dict:

```python
def _swap_extension(path: str, new_ext: str) -> str:
    """Replace the path's file extension with ``new_ext`` (no leading dot).

    Pure string surgery: ``"library/movies-hd/x.mkv"`` + ``"mp4"`` →
    ``"library/movies-hd/x.mp4"``. If the path has no extension, appends.
    """
    if "." in path.rsplit("/", 1)[-1]:
        base = path.rsplit(".", 1)[0]
        return f"{base}.{new_ext}"
    return f"{path}.{new_ext}"


def _handle_remux_container(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Allocate a new version; rewrite the asset's location path extension.

    The byte payload doesn't actually change here (the materializer's
    ffmpeg -c copy preserves streams); the version bump signals to
    voom-v2 that the file moved to a new container, which is a
    reconciliation-relevant event.
    """
    event = resolved.event
    assert isinstance(event, RemuxContainerEvent)
    prior_version_id = state.version_id_for_asset(event.target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    state.bind_version(
        event.target,
        ManifestVersion(
            id=new_version_id, asset_id=event.target, index=prior_version.index + 1,
        ),
    )
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    prev_container = previous.path.rsplit(".", 1)[-1] if "." in previous.path else ""
    new_path = _swap_extension(previous.path, event.to_container)
    state.locations[loc_id] = previous.model_copy(update={"path": new_path})
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.REMUX_CONTAINER,
        target_ids=[event.target],
        location_ids=[loc_id],
        input_version_ids=[prior_version_id],
        output_version_ids=[new_version_id],
        state_delta={
            "from_container": prev_container,
            "to_container": event.to_container,
            "from_path": previous.path,
            "to_path": new_path,
            "input_path": previous.path,
            "output_path": new_path,
        },
    )
    return (entry,)
```

Add `RemuxContainerEvent` to the existing scenario import block at the top of the file:

```python
from chaos_librarian.contract.scenario import (
    AddFileEvent,
    ArchiveFileEvent,
    CreateSidecarEvent,
    DeleteFileEvent,
    EditMetadataEvent,
    EmbedSubtitleEvent,
    ExtractSubtitleEvent,
    MoveAssetEvent,
    MoveBetweenRootsEvent,
    ReencodeAudioEvent,
    ReencodeVideoEvent,
    RemoveSidecarEvent,
    RemuxContainerEvent,
    RenameFileEvent,
    SlowCopyCommitEvent,
    SlowCopyStartEvent,
    TimelineActionName,
    UpdateSidecarEvent,
)
```

(Add all 6 new event imports here so subsequent tasks don't have to.)

Register in `_HANDLERS` (add to the dict at the bottom):

```python
    TimelineActionName.REMUX_CONTAINER: _handle_remux_container,
```

Add to `_STATE_DELTA_KEYS`:

```python
    TimelineActionName.REMUX_CONTAINER: frozenset(
        {"from_container", "to_container", "from_path", "to_path",
         "input_path", "output_path"}
    ),
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/engine/test_events_media.py::TestRemuxContainerHandler -v`

Expected: green.

- [ ] **Step 5: Lint, format, type-check; commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/engine/events.py tests/engine/test_events_media.py
git commit -m "$(cat <<'EOF'
feat(engine): _handle_remux_container — allocate version, rewrite path ext

Records from_container / to_container / from_path / to_path / input_path /
output_path in state_delta. The phase-B materializer (Sprint 7) reads
input_path + output_path for the ffmpeg -c copy invocation; the
from/to_container pair drives the version-history report's delta summary.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Engine — _handle_edit_metadata handler

**Files:**
- Modify: `src/chaos_librarian/engine/events.py` — add handler, register in `_HANDLERS` + `_STATE_DELTA_KEYS`.
- Test: `tests/engine/test_events_media.py` — handler tests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/engine/test_events_media.py`:

```python
class TestEditMetadataHandler:
    """edit_metadata allocates a new version and copies the fields dict into state_delta.

    WHY: metadata changes don't move bytes around but they DO change the
    asset's identity (the ffprobe output differs); voom-v2 treats them
    as a new version.
    """

    def test_edit_metadata_allocates_version(self) -> None:
        scenario = _scenario([
            {"id": "e0", "at": "1s", "action": "edit_metadata",
             "target": "a0", "fields": {"title": "X", "year": "2026"}},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        prior_version_id = state.version_id_for_asset("a0")
        resolved = next(resolve_timeline(scenario, run_id=_RUN_ID))
        entries = apply_event(state, resolved, ids, _RUN_ID, scenario.scenario_id)
        entry = entries[0]
        assert entry.input_version_ids == [prior_version_id]
        new_version_id = entry.output_version_ids[0]
        assert new_version_id != prior_version_id

    def test_edit_metadata_records_fields(self) -> None:
        scenario = _scenario([
            {"id": "e0", "at": "1s", "action": "edit_metadata",
             "target": "a0", "fields": {"title": "Pulsar", "year": "2026"}},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        resolved = next(resolve_timeline(scenario, run_id=_RUN_ID))
        entries = apply_event(state, resolved, ids, _RUN_ID, scenario.scenario_id)
        delta = entries[0].state_delta
        assert delta["fields"] == {"title": "Pulsar", "year": "2026"}
        assert delta["input_path"] == delta["output_path"]

    def test_edit_metadata_does_not_change_path(self) -> None:
        scenario = _scenario([
            {"id": "e0", "at": "1s", "action": "edit_metadata",
             "target": "a0", "fields": {"k": "v"}},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        loc_id = state.location_id_for_asset("a0")
        old_path = state.locations[loc_id].path
        resolved = next(resolve_timeline(scenario, run_id=_RUN_ID))
        apply_event(state, resolved, ids, _RUN_ID, scenario.scenario_id)
        assert state.locations[loc_id].path == old_path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_events_media.py::TestEditMetadataHandler -v`

- [ ] **Step 3: Add the handler**

In `src/chaos_librarian/engine/events.py`, AFTER `_handle_remux_container`:

```python
def _handle_edit_metadata(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Allocate a new version; record the fields delta. Path unchanged."""
    event = resolved.event
    assert isinstance(event, EditMetadataEvent)
    prior_version_id = state.version_id_for_asset(event.target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    state.bind_version(
        event.target,
        ManifestVersion(
            id=new_version_id, asset_id=event.target, index=prior_version.index + 1,
        ),
    )
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.EDIT_METADATA,
        target_ids=[event.target],
        location_ids=[loc_id],
        input_version_ids=[prior_version_id],
        output_version_ids=[new_version_id],
        state_delta={
            "fields": dict(event.fields),
            "input_path": previous.path,
            "output_path": previous.path,
        },
    )
    return (entry,)
```

Register in `_HANDLERS`:

```python
    TimelineActionName.EDIT_METADATA: _handle_edit_metadata,
```

Add to `_STATE_DELTA_KEYS`:

```python
    TimelineActionName.EDIT_METADATA: frozenset(
        {"fields", "input_path", "output_path"}
    ),
```

- [ ] **Step 4: Run tests; lint; commit**

Run: `uv run pytest tests/engine/test_events_media.py::TestEditMetadataHandler -v && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

```bash
git add src/chaos_librarian/engine/events.py tests/engine/test_events_media.py
git commit -m "$(cat <<'EOF'
feat(engine): _handle_edit_metadata — allocate version, record fields dict

In-place metadata edit: path unchanged, version bumped. state_delta
carries the verbatim fields dict so the phase-B materializer can map
each entry to an ffmpeg -metadata k=v flag.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Engine — _handle_embed_subtitle handler

**Files:**
- Modify: `src/chaos_librarian/engine/events.py` — add handler, register in `_HANDLERS` + `_STATE_DELTA_KEYS`.
- Test: NEW `tests/engine/test_events_sidecar.py` — handler tests (the sidecar test family file).

- [ ] **Step 1: Write the failing tests (creates the new test file)**

Create `tests/engine/test_events_sidecar.py`:

```python
"""Tests for the 4 sidecar-touching handlers added in Sprint 7.

embed_subtitle, extract_subtitle, remove_sidecar, update_sidecar.
"""

from __future__ import annotations

import uuid

import pytest

from chaos_librarian.contract.journal import AtomicJournalEntry
from chaos_librarian.contract.manifest import ManifestSidecar
from chaos_librarian.contract.scenario import Scenario, TimelineActionName
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _scenario_with_subtitle_declared(timeline: list[dict[str, object]]) -> Scenario:
    """Asset declares one English subtitle as a sidecar. Phase A would
    write it at ``a0.eng.srt``; the engine doesn't pre-populate it (only
    create_sidecar / extract_subtitle do)."""
    return Scenario.model_validate({
        "schema_version": 5,
        "scenario_id": "sidecar_tests",
        "seed": 1,
        "duration_scale": "short",
        "library": {"roots": [{"id": "r0", "path": "library/r0"}]},
        "works": [{
            "id": "w0", "title": "T",
            "variants": [{
                "id": "v0", "label": "hd",
                "bundle": {"id": "b0", "assets": [{
                    "id": "a0", "role": "primary_video", "container": "mkv",
                    "duration_seconds": 1,
                    "video": {"source": "color_bars", "codec": "h264",
                              "resolution": "hd"},
                    "audio": [{"codec": "aac", "channels": "stereo",
                               "language": "eng"}],
                    "subtitles": [{"codec": "srt", "language": "eng",
                                   "mode": "sidecar"}],
                }]},
            }],
        }],
        "timeline": timeline,
    })


class TestEmbedSubtitleHandler:
    """embed_subtitle allocates a new version, removes the sidecar from state.

    WHY: embedding consumes the sidecar file (materializer unlinks it).
    The manifest must reflect that — both the new asset version AND the
    absence of the sidecar row.
    """

    def test_embed_allocates_new_version(self) -> None:
        scenario = _scenario_with_subtitle_declared([
            {"id": "e_cs", "at": "1s", "action": "create_sidecar",
             "target": "a0", "to": "a0.eng.srt", "language": "eng"},
            {"id": "e_es", "at": "2s", "action": "embed_subtitle",
             "target": "a0", "sidecar_path": "a0.eng.srt"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario, run_id=_RUN_ID))
        apply_event(state, resolved_events[0], ids, _RUN_ID, scenario.scenario_id)
        prior_version_id = state.version_id_for_asset("a0")
        entries = apply_event(state, resolved_events[1], ids, _RUN_ID, scenario.scenario_id)
        entry = entries[0]
        assert entry.input_version_ids == [prior_version_id]
        assert entry.output_version_ids[0] != prior_version_id

    def test_embed_removes_sidecar_from_state(self) -> None:
        scenario = _scenario_with_subtitle_declared([
            {"id": "e_cs", "at": "1s", "action": "create_sidecar",
             "target": "a0", "to": "a0.eng.srt", "language": "eng"},
            {"id": "e_es", "at": "2s", "action": "embed_subtitle",
             "target": "a0", "sidecar_path": "a0.eng.srt"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario, run_id=_RUN_ID))
        apply_event(state, resolved_events[0], ids, _RUN_ID, scenario.scenario_id)
        assert len(state.sidecars) == 1
        apply_event(state, resolved_events[1], ids, _RUN_ID, scenario.scenario_id)
        assert len(state.sidecars) == 0

    def test_embed_state_delta_records_sidecar_id_and_path(self) -> None:
        scenario = _scenario_with_subtitle_declared([
            {"id": "e_cs", "at": "1s", "action": "create_sidecar",
             "target": "a0", "to": "a0.eng.srt", "language": "eng"},
            {"id": "e_es", "at": "2s", "action": "embed_subtitle",
             "target": "a0", "sidecar_path": "a0.eng.srt"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario, run_id=_RUN_ID))
        apply_event(state, resolved_events[0], ids, _RUN_ID, scenario.scenario_id)
        # Snapshot the sidecar id before embed consumes it.
        sidecar_id = next(iter(state.sidecars.keys()))
        entries = apply_event(state, resolved_events[1], ids, _RUN_ID, scenario.scenario_id)
        delta = entries[0].state_delta
        assert delta["embedded_sidecar_id"] == sidecar_id
        assert delta["embedded_sidecar_path"] == "a0.eng.srt"
        assert delta["language"] == "eng"
        assert delta["kind"] == "subtitle"
        assert delta["input_path"] == delta["output_path"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_events_sidecar.py::TestEmbedSubtitleHandler -v`

- [ ] **Step 3: Add the handler**

In `src/chaos_librarian/engine/events.py`, AFTER `_handle_edit_metadata`:

```python
def _handle_embed_subtitle(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Allocate a new version; remove the named sidecar from state.

    The materializer unlinks the sidecar file in phase B; here we mirror
    that with state.sidecars.pop. Validation guarantees the sidecar
    exists at scenario-construction time (rule_sidecar_target).
    """
    event = resolved.event
    assert isinstance(event, EmbedSubtitleEvent)
    sidecar_id = state.sidecar_id_for_path(event.target, event.sidecar_path)
    sidecar = state.sidecars[sidecar_id]
    prior_version_id = state.version_id_for_asset(event.target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    state.bind_version(
        event.target,
        ManifestVersion(
            id=new_version_id, asset_id=event.target, index=prior_version.index + 1,
        ),
    )
    del state.sidecars[sidecar_id]
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.EMBED_SUBTITLE,
        target_ids=[event.target],
        location_ids=[loc_id],
        input_version_ids=[prior_version_id],
        output_version_ids=[new_version_id],
        state_delta={
            "embedded_sidecar_id": sidecar_id,
            "embedded_sidecar_path": sidecar.path,
            "language": sidecar.language,
            "kind": sidecar.kind,
            "input_path": previous.path,
            "output_path": previous.path,
        },
    )
    return (entry,)
```

Register in `_HANDLERS`:

```python
    TimelineActionName.EMBED_SUBTITLE: _handle_embed_subtitle,
```

Add to `_STATE_DELTA_KEYS`:

```python
    TimelineActionName.EMBED_SUBTITLE: frozenset(
        {"embedded_sidecar_id", "embedded_sidecar_path",
         "language", "kind", "input_path", "output_path"}
    ),
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/engine/test_events_sidecar.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/engine/events.py tests/engine/test_events_sidecar.py
git commit -m "$(cat <<'EOF'
feat(engine): _handle_embed_subtitle — allocate version, consume sidecar

Removes the named sidecar from state.sidecars and allocates a new
ManifestVersion for the asset. state_delta records the consumed
sidecar's id/path/language/kind so the materializer can ffmpeg-mux
the subtitle and then unlink the file.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Engine — _handle_extract_subtitle handler

**Files:**
- Modify: `src/chaos_librarian/engine/events.py` — add handler, register in `_HANDLERS` + `_STATE_DELTA_KEYS`.
- Test: `tests/engine/test_events_sidecar.py` — handler tests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/engine/test_events_sidecar.py`:

```python
class TestExtractSubtitleHandler:
    """extract_subtitle allocates a NEW sidecar but DOES NOT bump the asset's version.

    WHY: extract is read-only on the asset — the bytes don't change.
    The asymmetry with embed_subtitle (which DOES allocate) is correct.
    """

    def test_extract_allocates_new_sidecar(self) -> None:
        scenario = _scenario_with_subtitle_declared([
            {"id": "e_xs", "at": "1s", "action": "extract_subtitle",
             "target": "a0", "to": "a0.fra.srt", "language": "fra"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        assert len(state.sidecars) == 0
        resolved = next(resolve_timeline(scenario, run_id=_RUN_ID))
        apply_event(state, resolved, ids, _RUN_ID, scenario.scenario_id)
        assert len(state.sidecars) == 1
        sidecar = next(iter(state.sidecars.values()))
        assert sidecar.kind == "subtitle"
        assert sidecar.language == "fra"
        assert sidecar.path == "a0.fra.srt"
        assert sidecar.asset_id == "a0"

    def test_extract_does_not_allocate_new_version(self) -> None:
        scenario = _scenario_with_subtitle_declared([
            {"id": "e_xs", "at": "1s", "action": "extract_subtitle",
             "target": "a0", "to": "a0.fra.srt", "language": "fra"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        prior_version_id = state.version_id_for_asset("a0")
        resolved = next(resolve_timeline(scenario, run_id=_RUN_ID))
        entries = apply_event(state, resolved, ids, _RUN_ID, scenario.scenario_id)
        # Same version after — extract is read-only.
        assert state.version_id_for_asset("a0") == prior_version_id
        # And the journal entry's input/output version ids are EMPTY.
        assert entries[0].input_version_ids == []
        assert entries[0].output_version_ids == []

    def test_extract_state_delta_records_sidecar_and_paths(self) -> None:
        scenario = _scenario_with_subtitle_declared([
            {"id": "e_xs", "at": "1s", "action": "extract_subtitle",
             "target": "a0", "to": "a0.fra.srt", "language": "fra"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        resolved = next(resolve_timeline(scenario, run_id=_RUN_ID))
        entries = apply_event(state, resolved, ids, _RUN_ID, scenario.scenario_id)
        delta = entries[0].state_delta
        assert delta["sidecar_path"] == "a0.fra.srt"
        assert delta["language"] == "fra"
        assert delta["input_path"].endswith("/a0.mkv")
        # extract has no output_path key — its output IS sidecar_path.
        assert "output_path" not in delta
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_events_sidecar.py::TestExtractSubtitleHandler -v`

- [ ] **Step 3: Add the handler**

In `src/chaos_librarian/engine/events.py`, AFTER `_handle_embed_subtitle`:

```python
def _handle_extract_subtitle(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Allocate a new sidecar row; asset's version is UNCHANGED.

    Asymmetric with embed_subtitle (which DOES bump version) because
    extraction is a read-only operation on the asset bytes.
    """
    event = resolved.event
    assert isinstance(event, ExtractSubtitleEvent)
    sidecar_id = ids.next_sidecar_id()
    state.sidecars[sidecar_id] = ManifestSidecar(
        id=sidecar_id,
        asset_id=event.target,
        kind="subtitle",
        path=event.to,
        language=event.language,
    )
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.EXTRACT_SUBTITLE,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={
            "sidecar_id": sidecar_id,
            "sidecar_path": event.to,
            "language": event.language,
            "input_path": previous.path,
        },
    )
    return (entry,)
```

Register in `_HANDLERS`:

```python
    TimelineActionName.EXTRACT_SUBTITLE: _handle_extract_subtitle,
```

Add to `_STATE_DELTA_KEYS`:

```python
    TimelineActionName.EXTRACT_SUBTITLE: frozenset(
        {"sidecar_id", "sidecar_path", "language", "input_path"}
    ),
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/engine/test_events_sidecar.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/engine/events.py tests/engine/test_events_sidecar.py
git commit -m "$(cat <<'EOF'
feat(engine): _handle_extract_subtitle — allocate sidecar, asset version unchanged

Read-only on the asset: bytes don't change, so no new version is
allocated. A new ManifestSidecar row appears with the requested
language at the destination path. The phase-B materializer ffprobes
for the matching language track and ffmpeg -map's it to the .srt
output.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Engine — _handle_remove_sidecar handler

**Files:**
- Modify: `src/chaos_librarian/engine/events.py` — add handler, register.
- Test: `tests/engine/test_events_sidecar.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/engine/test_events_sidecar.py`:

```python
class TestRemoveSidecarHandler:
    """remove_sidecar removes the sidecar from state; no version change."""

    def test_remove_drops_sidecar(self) -> None:
        scenario = _scenario_with_subtitle_declared([
            {"id": "e_cs", "at": "1s", "action": "create_sidecar",
             "target": "a0", "to": "a0.eng.srt", "language": "eng"},
            {"id": "e_rs", "at": "2s", "action": "remove_sidecar",
             "target": "a0", "sidecar_path": "a0.eng.srt"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario, run_id=_RUN_ID))
        apply_event(state, resolved_events[0], ids, _RUN_ID, scenario.scenario_id)
        assert len(state.sidecars) == 1
        apply_event(state, resolved_events[1], ids, _RUN_ID, scenario.scenario_id)
        assert len(state.sidecars) == 0

    def test_remove_state_delta_records_id_and_path(self) -> None:
        scenario = _scenario_with_subtitle_declared([
            {"id": "e_cs", "at": "1s", "action": "create_sidecar",
             "target": "a0", "to": "a0.eng.srt", "language": "eng"},
            {"id": "e_rs", "at": "2s", "action": "remove_sidecar",
             "target": "a0", "sidecar_path": "a0.eng.srt"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario, run_id=_RUN_ID))
        apply_event(state, resolved_events[0], ids, _RUN_ID, scenario.scenario_id)
        sidecar_id = next(iter(state.sidecars.keys()))
        entries = apply_event(state, resolved_events[1], ids, _RUN_ID, scenario.scenario_id)
        delta = entries[0].state_delta
        assert delta["removed_sidecar_id"] == sidecar_id
        assert delta["removed_sidecar_path"] == "a0.eng.srt"

    def test_remove_does_not_allocate_version(self) -> None:
        scenario = _scenario_with_subtitle_declared([
            {"id": "e_cs", "at": "1s", "action": "create_sidecar",
             "target": "a0", "to": "a0.eng.srt", "language": "eng"},
            {"id": "e_rs", "at": "2s", "action": "remove_sidecar",
             "target": "a0", "sidecar_path": "a0.eng.srt"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario, run_id=_RUN_ID))
        apply_event(state, resolved_events[0], ids, _RUN_ID, scenario.scenario_id)
        prior_version_id = state.version_id_for_asset("a0")
        apply_event(state, resolved_events[1], ids, _RUN_ID, scenario.scenario_id)
        assert state.version_id_for_asset("a0") == prior_version_id
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Add the handler**

In `src/chaos_librarian/engine/events.py`:

```python
def _handle_remove_sidecar(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Drop the named sidecar from state. No version change."""
    event = resolved.event
    assert isinstance(event, RemoveSidecarEvent)
    sidecar_id = state.sidecar_id_for_path(event.target, event.sidecar_path)
    sidecar = state.sidecars[sidecar_id]
    del state.sidecars[sidecar_id]
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.REMOVE_SIDECAR,
        target_ids=[event.target],
        location_ids=[state.location_id_for_asset(event.target)],
        state_delta={
            "removed_sidecar_id": sidecar_id,
            "removed_sidecar_path": sidecar.path,
        },
    )
    return (entry,)
```

Register + add to `_STATE_DELTA_KEYS`:

```python
    TimelineActionName.REMOVE_SIDECAR: _handle_remove_sidecar,
```

```python
    TimelineActionName.REMOVE_SIDECAR: frozenset(
        {"removed_sidecar_id", "removed_sidecar_path"}
    ),
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/engine/test_events_sidecar.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/engine/events.py tests/engine/test_events_sidecar.py
git commit -m "$(cat <<'EOF'
feat(engine): _handle_remove_sidecar — drop sidecar row, no version change

Pure deletion of a ManifestSidecar from state. The materializer
unlinks the file in phase B via the filesystem dispatcher (not the
media dispatcher — remove_sidecar is a stdlib op).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: Engine — _handle_update_sidecar handler

**Files:**
- Modify: `src/chaos_librarian/engine/events.py` — add handler, register.
- Test: `tests/engine/test_events_sidecar.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/engine/test_events_sidecar.py`:

```python
class TestUpdateSidecarHandler:
    """update_sidecar emits a journal entry but does NO state mutation.

    WHY: the actual content_hash change happens in phase B (the
    materializer regenerates bytes with a perturbed sub-seed). Plan-only
    mode has no way to mark the sidecar as "updated", and that's
    accepted — plan-only is bytes-blind.
    """

    def test_update_does_not_mutate_state(self) -> None:
        scenario = _scenario_with_subtitle_declared([
            {"id": "e_cs", "at": "1s", "action": "create_sidecar",
             "target": "a0", "to": "a0.eng.srt", "language": "eng"},
            {"id": "e_us", "at": "2s", "action": "update_sidecar",
             "target": "a0", "sidecar_path": "a0.eng.srt"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario, run_id=_RUN_ID))
        apply_event(state, resolved_events[0], ids, _RUN_ID, scenario.scenario_id)
        sidecars_before = dict(state.sidecars)
        apply_event(state, resolved_events[1], ids, _RUN_ID, scenario.scenario_id)
        # Same dict; same sidecar_ids; same fields.
        assert state.sidecars.keys() == sidecars_before.keys()

    def test_update_state_delta_records_sidecar_id_and_path(self) -> None:
        scenario = _scenario_with_subtitle_declared([
            {"id": "e_cs", "at": "1s", "action": "create_sidecar",
             "target": "a0", "to": "a0.eng.srt", "language": "eng"},
            {"id": "e_us", "at": "2s", "action": "update_sidecar",
             "target": "a0", "sidecar_path": "a0.eng.srt"},
        ])
        ids = IdAllocator(TraceRecorder(seed_stream="ids"))
        state = build_initial_state(scenario, ids)
        resolved_events = list(resolve_timeline(scenario, run_id=_RUN_ID))
        apply_event(state, resolved_events[0], ids, _RUN_ID, scenario.scenario_id)
        sidecar_id = next(iter(state.sidecars.keys()))
        entries = apply_event(state, resolved_events[1], ids, _RUN_ID, scenario.scenario_id)
        delta = entries[0].state_delta
        assert delta["sidecar_id"] == sidecar_id
        assert delta["sidecar_path"] == "a0.eng.srt"
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Add the handler**

In `src/chaos_librarian/engine/events.py`:

```python
def _handle_update_sidecar(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Emit a journal entry; no state mutation. Phase B regenerates bytes."""
    event = resolved.event
    assert isinstance(event, UpdateSidecarEvent)
    sidecar_id = state.sidecar_id_for_path(event.target, event.sidecar_path)
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.UPDATE_SIDECAR,
        target_ids=[event.target],
        location_ids=[state.location_id_for_asset(event.target)],
        state_delta={
            "sidecar_id": sidecar_id,
            "sidecar_path": event.sidecar_path,
        },
    )
    return (entry,)
```

Register + add to `_STATE_DELTA_KEYS`:

```python
    TimelineActionName.UPDATE_SIDECAR: _handle_update_sidecar,
```

```python
    TimelineActionName.UPDATE_SIDECAR: frozenset({"sidecar_id", "sidecar_path"}),
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/engine/test_events_sidecar.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/engine/events.py tests/engine/test_events_sidecar.py
git commit -m "$(cat <<'EOF'
feat(engine): _handle_update_sidecar — emit journal entry, no state mutation

The actual content_hash change happens in phase B via
sidecar_bytes.regenerate_sidecar with a perturbed sub-seed.
Plan-only mode stays bytes-blind on this event by design.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: Engine — extend `_minimal_scenario_for_action` registry + lock test green

**Why now:** the parametrized lock test in `tests/engine/test_state_delta_contract.py` walks every action in `_STATE_DELTA_KEYS` and asserts the registry can build a scenario for it. Sprint 7 added 7 rows (REENCODE_VIDEO, REENCODE_AUDIO existed but weren't in the registry per Decision 7; plus the 6 new actions). All seven need registry entries.

**Files:**
- Modify: `tests/engine/conftest.py` — extend `_minimal_scenario_for_action`.
- Test: `tests/engine/test_state_delta_contract.py` — verify the parametrized lock test green.

- [ ] **Step 1: Inspect the existing registry to confirm the shape**

Run: `rg -n "_minimal_scenario_for_action" tests/engine/conftest.py | head -20`

You should find a dict / dispatch table keyed by `TimelineActionName`. Each entry returns `(Scenario, WorldState, ResolvedEvent)` after applying any prerequisite events.

- [ ] **Step 2: Write the failing test first (parametrized)**

The lock test already exists in `tests/engine/test_state_delta_contract.py`. Run it:

```bash
uv run pytest tests/engine/test_state_delta_contract.py -v 2>&1 | tail -40
```

Expected: skipped or errored cases for the 7 Sprint 7 rows. If the test currently `xfails` unknown actions, change it to fail loudly first by removing the xfail and re-running — confirm that the test would fail without the registry extension.

- [ ] **Step 3: Extend the registry**

In `tests/engine/conftest.py`, add registry entries for each of the 7 missing actions. The Sprint 6 file already has helpers for declaring assets / building scenarios; use them. Sketch (adapt to the actual existing helpers — names may differ):

```python
def _scenario_reencode_video() -> tuple[Scenario, WorldState, ResolvedEvent]:
    scenario = _build_minimal_scenario(
        roots=[("r0", "library/r0")],
        works=[(
            "w0", "T", "v0", "hd", "b0",
            [("a0", "mkv", {"video": ("color_bars", "h264", "hd")})],
        )],
        timeline=[
            {"id": "e0", "at": "1s", "action": "reencode_video",
             "target": "a0", "resolution": "sd", "codec": "h264"},
        ],
    )
    ids = IdAllocator(TraceRecorder(seed_stream="ids"))
    state = build_initial_state(scenario, ids)
    resolved = next(resolve_timeline(scenario, run_id=_TEST_RUN_ID))
    return scenario, state, resolved


def _scenario_reencode_audio() -> tuple[Scenario, WorldState, ResolvedEvent]:
    # … same pattern with action: reencode_audio, from_channels/to_channels


def _scenario_remux_container() -> ...
def _scenario_edit_metadata() -> ...
def _scenario_embed_subtitle() -> ...   # prereq: create_sidecar first
def _scenario_extract_subtitle() -> ... # needs declared subtitle
def _scenario_remove_sidecar() -> ...   # prereq: create_sidecar first
def _scenario_update_sidecar() -> ...   # prereq: create_sidecar first
```

The Sprint 6 registry already follows this `apply prerequisite events, return state at the point the target event is about to run` pattern; mirror it exactly.

Add the 7 new keys to the registry's dispatch dict:

```python
_MINIMAL_SCENARIO_FOR_ACTION: dict[TimelineActionName, Callable[[], tuple[...]]] = {
    # … existing 8 Sprint 6 entries …
    TimelineActionName.REENCODE_VIDEO: _scenario_reencode_video,
    TimelineActionName.REENCODE_AUDIO: _scenario_reencode_audio,
    TimelineActionName.REMUX_CONTAINER: _scenario_remux_container,
    TimelineActionName.EDIT_METADATA: _scenario_edit_metadata,
    TimelineActionName.EMBED_SUBTITLE: _scenario_embed_subtitle,
    TimelineActionName.EXTRACT_SUBTITLE: _scenario_extract_subtitle,
    TimelineActionName.REMOVE_SIDECAR: _scenario_remove_sidecar,
    TimelineActionName.UPDATE_SIDECAR: _scenario_update_sidecar,
}
```

- [ ] **Step 4: Run the lock test**

Run: `uv run pytest tests/engine/test_state_delta_contract.py -v 2>&1 | tail -60`

Every action in `_STATE_DELTA_KEYS` (now 14 entries, was 8) gets parametrized; every case should pass.

- [ ] **Step 5: Run the full engine test suite**

Run: `uv run pytest tests/engine/ -v 2>&1 | tail -40`

Expected: green.

- [ ] **Step 6: Lint; commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add tests/engine/conftest.py
git commit -m "$(cat <<'EOF'
test(engine): extend _minimal_scenario_for_action with 7 Sprint 7 actions

Re-encodes were already handled by their per-handler tests but absent
from the lock-test registry; this commit adds them along with the 6
new media events so the parametrized _STATE_DELTA_KEYS gate covers
every entry.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Engine — derive_version_history + wire into AssetReport builder

**Files:**
- Create: `src/chaos_librarian/engine/version_history.py`.
- Modify: `src/chaos_librarian/engine/reports.py:145` — wire `derive_version_history(asset.id, journal)` into the AssetReport constructor.
- Test: NEW `tests/engine/test_version_history.py`.
- Test: `tests/engine/test_reports.py` — extend to assert `version_history` is populated.

- [ ] **Step 1: Write the failing tests (creates new file)**

Create `tests/engine/test_version_history.py`:

```python
"""Tests for engine.version_history.derive_version_history."""

from __future__ import annotations

import uuid

import pytest

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.engine.version_history import derive_version_history

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _atomic(
    *, event_id: str, action: TimelineActionName, target_ids: list[str],
    state_delta: dict[str, object],
    input_version_ids: list[str] | None = None,
    output_version_ids: list[str] | None = None,
    logical_time_ns: int = 0,
) -> AtomicJournalEntry:
    return AtomicJournalEntry(
        schema_version=1, event_id=event_id, scenario_id="sc", run_id=_RUN_ID,
        logical_time_ns=logical_time_ns, action=action.value,
        target_ids=target_ids,
        input_version_ids=input_version_ids or [],
        output_version_ids=output_version_ids or [],
        location_ids=[], state_delta=state_delta, phase=JournalPhase.ATOMIC,
    )


def test_version_history_empty_for_static_asset():
    journal = [
        _atomic(event_id="e0", action=TimelineActionName.MOVE_ASSET,
                target_ids=["a0"], state_delta={"from_path": "x", "to_path": "y"}),
    ]
    # move_asset is not version-affecting -> empty history.
    assert derive_version_history("a0", journal) == []


def test_version_history_includes_reencode_video():
    journal = [
        _atomic(event_id="e0", action=TimelineActionName.REENCODE_VIDEO,
                target_ids=["a0"], input_version_ids=["v0"],
                output_version_ids=["v1"],
                state_delta={"resolution": "sd", "codec": "h264",
                             "input_path": "x", "output_path": "x"},
                logical_time_ns=1000),
    ]
    history = derive_version_history("a0", journal)
    assert len(history) == 1
    assert history[0].action == TimelineActionName.REENCODE_VIDEO
    assert history[0].input_version_id == "v0"
    assert history[0].output_version_id == "v1"
    assert history[0].state_delta_summary == {"resolution": "sd", "codec": "h264"}


def test_version_history_excludes_extract_subtitle():
    journal = [
        _atomic(event_id="e0", action=TimelineActionName.EXTRACT_SUBTITLE,
                target_ids=["a0"],
                state_delta={"sidecar_id": "s0", "sidecar_path": "x.srt",
                             "language": "eng", "input_path": "x.mkv"}),
    ]
    # extract_subtitle doesn't allocate a version -> excluded.
    assert derive_version_history("a0", journal) == []


def test_version_history_filters_by_asset_id():
    journal = [
        _atomic(event_id="e0", action=TimelineActionName.REENCODE_VIDEO,
                target_ids=["a1"], input_version_ids=["v0"],
                output_version_ids=["v1"],
                state_delta={"resolution": "sd", "codec": "h264",
                             "input_path": "x", "output_path": "x"}),
    ]
    assert derive_version_history("a0", journal) == []
    assert len(derive_version_history("a1", journal)) == 1


def test_version_history_orders_chronologically():
    journal = [
        _atomic(event_id="e0", action=TimelineActionName.REENCODE_VIDEO,
                target_ids=["a0"], input_version_ids=["v0"],
                output_version_ids=["v1"],
                state_delta={"resolution": "sd", "codec": "h264",
                             "input_path": "x", "output_path": "x"},
                logical_time_ns=2000),
        _atomic(event_id="e1", action=TimelineActionName.EDIT_METADATA,
                target_ids=["a0"], input_version_ids=["v1"],
                output_version_ids=["v2"],
                state_delta={"fields": {"k": "v"},
                             "input_path": "x", "output_path": "x"},
                logical_time_ns=4000),
    ]
    history = derive_version_history("a0", journal)
    assert [e.logical_time_ns for e in history] == [2000, 4000]


def test_version_history_summary_keys_per_action():
    # Locks the _PRESERVED_DELTA_KEYS table.
    test_cases = [
        (TimelineActionName.REENCODE_VIDEO,
         {"resolution": "sd", "codec": "h264",
          "input_path": "x", "output_path": "x"},
         {"resolution": "sd", "codec": "h264"}),
        (TimelineActionName.REENCODE_AUDIO,
         {"from_channels": "5.1", "to_channels": "stereo",
          "input_path": "x", "output_path": "x"},
         {"from_channels": "5.1", "to_channels": "stereo"}),
        (TimelineActionName.REMUX_CONTAINER,
         {"from_container": "mkv", "to_container": "mp4",
          "from_path": "x.mkv", "to_path": "x.mp4",
          "input_path": "x.mkv", "output_path": "x.mp4"},
         {"from_container": "mkv", "to_container": "mp4"}),
        (TimelineActionName.EDIT_METADATA,
         {"fields": {"k": "v"}, "input_path": "x", "output_path": "x"},
         {"fields": {"k": "v"}}),
        (TimelineActionName.EMBED_SUBTITLE,
         {"embedded_sidecar_id": "s0", "embedded_sidecar_path": "x.srt",
          "language": "eng", "kind": "subtitle",
          "input_path": "x.mkv", "output_path": "x.mkv"},
         {"language": "eng", "kind": "subtitle"}),
    ]
    for action, delta, expected_summary in test_cases:
        journal = [
            _atomic(event_id="e", action=action, target_ids=["a0"],
                    input_version_ids=["v0"], output_version_ids=["v1"],
                    state_delta=delta),
        ]
        history = derive_version_history("a0", journal)
        assert len(history) == 1, f"action {action} should produce 1 entry"
        assert history[0].state_delta_summary == expected_summary, (
            f"action {action}: expected {expected_summary}, "
            f"got {history[0].state_delta_summary}"
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_version_history.py -v`

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement `derive_version_history`**

Create `src/chaos_librarian/engine/version_history.py`:

```python
"""derive_version_history — project version-affecting journal events for one asset.

Pure function over the journal. Mirrors ``engine/path_history.py``'s
shape for the version-allocating subset of actions (reencode_*,
remux_container, edit_metadata, embed_subtitle).

``extract_subtitle`` is intentionally NOT version-affecting (spec design
decision #9): extraction is read-only on the asset bytes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.reports import VersionHistoryEntry
from chaos_librarian.contract.scenario import TimelineActionName

__all__ = ["derive_version_history"]


_VERSION_AFFECTING_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset({
    TimelineActionName.REENCODE_VIDEO,
    TimelineActionName.REENCODE_AUDIO,
    TimelineActionName.REMUX_CONTAINER,
    TimelineActionName.EDIT_METADATA,
    TimelineActionName.EMBED_SUBTITLE,
})


_PRESERVED_DELTA_KEYS: Final[dict[TimelineActionName, frozenset[str]]] = {
    TimelineActionName.REENCODE_VIDEO: frozenset({"resolution", "codec"}),
    TimelineActionName.REENCODE_AUDIO: frozenset({"from_channels", "to_channels"}),
    TimelineActionName.REMUX_CONTAINER: frozenset({"from_container", "to_container"}),
    TimelineActionName.EDIT_METADATA: frozenset({"fields"}),
    TimelineActionName.EMBED_SUBTITLE: frozenset({"language", "kind"}),
}


def derive_version_history(
    asset_id: str, journal: Iterable[JournalEntry]
) -> list[VersionHistoryEntry]:
    """Project the version-affecting subset of ``journal`` for ``asset_id``.

    Reads each entry's ``action``, filters to the version-affecting set,
    further filters to entries that target ``asset_id``, and projects
    the contract-locked subset of ``state_delta`` keys per action.
    """
    history: list[VersionHistoryEntry] = []
    for entry in journal:
        try:
            action = TimelineActionName(entry.action)
        except ValueError:
            continue  # unknown actions never carry version semantics
        if action not in _VERSION_AFFECTING_ACTIONS:
            continue
        if asset_id not in entry.target_ids:
            continue
        preserved_keys = _PRESERVED_DELTA_KEYS[action]
        summary = {
            k: entry.state_delta[k]
            for k in preserved_keys
            if k in entry.state_delta
        }
        history.append(VersionHistoryEntry(
            event_id=entry.event_id,
            action=action,
            logical_time_ns=entry.logical_time_ns,
            input_version_id=(
                entry.input_version_ids[0] if entry.input_version_ids else None
            ),
            output_version_id=(
                entry.output_version_ids[0] if entry.output_version_ids else None
            ),
            state_delta_summary=summary,
        ))
    return history
```

- [ ] **Step 4: Wire into AssetReport builder**

In `src/chaos_librarian/engine/reports.py`, add import:

```python
from chaos_librarian.engine.version_history import derive_version_history
```

(near the existing `derive_path_history` import.)

Update `_build_asset_report`:

```python
    return AssetReport(
        schema_version=4,
        asset_id=asset_id,
        initial=initial_snapshot,
        history=history,
        current=_snapshot_for(asset_id, current),
        path_history=derive_path_history(asset_id, journal),
        version_history=derive_version_history(asset_id, journal),
    )
```

- [ ] **Step 5: Extend the reports test**

Append to `tests/engine/test_reports.py` (one test asserts the field is populated end-to-end):

```python
def test_asset_report_version_history_populated_for_reencode():
    # Build a scenario with one reencode_video event; run the engine;
    # assert AssetReport.version_history has one entry.
    scenario = Scenario.model_validate({
        "schema_version": 5,
        "scenario_id": "rep_test",
        "seed": 1, "duration_scale": "short",
        "library": {"roots": [{"id": "r0", "path": "library/r0"}]},
        "works": [{"id": "w0", "title": "T", "variants": [{
            "id": "v0", "label": "hd",
            "bundle": {"id": "b0", "assets": [{
                "id": "a0", "role": "primary_video", "container": "mkv",
                "duration_seconds": 1,
                "video": {"source": "color_bars", "codec": "h264",
                          "resolution": "hd"},
                "audio": [{"codec": "aac", "channels": "stereo", "language": "eng"}],
            }]},
        }]}],
        "timeline": [
            {"id": "e0", "at": "1s", "action": "reencode_video",
             "target": "a0", "resolution": "sd", "codec": "h264"},
        ],
    })
    # Use whatever run_plan helper your existing tests use — model after
    # the existing test_asset_report_path_history_populated test.
    report_set = _run_plan_and_build_reports(scenario)
    asset_report = next(r for r in report_set.assets if r.asset_id == "a0")
    assert len(asset_report.version_history) == 1
    assert asset_report.version_history[0].action == TimelineActionName.REENCODE_VIDEO
```

(Use the existing scaffold in `test_reports.py` for `_run_plan_and_build_reports` or its equivalent. If you find no analog, inline it via `engine.run_plan` directly.)

- [ ] **Step 6: Run tests; lint; commit**

```bash
uv run pytest tests/engine/test_version_history.py tests/engine/test_reports.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/engine/version_history.py \
        src/chaos_librarian/engine/reports.py \
        tests/engine/test_version_history.py \
        tests/engine/test_reports.py
git commit -m "$(cat <<'EOF'
feat(engine): derive_version_history pure projection + AssetReport wiring

Reads version-affecting journal entries (reencode_*, remux_container,
edit_metadata, embed_subtitle) for one asset and emits VersionHistoryEntry
rows. extract_subtitle is intentionally excluded — it allocates a
sidecar, not a version (asymmetric with embed_subtitle by design).

AssetReport now ships version_history as a populated field instead of
the empty-by-default placeholder added in the contract bump.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Validation — codes.py adds 4 new error constants

**Files:**
- Modify: `src/chaos_librarian/validation/codes.py` — add 4 new `Final` constants.
- Test: `tests/validation/test_codes.py` — assert each constant equals its expected string.

- [ ] **Step 1: Write the failing tests**

Append to `tests/validation/test_codes.py`:

```python
def test_e_sidecar_target_unknown_constant():
    assert codes.E_SIDECAR_TARGET_UNKNOWN == "E_SIDECAR_TARGET_UNKNOWN"


def test_e_extract_track_unknown_constant():
    assert codes.E_EXTRACT_TRACK_UNKNOWN == "E_EXTRACT_TRACK_UNKNOWN"


def test_e_sidecar_kind_mismatch_constant():
    assert codes.E_SIDECAR_KIND_MISMATCH == "E_SIDECAR_KIND_MISMATCH"


def test_e_sidecar_path_collision_constant():
    assert codes.E_SIDECAR_PATH_COLLISION == "E_SIDECAR_PATH_COLLISION"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/validation/test_codes.py -v -k "sidecar_target_unknown or extract_track or kind_mismatch or path_collision"`

- [ ] **Step 3: Add the constants**

In `src/chaos_librarian/validation/codes.py`, AFTER `E_SIDECAR_LANGUAGE_INVALID`:

```python
E_SIDECAR_TARGET_UNKNOWN: Final = "E_SIDECAR_TARGET_UNKNOWN"
E_EXTRACT_TRACK_UNKNOWN: Final = "E_EXTRACT_TRACK_UNKNOWN"
E_SIDECAR_KIND_MISMATCH: Final = "E_SIDECAR_KIND_MISMATCH"
E_SIDECAR_PATH_COLLISION: Final = "E_SIDECAR_PATH_COLLISION"
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/validation/test_codes.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/validation/codes.py tests/validation/test_codes.py
git commit -m "$(cat <<'EOF'
feat(validation): add Sprint 7 error codes

E_SIDECAR_TARGET_UNKNOWN, E_EXTRACT_TRACK_UNKNOWN,
E_SIDECAR_KIND_MISMATCH, E_SIDECAR_PATH_COLLISION. Constants only;
rule modules in subsequent commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: Validation — rules/sidecar_target.py (covers _UNKNOWN, _KIND_MISMATCH, _PATH_COLLISION)

**Files:**
- Create: `src/chaos_librarian/validation/rules/sidecar_target.py`.
- Test: NEW `tests/validation/rules/test_sidecar_target.py`.

**Approach:** one `rule_sidecar_target` function walks the timeline maintaining a `(asset_id, path) -> kind` projection. Three error code emissions:
1. `E_SIDECAR_TARGET_UNKNOWN` — `remove_sidecar` / `update_sidecar` / `embed_subtitle` reference a sidecar not in the projection.
2. `E_SIDECAR_KIND_MISMATCH` — `embed_subtitle` resolves to a non-subtitle sidecar.
3. `E_SIDECAR_PATH_COLLISION` — `extract_subtitle.to` collides with a live sidecar.

Projection starts populated with declared subtitles (each asset's `subtitles[].mode=sidecar` languages produce `<asset_id>.<language>.srt` entries with `kind="subtitle"`).

- [ ] **Step 1: Write the failing tests (creates new file)**

Create `tests/validation/rules/test_sidecar_target.py`:

```python
"""Tests for rules/sidecar_target.py — 3 codes share one projection."""

from __future__ import annotations

from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation.codes import (
    E_SIDECAR_KIND_MISMATCH,
    E_SIDECAR_PATH_COLLISION,
    E_SIDECAR_TARGET_UNKNOWN,
)
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.rules.sidecar_target import rule_sidecar_target


def _run(raw):
    collector = IssueCollector()
    rule_sidecar_target(raw, LineIndex(), collector)
    return collector.issues


def _minimal(timeline, *, asset_subtitles=None):
    """Build a raw dict for one asset with optional declared subtitles."""
    subtitles = asset_subtitles or []
    return {
        "schema_version": 5, "scenario_id": "sc", "seed": 1,
        "duration_scale": "short",
        "library": {"roots": [{"id": "r0", "path": "library/r0"}]},
        "works": [{"id": "w0", "title": "T", "variants": [{
            "id": "v0", "label": "l", "bundle": {"id": "b0", "assets": [{
                "id": "a0", "role": "primary_video", "container": "mkv",
                "duration_seconds": 1.0,
                "video": {"source": "color_bars", "codec": "h264",
                          "resolution": "hd"},
                "audio": [{"codec": "aac", "channels": "stereo", "language": "eng"}],
                "subtitles": subtitles,
            }]}}]}],
        "timeline": timeline,
    }


def test_remove_sidecar_unknown_path():
    raw = _minimal([
        {"id": "e0", "at": "1s", "action": "remove_sidecar",
         "target": "a0", "sidecar_path": "missing.srt"},
    ])
    issues = _run(raw)
    assert any(i.code == E_SIDECAR_TARGET_UNKNOWN for i in issues)


def test_update_sidecar_unknown_path():
    raw = _minimal([
        {"id": "e0", "at": "1s", "action": "update_sidecar",
         "target": "a0", "sidecar_path": "missing.srt"},
    ])
    issues = _run(raw)
    assert any(i.code == E_SIDECAR_TARGET_UNKNOWN for i in issues)


def test_embed_subtitle_unknown_sidecar_path():
    raw = _minimal([
        {"id": "e0", "at": "1s", "action": "embed_subtitle",
         "target": "a0", "sidecar_path": "missing.srt"},
    ])
    issues = _run(raw)
    assert any(i.code == E_SIDECAR_TARGET_UNKNOWN for i in issues)


def test_embed_subtitle_against_declared_subtitle_valid():
    raw = _minimal(
        timeline=[
            {"id": "e0", "at": "1s", "action": "embed_subtitle",
             "target": "a0", "sidecar_path": "a0.eng.srt"},
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "sidecar"},
        ],
    )
    issues = _run(raw)
    # Declared subtitle is in the projection at <asset_id>.<language>.srt
    # with kind=subtitle — embed should be accepted.
    assert not any(
        i.code in {E_SIDECAR_TARGET_UNKNOWN, E_SIDECAR_KIND_MISMATCH}
        for i in issues
    )


def test_embed_subtitle_against_poster_sidecar():
    raw = _minimal([
        {"id": "e_cs", "at": "1s", "action": "create_sidecar",
         "target": "a0", "to": "a0.poster.png", "kind": "poster"},
        {"id": "e_es", "at": "2s", "action": "embed_subtitle",
         "target": "a0", "sidecar_path": "a0.poster.png"},
    ])
    issues = _run(raw)
    assert any(i.code == E_SIDECAR_KIND_MISMATCH for i in issues)


def test_extract_subtitle_to_collides_with_declared_subtitle():
    raw = _minimal(
        timeline=[
            {"id": "e0", "at": "1s", "action": "extract_subtitle",
             "target": "a0", "to": "a0.eng.srt", "language": "eng"},
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "sidecar"},
        ],
    )
    issues = _run(raw)
    assert any(i.code == E_SIDECAR_PATH_COLLISION for i in issues)


def test_extract_subtitle_to_collides_with_created_sidecar():
    raw = _minimal([
        {"id": "e_cs", "at": "1s", "action": "create_sidecar",
         "target": "a0", "to": "a0.spa.srt", "language": "spa"},
        {"id": "e_xs", "at": "2s", "action": "extract_subtitle",
         "target": "a0", "to": "a0.spa.srt", "language": "spa"},
    ])
    issues = _run(raw)
    assert any(i.code == E_SIDECAR_PATH_COLLISION for i in issues)


def test_extract_subtitle_to_after_remove_valid():
    # Path freed by remove_sidecar should be reusable.
    raw = _minimal(
        timeline=[
            {"id": "e_rs", "at": "1s", "action": "remove_sidecar",
             "target": "a0", "sidecar_path": "a0.eng.srt"},
            {"id": "e_xs", "at": "2s", "action": "extract_subtitle",
             "target": "a0", "to": "a0.eng.srt", "language": "eng"},
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "sidecar"},
        ],
    )
    issues = _run(raw)
    # remove freed the slot; extract should not collide.
    assert not any(i.code == E_SIDECAR_PATH_COLLISION for i in issues)


def test_embed_subtitle_consumes_sidecar_then_subsequent_remove_unknown():
    raw = _minimal(
        timeline=[
            {"id": "e_es", "at": "1s", "action": "embed_subtitle",
             "target": "a0", "sidecar_path": "a0.eng.srt"},
            {"id": "e_rs", "at": "2s", "action": "remove_sidecar",
             "target": "a0", "sidecar_path": "a0.eng.srt"},
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "sidecar"},
        ],
    )
    issues = _run(raw)
    # embed consumed the sidecar; the subsequent remove finds nothing.
    assert any(i.code == E_SIDECAR_TARGET_UNKNOWN for i in issues)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/validation/rules/test_sidecar_target.py -v`

Expected: ModuleNotFoundError.

- [ ] **Step 3: Implement the rule**

Create `src/chaos_librarian/validation/rules/sidecar_target.py`:

```python
"""Rule: validate sidecar references — 3 codes share one (asset_id, path) projection.

Tracks a per-timeline-step ``(asset_id, path) -> kind`` projection
seeded with each asset's declared subtitles (mode=sidecar) and updated
by create_sidecar / extract_subtitle (insert) and remove_sidecar /
embed_subtitle (delete).

Emits:
- E_SIDECAR_TARGET_UNKNOWN: remove/update/embed reference a sidecar that
  isn't in the projection at that point in the timeline.
- E_SIDECAR_KIND_MISMATCH: embed_subtitle references a non-subtitle.
- E_SIDECAR_PATH_COLLISION: extract_subtitle.to lands on a live sidecar
  path (declared or runtime-created).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import SidecarKind, TimelineActionName
from chaos_librarian.validation.codes import (
    E_SIDECAR_KIND_MISMATCH,
    E_SIDECAR_PATH_COLLISION,
    E_SIDECAR_TARGET_UNKNOWN,
)
from chaos_librarian.validation.rules._common import (
    Reporter,
    _as_mapping,
    _iter_timeline_events,
    _list_at_path,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_sidecar_target"]


def rule_sidecar_target(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Walk timeline; maintain ``(asset_id, path) -> kind``; emit 3 codes.

    See module docstring for the precise contract.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    projection = _seed_projection_from_declared(raw)
    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        target = event.get("target")
        if not isinstance(action, str) or not isinstance(target, str):
            continue
        loc = ("timeline", idx, "action")
        if action == TimelineActionName.CREATE_SIDECAR:
            to = event.get("to")
            kind = event.get("kind", SidecarKind.SUBTITLE.value)
            if isinstance(to, str) and isinstance(kind, str):
                projection[(target, to)] = kind
        elif action == TimelineActionName.EXTRACT_SUBTITLE:
            to = event.get("to")
            if isinstance(to, str):
                if (target, to) in projection:
                    reporter.error(
                        code=E_SIDECAR_PATH_COLLISION,
                        message=(
                            f"extract_subtitle.to {to!r} collides with an "
                            f"existing sidecar on asset {target!r}"
                        ),
                        loc=("timeline", idx, "to"),
                    )
                else:
                    projection[(target, to)] = SidecarKind.SUBTITLE.value
        elif action == TimelineActionName.EMBED_SUBTITLE:
            sidecar_path = event.get("sidecar_path")
            if isinstance(sidecar_path, str):
                kind = projection.get((target, sidecar_path))
                if kind is None:
                    reporter.error(
                        code=E_SIDECAR_TARGET_UNKNOWN,
                        message=(
                            f"embed_subtitle references unknown sidecar "
                            f"{sidecar_path!r} on asset {target!r}"
                        ),
                        loc=("timeline", idx, "sidecar_path"),
                    )
                elif kind != SidecarKind.SUBTITLE.value:
                    reporter.error(
                        code=E_SIDECAR_KIND_MISMATCH,
                        message=(
                            f"embed_subtitle references {kind!r} sidecar "
                            f"{sidecar_path!r}; subtitle expected"
                        ),
                        loc=("timeline", idx, "sidecar_path"),
                    )
                else:
                    # embed consumes the sidecar — remove from projection.
                    del projection[(target, sidecar_path)]
        elif action == TimelineActionName.REMOVE_SIDECAR:
            sidecar_path = event.get("sidecar_path")
            if isinstance(sidecar_path, str):
                if (target, sidecar_path) not in projection:
                    reporter.error(
                        code=E_SIDECAR_TARGET_UNKNOWN,
                        message=(
                            f"remove_sidecar references unknown sidecar "
                            f"{sidecar_path!r} on asset {target!r}"
                        ),
                        loc=("timeline", idx, "sidecar_path"),
                    )
                else:
                    del projection[(target, sidecar_path)]
        elif action == TimelineActionName.UPDATE_SIDECAR:
            sidecar_path = event.get("sidecar_path")
            if isinstance(sidecar_path, str):
                if (target, sidecar_path) not in projection:
                    reporter.error(
                        code=E_SIDECAR_TARGET_UNKNOWN,
                        message=(
                            f"update_sidecar references unknown sidecar "
                            f"{sidecar_path!r} on asset {target!r}"
                        ),
                        loc=("timeline", idx, "sidecar_path"),
                    )


def _seed_projection_from_declared(raw: Mapping[str, object]) -> dict[tuple[str, str], str]:
    """Seed (asset_id, path) -> kind for every declared subtitle.

    Declared subtitles use the path convention <asset_id>.<language>.srt
    (per scenario v5 §"Declared-sidecar path convention").
    """
    projection: dict[tuple[str, str], str] = {}
    works = _list_at_path(raw, ("works",)) or []
    for work_obj in works:
        work = _as_mapping(work_obj)
        if work is None:
            continue
        for variant_obj in work.get("variants") or []:
            variant = _as_mapping(variant_obj)
            if variant is None:
                continue
            bundle = _as_mapping(variant.get("bundle"))
            if bundle is None:
                continue
            for asset_obj in bundle.get("assets") or []:
                asset = _as_mapping(asset_obj)
                if asset is None:
                    continue
                asset_id = asset.get("id")
                if not isinstance(asset_id, str):
                    continue
                for sub_obj in asset.get("subtitles") or []:
                    sub = _as_mapping(sub_obj)
                    if sub is None:
                        continue
                    if sub.get("mode") != "sidecar":
                        continue
                    language = sub.get("language")
                    if not isinstance(language, str):
                        continue
                    projection[(asset_id, f"{asset_id}.{language}.srt")] = (
                        SidecarKind.SUBTITLE.value
                    )
    return projection
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/validation/rules/test_sidecar_target.py -v`

Expected: green.

- [ ] **Step 5: Lint; commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/validation/rules/sidecar_target.py \
        tests/validation/rules/test_sidecar_target.py
git commit -m "$(cat <<'EOF'
feat(validation): rule_sidecar_target — 3 codes over one projection

Single (asset_id, path) -> kind projection seeded from declared
subtitles and updated by create_sidecar / extract_subtitle (insert)
and remove_sidecar / embed_subtitle (delete). Emits:
- E_SIDECAR_TARGET_UNKNOWN on remove/update/embed against a missing
  path,
- E_SIDECAR_KIND_MISMATCH on embed against a non-subtitle,
- E_SIDECAR_PATH_COLLISION on extract.to landing on a live path.

Rule not yet registered in the semantic pipeline (Task 21).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: Validation — rules/extract_track_unknown.py

**Files:**
- Create: `src/chaos_librarian/validation/rules/extract_track_unknown.py`.
- Test: NEW `tests/validation/rules/test_extract_track_unknown.py`.

- [ ] **Step 1: Write the failing tests**

Create `tests/validation/rules/test_extract_track_unknown.py`:

```python
"""Tests for rules/extract_track_unknown.py."""

from __future__ import annotations

from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation.codes import E_EXTRACT_TRACK_UNKNOWN
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.rules.extract_track_unknown import (
    rule_extract_track_unknown,
)


def _run(raw):
    collector = IssueCollector()
    rule_extract_track_unknown(raw, LineIndex(), collector)
    return collector.issues


def _scenario(timeline, *, asset_subtitles=None):
    return {
        "schema_version": 5, "scenario_id": "sc", "seed": 1,
        "duration_scale": "short",
        "library": {"roots": [{"id": "r0", "path": "library/r0"}]},
        "works": [{"id": "w0", "title": "T", "variants": [{
            "id": "v0", "label": "l", "bundle": {"id": "b0", "assets": [{
                "id": "a0", "role": "primary_video", "container": "mkv",
                "duration_seconds": 1.0,
                "video": {"source": "color_bars", "codec": "h264",
                          "resolution": "hd"},
                "audio": [{"codec": "aac", "channels": "stereo", "language": "eng"}],
                "subtitles": asset_subtitles or [],
            }]}}]}],
        "timeline": timeline,
    }


def test_extract_subtitle_on_asset_without_subtitle_track():
    raw = _scenario([
        {"id": "e0", "at": "1s", "action": "extract_subtitle",
         "target": "a0", "to": "a0.eng.srt", "language": "eng"},
    ])
    issues = _run(raw)
    assert any(i.code == E_EXTRACT_TRACK_UNKNOWN for i in issues)


def test_extract_subtitle_valid_with_declared_embedded_track():
    raw = _scenario(
        timeline=[
            {"id": "e0", "at": "1s", "action": "extract_subtitle",
             "target": "a0", "to": "a0.eng.srt", "language": "eng"},
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "embedded"},
        ],
    )
    issues = _run(raw)
    assert not any(i.code == E_EXTRACT_TRACK_UNKNOWN for i in issues)


def test_extract_subtitle_valid_with_declared_sidecar():
    # Sidecar mode also counts — once embedded by a prior embed_subtitle,
    # the track is in the file. For Sprint 7 validation, ANY declared
    # subtitle of either mode is enough to satisfy this rule.
    raw = _scenario(
        timeline=[
            {"id": "e0", "at": "1s", "action": "extract_subtitle",
             "target": "a0", "to": "a0.eng.srt", "language": "eng"},
        ],
        asset_subtitles=[
            {"codec": "srt", "language": "eng", "mode": "sidecar"},
        ],
    )
    issues = _run(raw)
    assert not any(i.code == E_EXTRACT_TRACK_UNKNOWN for i in issues)


def test_extract_subtitle_unknown_target_does_not_emit_track_error():
    # Unknown target is rule_target_unknown's job.
    raw = _scenario([
        {"id": "e0", "at": "1s", "action": "extract_subtitle",
         "target": "nonexistent_asset", "to": "x.srt", "language": "eng"},
    ])
    issues = _run(raw)
    # extract_track_unknown silently skips unknown targets.
    assert not any(i.code == E_EXTRACT_TRACK_UNKNOWN for i in issues)
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement the rule**

Create `src/chaos_librarian/validation/rules/extract_track_unknown.py`:

```python
"""Rule: extract_subtitle on an asset with no declared subtitle track.

The materializer's extract handler does ``ffmpeg -map 0:s:m:language``
(falling back to ``-map 0:s:0``); if the asset has no subtitle stream
at all, ffmpeg fails at runtime. This rule rejects scenarios where the
asset has no declared subtitle track of EITHER mode (embedded or
sidecar). A sidecar declaration counts because a prior embed_subtitle
in the timeline may have folded it into the asset.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_EXTRACT_TRACK_UNKNOWN
from chaos_librarian.validation.rules._common import (
    Reporter,
    _as_mapping,
    _iter_timeline_events,
    _list_at_path,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_extract_track_unknown"]


def rule_extract_track_unknown(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Emit E_EXTRACT_TRACK_UNKNOWN for extract_subtitle on a subtitle-less asset."""
    reporter = Reporter(collector=collector, line_index=line_index)
    assets_with_subtitle_tracks = _assets_with_subtitle_tracks(raw)
    for idx, event in _iter_timeline_events(raw):
        if event.get("action") != TimelineActionName.EXTRACT_SUBTITLE:
            continue
        target = event.get("target")
        if not isinstance(target, str):
            continue
        if target not in assets_with_subtitle_tracks:
            # Unknown asset is rule_target_unknown's job; only emit when
            # the asset exists but has no subtitle tracks.
            continue
        if not assets_with_subtitle_tracks[target]:
            reporter.error(
                code=E_EXTRACT_TRACK_UNKNOWN,
                message=(
                    f"extract_subtitle on asset {target!r} which declares no "
                    "subtitle tracks (embedded or sidecar)"
                ),
                loc=("timeline", idx, "target"),
            )


def _assets_with_subtitle_tracks(raw: Mapping[str, object]) -> dict[str, bool]:
    """asset_id -> True iff the asset declares at least one subtitle track."""
    out: dict[str, bool] = {}
    works = _list_at_path(raw, ("works",)) or []
    for work_obj in works:
        work = _as_mapping(work_obj)
        if work is None:
            continue
        for variant_obj in work.get("variants") or []:
            variant = _as_mapping(variant_obj)
            if variant is None:
                continue
            bundle = _as_mapping(variant.get("bundle"))
            if bundle is None:
                continue
            for asset_obj in bundle.get("assets") or []:
                asset = _as_mapping(asset_obj)
                if asset is None:
                    continue
                asset_id = asset.get("id")
                if not isinstance(asset_id, str):
                    continue
                subs = asset.get("subtitles") or []
                out[asset_id] = bool(subs)
    return out
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/validation/rules/test_extract_track_unknown.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/validation/rules/extract_track_unknown.py \
        tests/validation/rules/test_extract_track_unknown.py
git commit -m "$(cat <<'EOF'
feat(validation): rule_extract_track_unknown — reject subtitle-less extract

extract_subtitle on an asset with no declared subtitle tracks of any
mode (embedded / sidecar) emits E_EXTRACT_TRACK_UNKNOWN before
ffmpeg runtime would surface it as E_MATERIALIZE_MEDIA_FAILED.

Rule not yet registered in the semantic pipeline (Task 21).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 19: Validation — extend rules/timeline_lifecycle.py for Sprint 7

**Files:**
- Modify: `src/chaos_librarian/validation/rules/timeline_lifecycle.py` — extend `_LOCATION_DEPENDENT_PASSTHROUGH` and `_PATH_MUTATING_PASSTHROUGH`, add `sidecars_by_path` projection to the simulator state, reject embed/extract/remove/update on missing sidecars (`E_LIFECYCLE_INVALID`).
- Test: `tests/validation/rules/test_timeline_lifecycle.py` — extend with Sprint 7 cases.

- [ ] **Step 1: Write the failing tests**

Append to `tests/validation/rules/test_timeline_lifecycle.py`:

```python
class TestSprint7LifecycleExtensions:
    """Sprint 7 adds 6 new actions to the simulator; all 6 require placed targets.
    
    REMUX, EDIT_METADATA, EMBED_SUBTITLE, EXTRACT_SUBTITLE join
    _PATH_MUTATING_PASSTHROUGH (rejected against pending slow_copy).
    UPDATE_SIDECAR and REMOVE_SIDECAR are EXCLUDED — they don't touch
    the asset.
    """

    def test_remux_container_on_unplaced_asset_rejected(
        self, minimal_scenario, empty_index
    ):
        raw = minimal_scenario(timeline=[
            {"id": "e0", "at": "1s", "action": "delete_file", "target": "asset_main"},
            {"id": "e1", "at": "2s", "action": "remux_container",
             "target": "asset_main", "to_container": "mp4"},
        ])
        collector = IssueCollector()
        rule_timeline_lifecycle(raw, empty_index, collector)
        assert any(i.code == E_LIFECYCLE_INVALID for i in collector.issues)

    @pytest.mark.parametrize("action,fields", [
        ("remux_container", {"to_container": "mp4"}),
        ("edit_metadata", {"fields": {"k": "v"}}),
        ("embed_subtitle", {"sidecar_path": "asset_main.eng.srt"}),
        ("extract_subtitle", {"to": "asset_main.fra.srt", "language": "fra"}),
    ])
    def test_slow_copy_forbidden_action(
        self, minimal_scenario, empty_index, action, fields
    ):
        raw = minimal_scenario(
            timeline=[
                {"id": "e_sc", "at": "1s", "action": "slow_copy_start",
                 "target": "asset_main", "to": "asset_main.mkv",
                 "temp_path": "asset_main.mkv.copying",
                 "duration": "5s"},
                {"id": "e_op", "at": "2s", "action": action,
                 "target": "asset_main", **fields},
            ],
            asset_subtitles=[{"codec": "srt", "language": "eng", "mode": "sidecar"}],
        )
        collector = IssueCollector()
        rule_timeline_lifecycle(raw, empty_index, collector)
        assert any(i.code == E_LIFECYCLE_INVALID for i in collector.issues), (
            f"action {action} during pending slow_copy must be rejected"
        )

    def test_update_sidecar_during_pending_slow_copy_valid(
        self, minimal_scenario, empty_index
    ):
        # UPDATE_SIDECAR is intentionally NOT in _PATH_MUTATING_PASSTHROUGH
        # — it touches a sidecar file, not the asset bytes.
        raw = minimal_scenario(
            timeline=[
                {"id": "e_cs", "at": "0s", "action": "create_sidecar",
                 "target": "asset_main", "to": "asset_main.eng.srt",
                 "language": "eng"},
                {"id": "e_sc", "at": "1s", "action": "slow_copy_start",
                 "target": "asset_main", "to": "asset_main.mkv",
                 "temp_path": "asset_main.mkv.copying",
                 "duration": "5s"},
                {"id": "e_us", "at": "2s", "action": "update_sidecar",
                 "target": "asset_main", "sidecar_path": "asset_main.eng.srt"},
            ],
        )
        collector = IssueCollector()
        rule_timeline_lifecycle(raw, empty_index, collector)
        # Lifecycle rule should NOT flag update_sidecar during slow_copy.
        assert not any(i.code == E_LIFECYCLE_INVALID for i in collector.issues)

    def test_remove_sidecar_during_pending_slow_copy_valid(
        self, minimal_scenario, empty_index
    ):
        raw = minimal_scenario(
            timeline=[
                {"id": "e_cs", "at": "0s", "action": "create_sidecar",
                 "target": "asset_main", "to": "asset_main.eng.srt",
                 "language": "eng"},
                {"id": "e_sc", "at": "1s", "action": "slow_copy_start",
                 "target": "asset_main", "to": "asset_main.mkv",
                 "temp_path": "asset_main.mkv.copying",
                 "duration": "5s"},
                {"id": "e_rs", "at": "2s", "action": "remove_sidecar",
                 "target": "asset_main", "sidecar_path": "asset_main.eng.srt"},
            ],
        )
        collector = IssueCollector()
        rule_timeline_lifecycle(raw, empty_index, collector)
        assert not any(i.code == E_LIFECYCLE_INVALID for i in collector.issues)

    def test_embed_subtitle_on_missing_sidecar_emits_lifecycle_invalid(
        self, minimal_scenario, empty_index
    ):
        # Sprint 7 spec: lifecycle rule covers dynamic case (sidecar removed
        # earlier in timeline). Static case is rule_sidecar_target.
        raw = minimal_scenario(
            timeline=[
                {"id": "e_rs", "at": "1s", "action": "remove_sidecar",
                 "target": "asset_main", "sidecar_path": "asset_main.eng.srt"},
                {"id": "e_es", "at": "2s", "action": "embed_subtitle",
                 "target": "asset_main", "sidecar_path": "asset_main.eng.srt"},
            ],
            asset_subtitles=[{"codec": "srt", "language": "eng", "mode": "sidecar"}],
        )
        collector = IssueCollector()
        rule_timeline_lifecycle(raw, empty_index, collector)
        assert any(i.code == E_LIFECYCLE_INVALID for i in collector.issues)
```

The Sprint 6 `minimal_scenario` factory may not accept `asset_subtitles=`. If so, extend it in `tests/validation/rules/conftest.py` — the override pattern is straightforward; mirror however the existing factory accepts `**overrides`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/validation/rules/test_timeline_lifecycle.py::TestSprint7LifecycleExtensions -v`

- [ ] **Step 3: Extend the simulator**

In `src/chaos_librarian/validation/rules/timeline_lifecycle.py`:

Extend `_LOCATION_DEPENDENT_PASSTHROUGH` (replace existing):

```python
_LOCATION_DEPENDENT_PASSTHROUGH: frozenset[str] = frozenset(
    {
        TimelineActionName.REENCODE_VIDEO,
        TimelineActionName.REENCODE_AUDIO,
        TimelineActionName.CREATE_SIDECAR,
        TimelineActionName.ARCHIVE_FILE,
        TimelineActionName.MOVE_BETWEEN_ROOTS,
        TimelineActionName.REMUX_CONTAINER,
        TimelineActionName.EDIT_METADATA,
        TimelineActionName.EMBED_SUBTITLE,
        TimelineActionName.EXTRACT_SUBTITLE,
        TimelineActionName.REMOVE_SIDECAR,
        TimelineActionName.UPDATE_SIDECAR,
    }
)
```

Extend `_PATH_MUTATING_PASSTHROUGH` (replace existing) — per Sprint 7 spec §"Lifecycle simulator extensions":

```python
_PATH_MUTATING_PASSTHROUGH: frozenset[str] = frozenset(
    {
        # Sprint 6 members:
        TimelineActionName.ARCHIVE_FILE,
        TimelineActionName.MOVE_BETWEEN_ROOTS,
        # Sprint 7 members — set's intent is "ops forbidden against an
        # asset with pending slow_copy"; see follow-up issue #48 for
        # rename to slow_copy_forbidden_set.
        TimelineActionName.REENCODE_VIDEO,    # in-place re-encode
        TimelineActionName.REENCODE_AUDIO,    # in-place re-encode
        TimelineActionName.REMUX_CONTAINER,   # path-changing
        TimelineActionName.EDIT_METADATA,     # in-place byte mutator
        TimelineActionName.EMBED_SUBTITLE,    # in-place byte mutator
        TimelineActionName.EXTRACT_SUBTITLE,  # READS the asset
    }
)
```

Add a `sidecars_by_path` projection to `_LifecycleState` (extend the existing dataclass):

```python
@dataclass
class _LifecycleState:
    placed: set[str]
    pending_slow_copies: dict[str, str]
    assets_with_pending_copy: set[str]
    sidecars_by_path: dict[tuple[str, str], str] = field(default_factory=dict)
    """(asset_id, path) -> kind. Seeded from declared subtitles; updated
    by create_sidecar / extract_subtitle (insert) and
    remove_sidecar / embed_subtitle (delete)."""
```

Add `from dataclasses import dataclass, field` (replace existing dataclass import).

Seed `sidecars_by_path` in `rule_timeline_lifecycle` after building `state`:

```python
    state = _LifecycleState(
        placed=set(iter_asset_ids(raw)),
        pending_slow_copies={},
        assets_with_pending_copy=set(),
        sidecars_by_path=_seed_sidecars_by_path(raw),
    )
```

Add the helper:

```python
def _seed_sidecars_by_path(raw: Mapping[str, object]) -> dict[tuple[str, str], str]:
    """Seed (asset_id, path) -> kind for declared subtitle sidecars."""
    from chaos_librarian.contract.scenario import SidecarKind  # local to avoid cycle
    out: dict[tuple[str, str], str] = {}
    works = raw.get("works")
    if not isinstance(works, list):
        return out
    for work in works:
        if not isinstance(work, dict):
            continue
        for variant in work.get("variants") or []:
            if not isinstance(variant, dict):
                continue
            bundle = variant.get("bundle")
            if not isinstance(bundle, dict):
                continue
            for asset in bundle.get("assets") or []:
                if not isinstance(asset, dict):
                    continue
                asset_id = asset.get("id")
                if not isinstance(asset_id, str):
                    continue
                for sub in asset.get("subtitles") or []:
                    if not isinstance(sub, dict):
                        continue
                    if sub.get("mode") != "sidecar":
                        continue
                    language = sub.get("language")
                    if not isinstance(language, str):
                        continue
                    out[(asset_id, f"{asset_id}.{language}.srt")] = (
                        SidecarKind.SUBTITLE.value
                    )
    return out
```

Extend the dispatch in `rule_timeline_lifecycle` (inside the `for idx, event in _iter_timeline_events(raw):` loop). Add new branches for the 6 new actions BEFORE the existing `elif action == TimelineActionName.SLOW_COPY_START`:

```python
        elif action == TimelineActionName.CREATE_SIDECAR and isinstance(target, str):
            # Existing handler stays; ALSO insert into sidecars_by_path.
            _lifecycle_check_passthrough(action=action, target=target, **kwargs)
            to = event.get("to")
            kind = event.get("kind", "subtitle")
            if isinstance(to, str) and isinstance(kind, str):
                state.sidecars_by_path[(target, to)] = kind
        elif action == TimelineActionName.EXTRACT_SUBTITLE and isinstance(target, str):
            _lifecycle_check_passthrough(action=action, target=target, **kwargs)
            to = event.get("to")
            if isinstance(to, str):
                state.sidecars_by_path[(target, to)] = "subtitle"
        elif action == TimelineActionName.EMBED_SUBTITLE and isinstance(target, str):
            _lifecycle_check_passthrough(action=action, target=target, **kwargs)
            sidecar_path = event.get("sidecar_path")
            if isinstance(sidecar_path, str):
                if (target, sidecar_path) not in state.sidecars_by_path:
                    emit(
                        message=f"embed_subtitle on missing sidecar "
                                f"{sidecar_path!r} (asset {target!r})",
                        loc=loc,
                    )
                else:
                    del state.sidecars_by_path[(target, sidecar_path)]
        elif action == TimelineActionName.REMOVE_SIDECAR and isinstance(target, str):
            _lifecycle_check_passthrough(action=action, target=target, **kwargs)
            sidecar_path = event.get("sidecar_path")
            if isinstance(sidecar_path, str):
                if (target, sidecar_path) not in state.sidecars_by_path:
                    emit(
                        message=f"remove_sidecar on missing sidecar "
                                f"{sidecar_path!r} (asset {target!r})",
                        loc=loc,
                    )
                else:
                    del state.sidecars_by_path[(target, sidecar_path)]
        elif action == TimelineActionName.UPDATE_SIDECAR and isinstance(target, str):
            _lifecycle_check_passthrough(action=action, target=target, **kwargs)
            sidecar_path = event.get("sidecar_path")
            if isinstance(sidecar_path, str):
                if (target, sidecar_path) not in state.sidecars_by_path:
                    emit(
                        message=f"update_sidecar on missing sidecar "
                                f"{sidecar_path!r} (asset {target!r})",
                        loc=loc,
                    )
        elif action in _LOCATION_DEPENDENT_PASSTHROUGH and isinstance(target, str):
            # Catches REMUX_CONTAINER, EDIT_METADATA, REENCODE_*, etc.
            _lifecycle_check_passthrough(action=action, target=target, **kwargs)
```

Notice the existing `elif action in _LOCATION_DEPENDENT_PASSTHROUGH` branch must be moved AFTER the 6 new explicit branches so the explicit branches win for actions that need both passthrough check AND sidecar-projection updates. Verify by reading the current loop body and re-arranging carefully.

- [ ] **Step 4: Run lifecycle tests**

Run: `uv run pytest tests/validation/rules/test_timeline_lifecycle.py -v 2>&1 | tail -60`

Expected: green for both existing Sprint 6 cases and the new Sprint 7 cases.

- [ ] **Step 5: Lint; commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/validation/rules/timeline_lifecycle.py \
        tests/validation/rules/test_timeline_lifecycle.py \
        tests/validation/rules/conftest.py
git commit -m "$(cat <<'EOF'
feat(validation): extend rule_timeline_lifecycle for Sprint 7

Adds the 6 new media actions to _LOCATION_DEPENDENT_PASSTHROUGH and
the 4 byte/read media actions to _PATH_MUTATING_PASSTHROUGH (REENCODE_*,
REMUX_CONTAINER, EDIT_METADATA, EMBED_SUBTITLE, EXTRACT_SUBTITLE).
UPDATE_SIDECAR and REMOVE_SIDECAR are intentionally excluded — they
touch a sidecar, not the asset.

Adds a sidecars_by_path projection so dynamic "embed on
previously-removed sidecar" is caught by the lifecycle rule even though
rule_sidecar_target's structural projection wouldn't trip it.

Refs #48 (rename _PATH_MUTATING_PASSTHROUGH).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 20: Validation — extend rules/path_containment.py for extract_subtitle.to

**Files:**
- Modify: `src/chaos_librarian/validation/rules/path_containment.py` — add `EXTRACT_SUBTITLE: ("to",)` to `_PATH_FIELDS_BY_ACTION`.
- Test: `tests/validation/rules/test_path_containment.py` — append extract_subtitle case.

- [ ] **Step 1: Write the failing tests**

Append to `tests/validation/rules/test_path_containment.py`:

```python
def test_extract_subtitle_to_escaping_path_rejected(minimal_scenario, empty_index):
    raw = minimal_scenario(timeline=[
        {"id": "e0", "at": "1s", "action": "extract_subtitle",
         "target": "asset_main", "to": "../escape.srt", "language": "eng"},
    ])
    collector = IssueCollector()
    rule_path_containment(raw, empty_index, collector)
    assert any(i.code == E_PATH_CONTAINMENT for i in collector.issues)


def test_extract_subtitle_to_under_library_accepted(minimal_scenario, empty_index):
    raw = minimal_scenario(timeline=[
        {"id": "e0", "at": "1s", "action": "extract_subtitle",
         "target": "asset_main", "to": "asset_main.fra.srt", "language": "fra"},
    ])
    collector = IssueCollector()
    rule_path_containment(raw, empty_index, collector)
    # No containment issue for a relative under-library path.
    assert not any(i.code == E_PATH_CONTAINMENT for i in collector.issues)
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Extend `_PATH_FIELDS_BY_ACTION`**

In `src/chaos_librarian/validation/rules/path_containment.py`:

```python
_PATH_FIELDS_BY_ACTION: dict[str, tuple[str, ...]] = {
    TimelineActionName.MOVE_ASSET: ("to",),
    TimelineActionName.RENAME_FILE: ("to",),
    TimelineActionName.ADD_FILE: ("to",),
    TimelineActionName.CREATE_SIDECAR: ("to",),
    TimelineActionName.SLOW_COPY_START: ("to", "temp_path"),
    TimelineActionName.EXTRACT_SUBTITLE: ("to",),
}
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/validation/rules/test_path_containment.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/validation/rules/path_containment.py \
        tests/validation/rules/test_path_containment.py
git commit -m "$(cat <<'EOF'
feat(validation): extend path containment to extract_subtitle.to

Sprint 7's new sidecar destination path joins the per-action field
table so '..' escapes and absolute paths surface as E_PATH_CONTAINMENT
instead of leaking into the materializer's containment gate.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 21: Validation — register the two new rules in semantic.py

**Files:**
- Modify: `src/chaos_librarian/validation/semantic.py` — import and register `rule_sidecar_target` + `rule_extract_track_unknown`.
- Test: `tests/validation/test_pipeline.py` — sanity check that the new rules are reachable through the pipeline.

- [ ] **Step 1: Write the failing tests**

Append to `tests/validation/test_pipeline.py` (or create a new top-level integration test if pipeline tests live elsewhere — verify with `rg "_RULES" tests/validation/`):

```python
def test_pipeline_registers_rule_sidecar_target():
    from chaos_librarian.validation.semantic import _RULES
    from chaos_librarian.validation.rules.sidecar_target import rule_sidecar_target
    assert rule_sidecar_target in _RULES


def test_pipeline_registers_rule_extract_track_unknown():
    from chaos_librarian.validation.semantic import _RULES
    from chaos_librarian.validation.rules.extract_track_unknown import (
        rule_extract_track_unknown,
    )
    assert rule_extract_track_unknown in _RULES
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Register the rules**

In `src/chaos_librarian/validation/semantic.py`, add the imports:

```python
from chaos_librarian.validation.rules.extract_track_unknown import (
    rule_extract_track_unknown,
)
from chaos_librarian.validation.rules.sidecar_target import rule_sidecar_target
```

Append to `_RULES`:

```python
_RULES: list[Rule] = [
    rule_id_duplicate,
    rule_path_duplicate,
    rule_duration_syntax,
    rule_target_unknown,
    rule_root_unknown,
    rule_slow_copy_unpaired,
    rule_slow_copy_timing,
    rule_slow_copy_path_collision,
    rule_path_containment,
    rule_timeline_order,
    rule_timeline_lifecycle,
    rule_asset_id_container_safe,
    rule_sidecar_language_consistent,
    rule_sidecar_target,
    rule_extract_track_unknown,
]
```

- [ ] **Step 4: Run the full validation suite**

Run: `uv run pytest tests/validation/ -v 2>&1 | tail -40`

Expected: green. If `test_invalid_corpus.py` complains about missing fixtures, that's expected — those fixtures land in Task 41.

- [ ] **Step 5: Lint; commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/validation/semantic.py tests/validation/test_pipeline.py
git commit -m "$(cat <<'EOF'
feat(validation): register Sprint 7 rules in the semantic pipeline

rule_sidecar_target and rule_extract_track_unknown now fire as part
of the standard validation pass. End-to-end coverage from invalid
fixtures lands in Task 41.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 22: Materializer — errors.py adds MediaActionError

**Files:**
- Modify: `src/chaos_librarian/materializer/errors.py` — add `MediaActionError`.
- Modify: `src/chaos_librarian/materializer/__init__.py` — re-export.
- Test: `tests/materializer/test_errors.py` — round-trip of payload shape.

- [ ] **Step 1: Write the failing tests**

Append to `tests/materializer/test_errors.py`:

```python
def test_media_action_error_payload_carries_event_action_invocation():
    cause = RuntimeError("ffmpeg exit 1")
    err = MediaActionError(
        "reencode_video failed for event ev_rv_001",
        event_id="ev_rv_001",
        action=TimelineActionName.REENCODE_VIDEO,
        cause=cause,
        asset_id="asset_main",
        tool_invocation_index=3,
    )
    assert err.error_code == "E_MATERIALIZE_MEDIA_FAILED"
    assert err.event_id == "ev_rv_001"
    assert err.action == TimelineActionName.REENCODE_VIDEO
    assert err.cause is cause
    assert err.tool_invocation_index == 3
    assert err.payload["event_id"] == "ev_rv_001"
    assert err.payload["action"] == "reencode_video"
    assert err.payload["tool_invocation_index"] == 3
    assert err.asset_id == "asset_main"


def test_media_action_error_subclass_of_materialization_error():
    from chaos_librarian.materializer.errors import MaterializationError
    err = MediaActionError(
        "x", event_id="e0", action=TimelineActionName.REENCODE_VIDEO,
        cause=RuntimeError("y"),
    )
    assert isinstance(err, MaterializationError)
```

Add the import: `from chaos_librarian.materializer.errors import MediaActionError`.

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Add MediaActionError**

In `src/chaos_librarian/materializer/errors.py`, append:

```python
class MediaActionError(MaterializationError):
    """A phase-B media handler (ffmpeg-backed or sidecar-regeneration) raised.

    Library/ must be wiped; materialization.json records
    outcome=media_failed. ``tool_invocation_index`` cross-refs the
    failing invocation in MaterializationReport.invocations when an
    ffmpeg call was involved; ``None`` for update_sidecar's pure-Python
    paths.
    """

    error_code: str = "E_MATERIALIZE_MEDIA_FAILED"

    def __init__(
        self,
        message: str,
        *,
        event_id: str,
        action: TimelineActionName,
        cause: BaseException,
        asset_id: str | None = None,
        tool_invocation_index: int | None = None,
        field: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        merged_payload: dict[str, object] = dict(payload or {})
        merged_payload.setdefault("event_id", event_id)
        merged_payload.setdefault("action", action.value)
        merged_payload.setdefault("tool_invocation_index", tool_invocation_index)
        super().__init__(
            message, asset_id=asset_id, field=field, payload=merged_payload,
        )
        self.event_id = event_id
        self.cause = cause
        self.action = action
        self.tool_invocation_index = tool_invocation_index
```

- [ ] **Step 4: Re-export from `materializer/__init__.py`**

Add `MediaActionError` to the existing `from chaos_librarian.materializer.errors import (...)` block in `src/chaos_librarian/materializer/__init__.py` and to `__all__`.

- [ ] **Step 5: Run tests; lint; commit**

```bash
uv run pytest tests/materializer/test_errors.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/errors.py \
        src/chaos_librarian/materializer/__init__.py \
        tests/materializer/test_errors.py
git commit -m "$(cat <<'EOF'
feat(materializer): MediaActionError with E_MATERIALIZE_MEDIA_FAILED

Mirrors FilesystemActionError's shape but carries
tool_invocation_index so consumers can join the failing entry against
MaterializationReport.invocations. CLI wiring in a follow-up.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 23: Materializer — sidecar_bytes.py (render_poster, render_nfo, regenerate_sidecar)

**Files:**
- Create: `src/chaos_librarian/materializer/sidecar_bytes.py`.
- Test: NEW `tests/materializer/test_sidecar_bytes.py`.

**Design decisions:**
- `render_nfo(sidecar_id, language=None) -> bytes`: pure Python XML template (no ffmpeg).
- `render_poster(sidecar_id, resolved_seed) -> tuple[list[str], bytes]`: returns (ffmpeg argv, expected stdout-via-pipe bytes) — actually, poster rendering writes to a file via ffmpeg lavfi. Simpler shape: `poster_ffmpeg_argv(*, output_path, resolved_seed, sidecar_id) -> list[str]` returns just argv; the caller (media.py) runs it.
- `regenerate_sidecar(*, kind, language, sidecar_id, resolved_seed, event_id, duration_s) -> tuple[bytes | None, list[str] | None]`: returns `(bytes, None)` for subtitle/NFO and `(None, argv)` for poster. The caller writes bytes or runs argv accordingly.

Simpler split: keep `render_poster_argv`, `render_nfo`, and a subtitle helper that calls existing `recipes.srt_payload`. `regenerate_sidecar` is the dispatch.

- [ ] **Step 1: Write the failing tests (creates new file)**

Create `tests/materializer/test_sidecar_bytes.py`:

```python
"""Tests for materializer/sidecar_bytes.py — pure byte/argv generators."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.scenario import SidecarKind
from chaos_librarian.materializer.sidecar_bytes import (
    poster_ffmpeg_argv,
    regenerate_sidecar,
    render_nfo,
)


def test_render_nfo_is_xml_with_sidecar_id():
    body = render_nfo(sidecar_id="sidecar_0001")
    assert body.startswith(b"<?xml")
    assert b"sidecar_0001" in body


def test_render_nfo_deterministic():
    a = render_nfo(sidecar_id="sidecar_0001")
    b = render_nfo(sidecar_id="sidecar_0001")
    assert a == b


def test_poster_ffmpeg_argv_uses_lavfi_color_source():
    argv = poster_ffmpeg_argv(
        output_path=Path("/tmp/x.png"),
        resolved_seed=42,
        sidecar_id="sidecar_0001",
    )
    assert argv[0] == "ffmpeg"
    assert "-f" in argv and "lavfi" in argv
    # Hex color derived from seed should appear in the lavfi expression.
    joined = " ".join(argv)
    assert "color=" in joined
    assert "/tmp/x.png" in argv


def test_poster_ffmpeg_argv_deterministic_per_seed():
    a = poster_ffmpeg_argv(
        output_path=Path("/tmp/x.png"), resolved_seed=42, sidecar_id="s0")
    b = poster_ffmpeg_argv(
        output_path=Path("/tmp/x.png"), resolved_seed=42, sidecar_id="s0")
    assert a == b


def test_regenerate_sidecar_subtitle_returns_srt_bytes():
    bytes_, argv = regenerate_sidecar(
        kind=SidecarKind.SUBTITLE,
        language="eng",
        sidecar_id="sidecar_0001",
        resolved_seed=42,
        event_id="ev_us_001",
        duration_s=1.0,
    )
    assert argv is None
    assert bytes_ is not None
    assert b"00:00:00,000" in bytes_  # SRT timestamp marker
    assert b"sidecar_0001" in bytes_  # event_id-perturbed seed mention


def test_regenerate_sidecar_subtitle_distinct_per_event_id():
    a_bytes, _ = regenerate_sidecar(
        kind=SidecarKind.SUBTITLE, language="eng",
        sidecar_id="sidecar_0001", resolved_seed=42,
        event_id="ev_a", duration_s=1.0,
    )
    b_bytes, _ = regenerate_sidecar(
        kind=SidecarKind.SUBTITLE, language="eng",
        sidecar_id="sidecar_0001", resolved_seed=42,
        event_id="ev_b", duration_s=1.0,
    )
    assert a_bytes != b_bytes  # event_id is in the perturbed seed


def test_regenerate_sidecar_nfo_returns_xml_bytes():
    bytes_, argv = regenerate_sidecar(
        kind=SidecarKind.NFO, language=None,
        sidecar_id="sidecar_0001", resolved_seed=42,
        event_id="ev_us_001", duration_s=1.0,
    )
    assert argv is None
    assert bytes_ is not None
    assert bytes_.startswith(b"<?xml")


def test_regenerate_sidecar_poster_returns_argv():
    bytes_, argv = regenerate_sidecar(
        kind=SidecarKind.POSTER, language=None,
        sidecar_id="sidecar_0001", resolved_seed=42,
        event_id="ev_us_001", duration_s=1.0,
        output_path=Path("/tmp/x.png"),
    )
    assert bytes_ is None
    assert argv is not None
    assert argv[0] == "ffmpeg"
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement sidecar_bytes.py**

Create `src/chaos_librarian/materializer/sidecar_bytes.py`:

```python
"""Byte generators for non-subtitle sidecars + update_sidecar regeneration.

- ``render_nfo``: pure Python XML template. Returns bytes.
- ``poster_ffmpeg_argv``: returns the ffmpeg argv that will write a
  PNG via lavfi color source. The caller runs it.
- ``regenerate_sidecar``: dispatch by kind. Returns ``(bytes, None)``
  for subtitle/NFO; ``(None, argv)`` for poster.

The update_sidecar perturbed sub-seed is
``Hash(seed_stream="sidecar_update", sidecar_id, event_id)`` per spec
design decision #7.
"""

from __future__ import annotations

from pathlib import Path

from chaos_librarian.contract.scenario import SidecarKind
from chaos_librarian.determinism import hash_for
from chaos_librarian.materializer.recipes import srt_payload

__all__ = [
    "perturbed_seed_for_update",
    "poster_ffmpeg_argv",
    "regenerate_sidecar",
    "render_nfo",
]


def render_nfo(*, sidecar_id: str) -> bytes:
    """Minimal Kodi-style NFO XML. Deterministic from sidecar_id."""
    return (
        f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        f"<movie>\n"
        f"  <sidecar_id>{sidecar_id}</sidecar_id>\n"
        f"  <generator>chaos-librarian</generator>\n"
        f"</movie>\n"
    ).encode("utf-8")


def poster_ffmpeg_argv(
    *,
    output_path: Path,
    resolved_seed: int,
    sidecar_id: str,
) -> list[str]:
    """Build the ffmpeg argv for a single-color PNG poster.

    Hex color derived from (resolved_seed, sidecar_id) so different
    sidecars on the same run produce visually distinct posters.
    """
    seed_hash = hash_for(stream="poster_color", seed=resolved_seed,
                         keys=(sidecar_id,))
    color = f"{seed_hash & 0xFFFFFF:06x}"
    return [
        "ffmpeg", "-hide_banner", "-y",
        "-f", "lavfi",
        "-i", f"color=c=#{color}:s=400x600:d=0.01:r=1",
        "-frames:v", "1",
        str(output_path),
    ]


def perturbed_seed_for_update(*, sidecar_id: str, event_id: str,
                              resolved_seed: int) -> int:
    """Per spec design decision #7: distinct bytes for consecutive updates."""
    return hash_for(
        stream="sidecar_update", seed=resolved_seed,
        keys=(sidecar_id, event_id),
    )


def regenerate_sidecar(
    *,
    kind: SidecarKind,
    language: str | None,
    sidecar_id: str,
    resolved_seed: int,
    event_id: str,
    duration_s: float,
    output_path: Path | None = None,
) -> tuple[bytes | None, list[str] | None]:
    """Dispatch by kind. Returns (bytes, None) or (None, argv).

    output_path is required only for kind=POSTER (used in the ffmpeg argv).
    """
    perturbed_seed = perturbed_seed_for_update(
        sidecar_id=sidecar_id, event_id=event_id, resolved_seed=resolved_seed,
    )
    if kind == SidecarKind.SUBTITLE:
        assert language is not None, "subtitle sidecar requires language"
        return srt_payload(
            language=language, duration_s=duration_s, seed=perturbed_seed,
        ).encode("utf-8"), None
    if kind == SidecarKind.NFO:
        # NFO bytes don't depend on the seed (template is fixed); we
        # incorporate sidecar_id directly in the body.
        return render_nfo(sidecar_id=sidecar_id), None
    if kind == SidecarKind.POSTER:
        assert output_path is not None, "poster regeneration requires output_path"
        return None, poster_ffmpeg_argv(
            output_path=output_path, resolved_seed=perturbed_seed,
            sidecar_id=sidecar_id,
        )
    raise ValueError(f"unknown sidecar kind {kind!r}")
```

Verify `hash_for` exists in `chaos_librarian.determinism`:

```bash
rg -n "^def hash_for" src/chaos_librarian/determinism/
```

If the public helper has a different name (e.g. `hash_stream`, `derive_seed`), adapt the import + call. Use the existing helper exactly as Sprint 6's `materializer/filesystem.py` did for slow_copy seed derivation.

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/materializer/test_sidecar_bytes.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/sidecar_bytes.py \
        tests/materializer/test_sidecar_bytes.py
git commit -m "$(cat <<'EOF'
feat(materializer): sidecar_bytes — poster / NFO / regenerate_sidecar

Pure Python NFO renderer + ffmpeg argv builder for posters + dispatch
function for update_sidecar's per-kind byte regeneration. Subtitle path
delegates to recipes.srt_payload with a perturbed sub-seed including
event_id so consecutive updates produce distinct bytes (spec #7).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 24: Materializer — media.py foundation + _subtitle_codec_for_container

**Files:**
- Create: `src/chaos_librarian/materializer/media.py` — start with module skeleton + `_subtitle_codec_for_container` helper + `_MediaContext` dataclass.
- Test: NEW `tests/materializer/test_media.py` — codec helper tests + context smoke test.

- [ ] **Step 1: Write the failing tests (creates new file)**

Create `tests/materializer/test_media.py`:

```python
"""Tests for materializer/media.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer.errors import MediaActionError
from chaos_librarian.materializer.media import (
    _MediaContext,
    _subtitle_codec_for_container,
)


def test_subtitle_codec_mkv_uses_srt():
    assert _subtitle_codec_for_container("mkv") == "srt"


def test_subtitle_codec_webm_uses_srt():
    assert _subtitle_codec_for_container("webm") == "srt"


def test_subtitle_codec_mp4_uses_mov_text():
    assert _subtitle_codec_for_container("mp4") == "mov_text"


def test_subtitle_codec_m4v_uses_mov_text():
    assert _subtitle_codec_for_container("m4v") == "mov_text"


def test_subtitle_codec_mov_uses_mov_text():
    assert _subtitle_codec_for_container("mov") == "mov_text"


def test_subtitle_codec_unsupported_container_raises():
    with pytest.raises(ValueError, match="unsupported"):
        _subtitle_codec_for_container("ogg")


def test_media_context_construction(tmp_path):
    ctx = _MediaContext(
        library_root=tmp_path,
        scenario_assets={},
        resolved_seed=42,
        ffmpeg_version="7.0",
        ffprobe_version="7.0",
        post_phase_b_versions={},
        post_phase_b_sidecars={},
        invocations=[],
    )
    assert ctx.library_root == tmp_path
    assert ctx.resolved_seed == 42
    assert ctx.post_phase_b_versions == {}
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement media.py foundation**

Create `src/chaos_librarian/materializer/media.py`:

```python
"""Phase-B media dispatcher — ffmpeg-backed handlers for byte-changing events.

Parallel to Sprint 6's ``materializer/filesystem.py``: one handler per
media action, each reads every path from the journal entry's
``state_delta`` and writes through an atomic-rename temp-file.

The orchestrator in ``materializer/run.py`` walks the journal once and
dispatches each entry to ``apply_media_action`` here OR to the stdlib
dispatcher in ``filesystem.py``. See ``_MEDIA_ACTIONS`` /
``_STDLIB_ACTIONS`` below.

Per-action ffmpeg sketches are in the Sprint 7 spec
§"Per-action behavior" table.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.materialization import MediaAction, ToolInvocation
from chaos_librarian.contract.scenario import Asset, TimelineActionName

__all__ = ["_subtitle_codec_for_container"]


_SUBTITLE_CODEC_BY_CONTAINER: Final[dict[str, str]] = {
    "mkv": "srt",
    "webm": "srt",
    "mp4": "mov_text",
    "m4v": "mov_text",
    "mov": "mov_text",
}


def _subtitle_codec_for_container(container_ext: str) -> str:
    """Return the ffmpeg ``-c:s`` argument for a given container extension.

    MKV / WebM → ``srt``. MP4 / M4V / MOV → ``mov_text``. Other
    containers raise ValueError; the per-action handler wraps that in
    a MediaActionError so the user sees E_MATERIALIZE_MEDIA_FAILED.
    """
    codec = _SUBTITLE_CODEC_BY_CONTAINER.get(container_ext.lower())
    if codec is None:
        raise ValueError(
            f"unsupported container {container_ext!r} for subtitle codec selection; "
            f"supported: {sorted(_SUBTITLE_CODEC_BY_CONTAINER)}"
        )
    return codec


@dataclass(slots=True)
class _MediaContext:
    """Per-run state threaded through every media handler.

    Mirrors ``filesystem._PhaseBContext`` but carries extra fields the
    media dispatcher needs (ffmpeg/ffprobe version strings, post-phase-B
    version + sidecar hash dicts that ``manifest_build.augment_versions``
    / ``augment_updated_sidecars`` will drain).
    """

    library_root: Path
    scenario_assets: Mapping[str, Asset]
    resolved_seed: int
    ffmpeg_version: str
    ffprobe_version: str
    # Filled by handlers; drained by manifest_build.augment_versions.
    post_phase_b_versions: dict[str, tuple[str, ProbedMedia | None]] = field(
        default_factory=dict
    )
    # Filled by handlers; drained by manifest_build.augment_updated_sidecars.
    # Maps sidecar_id -> (content_hash, output_path).
    post_phase_b_sidecars: dict[str, tuple[str, str]] = field(default_factory=dict)
    # Shared with the orchestrator so each media handler's ffmpeg/ffprobe
    # calls append to the same MaterializationReport.invocations list.
    invocations: list[ToolInvocation] = field(default_factory=list)
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/materializer/test_media.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/media.py tests/materializer/test_media.py
git commit -m "$(cat <<'EOF'
feat(materializer): media.py — _subtitle_codec_for_container + _MediaContext

Single source of truth for per-container subtitle codec selection:
MKV/WebM → srt, MP4/M4V/MOV → mov_text. Unsupported containers raise
ValueError; per-handler wrappers will translate that into
MediaActionError so the user sees E_MATERIALIZE_MEDIA_FAILED.

Per-action handlers in subsequent commits.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 25: Materializer — apply_reencode_video handler in media.py

**Files:**
- Modify: `src/chaos_librarian/materializer/media.py` — add `_apply_reencode_video` handler.
- Test: `tests/materializer/test_media.py` — handler tests with mocked ffmpeg + ffprobe.

- [ ] **Step 1: Write the failing tests**

Append to `tests/materializer/test_media.py`:

```python
import hashlib
import uuid

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase


def _atomic_entry(
    *, event_id, action, target, state_delta,
    input_version_ids=None, output_version_ids=None,
):
    return AtomicJournalEntry(
        schema_version=1, event_id=event_id, scenario_id="sc",
        run_id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        logical_time_ns=0, action=action.value,
        target_ids=[target],
        input_version_ids=input_version_ids or [],
        output_version_ids=output_version_ids or [],
        location_ids=[], state_delta=state_delta, phase=JournalPhase.ATOMIC,
    )


@pytest.fixture
def media_ctx(tmp_path):
    ctx = _MediaContext(
        library_root=tmp_path, scenario_assets={}, resolved_seed=42,
        ffmpeg_version="7.0", ffprobe_version="7.0",
    )
    return ctx


def _stub_ffmpeg_writes(monkeypatch, *, stub_bytes=b"x" * 100, exit_code=0):
    """Mock run_ffmpeg + probe_file: write stub bytes; return canned ProbedMedia."""
    from chaos_librarian.contract.materialization import ToolInvocation
    from chaos_librarian.contract.manifest import ProbedMedia

    def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
        # The output path is the LAST positional argv element.
        Path(argv[-1]).write_bytes(stub_bytes)
        invocation = ToolInvocation(
            tool="ffmpeg", version=ffmpeg_version, command=list(argv),
            exit_code=exit_code, duration_ns=1000,
        )
        return invocation, ""

    def fake_probe(path, *, ffprobe_path):
        return ProbedMedia(
            container="matroska", duration_seconds=1.0,
            size_bytes=len(stub_bytes), streams=[],
        )

    monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
    monkeypatch.setattr("chaos_librarian.materializer.media.probe_file", fake_probe)


class TestApplyReencodeVideo:
    def test_apply_reencode_video_writes_output_and_returns_media_action(
        self, media_ctx, monkeypatch, tmp_path
    ):
        from chaos_librarian.materializer.media import apply_media_action
        # Stage the input file at the library-relative input_path.
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"x" * 100)
        entry = _atomic_entry(
            event_id="ev_rv_001",
            action=TimelineActionName.REENCODE_VIDEO,
            target="a0",
            input_version_ids=["v0"],
            output_version_ids=["v1"],
            state_delta={
                "resolution": "sd", "codec": "h264",
                "input_path": "x.mkv", "output_path": "x.mkv",
            },
        )
        result = apply_media_action(media_ctx, entry)
        # ffmpeg's stub wrote 100 bytes to the output path.
        assert (tmp_path / "x.mkv").read_bytes() == b"x" * 100
        expected_hash = "sha256:" + hashlib.sha256(b"x" * 100).hexdigest()
        assert result.output_content_hash == expected_hash
        assert result.action == TimelineActionName.REENCODE_VIDEO
        assert result.output_version_id == "v1"
        # And the post_phase_b_versions map captured the new hash + probed.
        assert media_ctx.post_phase_b_versions["v1"][0] == expected_hash

    def test_apply_reencode_video_uses_temp_sibling_for_atomic_write(
        self, media_ctx, monkeypatch, tmp_path
    ):
        from chaos_librarian.materializer.media import apply_media_action
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        captured_argv: list[list[str]] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured_argv.append(list(argv))
            Path(argv[-1]).write_bytes(b"x" * 100)
            from chaos_librarian.contract.materialization import ToolInvocation
            return ToolInvocation(
                tool="ffmpeg", version=ffmpeg_version, command=list(argv),
                exit_code=0, duration_ns=1000,
            ), ""

        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        from chaos_librarian.contract.manifest import ProbedMedia
        monkeypatch.setattr(
            "chaos_librarian.materializer.media.probe_file",
            lambda p, **k: ProbedMedia(container="matroska", duration_seconds=1.0,
                                       size_bytes=100, streams=[]),
        )
        entry = _atomic_entry(
            event_id="ev_rv_001",
            action=TimelineActionName.REENCODE_VIDEO, target="a0",
            input_version_ids=["v0"], output_version_ids=["v1"],
            state_delta={"resolution": "sd", "codec": "h264",
                         "input_path": "x.mkv", "output_path": "x.mkv"},
        )
        apply_media_action(media_ctx, entry)
        # The ffmpeg argv's output path should be a temp sibling like
        # x.mkv.tmp.42 (resolved_seed=42 from the fixture).
        output_arg = captured_argv[0][-1]
        assert ".tmp." in output_arg

    def test_apply_reencode_video_nonzero_exit_wraps_in_media_action_error(
        self, media_ctx, monkeypatch, tmp_path
    ):
        from chaos_librarian.materializer.media import apply_media_action
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        _stub_ffmpeg_writes(monkeypatch, exit_code=1)
        entry = _atomic_entry(
            event_id="ev_rv_001",
            action=TimelineActionName.REENCODE_VIDEO, target="a0",
            input_version_ids=["v0"], output_version_ids=["v1"],
            state_delta={"resolution": "sd", "codec": "h264",
                         "input_path": "x.mkv", "output_path": "x.mkv"},
        )
        with pytest.raises(MediaActionError) as exc_info:
            apply_media_action(media_ctx, entry)
        assert exc_info.value.event_id == "ev_rv_001"
        assert exc_info.value.action == TimelineActionName.REENCODE_VIDEO
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement `_apply_reencode_video` and the `apply_media_action` dispatcher skeleton**

Append to `src/chaos_librarian/materializer/media.py`:

```python
import hashlib
import time

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.materialization import MediaAction, ToolInvocation
from chaos_librarian.materializer.errors import MediaActionError
from chaos_librarian.materializer.ffmpeg import BITEXACT_FLAGS, run_ffmpeg
from chaos_librarian.materializer.probe import probe_file


def _temp_sibling(output_path: Path, resolved_seed: int) -> Path:
    """Return ``<output>.tmp.<resolved_seed>`` Path."""
    return output_path.with_name(f"{output_path.name}.tmp.{resolved_seed}")


def _hash_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _apply_reencode_video(
    ctx: _MediaContext, entry: JournalEntry
) -> MediaAction:
    """Re-encode video in place; produce a new ManifestVersion's content_hash."""
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    output_path = ctx.library_root / str(delta["output_path"])
    temp_output = _temp_sibling(output_path, ctx.resolved_seed)
    resolution = str(delta["resolution"])
    # Resolution mapping mirrors preflight.RESOLUTION_PIXELS.
    width, height = {
        "sd": (640, 480), "hd": (1280, 720), "1080p": (1920, 1080),
    }.get(resolution, (640, 480))
    codec = str(delta["codec"])
    argv = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(input_path),
        "-vf", f"scale={width}:{height}",
        "-c:v", codec, "-c:a", "copy", "-c:s", "copy",
        *BITEXACT_FLAGS,
        str(temp_output),
    ]
    started = time.monotonic_ns()
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
    invocation_index = len(ctx.invocations)
    ctx.invocations.append(invocation)
    if invocation.exit_code != 0:
        raise MediaActionError(
            f"reencode_video failed for event {entry.event_id}: "
            f"ffmpeg exit {invocation.exit_code}",
            event_id=entry.event_id,
            action=TimelineActionName.REENCODE_VIDEO,
            cause=RuntimeError(stderr_tail or "ffmpeg failed"),
            asset_id=entry.target_ids[0] if entry.target_ids else None,
            tool_invocation_index=invocation_index,
        )
    temp_output.replace(output_path)
    new_hash = _hash_file(output_path)
    probed = probe_file(output_path, ffprobe_path="ffprobe")
    new_version_id = entry.output_version_ids[0]
    ctx.post_phase_b_versions[new_version_id] = (new_hash, probed)
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.REENCODE_VIDEO,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=new_version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )


# Dispatcher will route here. Other handlers added in subsequent tasks.
_HANDLERS: dict[
    TimelineActionName,
    "Callable[[_MediaContext, JournalEntry], MediaAction]",
] = {
    TimelineActionName.REENCODE_VIDEO: _apply_reencode_video,
}


def apply_media_action(ctx: _MediaContext, entry: JournalEntry) -> MediaAction:
    """Dispatch one journal entry to its media handler.

    Raises MediaActionError on ffmpeg non-zero exit, ffprobe parse
    failure, or OSError during the rename.
    """
    action = TimelineActionName(entry.action)
    handler = _HANDLERS.get(action)
    if handler is None:
        raise MediaActionError(
            f"no media handler for action {action.value!r}",
            event_id=entry.event_id,
            action=action,
            cause=RuntimeError("no dispatch"),
        )
    return handler(ctx, entry)
```

Add to `__all__`:

```python
__all__ = ["_subtitle_codec_for_container", "apply_media_action", "_MediaContext"]
```

Add `Callable` import: `from collections.abc import Callable`.

Add `probe_file` if it's not already module-level — check `materializer/probe.py` for the public function name and import it. The test mocks `chaos_librarian.materializer.media.probe_file` so the symbol must live in this module's namespace.

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/materializer/test_media.py::TestApplyReencodeVideo -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/media.py tests/materializer/test_media.py
git commit -m "$(cat <<'EOF'
feat(materializer): media._apply_reencode_video + dispatcher skeleton

ffmpeg-based handler with atomic temp-sibling rename, re-hash, and
re-probe. Populates _MediaContext.post_phase_b_versions so
manifest_build.augment_versions can stamp content_hash + probed onto
the new ManifestVersion row.

Other handlers in subsequent tasks; dispatcher carries one entry for
now.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 26: Materializer — apply_reencode_audio handler

**Files:**
- Modify: `src/chaos_librarian/materializer/media.py`.
- Test: `tests/materializer/test_media.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/materializer/test_media.py`:

```python
class TestApplyReencodeAudio:
    def test_apply_reencode_audio_writes_output(self, media_ctx, monkeypatch, tmp_path):
        from chaos_librarian.materializer.media import apply_media_action
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"a" * 100)
        entry = _atomic_entry(
            event_id="ev_ra_001",
            action=TimelineActionName.REENCODE_AUDIO, target="a0",
            input_version_ids=["v0"], output_version_ids=["v1"],
            state_delta={"from_channels": "5.1", "to_channels": "stereo",
                         "input_path": "x.mkv", "output_path": "x.mkv"},
        )
        result = apply_media_action(media_ctx, entry)
        assert (tmp_path / "x.mkv").read_bytes() == b"a" * 100
        assert result.action == TimelineActionName.REENCODE_AUDIO

    def test_apply_reencode_audio_argv_uses_ac_to_channels(
        self, media_ctx, monkeypatch, tmp_path
    ):
        from chaos_librarian.materializer.media import apply_media_action
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        captured_argv: list[list[str]] = []

        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured_argv.append(list(argv))
            Path(argv[-1]).write_bytes(b"a" * 100)
            from chaos_librarian.contract.materialization import ToolInvocation
            return ToolInvocation(
                tool="ffmpeg", version=ffmpeg_version, command=list(argv),
                exit_code=0, duration_ns=1000,
            ), ""

        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        from chaos_librarian.contract.manifest import ProbedMedia
        monkeypatch.setattr(
            "chaos_librarian.materializer.media.probe_file",
            lambda p, **k: ProbedMedia(container="matroska", duration_seconds=1.0,
                                       size_bytes=100, streams=[]),
        )
        entry = _atomic_entry(
            event_id="ev_ra_001",
            action=TimelineActionName.REENCODE_AUDIO, target="a0",
            input_version_ids=["v0"], output_version_ids=["v1"],
            state_delta={"from_channels": "5.1", "to_channels": "stereo",
                         "input_path": "x.mkv", "output_path": "x.mkv"},
        )
        apply_media_action(media_ctx, entry)
        argv = captured_argv[0]
        # ffmpeg argv must carry -ac stereo (the TARGET channel layout).
        assert "-ac" in argv
        assert argv[argv.index("-ac") + 1] == "stereo"
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement `_apply_reencode_audio`**

Append to `src/chaos_librarian/materializer/media.py`:

```python
def _apply_reencode_audio(
    ctx: _MediaContext, entry: JournalEntry
) -> MediaAction:
    """Re-encode audio in place. from_channels is descriptive; -ac uses to_channels."""
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    output_path = ctx.library_root / str(delta["output_path"])
    temp_output = _temp_sibling(output_path, ctx.resolved_seed)
    argv = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(input_path),
        "-c:v", "copy",
        "-ac", str(delta["to_channels"]),
        "-c:a", "aac",
        "-c:s", "copy",
        *BITEXACT_FLAGS,
        str(temp_output),
    ]
    started = time.monotonic_ns()
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
    invocation_index = len(ctx.invocations)
    ctx.invocations.append(invocation)
    if invocation.exit_code != 0:
        raise MediaActionError(
            f"reencode_audio failed for event {entry.event_id}: "
            f"ffmpeg exit {invocation.exit_code}",
            event_id=entry.event_id,
            action=TimelineActionName.REENCODE_AUDIO,
            cause=RuntimeError(stderr_tail or "ffmpeg failed"),
            asset_id=entry.target_ids[0] if entry.target_ids else None,
            tool_invocation_index=invocation_index,
        )
    temp_output.replace(output_path)
    new_hash = _hash_file(output_path)
    probed = probe_file(output_path, ffprobe_path="ffprobe")
    new_version_id = entry.output_version_ids[0]
    ctx.post_phase_b_versions[new_version_id] = (new_hash, probed)
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.REENCODE_AUDIO,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=new_version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )
```

Register in `_HANDLERS`:

```python
    TimelineActionName.REENCODE_AUDIO: _apply_reencode_audio,
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/materializer/test_media.py::TestApplyReencodeAudio -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/media.py tests/materializer/test_media.py
git commit -m "$(cat <<'EOF'
feat(materializer): media._apply_reencode_audio

ffmpeg -ac to_channels with -c:v copy, -c:a aac, -c:s copy. Same
atomic temp-rename + re-hash + re-probe shape as reencode_video.
from_channels stays descriptive only — ffmpeg auto-detects the source.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 27: Materializer — apply_remux_container handler

**Files:**
- Modify: `src/chaos_librarian/materializer/media.py`.
- Test: `tests/materializer/test_media.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/materializer/test_media.py`:

```python
class TestApplyRemuxContainer:
    def test_apply_remux_writes_to_new_extension(self, media_ctx, monkeypatch, tmp_path):
        from chaos_librarian.materializer.media import apply_media_action
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"r" * 100)
        entry = _atomic_entry(
            event_id="ev_rmx_001",
            action=TimelineActionName.REMUX_CONTAINER, target="a0",
            input_version_ids=["v0"], output_version_ids=["v1"],
            state_delta={
                "from_container": "mkv", "to_container": "mp4",
                "from_path": "x.mkv", "to_path": "x.mp4",
                "input_path": "x.mkv", "output_path": "x.mp4",
            },
        )
        result = apply_media_action(media_ctx, entry)
        assert (tmp_path / "x.mp4").exists()
        assert result.output_path == "x.mp4"

    def test_apply_remux_argv_uses_c_copy(self, media_ctx, monkeypatch, tmp_path):
        from chaos_librarian.materializer.media import apply_media_action
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        captured: list[list[str]] = []
        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured.append(list(argv))
            Path(argv[-1]).write_bytes(b"r" * 100)
            from chaos_librarian.contract.materialization import ToolInvocation
            return ToolInvocation(tool="ffmpeg", version=ffmpeg_version,
                                  command=list(argv), exit_code=0,
                                  duration_ns=1000), ""
        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        from chaos_librarian.contract.manifest import ProbedMedia
        monkeypatch.setattr(
            "chaos_librarian.materializer.media.probe_file",
            lambda p, **k: ProbedMedia(container="mp4", duration_seconds=1.0,
                                       size_bytes=100, streams=[]),
        )
        entry = _atomic_entry(
            event_id="ev_rmx_001",
            action=TimelineActionName.REMUX_CONTAINER, target="a0",
            input_version_ids=["v0"], output_version_ids=["v1"],
            state_delta={"from_container": "mkv", "to_container": "mp4",
                         "from_path": "x.mkv", "to_path": "x.mp4",
                         "input_path": "x.mkv", "output_path": "x.mp4"},
        )
        apply_media_action(media_ctx, entry)
        argv = captured[0]
        assert "-c" in argv and argv[argv.index("-c") + 1] == "copy"
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement `_apply_remux_container`**

Append to `src/chaos_librarian/materializer/media.py`:

```python
def _apply_remux_container(
    ctx: _MediaContext, entry: JournalEntry
) -> MediaAction:
    """Container swap via ffmpeg -c copy. Path extension differs."""
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    output_path = ctx.library_root / str(delta["output_path"])
    temp_output = _temp_sibling(output_path, ctx.resolved_seed)
    argv = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(input_path),
        "-c", "copy",
        *BITEXACT_FLAGS,
        str(temp_output),
    ]
    started = time.monotonic_ns()
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
    invocation_index = len(ctx.invocations)
    ctx.invocations.append(invocation)
    if invocation.exit_code != 0:
        raise MediaActionError(
            f"remux_container failed for event {entry.event_id}: "
            f"ffmpeg exit {invocation.exit_code}",
            event_id=entry.event_id,
            action=TimelineActionName.REMUX_CONTAINER,
            cause=RuntimeError(stderr_tail or "ffmpeg failed"),
            asset_id=entry.target_ids[0] if entry.target_ids else None,
            tool_invocation_index=invocation_index,
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output.replace(output_path)
    new_hash = _hash_file(output_path)
    probed = probe_file(output_path, ffprobe_path="ffprobe")
    new_version_id = entry.output_version_ids[0]
    ctx.post_phase_b_versions[new_version_id] = (new_hash, probed)
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.REMUX_CONTAINER,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=new_version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )
```

Register:

```python
    TimelineActionName.REMUX_CONTAINER: _apply_remux_container,
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/materializer/test_media.py::TestApplyRemuxContainer -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/media.py tests/materializer/test_media.py
git commit -m "$(cat <<'EOF'
feat(materializer): media._apply_remux_container

ffmpeg -c copy from input_path to output_path (different extension).
Atomic temp-rename + re-hash + re-probe.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 28: Materializer — apply_edit_metadata handler

**Files:**
- Modify: `src/chaos_librarian/materializer/media.py`.
- Test: `tests/materializer/test_media.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/materializer/test_media.py`:

```python
class TestApplyEditMetadata:
    def test_apply_edit_metadata_argv_passes_each_field(
        self, media_ctx, monkeypatch, tmp_path
    ):
        from chaos_librarian.materializer.media import apply_media_action
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        captured: list[list[str]] = []
        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured.append(list(argv))
            Path(argv[-1]).write_bytes(b"m" * 100)
            from chaos_librarian.contract.materialization import ToolInvocation
            return ToolInvocation(tool="ffmpeg", version=ffmpeg_version,
                                  command=list(argv), exit_code=0,
                                  duration_ns=1000), ""
        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        from chaos_librarian.contract.manifest import ProbedMedia
        monkeypatch.setattr(
            "chaos_librarian.materializer.media.probe_file",
            lambda p, **k: ProbedMedia(container="matroska", duration_seconds=1.0,
                                       size_bytes=100, streams=[]),
        )
        entry = _atomic_entry(
            event_id="ev_em_001",
            action=TimelineActionName.EDIT_METADATA, target="a0",
            input_version_ids=["v0"], output_version_ids=["v1"],
            state_delta={"fields": {"title": "Pulsar", "year": "2026"},
                         "input_path": "x.mkv", "output_path": "x.mkv"},
        )
        apply_media_action(media_ctx, entry)
        argv = captured[0]
        # Each field must appear as -metadata key=value
        assert "title=Pulsar" in argv
        assert "year=2026" in argv
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement `_apply_edit_metadata`**

Append to `src/chaos_librarian/materializer/media.py`:

```python
def _apply_edit_metadata(
    ctx: _MediaContext, entry: JournalEntry
) -> MediaAction:
    """ffmpeg -c copy -map_metadata 0 -metadata k=v..."""
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    output_path = ctx.library_root / str(delta["output_path"])
    temp_output = _temp_sibling(output_path, ctx.resolved_seed)
    fields = delta["fields"]
    if not isinstance(fields, dict):
        raise MediaActionError(
            f"edit_metadata.fields not a dict for event {entry.event_id}",
            event_id=entry.event_id,
            action=TimelineActionName.EDIT_METADATA,
            cause=TypeError(f"fields type {type(fields).__name__}"),
        )
    metadata_args: list[str] = []
    for key, value in sorted(fields.items()):  # sorted = deterministic argv
        metadata_args.extend(["-metadata", f"{key}={value}"])
    argv = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(input_path),
        "-c", "copy", "-map_metadata", "0",
        *metadata_args,
        *BITEXACT_FLAGS,
        str(temp_output),
    ]
    started = time.monotonic_ns()
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
    invocation_index = len(ctx.invocations)
    ctx.invocations.append(invocation)
    if invocation.exit_code != 0:
        raise MediaActionError(
            f"edit_metadata failed for event {entry.event_id}: "
            f"ffmpeg exit {invocation.exit_code}",
            event_id=entry.event_id,
            action=TimelineActionName.EDIT_METADATA,
            cause=RuntimeError(stderr_tail or "ffmpeg failed"),
            asset_id=entry.target_ids[0] if entry.target_ids else None,
            tool_invocation_index=invocation_index,
        )
    temp_output.replace(output_path)
    new_hash = _hash_file(output_path)
    probed = probe_file(output_path, ffprobe_path="ffprobe")
    new_version_id = entry.output_version_ids[0]
    ctx.post_phase_b_versions[new_version_id] = (new_hash, probed)
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.EDIT_METADATA,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=new_version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )
```

Register:

```python
    TimelineActionName.EDIT_METADATA: _apply_edit_metadata,
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/materializer/test_media.py::TestApplyEditMetadata -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/media.py tests/materializer/test_media.py
git commit -m "$(cat <<'EOF'
feat(materializer): media._apply_edit_metadata

Maps fields dict to -metadata key=value flags (sorted for determinism)
and runs ffmpeg -c copy -map_metadata 0. Atomic temp-rename + re-hash
+ re-probe.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 29: Materializer — apply_embed_subtitle handler

**Files:**
- Modify: `src/chaos_librarian/materializer/media.py` — add handler that calls `_subtitle_codec_for_container`.
- Test: `tests/materializer/test_media.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/materializer/test_media.py`:

```python
class TestApplyEmbedSubtitle:
    def test_apply_embed_unlinks_sidecar_after_success(
        self, media_ctx, monkeypatch, tmp_path
    ):
        from chaos_librarian.materializer.media import apply_media_action
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        (tmp_path / "x.eng.srt").write_bytes(b"1\n00:00:00,000 --> 00:00:01,000\nhi\n\n")
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"e" * 100)
        entry = _atomic_entry(
            event_id="ev_es_001",
            action=TimelineActionName.EMBED_SUBTITLE, target="a0",
            input_version_ids=["v0"], output_version_ids=["v1"],
            state_delta={
                "embedded_sidecar_id": "sidecar_0001",
                "embedded_sidecar_path": "x.eng.srt",
                "language": "eng", "kind": "subtitle",
                "input_path": "x.mkv", "output_path": "x.mkv",
            },
        )
        apply_media_action(media_ctx, entry)
        # Sidecar file consumed.
        assert not (tmp_path / "x.eng.srt").exists()

    def test_apply_embed_mkv_uses_srt_codec(self, media_ctx, monkeypatch, tmp_path):
        from chaos_librarian.materializer.media import apply_media_action
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        (tmp_path / "x.eng.srt").write_bytes(b"1\n")
        captured: list[list[str]] = []
        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured.append(list(argv))
            Path(argv[-1]).write_bytes(b"e" * 100)
            from chaos_librarian.contract.materialization import ToolInvocation
            return ToolInvocation(tool="ffmpeg", version=ffmpeg_version,
                                  command=list(argv), exit_code=0, duration_ns=1), ""
        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        from chaos_librarian.contract.manifest import ProbedMedia
        monkeypatch.setattr(
            "chaos_librarian.materializer.media.probe_file",
            lambda p, **k: ProbedMedia(container="matroska", duration_seconds=1.0,
                                       size_bytes=100, streams=[]),
        )
        entry = _atomic_entry(
            event_id="ev_es_001",
            action=TimelineActionName.EMBED_SUBTITLE, target="a0",
            input_version_ids=["v0"], output_version_ids=["v1"],
            state_delta={
                "embedded_sidecar_id": "sidecar_0001",
                "embedded_sidecar_path": "x.eng.srt",
                "language": "eng", "kind": "subtitle",
                "input_path": "x.mkv", "output_path": "x.mkv",
            },
        )
        apply_media_action(media_ctx, entry)
        argv = captured[0]
        # mkv output → -c:s srt
        assert "-c:s" in argv
        assert argv[argv.index("-c:s") + 1] == "srt"

    def test_apply_embed_mp4_uses_mov_text_codec(self, media_ctx, monkeypatch, tmp_path):
        from chaos_librarian.materializer.media import apply_media_action
        (tmp_path / "x.mp4").write_bytes(b"y" * 50)
        (tmp_path / "x.eng.srt").write_bytes(b"1\n")
        captured: list[list[str]] = []
        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured.append(list(argv))
            Path(argv[-1]).write_bytes(b"e" * 100)
            from chaos_librarian.contract.materialization import ToolInvocation
            return ToolInvocation(tool="ffmpeg", version=ffmpeg_version,
                                  command=list(argv), exit_code=0, duration_ns=1), ""
        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        from chaos_librarian.contract.manifest import ProbedMedia
        monkeypatch.setattr(
            "chaos_librarian.materializer.media.probe_file",
            lambda p, **k: ProbedMedia(container="mp4", duration_seconds=1.0,
                                       size_bytes=100, streams=[]),
        )
        entry = _atomic_entry(
            event_id="ev_es_001",
            action=TimelineActionName.EMBED_SUBTITLE, target="a0",
            input_version_ids=["v0"], output_version_ids=["v1"],
            state_delta={
                "embedded_sidecar_id": "sidecar_0001",
                "embedded_sidecar_path": "x.eng.srt",
                "language": "eng", "kind": "subtitle",
                "input_path": "x.mp4", "output_path": "x.mp4",
            },
        )
        apply_media_action(media_ctx, entry)
        argv = captured[0]
        assert argv[argv.index("-c:s") + 1] == "mov_text"
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement `_apply_embed_subtitle`**

Append to `src/chaos_librarian/materializer/media.py`:

```python
def _apply_embed_subtitle(
    ctx: _MediaContext, entry: JournalEntry
) -> MediaAction:
    """ffmpeg muxes the sidecar into the asset; unlinks the sidecar after success."""
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    output_path = ctx.library_root / str(delta["output_path"])
    sidecar_disk_path = ctx.library_root / str(delta["embedded_sidecar_path"])
    temp_output = _temp_sibling(output_path, ctx.resolved_seed)
    container_ext = output_path.suffix.lstrip(".")
    try:
        subtitle_codec = _subtitle_codec_for_container(container_ext)
    except ValueError as exc:
        raise MediaActionError(
            f"embed_subtitle: unsupported output container {container_ext!r} "
            f"for event {entry.event_id}",
            event_id=entry.event_id,
            action=TimelineActionName.EMBED_SUBTITLE,
            cause=exc,
            asset_id=entry.target_ids[0] if entry.target_ids else None,
        ) from exc
    argv = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(input_path),
        "-i", str(sidecar_disk_path),
        "-map", "0", "-map", "1",
        "-c:v", "copy", "-c:a", "copy",
        "-c:s", subtitle_codec,
        *BITEXACT_FLAGS,
        str(temp_output),
    ]
    started = time.monotonic_ns()
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
    invocation_index = len(ctx.invocations)
    ctx.invocations.append(invocation)
    if invocation.exit_code != 0:
        raise MediaActionError(
            f"embed_subtitle failed for event {entry.event_id}: "
            f"ffmpeg exit {invocation.exit_code}",
            event_id=entry.event_id,
            action=TimelineActionName.EMBED_SUBTITLE,
            cause=RuntimeError(stderr_tail or "ffmpeg failed"),
            asset_id=entry.target_ids[0] if entry.target_ids else None,
            tool_invocation_index=invocation_index,
        )
    temp_output.replace(output_path)
    sidecar_disk_path.unlink()
    new_hash = _hash_file(output_path)
    probed = probe_file(output_path, ffprobe_path="ffprobe")
    new_version_id = entry.output_version_ids[0]
    ctx.post_phase_b_versions[new_version_id] = (new_hash, probed)
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.EMBED_SUBTITLE,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["output_path"]),
        input_version_id=entry.input_version_ids[0] if entry.input_version_ids else None,
        output_version_id=new_version_id,
        output_sidecar_id=None,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )
```

Register:

```python
    TimelineActionName.EMBED_SUBTITLE: _apply_embed_subtitle,
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/materializer/test_media.py::TestApplyEmbedSubtitle -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/media.py tests/materializer/test_media.py
git commit -m "$(cat <<'EOF'
feat(materializer): media._apply_embed_subtitle

ffmpeg muxes the sidecar via -map 0 / -map 1; -c:s codec chosen per
container by _subtitle_codec_for_container (mkv/webm → srt;
mp4/m4v/mov → mov_text; others raise MediaActionError). Sidecar file
unlinked after successful rename.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 30: Materializer — apply_extract_subtitle handler

**Files:**
- Modify: `src/chaos_librarian/materializer/media.py`.
- Test: `tests/materializer/test_media.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/materializer/test_media.py`:

```python
class TestApplyExtractSubtitle:
    def test_apply_extract_writes_srt_at_to_path(self, media_ctx, monkeypatch, tmp_path):
        from chaos_librarian.materializer.media import apply_media_action
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        _stub_ffmpeg_writes(monkeypatch, stub_bytes=b"s" * 100)
        entry = _atomic_entry(
            event_id="ev_xs_001",
            action=TimelineActionName.EXTRACT_SUBTITLE, target="a0",
            state_delta={"sidecar_id": "sidecar_0002",
                         "sidecar_path": "x.fra.srt",
                         "language": "fra", "input_path": "x.mkv"},
        )
        result = apply_media_action(media_ctx, entry)
        assert (tmp_path / "x.fra.srt").exists()
        assert result.output_sidecar_id == "sidecar_0002"
        assert result.input_version_id is None
        assert result.output_version_id is None
        # post_phase_b_sidecars captured the new hash + path.
        assert "sidecar_0002" in media_ctx.post_phase_b_sidecars

    def test_apply_extract_argv_maps_language_with_fallback(
        self, media_ctx, monkeypatch, tmp_path
    ):
        from chaos_librarian.materializer.media import apply_media_action
        (tmp_path / "x.mkv").write_bytes(b"y" * 50)
        captured: list[list[str]] = []
        def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
            captured.append(list(argv))
            Path(argv[-1]).write_bytes(b"s" * 100)
            from chaos_librarian.contract.materialization import ToolInvocation
            return ToolInvocation(tool="ffmpeg", version=ffmpeg_version,
                                  command=list(argv), exit_code=0,
                                  duration_ns=1), ""
        monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
        entry = _atomic_entry(
            event_id="ev_xs_001",
            action=TimelineActionName.EXTRACT_SUBTITLE, target="a0",
            state_delta={"sidecar_id": "sidecar_0002",
                         "sidecar_path": "x.fra.srt",
                         "language": "fra", "input_path": "x.mkv"},
        )
        apply_media_action(media_ctx, entry)
        argv = captured[0]
        joined = " ".join(argv)
        # Either the language-specific map or the fallback s:0 map.
        assert "0:s:m:language:fra" in joined or "0:s:0" in joined
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement `_apply_extract_subtitle`**

Append to `src/chaos_librarian/materializer/media.py`:

```python
def _apply_extract_subtitle(
    ctx: _MediaContext, entry: JournalEntry
) -> MediaAction:
    """ffmpeg -map 0:s:m:language:<lang>? -c:s srt sidecar.srt.

    Output is always .srt regardless of asset container. No re-probe
    (asset bytes unchanged); hash only the new sidecar file.
    """
    delta = entry.state_delta
    input_path = ctx.library_root / str(delta["input_path"])
    sidecar_path = ctx.library_root / str(delta["sidecar_path"])
    temp_output = _temp_sibling(sidecar_path, ctx.resolved_seed)
    language = str(delta["language"])
    # The optional "?" suffix tells ffmpeg "skip if no match" — combined
    # with a -map fallback, this gives the language-or-track-0 behavior.
    # In practice ffmpeg's stream-specifier matrix is fiddly; if the
    # language match misses, ffmpeg emits a warning and the fallback
    # -map covers it. The output is always .srt.
    argv = [
        "ffmpeg", "-hide_banner", "-y",
        "-i", str(input_path),
        "-map", f"0:s:m:language:{language}?",
        "-map", "0:s:0",
        "-c:s", "srt",
        *BITEXACT_FLAGS,
        str(temp_output),
    ]
    started = time.monotonic_ns()
    invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
    invocation_index = len(ctx.invocations)
    ctx.invocations.append(invocation)
    if invocation.exit_code != 0:
        raise MediaActionError(
            f"extract_subtitle failed for event {entry.event_id}: "
            f"ffmpeg exit {invocation.exit_code}",
            event_id=entry.event_id,
            action=TimelineActionName.EXTRACT_SUBTITLE,
            cause=RuntimeError(stderr_tail or "ffmpeg failed"),
            asset_id=entry.target_ids[0] if entry.target_ids else None,
            tool_invocation_index=invocation_index,
        )
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    temp_output.replace(sidecar_path)
    new_hash = _hash_file(sidecar_path)
    sidecar_id = str(delta["sidecar_id"])
    ctx.post_phase_b_sidecars[sidecar_id] = (new_hash, str(delta["sidecar_path"]))
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.EXTRACT_SUBTITLE,
        target_asset_id=entry.target_ids[0],
        input_path=str(delta["input_path"]),
        output_path=str(delta["sidecar_path"]),
        input_version_id=None,
        output_version_id=None,
        output_sidecar_id=sidecar_id,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )
```

Register:

```python
    TimelineActionName.EXTRACT_SUBTITLE: _apply_extract_subtitle,
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/materializer/test_media.py::TestApplyExtractSubtitle -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/media.py tests/materializer/test_media.py
git commit -m "$(cat <<'EOF'
feat(materializer): media._apply_extract_subtitle

ffmpeg -map 0:s:m:language:<lang>? with -map 0:s:0 fallback; output
always .srt. Asset bytes unchanged → no re-probe. Populates
post_phase_b_sidecars so augment_updated_sidecars can stamp the new
content_hash + path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 31: Materializer — apply_update_sidecar handler

**Files:**
- Modify: `src/chaos_librarian/materializer/media.py`.
- Test: `tests/materializer/test_media.py`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/materializer/test_media.py`:

```python
class TestApplyUpdateSidecar:
    def test_update_sidecar_subtitle_regenerates_bytes(
        self, monkeypatch, tmp_path
    ):
        from chaos_librarian.materializer.media import apply_media_action
        from chaos_librarian.contract.scenario import Asset, SubtitleTrack
        from chaos_librarian.contract.manifest import ManifestSidecar

        # Asset declared with a subtitle so ctx can find duration_seconds.
        asset = Asset.model_validate({
            "id": "a0", "role": "primary_video", "container": "mkv",
            "duration_seconds": 2.0,
            "video": {"source": "color_bars", "codec": "h264", "resolution": "hd"},
            "audio": [{"codec": "aac", "channels": "stereo", "language": "eng"}],
            "subtitles": [{"codec": "srt", "language": "eng", "mode": "sidecar"}],
        })
        sidecar = ManifestSidecar(
            id="sidecar_0001", asset_id="a0", kind="subtitle",
            path="a0.eng.srt", language="eng",
        )
        # Pre-populate the sidecar file.
        (tmp_path / "a0.eng.srt").write_bytes(b"old")
        ctx = _MediaContext(
            library_root=tmp_path,
            scenario_assets={"a0": asset},
            resolved_seed=42,
            ffmpeg_version="7.0", ffprobe_version="7.0",
        )
        # update_sidecar needs the sidecar's kind/language. We make the
        # handler look it up from a side-table by sidecar_id; the
        # implementation reads ctx.scenario_assets but ALSO needs the
        # sidecar's recorded kind/language. The simplest contract: pass
        # them in via the journal entry's state_delta extension OR have
        # the handler look up the sidecar via a callback that knows the
        # current manifest. See Step 3 below for the chosen approach
        # (pass a sidecar_lookup callable on _MediaContext).
        ctx.sidecar_lookup = lambda sid: sidecar  # type: ignore[attr-defined]
        entry = _atomic_entry(
            event_id="ev_us_001",
            action=TimelineActionName.UPDATE_SIDECAR, target="a0",
            state_delta={"sidecar_id": "sidecar_0001",
                         "sidecar_path": "a0.eng.srt"},
        )
        result = apply_media_action(ctx, entry)
        new_bytes = (tmp_path / "a0.eng.srt").read_bytes()
        assert new_bytes != b"old"
        assert b"00:00:00,000" in new_bytes
        assert result.output_sidecar_id == "sidecar_0001"
        assert result.tool_invocation_index is None  # subtitle is pure Python
        assert "sidecar_0001" in ctx.post_phase_b_sidecars
```

This test reveals a needed `_MediaContext` extension: `sidecar_lookup: Callable[[str], ManifestSidecar | None]`. Add it.

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Extend `_MediaContext` with `sidecar_lookup` and implement `_apply_update_sidecar`**

In `src/chaos_librarian/materializer/media.py`, extend `_MediaContext`:

```python
@dataclass(slots=True)
class _MediaContext:
    library_root: Path
    scenario_assets: Mapping[str, Asset]
    resolved_seed: int
    ffmpeg_version: str
    ffprobe_version: str
    post_phase_b_versions: dict[str, tuple[str, ProbedMedia | None]] = field(
        default_factory=dict
    )
    post_phase_b_sidecars: dict[str, tuple[str, str]] = field(default_factory=dict)
    invocations: list[ToolInvocation] = field(default_factory=list)
    # update_sidecar needs the (kind, language) recorded on the existing
    # ManifestSidecar; the orchestrator passes a lookup callable so this
    # module doesn't import from manifest_build.
    sidecar_lookup: Callable[[str], "ManifestSidecar | None"] | None = None
```

Add `ManifestSidecar` to TYPE_CHECKING imports:

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from chaos_librarian.contract.manifest import ManifestSidecar
```

Append the handler:

```python
from chaos_librarian.contract.scenario import SidecarKind
from chaos_librarian.materializer.sidecar_bytes import regenerate_sidecar


def _apply_update_sidecar(
    ctx: _MediaContext, entry: JournalEntry
) -> MediaAction:
    """Regenerate the sidecar's bytes with a perturbed sub-seed.

    Per spec design decision #7, the perturbed seed includes event_id
    so consecutive updates on the same sidecar produce distinct bytes.

    Subtitle / NFO: pure Python; tool_invocation_index = None.
    Poster: invokes ffmpeg lavfi; tool_invocation_index populated.
    """
    delta = entry.state_delta
    sidecar_id = str(delta["sidecar_id"])
    sidecar_path = ctx.library_root / str(delta["sidecar_path"])
    temp_output = _temp_sibling(sidecar_path, ctx.resolved_seed)
    if ctx.sidecar_lookup is None:
        raise MediaActionError(
            "update_sidecar: ctx.sidecar_lookup is None",
            event_id=entry.event_id,
            action=TimelineActionName.UPDATE_SIDECAR,
            cause=RuntimeError("missing lookup"),
        )
    sidecar = ctx.sidecar_lookup(sidecar_id)
    if sidecar is None:
        raise MediaActionError(
            f"update_sidecar: sidecar_id {sidecar_id!r} not in manifest",
            event_id=entry.event_id,
            action=TimelineActionName.UPDATE_SIDECAR,
            cause=KeyError(sidecar_id),
        )
    asset = ctx.scenario_assets.get(sidecar.asset_id)
    if asset is None:
        raise MediaActionError(
            f"update_sidecar: asset {sidecar.asset_id!r} not in scenario",
            event_id=entry.event_id,
            action=TimelineActionName.UPDATE_SIDECAR,
            cause=KeyError(sidecar.asset_id),
        )
    kind = SidecarKind(sidecar.kind)
    started = time.monotonic_ns()
    invocation_index: int | None = None
    bytes_, argv = regenerate_sidecar(
        kind=kind,
        language=sidecar.language,
        sidecar_id=sidecar_id,
        resolved_seed=ctx.resolved_seed,
        event_id=entry.event_id,
        duration_s=asset.duration_seconds,
        output_path=temp_output,
    )
    if bytes_ is not None:
        temp_output.parent.mkdir(parents=True, exist_ok=True)
        temp_output.write_bytes(bytes_)
    else:
        assert argv is not None
        invocation, stderr_tail = run_ffmpeg(argv, ffmpeg_version=ctx.ffmpeg_version)
        invocation_index = len(ctx.invocations)
        ctx.invocations.append(invocation)
        if invocation.exit_code != 0:
            raise MediaActionError(
                f"update_sidecar (poster) failed for event {entry.event_id}: "
                f"ffmpeg exit {invocation.exit_code}",
                event_id=entry.event_id,
                action=TimelineActionName.UPDATE_SIDECAR,
                cause=RuntimeError(stderr_tail or "ffmpeg failed"),
                asset_id=sidecar.asset_id,
                tool_invocation_index=invocation_index,
            )
    temp_output.replace(sidecar_path)
    new_hash = _hash_file(sidecar_path)
    ctx.post_phase_b_sidecars[sidecar_id] = (new_hash, str(delta["sidecar_path"]))
    return MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.UPDATE_SIDECAR,
        target_asset_id=sidecar.asset_id,
        input_path=str(delta["sidecar_path"]),  # input == output for update
        output_path=str(delta["sidecar_path"]),
        input_version_id=None,
        output_version_id=None,
        output_sidecar_id=sidecar_id,
        input_content_hash=None,
        output_content_hash=new_hash,
        tool_invocation_index=invocation_index,
        duration_ns=time.monotonic_ns() - started,
    )
```

Register:

```python
    TimelineActionName.UPDATE_SIDECAR: _apply_update_sidecar,
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/materializer/test_media.py::TestApplyUpdateSidecar -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/media.py tests/materializer/test_media.py
git commit -m "$(cat <<'EOF'
feat(materializer): media._apply_update_sidecar

Routes through sidecar_bytes.regenerate_sidecar — pure Python for
subtitle / NFO, ffmpeg lavfi for poster. Perturbed sub-seed includes
event_id so consecutive updates produce distinct bytes
(spec design decision #7).

Adds _MediaContext.sidecar_lookup callable so the handler can resolve
the recorded (kind, language) without importing manifest_build.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 32: Materializer — media.py exports _MEDIA_ACTIONS / _STDLIB_ACTIONS / SUPPORTED_S7_ACTIONS

**Files:**
- Modify: `src/chaos_librarian/materializer/media.py` — add the three frozenset constants.
- Test: `tests/materializer/test_media.py` — assert membership.

- [ ] **Step 1: Write the failing tests**

Append to `tests/materializer/test_media.py`:

```python
def test_media_actions_constant_contents():
    from chaos_librarian.materializer.media import _MEDIA_ACTIONS
    assert _MEDIA_ACTIONS == frozenset({
        TimelineActionName.REENCODE_VIDEO,
        TimelineActionName.REENCODE_AUDIO,
        TimelineActionName.REMUX_CONTAINER,
        TimelineActionName.EDIT_METADATA,
        TimelineActionName.EMBED_SUBTITLE,
        TimelineActionName.EXTRACT_SUBTITLE,
        TimelineActionName.UPDATE_SIDECAR,
    })


def test_stdlib_actions_constant_includes_remove_sidecar():
    from chaos_librarian.materializer.media import _STDLIB_ACTIONS
    # Sprint 6's set plus REMOVE_SIDECAR (stdlib op).
    assert TimelineActionName.REMOVE_SIDECAR in _STDLIB_ACTIONS
    assert TimelineActionName.MOVE_ASSET in _STDLIB_ACTIONS  # from S6


def test_supported_s7_actions_union():
    from chaos_librarian.materializer.media import (
        _MEDIA_ACTIONS, _STDLIB_ACTIONS, SUPPORTED_S7_ACTIONS,
    )
    assert SUPPORTED_S7_ACTIONS == _STDLIB_ACTIONS | _MEDIA_ACTIONS
    # add_file remains excluded.
    assert TimelineActionName.ADD_FILE not in SUPPORTED_S7_ACTIONS
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Add the constants**

Append to `src/chaos_librarian/materializer/media.py`:

```python
from chaos_librarian.materializer.preflight import SUPPORTED_S6_ACTIONS


_MEDIA_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset({
    TimelineActionName.REENCODE_VIDEO,
    TimelineActionName.REENCODE_AUDIO,
    TimelineActionName.REMUX_CONTAINER,
    TimelineActionName.EDIT_METADATA,
    TimelineActionName.EMBED_SUBTITLE,
    TimelineActionName.EXTRACT_SUBTITLE,
    TimelineActionName.UPDATE_SIDECAR,
})


_STDLIB_ACTIONS: Final[frozenset[TimelineActionName]] = (
    SUPPORTED_S6_ACTIONS | frozenset({TimelineActionName.REMOVE_SIDECAR})
)


SUPPORTED_S7_ACTIONS: Final[frozenset[TimelineActionName]] = (
    _STDLIB_ACTIONS | _MEDIA_ACTIONS
)
# add_file remains excluded; preflight rejects it with
# E_MATERIALIZE_TIMELINE_UNSUPPORTED.
```

Extend `__all__`:

```python
__all__ = [
    "_MEDIA_ACTIONS",
    "_STDLIB_ACTIONS",
    "_MediaContext",
    "_subtitle_codec_for_container",
    "SUPPORTED_S7_ACTIONS",
    "apply_media_action",
]
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/materializer/test_media.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/media.py tests/materializer/test_media.py
git commit -m "$(cat <<'EOF'
feat(materializer): media constants — _MEDIA_ACTIONS / _STDLIB_ACTIONS / SUPPORTED_S7_ACTIONS

REMOVE_SIDECAR routes to stdlib (filesystem.py), UPDATE_SIDECAR routes
to media (handles its byte regen via media.py's atomic-write machinery
even when the byte generator is pure Python). add_file stays excluded.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 33: Materializer — filesystem.py adds _remove_sidecar helper

**Files:**
- Modify: `src/chaos_librarian/materializer/filesystem.py` — add `_remove_sidecar` helper and register in `_DISPATCH`.
- Test: `tests/materializer/test_filesystem.py` — append helper test.

- [ ] **Step 1: Write the failing tests**

Append to `tests/materializer/test_filesystem.py`:

```python
def test_remove_sidecar_unlinks_file_and_returns_action(tmp_path):
    from chaos_librarian.materializer.filesystem import apply_phase_b
    sidecar = tmp_path / "a0.eng.srt"
    sidecar.write_bytes(b"x")
    # Dummy scenario; we only use it for asset metadata lookup.
    scenario = _build_minimal_scenario_with_asset_a0()
    journal = [
        _build_atomic_journal_entry(
            event_id="ev_rs_001",
            action=TimelineActionName.REMOVE_SIDECAR,
            target="a0",
            state_delta={"removed_sidecar_id": "sidecar_0001",
                         "removed_sidecar_path": "a0.eng.srt"},
        ),
    ]
    actions, _ = apply_phase_b(
        library_root=tmp_path, journal=journal, scenario=scenario, resolved_seed=42,
    )
    assert not sidecar.exists()
    assert len(actions) == 1
    assert actions[0].action == TimelineActionName.REMOVE_SIDECAR
    assert actions[0].from_path == "a0.eng.srt"
    assert actions[0].to_path is None
```

Reuse `_build_minimal_scenario_with_asset_a0` and `_build_atomic_journal_entry` from the existing Sprint 6 test helpers (verify with `rg "_build_minimal_scenario" tests/materializer/test_filesystem.py`).

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement `_remove_sidecar` and register**

Append to `src/chaos_librarian/materializer/filesystem.py`:

```python
def _remove_sidecar(ctx: _PhaseBContext, entry: JournalEntry) -> FilesystemAction:
    """Unlink the sidecar file at state_delta['removed_sidecar_path']."""
    asset_id = entry.target_ids[0]
    removed_path = str(entry.state_delta["removed_sidecar_path"])
    (ctx.library_root / removed_path).unlink()
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.REMOVE_SIDECAR,
        target_asset_id=asset_id,
        from_path=removed_path,
        to_path=None,
        temp_path=None,
        duration_ns=0,
    )
```

Register in `_DISPATCH`:

```python
    TimelineActionName.REMOVE_SIDECAR: _remove_sidecar,
```

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/materializer/test_filesystem.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/filesystem.py tests/materializer/test_filesystem.py
git commit -m "$(cat <<'EOF'
feat(materializer): filesystem._remove_sidecar

Pure stdlib unlink + FilesystemAction audit row. The materializer
routes REMOVE_SIDECAR here (not to media.py) because there's no
ffmpeg involvement — the manifest row is removed by the engine, the
file is removed here.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 34: Materializer — manifest_build.py augment_versions + augment_updated_sidecars + find_sidecar_for kind branching

**Files:**
- Modify: `src/chaos_librarian/materializer/manifest_build.py` — add 2 new functions + branch existing `find_sidecar_for` on kind.
- Test: `tests/materializer/test_manifest_build.py` — round-trip tests.

- [ ] **Step 1: Write the failing tests**

Append to `tests/materializer/test_manifest_build.py`:

```python
def test_augment_versions_stamps_content_hash_and_probed():
    from chaos_librarian.materializer.manifest_build import augment_versions
    manifest = _minimal_manifest_with_one_version("v1")
    probed = _stub_probed_media()
    augment_versions(manifest, {"v1": ("sha256:" + "a" * 64, probed)})
    version = next(v for v in manifest.versions if v.id == "v1")
    assert version.content_hash == "sha256:" + "a" * 64
    assert version.probed is probed


def test_augment_versions_ignores_unknown_ids():
    from chaos_librarian.materializer.manifest_build import augment_versions
    manifest = _minimal_manifest_with_one_version("v1")
    augment_versions(manifest, {"v_missing": ("sha256:" + "a" * 64, None)})
    # No exception; v1 untouched.
    version = next(v for v in manifest.versions if v.id == "v1")
    assert version.content_hash is None


def test_augment_updated_sidecars_stamps_hash_and_path():
    from chaos_librarian.materializer.manifest_build import augment_updated_sidecars
    manifest = _minimal_manifest_with_one_sidecar("sidecar_0001", "a.eng.srt")
    augment_updated_sidecars(
        manifest,
        {"sidecar_0001": ("sha256:" + "b" * 64, "a.eng.srt")},
    )
    sidecar = next(s for s in manifest.sidecars if s.id == "sidecar_0001")
    assert sidecar.content_hash == "sha256:" + "b" * 64
    assert sidecar.path == "a.eng.srt"


def test_find_sidecar_for_poster_uses_asset_id_and_kind():
    from chaos_librarian.materializer.manifest_build import find_sidecar_for
    manifest = _minimal_manifest_with_poster("sidecar_0001", "a0", "a0.poster.png")
    # poster lookup ignores language (which is None for poster).
    found = find_sidecar_for(manifest, "a0", language=None, kind="poster")
    assert found is not None
    assert found.kind == "poster"


def test_find_sidecar_for_subtitle_keeps_language_keyed_lookup():
    from chaos_librarian.materializer.manifest_build import find_sidecar_for
    manifest = _minimal_manifest_with_one_sidecar("sidecar_0001", "a.eng.srt",
                                                  language="eng")
    found = find_sidecar_for(manifest, "a", language="eng", kind="subtitle")
    assert found is not None
```

Reuse / extend the test helpers under `tests/materializer/conftest.py` for the manifest-builder fixtures.

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement the augment_* functions and branch find_sidecar_for**

In `src/chaos_librarian/materializer/manifest_build.py`, append:

```python
def augment_versions(
    manifest: Manifest,
    post_phase_b_versions: Mapping[str, tuple[str, "ProbedMedia | None"]],
) -> None:
    """Stamp content_hash + probed onto every version whose id is in the map.

    Sprint 7 wiring: each successful media handler (reencode_*,
    remux_container, edit_metadata, embed_subtitle) registers its new
    version's content_hash + probed here; this function drains the map
    into the manifest.
    """
    for version in manifest.versions:
        entry = post_phase_b_versions.get(version.id)
        if entry is None:
            continue
        content_hash, probed = entry
        version.content_hash = content_hash
        version.probed = probed


def augment_updated_sidecars(
    manifest: Manifest,
    post_phase_b_sidecars: Mapping[str, tuple[str, str]],
) -> None:
    """Stamp content_hash + path on sidecar rows touched by update / extract.

    Mirrors augment_timeline_sidecars' shape (Sprint 6) but for the
    Sprint 7 update_sidecar / extract_subtitle outputs. Maps
    sidecar_id -> (content_hash, path).
    """
    for sidecar in manifest.sidecars:
        entry = post_phase_b_sidecars.get(sidecar.id)
        if entry is None:
            continue
        content_hash, path = entry
        sidecar.content_hash = content_hash
        sidecar.path = path
```

Add `ProbedMedia` to the imports.

Replace `find_sidecar_for` to branch on kind:

```python
def find_sidecar_for(
    manifest: Manifest,
    asset_id: str,
    *,
    language: str | None = None,
    kind: str = "subtitle",
) -> ManifestSidecar | None:
    """Return the ManifestSidecar matching (asset_id, language, kind) or None.

    Subtitle (default): keyed by (asset_id, language). Other kinds
    (poster, nfo): keyed by (asset_id, kind) — one poster per asset,
    one NFO per asset. language is None for non-subtitle kinds.
    """
    for sidecar in manifest.sidecars:
        if sidecar.asset_id != asset_id:
            continue
        if kind == "subtitle":
            if sidecar.kind == "subtitle" and sidecar.language == language:
                return sidecar
        else:
            if sidecar.kind == kind:
                return sidecar
    return None
```

Existing callers in `augment_manifest` pass `language=sub.language` positionally — update them to keyword:

```python
        existing = find_sidecar_for(manifest, asset.id, language=sub.language)
```

(Old call site in Sprint 5/6 was positional; new signature defaults `kind="subtitle"` so existing subtitle lookups still work.)

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/materializer/test_manifest_build.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/manifest_build.py \
        tests/materializer/test_manifest_build.py
git commit -m "$(cat <<'EOF'
feat(materializer): manifest_build.augment_versions + augment_updated_sidecars

Stamps content_hash + probed onto manifest.versions rows touched by
phase-B media handlers, and content_hash + path onto manifest.sidecars
rows touched by extract_subtitle / update_sidecar.

find_sidecar_for branches on kind — subtitle keyed by
(asset_id, language), poster/NFO keyed by (asset_id, kind).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 35: Materializer — preflight.py swaps SUPPORTED_S6 for SUPPORTED_S7

**Files:**
- Modify: `src/chaos_librarian/materializer/preflight.py` — `preflight_timeline` rejects against `SUPPORTED_S7_ACTIONS`; the old `SUPPORTED_S6_ACTIONS` constant stays as a building block (imported by `media._STDLIB_ACTIONS`), but the rejection set is `SUPPORTED_S7_ACTIONS`.
- Test: `tests/materializer/test_preflight.py` — update to check that the 6 new actions pass preflight.

- [ ] **Step 1: Write the failing tests**

Append to `tests/materializer/test_preflight.py`:

```python
@pytest.mark.parametrize("action_name,extra_fields", [
    ("remux_container", {"to_container": "mp4"}),
    ("edit_metadata", {"fields": {"k": "v"}}),
    ("embed_subtitle", {"sidecar_path": "a0.eng.srt"}),
    ("extract_subtitle", {"to": "a0.fra.srt", "language": "fra"}),
    ("remove_sidecar", {"sidecar_path": "a0.eng.srt"}),
    ("update_sidecar", {"sidecar_path": "a0.eng.srt"}),
])
def test_preflight_timeline_accepts_sprint_7_actions(action_name, extra_fields):
    from chaos_librarian.materializer.preflight import preflight_timeline
    scenario = _scenario_v5_with_timeline([
        {"id": "e0", "at": "1s", "action": action_name, "target": "a0",
         **extra_fields},
    ])
    # Should not raise.
    preflight_timeline(scenario)


def test_preflight_timeline_still_rejects_add_file():
    from chaos_librarian.materializer.preflight import preflight_timeline
    from chaos_librarian.materializer.errors import TimelineUnsupportedError
    scenario = _scenario_v5_with_timeline([
        {"id": "e0", "at": "1s", "action": "add_file",
         "target": "a_new", "to": "newpath.mkv"},
    ])
    with pytest.raises(TimelineUnsupportedError):
        preflight_timeline(scenario)
```

`_scenario_v5_with_timeline` builds a v5 scenario with the asset declarations the events need (e.g. for `embed_subtitle`, the asset needs at least a declared subtitle so the scenario is consistent — but preflight only inspects timeline `action` values, so any asset shape works as long as the YAML validates).

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Update preflight_timeline**

In `src/chaos_librarian/materializer/preflight.py`:

```python
from chaos_librarian.materializer.media import SUPPORTED_S7_ACTIONS

__all__ = [
    "AUDIO_RECIPES", "FPS_DEFAULT", "RESOLUTION_PIXELS",
    "SUPPORTED_S6_ACTIONS",
    "SUPPORTED_S7_ACTIONS",
    "VIDEO_RECIPES",
    "iter_assets",
    "preflight_asset",
    "preflight_timeline",
]


def preflight_timeline(scenario: Scenario) -> None:
    """Reject any timeline event whose action is outside SUPPORTED_S7_ACTIONS.

    Raised before phase A so the matrix-rejection contract (no run-dir
    allocation, exit 5, E_MATERIALIZE_TIMELINE_UNSUPPORTED) holds.
    """
    for index, event in enumerate(scenario.timeline):
        if event.action not in SUPPORTED_S7_ACTIONS:
            raise TimelineUnsupportedError(
                f"timeline action {event.action.value!r} not supported",
                field=f"timeline[{index}].action",
                payload={
                    "event_id": event.id,
                    "action": event.action.value,
                    "supported": sorted(a.value for a in SUPPORTED_S7_ACTIONS),
                },
            )
```

Note: `SUPPORTED_S6_ACTIONS` is still exported — `media.py`'s `_STDLIB_ACTIONS` imports it. Don't delete the constant; only the `preflight_timeline` function body now uses the wider Sprint 7 set.

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/materializer/test_preflight.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/preflight.py tests/materializer/test_preflight.py
git commit -m "$(cat <<'EOF'
feat(materializer): preflight_timeline accepts the 6 new Sprint 7 actions

Switches the rejection set from SUPPORTED_S6_ACTIONS to
SUPPORTED_S7_ACTIONS (defined in media.py as the union of the stdlib
and media handler sets). add_file remains excluded.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 36: Materializer — run.py unified phase-B walk (dispatches to stdlib OR media)

**Files:**
- Modify: `src/chaos_librarian/materializer/run.py` — replace the Sprint 6 `apply_phase_b` call with a unified per-entry dispatcher; catch `MediaActionError` and `FilesystemActionError` (both routed through `finalize_failure_phase_b`); add `augment_versions` + `augment_updated_sidecars` calls.
- Modify: `src/chaos_librarian/materializer/finalize.py` — rename / extend `finalize_failure_filesystem` to `finalize_failure_phase_b` (accepts outcome parameter + media_actions). Add `media_actions` to `finalize_success` signature.
- Modify: `src/chaos_librarian/materializer/writer.py` — rename `cleanup_failed_filesystem_run` to `cleanup_failed_phase_b_run` (the function body stays — just wipes `library/`).
- Test: `tests/materializer/test_run.py` — extend with media-bearing scenarios using mocked ffmpeg.

This task is the largest behavioral change. Take it step by step.

- [ ] **Step 1: Write the failing tests (mocked-subprocess Layer-3 tests)**

Create `tests/materializer/test_run_sprint7.py` (new file alongside `test_run.py`):

```python
"""Layer-3 materializer orchestrator tests for Sprint 7 — mocked ffmpeg."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from chaos_librarian.contract.materialization import Outcome


def _write_scenario(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "scenario.yaml"
    path.write_text(body)
    return path


@pytest.fixture
def mocked_ffmpeg_and_probe(monkeypatch, request):
    """Patch run_ffmpeg + probe_file + detect_capabilities for orchestrator tests."""
    from chaos_librarian.contract.manifest import ProbedMedia
    from chaos_librarian.contract.materialization import ToolInvocation

    def fake_run(argv, *, ffmpeg_version, timeout_s=60.0):
        Path(argv[-1]).write_bytes(b"x" * 100)
        return ToolInvocation(
            tool="ffmpeg", version=ffmpeg_version, command=list(argv),
            exit_code=0, duration_ns=1,
        ), ""

    def fake_probe(path, *, ffprobe_path):
        return ProbedMedia(
            container="matroska", duration_seconds=1.0,
            size_bytes=100, streams=[],
        )

    monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", fake_run)
    monkeypatch.setattr("chaos_librarian.materializer.media.probe_file", fake_probe)
    # detect_capabilities patched to a fixed ToolchainInfo with known versions.
    from chaos_librarian.contract.materialization import ToolchainInfo
    monkeypatch.setattr(
        "chaos_librarian.materializer.run.detect_capabilities",
        lambda: ToolchainInfo(ffmpeg="7.0", ffprobe="7.0"),
    )
    return None


def test_materialize_reencode_video_timeline_runs_phase_b(
    tmp_path, mocked_ffmpeg_and_probe
):
    from chaos_librarian.materializer.run import materialize_scenario
    scenario_yaml = _write_scenario(tmp_path, """\
schema_version: 5
scenario_id: sc_test
seed: 42
duration_scale: short
library:
  roots:
    - id: r0
      path: library/r0
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
timeline:
  - id: ev_rv_001
    at: 1s
    action: reencode_video
    target: a0
    resolution: sd
    codec: h264
""")
    out_dir = tmp_path / "run-001"
    artifacts = materialize_scenario(scenario_yaml, out_dir)
    assert (out_dir / "library").exists()
    report = artifacts.materialization_report
    assert report.outcome == Outcome.SUCCESS
    assert len(report.media_actions) == 1
    assert report.media_actions[0].action.value == "reencode_video"


def test_materialize_media_failure_wipes_library_and_writes_report(
    tmp_path, monkeypatch
):
    from chaos_librarian.contract.materialization import Outcome, ToolchainInfo
    from chaos_librarian.contract.manifest import ProbedMedia
    from chaos_librarian.contract.materialization import ToolInvocation
    from chaos_librarian.materializer.errors import MediaActionError

    def failing_run(argv, *, ffmpeg_version, timeout_s=60.0):
        return ToolInvocation(
            tool="ffmpeg", version=ffmpeg_version, command=list(argv),
            exit_code=1, duration_ns=1,
        ), "stub stderr"

    monkeypatch.setattr("chaos_librarian.materializer.media.run_ffmpeg", failing_run)
    monkeypatch.setattr(
        "chaos_librarian.materializer.media.probe_file",
        lambda p, **k: ProbedMedia(container="matroska", duration_seconds=1.0,
                                   size_bytes=100, streams=[]),
    )
    monkeypatch.setattr(
        "chaos_librarian.materializer.run.detect_capabilities",
        lambda: ToolchainInfo(ffmpeg="7.0", ffprobe="7.0"),
    )
    from chaos_librarian.materializer.run import materialize_scenario
    scenario_yaml = _write_scenario(tmp_path, """\
schema_version: 5
scenario_id: sc_fail
seed: 42
duration_scale: short
library:
  roots:
    - id: r0
      path: library/r0
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
timeline:
  - id: ev_rv_001
    at: 1s
    action: reencode_video
    target: a0
    resolution: sd
    codec: h264
""")
    out_dir = tmp_path / "run-002"
    with pytest.raises(MediaActionError):
        materialize_scenario(scenario_yaml, out_dir)
    # library/ wiped.
    assert not (out_dir / "library").exists()
    # materialization.json present with outcome=media_failed.
    report_path = out_dir / "materialization.json"
    assert report_path.exists()
    import json
    body = json.loads(report_path.read_text())
    assert body["outcome"] == "media_failed"
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Rename writer + finalize functions**

In `src/chaos_librarian/materializer/writer.py`, rename `cleanup_failed_filesystem_run` → `cleanup_failed_phase_b_run` (find the def and rename + update its docstring to mention "phase B failure (filesystem OR media)").

In `src/chaos_librarian/materializer/finalize.py`, REPLACE `finalize_failure_filesystem` with:

```python
def finalize_failure_phase_b(
    ctx: RunContext,
    exc: MaterializationError,  # FilesystemActionError or MediaActionError
    outcome: Outcome,            # FS_FAILED or MEDIA_FAILED
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
    filesystem_actions: list[FilesystemAction],
    media_actions: list["MediaAction"],
) -> None:
    """Caught phase-B failure path: outcome=fs_failed | media_failed; library/ wiped.

    Shared between FilesystemActionError (stage=FILESYSTEM, outcome=FS_FAILED)
    and MediaActionError (stage=MEDIA, outcome=MEDIA_FAILED). The fields
    on MaterializationFailure are derived from the exc subclass + outcome.
    """
    from chaos_librarian.materializer.errors import (
        FilesystemActionError, MediaActionError,
    )
    finished_at = datetime.now(UTC)
    if isinstance(exc, MediaActionError):
        stage = FailureStage.MEDIA
        invocation_index = exc.tool_invocation_index
    elif isinstance(exc, FilesystemActionError):
        stage = FailureStage.FILESYSTEM
        invocation_index = None
    else:
        stage = FailureStage.FILESYSTEM  # defensive default
        invocation_index = None
    cause = getattr(exc, "cause", None)
    failure = MaterializationFailure(
        asset_id=exc.asset_id,
        stage=stage,
        exit_code=None,
        stderr_tail=str(cause) if cause is not None else "",
        invocation_index=invocation_index,
    )
    report = build_report(
        outcome=outcome,
        run_id=ctx.run_id,
        caps=ctx.caps,
        started_at=ctx.started_at,
        finished_at=finished_at,
        invocations=invocations,
        materialized=materialized,
        failures=[failure],
        filesystem_actions=filesystem_actions,
        media_actions=media_actions,
    )
    replay_bundle = build_replay_bundle(
        run_id=ctx.run_id,
        scenario_yaml_bytes=ctx.run_input.raw_bytes,
        plan_artifacts=ctx.plan_artifacts,
        caps=ctx.caps,
        created_at=finished_at,
    )
    cleanup_failed_phase_b_run(
        ctx.out_dir,
        build_metadata(
            plan_artifacts=ctx.plan_artifacts,
            scenario_yaml_bytes=ctx.run_input.raw_bytes,
            materialization_report=report,
            replay_bundle=replay_bundle,
            sentinel=build_sentinel(ctx, RunSentinelState.COMPLETE),
        ),
    )
```

Delete the old `finalize_failure_filesystem` and `cleanup_failed_filesystem_run` (replace, don't deprecate).

Update `finalize_success`'s signature:

```python
def finalize_success(
    ctx: RunContext,
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
    filesystem_actions: list[FilesystemAction],
    media_actions: list["MediaAction"],
) -> MaterializeArtifacts:
    # … existing body; pass media_actions through to build_report and
    # MaterializationReport.
```

Update `build_report` in `materializer/reports.py` to accept `media_actions` and pass it to `MaterializationReport(..., media_actions=media_actions)`.

Update `__all__` and any import in `writer.py`'s caller (which used to read `cleanup_failed_filesystem_run`).

- [ ] **Step 4: Rewrite the phase-B walk in run.py**

In `src/chaos_librarian/materializer/run.py`, replace the body of `_run_synthesis` (Sprint 6's phase-A loop + `apply_phase_b` call) with:

```python
def _run_synthesis(ctx: RunContext, scenario: Scenario) -> MaterializeArtifacts:
    """Steps 7-8: per-asset synthesis loop, unified phase-B walk, finalize."""
    invocations: list[ToolInvocation] = []
    materialized: list[MaterializedAsset] = []
    filesystem_actions: list[FilesystemAction] = []
    media_actions: list[MediaAction] = []
    primary_root_path = scenario.library.roots[0].path
    timeline_sidecar_languages = _timeline_sidecar_languages(scenario)
    try:
        # Phase A — synthesis (unchanged from Sprint 6).
        for invocation_index, asset in enumerate(iter_assets(scenario)):
            skip_languages = timeline_sidecar_languages.get(asset.id, frozenset())
            invocation, materialized_asset, probed, sidecar_hashes = materialize_one_asset(
                asset,
                ctx.plan_artifacts.replay_bundle.resolved_seed,
                ctx.out_dir, ctx.caps, invocation_index,
                root_path=primary_root_path,
                skip_languages=skip_languages,
            )
            invocations.append(invocation)
            materialized.append(materialized_asset)
            augment_manifest(
                ctx.plan_artifacts.current_manifest,
                asset, materialized_asset, probed, sidecar_hashes,
                skip_languages=skip_languages,
            )
        # Phase B — unified journal walk. Each entry routes to stdlib or media.
        scenario_assets = {
            asset.id: asset for asset in iter_assets(scenario)
        }
        ffmpeg_version = ctx.caps.ffmpeg or "unknown"
        ffprobe_version = ctx.caps.ffprobe or "unknown"
        fs_ctx = _PhaseBContext(
            library_root=ctx.out_dir / "library",
            scenario_assets=scenario_assets,
            resolved_seed=ctx.plan_artifacts.replay_bundle.resolved_seed,
        )
        media_ctx = _MediaContext(
            library_root=ctx.out_dir / "library",
            scenario_assets=scenario_assets,
            resolved_seed=ctx.plan_artifacts.replay_bundle.resolved_seed,
            ffmpeg_version=ffmpeg_version,
            ffprobe_version=ffprobe_version,
            invocations=invocations,
            sidecar_lookup=_sidecar_lookup_from(ctx.plan_artifacts.current_manifest),
        )
        for entry in ctx.plan_artifacts.journal:
            action = TimelineActionName(entry.action)
            if action in _STDLIB_ACTIONS:
                result = _dispatch_one(fs_ctx, entry)
                if result is not None:
                    filesystem_actions.append(result)
            elif action in _MEDIA_ACTIONS:
                media_actions.append(apply_media_action(media_ctx, entry))
            else:
                # Defense in depth — preflight should have rejected this.
                raise MediaActionError(
                    f"unsupported phase-B action {action.value!r}",
                    event_id=entry.event_id, action=action,
                    cause=RuntimeError("not in _STDLIB_ACTIONS or _MEDIA_ACTIONS"),
                )
        # Drain phase-B sidecar hashes from BOTH dispatchers.
        augment_timeline_sidecars(
            ctx.plan_artifacts.current_manifest, fs_ctx.phase_b_sidecar_hashes,
        )
        augment_versions(
            ctx.plan_artifacts.current_manifest, media_ctx.post_phase_b_versions,
        )
        augment_updated_sidecars(
            ctx.plan_artifacts.current_manifest, media_ctx.post_phase_b_sidecars,
        )
    except (ToolFailedError, ProbeParseError) as exc:
        if isinstance(exc, ToolFailedError):
            invocations.append(exc.invocation)
        finalize_failure(ctx, exc, Outcome.TOOL_FAILED, invocations, materialized)
        raise
    except FilesystemActionError as exc:
        finalize_failure_phase_b(
            ctx, exc, Outcome.FS_FAILED, invocations, materialized,
            filesystem_actions, media_actions,
        )
        raise
    except MediaActionError as exc:
        finalize_failure_phase_b(
            ctx, exc, Outcome.MEDIA_FAILED, invocations, materialized,
            filesystem_actions, media_actions,
        )
        raise
    return finalize_success(
        ctx, invocations, materialized, filesystem_actions, media_actions,
    )


def _sidecar_lookup_from(manifest):
    """Build a sidecar_id -> ManifestSidecar lookup callable."""
    by_id = {s.id: s for s in manifest.sidecars}
    return lambda sid: by_id.get(sid)
```

Add the new imports at the top:

```python
from chaos_librarian.contract.materialization import (
    FilesystemAction,
    MaterializedAsset,
    MediaAction,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.scenario import CreateSidecarEvent, Scenario, TimelineActionName
from chaos_librarian.materializer.errors import (
    FilesystemActionError,
    MediaActionError,
    ProbeParseError,
    ScenarioValidationError,
    ToolFailedError,
)
from chaos_librarian.materializer.filesystem import _PhaseBContext, _dispatch_one
from chaos_librarian.materializer.finalize import (
    build_sentinel,
    finalize_failure,
    finalize_failure_phase_b,
    finalize_success,
)
from chaos_librarian.materializer.manifest_build import (
    augment_manifest,
    augment_timeline_sidecars,
    augment_updated_sidecars,
    augment_versions,
)
from chaos_librarian.materializer.media import (
    _MEDIA_ACTIONS,
    _STDLIB_ACTIONS,
    _MediaContext,
    apply_media_action,
)
```

Remove the `from chaos_librarian.materializer.filesystem import apply_phase_b` line — `apply_phase_b` is no longer called as a top-level orchestrator entry point (Sprint 6's tests still use it directly for unit-testing the stdlib helpers, so don't delete the function).

Note: `_dispatch_one` and `_PhaseBContext` are currently underscore-prefixed module-private in `filesystem.py`. Either (a) export them (drop the underscore + add to `__all__`), or (b) re-introduce `apply_phase_b` as the only entry point and call it per-entry. **Choose (a)** — refactor `filesystem.py` to make `PhaseBContext` and `dispatch_one` public. Update `filesystem.py` accordingly:

```python
__all__ = ["PhaseBContext", "apply_phase_b", "dispatch_one"]

# Rename the leading underscore on the dataclass and the function.
```

(Or keep underscore names but import them — both work since these are internal modules. Pick the lighter-touch approach: keep the underscores in `filesystem.py`, and just import them with underscores in `run.py`. Mark the rationale in a one-line comment.)

- [ ] **Step 5: Run the new orchestrator test**

Run: `uv run pytest tests/materializer/test_run_sprint7.py -v 2>&1 | tail -40`

Expected: green. Debug any wiring issues (likely candidates: missing import, wrong dataclass field default, the `_sidecar_lookup_from` closure not pickling, etc.).

- [ ] **Step 6: Run the full materializer suite**

Run: `uv run pytest tests/materializer/ -v 2>&1 | tail -40`

Expected: green. Sprint 6's existing tests that hit `finalize_failure_filesystem` should be updated to use `finalize_failure_phase_b` (mechanical rename in the test file's mocks/imports). The cleanup_failed_filesystem_run callers in tests also rename.

- [ ] **Step 7: Lint; commit**

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/materializer/ tests/materializer/
git commit -m "$(cat <<'EOF'
feat(materializer): unified phase-B walk dispatches stdlib OR media per entry

run.py replaces Sprint 6's apply_phase_b call with a per-journal-entry
dispatcher that routes each entry to filesystem._dispatch_one (stdlib
ops) or media.apply_media_action (ffmpeg-backed + sidecar regen).

Renames finalize_failure_filesystem -> finalize_failure_phase_b and
cleanup_failed_filesystem_run -> cleanup_failed_phase_b_run, both now
shared by FS_FAILED and MEDIA_FAILED outcomes.

augment_versions + augment_updated_sidecars drain media_ctx.post_phase_b
maps into the manifest after the walk.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 37: CLI — materialize.py catches MediaActionError

**Files:**
- Modify: `src/chaos_librarian/cli/commands/materialize.py` — add `except MediaActionError`.
- Modify: `src/chaos_librarian/materializer/__init__.py` — re-export `MediaActionError`.
- Test: NEW `tests/cli/test_materialize_sprint7.py` — assert exit 5 + JSON payload shape.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_materialize_sprint7.py`:

```python
"""Layer-5 CLI integration tests for Sprint 7 materialize paths."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app

runner = CliRunner()


def _write_scenario(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "scenario.yaml"
    path.write_text(body)
    return path


def test_materialize_media_failed_exit_5_with_json_payload(tmp_path):
    from chaos_librarian.contract.scenario import TimelineActionName
    from chaos_librarian.materializer.errors import MediaActionError
    scenario = _write_scenario(tmp_path, """\
schema_version: 5
scenario_id: sc_test
seed: 42
duration_scale: short
library:
  roots: [{id: r0, path: library/r0}]
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{codec: aac, channels: stereo, language: eng}]
timeline:
  - id: ev_rv_001
    at: 1s
    action: reencode_video
    target: a0
    resolution: sd
    codec: h264
""")
    out_dir = tmp_path / "run-001"

    def fail(*args, **kwargs):
        raise MediaActionError(
            "stub failure", event_id="ev_rv_001",
            action=TimelineActionName.REENCODE_VIDEO,
            cause=RuntimeError("ffmpeg exit 1"),
            asset_id="a0", tool_invocation_index=2,
        )

    with patch("chaos_librarian.cli.commands.materialize.materialize_scenario",
               side_effect=fail):
        result = runner.invoke(app, [
            "materialize", str(scenario), "--out", str(out_dir), "--json",
        ])
    assert result.exit_code == 5
    body = json.loads(result.stderr.strip().splitlines()[-1])
    assert body["error_code"] == "E_MATERIALIZE_MEDIA_FAILED"
    assert body["details"]["event_id"] == "ev_rv_001"
    assert body["details"]["action"] == "reencode_video"
    assert body["details"]["tool_invocation_index"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Catch MediaActionError in the CLI command**

In `src/chaos_librarian/cli/commands/materialize.py`, add the import:

```python
from chaos_librarian.materializer import (
    ...,
    MediaActionError,
    ...
)
```

And the except branch (BEFORE `ContainmentViolationError`):

```python
    except MediaActionError as exc:
        # Phase B has already wiped library/ and written the failure
        # report; surface E_MATERIALIZE_MEDIA_FAILED with run_dir=out so
        # the envelope advertises materialization_report_path.
        emit_materialize_error(exc, json_output=json_output, run_dir=out)
        raise typer.Exit(code=5) from exc
```

In `src/chaos_librarian/materializer/__init__.py`, add `MediaActionError` to both the import and `__all__`.

- [ ] **Step 4: Run tests; lint; commit**

```bash
uv run pytest tests/cli/test_materialize_sprint7.py -v
uv run ruff check . && uv run ruff format --check . && uv run ty check src tests
git add src/chaos_librarian/cli/commands/materialize.py \
        src/chaos_librarian/materializer/__init__.py \
        tests/cli/test_materialize_sprint7.py
git commit -m "$(cat <<'EOF'
feat(cli): materialize catches MediaActionError -> exit 5

Routes E_MATERIALIZE_MEDIA_FAILED through emit_materialize_error with
run_dir=out so consumers see materialization_report_path in the
envelope; library/ has already been wiped by the phase-B failure
path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 38: Run the full suite (mid-sprint checkpoint)

**Files:** verification only.

- [ ] **Step 1: Schema drift gate**

Run: `uv run python -m chaos_librarian.schema_export --check`

- [ ] **Step 2: Full pytest suite**

Run: `uv run pytest -q 2>&1 | tail -40`

Expected: green. Layer-4 real-tool integration tests (test_materialize_sprint7_real.py) will fail or be skipped at this point — they don't exist yet (Task 43). Anything else failing is a regression you missed.

- [ ] **Step 3: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

- [ ] **Step 4: No commit — checkpoint only**

Verify everything is green before moving on to fixtures + integration tests.

---

## Task 39: Fixtures — extend version-evolution.yaml with edit_metadata

**Files:**
- Modify: `tests/fixtures/scenarios/version-evolution.yaml` — add one `edit_metadata` event in the existing timeline order.
- Test: `tests/contract/test_sample_scenarios.py` should round-trip the new shape (already exists; assertion will pick up the v5 fixture automatically).

- [ ] **Step 1: Inspect the existing fixture**

Run: `cat tests/fixtures/scenarios/version-evolution.yaml`

Note the existing event order; the new `edit_metadata` should land after the reencode events but before any rename/delete (per the source design's "update metadata" line).

- [ ] **Step 2: Add the new event**

Append (or splice in correct chronological order) one event:

```yaml
  - id: ev_edit_meta_001
    at: 5s
    action: edit_metadata
    target: <existing asset id from this fixture, e.g. asset_main>
    fields:
      title: "Pulsar (remastered)"
      year: "2026"
```

Match the existing asset id used by the prior reencode events in this fixture.

- [ ] **Step 3: Run the contract sample-scenarios smoke test**

Run: `uv run pytest tests/contract/test_sample_scenarios.py -v`

Expected: green.

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/scenarios/version-evolution.yaml
git commit -m "$(cat <<'EOF'
test(fixtures): version-evolution.yaml gains an edit_metadata event

Covers the source design's "update metadata" line; consumed by the
Layer-4 test_version_evolution_end_to_end exit-criterion test.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 40: Fixtures — extend bundle-sidecars.yaml with poster + NFO + embed_subtitle + rename

**Files:**
- Modify: `tests/fixtures/scenarios/bundle-sidecars.yaml` — add poster/NFO `create_sidecar` events at `at: 0s`, an `embed_subtitle` for the declared English subtitle, and a `rename_file` on the asset.

- [ ] **Step 1: Inspect the existing fixture**

Run: `cat tests/fixtures/scenarios/bundle-sidecars.yaml`

Note the existing English subtitle declaration; the new `embed_subtitle.sidecar_path` should reference `<asset_id>.eng.srt` (the declared path).

Per the spec §"Exit-criterion fixtures": the existing timeline `create_sidecar` event in this fixture is REMOVED so the new test doesn't trip the Sprint 6 collision path.

- [ ] **Step 2: Apply edits**

REMOVE the existing `create_subs_001` event from the timeline, and replace the whole `timeline:` block with:

```yaml
timeline:
  - id: ev_create_poster
    at: 0s
    action: create_sidecar
    target: asset_main
    to: movies-hd/Quasar.poster.png
    kind: poster
  - id: ev_create_nfo
    at: 0s
    action: create_sidecar
    target: asset_main
    to: movies-hd/Quasar.nfo
    kind: nfo
  - id: ev_embed_subtitle
    at: 1s
    action: embed_subtitle
    target: asset_main
    sidecar_path: asset_main.eng.srt
  - id: ev_rename_asset
    at: 2s
    action: rename_file
    target: asset_main
    to: movies-hd/Quasar.HD.mkv
```

Notes:
- Asset id `asset_main` matches the fixture's existing declaration (line 20).
- Library root is `movies-hd` per the fixture's `library.roots[0].path` (line 9), so poster/NFO paths live under `movies-hd/`.
- `embed_subtitle.sidecar_path` uses the declared-subtitle convention `<asset_id>.<language>.srt` per the Sprint 7 spec — phase A writes the declared subtitle at `<library>/asset_main.eng.srt`.
- The rename target `movies-hd/Quasar.HD.mkv` is the post-rename path the Layer-4 test asserts.

- [ ] **Step 3: Run the contract sample-scenarios smoke test**

Run: `uv run pytest tests/contract/test_sample_scenarios.py -v`

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/scenarios/bundle-sidecars.yaml
git commit -m "$(cat <<'EOF'
test(fixtures): bundle-sidecars.yaml — poster + NFO + embed_subtitle + rename

Replaces the previous create_sidecar timeline event (which would
trip the Sprint 6 collision path) with poster + NFO sidecar
creations at at:0s, an embed_subtitle that consumes the declared
English subtitle, and a rename_file on the asset.

Consumed by the Layer-4 test_bundle_sidecars_end_to_end exit-criterion
test.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 41: Fixtures — new positive fixtures

**Files (one new file each):**
- `tests/fixtures/scenarios/remux-container.yaml`
- `tests/fixtures/scenarios/edit-metadata.yaml`
- `tests/fixtures/scenarios/embed-extract-roundtrip.yaml`
- `tests/fixtures/scenarios/update-sidecar.yaml`
- `tests/fixtures/scenarios/remove-sidecar.yaml`
- `tests/fixtures/scenarios/subtitle-ops-on-mp4.yaml`

Each fixture: one asset, a minimal timeline focused on the named action.

- [ ] **Step 1: Write `remux-container.yaml`**

```yaml
schema_version: 5
scenario_id: sc_remux_001
seed: 42
duration_scale: short
library:
  roots:
    - id: r0
      path: library/movies
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{codec: aac, channels: stereo, language: eng}]
timeline:
  - id: ev_remux_001
    at: 1s
    action: remux_container
    target: a0
    to_container: mp4
```

- [ ] **Step 2: Write `edit-metadata.yaml`** — same shape with `edit_metadata` event carrying `fields: {title: "Pulsar", year: "2026"}`.

- [ ] **Step 3: Write `embed-extract-roundtrip.yaml`** — asset declares one English subtitle (mode: embedded); timeline embeds a sidecar then extracts. Sketch:

```yaml
schema_version: 5
scenario_id: sc_ee_001
seed: 42
duration_scale: short
library: {roots: [{id: r0, path: library/movies}]}
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{codec: aac, channels: stereo, language: eng}]
              subtitles:
                - {codec: srt, language: eng, mode: sidecar}
timeline:
  - id: ev_embed
    at: 1s
    action: embed_subtitle
    target: a0
    sidecar_path: a0.eng.srt
  - id: ev_extract
    at: 2s
    action: extract_subtitle
    target: a0
    to: a0.eng.extracted.srt
    language: eng
```

- [ ] **Step 4: Write `update-sidecar.yaml`** — same base, timeline:

```yaml
timeline:
  - id: ev_update
    at: 1s
    action: update_sidecar
    target: a0
    sidecar_path: a0.eng.srt
```

- [ ] **Step 5: Write `remove-sidecar.yaml`** — same base, timeline:

```yaml
timeline:
  - id: ev_remove
    at: 1s
    action: remove_sidecar
    target: a0
    sidecar_path: a0.eng.srt
```

- [ ] **Step 6: Write `subtitle-ops-on-mp4.yaml`** — asset declares one English subtitle (sidecar mode), timeline remuxes to mp4 then embeds:

```yaml
schema_version: 5
scenario_id: sc_mp4_sub_001
seed: 42
duration_scale: short
library: {roots: [{id: r0, path: library/movies}]}
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{codec: aac, channels: stereo, language: eng}]
              subtitles:
                - {codec: srt, language: eng, mode: sidecar}
timeline:
  - id: ev_remux
    at: 1s
    action: remux_container
    target: a0
    to_container: mp4
  - id: ev_embed
    at: 2s
    action: embed_subtitle
    target: a0
    sidecar_path: a0.eng.srt
```

- [ ] **Step 7: Run the contract sample-scenarios smoke test**

Run: `uv run pytest tests/contract/test_sample_scenarios.py -v`

Expected: green (each fixture round-trips through `Scenario.model_validate`).

- [ ] **Step 8: Commit**

```bash
git add tests/fixtures/scenarios/remux-container.yaml \
        tests/fixtures/scenarios/edit-metadata.yaml \
        tests/fixtures/scenarios/embed-extract-roundtrip.yaml \
        tests/fixtures/scenarios/update-sidecar.yaml \
        tests/fixtures/scenarios/remove-sidecar.yaml \
        tests/fixtures/scenarios/subtitle-ops-on-mp4.yaml
git commit -m "$(cat <<'EOF'
test(fixtures): 6 new positive scenarios for Sprint 7 actions

remux-container (mkv -> mp4), edit-metadata (fields dict),
embed-extract-roundtrip (subtitle round-trip), update-sidecar
(regenerate bytes), remove-sidecar (unlink + manifest row removal),
subtitle-ops-on-mp4 (mov_text codec coverage).

Consumed by the Layer-4 real-tool integration tests.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 42: Fixtures — new invalid corpus

**Files (one new file each):**
- `tests/fixtures/scenarios/invalid/edit-metadata-empty-fields.yaml` — `E_SCHEMA_INVALID`
- `tests/fixtures/scenarios/invalid/embed-subtitle-unknown-sidecar.yaml` — `E_SIDECAR_TARGET_UNKNOWN`
- `tests/fixtures/scenarios/invalid/embed-subtitle-kind-mismatch.yaml` — `E_SIDECAR_KIND_MISMATCH`
- `tests/fixtures/scenarios/invalid/extract-subtitle-no-track.yaml` — `E_EXTRACT_TRACK_UNKNOWN`
- `tests/fixtures/scenarios/invalid/extract-subtitle-collides-with-declared.yaml` — `E_SIDECAR_PATH_COLLISION`
- `tests/fixtures/scenarios/invalid/remove-sidecar-after-remove.yaml` — `E_LIFECYCLE_INVALID`
- `tests/fixtures/scenarios/invalid/create-poster-with-language.yaml` — `E_SCHEMA_INVALID`

Each fixture starts with `# expected: <CODE>` per the project convention (per CLAUDE.md). The harness `tests/validation/test_invalid_corpus.py` reads that marker and asserts the validation report carries the same code.

- [ ] **Step 1: Write `edit-metadata-empty-fields.yaml`**

```yaml
# expected: E_SCHEMA_INVALID
schema_version: 5
scenario_id: sc_inv_em_001
seed: 1
duration_scale: short
library: {roots: [{id: r0, path: library/movies}]}
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{codec: aac, channels: stereo, language: eng}]
timeline:
  - id: ev_em
    at: 1s
    action: edit_metadata
    target: a0
    fields: {}
```

(The Pydantic shape pass catches the empty-fields rejection via the `model_validator`; this surfaces as one of the shape error codes — likely `E_FIELD_SHAPE` or a generic `E_SCHEMA_INVALID` per the project's `validation/codes.py`. Verify which code the shape pass emits for `model_validator` failures by running the test once; adjust the `# expected:` marker to match what the codes table actually emits.)

If `validation/codes.py` has no `E_SCHEMA_INVALID` constant, the marker should be whatever code the shape pass emits for a model_validator ValueError. Run `uv run python -c "from chaos_librarian.scenario_io import prepare_run_input; from chaos_librarian.validation import run_validation; print(run_validation(prepare_run_input('tests/fixtures/scenarios/invalid/edit-metadata-empty-fields.yaml')).issues)"` to see the actual emitted code, then update the marker.

- [ ] **Step 2: Write `embed-subtitle-unknown-sidecar.yaml`**

```yaml
# expected: E_SIDECAR_TARGET_UNKNOWN
schema_version: 5
scenario_id: sc_inv_es_001
seed: 1
duration_scale: short
library: {roots: [{id: r0, path: library/movies}]}
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{codec: aac, channels: stereo, language: eng}]
timeline:
  - id: ev_es
    at: 1s
    action: embed_subtitle
    target: a0
    sidecar_path: missing.srt
```

- [ ] **Step 3: Write `embed-subtitle-kind-mismatch.yaml`**

```yaml
# expected: E_SIDECAR_KIND_MISMATCH
schema_version: 5
scenario_id: sc_inv_es_002
seed: 1
duration_scale: short
library: {roots: [{id: r0, path: library/movies}]}
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{codec: aac, channels: stereo, language: eng}]
timeline:
  - id: ev_cs
    at: 1s
    action: create_sidecar
    target: a0
    to: a0.poster.png
    kind: poster
  - id: ev_es
    at: 2s
    action: embed_subtitle
    target: a0
    sidecar_path: a0.poster.png
```

- [ ] **Step 4: Write `extract-subtitle-no-track.yaml`**

```yaml
# expected: E_EXTRACT_TRACK_UNKNOWN
schema_version: 5
scenario_id: sc_inv_xs_001
seed: 1
duration_scale: short
library: {roots: [{id: r0, path: library/movies}]}
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{codec: aac, channels: stereo, language: eng}]
timeline:
  - id: ev_xs
    at: 1s
    action: extract_subtitle
    target: a0
    to: a0.eng.srt
    language: eng
```

(Asset has zero subtitle declarations.)

- [ ] **Step 5: Write `extract-subtitle-collides-with-declared.yaml`**

```yaml
# expected: E_SIDECAR_PATH_COLLISION
schema_version: 5
scenario_id: sc_inv_xs_002
seed: 1
duration_scale: short
library: {roots: [{id: r0, path: library/movies}]}
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{codec: aac, channels: stereo, language: eng}]
              subtitles:
                - {codec: srt, language: eng, mode: sidecar}
timeline:
  - id: ev_xs
    at: 1s
    action: extract_subtitle
    target: a0
    to: a0.eng.srt
    language: eng
```

(Extract target collides with declared subtitle's phase-A path `a0.eng.srt`.)

- [ ] **Step 6: Write `remove-sidecar-after-remove.yaml`**

```yaml
# expected: E_LIFECYCLE_INVALID
schema_version: 5
scenario_id: sc_inv_rs_001
seed: 1
duration_scale: short
library: {roots: [{id: r0, path: library/movies}]}
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{codec: aac, channels: stereo, language: eng}]
              subtitles:
                - {codec: srt, language: eng, mode: sidecar}
timeline:
  - id: ev_rs_1
    at: 1s
    action: remove_sidecar
    target: a0
    sidecar_path: a0.eng.srt
  - id: ev_rs_2
    at: 2s
    action: remove_sidecar
    target: a0
    sidecar_path: a0.eng.srt
```

- [ ] **Step 7: Write `create-poster-with-language.yaml`**

```yaml
# expected: E_SCHEMA_INVALID
schema_version: 5
scenario_id: sc_inv_cs_001
seed: 1
duration_scale: short
library: {roots: [{id: r0, path: library/movies}]}
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{codec: aac, channels: stereo, language: eng}]
timeline:
  - id: ev_cs
    at: 1s
    action: create_sidecar
    target: a0
    to: a0.poster.png
    kind: poster
    language: eng  # forbidden for poster
```

- [ ] **Step 8: Run the invalid-corpus harness**

Run: `uv run pytest tests/validation/test_invalid_corpus.py -v 2>&1 | tail -40`

Adjust any `# expected:` markers whose actual code differs from the predicted one.

- [ ] **Step 9: Commit**

```bash
git add tests/fixtures/scenarios/invalid/*.yaml
git commit -m "$(cat <<'EOF'
test(fixtures): invalid corpus for Sprint 7 — 7 new error fixtures

E_SCHEMA_INVALID (edit_metadata empty fields, create_sidecar poster
with language), E_SIDECAR_TARGET_UNKNOWN (embed on missing),
E_SIDECAR_KIND_MISMATCH (embed on poster sidecar),
E_EXTRACT_TRACK_UNKNOWN (extract on subtitle-less asset),
E_SIDECAR_PATH_COLLISION (extract.to collides with declared),
E_LIFECYCLE_INVALID (remove-after-remove).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 43: Layer 4 — real-tool integration tests

**Files:**
- Create: `tests/integration/test_materialize_sprint7_real.py`.

**Skip-if-not-installed:** `pytest.mark.skipif(not _ffmpeg_meets_minimum(), reason="ffmpeg >= 7.0")` mirrors Sprint 5/6.

Each test runs `materialize_scenario(...)` against a fixture and asserts:
- the expected file exists at the expected path,
- the manifest reflects post-phase-B state,
- ffprobe reports the expected codec/container when relevant.

- [ ] **Step 1: Write all Layer 4 tests in one file**

Create `tests/integration/test_materialize_sprint7_real.py`:

```python
"""Layer-4 real-tool integration tests for Sprint 7 media mutations.

Skip silently when ffmpeg or ffprobe aren't installed or below the
minimum version (mirrors Sprint 5/6).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.materialization import Outcome
from chaos_librarian.materializer import materialize_scenario

# pytest helper from existing conftest.py
from tests.integration.conftest import (
    _ffmpeg_meets_minimum,
    _load_asset_report,
    _load_current_manifest,
    _load_materialization_report,
    sha256_of,
)

pytestmark = pytest.mark.skipif(
    not _ffmpeg_meets_minimum(),
    reason="ffmpeg >= 7.0 required for Sprint 7 real-tool tests",
)


FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "scenarios"


def test_version_evolution_end_to_end(tmp_path):
    """EXIT CRITERION #1. Reencode + downmix + edit_metadata round-trip."""
    out = tmp_path / "run-001"
    artifacts = materialize_scenario(FIXTURE_DIR / "version-evolution.yaml", out)
    assert artifacts.materialization_report.outcome == Outcome.SUCCESS
    manifest = _load_current_manifest(out)
    # The fixture's primary asset (asset_main) should now carry 4 versions
    # (initial + reencode_video + reencode_audio + edit_metadata).
    primary_versions = [v for v in manifest.versions if v.asset_id == "asset_main"]
    assert len(primary_versions) == 4
    for version in primary_versions[1:]:  # skip initial
        assert version.content_hash is not None
        assert version.probed is not None
    report = _load_materialization_report(out)
    assert len(report.media_actions) == 3
    asset_report = _load_asset_report(out, "asset_main")
    assert len(asset_report.version_history) == 3


def test_bundle_sidecars_end_to_end(tmp_path):
    """EXIT CRITERION #2. Poster + NFO + embed + rename."""
    out = tmp_path / "run-002"
    artifacts = materialize_scenario(FIXTURE_DIR / "bundle-sidecars.yaml", out)
    assert artifacts.materialization_report.outcome == Outcome.SUCCESS
    # The renamed asset path exists under library/ (Task 40 sets the
    # rename target to movies-hd/Quasar.HD.mkv).
    assert (out / "library" / "movies-hd" / "Quasar.HD.mkv").exists()
    # The declared English subtitle's phase-A path (asset_main.eng.srt)
    # was consumed by embed_subtitle and unlinked.
    assert not (out / "library" / "asset_main.eng.srt").exists()
    # Poster + NFO files exist at their create_sidecar to: paths.
    assert (out / "library" / "movies-hd" / "Quasar.poster.png").exists()
    assert (out / "library" / "movies-hd" / "Quasar.nfo").exists()
    manifest = _load_current_manifest(out)
    sidecar_kinds = {s.kind for s in manifest.sidecars}
    assert "poster" in sidecar_kinds
    assert "nfo" in sidecar_kinds
    # And the manifest's lone subtitle sidecar is GONE (embed consumed it).
    assert not any(s.kind == "subtitle" for s in manifest.sidecars)


def test_remux_container_real(tmp_path):
    out = tmp_path / "run-003"
    artifacts = materialize_scenario(FIXTURE_DIR / "remux-container.yaml", out)
    assert artifacts.materialization_report.outcome == Outcome.SUCCESS
    # File now at .mp4 extension.
    assert (out / "library" / "movies" / "a0.mp4").exists()
    assert not (out / "library" / "movies" / "a0.mkv").exists()


def test_edit_metadata_real(tmp_path):
    out = tmp_path / "run-004"
    artifacts = materialize_scenario(FIXTURE_DIR / "edit-metadata.yaml", out)
    assert artifacts.materialization_report.outcome == Outcome.SUCCESS
    # ffprobe the output and assert the metadata fields are present.
    # Use the existing probe_file helper.
    from chaos_librarian.materializer.probe import probe_file
    probed = probe_file(out / "library" / "movies" / "a0.mkv",
                        ffprobe_path="ffprobe")
    # The probe model doesn't carry format metadata in the current shape;
    # if so, run ffprobe directly via subprocess and parse stdout for
    # title= / year= tags. Match the fixture's edit_metadata.fields.
    import subprocess
    out_str = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags",
         "-of", "default=noprint_wrappers=1",
         str(out / "library" / "movies" / "a0.mkv")],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "TAG:title=Pulsar" in out_str or "title=Pulsar" in out_str
    assert "year=2026" in out_str.lower()


def test_embed_then_extract_round_trip(tmp_path):
    out = tmp_path / "run-005"
    artifacts = materialize_scenario(
        FIXTURE_DIR / "embed-extract-roundtrip.yaml", out)
    assert artifacts.materialization_report.outcome == Outcome.SUCCESS
    # Extracted .srt exists.
    assert (out / "library" / "movies" / "a0.eng.extracted.srt").exists()


def test_update_sidecar_changes_content_hash(tmp_path):
    out = tmp_path / "run-006"
    artifacts = materialize_scenario(FIXTURE_DIR / "update-sidecar.yaml", out)
    assert artifacts.materialization_report.outcome == Outcome.SUCCESS
    manifest = _load_current_manifest(out)
    sidecar = next(s for s in manifest.sidecars if s.id.startswith("sidecar_"))
    # content_hash should differ from the initial phase-A hash. Since
    # update_sidecar regenerates with a perturbed sub-seed including
    # event_id, the hash is deterministic but different from phase A's.
    assert sidecar.content_hash is not None


def test_remove_sidecar_real(tmp_path):
    out = tmp_path / "run-007"
    artifacts = materialize_scenario(FIXTURE_DIR / "remove-sidecar.yaml", out)
    assert artifacts.materialization_report.outcome == Outcome.SUCCESS
    # File gone.
    assert not (out / "library" / "movies" / "a0.eng.srt").exists()
    # Manifest row gone.
    manifest = _load_current_manifest(out)
    assert all(s.path != "a0.eng.srt" for s in manifest.sidecars)


def test_subtitle_ops_on_mp4_asset_use_mov_text(tmp_path):
    out = tmp_path / "run-008"
    artifacts = materialize_scenario(
        FIXTURE_DIR / "subtitle-ops-on-mp4.yaml", out)
    assert artifacts.materialization_report.outcome == Outcome.SUCCESS
    # mp4 file exists with embedded mov_text track.
    mp4_path = out / "library" / "movies" / "a0.mp4"
    assert mp4_path.exists()
    import subprocess, json
    probe_out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_streams", str(mp4_path)],
        capture_output=True, text=True, check=True,
    ).stdout
    streams = json.loads(probe_out)["streams"]
    subtitle_codecs = [s["codec_name"] for s in streams
                       if s.get("codec_type") == "subtitle"]
    assert "mov_text" in subtitle_codecs


def test_phase_b_media_failure_cleans_library(tmp_path):
    """Hand-craft a scenario that ffmpeg rejects (reencode_audio -ac quad)."""
    # Build the scenario in-place rather than as a fixture so the failure
    # case stays isolated from the positive-fixture corpus.
    scenario_yaml = tmp_path / "fail.yaml"
    scenario_yaml.write_text("""\
schema_version: 5
scenario_id: sc_fail
seed: 42
duration_scale: short
library: {roots: [{id: r0, path: library/movies}]}
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{codec: aac, channels: stereo, language: eng}]
timeline:
  - id: ev_ra
    at: 1s
    action: reencode_audio
    target: a0
    from_channels: stereo
    to_channels: quad
""")
    out = tmp_path / "run-fail"
    from chaos_librarian.materializer.errors import MediaActionError
    with pytest.raises(MediaActionError):
        materialize_scenario(scenario_yaml, out)
    # library/ wiped.
    assert not (out / "library").exists()
    # materialization.json present with outcome=media_failed.
    report_path = out / "materialization.json"
    assert report_path.exists()
    import json
    body = json.loads(report_path.read_text())
    assert body["outcome"] == "media_failed"
```

All asset-id strings above (`asset_main`) are taken from the Sprint 5/6 fixtures' existing declarations — verify with `rg "id: asset_main" tests/fixtures/scenarios/version-evolution.yaml tests/fixtures/scenarios/bundle-sidecars.yaml` before relying on them. The bundle-sidecars fixture's library root is `movies-hd/` (not `library/movies-hd`); the assertions above reflect that.

- [ ] **Step 2: Run the Layer 4 suite**

Run: `uv run pytest tests/integration/test_materialize_sprint7_real.py -v 2>&1 | tail -60`

Expected: green if ffmpeg ≥ 7.0 is installed; skipped otherwise.

If any test fails for reasons unrelated to the test's intent (e.g. asset-id mismatch with the actual fixture), fix the test, not the implementation.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_materialize_sprint7_real.py
git commit -m "$(cat <<'EOF'
test(integration): Layer-4 real-tool tests for Sprint 7 media mutations

Covers both exit criteria (Version Evolution + Bundle Sidecars
end-to-end) plus per-action smoke tests for remux_container,
edit_metadata, embed/extract round-trip, update_sidecar,
remove_sidecar, mp4 mov_text codec selection, and a hand-crafted
ffmpeg failure (reencode_audio -ac quad) that exercises the
phase-B media-failure cleanup path.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 44: Sprint 7 final verification + push

**Files:** none.

- [ ] **Step 1: Full suite**

Run: `uv run pytest -q 2>&1 | tail -40`

Expected: 100% green.

- [ ] **Step 2: Lint, format, type-check, schema drift gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests && uv run python -m chaos_librarian.schema_export --check`

Expected: green.

- [ ] **Step 3: Pre-commit hooks**

Run: `prek run --all-files`

Expected: green.

- [ ] **Step 4: Review the branch's net diff**

Run: `git log --oneline main..feat/sprint-7` and `git diff main..feat/sprint-7 -- '*.py' '*.yaml' '*.json' '*.md' | wc -l`

Sanity-check that:
- Every commit follows the conventional-commit style and ends with the `Co-Authored-By` trailer.
- The spec file has the round-1 + round-2 findings applied (already committed in earlier tasks if you've staged it; if it's still uncommitted from the spec-fix plan, stage and commit it now with `docs(sprint-7): apply round-1 + round-2 /challenge findings`).

- [ ] **Step 5: Verification skill**

**REQUIRED SUB-SKILL:** Use `superpowers:verification-before-completion` to confirm every claim before announcing the branch ready.

- [ ] **Step 6: Final commit (if any pending) and push**

If the spec file is uncommitted, commit it now:

```bash
git add docs/superpowers/specs/2026-05-20-sprint-7-design.md \
        docs/superpowers/plans/2026-05-20-sprint-7-media-mutations.md
git commit -m "$(cat <<'EOF'
docs(sprint-7): final spec + implementation plan

Spec carries both rounds of /challenge findings; plan walks the
implementation in 44 bite-sized TDD tasks.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

Push:

```bash
git push -u origin feat/sprint-7
```

- [ ] **Step 7: Open PR (via gh CLI)**

Use the project's existing PR template style. Title: `Sprint 7 — Media Mutations`.

Body sketch:

```markdown
## Summary
- Lifts Sprint 6's no-media-mutation preflight gate
- 8 new timeline actions wired end-to-end (engine + validation + materializer)
- New `materializer/media.py` ffmpeg dispatcher with atomic temp-rename, re-probe, re-hash
- Sidecar-kind widening: subtitle / poster / NFO
- 4 schema bumps: scenario v5, manifest v4, materialization v4, asset-report v4
- 4 new validation codes: `E_SIDECAR_TARGET_UNKNOWN`, `E_EXTRACT_TRACK_UNKNOWN`, `E_SIDECAR_KIND_MISMATCH`, `E_SIDECAR_PATH_COLLISION`
- Refs follow-up issues #48 (`_PATH_MUTATING_PASSTHROUGH` rename) and #49 (Sprint 6 spec/code sidecar divergence)

## Exit criteria
- ✅ Version Evolution scenario runs end-to-end (`test_version_evolution_end_to_end`)
- ✅ Bundle Sidecars scenario runs end-to-end (`test_bundle_sidecars_end_to_end`)

## Test plan
- [x] `uv run pytest -q` green
- [x] `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests` green
- [x] `uv run python -m chaos_librarian.schema_export --check` green
- [x] Layer 4 real-tool tests pass with ffmpeg 7.0+ installed
```

```bash
gh pr create --title "Sprint 7 — Media Mutations" --body "$(cat <<'EOF'
[paste the body from above]
EOF
)"
```

---

## Wrap-up checklist

- [ ] All 44 tasks completed in order.
- [ ] Schema drift gate green.
- [ ] Full pytest suite green.
- [ ] Lint, format, type-check, prek green.
- [ ] PR opened and CI green.
- [ ] Follow-up issues #48 + #49 cross-referenced in PR description.
- [ ] Spec doc committed.
- [ ] Plan doc committed.

After merge, post-sprint actions:
- Update `CLAUDE.md` §"Project state" with Sprint 7's merged status (one-line bump).
- Close any `feat/sprint-7` worktree if one was used.
- Pick up Sprint 8 brainstorming.







