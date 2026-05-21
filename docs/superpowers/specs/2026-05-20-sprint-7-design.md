# Sprint 7 — Media Mutations

**Status:** design, pending implementation plan.
**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md) — §"Sprint 7", §"Mutation Model", §"Materialize Mode", §"Schema Contract".
**Predecessor:** Sprint 6 (`feat/sprint-6`, merged on `main`) extended `chaos-librarian materialize` to apply filesystem mutations via a phase-B journal walk. Sprint 7 extends phase B to also execute media mutations (ffmpeg-driven byte changes) so the Version Evolution and Bundle Sidecars scenarios run end-to-end.
**Target branch:** `feat/sprint-7`.

## Goal

Lift Sprint 6's no-media-mutation preflight restriction. Sprint 7 extends phase B from "stdlib filesystem ops only" to a unified journal walk that dispatches each event to either a stdlib helper or an ffmpeg-based media helper. After Sprint 7, the materializer can execute every Version Evolution + Bundle Sidecars mutation end-to-end.

Sprint 7's materialize rejects any timeline action outside the supported set with `E_MATERIALIZE_TIMELINE_UNSUPPORTED` (exit 5). Future sprints lift the restriction for the deferred-mutation list below.

## Mid-Cut Scope

Eight new supported actions added to phase B beyond Sprint 6's filesystem set:

| Action | Status going in | Sprint 7 work |
|---|---|---|
| `reencode_video` | scenario + plan-only handler exist; materialize rejects | wire ffmpeg dispatch, new `version_id`, re-probe + re-hash |
| `reencode_audio` | same | same |
| `remux_container` | **new event** | new scenario variant, engine handler, ffmpeg dispatch |
| `edit_metadata` | **new event** | dict-of-strings payload, ffmpeg `-metadata` |
| `embed_subtitle` | **new event** | references existing sidecar by path; ffmpeg merges into container, sidecar row + file removed |
| `extract_subtitle` | **new event** | new sidecar allocated; ffmpeg `-map 0:s` to SRT |
| `remove_sidecar` | **new event** | stdlib unlink + manifest row removal |
| `update_sidecar` | **new event** | regenerate sidecar bytes + new content_hash on existing row |

Plus a sidecar-kind widening: `CreateSidecarEvent` gains a `kind: "subtitle" | "poster" | "nfo"` field (default `"subtitle"`), so Bundle Sidecars can exercise poster + NFO.

### Deferred (to follow-up sprints)

- `track_add` / `track_remove` / `track_reorder` — requires a track-targeting model; engine doesn't track per-track identity yet.
- `set_default_flag` / `set_forced_flag` — needs default/forced state on `ManifestTrack`.
- `set_commentary_label` — same blocker.
- `change_bitrate` — fits naturally as a future field on `ReencodeVideoEvent` / `ReencodeAudioEvent`; deferring avoids a re-bump of the scenario contract.
- `convert_subtitle` — covered functionally by `extract` + manual sidecar replace; defer.
- `rename_sidecar` / `move_sidecar` — Sprint 7's `RenameFileEvent.target` accepts asset_ids only; a sidecar-rename event would let scenarios exercise coordinated bundle-renames where every file in a bundle gets a new name. Deferred to a follow-up sprint so the Sprint 7 PR stays focused on byte-changing media mutations.
- `add_file` materialize — still deferred per Sprint 6.

### Exit-criterion fixtures

- `version-evolution.yaml` — exists with `reencode_video` + `reencode_audio`. Sprint 7 extends with one `edit_metadata` event so the source design's "update metadata" line is covered.
- `bundle-sidecars.yaml` — exists with `create_sidecar`. Sprint 7 extends with a poster sidecar (`kind: poster`), an NFO sidecar (`kind: nfo`), an `embed_subtitle` event that consumes the **declared** English subtitle, and a `rename_file` on the asset. The existing timeline `create_sidecar` event is **removed** in the extension so the fixture doesn't trigger Sprint 6's sidecar-collision path. `embed_subtitle.sidecar_path` is the declared sidecar's phase-A path (see "Declared-sidecar path convention" added below). Sidecars stay at their original paths — the existing `RenameFileEvent.target` accepts an asset_id only, and the mid-cut does not introduce a sidecar-rename event (see "Deferred" above and "Alternatives Rejected"). The resulting test exercises the "asset renames, sidecars stay" reconciliation case; coordinated bundle-rename is deferred to a follow-up sprint.

## Design Decisions Resolved In Brainstorming

The source design lists thirteen mutations under Sprint 7 deliverables. Each open question is resolved below; push back if you disagree before the plan is written.

1. **Mutation scope.** Mid-cut (above) — 8 new actions plus sidecar-kind extension. Other source-listed mutations are deferred for the reasons in "Deferred" above.

2. **Execution model.** Unified phase-B dispatcher. Single journal walk after phase A; each event dispatches to either the stdlib helper (Sprint 6's `materializer/filesystem.py`) or a new ffmpeg-based media helper (`materializer/media.py`), based on action kind. Pros: real-timeline ordering preserved (move → reencode → move works correctly); state-delta-driven; one phase to reason about. Alternative phase-C model rejected because media mutations would operate on post-phase-B paths instead of journal-time paths. Phase-B media handlers read every path they touch from `entry.state_delta` (input_path / output_path / sidecar_path) — they never consult `WorldState` or the plan-only manifest at execution time. This extends Sprint 6's "journal is the truth source" rule to media events.

3. **Audit shape.** Parallel arrays. `MaterializationReport` keeps Sprint 6's `filesystem_actions: list[FilesystemAction]` unchanged and adds `media_actions: list[MediaAction]`. Mirrors Sprint 5's `invocations: list[ToolInvocation]` arrangement. A unified discriminated union would have broken Sprint 6's wire format.

4. **`EditMetadataEvent` shape.** Dict-of-strings (`fields: dict[str, str]`). Materializer maps each key to `ffmpeg -metadata <key>=<value>`. Covers Version Evolution's metadata-update line without committing the contract to a fixed metadata vocabulary. Empty dict rejected at scenario validation.

5. **Sidecar kind extension.** `CreateSidecarEvent.kind: SidecarKind = SUBTITLE`. Subtitle requires `language`; poster/NFO forbids `language`. Enforced by a model-level `@model_validator(mode="after")` on the event raising `E_SCHEMA_INVALID`. Manifest's `ManifestSidecar.language` widens from `str` to `str | None` (manifest schema bump 3 → 4).

6. **Poster/NFO declaration.** Runtime `create_sidecar` events only; no new declared-on-asset shape (`Asset.posters` / `Asset.nfo`). The Bundle Sidecars fixture extension uses `create_sidecar` at `at: 0s` for poster + NFO. Keeps the contract minimal; declared-poster support can land in a follow-up sprint if `at: 0s` proves awkward.

7. **`update_sidecar` payload.** No new payload in the scenario. The materializer regenerates the sidecar's bytes from its recorded `(kind, language, seed-stream)` with a perturbed sub-seed (`Hash(seed_stream="sidecar_update", sidecar_id, event_id)`). Including `event_id` ensures consecutive updates on the same sidecar produce distinct bytes — each update is observably distinct in the manifest's `content_hash` field, which is the test surface. Scenarios stay declarative about *what* changed without prescribing *how*.

8. **`extract_subtitle` language fallback.** If no embedded subtitle track matches the scenario's `language`, the handler falls back to track 0. The new `E_EXTRACT_TRACK_UNKNOWN` rule guarantees at least one subtitle track exists at validation time. Alternative: hard-fail at materialize on mismatch — rejected because the scenario contract has no way to express track index.

9. **`extract_subtitle` does not allocate a new version.** The asset's bytes are unchanged — extraction is a read. Only a new sidecar appears. Asymmetric with `embed_subtitle` (which does allocate); the asymmetry is correct.

10. **`update_sidecar` does no state mutation in the engine.** The engine emits a journal entry but the actual content_hash change happens in phase B and lands via `augment_updated_sidecars` (sidecar analog to `augment_versions`). Plan-only mode therefore has no way to mark the sidecar as "updated"; that's accepted because plan-only is bytes-blind.

11. **Atomic write for media handlers.** Even when input == output, each media handler writes to a sibling temp file (`<output>.tmp.<resolved_seed>`) then `Path.replace`s into place. Protects against partial-write corruption on ffmpeg crash mid-operation. One extra file per media event during execution.

12. **mkvmerge remains optional.** Every Sprint 7 mutation is achievable with ffmpeg + ffprobe alone. Resolves the source design's Sprint-7 open question: "Whether MKVToolNix is required for any V1 mutation or remains optional" — optional.

13. **Re-probe + re-hash.** After every successful media handler, the dispatcher re-hashes the output file and re-runs ffprobe. `manifest_build.augment_versions(manifest, post_phase_b_versions)` stamps `content_hash` + `probed` onto every phase-B-allocated `ManifestVersion`; `augment_updated_sidecars(manifest, post_phase_b_sidecars)` stamps the analog onto `ManifestSidecar` rows touched by `update_sidecar` / `extract_subtitle`. Mirrors Sprint 6's `augment_timeline_sidecars`.

14. **Failure semantics.** New `MediaActionError(MaterializationError)` with `E_MATERIALIZE_MEDIA_FAILED` (exit 5). New `Outcome.MEDIA_FAILED` and `FailureStage.MEDIA`. On phase-B media failure: wipe `library/`, write `materialization.json` with `outcome=media_failed`, exit 5. Sprint 6's `cleanup_failed_filesystem_run` is renamed `cleanup_failed_phase_b_run` to reflect the broader scope.

## Architecture

Single PR on `feat/sprint-7`. The engine stays pure (no `Path` I/O). Sprint 6's `materializer/filesystem.py` keeps its stdlib helpers; a new `materializer/media.py` owns ffmpeg-based phase-B helpers. The phase-B orchestrator in `run.py` walks the journal once and dispatches per event.

### New modules

```
src/chaos_librarian/materializer/
  media.py                # apply_media_action(ctx, entry) -> MediaAction.
                          # One handler per "media-path" action (the set in
                          # _MEDIA_ACTIONS below). Reads source path from
                          # entry.state_delta; writes to a sibling temp path;
                          # atomically renames into place; re-probes;
                          # re-hashes; emits MediaAction. Raises
                          # MediaActionError on failure. Most handlers shell
                          # out to ffmpeg; update_sidecar is the exception
                          # (delegates to sidecar_bytes.regenerate_sidecar
                          # for byte regeneration but still routes through
                          # media.py for the temp/rename/hash machinery and
                          # the MediaAction audit record).
                          # Also exposes _subtitle_codec_for_container(
                          # container_ext: str) -> str — single source of
                          # truth for subtitle codec selection (`srt` for
                          # mkv/webm, `mov_text` for mp4/m4v/mov). Raises
                          # MediaActionError (E_MATERIALIZE_MEDIA_FAILED)
                          # for unsupported containers. Called by the
                          # embed_subtitle / extract_subtitle handlers when
                          # building the ffmpeg -c:s argument.
  sidecar_bytes.py        # Pure byte generators for non-subtitle sidecars:
                          # render_poster (PNG via ffmpeg lavfi color/palette
                          # source piped to a one-shot), render_nfo (XML
                          # string template). Also exposes regenerate_sidecar
                          # (kind, language, sidecar_id, resolved_seed) -> bytes
                          # which media.py's update_sidecar handler calls.
                          # Subtitle SRT generation stays in recipes.py and
                          # is invoked from sidecar_bytes.regenerate_sidecar
                          # for kind=subtitle.

src/chaos_librarian/engine/
  version_history.py      # derive_version_history(asset_id, journal) ->
                          # list[VersionHistoryEntry]. Pure function. Mirrors
                          # Sprint 6's engine/path_history.py.
```

### Modified modules

```
src/chaos_librarian/contract/
  __init__.py             # bumps:
                          #   SCENARIO_SCHEMA_VERSION         4 -> 5
                          #   MANIFEST_SCHEMA_VERSION         3 -> 4
                          #   MATERIALIZATION_SCHEMA_VERSION  3 -> 4
                          #   ASSET_REPORT_SCHEMA_VERSION     3 -> 4
                          # (all other versions unchanged)
  scenario.py             # + RemuxContainerEvent, EditMetadataEvent,
                          # EmbedSubtitleEvent, ExtractSubtitleEvent,
                          # RemoveSidecarEvent, UpdateSidecarEvent;
                          # + CreateSidecarEvent.kind: SidecarKind (default SUBTITLE);
                          # + CreateSidecarEvent.language widens to str | None;
                          # + model_validator on CreateSidecarEvent for the
                          #   subtitle-requires-language / poster-NFO-forbid-language rule;
                          # + SidecarKind StrEnum (SUBTITLE / POSTER / NFO);
                          # Scenario.schema_version Literal[5]
  manifest.py             # ManifestSidecar.language: str | None  (was: str)
                          # Manifest.schema_version Literal[4]
  materialization.py      # + MediaAction model;
                          # + Outcome.MEDIA_FAILED; + FailureStage.MEDIA;
                          # + MaterializationReport.media_actions;
                          # MaterializationReport.schema_version Literal[4]
  reports.py              # + VersionHistoryEntry model;
                          # + AssetReport.version_history;
                          # AssetReport.schema_version Literal[4]

src/chaos_librarian/engine/
  events.py               # + _handle_remux_container, _handle_edit_metadata,
                          # _handle_embed_subtitle, _handle_extract_subtitle,
                          # _handle_remove_sidecar, _handle_update_sidecar;
                          # + _HANDLERS entries;
                          # + _STATE_DELTA_KEYS entries (6 actions)
  state.py                # + WorldState.sidecar_id_for_path(asset_id, path)
  reports.py              # AssetReport builder calls derive_version_history per asset

src/chaos_librarian/materializer/
  run.py                  # phase B becomes a single journal walk that
                          # dispatches each entry to stdlib OR media helper;
                          # returns both action lists plus post_phase_b_versions
                          # and post_phase_b_sidecars maps for the augment_* calls
  preflight.py            # + SUPPORTED_S7_ACTIONS frozenset adds the 8 new
                          # actions to Sprint 6's set; rejects add_file with
                          # the existing E_MATERIALIZE_TIMELINE_UNSUPPORTED code
  filesystem.py           # + _remove_sidecar helper (stdlib unlink + audit row);
                          # remove_sidecar dispatches here, not to media.py
  finalize.py             # threads media_actions through MaterializationReport
                          # build_report call
  errors.py               # + MediaActionError(MaterializationError);
                          # + error code E_MATERIALIZE_MEDIA_FAILED
  manifest_build.py       # + augment_versions(manifest, post_phase_b_versions)
                          # + augment_updated_sidecars(manifest, post_phase_b_sidecars)
                          # Sprint 6's augment_timeline_sidecars and Sprint 5's
                          # augment_manifest both unchanged

src/chaos_librarian/validation/
  rules/timeline_lifecycle.py  # extend simulator with 6 new actions:
                               # all 6 require placed target; REMUX_CONTAINER
                               # (path-changing), EDIT_METADATA and
                               # EMBED_SUBTITLE (in-place byte mutators), and
                               # EXTRACT_SUBTITLE (reads the asset) all join
                               # _PATH_MUTATING_PASSTHROUGH so they're rejected
                               # against an asset with pending slow_copy.
                               # UPDATE_SIDECAR and REMOVE_SIDECAR are
                               # excluded — they don't touch the asset.
                               # + state.sidecars_by_path projection updated by
                               # create_sidecar / remove_sidecar / embed_subtitle
                               # / extract_subtitle
  rules/path_containment.py    # extend to extract_subtitle.to (new sidecar
                               # path) — every other new event references an
                               # existing path already covered
  rules/sidecar_target.py      # NEW: remove/update/embed events reference an
                               # existing (asset_id, path) sidecar; emit
                               # E_SIDECAR_TARGET_UNKNOWN
  rules/extract_track_unknown.py # NEW: extract_subtitle on an asset with no
                               # declared subtitle track emits
                               # E_EXTRACT_TRACK_UNKNOWN
  codes.py                     # + E_SIDECAR_TARGET_UNKNOWN
                               # + E_EXTRACT_TRACK_UNKNOWN
                               # + E_SIDECAR_KIND_MISMATCH
                               # + E_SIDECAR_PATH_COLLISION

src/chaos_librarian/schema_export.py
                               # regenerate scenario.schema.json (v5),
                               # manifest.schema.json (v4),
                               # materialization.schema.json (v4),
                               # asset-report.schema.json (v4); other schemas
                               # untouched
```

### Generated artifacts

```
schemas/
  scenario.schema.json         # REGEN: v5 with 6 new events + SidecarKind enum
  manifest.schema.json         # REGEN: v4 with sidecar.language optional
  materialization.schema.json  # REGEN: v4 with MediaAction, MEDIA_FAILED, MEDIA
  asset-report.schema.json     # REGEN: v4 with version_history
  # All others unchanged
```

`schema_export.py --check` runs in CI and fails on drift. Engineers regenerate locally with `--write` and commit the updated artifacts in the same change.

### Composition: how a media-bearing materialize run flows

```
chaos-librarian materialize scenario.yaml --out fixtures/run-001
  cli/app.py:materialize
    detect_capabilities()                        # exit 4 on failure
    validate_scenario(scenario)                  # exit 3 on validation failure
    materializer.materialize_scenario(...)
      step 1: preflight_timeline(scenario,
              SUPPORTED_S7_ACTIONS)              # E_MATERIALIZE_TIMELINE_UNSUPPORTED, exit 5
      step 2: containment gate                   # exit 7
      step 3: re-run detect_capabilities         # exit 4 on regression
      step 4: engine.run_plan(scenario)
              -> manifests, FULL journal, plan-only replay shape
      step 5: pre-flight matrix check            # exit 5
      step 6: begin_materialize_run              # sentinel state='in_progress'
      step 7: phase A — synthesis loop           # Sprint 5/6 logic, unchanged
                                                 # (writes initial bytes for
                                                 # every declared asset and
                                                 # declared sidecar)
      step 8: phase B — unified journal walk     # EXTENDED IN SPRINT 7
                for entry in journal:
                  if entry.action in _STDLIB_ACTIONS:
                    fs_actions.append(_dispatch_stdlib(ctx_fs, entry))
                  elif entry.action in _MEDIA_ACTIONS:
                    media_actions.append(_dispatch_media(ctx_media, entry))
                  else:
                    raise UnsupportedActionError  # defense in depth
                # E_MATERIALIZE_FS_FAILED on first stdlib OSError
                # E_MATERIALIZE_MEDIA_FAILED on first ffmpeg/probe failure
      step 9: augment_versions(manifest, ctx_media.post_phase_b_versions)
              augment_updated_sidecars(manifest, ctx_media.post_phase_b_sidecars)
              # stamp content_hash + probed on phase-B-touched rows
      step 10: atomic metadata write             # outcome=success
      step 11: return MaterializeArtifacts
    cli writes --json payload to stdout, exits 0
```

Failure at any step in phase B: stop the walk, record the failure (`MaterializationFailure(asset_id=..., stage=MEDIA|FILESYSTEM, exit_code=ffmpeg_exit_code_or_None, stderr_tail=..., invocation_index=tool_invocation_index_or_None)`), `cleanup_failed_phase_b_run(out_dir)`, write metadata atomically with `outcome=media_failed | fs_failed`, exit 5.

## Scenario Contract Changes

`SCENARIO_SCHEMA_VERSION` bumps 4 → 5. Six additive event variants plus one additive field on `CreateSidecarEvent`. Existing fixtures bump their `schema_version: 4` line to `5` — purely a header change.

### `SidecarKind` enum

```python
class SidecarKind(enum.StrEnum):
    SUBTITLE = "subtitle"
    POSTER = "poster"
    NFO = "nfo"
```

### Declared-sidecar path convention

Declared subtitle sidecars (`asset.subtitles[]` entries with `mode: sidecar`)
are written by phase A at the library-relative path
`<asset_id>.<language>.srt`. This convention is established in Sprint 5's
`materializer/synthesis.py` and used by `manifest_build.py`'s
`augment_manifest`. Scenario authors writing `embed_subtitle.sidecar_path`,
`remove_sidecar.sidecar_path`, or `update_sidecar.sidecar_path` that
reference a declared subtitle MUST use this exact path. Sidecars created
at runtime by `create_sidecar` use the event's literal `to:` path
instead.

### `CreateSidecarEvent` widens

```python
class CreateSidecarEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.CREATE_SIDECAR] = TimelineActionName.CREATE_SIDECAR
    target: str
    to: str
    language: str | None = None        # was: str; now optional
    kind: SidecarKind = SidecarKind.SUBTITLE   # NEW

    @model_validator(mode="after")
    def _check_language_matches_kind(self) -> "CreateSidecarEvent":
        if self.kind == SidecarKind.SUBTITLE and self.language is None:
            raise ValueError("subtitle sidecar requires language")
        if self.kind != SidecarKind.SUBTITLE and self.language is not None:
            raise ValueError(f"{self.kind.value} sidecar forbids language")
        return self
```

### Six new event variants

```python
class RemuxContainerEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.REMUX_CONTAINER] = TimelineActionName.REMUX_CONTAINER
    target: str
    to_container: str   # "mp4" / "mkv" / "webm". Engine renames the location's
                        # path extension; materializer runs ffmpeg -c copy.


class EditMetadataEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.EDIT_METADATA] = TimelineActionName.EDIT_METADATA
    target: str
    fields: dict[str, str]   # opaque key=value pairs; materializer maps each
                             # to ffmpeg -metadata. Empty dict rejected at
                             # validation (E_SCHEMA_INVALID).


class EmbedSubtitleEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.EMBED_SUBTITLE] = TimelineActionName.EMBED_SUBTITLE
    target: str            # asset to embed into
    sidecar_path: str      # path of the existing sidecar to absorb.
                           # For a DECLARED subtitle, use
                           # "<asset_id>.<language>.srt" (see "Declared-sidecar
                           # path convention" above). For a sidecar created
                           # by create_sidecar, use that event's "to:" path.
                           # After successful embed: sidecar row removed from
                           # manifest, sidecar file removed from disk.


class ExtractSubtitleEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.EXTRACT_SUBTITLE] = TimelineActionName.EXTRACT_SUBTITLE
    target: str            # asset to extract from
    to: str                # destination sidecar path (must resolve under library/)
    language: str          # language tag for the new sidecar row
    # Embedded-track selection: extracts the first subtitle track of the
    # asset whose language matches. If no language match, falls back to the
    # first subtitle track. Validator rejects if asset has no subtitle track
    # via E_EXTRACT_TRACK_UNKNOWN.


class RemoveSidecarEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.REMOVE_SIDECAR] = TimelineActionName.REMOVE_SIDECAR
    target: str            # asset_id (sidecars belong to assets)
    sidecar_path: str      # which sidecar to remove (lookup by asset_id + path).
                           # For a DECLARED subtitle, use
                           # "<asset_id>.<language>.srt"; for a create_sidecar-
                           # created sidecar, use that event's "to:" path.


class UpdateSidecarEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.UPDATE_SIDECAR] = TimelineActionName.UPDATE_SIDECAR
    target: str
    sidecar_path: str      # For a DECLARED subtitle, use
                           # "<asset_id>.<language>.srt"; for a create_sidecar-
                           # created sidecar, use that event's "to:" path.
    # The new bytes are regenerated from the sidecar's recorded
    # (kind, language, seed-stream) — no new payload in the scenario. The
    # content_hash on ManifestSidecar updates; sidecar_id is preserved.
```

### `TimelineActionName` extensions

```python
class TimelineActionName(enum.StrEnum):
    # ... existing 11 ...
    REMUX_CONTAINER  = "remux_container"
    EDIT_METADATA    = "edit_metadata"
    EMBED_SUBTITLE   = "embed_subtitle"
    EXTRACT_SUBTITLE = "extract_subtitle"
    REMOVE_SIDECAR   = "remove_sidecar"
    UPDATE_SIDECAR   = "update_sidecar"
```

`ALL_TIMELINE_ACTIONS` derives from the enum and picks up the new values automatically.

### Discriminated union extension

```python
TimelineEvent = Annotated[
    MoveAssetEvent | RenameFileEvent | DeleteFileEvent | AddFileEvent
    | ReencodeVideoEvent | ReencodeAudioEvent | CreateSidecarEvent
    | SlowCopyStartEvent | SlowCopyCommitEvent
    | ArchiveFileEvent | MoveBetweenRootsEvent
    | RemuxContainerEvent | EditMetadataEvent
    | EmbedSubtitleEvent | ExtractSubtitleEvent
    | RemoveSidecarEvent | UpdateSidecarEvent,
    Field(discriminator="action"),
]
```

## Engine Changes

### New handlers

> Sprint 7 also modifies the existing Sprint-5 `_handle_reencode_video` and
> `_handle_reencode_audio` handlers to populate `input_path` and `output_path`
> in `state_delta` (both equal to the asset's current `state.locations[loc_id].path`,
> since these are in-place re-encodes). The phase-B media dispatcher reads
> every path from the journal entry's `state_delta`, never from `WorldState`
> or the plan-only manifest — see design decision #2.

```python
def _handle_remux_container(state, resolved, ids, run_id, scenario_id):
    """Allocate a new version; rewrite location.path's extension."""
    event = resolved.event
    assert isinstance(event, RemuxContainerEvent)
    prior_version_id = state.version_id_for_asset(event.target)
    new_version_id = ids.next_version_id()
    state.bind_version(event.target, ManifestVersion(
        id=new_version_id, asset_id=event.target,
        index=state.versions[prior_version_id].index + 1,
    ))
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    prev_container = Path(previous.path).suffix.lstrip(".")
    new_path = _swap_extension(previous.path, event.to_container)
    state.locations[loc_id] = previous.model_copy(update={"path": new_path})
    entry = _new_atomic_entry(
        ...,
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
            "input_path": previous.path,    # for phase B (Finding #1)
            "output_path": new_path,        # for phase B
        },
    )
    return (entry,)


def _handle_edit_metadata(state, resolved, ids, run_id, scenario_id):
    """Allocate a new version; record the fields delta."""
    event = resolved.event
    assert isinstance(event, EditMetadataEvent)
    prior_version_id = state.version_id_for_asset(event.target)
    new_version_id = ids.next_version_id()
    state.bind_version(event.target, ManifestVersion(
        id=new_version_id, asset_id=event.target,
        index=state.versions[prior_version_id].index + 1,
    ))
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    entry = _new_atomic_entry(
        ...,
        action=TimelineActionName.EDIT_METADATA,
        target_ids=[event.target],
        location_ids=[loc_id],
        input_version_ids=[prior_version_id],
        output_version_ids=[new_version_id],
        state_delta={
            "fields": dict(event.fields),
            "input_path": previous.path,     # in-place edit
            "output_path": previous.path,
        },
    )
    return (entry,)


def _handle_embed_subtitle(state, resolved, ids, run_id, scenario_id):
    """Allocate new version; remove the named sidecar from state."""
    event = resolved.event
    assert isinstance(event, EmbedSubtitleEvent)
    sidecar_id = state.sidecar_id_for_path(event.target, event.sidecar_path)
    sidecar = state.sidecars[sidecar_id]
    prior_version_id = state.version_id_for_asset(event.target)
    new_version_id = ids.next_version_id()
    state.bind_version(event.target, ManifestVersion(...))
    del state.sidecars[sidecar_id]
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    entry = _new_atomic_entry(
        ...,
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
            "input_path": previous.path,     # in-place embed into asset
            "output_path": previous.path,
        },
    )
    return (entry,)


def _handle_extract_subtitle(state, resolved, ids, run_id, scenario_id):
    """Allocate new sidecar; asset's version is UNCHANGED (read-only extract)."""
    event = resolved.event
    assert isinstance(event, ExtractSubtitleEvent)
    sidecar_id = ids.next_sidecar_id()
    state.sidecars[sidecar_id] = ManifestSidecar(
        id=sidecar_id, asset_id=event.target,
        kind="subtitle", path=event.to, language=event.language,
    )
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    entry = _new_atomic_entry(
        ...,
        action=TimelineActionName.EXTRACT_SUBTITLE,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={
            "sidecar_id": sidecar_id,
            "sidecar_path": event.to,
            "language": event.language,
            "input_path": previous.path,     # asset read; output is sidecar_path
        },
    )
    return (entry,)


def _handle_remove_sidecar(state, resolved, ids, run_id, scenario_id):
    """Remove the named sidecar from state."""
    event = resolved.event
    assert isinstance(event, RemoveSidecarEvent)
    sidecar_id = state.sidecar_id_for_path(event.target, event.sidecar_path)
    sidecar = state.sidecars[sidecar_id]
    del state.sidecars[sidecar_id]
    entry = _new_atomic_entry(
        ...,
        action=TimelineActionName.REMOVE_SIDECAR,
        target_ids=[event.target],
        location_ids=[state.location_id_for_asset(event.target)],
        state_delta={
            "removed_sidecar_id": sidecar_id,
            "removed_sidecar_path": sidecar.path,
        },
    )
    return (entry,)


def _handle_update_sidecar(state, resolved, ids, run_id, scenario_id):
    """No state mutation in the engine; content_hash is filled in phase B."""
    event = resolved.event
    assert isinstance(event, UpdateSidecarEvent)
    sidecar_id = state.sidecar_id_for_path(event.target, event.sidecar_path)
    entry = _new_atomic_entry(
        ...,
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

### `_STATE_DELTA_KEYS` extensions

Sprint 6's lock table grows with one row per new action, and Sprint 7 also
EXTENDS the existing `REENCODE_VIDEO` and `REENCODE_AUDIO` entries (set up
in Sprint 5) to include `input_path` and `output_path` so the phase-B
media dispatcher can read every path from the journal entry rather than
reconstructing it from `WorldState` (Finding #1):

```python
# Extended in Sprint 7 (Sprint 5's entries gain input_path / output_path):
_STATE_DELTA_KEYS[TimelineActionName.REENCODE_VIDEO]   = frozenset(
    {"resolution", "codec", "input_path", "output_path"}
)
_STATE_DELTA_KEYS[TimelineActionName.REENCODE_AUDIO]   = frozenset(
    {"from_channels", "to_channels", "input_path", "output_path"}
)

# New in Sprint 7:
_STATE_DELTA_KEYS[TimelineActionName.REMUX_CONTAINER]  = frozenset(
    {"from_container", "to_container", "from_path", "to_path",
     "input_path", "output_path"}
)
_STATE_DELTA_KEYS[TimelineActionName.EDIT_METADATA]    = frozenset(
    {"fields", "input_path", "output_path"}
)
_STATE_DELTA_KEYS[TimelineActionName.EMBED_SUBTITLE]   = frozenset(
    {"embedded_sidecar_id", "embedded_sidecar_path",
     "language", "kind", "input_path", "output_path"}
)
_STATE_DELTA_KEYS[TimelineActionName.EXTRACT_SUBTITLE] = frozenset(
    {"sidecar_id", "sidecar_path", "language", "input_path"}
)
_STATE_DELTA_KEYS[TimelineActionName.REMOVE_SIDECAR]   = frozenset(
    {"removed_sidecar_id", "removed_sidecar_path"}
)
_STATE_DELTA_KEYS[TimelineActionName.UPDATE_SIDECAR]   = frozenset(
    {"sidecar_id", "sidecar_path"}
)
```

`extract_subtitle` needs only `input_path` (the asset it reads from);
its output is the new sidecar at `sidecar_path`, which is already in the
delta. The other four byte-changing media events need both keys because
phase-A may have placed the file somewhere different from where the
journal-time path resolves when path-changing events interleave.

The parametrized `test_state_delta_keys_match_contract` from Sprint 6 grows by these six rows automatically; Sprint 7 also updates its REENCODE_VIDEO / REENCODE_AUDIO rows to match the extended keysets.

### `WorldState.sidecar_id_for_path` (new helper)

```python
def sidecar_id_for_path(self, asset_id: str, path: str) -> str:
    """Lookup a sidecar by (asset_id, path). Raises KeyError if missing.

    Validation guarantees the lookup succeeds for any well-formed scenario;
    the engine raises rather than emitting a journal entry — a missing
    sidecar is a bug at this layer.
    """
    for sid, sidecar in self.sidecars.items():
        if sidecar.asset_id == asset_id and sidecar.path == path:
            return sid
    raise KeyError(
        f"no sidecar for asset {asset_id!r} at path {path!r}"
    )
```

### Lifecycle simulator extensions

`rule_timeline_lifecycle` extends:

```python
_LOCATION_DEPENDENT_PASSTHROUGH |= frozenset({
    TimelineActionName.REMUX_CONTAINER,
    TimelineActionName.EDIT_METADATA,
    TimelineActionName.EMBED_SUBTITLE,
    TimelineActionName.EXTRACT_SUBTITLE,
    TimelineActionName.REMOVE_SIDECAR,
    TimelineActionName.UPDATE_SIDECAR,
})
```

The set's intent is **"operations forbidden against an asset with a pending slow_copy"**, not literally "operations that mutate the path". The Sprint 6 name predates byte-only mutators and is retained for surgical scope; a follow-up issue tracks the rename. Sprint 7 makes the full membership explicit:

```python
_PATH_MUTATING_PASSTHROUGH |= frozenset({
    TimelineActionName.REENCODE_VIDEO,    # in-place re-encode; unsafe mid-slow-copy
    TimelineActionName.REENCODE_AUDIO,    # in-place re-encode; unsafe mid-slow-copy
    TimelineActionName.REMUX_CONTAINER,   # path-changing
    TimelineActionName.EDIT_METADATA,     # in-place byte mutator
    TimelineActionName.EMBED_SUBTITLE,    # in-place byte mutator
    TimelineActionName.EXTRACT_SUBTITLE,  # READS the asset; unsafe mid-slow-copy
})
```

`UPDATE_SIDECAR` and `REMOVE_SIDECAR` are intentionally **excluded** — both operate on a sidecar file, not the asset's bytes or path; a pending slow_copy on the asset doesn't affect their safety.

The simulator's `state.sidecars_by_path` projection is new — a `dict[(asset_id, path), bool]` of currently-existing sidecars, updated by `create_sidecar` (insert), `remove_sidecar` / `embed_subtitle` (delete), `extract_subtitle` (insert). Embed/extract/remove/update on a non-existing sidecar emits `E_LIFECYCLE_INVALID`. (`E_SIDECAR_TARGET_UNKNOWN` from the new structural rule covers the static case where the path was never declared; the lifecycle rule covers the dynamic case where it was deleted earlier in the timeline.)

### New validation rules

`rules/sidecar_target.py`:

```python
def rule_sidecar_target(scenario, ...) -> list[ValidationIssue]:
    """remove/update/embed events must reference a sidecar that exists in
    scope: either declared on the asset (asset.subtitles[].mode=SIDECAR for
    subtitles) or created earlier in the timeline by create_sidecar /
    extract_subtitle.

    Tracks (asset_id, path) -> kind at each timeline step. The projection
    is updated by create_sidecar (inserts with the event's kind) and
    extract_subtitle (inserts with kind="subtitle"); entries are removed
    by remove_sidecar / embed_subtitle (the sidecar file is consumed).

    Emits E_SIDECAR_TARGET_UNKNOWN on miss.

    Also enforces two kind/path constraints over the same projection:

    - embed_subtitle.sidecar_path MUST resolve to a sidecar whose tracked
      kind is "subtitle". On a non-subtitle target (e.g. a poster sidecar
      created earlier in the timeline), emits E_SIDECAR_KIND_MISMATCH.
      Catches the case where the engine would otherwise hand a PNG /
      arbitrary-bytes file to ffmpeg's subtitle muxer and surface as a
      runtime E_MATERIALIZE_MEDIA_FAILED instead of a Layer-3
      validation error.
    - extract_subtitle.to MUST NOT collide with any sidecar path that is
      currently live in the (asset_id, path) projection at the simulated
      point in the timeline — neither a declared subtitle path
      (<asset_id>.<language>.srt per "Declared-sidecar path convention")
      nor a previously-created-and-not-yet-removed sidecar. On collision,
      emits E_SIDECAR_PATH_COLLISION. (A previously-removed path that
      has been freed by remove_sidecar / embed_subtitle is a valid
      target.)
    """
```

`rules/extract_track_unknown.py`:

```python
def rule_extract_track_unknown(scenario, ...) -> list[ValidationIssue]:
    """extract_subtitle on an asset with no declared subtitle track emits
    E_EXTRACT_TRACK_UNKNOWN. The asset's subtitle declarations live on
    asset.subtitles (both mode=embedded and mode=sidecar count: a sidecar
    that's been embedded earlier in the timeline becomes an embedded
    track at the embed time).
    """
```

### Path-containment integration

`rules/path_containment.py` extends to `extract_subtitle.to` (a new sidecar path). All other new events reference existing paths already covered.

## Manifest Changes

`MANIFEST_SCHEMA_VERSION` bumps 3 → 4. One additive change.

```python
class ManifestSidecar(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    asset_id: str
    kind: str
    path: str
    language: str | None = None   # was: str
    content_hash: str | None = ...
```

The existing `_find_sidecar_for` lookup in `manifest_build.py` branches on `kind`:

```python
def _find_sidecar_for(
    manifest: Manifest,
    *,
    asset_id: str,
    kind: str,
    language: str | None = None,
) -> ManifestSidecar | None:
    if kind == "subtitle":
        assert language is not None
        return next((s for s in manifest.sidecars
                     if s.asset_id == asset_id and s.kind == "subtitle"
                     and s.language == language), None)
    return next((s for s in manifest.sidecars
                 if s.asset_id == asset_id and s.kind == kind), None)
```

Subtitle keeps `(asset_id, language)`; poster/NFO uses `(asset_id, kind)` (one poster per asset, one NFO per asset, multiple subtitles per language).

## Materializer Phase-B Media Dispatcher

`materializer/media.py` exposes one orchestrator-facing entry point per action, plus a `_dispatch_media` wrapper that times each call and packages a `MediaAction`.

```python
def apply_media_action(
    ctx: _MediaContext, entry: JournalEntry
) -> _MediaResult:
    """Dispatch one journal entry to its ffmpeg-based handler. Raises
    MediaActionError on ffmpeg non-zero exit, ffprobe parse failure, or
    OSError during the rename.
    """
```

### `MediaAction` audit shape

```python
class MediaAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: TimelineActionName
    target_asset_id: str
    input_path: str                  # library-relative
    output_path: str                 # library-relative (may equal input_path)
    input_version_id: str | None     # None for extract_subtitle / update_sidecar
    output_version_id: str | None    # None for extract_subtitle / remove_sidecar / update_sidecar
    output_sidecar_id: str | None    # populated by extract_subtitle / update_sidecar
    input_content_hash: str | None   # sha256:..., when applicable
    output_content_hash: str | None
    tool_invocation_index: int | None  # cross-ref into MaterializationReport.invocations
    duration_ns: int
```

`tool_invocation_index` is a numeric pointer into the existing `MaterializationReport.invocations` array — Sprint 5 already records every ffmpeg/ffprobe call there. `MediaAction` carries the index so consumers can join the audit streams without re-parsing tool args.

### Per-action behavior

Each ffmpeg-driven handler writes to a sibling temp file (`<output>.tmp.<resolved_seed>`), then `Path.replace`s into place. The temp-file dance gives us atomicity even when input == output.

| Action | ffmpeg command (sketch) | Output path | Re-probe? | Re-hash? |
|---|---|---|---|---|
| `reencode_video` | `-i in -vf scale=... -c:v <codec> -c:a copy -c:s copy out` | same as input | yes | yes |
| `reencode_audio` | `-i in -c:v copy -ac <to_channels> -c:a aac -c:s copy out` | same as input | yes | yes |
| `remux_container` | `-i in -c copy <out.new_ext>` | new extension | yes | yes |
| `edit_metadata` | `-i in -c copy -map_metadata 0 -metadata k=v ... out` | same | yes | yes |
| `embed_subtitle` | `-i video -i sidecar -map 0 -map 1 -c:v copy -c:a copy -c:s <subtitle_codec_for(output_ext)> out`, then `Path(sidecar).unlink()` | same as video input | yes | yes |
| `extract_subtitle` | `-i in -map 0:s:m:language:<lang>? -c:s <subtitle_codec_for(output_ext)> sidecar.srt` (fallback to `-map 0:s:0` if no language match) | sidecar path (new) | no (video unchanged) | hash sidecar only |
| `update_sidecar` | regenerate bytes via `sidecar_bytes.regenerate_sidecar` with a perturbed sub-seed `Hash(seed_stream="sidecar_update", sidecar_id, event_id)` (subtitle/NFO are pure Python; poster invokes ffmpeg lavfi); write to temp; rename into place | same | no | yes |

Subtitle codec is selected per-container by `media._subtitle_codec_for_container`. MKV / WebM → `srt`; MP4 / M4V / MOV → `mov_text`. Other containers raise `MediaActionError` (`E_MATERIALIZE_MEDIA_FAILED`) at dispatch time. The extract handler's output is always `.srt`, so its codec selection always returns `srt`; the table column shows the helper call for consistency with the embed row, whose output container is the asset's current container.

For `reencode_audio`, `from_channels` is descriptive only — ffmpeg's `-ac` accepts the target; the source is auto-detected. The journal preserves both for the oracle record.

### `_STDLIB_ACTIONS` / `_MEDIA_ACTIONS` constants

```python
_STDLIB_ACTIONS: Final[frozenset[TimelineActionName]] = SUPPORTED_S6_ACTIONS | {
    TimelineActionName.REMOVE_SIDECAR,    # pure unlink + manifest row delete
}

_MEDIA_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset({
    TimelineActionName.REENCODE_VIDEO,
    TimelineActionName.REENCODE_AUDIO,
    TimelineActionName.REMUX_CONTAINER,
    TimelineActionName.EDIT_METADATA,
    TimelineActionName.EMBED_SUBTITLE,
    TimelineActionName.EXTRACT_SUBTITLE,
    TimelineActionName.UPDATE_SIDECAR,    # bytes change + re-hash;
                                          # dispatched through media.py for
                                          # the audit/atomic-write machinery
                                          # even when the byte generator
                                          # itself is pure Python
})

SUPPORTED_S7_ACTIONS: Final[frozenset[TimelineActionName]] = (
    _STDLIB_ACTIONS | _MEDIA_ACTIONS
)
# add_file remains excluded; preflight rejects it with
# E_MATERIALIZE_TIMELINE_UNSUPPORTED.
```

### Re-probe + re-hash flow

After each successful media handler, the dispatcher:

```python
post_path = ctx.library_root / result.output_path
new_hash = "sha256:" + hashlib.sha256(post_path.read_bytes()).hexdigest()
if result.requires_probe:
    new_probed = probe_file(post_path, ffprobe_path=ctx.ffprobe_path)
else:
    new_probed = None
if result.new_version_id is not None:
    ctx.post_phase_b_versions[result.new_version_id] = (new_hash, new_probed)
if result.new_sidecar_id is not None:
    ctx.post_phase_b_sidecars[result.new_sidecar_id] = (new_hash, result.output_path)
```

`manifest_build.augment_versions(manifest, post_phase_b_versions)` and `augment_updated_sidecars(manifest, post_phase_b_sidecars)` stamp the manifest before the atomic write. Both functions key on the appropriate id — same pattern as Sprint 6's `augment_timeline_sidecars`.

### Capability gate

`detect_capabilities()` already records ffmpeg + ffprobe versions. Sprint 7 adds no new capability requirements. mkvmerge remains optional and unused; the source design's "MKVToolNix when needed" stays forward-looking.

## Report Changes

### `VersionHistoryEntry`

```python
class VersionHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: TimelineActionName
    logical_time_ns: int
    input_version_id: str | None       # None for extract_subtitle, sidecar ops
    output_version_id: str | None
    state_delta_summary: dict[str, object]  # selected keys per _PRESERVED_DELTA_KEYS
```

### `AssetReport.version_history`

```python
class AssetReport(BaseModel):
    # ... existing fields: asset_id, initial, history, current, path_history ...
    schema_version: Literal[4]
    version_history: list[VersionHistoryEntry] = Field(default_factory=list)
```

### Derivation

```python
_VERSION_AFFECTING_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset({
    TimelineActionName.REENCODE_VIDEO,
    TimelineActionName.REENCODE_AUDIO,
    TimelineActionName.REMUX_CONTAINER,
    TimelineActionName.EDIT_METADATA,
    TimelineActionName.EMBED_SUBTITLE,
})

_PRESERVED_DELTA_KEYS: Final[dict[TimelineActionName, frozenset[str]]] = {
    TimelineActionName.REENCODE_VIDEO:  frozenset({"resolution", "codec"}),
    TimelineActionName.REENCODE_AUDIO:  frozenset({"from_channels", "to_channels"}),
    TimelineActionName.REMUX_CONTAINER: frozenset({"from_container", "to_container"}),
    TimelineActionName.EDIT_METADATA:   frozenset({"fields"}),
    TimelineActionName.EMBED_SUBTITLE:  frozenset({"language", "kind"}),
}


def derive_version_history(
    asset_id: str, journal: Iterable[JournalEntry]
) -> list[VersionHistoryEntry]:
    history = []
    for entry in journal:
        if entry.action not in _VERSION_AFFECTING_ACTIONS:
            continue
        if asset_id not in entry.target_ids:
            continue
        preserved_keys = _PRESERVED_DELTA_KEYS[entry.action]
        history.append(VersionHistoryEntry(
            event_id=entry.event_id,
            action=entry.action,
            logical_time_ns=entry.logical_time_ns,
            input_version_id=(entry.input_version_ids[0]
                              if entry.input_version_ids else None),
            output_version_id=(entry.output_version_ids[0]
                               if entry.output_version_ids else None),
            state_delta_summary={k: entry.state_delta[k]
                                 for k in preserved_keys
                                 if k in entry.state_delta},
        ))
    return history
```

`engine/reports.py:build_report_set` calls `derive_version_history(asset.id, journal)` for every asset and threads the result into the `AssetReport` constructor. Plan-only and materialize both pass through this function — no mode-specific branching, same as `path_history`.

The `_PRESERVED_DELTA_KEYS` table is the explicit, drift-locked contract for what each `state_delta_summary` carries. A Layer 2 parametrized test (`test_version_history_summary_keys`) asserts that the emitted `state_delta_summary` matches the table — locks the surface against silent drift in future sprints, same way Sprint 6 locked `_STATE_DELTA_KEYS`.

## MaterializationReport Changes

`MATERIALIZATION_SCHEMA_VERSION` bumps 3 → 4.

```python
class FailureStage(enum.StrEnum):
    FFMPEG = "ffmpeg"
    FFPROBE = "ffprobe"
    FILESYSTEM = "filesystem"
    MEDIA = "media"               # NEW


class Outcome(enum.StrEnum):
    SUCCESS = "success"
    UNSUPPORTED = "unsupported"
    TOOL_FAILED = "tool_failed"
    TOOL_MISSING = "tool_missing"
    CONTAINMENT_VIOLATION = "containment_violation"
    FS_FAILED = "fs_failed"
    MEDIA_FAILED = "media_failed"  # NEW


class MaterializationReport(BaseModel):
    # ... existing fields ...
    schema_version: Literal[4]
    media_actions: list[MediaAction] = Field(default_factory=list)
```

## Error Model

| code | when | error_code(s) |
|---|---|---|
| 0 | success | — |
| 2 | usage error (Typer-handled) | — |
| 3 | scenario validation failed | E_* from validation pipeline, incl. new **E_SIDECAR_TARGET_UNKNOWN**, **E_EXTRACT_TRACK_UNKNOWN**, **E_SIDECAR_KIND_MISMATCH**, **E_SIDECAR_PATH_COLLISION** |
| 4 | required tool missing or below minimum | E_MATERIALIZE_CAPABILITY_GATE |
| 5 | materializer ran but produced an error | E_MATERIALIZE_TIMELINE_UNSUPPORTED, E_MATERIALIZE_UNSUPPORTED, E_MATERIALIZE_TOOL_FAILED, E_MATERIALIZE_PROBE_PARSE_FAILED, E_MATERIALIZE_FS_FAILED, **E_MATERIALIZE_MEDIA_FAILED** |
| 7 | containment violation; or in-progress sentinel | E_PATH_CONTAINMENT, E_SENTINEL_IN_PROGRESS |

### Exit-5 outcome mapping (additive on Sprint 6)

| error_code | `outcome` | writes materialization.json? |
|---|---|---|
| **E_MATERIALIZE_MEDIA_FAILED** | **`media_failed`** | **yes** |

### JSON failure payload for phase-B media failures

```json
{
  "error_code": "E_MATERIALIZE_MEDIA_FAILED",
  "message": "reencode_video failed for event reencode_001: ffmpeg exit 1",
  "event_id": "reencode_001",
  "action": "reencode_video",
  "asset_id": "asset_main",
  "tool_invocation_index": 7,
  "materialization_report_path": "fixtures/run-001/materialization.json"
}
```

### Exception hierarchy additions

```python
class MediaActionError(MaterializationError):
    error_code: str = "E_MATERIALIZE_MEDIA_FAILED"

    def __init__(
        self,
        message: str,
        *,
        event_id: str,
        action: TimelineActionName,
        cause: Exception,
        asset_id: str | None = None,
        tool_invocation_index: int | None = None,
        field: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        merged_payload = dict(payload or {})
        merged_payload.setdefault("event_id", event_id)
        merged_payload.setdefault("action", action.value)
        merged_payload.setdefault("tool_invocation_index", tool_invocation_index)
        super().__init__(message, asset_id=asset_id, field=field, payload=merged_payload)
        self.event_id = event_id
        self.cause = cause
        self.action = action
        self.tool_invocation_index = tool_invocation_index
```

The existing `cli/app.py:materialize` try/except dispatches on subclass identity; adding `MediaActionError` is a one-line extension.

## Testing Strategy

Five test layers mirroring source layout under `tests/`.

### Layer 1 — Contract drift gate (existing, extended)

`schema_export.py --check` runs in CI. Sprint 7 brings:

- `scenario.schema.json` (v5) — six new event variants in the discriminated union, `SidecarKind` enum, widened `CreateSidecarEvent`.
- `manifest.schema.json` (v4) — `ManifestSidecar.language` optional.
- `materialization.schema.json` (v4) — `MediaAction`, `MEDIA_FAILED`, `MEDIA` enum members.
- `asset-report.schema.json` (v4) — `VersionHistoryEntry`, `version_history` array.

`tests/contract/test_contract_constants.py` asserts the four bumped version constants.

### Layer 2 — Pure unit tests (no subprocess, no I/O)

```
tests/engine/test_events_sprint7.py
  - test_remux_container_handler_allocates_version
  - test_remux_container_handler_rewrites_extension
  - test_edit_metadata_handler_allocates_version
  - test_edit_metadata_handler_preserves_fields_dict
  - test_embed_subtitle_handler_allocates_version
  - test_embed_subtitle_handler_removes_sidecar_from_state
  - test_extract_subtitle_handler_allocates_sidecar
  - test_extract_subtitle_handler_does_not_allocate_version
  - test_remove_sidecar_handler_removes_from_state
  - test_update_sidecar_handler_no_state_mutation
  - test_state_delta_keys_match_contract: extended with the 6 new actions

tests/engine/test_version_history.py
  - test_version_history_empty_for_static_asset
  - test_version_history_orders_chronologically
  - test_version_history_filters_non_version_actions: move_asset on the
    same asset is excluded
  - test_version_history_records_input_output_version_ids
  - test_version_history_summary_keys: parametrized over
    _PRESERVED_DELTA_KEYS; for each version-affecting action, build a
    minimal scenario, run the engine, assert the emitted
    state_delta_summary's keys match the table.
  - test_version_history_extract_subtitle_excluded: extract doesn't
    allocate a version, so it's not in version_history

tests/contract/test_scenario_v5.py
  - round-trip tests for each new event variant (6)
  - test_create_sidecar_kind_subtitle_requires_language
  - test_create_sidecar_kind_poster_forbids_language
  - test_create_sidecar_kind_nfo_forbids_language
  - test_create_sidecar_default_kind_is_subtitle
  - test_edit_metadata_rejects_empty_fields
  - existing v4 fixtures still validate after bumping schema_version

tests/contract/test_manifest_v4.py
  - test_sidecar_language_optional_for_poster
  - test_sidecar_language_optional_for_nfo

tests/materializer/test_media.py  # NEW MODULE
  - test_apply_reencode_video_invokes_ffmpeg_scale_and_codec
  - test_apply_reencode_audio_invokes_ffmpeg_ac_and_codec
  - test_apply_remux_container_uses_c_copy_with_new_ext
  - test_apply_edit_metadata_passes_each_field
  - test_apply_embed_subtitle_removes_sidecar_after_success
  - test_apply_extract_subtitle_writes_srt_at_to_path
  - test_apply_extract_subtitle_falls_back_to_track_0_on_lang_miss
  - test_apply_update_sidecar_perturbs_seed_for_new_bytes
  - test_apply_atomic_write_uses_temp_sibling
  - test_apply_oserror_wraps_into_MediaActionError
  - test_apply_ffmpeg_nonzero_exit_wraps_into_MediaActionError
  - test_subtitle_codec_mkv_uses_srt
  - test_subtitle_codec_mp4_uses_mov_text
  - test_subtitle_codec_unsupported_container_raises_MediaActionError

tests/validation/rules/test_sidecar_target.py  # NEW
  - test_remove_sidecar_unknown_path -> E_SIDECAR_TARGET_UNKNOWN
  - test_update_sidecar_unknown_path -> E_SIDECAR_TARGET_UNKNOWN
  - test_embed_subtitle_unknown_sidecar_path -> E_SIDECAR_TARGET_UNKNOWN
  - test_embed_subtitle_against_poster_sidecar -> E_SIDECAR_KIND_MISMATCH
  - test_extract_subtitle_to_collides_with_declared_subtitle ->
    E_SIDECAR_PATH_COLLISION
  - test_extract_subtitle_to_collides_with_created_sidecar ->
    E_SIDECAR_PATH_COLLISION
  - test_remove_sidecar_after_create_sidecar_valid
  - test_embed_then_extract_valid (re-extracted sidecar at the right path)

tests/validation/rules/test_extract_track_unknown.py  # NEW
  - test_extract_subtitle_on_asset_without_subtitle_track ->
    E_EXTRACT_TRACK_UNKNOWN

tests/validation/rules/test_timeline_lifecycle_sprint7.py
  - test_each_new_action_on_unplaced_asset -> E_LIFECYCLE_INVALID (6 cases)
  - test_slow_copy_forbidden_action -> E_LIFECYCLE_INVALID (4 cases:
    remux, edit_metadata, embed_subtitle, extract_subtitle)
  - test_update_sidecar_during_pending_slow_copy_valid (positive case;
    locks the exclusion)
  - test_remove_sidecar_during_pending_slow_copy_valid (positive case;
    locks the exclusion)
  - test_remove_sidecar_after_remove_sidecar -> E_LIFECYCLE_INVALID
  - test_update_sidecar_on_removed_sidecar -> E_LIFECYCLE_INVALID
  - test_embed_subtitle_consumes_sidecar (subsequent ops on the same
    sidecar path fail)
```

### Layer 3 — Materializer orchestrator unit tests (mocked subprocess)

```
tests/materializer/test_run_sprint7.py
  - run_ffmpeg, probe_file patched at module boundary (ffmpeg writes
    100-byte stub files; probe returns canned ProbedMedia)
  - test_reencode_video_timeline_runs_phase_b: assert library/ contains
    the file at the original path, materialization_report.media_actions
    has 1 entry, outcome=success
  - test_mixed_filesystem_and_media_timeline: move_asset + reencode_video
    + rename_file; assert journal order preserved in both fs_actions and
    media_actions arrays; final file at the renamed path
  - test_phase_b_media_oserror_aborts_and_cleans_up: monkeypatch
    _apply_reencode_video to raise OSError on first call; assert library/
    wiped, materialization.json present with outcome=media_failed,
    failures[0].stage=media, exit 5
  - test_phase_b_ffmpeg_nonzero_aborts_and_cleans_up: ffmpeg mock returns
    exit 1; assert outcome=media_failed,
    failures[0].tool_invocation_index points at the failing call
  - test_track_add_rejected_at_preflight: scenario with track_add (not
    supported) -> E_MATERIALIZE_TIMELINE_UNSUPPORTED, no run-dir
```

### Layer 4 — Real-tool integration tests (skip-if-not-installed)

```
tests/integration/test_materialize_sprint7_real.py
  pytest.mark.skipif(not _ffmpeg_meets_minimum(), reason="ffmpeg >= 7.0")

  - test_version_evolution_end_to_end:
      EXIT CRITERION #1. Runs version-evolution.yaml (extended fixture
      with one edit_metadata event) through materialize. Asserts:
        * library/movies-hd/Pulsar.mkv exists
        * sha256 differs from initial (reencode + downmix + meta)
        * manifest.current.versions has 4 entries (initial + 3 mutations)
        * each post-initial version has content_hash + probed populated
        * ffprobe on the final file reports resolution=SD, channels=2
        * reports/assets/asset_main.json.version_history has 3 entries
        * materialization.json.media_actions has 3 entries

  - test_bundle_sidecars_end_to_end:
      EXIT CRITERION #2. Runs bundle-sidecars.yaml (extended fixture with
      poster, NFO, embed_subtitle consuming the declared English subtitle,
      and a rename_file on the asset).
      Asserts:
        * library/movies-hd/Quasar.HD.mkv exists with embedded subtitle
          (asset renamed)
        * library/asset_main.eng.srt does NOT exist (the declared
          subtitle's phase-A path was consumed by embed_subtitle)
        * library/movies-hd/Quasar.poster.png exists
        * library/movies-hd/Quasar.nfo exists
        * manifest.current.sidecars has 2 entries (poster, NFO) at their
          original paths
        * reports/bundles/bundle_hd.json lists the renamed asset and
          the two unrenamed sidecars

  - test_remux_container_real:
      A new fixture (remux-container.yaml) mkv -> mp4. Assert ffprobe
      reports mp4 container after materialize, content_hash differs.

  - test_edit_metadata_real:
      A new fixture (edit-metadata.yaml). Assert ffprobe metadata fields
      reflect the dict.

  - test_embed_then_extract_round_trip:
      Embed sidecar, then extract it back. Assert the extracted .srt
      carries the same timing data as the original sidecar.

  - test_update_sidecar_changes_content_hash:
      Update an existing subtitle. Assert
      manifest.current.sidecars[X].content_hash differs from initial;
      sidecar.id is preserved.

  - test_remove_sidecar_real:
      Remove a subtitle. Assert sidecar file is gone; manifest row removed.

  - test_subtitle_ops_on_mp4_asset_use_mov_text:
      Small fixture (subtitle-ops-on-mp4.yaml) that `remux_container mkv ->
      mp4` then `embed_subtitle` on the mp4 asset. Assert ffprobe reports
      `mov_text` codec on the subtitle track and library/...mp4 exists.
      Locks the per-container subtitle codec selection end-to-end.

  - test_phase_b_media_failure_cleans_library:
      Hand-craft a scenario that ffmpeg rejects — e.g., `reencode_audio`
      with `to_channels="quad"` (ffmpeg's `-ac quad` is rejected;
      `from_channels` would not trigger failure because the spec treats
      it as descriptive only and ffmpeg auto-detects the source channel
      count). Assert exit 5, `library/` wiped, materialization.json
      present with outcome=media_failed.
```

### Layer 5 — CLI integration tests

```
tests/cli/test_materialize_sprint7.py
  - test_materialize_media_timeline_exit_0: mocked detect_capabilities
    + materialize_scenario; assert exit 0, JSON payload shape
  - test_materialize_media_failed_exit_5: mock raises MediaActionError;
    assert error_code, event_id, action, tool_invocation_index in stdout
```

### Existing-fixture validation

Every existing fixture under `tests/fixtures/scenarios/` (subtle: the v4 → v5 bump is purely additive at the wire format, but `schema_version: Literal[5]` on the `Scenario` model rejects the bare integer `4`, so the fixtures themselves must be edited). The change is a one-line bump per fixture.

### New scenario fixtures

```
tests/fixtures/scenarios/
  version-evolution.yaml       # EXTENDED: add one edit_metadata event
  bundle-sidecars.yaml         # EXTENDED: add poster + NFO + embed_subtitle
                               # + coordinated bundle-rename
  remux-container.yaml         # NEW
  edit-metadata.yaml           # NEW
  embed-extract-roundtrip.yaml # NEW
  update-sidecar.yaml          # NEW
  remove-sidecar.yaml          # NEW
  subtitle-ops-on-mp4.yaml     # NEW: mp4 subtitle codec coverage

tests/fixtures/scenarios/invalid/
  edit-metadata-empty-fields.yaml          # NEW: E_SCHEMA_INVALID
  embed-subtitle-unknown-sidecar.yaml      # NEW: E_SIDECAR_TARGET_UNKNOWN
  embed-subtitle-kind-mismatch.yaml        # NEW: E_SIDECAR_KIND_MISMATCH
  extract-subtitle-no-track.yaml           # NEW: E_EXTRACT_TRACK_UNKNOWN
  extract-subtitle-collides-with-declared.yaml  # NEW: E_SIDECAR_PATH_COLLISION
  remove-sidecar-after-remove.yaml         # NEW: E_LIFECYCLE_INVALID
  create-poster-with-language.yaml         # NEW: E_SCHEMA_INVALID
```

### Out of scope for Sprint 7 tests

- Track add/remove/reorder (deferred).
- Default/forced/commentary flag edits (deferred).
- Subtitle convert (deferred).
- Bitrate change (deferred).
- Wall-clock slow_copy partial growth (Sprint 8).
- Plan-vs-materialize journal equivalence beyond filesystem mutations (Sprint 9's adapter).
- Materialize replay (still stubbed at E_MATERIALIZE_REPLAY_NOT_IMPLEMENTED per Sprint 5 spec).
- `step` on materialize fixtures (stays plan-only per Sprint 6).

## Exit Criteria

From the source design doc:

- ✅ Version Evolution scenario runs end-to-end → Layer 4 `test_version_evolution_end_to_end`.
- ✅ Bundle Sidecars scenario runs end-to-end → Layer 4 `test_bundle_sidecars_end_to_end`.

Plus additions resolved during brainstorming:

- ✅ Six new scenario actions validate and execute → Layer 2 + Layer 4.
- ✅ Re-probe and re-hash populate `ManifestVersion.content_hash` and `probed` for every post-phase-B version → Layer 4.
- ✅ Sidecar kind extension (subtitle / poster / NFO) materializes → Layer 4 Bundle Sidecars test.
- ✅ Phase-B media failure wipes library and writes `materialization.json` → Layer 3 + Layer 4.
- ✅ All four schema artifacts in the drift gate validate after `--write` (scenario v5, manifest v4, materialization v4, asset-report v4).
- ✅ mkvmerge remains optional (source design's Sprint-7 Open Question resolved).

## Alternatives Rejected

- **All thirteen mutations in Sprint 7.** Too large for one PR; precedent has been one PR per sprint. Cut to the mid-cut covering both exit criteria.

- **Per-key event variants for metadata** (`set_title`, `set_language`, etc.). Explodes the action enum for marginal value over the dict shape. Rejected.

- **Unified `PhaseBAction` discriminated union** for the audit array. Would have broken Sprint 6's wire format (materialization v3 consumers re-key); parallel arrays match Sprint 5's `invocations` precedent. Rejected.

- **Phase C for media mutations** (separate after-phase-B walk). Breaks correct ordering when filesystem and media events interleave; would force a "replay path tracking in phase C" duplication of Sprint 6 logic. Rejected.

- **Sentinel `"und"` for poster/NFO language.** Lies in the data; the schema bump to optional is the honest move. Rejected.

- **Hard fail when `extract_subtitle` language doesn't match a track.** Picked fallback to track 0 because the scenario contract has no way to express track index; failing loud would surprise authors. Rejected.

- **Bundle-aware move event.** A single event that renames an asset plus all its sidecars in one declaration. Rejected as new contract surface for marginal value — scenarios can express the same intent with `rename_file` on the asset plus future per-sidecar rename events at the same `at:`. Coordinated bundle-renames are deferred along with `rename_sidecar` (see "Mid-Cut Scope" / "Deferred").

- **Track the current container in `WorldState`.** Considered for `_handle_remux_container`'s `from_container` field (Finding #3). Rejected — the location's path extension is already the source of truth for the current container, and adding a parallel field would create a synchronization burden every time a path-changing event lands on an asset.

- **`mkvmerge` required.** Resolves source design's Sprint-7 Open Question: every Sprint 7 mutation is achievable with ffmpeg alone. Rejected.

- **`update_sidecar` carries a payload.** Picked "regenerate from recipe + perturbed sub-seed" so scenarios stay declarative about *what* changed without prescribing *how*. Rejected.

- **`extract_subtitle` allocates a new version on the asset.** The asset's bytes are unchanged — extraction is a read. Allocating would be misleading. Asymmetric with `embed_subtitle` (which does allocate); the asymmetry is correct.

- **Declared-on-asset poster/NFO support** (e.g., `Asset.posters`, `Asset.nfo`). Adds contract surface for marginal value over runtime `create_sidecar` events at `at: 0s`. Can land in a follow-up sprint if `at: 0s` proves awkward. Rejected for Sprint 7.

- **Materialize replay this sprint.** Still stubbed per Sprint 5's rationale; Sprint 9's adapter is the first real consumer. Rejected.

- **`add_file` materialize.** Still deferred per Sprint 6 (the Sprint 7 mid-cut focuses on media mutations, not adding files). Preflight rejects with `E_MATERIALIZE_TIMELINE_UNSUPPORTED`.

## Open Questions

None. All design decisions were resolved during brainstorming. The source design's Sprint-7 open question about MKVToolNix is resolved in this spec (optional, not required for any Sprint 7 mutation).
