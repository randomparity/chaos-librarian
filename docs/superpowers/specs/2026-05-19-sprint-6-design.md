# Sprint 6 — Filesystem Mutations

**Status:** design, pending implementation plan.
**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md) — §"Sprint 6", §"Mutation Model", §"Filesystem Safety", §"Materialize Mode", §"Schema Contract".
**Predecessor:** Sprint 5 (`feat/sprint-5`, merged on `main`) shipped `chaos-librarian capabilities` and `chaos-librarian materialize` for static scenarios (empty timeline). Sprint 6 lifts the static-only gate for filesystem mutations.
**Target branch:** `feat/sprint-6`.

## Goal

Lift the Sprint 5 static-only timeline gate for filesystem mutations. Sprint 6 ships:

1. Engine handlers and scenario contract entries for `archive_file` and `move_between_roots` (the two new actions; the four others — `remove_sidecar`, `update_sidecar`, plus the originally-listed media mutations — are deferred).
2. Materializer phase-B dispatcher that executes filesystem effects against `<run-dir>/library/` for every supported timeline action: move, rename, delete, slow-copy (start/commit), archive, move-between-roots, create_sidecar. (`add_file` is deferred to Sprint 7.)
3. Per-asset `path_history` on `AssetReport`, derived from the journal and populated in both plan-only and materialize modes.
4. `FilesystemAction` audit records on `MaterializationReport` so consumers can correlate journal entries to real disk operations.

Sprint 6's materialize rejects any scenario whose timeline contains an action outside the Sprint-6-supported set with `E_MATERIALIZE_UNSUPPORTED` (exit 5). Sprint 7 lifts the restriction for media mutations.

## Design Decisions Resolved In Brainstorming

The source design doc lists eleven mutations under Sprint 6 deliverables, but only resolves the exit criterion ("Identity Move/Rename scenario runs end-to-end on a real directory"). Each open question is resolved below; push back if you disagree before the plan is written.

1. **Mutation scope.** Existing six filesystem actions (move, rename, delete, create_sidecar, slow_copy_start, slow_copy_commit) **plus** `archive_file` and `move_between_roots` — eight supported actions total. `add_file` is deferred to Sprint 7 (see Alternatives Rejected). The two new sidecar actions in the source design (`remove_sidecar`, `update_sidecar`) are deferred to a follow-up sprint. Rationale: the Identity Move/Rename exit criterion only exercises move + rename; archive_file and move_between_roots are filesystem-level moves that share the same execution path; sidecar removal/update can land alongside Sprint 7's media-mutation work where the sidecar lifecycle is more naturally exercised.

2. **Slow-copy materialize behavior.** Two-step temp → final rename. At `slow_copy_start`: write the FULL bytes immediately to `temp_path` (no wall-clock partial growth — that's Sprint 8). Stamp `ManifestLocation.temp_path`. At `slow_copy_commit`: `Path(temp_path).replace(Path(final_path))`. If `final_path != initial_path` (the asset's pre-start location), also `Path(initial_path).unlink(missing_ok=True)` so the on-disk state matches the engine's location model (which treats slow_copy as a teleport via temp). External observers reading the run-dir between the two events see BOTH the initial file and the temp file — that's the watcher-test signal.

3. **Step + materialize.** `chaos-librarian step` stays plan-only-only. A `step <materialize-run-dir>` call continues to surface the existing sentinel/state-recovery errors. Rationale: step's recovery model is journal-replay; extending it to re-derive filesystem state would meaningfully expand scope. Sprint 9's adapter is the first real consumer.

4. **Path history shape.** Add `path_history: list[PathHistoryEntry]` to `AssetReport`. Each entry carries `event_id`, `action` (`TimelineActionName`), `logical_time_ns`, and optional `from_path`/`to_path`/`temp_path`. Derived from the journal (filesystem-affecting subset filtered by `target_ids[0]`). Populated in BOTH plan-only and materialize modes — it's a logical record, not a materialize-only audit. Bumps `ASSET_REPORT_SCHEMA_VERSION` 2 → 3.

5. **Mutation execution model.** Two-phase. Phase A is the existing Sprint 5 synthesis loop (writes every declared asset's initial bytes at its initial path; this is unchanged). Phase B walks the journal and dispatches each entry to `apply_phase_b(library_root=..., journal=..., scenario=..., resolved_seed=...)` which performs the real `Path.rename` / `Path.unlink` / `Path.write_bytes` / `Path.replace`. Clean separation: media bytes come from FFmpeg in phase A, path changes come from python stdlib in phase B.

6. **Mixed timeline policy.** `preflight_timeline(scenario, supported_actions)` runs before phase A. Any timeline event whose action is not in `SUPPORTED_S6_ACTIONS` fails with `E_MATERIALIZE_UNSUPPORTED` (exit 5), payload includes the failing `event_id` and `action`. No run-dir allocated. Reuses the lazy-allocation pattern Sprint 5 established for matrix rejections. The existing `E_MATERIALIZE_TIMELINE_UNSUPPORTED` code is repurposed: instead of "any non-empty timeline" (Sprint 5's meaning) it now means "unsupported timeline action" — Sprint 6 widens the semantics of the same code rather than introducing a parallel one.

7. **Archive/move-between-roots semantics.** Distinct scenario actions with explicit root references:
   - `ArchiveFileEvent`: `target` only; no `to:` field. Destination derived from `library.archive_root` (a new optional `str` field on `Library`). When `archive_root` is unset OR equals the sentinel `"archive"`, the archive path is `<primary_root>/archive/<asset_id>.<container>`. When set to a real root id, the archive path is `<that_root_path>/<asset_id>.<container>`.
   - `MoveBetweenRootsEvent`: `target` + `from_root_id` + `to_root_id`, both referencing entries in `library.roots[].id`. Engine handler synthesizes the destination path as `<to_root.path>/<asset_id>.<container>`.
   - Both root ids (and `archive_root` when set) are validated by a new `E_ROOT_UNKNOWN` rule. Distinguishing these from `move_asset` makes scenarios self-documenting and lets reports filter by intent.

8. **Materialize replay.** Stays stubbed at `MaterializeReplayNotImplemented` (exit 1). Rationale: same as Sprint 5 — the canonicalization rule's real consumer is the voom-v2 adapter (Sprint 9). Adding replay now without a real consumer risks two reworks.

9. **Re-probe and re-hash.** Re-hash and re-probe only when bytes change. `move_asset` / `rename_file` / `delete_file` / `archive_file` / `move_between_roots` / `slow_copy_*` are pure path changes — the existing `content_hash` + `probed` on `ManifestVersion` stay valid; only `ManifestLocation.path` (and `temp_path`) update. `create_sidecar` writes new bytes and hashes them inline; `add_file` is deferred to Sprint 7. Minimizes ffprobe invocations and matches engine semantics.

10. **Filesystem action audit.** `MaterializationReport` gains `filesystem_actions: list[FilesystemAction]` (one record per phase-B operation). Each `FilesystemAction` carries `event_id`, `action`, `target_asset_id`, `from_path`/`to_path`/`temp_path`, and `duration_ns`. Bumps `MATERIALIZATION_SCHEMA_VERSION` 2 → 3. Mirrors the role of `ToolInvocation` for subprocesses.

11. **Failure cleanup.** Wipe `library/` on any phase-B failure (matches Sprint 5's clean-failure model). No best-effort revert: filesystem operations can fail mid-way, and any revert path is itself failure-prone. The `Outcome` enum gains `FS_FAILED` and `FailureStage` gains `FILESYSTEM` — both additive on `materialization.schema.json` v3.

## Architecture

Single PR on `feat/sprint-6`. The engine stays pure plan-only (no `Path` I/O); a new `materializer/filesystem.py` module owns phase-B disk effects. Composition is one-directional: materializer imports engine, never the reverse — same as Sprint 5.

### New modules

```
src/chaos_librarian/materializer/
  filesystem.py    # apply_phase_b(library_root, journal, scenario, resolved_seed)
                   # -> list[FilesystemAction]. Pure stdlib I/O. Per-action
                   # dispatch table; one helper per TimelineActionName variant.

src/chaos_librarian/engine/
  path_history.py  # derive_path_history(asset_id, journal) -> list[PathHistoryEntry]
                   # Pure function. Filters journal to filesystem-affecting
                   # entries for one asset and projects to the report shape.
```

### Modified modules

```
src/chaos_librarian/contract/
  __init__.py         # bumps:
                      #   SCENARIO_SCHEMA_VERSION         3 -> 4
                      #   MATERIALIZATION_SCHEMA_VERSION  2 -> 3
                      #   ASSET_REPORT_SCHEMA_VERSION     2 -> 3
                      # (all other versions unchanged)
  scenario.py         # + ArchiveFileEvent, MoveBetweenRootsEvent;
                      # + TimelineActionName.ARCHIVE_FILE, .MOVE_BETWEEN_ROOTS;
                      # + Library.archive_root: str | None = None;
                      # Scenario.schema_version Literal[4]
  materialization.py  # + FilesystemAction model;
                      # + Outcome.FS_FAILED; + FailureStage.FILESYSTEM;
                      # + MaterializationReport.filesystem_actions;
                      # MaterializationReport.schema_version Literal[3]
  reports.py          # + PathHistoryEntry model;
                      # + AssetReport.path_history; Literal[3]

src/chaos_librarian/engine/
  events.py           # + _handle_archive_file, _handle_move_between_roots;
                      # + _HANDLERS entries for both
  state.py            # + WorldState._root_paths (root_id -> path);
                      # + WorldState._archive_path_template;
                      # + root_path_for / archive_path_for helpers;
                      # build_initial_state populates both from the scenario;
                      # + INITIAL_PATH_TEMPLATE module-level constant lifted
                      # from build_initial_state so the slow-copy validation
                      # rule can format an asset's initial path without
                      # duplicating the path convention
  reports.py          # AssetReport builder calls derive_path_history per asset

src/chaos_librarian/materializer/
  run.py              # remove TimelineUnsupportedError gate for non-empty
                      # timelines; add preflight_timeline call before phase A;
                      # add phase B dispatcher after phase A; call
                      # augment_timeline_sidecars after phase B
  preflight.py        # + preflight_timeline(scenario, supported_actions);
                      # + SUPPORTED_S6_ACTIONS frozenset constant
  finalize.py         # threads filesystem_actions through MaterializationReport
                      # build_report call
  errors.py           # + FilesystemActionError(MaterializationError);
                      # + error_code E_MATERIALIZE_FS_FAILED
  manifest_build.py   # + augment_timeline_sidecars(manifest, phase_b_sidecar_hashes)
                      # — stamps content_hash on timeline-created sidecar rows by
                      # sidecar_id. Sprint 5's augment_manifest (declared-subtitle
                      # path, keyed by (asset_id, language)) is untouched.

src/chaos_librarian/validation/
  rules/timeline_lifecycle.py  # extend simulator with ARCHIVE_FILE and
                               # MOVE_BETWEEN_ROOTS in _LOCATION_DEPENDENT* sets;
                               # archive_file keeps asset placed
  rules/path_containment.py    # synthesize to_path for archive_file from
                               # library.archive_root + asset_id + container;
                               # synthesize to_path for move_between_roots from
                               # to_root.path + asset_id + container; both run
                               # through resolve_under_library
  rules/target_unknown.py      # extend with from_root_id / to_root_id / archive_root
                               # validation; raises new E_ROOT_UNKNOWN code
  codes.py                     # + E_ROOT_UNKNOWN constant
                               # + E_SLOW_COPY_PATH_COLLISION constant

src/chaos_librarian/schema_export.py
                               # regenerate scenario.schema.json (v4),
                               # materialization.schema.json (v3),
                               # asset-report.schema.json (v3); other schemas
                               # untouched
```

### Generated artifacts

```
schemas/
  scenario.schema.json         # REGEN: v4 with ArchiveFileEvent +
                               # MoveBetweenRootsEvent in oneOf;
                               # Library.archive_root optional
  materialization.schema.json  # REGEN: v3 with FilesystemAction,
                               # FS_FAILED, FILESYSTEM enum members
  asset-report.schema.json     # REGEN: v3 with PathHistoryEntry +
                               # path_history array
  # All others unchanged
```

`schema_export.py --check` runs in CI and fails on drift. Engineers regenerate locally with `--write` and commit the updated artifacts in the same change.

### Composition: how a materialize run flows

```
chaos-librarian materialize scenario.yaml --out fixtures/run-001
  cli/app.py:materialize
    detect_capabilities()                        # exit 4 on failure
    validate_scenario(scenario)                  # exit 3 on validation failure
    materializer.materialize_scenario(...)
      step 1: preflight_timeline(scenario,
              SUPPORTED_S6_ACTIONS)              # E_MATERIALIZE_UNSUPPORTED, exit 5
      step 2: containment gate                   # E_PATH_CONTAINMENT, exit 7
      step 3: re-run detect_capabilities         # exit 4 on regression
      step 4: engine.run_plan(scenario)
              -> initial manifest, current manifest, FULL journal, plan-only
              replay shape (the plan-only run_id is discarded; materialize
              assigns a fresh UUIDv4)
      step 5: pre-flight matrix check (Sprint 5) # E_MATERIALIZE_UNSUPPORTED, exit 5
      step 6: begin_materialize_run (Sprint 5)   # sentinel state='in_progress'
      step 7: phase A — synthesis loop           # Sprint 5 logic, unchanged
                build FFmpegInput recipes
                write SRT sidecars declared on asset.subtitles
                run_ffmpeg / probe_file / hash    # E_MATERIALIZE_*, exit 5
                augment manifest
      step 8: phase B — timeline application    # NEW IN SPRINT 6
                filesystem_actions = apply_phase_b(
                  library_root=out_dir/"library",
                  journal=plan_artifacts.journal,
                  scenario=run_input.scenario,
                  resolved_seed=plan_artifacts.replay_bundle.resolved_seed,
                )
                # E_MATERIALIZE_FS_FAILED on first OSError, exit 5
      step 9: atomic metadata write              # Sprint 5 logic, plus
                                                 # filesystem_actions threaded
                                                 # through build_report
      step 10: return MaterializeArtifacts
    cli writes --json payload to stdout, exits 0
```

Failure at any step in phase B: stop the loop, record the failure
(`MaterializationFailure(asset_id, stage=FILESYSTEM, exit_code=None,
stderr_tail=str(exc.cause), invocation_index=None)`), `shutil.rmtree(out_dir /
"library")`, write metadata atomically with `outcome=FS_FAILED`, exit 5.

## Scenario Contract Changes

`SCENARIO_SCHEMA_VERSION` bumps 3 → 4. Two additive shapes; no existing-field
changes. Existing fixtures re-validate cleanly.

### New event variants

```python
class ArchiveFileEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.ARCHIVE_FILE] = TimelineActionName.ARCHIVE_FILE
    target: str
    # No `to:` field. Destination derived from library.archive_root.


class MoveBetweenRootsEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.MOVE_BETWEEN_ROOTS] = (
        TimelineActionName.MOVE_BETWEEN_ROOTS
    )
    target: str
    from_root_id: str
    to_root_id: str
```

Both join the existing discriminated union:

```python
TimelineEvent = Annotated[
    MoveAssetEvent | RenameFileEvent | DeleteFileEvent | AddFileEvent
    | ReencodeVideoEvent | ReencodeAudioEvent | CreateSidecarEvent
    | SlowCopyStartEvent | SlowCopyCommitEvent
    | ArchiveFileEvent | MoveBetweenRootsEvent,
    Field(discriminator="action"),
]
```

### `Library.archive_root`

```python
class Library(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    roots: tuple[LibraryRoot, ...]
    archive_root: str | None = None
```

Semantics:
- `None` (default) or `"archive"` (sentinel): archive_file destination is
  `<roots[0].path>/archive/<asset_id>.<container>`.
- Any other value: must match an existing `roots[].id`; archive_file destination
  is `<that_root.path>/<asset_id>.<container>`.
- Validated by the `E_ROOT_UNKNOWN` rule.

The sentinel `"archive"` exists so authors can write `archive_root: "archive"`
to make the default explicit without declaring a real "archive" root.

### `TimelineActionName` extensions

```python
class TimelineActionName(enum.StrEnum):
    # ... existing 9 ...
    ARCHIVE_FILE = "archive_file"
    MOVE_BETWEEN_ROOTS = "move_between_roots"
```

`ALL_TIMELINE_ACTIONS` derives from the enum and picks up both new values
automatically.

## Engine Changes

### New handlers

```python
def _handle_archive_file(state, resolved, ids, run_id, scenario_id):
    """Move target to <archive_root>/<asset_id>.<container>.

    Resolves archive_root once per scenario (cached on state in build_initial_state).
    Updates location.path; asset stays placed.
    """
    event = resolved.event
    assert isinstance(event, ArchiveFileEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    archive_path = state.archive_path_for(event.target)
    state.locations[loc_id] = previous.model_copy(update={"path": archive_path})
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.ARCHIVE_FILE,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={"from_path": previous.path, "to_path": archive_path},
    )
    return (entry,)


def _handle_move_between_roots(state, resolved, ids, run_id, scenario_id):
    """Move target from from_root to to_root, preserving filename.

    The scenario validator has already proven both root ids exist. The
    destination is <to_root.path>/<asset_id>.<container>, computed once
    here from state's cached root lookup.
    """
    event = resolved.event
    assert isinstance(event, MoveBetweenRootsEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    asset = state.assets[event.target]
    to_root_path = state.root_path_for(event.to_root_id)
    destination = f"{to_root_path}/{event.target}.{asset.container}"
    state.locations[loc_id] = previous.model_copy(update={"path": destination})
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.MOVE_BETWEEN_ROOTS,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={
            "from_path": previous.path,
            "to_path": destination,
            "from_root_id": event.from_root_id,
            "to_root_id": event.to_root_id,
        },
    )
    return (entry,)
```

### `state_delta` key contract

The phase-B dispatcher and `derive_path_history` read about ten string keys
out of each journal entry's `state_delta`. The contract has been implicit —
a typo in any handler would silently produce `None` values downstream
rather than failing fast. Sprint 6 makes the contract explicit with a
module-level constant in `engine/events.py`:

```python
_STATE_DELTA_KEYS: Final[dict[TimelineActionName, frozenset[str]]] = {
    TimelineActionName.MOVE_ASSET:         frozenset({"from_path", "to_path"}),
    TimelineActionName.RENAME_FILE:        frozenset({"from_path", "to_path"}),
    TimelineActionName.DELETE_FILE:        frozenset({"removed_path"}),
    TimelineActionName.CREATE_SIDECAR:     frozenset({"sidecar_path", "sidecar_id", "language"}),
    TimelineActionName.SLOW_COPY_START:    frozenset({"final_path", "temp_path", "initial_path_at_start"}),
    TimelineActionName.SLOW_COPY_COMMIT:   frozenset({"final_path"}),
    TimelineActionName.ARCHIVE_FILE:       frozenset({"from_path", "to_path"}),
    TimelineActionName.MOVE_BETWEEN_ROOTS: frozenset(
        {"from_path", "to_path", "from_root_id", "to_root_id"}
    ),
}
```

Semantics:

- Each handler's emitted `state_delta` must contain AT LEAST the keys
  declared for its action. Extra keys are allowed for forward
  compatibility (e.g., a future sprint adding `bytes_written` to
  `slow_copy_start` doesn't break consumers that only read the contract
  set).
- `slow_copy_commit` deliberately carries only `final_path`; its dispatcher
  pops the matching `slow_copy_start` entry from `pending_slow_copy` to
  recover `initial_path` and `temp_path`. The related-event_id traversal
  is already part of the journal model.
- `add_file` is intentionally absent from this table — it is deferred to
  Sprint 7, and the preflight gate rejects it before any handler runs.
  Sprint 7's implementation should add an entry here at the same time the
  helper lands.

A Layer 2 test (`test_state_delta_keys_match_contract`, see Testing
Strategy) parametrizes over `_STATE_DELTA_KEYS` and asserts that each
handler's emitted `state_delta` is a superset of the contract — locking
the surface against drift in future sprints.

### `WorldState` extensions

```python
@dataclass
class WorldState:
    # ... existing fields ...
    _root_paths: dict[str, str] = field(default_factory=dict)   # root_id -> path
    _archive_path_template: str = ""                            # template format string

    def root_path_for(self, root_id: str) -> str:
        return self._root_paths[root_id]

    def archive_path_for(self, asset_id: str) -> str:
        asset = self.assets[asset_id]
        return self._archive_path_template.format(
            asset_id=asset_id, container=asset.container
        )
```

`build_initial_state` populates `_root_paths` and `_archive_path_template`
once at scenario load:

```python
def build_initial_state(scenario, ids):
    # ... existing logic ...
    state._root_paths = {root.id: root.path for root in scenario.library.roots}
    archive_root = scenario.library.archive_root
    if archive_root is None or archive_root == "archive":
        archive_base = f"{primary_root.path}/archive"
    else:
        archive_base = state._root_paths[archive_root]
    state._archive_path_template = f"{archive_base}/{{asset_id}}.{{container}}"
    # ...
```

Validation has already proven `archive_root` references a real root id (or is
the sentinel), so `_root_paths[archive_root]` is safe.

### Lifecycle simulator extensions

`rule_timeline_lifecycle` extends two sets:

```python
_LOCATION_DEPENDENT_PASSTHROUGH = frozenset({
    TimelineActionName.REENCODE_VIDEO,
    TimelineActionName.REENCODE_AUDIO,
    TimelineActionName.CREATE_SIDECAR,
    TimelineActionName.ARCHIVE_FILE,        # NEW
    TimelineActionName.MOVE_BETWEEN_ROOTS,  # NEW
})
```

Both new actions require the target to be placed and keep it placed. Neither
participates in slow-copy interleave restrictions: an asset with a pending
slow_copy cannot be archived or moved-between-roots until the commit lands.
That's enforced by adding both to the `_MUTATION_ACTIONS`-style pending-copy
check:

```python
def _lifecycle_check_passthrough(*, action, target, state, emit, loc):
    if target not in state.placed:
        emit(message=f"{action} on unplaced asset {target!r}", loc=loc)
    if action in _PATH_MUTATING_PASSTHROUGH and target in state.assets_with_pending_copy:
        emit(message=f"{action} on asset {target!r} with a pending slow_copy", loc=loc)


_PATH_MUTATING_PASSTHROUGH = frozenset({
    TimelineActionName.ARCHIVE_FILE,
    TimelineActionName.MOVE_BETWEEN_ROOTS,
})
```

### `E_ROOT_UNKNOWN` validation rule

Lives in `rules/target_unknown.py` (where the closest existing rule lives) or a
new `rules/root_unknown.py` — final placement is an implementation detail. The
rule asserts:

- For every `MoveBetweenRootsEvent`: `event.from_root_id ∈ library.roots[].id`
  and `event.to_root_id ∈ library.roots[].id`.
- For `library.archive_root`: if not None and not the sentinel `"archive"`,
  must match a `library.roots[].id`.

Each violation emits one `ValidationIssue` with code `E_ROOT_UNKNOWN`, severity
ERROR, pointing at the offending field.

### Path-containment integration

`rules/path_containment.py` is responsible for proving every scenario path
resolves under `library/`. The new actions produce synthesized destinations,
which the containment rule needs to validate without re-implementing the
synthesis:

- For `ArchiveFileEvent`: derive `to_path` as `<archive_root_path>/<asset_id>.<container>` and run it through `resolve_under_library`.
- For `MoveBetweenRootsEvent`: derive `to_path` as `<to_root_path>/<asset_id>.<container>` and run it through `resolve_under_library`.

The derivation logic is small (a few lines per action) and lives in
`path_containment.py` directly — the rule already inspects per-event fields, so
adding two more action branches is a localized change.

### Slow-copy path-collision rule

Phase B's `slow_copy_commit` helper unlinks `initial_path` and then
`replace`s `temp_path → final_path` (see "Per-action behavior"). Two
degenerate `temp_path` choices break that contract:

- `temp_path == final_path` — the multi-phase visibility contract collapses
  (no separate temp file ever exists; external observers cannot see the
  in-progress copy).
- `temp_path == initial_path` — the commit's `initial_path.unlink()` wipes
  the temp file before the `replace` runs.

Neither case is caught by `move_after_delete` / `double_slow_copy` /
existing `slow_copy.py` rule. Sprint 6 extends `rules/slow_copy.py` with two
checks that both emit `E_SLOW_COPY_PATH_COLLISION`:

- For every `SlowCopyStartEvent`: assert `event.temp_path != event.to`.
- For every `SlowCopyStartEvent`: assert `event.temp_path` is not the
  asset's initial-state path under the
  `<primary_root>/<asset_id>.<container>` convention.

The initial-path derivation reuses the path template that
`engine.state.build_initial_state` already builds. Sprint 6 lifts that
template to a module-level constant in `engine/state.py` (proposed name:
`INITIAL_PATH_TEMPLATE`) so the validation rule can format it without
duplicating the convention. No new helper is required.

## Materializer Phase-B Dispatcher

`materializer/filesystem.py` exposes one orchestrator-facing entry point that
walks the journal, applies effects, and returns the per-event audit records:

```python
def apply_phase_b(
    *,
    library_root: Path,
    journal: Sequence[JournalEntry],
    scenario: Scenario,
    resolved_seed: int,
) -> list[FilesystemAction]:
    """Walk the journal and apply real filesystem effects.

    Raises ``FilesystemActionError`` on the first OSError; the orchestrator
    catches it, routes through ``cleanup_failed_run``, and exits 5.
    """
```

The dispatcher carries four pieces of incremental state alongside the journal
walk:

- `current_path: dict[str, str]` — initialized from the scenario's per-asset
  initial paths (same convention as `engine.state.build_initial_state`). Each
  filesystem action that moves bytes updates this map.
- `pending_slow_copy: dict[str, _PendingSlowCopy]` — keyed by the
  `slow_copy_start` event_id; populated at start, drained at commit. Tracks
  `asset_id`, `initial_path` (the on-disk path the bytes were copied FROM),
  and `temp_path` (the on-disk path the bytes were copied TO).
- `scenario_assets: Mapping[str, Asset]` — pre-built `{asset_id: Asset}` for
  metadata lookups (duration, container).
- `phase_b_sidecar_hashes: dict[str, str]` — `sidecar_id -> sha256` for every
  timeline-created sidecar written during phase B. Drained after the journal
  walk by `manifest_build.augment_timeline_sidecars(manifest, ...)`, which
  stamps `ManifestSidecar.content_hash` on the matching row. Separate from
  the declared-subtitle path, which feeds Sprint 5's `augment_manifest` via
  an `(asset_id, language)`-keyed map populated during phase A's synthesis
  loop. The two maps never share keys: declared subtitles are not written
  during phase B, and timeline-created sidecars do not pass through the
  phase-A loop.

Each per-action helper has the same signature:

```python
@dataclass(frozen=True, slots=True)
class _PhaseBContext:
    library_root: Path
    scenario_assets: Mapping[str, Asset]
    resolved_seed: int
    current_path: dict[str, str]                     # mutated
    pending_slow_copy: dict[str, _PendingSlowCopy]   # mutated
    phase_b_sidecar_hashes: dict[str, str]           # mutated; sidecar_id -> sha256


def _move_asset(ctx: _PhaseBContext, entry: JournalEntry) -> FilesystemAction:
    asset_id = entry.target_ids[0]
    from_path = entry.state_delta["from_path"]
    to_path = entry.state_delta["to_path"]
    (ctx.library_root / to_path).parent.mkdir(parents=True, exist_ok=True)
    (ctx.library_root / from_path).replace(ctx.library_root / to_path)
    ctx.current_path[asset_id] = to_path
    return FilesystemAction(
        event_id=entry.event_id,
        action=entry.action,
        target_asset_id=asset_id,
        from_path=from_path,
        to_path=to_path,
        duration_ns=0,                       # filled by dispatcher
    )
```

The dispatcher computes `duration_ns` per call:

```python
def _dispatch_one(ctx: _PhaseBContext, entry: JournalEntry) -> FilesystemAction:
    handler = _DISPATCH[entry.action]
    started = time.monotonic_ns()
    try:
        action = handler(ctx, entry)
    except OSError as exc:
        raise FilesystemActionError(
            f"{entry.action} failed for event {entry.event_id}: {exc}",
            event_id=entry.event_id, cause=exc, action=entry.action,
            asset_id=entry.target_ids[0] if entry.target_ids else None,
        ) from exc
    return action.model_copy(update={"duration_ns": time.monotonic_ns() - started})
```

### Per-action behavior

All handlers read paths and asset ids directly from the journal entry — no
appeal to WorldState. The engine already populates the relevant
`state_delta` keys; the only engine-side change required is adding the
sidecar's `language` and the slow-copy's `initial_path_at_start` to their
respective `state_delta` payloads (both additive; `state_delta` is
`dict[str, object]` and accepts arbitrary keys without a schema bump).

| Action | Helper logic |
|---|---|
| `move_asset`, `rename_file`, `move_between_roots`, `archive_file` | `(library/from).replace(library/to)`; update `current_path[asset_id] = to`. The three latter share the body with `move_asset`; the dispatcher entry keeps the original `entry.action` on the `FilesystemAction`. |
| `delete_file` | `(library/from).unlink()`; del `current_path[asset_id]`. |
| `create_sidecar` | Read `language`, `sidecar_path`, and `sidecar_id` from `state_delta` (the engine handler allocates `sidecar_id` and the contract above requires these three keys). Look up `asset.duration_seconds` in `ctx.scenario_assets[asset_id]`. Generate body via `recipes.srt_payload(language=..., duration_s=..., seed=ctx.resolved_seed)`. Write the file at `sidecar_path`, sha256 the bytes, and APPEND to `ctx.phase_b_sidecar_hashes` keyed by `sidecar_id`. After phase B completes, the orchestrator calls `manifest_build.augment_timeline_sidecars(manifest, phase_b_sidecar_hashes)` which iterates `manifest.sidecars`, looks up each `sidecar.id` in the dict, and stamps `content_hash` when present. The existing `augment_manifest` (declared-subtitle path) keeps its `(asset_id, language)` keying — declared subtitles are hashed during phase A's synthesis loop and do not pass through the phase-B map. Collision rule: if a `create_sidecar` event reuses an `(asset_id, language)` pair already occupied by a declared subtitle, the engine handler still allocates a new `sidecar_id` and appends a new `ManifestSidecar` row — both rows coexist in the manifest. The declared row keeps its phase-A hash; the timeline row gets its phase-B hash. The two-row outcome is the intended semantic (declared sidecar plus a runtime-created sidecar are distinct objects in the test surface). |
| `slow_copy_start` | Read `initial_path_at_start` and `temp_path` from `state_delta`. Copy the bytes: `(library/temp_path).write_bytes((library/initial_path).read_bytes())`. Record `pending_slow_copy[entry.event_id] = _PendingSlowCopy(asset_id, initial_path, temp_path)`. `current_path` is NOT updated yet (the bytes are still at the initial path too). |
| `slow_copy_commit` | Pop `pending_slow_copy[entry.related_event_id]`. Read `final_path` from `state_delta`. If `initial_path != final_path`: `(library/initial_path).unlink(missing_ok=True)`. Then `(library/temp_path).replace(library/final_path)`. Update `current_path[asset_id] = final_path`. |

**Slow-copy path invariants.** The validation rule (see "Slow-copy
path-collision rule" above) rejects `temp_path == initial_path` and
`temp_path == final_path` before phase B runs, so the commit helper can
rely on the three paths being pairwise distinct: the `unlink(initial_path)`
cannot wipe `temp_path`, and the `replace(temp_path → final_path)` always
moves bytes from a distinct source to a distinct destination.

### `_DISPATCH` table

```python
_DISPATCH: dict[TimelineActionName, Callable[..., FilesystemAction]] = {
    TimelineActionName.MOVE_ASSET: _move_asset,
    TimelineActionName.RENAME_FILE: _move_asset,           # same body
    TimelineActionName.DELETE_FILE: _delete_file,
    TimelineActionName.CREATE_SIDECAR: _create_sidecar,
    TimelineActionName.SLOW_COPY_START: _slow_copy_start,
    TimelineActionName.SLOW_COPY_COMMIT: _slow_copy_commit,
    TimelineActionName.ARCHIVE_FILE: _move_asset,          # same body
    TimelineActionName.MOVE_BETWEEN_ROOTS: _move_asset,    # same body
}
```

Three actions (`rename_file`, `archive_file`, `move_between_roots`) share
`_move_asset`'s body. The dispatched `FilesystemAction.action` field carries
the original `entry.action` so the audit record preserves the semantic
distinction.

### Engine-side state_delta extensions (additive)

The engine handlers expand their `state_delta` payloads so phase B can drive
purely from the journal:

- `_handle_create_sidecar`: add `state_delta["language"] = event.language`.
- `_handle_slow_copy_start`: add
  `state_delta["initial_path_at_start"] = previous.path`. Also include
  `state_delta["temp_path"] = event.temp_path` so the commit helper can read it
  without going through the `StartedJournalEntry.temp_path` typed field (uniform
  with how move/rename/delete put paths in `state_delta`).

Both changes are additive — `state_delta: dict[str, object]` already accepts
arbitrary keys with no schema bump. Existing consumers ignore extra keys.

### Preflight gate

```python
SUPPORTED_S6_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset({
    TimelineActionName.MOVE_ASSET,
    TimelineActionName.RENAME_FILE,
    TimelineActionName.DELETE_FILE,
    TimelineActionName.CREATE_SIDECAR,
    TimelineActionName.SLOW_COPY_START,
    TimelineActionName.SLOW_COPY_COMMIT,
    TimelineActionName.ARCHIVE_FILE,
    TimelineActionName.MOVE_BETWEEN_ROOTS,
})
# add_file is intentionally excluded; preflight rejects it with
# E_MATERIALIZE_TIMELINE_UNSUPPORTED (deferred to Sprint 7, see Alternatives Rejected).


def preflight_timeline(scenario: Scenario) -> None:
    for index, event in enumerate(scenario.timeline):
        if event.action not in SUPPORTED_S6_ACTIONS:
            raise TimelineUnsupportedError(
                f"timeline action {event.action!r} not supported in Sprint 6",
                field=f"timeline[{index}].action",
                payload={
                    "event_id": event.id,
                    "action": event.action.value,
                    "supported": sorted(a.value for a in SUPPORTED_S6_ACTIONS),
                },
            )
```

## Report Changes

### `PathHistoryEntry`

```python
class PathHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: TimelineActionName
    logical_time_ns: int
    from_path: str | None = None
    to_path: str | None = None
    temp_path: str | None = None
```

### `AssetReport.path_history`

```python
class AssetReport(BaseModel):
    # ... existing fields: asset_id, initial, history, current ...
    schema_version: Literal[3]
    path_history: list[PathHistoryEntry] = Field(default_factory=list)
```

`AssetReport` already carries a `history: list[AssetHistoryEntry]` from Sprint
4 — verbatim journal entries (every event, including media mutations) keyed
by `logical_time_ns`/`event_id`/`action`/`state_delta`. `path_history` lives
alongside it as a typed projection of the filesystem-affecting subset:
external consumers (voom-v2 adapter) get `from_path` / `to_path` / `temp_path`
as typed `str | None` fields without having to filter `history` and parse
`state_delta` keys themselves. The two fields are intentionally redundant;
the verbatim `history` stays the truth source.

### Derivation

```python
_FILESYSTEM_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset({
    TimelineActionName.ADD_FILE,
    TimelineActionName.MOVE_ASSET,
    TimelineActionName.RENAME_FILE,
    TimelineActionName.DELETE_FILE,
    TimelineActionName.CREATE_SIDECAR,
    TimelineActionName.SLOW_COPY_START,
    TimelineActionName.SLOW_COPY_COMMIT,
    TimelineActionName.ARCHIVE_FILE,
    TimelineActionName.MOVE_BETWEEN_ROOTS,
})


def derive_path_history(
    asset_id: str, journal: Iterable[JournalEntry]
) -> list[PathHistoryEntry]:
    """Project the journal to one asset's filesystem-affecting subset."""
    history: list[PathHistoryEntry] = []
    for entry in journal:
        if entry.action not in _FILESYSTEM_ACTIONS:
            continue
        if asset_id not in entry.target_ids:
            continue
        delta = entry.state_delta
        history.append(PathHistoryEntry(
            event_id=entry.event_id,
            action=entry.action,
            logical_time_ns=entry.logical_time_ns,
            from_path=(
                delta.get("from_path")
                or delta.get("removed_path")
                or delta.get("initial_path_at_start")
            ),
            to_path=(
                delta.get("to_path")
                or delta.get("added_path")
                or delta.get("final_path")
                or delta.get("sidecar_path")
            ),
            temp_path=delta.get("temp_path"),
        ))
    return history
```

`engine/reports.py:build_report_set` calls `derive_path_history(asset.id,
journal)` for every asset and threads the result into the AssetReport
constructor. Plan-only and materialize both pass through this function — no
mode-specific branching.

## MaterializationReport Changes

### `FilesystemAction`

```python
class FilesystemAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: TimelineActionName
    target_asset_id: str
    from_path: str | None = None
    to_path: str | None = None
    temp_path: str | None = None
    duration_ns: int
```

### Enum additions

```python
class Outcome(enum.StrEnum):
    SUCCESS = "success"
    UNSUPPORTED = "unsupported"
    TOOL_FAILED = "tool_failed"
    TOOL_MISSING = "tool_missing"
    CONTAINMENT_VIOLATION = "containment_violation"
    FS_FAILED = "fs_failed"      # NEW


class FailureStage(enum.StrEnum):
    FFMPEG = "ffmpeg"
    FFPROBE = "ffprobe"
    FILESYSTEM = "filesystem"     # NEW
```

### `MaterializationReport.filesystem_actions`

```python
class MaterializationReport(BaseModel):
    # ... existing fields ...
    schema_version: Literal[3]
    filesystem_actions: list[FilesystemAction] = Field(default_factory=list)
```

## Error Model

| code | when                                                  | error_code(s) |
|------|-------------------------------------------------------|---------------|
| 0    | success                                               | — |
| 2    | usage error (Typer-handled)                           | — |
| 3    | scenario validation failed                            | E_* from validation pipeline, incl. new E_ROOT_UNKNOWN, new E_SLOW_COPY_PATH_COLLISION |
| 4    | required tool missing or below minimum                | E_MATERIALIZE_CAPABILITY_GATE |
| 5    | materializer ran but produced an error                | E_MATERIALIZE_TIMELINE_UNSUPPORTED (re-purposed: now "unsupported action"), E_MATERIALIZE_UNSUPPORTED, E_MATERIALIZE_TOOL_FAILED, E_MATERIALIZE_PROBE_PARSE_FAILED, **E_MATERIALIZE_FS_FAILED** |
| 7    | containment violation; or in-progress sentinel        | E_PATH_CONTAINMENT, E_SENTINEL_IN_PROGRESS |

### Exit-5 outcome mapping in `materialization.json`

| error_code                            | `outcome` field         | writes materialization.json? |
|---------------------------------------|-------------------------|------------------------------|
| E_MATERIALIZE_TIMELINE_UNSUPPORTED    | `unsupported`           | no (pre-flight)              |
| E_MATERIALIZE_UNSUPPORTED             | `unsupported`           | no (pre-flight)              |
| E_MATERIALIZE_TOOL_FAILED             | `tool_failed`           | yes                          |
| E_MATERIALIZE_PROBE_PARSE_FAILED      | `tool_failed`           | yes                          |
| **E_MATERIALIZE_FS_FAILED**           | **`fs_failed`**         | **yes**                      |
| E_MATERIALIZE_CAPABILITY_GATE         | `tool_missing`          | no (pre-flight, exit 4)      |
| E_PATH_CONTAINMENT (at materialize)   | `containment_violation` | no (pre-flight, exit 7)      |

### JSON failure payload for phase-B failures

```json
{
  "error_code": "E_MATERIALIZE_FS_FAILED",
  "message": "move_asset failed for event move_001: [Errno 2] ...",
  "event_id": "move_001",
  "action": "move_asset",
  "asset_id": "asset_hd_main",
  "errno": 2,
  "materialization_report_path": "fixtures/run-001/materialization.json"
}
```

### Exception hierarchy additions

```python
class FilesystemActionError(MaterializationError):
    error_code: str = "E_MATERIALIZE_FS_FAILED"

    def __init__(
        self,
        message: str,
        *,
        event_id: str,
        cause: OSError,
        action: TimelineActionName,
        asset_id: str | None = None,
        field: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        merged_payload = dict(payload or {})
        merged_payload.setdefault("event_id", event_id)
        merged_payload.setdefault("action", action.value)
        merged_payload.setdefault("errno", cause.errno)
        super().__init__(message, asset_id=asset_id, field=field, payload=merged_payload)
        self.event_id = event_id
        self.cause = cause
        self.action = action
```

The existing `cli/app.py:materialize` try/except dispatches on subclass
identity; adding `FilesystemActionError` is a one-line extension.

## Testing Strategy

Five test layers mirroring source layout under `tests/`.

### Layer 1 — Contract drift gate (existing, extended)

`schema_export.py --check` runs in CI. Sprint 6 brings:

- `scenario.schema.json` (regenerated at v4) with ArchiveFileEvent +
  MoveBetweenRootsEvent in the discriminated union.
- `materialization.schema.json` (regenerated at v3) with FilesystemAction,
  FS_FAILED, FILESYSTEM enum members.
- `asset-report.schema.json` (regenerated at v3) with PathHistoryEntry +
  path_history array.

`tests/contract/test_contract_constants.py` asserts the three bumped version
constants.

### Layer 2 — Pure unit tests (no subprocess, no I/O)

```
tests/engine/test_events_sprint6.py
  - test_archive_file_handler: builds WorldState, applies ArchiveFileEvent,
    asserts location.path is the derived archive path and asset stays placed
  - test_archive_file_with_explicit_archive_root: scenario with
    library.archive_root="staging" (a declared root id); assert derived
    path uses staging root's path
  - test_archive_file_with_sentinel_archive_root: archive_root="archive";
    same outcome as None
  - test_move_between_roots_handler: applies MoveBetweenRootsEvent, asserts
    location.path moves to to_root-rooted destination
  - test_archive_file_journal_entry: assert state_delta has from_path + to_path
  - test_move_between_roots_journal_entry: assert state_delta carries
    from_root_id, to_root_id, from_path, to_path
  - test_state_delta_keys_match_contract: parametrized over every entry in
    `_STATE_DELTA_KEYS`. For each action, build a minimal scenario that
    exercises the handler once, invoke the engine, and assert
    `set(emitted_entry.state_delta.keys()) >= _STATE_DELTA_KEYS[action]`.
    Locks the state_delta surface against silent drift in future sprints.

tests/engine/test_path_history.py
  - test_path_history_empty_for_static_asset: asset with no filesystem events
    in journal -> empty history list
  - test_path_history_orders_chronologically: journal with 3 mutations on one
    asset -> 3 PathHistoryEntries ordered by logical_time_ns
  - test_path_history_filters_non_filesystem_actions: reencode_video on the
    same asset is excluded
  - test_path_history_includes_slow_copy_pair: both start and commit appear
    as separate entries; start's to_path is the final, temp_path is the temp
  - test_path_history_archive_and_move_between_roots: both action types
    surface with correct from/to paths

tests/contract/test_scenario_v4.py
  - test_archive_file_round_trip: dict payload -> Scenario.model_validate ->
    model_dump matches input
  - test_move_between_roots_round_trip
  - test_archive_file_rejects_to_field: payload with `to:` fails (extra=forbid)
  - test_move_between_roots_requires_both_root_ids
  - test_library_archive_root_optional
  - test_library_archive_root_sentinel_value

tests/materializer/test_filesystem.py  # NEW MODULE
  - one test per dispatch case, with a tmp_path library_root:
      * test_apply_move_asset_renames_file
      * test_apply_rename_file_is_alias_of_move
      * test_apply_delete_file_unlinks
      * test_apply_archive_file_moves_to_archive_root
      * test_apply_archive_file_with_explicit_root
      * test_apply_move_between_roots_crosses_roots
      * test_apply_create_sidecar_writes_srt_and_hashes
      * test_apply_create_sidecar_returns_hash_keyed_by_sidecar_id
      * test_apply_slow_copy_start_writes_full_bytes_to_temp_path
      * test_apply_slow_copy_commit_renames_temp_to_final
      * test_apply_slow_copy_commit_unlinks_initial_when_different_from_final
      * test_apply_unknown_action_raises (defense-in-depth)
      * test_apply_oserror_wraps_into_FilesystemActionError

tests/validation/rules/test_root_unknown.py  # NEW
  - test_move_between_roots_unknown_from_root_id -> E_ROOT_UNKNOWN
  - test_move_between_roots_unknown_to_root_id -> E_ROOT_UNKNOWN
  - test_archive_root_unknown -> E_ROOT_UNKNOWN
  - test_archive_root_sentinel_value_valid
  - test_archive_root_none_valid

tests/validation/rules/test_timeline_lifecycle_sprint6.py
  - test_archive_file_on_unplaced_asset -> E_LIFECYCLE_INVALID
  - test_archive_file_keeps_asset_placed
  - test_move_between_roots_on_unplaced_asset -> E_LIFECYCLE_INVALID
  - test_archive_file_on_pending_slow_copy -> E_LIFECYCLE_INVALID
  - test_move_between_roots_on_pending_slow_copy -> E_LIFECYCLE_INVALID

tests/validation/rules/test_path_containment_sprint6.py
  - test_archive_file_path_synthesis_respects_containment: scenario with
    archive_root pointing at a root path that resolves outside library/ via
    a `..` segment -> E_PATH_CONTAINMENT
  - test_move_between_roots_path_synthesis_respects_containment

tests/validation/rules/test_slow_copy.py  # EXISTING file; add cases
  - test_slow_copy_rejects_temp_equals_final: SlowCopyStartEvent with
    temp_path == to -> E_SLOW_COPY_PATH_COLLISION
  - test_slow_copy_rejects_temp_equals_initial_path: SlowCopyStartEvent
    whose temp_path collides with the asset's initial-state path under
    the <primary_root>/<asset_id>.<container> convention ->
    E_SLOW_COPY_PATH_COLLISION
```

### Layer 3 — Materializer orchestrator unit tests (mocked subprocess)

```
tests/materializer/test_run_sprint6.py
  - run_ffmpeg, probe_file patched at module boundary (synthesis returns a
    canned ProbedMedia; ffmpeg writes 100-byte stub files)
  - test_filesystem_only_timeline_runs_phase_b: identity-move-rename scenario;
    assert library/ contains the moved+renamed file at the final path;
    materialization_report.filesystem_actions has 2 entries; sentinel flipped
    to complete; outcome=success
  - test_reencode_video_rejected_at_preflight: mixed scenario with
    reencode_video event -> E_MATERIALIZE_UNSUPPORTED at preflight, no
    run-dir allocated
  - test_add_file_rejected_at_preflight: scenario with delete_file ->
    add_file on the same asset; preflight rejects with
    E_MATERIALIZE_TIMELINE_UNSUPPORTED, no run-dir allocated. Locks the
    deferral of add_file materialize to Sprint 7.
  - test_phase_b_oserror_aborts_and_cleans_up: monkeypatch the _move_asset
    helper to raise OSError on the third invocation; assert library/ wiped,
    materialization.json present with outcome=fs_failed,
    failures[0].stage=filesystem, failures[0].invocation_index is None,
    exit 5
  - test_phase_a_failure_preempts_phase_b: ffmpeg returns exit 1;
    assert phase B never runs, filesystem_actions=[]
```

### Layer 4 — Real-tool integration tests (skip-if-not-installed)

```
tests/integration/test_materialize_sprint6_real.py
  pytest.mark.skipif(not _ffmpeg_meets_minimum(), reason="ffmpeg >= 7.0")

  - test_identity_move_rename_end_to_end:
      EXIT CRITERION. Runs identity-move-rename.yaml through materialize.
      Asserts:
        * library/movies-hd/Blazar.mkv exists and is the same bytes (sha256)
          as the initial-state file
        * the initial-state path no longer exists
        * manifest.current.locations[0].path == "movies-hd/Blazar.mkv"
        * reports/assets/asset_hd_main.json.path_history has 2 entries
          (move_001, rename_001) in order
        * materialization.json.filesystem_actions has 2 entries
        * journal.jsonl has 2 entries; replay.json applied_events == 2

  - test_slow_copy_real_visibility:
      Runs slow-copy.yaml (existing fixture) — note: current fixture uses
      video.source=noise which Sprint 5 rejects; Sprint 6 must either swap
      the fixture's source to mandelbrot or accept that this test requires
      a Sprint 6 update to the fixture. Asserts:
        * After phase B completes, library/movies-hd/Nova.mkv exists
        * library/movies-hd/Nova.mkv.part does NOT exist (commit cleaned up)
        * manifest.current shows location.path = "movies-hd/Nova.mkv",
          temp_path = None
        * content_hash matches between manifest.current and the file's
          actual sha256

  - test_archive_file_real:
      A new fixture (archive-file.yaml) with library.archive_root unset;
      assert the file ends up at library/<primary_root>/archive/<asset_id>.mkv

  - test_archive_file_real_with_explicit_root:
      Fixture with library.archive_root set to a declared root id;
      assert the file ends up under that root

  - test_move_between_roots_real:
      A new fixture (move-between-roots.yaml) with 2 roots, one move event;
      assert file crosses from first to second

  - test_create_sidecar_real_via_timeline:
      Scenario with a timeline create_sidecar event (not declared on the
      asset's subtitles); assert SRT file exists at the event's to_path and
      manifest.sidecars carries the content_hash

  - test_create_sidecar_collides_with_declared_subtitle:
      Scenario declares one English subtitle on the asset and includes a
      create_sidecar event for the same (asset_id, language) pair. Assert:
      manifest.sidecars contains TWO entries for that (asset_id, language),
      with distinct sidecar_id values and distinct on-disk paths; both
      content_hash values are populated (the declared row from phase A's
      augment_manifest, the timeline row from phase B's
      augment_timeline_sidecars).

  - test_phase_b_failure_cleans_library:
      Hand-crafted scenario where a delete_file targets an asset whose path
      was tampered with between phase A and phase B (simulate via a pytest
      fixture that pre-deletes the file). Assert exit 5, library/ wiped,
      materialization.json present with outcome=fs_failed

  - test_mixed_supported_unsupported_action_rejected:
      Scenario with one move_asset (supported) and one reencode_video
      (unsupported). Assert exit 5 with E_MATERIALIZE_UNSUPPORTED, no
      run-dir allocated.
```

### Layer 5 — CLI integration tests

```
tests/cli/test_materialize_sprint6.py
  - test_materialize_filesystem_timeline_exit_0: mocked detect_capabilities
    and materialize_scenario; assert exit 0, JSON payload shape
  - test_materialize_unsupported_action_exit_5: mock raises
    TimelineUnsupportedError on reencode_video; assert error_code +
    materialization_report_path absent
  - test_materialize_fs_failed_exit_5: mock raises FilesystemActionError;
    assert error_code, asset_id, event_id in stdout,
    materialization_report_path present
```

### Existing-fixture validation

`tests/contract/test_sample_scenarios.py` re-runs after the scenario schema
bump. Every existing fixture under `tests/fixtures/scenarios/` (all seven —
`bundle-sidecars`, `duplicate-variant`, `identity-move-rename`,
`seed-random`, `slow-copy`, `static-library`, `version-evolution`) is updated
to declare `schema_version: 4`. The v3 → v4 bump is purely additive at the
wire format (two new event variants in the discriminated union, one new
optional field on Library), but the `schema_version: Literal[4]` field on
the `Scenario` model rejects the bare integer `3`, so the fixtures themselves
must be edited. The change is a one-line bump per fixture.

### New scenario fixtures

```
tests/fixtures/scenarios/
  archive-file.yaml         # NEW: single asset, archive_file event,
                            # default archive_root (None)
  move-between-roots.yaml   # NEW: 2 roots, one asset, move_between_roots
                            # event from root[0] to root[1]
```

Optional fixture updates:

```
tests/fixtures/scenarios/slow-copy.yaml
  # Update video.source from "noise" (Sprint 6+ still doesn't materialize
  # noise) to "mandelbrot" so the real-tool test can materialize it.
  # If the fixture is preserved unchanged for plan-only purposes, add a
  # second fixture slow-copy-materialize.yaml using mandelbrot.
```

### Out of scope for Sprint 6 tests

- Wall-clock slow_copy partial growth (Sprint 8).
- Media mutation execution (Sprint 7).
- `add_file` in materialize (deferred to Sprint 7 to land alongside add-with-recipe).
- `remove_sidecar` / `update_sidecar` actions (deferred).
- Cross-mode plan-vs-materialize journal equivalence for non-empty timelines
  (Sprint 9's adapter).
- Materialize replay (still stubbed at E_MATERIALIZE_REPLAY_NOT_IMPLEMENTED
  per Sprint 5 spec).
- `step` on materialize fixtures (stays plan-only).

## Exit Criteria

From the source design doc:

- ✅ Identity Move/Rename scenario runs end-to-end on a real directory →
  Layer 4 `test_identity_move_rename_end_to_end`.

Plus additions resolved during brainstorming:

- ✅ Two new scenario actions (`archive_file`, `move_between_roots`) validate
  and execute → Layer 2 + Layer 4.
- ✅ Slow-copy materializes with intermediate temp_path visibility → Layer 4
  `test_slow_copy_real_visibility`.
- ✅ Per-asset `path_history` populates in both plan-only and materialize →
  Layer 2 `test_path_history_*` + Layer 4 (asserted on the materialized
  AssetReport).
- ✅ Mixed timeline (filesystem + media) rejected at preflight → Layer 3
  `test_reencode_video_rejected_at_preflight` + Layer 4
  `test_mixed_supported_unsupported_action_rejected`.
- ✅ Phase-B failure wipes library and writes `materialization.json` →
  Layer 3 + Layer 4.
- ✅ All three schema artifacts in the drift gate validate after `--write`
  (scenario v4, materialization v3, asset-report v3).

## Alternatives Rejected

- **All four new mutations (incl. `remove_sidecar`, `update_sidecar`).**
  The source design doc lists them under Sprint 6, but the Identity
  Move/Rename exit criterion doesn't exercise them, and sidecar mutations
  fit more naturally alongside Sprint 7's media-mutation work (where the
  full sidecar lifecycle including embed/extract lives). Rejected to keep
  Sprint 6 focused on filesystem-level path changes.

- **Wall-clock partial growth for slow_copy.** Anticipates Sprint 8. Adds
  non-trivial timing logic and contradicts the layering the source design
  established (Sprint 6 = filesystem mutations, Sprint 8 = wall-clock).

- **Best-effort revert on phase-B failure.** Would attempt to reverse each
  applied filesystem operation. Rejected because filesystem operations can
  fail mid-way (partial write, mid-`replace`), and revert paths are
  themselves failure-prone. Wiping `library/` keeps the recovery model
  uniform with Sprint 5.

- **`step` extension to materialize fixtures.** Step's journal-replay
  recovery model doesn't re-derive filesystem state; extending it would
  meaningfully expand Sprint 6's scope. Sprint 9's adapter is the first
  real consumer.

- **Materialize replay this sprint.** Sprint 5 deferred this on the
  rationale that the canonicalizer has no real consumer until Sprint 9.
  Filesystem mutations now exercise the journal canonicalization path
  through plan-vs-materialize tests; that's the meaningful gain. Adding
  full replay support without a consumer risks two reworks.

- **Synthesize `to:` for `move_between_roots` at engine time, leave
  `to:` field on the event.** Would mirror `move_asset`'s shape. Rejected
  because the explicit `from_root_id`/`to_root_id` makes scenarios
  self-documenting and lets the validator check root membership without
  parsing path prefixes.

- **`Outcome.FS_FAILED` repurposing `TOOL_FAILED`.** Would avoid an enum
  member. Rejected because phase-B failures carry no `ToolInvocation` and
  inflating "tool failed" semantics to include them would mislead the
  Sprint 9 adapter and any human reading the report.

- **Materialize `add_file` with a zero-byte payload.** Would let Sprint 6
  cover all currently-engineered timeline actions. Rejected because phase
  A populates `ManifestVersion.content_hash` from the originally-synthesized
  bytes, so writing `b""` at phase B leaves the hash stale. Re-hash plus
  re-probe is viable but introduces a second probe path outside the phase-A
  synthesis loop. Deferring `add_file` materialize to Sprint 7 (where
  recipe-driven byte synthesis lands) is the cleaner cut; the lifecycle
  rule already makes `add_file` reachable only after `delete_file` on the
  same asset, so existing plan-only scenarios continue to work unchanged
  and Sprint 6's preflight rejects `add_file` with the existing
  `E_MATERIALIZE_TIMELINE_UNSUPPORTED` code.

## Open Questions

None. All design decisions were resolved during brainstorming.
