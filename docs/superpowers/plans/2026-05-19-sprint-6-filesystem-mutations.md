# Sprint 6 — Filesystem Mutations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lift the Sprint 5 static-only timeline gate. Ship engine handlers, validation rules, and a materializer phase-B dispatcher for eight filesystem timeline actions (`move_asset`, `rename_file`, `delete_file`, `create_sidecar`, `slow_copy_start`, `slow_copy_commit`, `archive_file`, `move_between_roots`) so `chaos-librarian materialize` runs the Identity Move/Rename scenario end-to-end on a real directory.

**Architecture:** Engine stays pure plan-only (no `Path` I/O). A new `materializer/filesystem.py` module owns phase-B disk effects. Composition is one-directional: materializer imports engine, never the reverse — same as Sprint 5. Phase B walks the journal and dispatches each entry to a per-action helper; the dispatcher's `_PhaseBContext` carries incremental state (`pending_slow_copy`, `phase_b_sidecar_hashes`) and a read-only `scenario_assets` lookup. Each helper reads its source path from `entry.state_delta` rather than from any cached path-tracking map. On any `OSError`, the run aborts, `library/` is wiped, and `materialization.json` records `outcome=fs_failed`.

**Tech Stack:** Python 3.13, Pydantic v2, Typer (existing CLI shell), Sprint 1 validation pipeline, Sprint 2 determinism, Sprint 3 engine, Sprint 4 reports, Sprint 5 materializer. No new runtime dependencies.

**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md) — §"Sprint 6", §"Mutation Model", §"Filesystem Safety", §"Materialize Mode", §"Schema Contract".

**Design doc:** [`docs/superpowers/specs/2026-05-19-sprint-6-design.md`](../specs/2026-05-19-sprint-6-design.md) — load-bearing for every task; revised after the `/challenge` adversarial review (commit `2b15812 docs(sprint-6): address adversarial-review findings 1-4`). Read it before starting any task; do not deviate from its decisions silently.

**Branch:** `feat/sprint-6` (already exists; tip is `2b15812`).

---

## Open Design Decisions Baked Into This Plan

These resolve gaps the spec deliberately left for the implementer. Push back via PR comment if you disagree before merging.

1. **Test-file naming.** The spec mentions `test_events_sprint6.py`, `test_run_sprint6.py`, etc. The existing convention splits engine tests by action family (`test_events_filesystem.py`, `test_events_media.py`, `test_events_slow_copy.py`) — Sprint 6 follows the family convention, not the sprint-suffix convention:
   - `archive_file` + `move_between_roots` handler tests → extend `tests/engine/test_events_filesystem.py`.
   - `_STATE_DELTA_KEYS` drift-lock test → new file `tests/engine/test_state_delta_contract.py` (cross-cuts every handler family).
   - Materializer orchestrator tests → extend `tests/materializer/test_run.py`.
   - Materializer filesystem helper tests → new file `tests/materializer/test_filesystem.py`.
   - `derive_path_history` tests → new file `tests/engine/test_path_history.py`.
   - Validation rule additions → extend existing `tests/validation/rules/test_slow_copy.py`, `test_target_unknown.py`, `test_timeline_lifecycle.py`, `test_path_containment.py` (one file per rule, matching the source layout).
   - New file `tests/validation/rules/test_root_unknown.py` is NOT created — `E_ROOT_UNKNOWN` lives in `rules/target_unknown.py`; its tests go in `tests/validation/rules/test_target_unknown.py`.

2. **`E_ROOT_UNKNOWN` rule placement.** The spec leaves this as an implementation detail. Extend the existing `rules/target_unknown.py` and reuse its `iter_asset_ids`-style helper for root-id lookup. Keeps the rule count at 12 instead of 13.

3. **`E_SLOW_COPY_PATH_COLLISION` rule placement.** Extend the existing `rules/slow_copy.py`; add a new public function `rule_slow_copy_path_collision` alongside `rule_slow_copy_unpaired` and `rule_slow_copy_timing`.

4. **`WorldState._archive_path_template` shape.** A Python `str.format`-able template with placeholders `{asset_id}` and `{container}`, populated once in `build_initial_state` and consumed by `archive_path_for(asset_id)`. Example value: `"library/movies-hd/archive/{asset_id}.{container}"`.

5. **`INITIAL_PATH_TEMPLATE` placement.** Lifted to `src/chaos_librarian/contract/paths.py` as a module-level `Final[str]` constant. Both `engine/state.py` and `validation/rules/slow_copy.py` import from `contract.paths`. Lives in `contract/` (not `engine/`) to preserve the validation→contract→errors-only layering; no existing validation rule imports from `chaos_librarian.engine`. Format: `"{root_path}/{asset_id}.{container}"`.

6. **`_STATE_DELTA_KEYS` placement.** A module-level `Final[dict[TimelineActionName, frozenset[str]]]` in `src/chaos_librarian/engine/events.py`. `add_file` is intentionally absent; Sprint 7 will add its entry when the materialize-side helper lands.

7. **`augment_timeline_sidecars` placement.** New public function in `src/chaos_librarian/materializer/manifest_build.py` alongside the existing `augment_manifest`. Signature: `augment_timeline_sidecars(manifest: Manifest, phase_b_sidecar_hashes: Mapping[str, str]) -> None` — mutates `manifest.sidecars` in place to mirror `augment_manifest`'s side-effecting style.

   But: `Manifest` is `frozen=True` per `contract/manifest.py`. Confirm before implementing — if frozen, `augment_timeline_sidecars` must return a new `Manifest` (functional style) and `run.py` must rebind. Looking at the existing `augment_manifest`, this is already how it works: it accepts and mutates an internal mutable representation, not the frozen Manifest model. Follow the same pattern.

8. **Per-action helper signatures in `filesystem.py`.** Each helper takes `(ctx: _PhaseBContext, entry: JournalEntry) -> FilesystemAction` per the design spec. `duration_ns` is filled by `_dispatch_one`, not the helper itself (the helper returns `duration_ns=0` and the dispatcher does `model_copy(update={...})`).

9. **`FilesystemActionError.payload`.** Includes `event_id`, `action.value`, and `errno` (from `OSError.errno`). The CLI handler reads these into the stdout JSON via the existing `error_code` / `asset_id` / `field` / `payload` contract.

10. **Failure cleanup uses `shutil.rmtree`, not iterative unlink.** Wipes `library/` entirely; matches Sprint 5's `finalize_failure` semantic. `library/` is recreated from scratch on the next materialize.

11. **Fixture `schema_version: 4` bump is mechanical.** Every existing fixture file (`bundle-sidecars`, `duplicate-variant`, `identity-move-rename`, `seed-random`, `slow-copy`, `static-library`, `version-evolution`) gains a one-line bump. The `invalid/` corpus is untouched (those fixtures already trigger errors before the `schema_version` literal check).

12. **`slow-copy.yaml` fixture stays at `video.source: noise`.** Sprint 6 does NOT change the existing fixture's source. The Layer 4 `test_slow_copy_real_visibility` test creates a NEW fixture `slow-copy-materialize.yaml` with `mandelbrot` for the real-tool run. The plan-only `slow-copy.yaml` corpus keeps its existing semantics.

13. **No new error code constant `E_MATERIALIZE_FS_FAILED` in `validation/codes.py`.** It's a materializer error, so it lives only on the `FilesystemActionError` class attribute (mirroring how `E_MATERIALIZE_TOOL_FAILED` is class-side only).

14. **Commit cadence.** One commit per task (the final step of every task). Use the project's commit-message style (`feat(contract):`, `feat(engine):`, `test(validation):`, etc.). Each commit ends with the standard `Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>` trailer.

---

## File Structure

### To create

```
src/chaos_librarian/engine/path_history.py
  derive_path_history(asset_id, journal) -> list[PathHistoryEntry]

src/chaos_librarian/materializer/filesystem.py
  apply_phase_b(library_root, journal, scenario, resolved_seed)
    -> tuple[list[FilesystemAction], dict[str, str]]
  _PhaseBContext, _PendingSlowCopy, _DISPATCH, per-action helpers
  Returns (filesystem_actions, phase_b_sidecar_hashes).

tests/engine/test_state_delta_contract.py
  Parametrized lock test for _STATE_DELTA_KEYS.

tests/engine/test_path_history.py
  Pure-projection tests for derive_path_history.

tests/materializer/test_filesystem.py
  Per-action helper tests with tmp_path library_root.

tests/integration/test_materialize_sprint6_real.py
  Layer 4 real-tool integration tests (skip-if-not-installed).

tests/cli/test_materialize_sprint6.py
  Layer 5 CLI integration tests (mocked orchestrator).

tests/fixtures/scenarios/archive-file.yaml
tests/fixtures/scenarios/move-between-roots.yaml
tests/fixtures/scenarios/slow-copy-materialize.yaml
```

### To modify

```
src/chaos_librarian/contract/__init__.py
  Bump SCENARIO_SCHEMA_VERSION 3 -> 4
  Bump MATERIALIZATION_SCHEMA_VERSION 2 -> 3
  Bump ASSET_REPORT_SCHEMA_VERSION 2 -> 3

src/chaos_librarian/contract/scenario.py
  + TimelineActionName.ARCHIVE_FILE, .MOVE_BETWEEN_ROOTS
  + ArchiveFileEvent, MoveBetweenRootsEvent variants
  + Library.archive_root: str | None = None
  Scenario.schema_version: Literal[4]

src/chaos_librarian/contract/reports.py
  + PathHistoryEntry model
  + AssetReport.path_history field
  AssetReport.schema_version: Literal[3]

src/chaos_librarian/contract/materialization.py
  + FilesystemAction model
  + Outcome.FS_FAILED, FailureStage.FILESYSTEM
  + MaterializationReport.filesystem_actions field
  MaterializationReport.schema_version: Literal[3]

src/chaos_librarian/engine/events.py
  + _STATE_DELTA_KEYS module-level constant
  + _handle_archive_file, _handle_move_between_roots
  + _HANDLERS entries for both
  _handle_create_sidecar: add state_delta["language"]
  _handle_slow_copy_start: add state_delta["initial_path_at_start"]

src/chaos_librarian/contract/paths.py
  + INITIAL_PATH_TEMPLATE module-level constant

src/chaos_librarian/engine/state.py
  imports INITIAL_PATH_TEMPLATE from contract.paths (new home; see
    Open Design Decision 5)
  + WorldState._root_paths, ._archive_path_template
  + WorldState.root_path_for, .archive_path_for helpers
  build_initial_state populates _root_paths and _archive_path_template

src/chaos_librarian/engine/reports.py
  AssetReport builder calls derive_path_history per asset

src/chaos_librarian/materializer/errors.py
  + FilesystemActionError(MaterializationError) with error_code E_MATERIALIZE_FS_FAILED

src/chaos_librarian/materializer/preflight.py
  + SUPPORTED_S6_ACTIONS frozenset
  + preflight_timeline(scenario) function

src/chaos_librarian/materializer/manifest_build.py
  + augment_timeline_sidecars(manifest, phase_b_sidecar_hashes)

src/chaos_librarian/materializer/run.py
  Remove TimelineUnsupportedError gate for non-empty timelines
  Add preflight_timeline call before phase A
  Add phase B dispatcher after phase A
  Add augment_timeline_sidecars call after phase B
  On FilesystemActionError: shutil.rmtree library/ + outcome=fs_failed

src/chaos_librarian/materializer/finalize.py
  Thread filesystem_actions through MaterializationReport build

src/chaos_librarian/cli/app.py
  Materialize command: catch FilesystemActionError, format as JSON, exit 5

src/chaos_librarian/validation/codes.py
  + E_ROOT_UNKNOWN constant
  + E_SLOW_COPY_PATH_COLLISION constant

src/chaos_librarian/validation/rules/target_unknown.py
  + rule_root_unknown — validates from_root_id / to_root_id / archive_root

src/chaos_librarian/validation/rules/slow_copy.py
  + rule_slow_copy_path_collision — rejects temp == initial / temp == final

src/chaos_librarian/validation/rules/timeline_lifecycle.py
  Extend _LOCATION_DEPENDENT_PASSTHROUGH with ARCHIVE_FILE + MOVE_BETWEEN_ROOTS
  Add _PATH_MUTATING_PASSTHROUGH check (pending slow_copy guard)

src/chaos_librarian/validation/rules/path_containment.py
  Synthesize to_path for archive_file + move_between_roots events

src/chaos_librarian/validation/pipeline.py
  Register rule_root_unknown and rule_slow_copy_path_collision in the
  pipeline's rule list (the exact registration site is at the bottom
  of pipeline.py — `_SEMANTIC_RULES` or similar).

src/chaos_librarian/schema_export.py
  Schema regeneration (run, don't edit) — no logic changes expected;
  the TypeAdapter wrap-up already handles new variants in oneOf.

schemas/scenario.schema.json          # REGEN to v4
schemas/asset-report.schema.json      # REGEN to v3
schemas/materialization.schema.json   # REGEN to v3

tests/fixtures/scenarios/bundle-sidecars.yaml
tests/fixtures/scenarios/duplicate-variant.yaml
tests/fixtures/scenarios/identity-move-rename.yaml
tests/fixtures/scenarios/seed-random.yaml
tests/fixtures/scenarios/slow-copy.yaml
tests/fixtures/scenarios/static-library.yaml
tests/fixtures/scenarios/version-evolution.yaml
  Bump schema_version: 3 -> 4 (one-line each).
```

---

## Test Helpers Reference

Every task below references one or more shared test helpers. This section lists each helper's signature, its module, and a one-line description so individual tasks don't have to redefine them. Before starting any task, verify which helpers exist (grep in `tests/`) and which need to be created — each task's "Files" section notes whether the helper is new or pre-existing.

#### Engine-side test helpers (in `tests/engine/conftest.py`, new file unless noted)

- `_build_minimal_scenario(*, roots, works, archive_root=None) -> Scenario` — assembles a `Scenario` v4 with the named library roots and one asset per work entry. Defined in Task 4.
- `_resolve_one(scenario, event_id) -> ResolvedEvent` — replays `engine.resolution.resolve_one` for a single timeline event.
- `_resolve_archive_file(scenario, *, event_id, target) -> ResolvedEvent` — convenience wrapper that injects an `ArchiveFileEvent` into a scenario's timeline and resolves it. Defined in Task 6.
- `_resolve_move_between_roots(scenario, *, event_id, target, from_root_id, to_root_id) -> ResolvedEvent` — same shape for `MoveBetweenRootsEvent`. Defined in Task 7.
- `_minimal_scenario_for_action(action: TimelineActionName) -> tuple[Scenario, WorldState, ResolvedEvent]` — per-action minimal-scenario builder consumed by the `_STATE_DELTA_KEYS` lock test. Returns a pre-advanced `WorldState` for actions that need a prerequisite (e.g. `slow_copy_commit` needs its matching `slow_copy_start` already applied). Defined in Task 5 (full code, not stub).

#### Materializer-side test helpers (in `tests/materializer/conftest.py`)

- `_atomic_entry(*, event_id, action, target, state_delta) -> AtomicJournalEntry` — typed journal entry builder for phase-B helper tests. Defined in Task 17.
- `_validated_entry(payload: dict) -> JournalEntry` — runs a raw dict through the journal `TypeAdapter`. Used by Task 13's `derive_path_history` tests.
- `_mock_ffmpeg(monkeypatch, *, stub_bytes: bytes)` — patches the `ffmpeg` subprocess call to write `stub_bytes` and return success. Already exists from Sprint 5; verify the actual name with `rg 'def .*mock_ffmpeg' tests/materializer/`.
- `_mock_probe(monkeypatch)` — same, for `ffprobe`.

#### Integration-test helpers (in `tests/integration/conftest.py`, extend the existing Sprint 5 file)

- `sha256_of(path: Path) -> str` — already exists per Sprint 5 integration tests.
- `_initial_sha256_for(asset_id: str, out_dir: Path) -> str` — reads `materialization.json`, finds the `MaterializedAsset` with the matching `asset_id`, and returns its `content_hash`. NEW in Sprint 6 (Task 21).
- `_load_current_manifest(out_dir: Path) -> Manifest` — already exists per Sprint 5.
- `_load_asset_report(out_dir: Path, asset_id: str) -> AssetReport` — already exists per Sprint 5.
- `_load_materialization_report(out_dir: Path) -> MaterializationReport` — already exists per Sprint 5.
- `_load_replay_bundle(out_dir: Path) -> ReplayBundle` — already exists per Sprint 5.

---

## Task 1: Scenario Contract — v4 bump, new actions, new events, archive_root, fixture migration

**Why first:** every downstream task imports `TimelineActionName.ARCHIVE_FILE` or `MoveBetweenRootsEvent`. The schema drift gate fails until both fixtures and JSON Schema are regenerated, so do all of this in one commit.

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py:16` — bump constant.
- Modify: `src/chaos_librarian/contract/scenario.py:15-33,94-96,205-213,235-246,252-262` — new enum members, Library field, two new event variants, union extension, schema_version literal.
- Modify (one line each): `tests/fixtures/scenarios/{bundle-sidecars,duplicate-variant,identity-move-rename,seed-random,slow-copy,static-library,version-evolution}.yaml`.
- Test: `tests/contract/test_scenario.py` (extend) — round-trip + rejection tests for the two new event variants and `Library.archive_root`.
- Test: `tests/contract/test_contract_constants.py` (extend) — assert the bumped constant.
- Regenerate: `schemas/scenario.schema.json`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/contract/test_scenario.py` (append to the existing file; match its style):

```python
def test_archive_file_event_round_trip():
    payload = {
        "id": "ev_arch_001",
        "at": "0ns",
        "action": "archive_file",
        "target": "asset_hd_main",
    }
    event = ArchiveFileEvent.model_validate(payload)
    assert event.target == "asset_hd_main"
    assert event.action == TimelineActionName.ARCHIVE_FILE
    assert event.model_dump(mode="json")["action"] == "archive_file"


def test_archive_file_event_rejects_to_field():
    payload = {
        "id": "ev_arch_001",
        "at": "0ns",
        "action": "archive_file",
        "target": "asset_hd_main",
        "to": "movies-hd/archive/asset_hd_main.mkv",
    }
    with pytest.raises(ValidationError) as exc_info:
        ArchiveFileEvent.model_validate(payload)
    assert any(err["type"] == "extra_forbidden" for err in exc_info.value.errors())


def test_move_between_roots_event_round_trip():
    payload = {
        "id": "ev_mbr_001",
        "at": "0ns",
        "action": "move_between_roots",
        "target": "asset_hd_main",
        "from_root_id": "movies-hd",
        "to_root_id": "movies-archive",
    }
    event = MoveBetweenRootsEvent.model_validate(payload)
    assert event.from_root_id == "movies-hd"
    assert event.to_root_id == "movies-archive"


def test_move_between_roots_requires_both_root_ids():
    payload = {
        "id": "ev_mbr_001",
        "at": "0ns",
        "action": "move_between_roots",
        "target": "asset_hd_main",
        "from_root_id": "movies-hd",
    }
    with pytest.raises(ValidationError) as exc_info:
        MoveBetweenRootsEvent.model_validate(payload)
    assert any(
        err["type"] == "missing" and err["loc"] == ("to_root_id",)
        for err in exc_info.value.errors()
    )


def test_library_archive_root_defaults_to_none():
    library = Library(roots=(LibraryRoot(id="movies-hd", path="library/movies-hd"),))
    assert library.archive_root is None


def test_library_archive_root_accepts_sentinel_string():
    library = Library(
        roots=(LibraryRoot(id="movies-hd", path="library/movies-hd"),),
        archive_root="archive",
    )
    assert library.archive_root == "archive"


def test_library_archive_root_accepts_real_root_id():
    library = Library(
        roots=(
            LibraryRoot(id="movies-hd", path="library/movies-hd"),
            LibraryRoot(id="staging", path="library/staging"),
        ),
        archive_root="staging",
    )
    assert library.archive_root == "staging"


def test_scenario_v4_round_trip_with_new_events():
    payload = {
        "schema_version": 4,
        "scenario_id": "sc_arch_001",
        "seed": 42,
        "duration_scale": "short",
        "library": {
            "roots": [{"id": "movies-hd", "path": "library/movies-hd"}],
            "archive_root": None,
        },
        "works": [],
        "timeline": [
            {
                "id": "ev_arch_001",
                "at": "0ns",
                "action": "archive_file",
                "target": "asset_hd_main",
            },
        ],
    }
    scenario = Scenario.model_validate(payload)
    assert scenario.schema_version == 4
    assert scenario.timeline[0].action == TimelineActionName.ARCHIVE_FILE
```

Add imports at the top of `tests/contract/test_scenario.py` as needed: `ArchiveFileEvent`, `MoveBetweenRootsEvent`, `Library`, `LibraryRoot`.

Add to `tests/contract/test_contract_constants.py`:

```python
def test_scenario_schema_version_bumped_to_4():
    assert chaos_librarian.contract.SCENARIO_SCHEMA_VERSION == 4
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/contract/test_scenario.py tests/contract/test_contract_constants.py -v`

Expected: failures referencing missing names (`ArchiveFileEvent`, `MoveBetweenRootsEvent`, `Library.archive_root`) and wrong constant value.

- [ ] **Step 3: Bump the schema version constant**

In `src/chaos_librarian/contract/__init__.py`:

```python
SCENARIO_SCHEMA_VERSION: Final = 4
```

- [ ] **Step 4: Add the two new enum members + Library field**

In `src/chaos_librarian/contract/scenario.py`, extend `TimelineActionName`:

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
```

Extend `Library`:

```python
class Library(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    roots: tuple[LibraryRoot, ...]
    archive_root: str | None = None
```

- [ ] **Step 5: Add the two new event variants and extend the discriminated union**

Below `SlowCopyCommitEvent` in `src/chaos_librarian/contract/scenario.py`:

```python
class ArchiveFileEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.ARCHIVE_FILE] = TimelineActionName.ARCHIVE_FILE
    target: str


class MoveBetweenRootsEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.MOVE_BETWEEN_ROOTS] = (
        TimelineActionName.MOVE_BETWEEN_ROOTS
    )
    target: str
    from_root_id: str
    to_root_id: str
```

Extend the `TimelineEvent` union:

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
    | MoveBetweenRootsEvent,
    Field(discriminator="action"),
]
```

Bump `Scenario.schema_version`:

```python
class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)
    schema_version: Literal[4]
    # ... rest unchanged
```

- [ ] **Step 6: Bump every existing fixture's `schema_version`**

For each file in `tests/fixtures/scenarios/{bundle-sidecars,duplicate-variant,identity-move-rename,seed-random,slow-copy,static-library,version-evolution}.yaml`, change the first non-comment line from:

```yaml
schema_version: 3
```

to:

```yaml
schema_version: 4
```

Verify with: `rg 'schema_version: 3' tests/fixtures/scenarios/` (should return zero hits outside the `invalid/` subdirectory; invalid fixtures with deliberately-wrong shapes can stay at 3 if they don't trip the Literal check before their target rule fires — re-verify after Step 7).

- [ ] **Step 7: Regenerate the scenario schema**

Run: `uv run python -m chaos_librarian.schema_export --write`

Verify the diff: `git diff schemas/scenario.schema.json` should show the two new event variants in the `oneOf`, the new `archive_root` field on `Library`, and `schema_version` enum widened to `4`.

- [ ] **Step 8: Run the full test suite to catch fixture or invalid-corpus regressions**

Run: `uv run pytest -q`

Expected: All contract tests pass. The `invalid/` corpus may surface new failures if any invalid fixture's first error was the schema_version literal check (now version 4) and the fixture file still says `schema_version: 3`. Fix by bumping those fixtures too — `# expected: E_FIELD_LITERAL` fixtures that DELIBERATELY use wrong schema_version should keep their value; others should be bumped.

Walk through any failures one by one; do not skip.

- [ ] **Step 9: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

Fix any failures.

- [ ] **Step 10: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/scenario.py \
        schemas/scenario.schema.json \
        tests/fixtures/scenarios/*.yaml \
        tests/contract/test_scenario.py \
        tests/contract/test_contract_constants.py
git commit -m "$(cat <<'EOF'
feat(contract): scenario v4 — add archive_file, move_between_roots, Library.archive_root

Add two new TimelineActionName variants (ARCHIVE_FILE, MOVE_BETWEEN_ROOTS) and
their event types to the discriminated union. Library gains an optional
archive_root field naming the root that archive_file targets. Existing fixtures
bump schema_version 3 -> 4 (purely additive at the wire format).

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: AssetReport Contract — v3 bump, PathHistoryEntry, path_history field

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py:23` — bump constant.
- Modify: `src/chaos_librarian/contract/reports.py` — new `PathHistoryEntry` model + `AssetReport.path_history` field + `Literal[3]`.
- Test: `tests/contract/test_reports.py` (extend) — round-trip + default tests.
- Test: `tests/contract/test_contract_constants.py` (extend) — assert the bumped constant.
- Regenerate: `schemas/asset-report.schema.json`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/contract/test_reports.py`:

```python
def test_path_history_entry_round_trip():
    payload = {
        "event_id": "ev_move_001",
        "action": "move_asset",
        "logical_time_ns": 1_000_000_000,
        "from_path": "movies-hd/old.mkv",
        "to_path": "movies-hd/new.mkv",
        "temp_path": None,
    }
    entry = PathHistoryEntry.model_validate(payload)
    assert entry.from_path == "movies-hd/old.mkv"
    assert entry.to_path == "movies-hd/new.mkv"
    assert entry.temp_path is None
    assert entry.action == TimelineActionName.MOVE_ASSET


def test_asset_report_path_history_defaults_to_empty_list():
    payload = {
        "schema_version": 3,
        "asset_id": "asset_hd_main",
        "initial": {
            "location_path": "movies-hd/asset_hd_main.mkv",
            "version_id": "version_0001",
            "version_index": 0,
        },
        "history": [],
        "current": {
            "location_path": "movies-hd/asset_hd_main.mkv",
            "version_id": "version_0001",
            "version_index": 0,
        },
    }
    report = AssetReport.model_validate(payload)
    assert report.path_history == []


def test_asset_report_v3_round_trip_with_path_history():
    payload = {
        "schema_version": 3,
        "asset_id": "asset_hd_main",
        "initial": {
            "location_path": "movies-hd/asset_hd_main.mkv",
            "version_id": "version_0001",
            "version_index": 0,
        },
        "history": [],
        "current": None,
        "path_history": [
            {
                "event_id": "ev_delete_001",
                "action": "delete_file",
                "logical_time_ns": 1_000_000_000,
                "from_path": "movies-hd/asset_hd_main.mkv",
                "to_path": None,
                "temp_path": None,
            }
        ],
    }
    report = AssetReport.model_validate(payload)
    assert len(report.path_history) == 1
    assert report.path_history[0].action == TimelineActionName.DELETE_FILE
```

Add to `tests/contract/test_contract_constants.py`:

```python
def test_asset_report_schema_version_bumped_to_3():
    assert chaos_librarian.contract.ASSET_REPORT_SCHEMA_VERSION == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/contract/test_reports.py tests/contract/test_contract_constants.py -v`

Expected: `PathHistoryEntry` undefined, `path_history` missing on AssetReport, schema_version literal mismatch.

- [ ] **Step 3: Bump the constant**

In `src/chaos_librarian/contract/__init__.py`:

```python
ASSET_REPORT_SCHEMA_VERSION: Final = 3
```

- [ ] **Step 4: Add the PathHistoryEntry model + path_history field**

In `src/chaos_librarian/contract/reports.py`, before `AssetReport` (and after `AssetHistoryEntry`):

```python
from chaos_librarian.contract.scenario import TimelineActionName


class PathHistoryEntry(BaseModel):
    """One filesystem-affecting event projected for a single asset.

    Derived from the journal by ``derive_path_history``. Mirrors the
    verbatim ``AssetHistoryEntry`` but flattens the path-bearing
    ``state_delta`` keys into typed ``str | None`` fields so external
    consumers (voom-v2 adapter) can read them without parsing dicts.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: TimelineActionName
    logical_time_ns: int
    from_path: str | None = None
    to_path: str | None = None
    temp_path: str | None = None
```

Bump `AssetReport`:

```python
class AssetReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3]
    asset_id: str
    initial: AssetSnapshot
    history: list[AssetHistoryEntry] = Field(default_factory=list)
    current: AssetSnapshot | None
    path_history: list[PathHistoryEntry] = Field(default_factory=list)
```

- [ ] **Step 5: Regenerate the asset-report schema**

Run: `uv run python -m chaos_librarian.schema_export --write`

Verify: `git diff schemas/asset-report.schema.json` shows `PathHistoryEntry` in `$defs`, `path_history` on the top-level object, and `schema_version` enum value `3`.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/contract/ -v`

Expected: all pass. If any non-extended tests break, check whether they hardcode `schema_version: 2` literals.

- [ ] **Step 7: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/reports.py \
        schemas/asset-report.schema.json \
        tests/contract/test_reports.py \
        tests/contract/test_contract_constants.py
git commit -m "$(cat <<'EOF'
feat(contract): asset-report v3 — add PathHistoryEntry and path_history

Typed projection of the filesystem-affecting journal subset per asset. Lives
alongside the verbatim ``history`` field; consumers (voom-v2 adapter) read
from_path / to_path / temp_path as ``str | None`` without parsing state_delta
dicts.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: MaterializationReport Contract — v3 bump, FilesystemAction, enum extensions

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py:21` — bump constant.
- Modify: `src/chaos_librarian/contract/materialization.py` — new model + enum members + field + `Literal[3]`.
- Test: `tests/contract/test_materialization.py` (extend, or create if missing — check first).
- Test: `tests/contract/test_contract_constants.py` (extend).
- Regenerate: `schemas/materialization.schema.json`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/contract/test_materialization.py` (create if it doesn't exist; match other test_*.py file style):

```python
def test_filesystem_action_round_trip():
    payload = {
        "event_id": "ev_move_001",
        "action": "move_asset",
        "target_asset_id": "asset_hd_main",
        "from_path": "movies-hd/old.mkv",
        "to_path": "movies-hd/new.mkv",
        "temp_path": None,
        "duration_ns": 1_500_000,
    }
    action = FilesystemAction.model_validate(payload)
    assert action.action == TimelineActionName.MOVE_ASSET
    assert action.duration_ns == 1_500_000


def test_outcome_fs_failed_present():
    assert Outcome("fs_failed") is Outcome.FS_FAILED


def test_failure_stage_filesystem_present():
    assert FailureStage("filesystem") is FailureStage.FILESYSTEM


def test_materialization_report_filesystem_actions_defaults_to_empty():
    payload = {
        "schema_version": 3,
        "run_id": "1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01",
        "outcome": "success",
        "platform": "darwin",
        "started_at": "2026-05-19T00:00:00Z",
        "finished_at": "2026-05-19T00:00:01Z",
        "toolchain": {},
        "invocations": [],
        "materialized": [],
        "failures": [],
    }
    report = MaterializationReport.model_validate(payload)
    assert report.filesystem_actions == []
```

Add to `tests/contract/test_contract_constants.py`:

```python
def test_materialization_schema_version_bumped_to_3():
    assert chaos_librarian.contract.MATERIALIZATION_SCHEMA_VERSION == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/contract/test_materialization.py tests/contract/test_contract_constants.py -v`

Expected: `FilesystemAction`/`Outcome.FS_FAILED`/`FailureStage.FILESYSTEM` undefined; schema_version literal mismatch.

- [ ] **Step 3: Bump constant**

In `src/chaos_librarian/contract/__init__.py`:

```python
MATERIALIZATION_SCHEMA_VERSION: Final = 3
```

- [ ] **Step 4: Add FilesystemAction, enum members, filesystem_actions field**

In `src/chaos_librarian/contract/materialization.py`, add at the top of imports:

```python
from chaos_librarian.contract.scenario import TimelineActionName
```

Extend `Outcome`:

```python
class Outcome(enum.StrEnum):
    SUCCESS = "success"
    UNSUPPORTED = "unsupported"
    TOOL_FAILED = "tool_failed"
    TOOL_MISSING = "tool_missing"
    CONTAINMENT_VIOLATION = "containment_violation"
    FS_FAILED = "fs_failed"
```

Extend `FailureStage`:

```python
class FailureStage(enum.StrEnum):
    FFMPEG = "ffmpeg"
    FFPROBE = "ffprobe"
    FILESYSTEM = "filesystem"
```

Before `MaterializationReport`, add the new model:

```python
class FilesystemAction(BaseModel):
    """One phase-B filesystem operation audit record.

    Mirrors ``ToolInvocation``'s role for subprocesses: one record per
    journal entry that produced a real disk change.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: TimelineActionName
    target_asset_id: str
    from_path: str | None = None
    to_path: str | None = None
    temp_path: str | None = None
    duration_ns: int
```

Update `MaterializationReport`:

```python
class MaterializationReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3]
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
```

- [ ] **Step 5: Regenerate the materialization schema**

Run: `uv run python -m chaos_librarian.schema_export --write`

Verify the diff shows `FilesystemAction` in `$defs`, the two new enum values, the new `filesystem_actions` array, and `schema_version: 3`.

- [ ] **Step 5b: Sweep in-code construction sites**

Run `rg -n 'MaterializationReport\(' src/ tests/` to find every construction. Bump `schema_version=2` → `schema_version=3` at each site so this task lands a green build (no skip-and-defer). Same for any `Outcome(...)` / `FailureStage(...)` literal references that need updating (none are expected, but verify with a quick `rg` for each). Likely site: `src/chaos_librarian/materializer/finalize.py`, and any test factories under `tests/materializer/conftest.py` if present.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/contract/ tests/materializer/ -v`

Expected: pass (all sites bumped in Step 5b). If any test still fails because a construction site emits `schema_version=2`, the sweep missed it — DO NOT skip silently; find and bump it.

- [ ] **Step 7: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/materialization.py \
        schemas/materialization.schema.json \
        tests/contract/test_materialization.py \
        tests/contract/test_contract_constants.py
# also add any source files touched by Step 5b's construction-site sweep
# (likely src/chaos_librarian/materializer/finalize.py and possibly
# tests/materializer/conftest.py)
git commit -m "$(cat <<'EOF'
feat(contract): materialization v3 — add FilesystemAction, fs_failed outcome

Add per-phase-B-operation audit records to MaterializationReport. Outcome
gains FS_FAILED for phase-B exceptions; FailureStage gains FILESYSTEM so
MaterializationFailure can locate phase-B failures.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: contract `paths.py` constant + engine `state.py` root_paths / archive_path_template

**Why before handlers:** the new engine handlers in Tasks 6-7 call `state.root_path_for` and `state.archive_path_for`. Land the state extensions and refactor `build_initial_state` first so those tasks add handlers without simultaneously growing the state contract.

**Files:**
- Modify: `src/chaos_librarian/contract/paths.py` — add `INITIAL_PATH_TEMPLATE` constant (lives in `contract/`, not `engine/`, so the slow-copy validation rule can import it without inverting the validation→contract→errors layering; see Open Design Decision 5).
- Modify: `src/chaos_librarian/engine/state.py` — import `INITIAL_PATH_TEMPLATE` from `contract.paths`; extend `WorldState` with `_root_paths`, `_archive_path_template`, `root_path_for`, `archive_path_for`; populate them in `build_initial_state`.
- Test: `tests/engine/test_state.py` — extend with helpers + archive_root resolution tests.

- [ ] **Step 1: Write the failing tests**

Add to `tests/engine/test_state.py`:

```python
def test_world_state_root_path_for_returns_declared_path():
    scenario = _build_minimal_scenario(
        roots=[("movies-hd", "library/movies-hd"), ("staging", "library/staging")],
        works=[("work_001", "asset_hd_main", "mkv")],
    )
    state = build_initial_state(scenario, IdAllocator())
    assert state.root_path_for("movies-hd") == "library/movies-hd"
    assert state.root_path_for("staging") == "library/staging"


def test_world_state_archive_path_for_default_root():
    scenario = _build_minimal_scenario(
        roots=[("movies-hd", "library/movies-hd")],
        works=[("work_001", "asset_hd_main", "mkv")],
    )
    state = build_initial_state(scenario, IdAllocator())
    assert state.archive_path_for("asset_hd_main") == (
        "library/movies-hd/archive/asset_hd_main.mkv"
    )


def test_world_state_archive_path_for_sentinel_value():
    scenario = _build_minimal_scenario(
        roots=[("movies-hd", "library/movies-hd")],
        works=[("work_001", "asset_hd_main", "mkv")],
        archive_root="archive",
    )
    state = build_initial_state(scenario, IdAllocator())
    assert state.archive_path_for("asset_hd_main") == (
        "library/movies-hd/archive/asset_hd_main.mkv"
    )


def test_world_state_archive_path_for_explicit_root():
    scenario = _build_minimal_scenario(
        roots=[
            ("movies-hd", "library/movies-hd"),
            ("cold-storage", "library/cold-storage"),
        ],
        works=[("work_001", "asset_hd_main", "mkv")],
        archive_root="cold-storage",
    )
    state = build_initial_state(scenario, IdAllocator())
    assert state.archive_path_for("asset_hd_main") == (
        "library/cold-storage/asset_hd_main.mkv"
    )


def test_initial_path_template_format():
    # Module-level constant lifted from build_initial_state so the slow-copy
    # validation rule can format an asset's initial path without duplicating
    # the convention.
    assert INITIAL_PATH_TEMPLATE.format(
        root_path="library/movies-hd",
        asset_id="asset_hd_main",
        container="mkv",
    ) == "library/movies-hd/asset_hd_main.mkv"
```

Update the `_build_minimal_scenario` helper (or add one if not present) to accept `archive_root` and multiple roots. The helper signature should be:

```python
def _build_minimal_scenario(
    *,
    roots: list[tuple[str, str]],
    works: list[tuple[str, str, str]],
    archive_root: str | None = None,
) -> Scenario:
    """Build a minimal Scenario for engine-level tests.

    Each work entry is (work_id, asset_id, container). One bundle per
    work, one variant per work, one asset per bundle.
    """
    # … construct Scenario with schema_version=4, declared library, no timeline.
```

If a similar helper already exists, extend it; otherwise add it to a `tests/engine/conftest.py` so other Sprint 6 tests can reuse it.

Imports at top of `test_state.py`:
```python
from chaos_librarian.contract.paths import INITIAL_PATH_TEMPLATE
from chaos_librarian.engine.state import build_initial_state
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/test_state.py -v -k 'root_path_for or archive_path_for or initial_path_template'`

Expected: `AttributeError` / `ImportError` for missing names.

- [ ] **Step 3: Add the module-level `INITIAL_PATH_TEMPLATE` constant to `contract/paths.py`**

In `src/chaos_librarian/contract/paths.py`, near the existing module-level definitions:

```python
from typing import Final

INITIAL_PATH_TEMPLATE: Final[str] = "{root_path}/{asset_id}.{container}"
"""Initial on-disk path convention for every declared asset.

Sprint 0 baked this into ``build_initial_state``'s f-string at the assignment
site; Sprint 6 lifts it to a module-level constant so the slow-copy
path-collision validation rule (``rules/slow_copy.py``) can format it
without re-encoding the convention. Format keys: ``root_path``, ``asset_id``,
``container``.

Lives in ``contract/paths.py`` (not ``engine/state.py``) to preserve the
validation→contract→errors-only layering — no validation rule imports
from ``chaos_librarian.engine``.
"""
```

- [ ] **Step 4: Add the import in `engine/state.py`**

In `src/chaos_librarian/engine/state.py`, add the import at the top alongside other `contract`-module imports:

```python
from chaos_librarian.contract.paths import INITIAL_PATH_TEMPLATE
```

- [ ] **Step 5: Extend `WorldState` with the two new fields + helpers**

In `src/chaos_librarian/engine/state.py`, extend `WorldState`:

```python
@dataclass
class WorldState:
    works: dict[str, ManifestWork] = field(default_factory=dict)
    variants: dict[str, ManifestVariant] = field(default_factory=dict)
    bundles: dict[str, ManifestBundle] = field(default_factory=dict)
    assets: dict[str, ManifestAsset] = field(default_factory=dict)
    versions: dict[str, ManifestVersion] = field(default_factory=dict)
    locations: dict[str, ManifestLocation] = field(default_factory=dict)
    sidecars: dict[str, ManifestSidecar] = field(default_factory=dict)

    _asset_to_location: dict[str, str] = field(default_factory=dict)
    _asset_to_version: dict[str, str] = field(default_factory=dict)
    pending_slow_copies: dict[str, tuple[str, str]] = field(default_factory=dict)

    # Sprint 6 additions:
    _root_paths: dict[str, str] = field(default_factory=dict)
    _archive_path_template: str = ""

    # ... existing methods unchanged ...

    def root_path_for(self, root_id: str) -> str:
        """Return the declared path of the library root with this id.

        Raises:
            KeyError: if ``root_id`` was not declared in the scenario.
        """
        return self._root_paths[root_id]

    def archive_path_for(self, asset_id: str) -> str:
        """Return the archive destination for ``asset_id``.

        Formats ``_archive_path_template`` with the asset's container.
        Validation (``rules/target_unknown.rule_root_unknown``) has
        already proven the archive root resolves, so the template is
        populated and the format call cannot KeyError.
        """
        asset = self.assets[asset_id]
        return self._archive_path_template.format(
            asset_id=asset_id,
            container=asset.container,
        )
```

- [ ] **Step 6: Refactor `build_initial_state` to populate the new fields and use `INITIAL_PATH_TEMPLATE`**

Replace `build_initial_state`'s body (preserve outer signature and docstring; update internals):

```python
def build_initial_state(scenario: Scenario, ids: IdAllocator) -> WorldState:
    if not scenario.library.roots:
        raise ChaosLibrarianValueError(
            "scenario has no library roots; cannot synthesize initial paths"
        )
    primary_root = scenario.library.roots[0]
    state = WorldState()
    state._root_paths = {root.id: root.path for root in scenario.library.roots}
    archive_root = scenario.library.archive_root
    if archive_root is None or archive_root == "archive":
        archive_base = f"{primary_root.path}/archive"
    else:
        archive_base = state._root_paths[archive_root]
    state._archive_path_template = (
        f"{archive_base}/{{asset_id}}.{{container}}"
    )

    for work in scenario.works:
        state.works[work.id] = ManifestWork(id=work.id, title=work.title)
        for variant in work.variants:
            state.variants[variant.id] = ManifestVariant(
                id=variant.id, work_id=work.id, label=variant.label
            )
            bundle = variant.bundle
            state.bundles[bundle.id] = ManifestBundle(id=bundle.id, variant_id=variant.id)
            for asset in bundle.assets:
                state.assets[asset.id] = ManifestAsset(
                    id=asset.id,
                    bundle_id=bundle.id,
                    role=asset.role,
                    container=asset.container,
                    duration_seconds=asset.duration_seconds,
                )
                version_id = ids.next_version_id()
                state.bind_version(
                    asset.id,
                    ManifestVersion(id=version_id, asset_id=asset.id, index=0),
                )
                location_id = ids.next_location_id()
                state.bind_location(
                    asset.id,
                    ManifestLocation(
                        id=location_id,
                        asset_id=asset.id,
                        path=INITIAL_PATH_TEMPLATE.format(
                            root_path=primary_root.path,
                            asset_id=asset.id,
                            container=asset.container,
                        ),
                    ),
                )

    return state
```

- [ ] **Step 7: Run the new + existing tests**

Run: `uv run pytest tests/engine/test_state.py -v`

Expected: new tests pass; existing tests still pass (the refactor's semantics are unchanged).

Run the full engine suite: `uv run pytest tests/engine -q`

Expected: pass.

- [ ] **Step 8: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

- [ ] **Step 9: Commit**

```bash
git add src/chaos_librarian/contract/paths.py \
        src/chaos_librarian/engine/state.py \
        tests/engine/test_state.py
# also tests/engine/conftest.py if you added the helper there
git commit -m "$(cat <<'EOF'
feat(engine): lift INITIAL_PATH_TEMPLATE; WorldState tracks roots + archive

Add module-level INITIAL_PATH_TEMPLATE in contract/paths.py so the upcoming
slow-copy path-collision validation rule can format an asset's initial path
without duplicating the convention. Lives in contract/ (not engine/) to
preserve the validation→contract→errors-only layering. WorldState gains
_root_paths and _archive_path_template populated once in build_initial_state
from scenario.library, plus root_path_for and archive_path_for helpers
consumed by the archive_file / move_between_roots handlers landing next.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Engine `_STATE_DELTA_KEYS` constant + parametrized drift-lock test

**Why before new handlers:** the contract documents what each handler MUST emit. Land the constant + lock test populated with the existing handlers; Tasks 6-8 add entries as new handlers and additive keys land. The drift-lock test guards every subsequent change.

**Files:**
- Modify: `src/chaos_librarian/engine/events.py` — add `_STATE_DELTA_KEYS` module-level constant.
- Test: `tests/engine/test_state_delta_contract.py` (new file).

- [ ] **Step 1: Write the failing test**

Create `tests/engine/test_state_delta_contract.py`:

```python
"""Parametrized lock for ``_STATE_DELTA_KEYS``.

For every action in the Sprint-6-supported set, exercises the handler on a
minimal scenario and asserts the emitted ``state_delta`` is a superset of
the contract. Locks the surface against silent drift when future sprints
add or rename keys.
"""

from __future__ import annotations

import uuid

import pytest

from chaos_librarian.contract.journal import JournalPhase
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.engine.events import _STATE_DELTA_KEYS, apply_event
from chaos_librarian.engine.resolution import resolve_one
from chaos_librarian.engine.state import build_initial_state


@pytest.mark.parametrize("action", sorted(_STATE_DELTA_KEYS, key=lambda a: a.value))
def test_state_delta_keys_match_contract(action):
    """Every handler's emitted state_delta is a superset of _STATE_DELTA_KEYS[action]."""
    scenario, state, resolved_event = _minimal_scenario_for_action(action)
    entries = apply_event(
        state=state,
        resolved=resolved_event,
        ids=IdAllocator(),
        run_id=uuid.UUID("1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01"),
        scenario_id="sc_test",
    )
    # Walk all emitted entries (slow_copy_start emits a Started entry whose
    # state_delta carries the start-time fields; commit emits Committed).
    for entry in entries:
        if entry.phase is JournalPhase.STARTED and action is TimelineActionName.SLOW_COPY_START:
            assert set(entry.state_delta.keys()) >= _STATE_DELTA_KEYS[action]
        elif entry.phase is JournalPhase.COMMITTED and action is TimelineActionName.SLOW_COPY_COMMIT:
            assert set(entry.state_delta.keys()) >= _STATE_DELTA_KEYS[action]
        elif entry.phase is JournalPhase.ATOMIC:
            assert set(entry.state_delta.keys()) >= _STATE_DELTA_KEYS[action]
```

Add `_minimal_scenario_for_action` to `tests/engine/conftest.py` (create the file if it doesn't yet exist). Every branch is fully implemented — Tasks 6, 7, 8 add no further branches:

```python
from __future__ import annotations

import uuid

from chaos_librarian.contract.scenario import (
    ArchiveFileEvent,
    CreateSidecarEvent,
    DeleteFileEvent,
    MoveAssetEvent,
    MoveBetweenRootsEvent,
    RenameFileEvent,
    Scenario,
    SlowCopyCommitEvent,
    SlowCopyStartEvent,
    TimelineActionName,
)
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState, build_initial_state


def _minimal_scenario_for_action(
    action: TimelineActionName,
) -> tuple[Scenario, WorldState, ResolvedEvent]:
    """Build the smallest scenario whose terminal event is ``action``.

    Returns (scenario, prepared_world_state, resolved_event). The state is
    pre-advanced through any prerequisite events (e.g. ``slow_copy_commit``
    needs its matching ``slow_copy_start`` applied first so
    ``state.pending_slow_copies`` is populated).
    """
    scenario = _build_minimal_scenario(
        roots=[
            ("movies-hd", "library/movies-hd"),
            ("cold-storage", "library/cold-storage"),
        ],
        works=[("work_001", "asset_hd_main", "mkv")],
        archive_root=None,
    )
    state = build_initial_state(scenario, IdAllocator())
    ids = IdAllocator()
    run_id = uuid.UUID("1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01")

    if action is TimelineActionName.MOVE_ASSET:
        event = MoveAssetEvent(
            id="ev", at="0ns", target="asset_hd_main", to="movies-hd/new.mkv"
        )
    elif action is TimelineActionName.RENAME_FILE:
        event = RenameFileEvent(
            id="ev", at="0ns", target="asset_hd_main", to="movies-hd/renamed.mkv"
        )
    elif action is TimelineActionName.DELETE_FILE:
        event = DeleteFileEvent(id="ev", at="0ns", target="asset_hd_main")
    elif action is TimelineActionName.CREATE_SIDECAR:
        event = CreateSidecarEvent(
            id="ev",
            at="0ns",
            target="asset_hd_main",
            to="movies-hd/asset_hd_main.en.srt",
            language="en",
        )
    elif action is TimelineActionName.SLOW_COPY_START:
        event = SlowCopyStartEvent(
            id="ev",
            at="0ns",
            target="asset_hd_main",
            to="movies-hd/final.mkv",
            temp_path="movies-hd/temp.mkv",
            duration="1ns",
        )
    elif action is TimelineActionName.SLOW_COPY_COMMIT:
        # Apply a preceding slow_copy_start so the commit can pop it.
        start_event = SlowCopyStartEvent(
            id="start",
            at="0ns",
            target="asset_hd_main",
            to="movies-hd/final.mkv",
            temp_path="movies-hd/temp.mkv",
            duration="1ns",
        )
        apply_event(
            state=state,
            resolved=ResolvedEvent(event=start_event, at_ns=0),
            ids=ids,
            run_id=run_id,
            scenario_id="sc_test",
        )
        event = SlowCopyCommitEvent(id="ev", at="1ns", for_="start")
    elif action is TimelineActionName.ARCHIVE_FILE:
        event = ArchiveFileEvent(id="ev", at="0ns", target="asset_hd_main")
    elif action is TimelineActionName.MOVE_BETWEEN_ROOTS:
        event = MoveBetweenRootsEvent(
            id="ev",
            at="0ns",
            target="asset_hd_main",
            from_root_id="movies-hd",
            to_root_id="cold-storage",
        )
    else:
        raise AssertionError(f"unhandled action: {action!r}")

    resolved = ResolvedEvent(event=event, at_ns=1)
    return scenario, state, resolved
```

`_minimal_scenario_for_action` consumes `_build_minimal_scenario` (Task 4) and is consumed by the parametrized test. Because every branch is fully implemented here, Tasks 6, 7, and 8 do NOT need a "fill in the new branch for `_minimal_scenario_for_action`" sub-step.

- [ ] **Step 2: Run the test to see it fail**

Run: `uv run pytest tests/engine/test_state_delta_contract.py -v`

Expected: `ImportError: cannot import name '_STATE_DELTA_KEYS'`.

- [ ] **Step 3: Add `_STATE_DELTA_KEYS` with the existing actions only**

In `src/chaos_librarian/engine/events.py`, near the top (above the handlers, after the imports):

```python
from typing import Final

_STATE_DELTA_KEYS: Final[dict[TimelineActionName, frozenset[str]]] = {
    TimelineActionName.MOVE_ASSET:         frozenset({"from_path", "to_path"}),
    TimelineActionName.RENAME_FILE:        frozenset({"from_path", "to_path"}),
    TimelineActionName.DELETE_FILE:        frozenset({"removed_path"}),
    TimelineActionName.CREATE_SIDECAR:     frozenset({"sidecar_path", "sidecar_id"}),
    TimelineActionName.SLOW_COPY_START:    frozenset({"final_path", "temp_path"}),
    TimelineActionName.SLOW_COPY_COMMIT:   frozenset({"final_path"}),
}
"""Per-action contract for emitted ``state_delta`` keys.

Each handler MUST emit at least these keys; extras are allowed for forward
compatibility. ``add_file`` is intentionally absent (deferred to Sprint 7);
``archive_file`` and ``move_between_roots`` land alongside their handlers.
The ``language`` key on create_sidecar and ``initial_path_at_start`` on
slow_copy_start are additive (Task 8); their entries here are bumped to
include those keys when Task 8 lands.

The parametrized test ``test_state_delta_keys_match_contract`` enforces this
contract by invoking each handler against a minimal scenario.
"""
```

Note: the constant is intentionally INTERNAL (`_` prefix). External callers should not depend on it. The test imports it via the `_` name explicitly — that's the only allowed consumer.

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/engine/test_state_delta_contract.py -v`

Expected: PASS for the six existing actions; the `_minimal_scenario_for_action` branches for ARCHIVE_FILE and MOVE_BETWEEN_ROOTS aren't reached yet (the constant doesn't include those keys yet).

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/engine/events.py \
        tests/engine/test_state_delta_contract.py \
        tests/engine/conftest.py
git commit -m "$(cat <<'EOF'
feat(engine): _STATE_DELTA_KEYS contract + parametrized drift-lock test

Document the per-action state_delta key contract that the materializer
phase-B dispatcher and derive_path_history read from journal entries. The
parametrized test exercises each handler on a minimal scenario and asserts
the emitted state_delta is a superset of the declared keys, locking the
surface against silent drift in future sprints.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Engine handler `_handle_archive_file`

**Files:**
- Modify: `src/chaos_librarian/engine/events.py` — add handler, register in `_HANDLERS`, add entry to `_STATE_DELTA_KEYS`.
- Test: `tests/engine/test_events_filesystem.py` (extend).

- [ ] **Step 1: Write the failing tests**

Add to `tests/engine/test_events_filesystem.py`:

```python
def test_archive_file_handler_moves_location_to_archive_path():
    scenario = _build_minimal_scenario(
        roots=[("movies-hd", "library/movies-hd")],
        works=[("work_001", "asset_hd_main", "mkv")],
    )
    state = build_initial_state(scenario, IdAllocator())
    resolved = _resolve_archive_file(scenario, event_id="ev_arch_001", target="asset_hd_main")
    entries = apply_event(
        state=state,
        resolved=resolved,
        ids=IdAllocator(),
        run_id=uuid.UUID("1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01"),
        scenario_id="sc_test",
    )
    loc_id = state.location_id_for_asset("asset_hd_main")
    assert state.locations[loc_id].path == "library/movies-hd/archive/asset_hd_main.mkv"
    assert state.has_location("asset_hd_main"), "archive keeps the asset placed"
    assert len(entries) == 1
    entry = entries[0]
    assert entry.action == TimelineActionName.ARCHIVE_FILE
    assert entry.target_ids == ["asset_hd_main"]
    assert entry.state_delta == {
        "from_path": "library/movies-hd/asset_hd_main.mkv",
        "to_path": "library/movies-hd/archive/asset_hd_main.mkv",
    }


def test_archive_file_handler_uses_explicit_archive_root():
    scenario = _build_minimal_scenario(
        roots=[
            ("movies-hd", "library/movies-hd"),
            ("cold-storage", "library/cold-storage"),
        ],
        works=[("work_001", "asset_hd_main", "mkv")],
        archive_root="cold-storage",
    )
    state = build_initial_state(scenario, IdAllocator())
    resolved = _resolve_archive_file(scenario, event_id="ev_arch_001", target="asset_hd_main")
    apply_event(
        state=state,
        resolved=resolved,
        ids=IdAllocator(),
        run_id=uuid.UUID("1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01"),
        scenario_id="sc_test",
    )
    loc_id = state.location_id_for_asset("asset_hd_main")
    assert state.locations[loc_id].path == "library/cold-storage/asset_hd_main.mkv"
```

Add a helper `_resolve_archive_file(scenario, event_id, target)` that builds an `ArchiveFileEvent` and wraps it in a `ResolvedEvent` (use the existing pattern in `tests/engine/test_events_filesystem.py`).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/engine/test_events_filesystem.py -v -k archive`

Expected: failure — handler not registered, lookup raises KeyError.

- [ ] **Step 3: Implement the handler**

In `src/chaos_librarian/engine/events.py`, add an import: `ArchiveFileEvent` (from `chaos_librarian.contract.scenario`).

Add the handler (place after `_handle_slow_copy_commit`):

```python
def _handle_archive_file(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Move ``target`` to its archive destination.

    The destination is ``state.archive_path_for(target)``; validation has
    already proven the archive root exists. ``location.path`` updates;
    the asset stays placed.
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
```

Register in `_HANDLERS`:

```python
_HANDLERS: dict[TimelineActionName, _Handler] = {
    TimelineActionName.MOVE_ASSET: _handle_move_asset,
    TimelineActionName.RENAME_FILE: _handle_rename_file,
    TimelineActionName.DELETE_FILE: _handle_delete_file,
    TimelineActionName.ADD_FILE: _handle_add_file,
    TimelineActionName.REENCODE_VIDEO: _handle_reencode_video,
    TimelineActionName.REENCODE_AUDIO: _handle_reencode_audio,
    TimelineActionName.CREATE_SIDECAR: _handle_create_sidecar,
    TimelineActionName.SLOW_COPY_START: _handle_slow_copy_start,
    TimelineActionName.SLOW_COPY_COMMIT: _handle_slow_copy_commit,
    TimelineActionName.ARCHIVE_FILE: _handle_archive_file,
}
```

Add to `_STATE_DELTA_KEYS`:

```python
_STATE_DELTA_KEYS: Final[dict[TimelineActionName, frozenset[str]]] = {
    # ... existing entries ...
    TimelineActionName.ARCHIVE_FILE: frozenset({"from_path", "to_path"}),
}
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/engine/test_events_filesystem.py tests/engine/test_state_delta_contract.py -v`

Expected: archive_file tests pass; the drift-lock test now covers ARCHIVE_FILE because the constant now includes it (the `_minimal_scenario_for_action` branch is already wired up in Task 5).

- [ ] **Step 5: Lint, format, type-check, commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

```bash
git add src/chaos_librarian/engine/events.py \
        tests/engine/test_events_filesystem.py \
        tests/engine/test_state_delta_contract.py
git commit -m "$(cat <<'EOF'
feat(engine): _handle_archive_file moves asset to library.archive_root

Resolves the archive destination via WorldState.archive_path_for (populated
in build_initial_state from library.archive_root + sentinel handling). Asset
stays placed; only location.path updates. Adds the archive_file entry to
_STATE_DELTA_KEYS so the drift-lock test covers it.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Engine handler `_handle_move_between_roots`

**Files:**
- Modify: `src/chaos_librarian/engine/events.py` — add handler, register, extend `_STATE_DELTA_KEYS`.
- Test: `tests/engine/test_events_filesystem.py` (extend).

- [ ] **Step 1: Write the failing tests**

```python
def test_move_between_roots_handler_crosses_roots():
    scenario = _build_minimal_scenario(
        roots=[
            ("movies-hd", "library/movies-hd"),
            ("staging", "library/staging"),
        ],
        works=[("work_001", "asset_hd_main", "mkv")],
    )
    state = build_initial_state(scenario, IdAllocator())
    resolved = _resolve_move_between_roots(
        scenario,
        event_id="ev_mbr_001",
        target="asset_hd_main",
        from_root_id="movies-hd",
        to_root_id="staging",
    )
    entries = apply_event(
        state=state,
        resolved=resolved,
        ids=IdAllocator(),
        run_id=uuid.UUID("1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01"),
        scenario_id="sc_test",
    )
    loc_id = state.location_id_for_asset("asset_hd_main")
    assert state.locations[loc_id].path == "library/staging/asset_hd_main.mkv"
    entry = entries[0]
    assert entry.action == TimelineActionName.MOVE_BETWEEN_ROOTS
    assert entry.state_delta == {
        "from_path": "library/movies-hd/asset_hd_main.mkv",
        "to_path": "library/staging/asset_hd_main.mkv",
        "from_root_id": "movies-hd",
        "to_root_id": "staging",
    }
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/engine/test_events_filesystem.py -v -k move_between_roots`

Expected: KeyError on handler lookup.

- [ ] **Step 3: Implement the handler**

Add `MoveBetweenRootsEvent` to the imports in `events.py`. Add the handler:

```python
def _handle_move_between_roots(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Move ``target`` from ``from_root_id`` to ``to_root_id``.

    The destination is ``<to_root.path>/<asset_id>.<container>``. Validation
    has already proven both root ids exist.
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

Register in `_HANDLERS`:

```python
TimelineActionName.MOVE_BETWEEN_ROOTS: _handle_move_between_roots,
```

Extend `_STATE_DELTA_KEYS`:

```python
TimelineActionName.MOVE_BETWEEN_ROOTS: frozenset(
    {"from_path", "to_path", "from_root_id", "to_root_id"}
),
```

- [ ] **Step 4: Run tests, lint, type-check, commit**

The `_minimal_scenario_for_action` branch for `MOVE_BETWEEN_ROOTS` is already wired up in Task 5 — no additional helper edit needed here.

```bash
git add src/chaos_librarian/engine/events.py \
        tests/engine/test_events_filesystem.py \
        tests/engine/test_state_delta_contract.py
git commit -m "$(cat <<'EOF'
feat(engine): _handle_move_between_roots moves asset across declared roots

Synthesizes destination as <to_root.path>/<asset_id>.<container>. State_delta
carries from_root_id and to_root_id so consumers can filter
move_between_roots from plain move_asset.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: state_delta additive keys — `language` on create_sidecar, `initial_path_at_start` on slow_copy_start

**Files:**
- Modify: `src/chaos_librarian/engine/events.py` — emit additional keys; update `_STATE_DELTA_KEYS`.
- Test: `tests/engine/test_events_filesystem.py` and `tests/engine/test_events_slow_copy.py` (existing tests need updating).

- [ ] **Step 1: Update tests to assert the new keys**

In `tests/engine/test_events_filesystem.py`'s create_sidecar test, update the state_delta assertion:

```python
# Was: assert entry.state_delta == {"sidecar_path": ..., "sidecar_id": ...}
# Now:
assert entry.state_delta == {
    "sidecar_path": "movies-hd/asset_hd_main.en.srt",
    "sidecar_id": "sidecar_0001",
    "language": "en",
}
```

In `tests/engine/test_events_slow_copy.py`'s start test, update the state_delta assertion to include `initial_path_at_start`:

```python
assert entry.state_delta == {
    "final_path": "movies-hd/final.mkv",
    "temp_path": "movies-hd/temp.mkv",
    "initial_path_at_start": "library/movies-hd/asset_hd_main.mkv",
}
```

Also update the `_STATE_DELTA_KEYS` lock test (which already runs but with the
old key set — the test will be more strict once the constant is widened).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/engine/test_events_filesystem.py tests/engine/test_events_slow_copy.py tests/engine/test_state_delta_contract.py -v`

Expected: failures on the updated assertions (handler still emits the old key set).

- [ ] **Step 3: Update `_handle_create_sidecar` to emit `language`**

In `src/chaos_librarian/engine/events.py`, replace `_handle_create_sidecar`'s `state_delta` argument:

```python
state_delta={
    "sidecar_path": event.to,
    "sidecar_id": sidecar_id,
    "language": event.language,
},
```

- [ ] **Step 4: Update `_handle_slow_copy_start` to emit `initial_path_at_start`**

```python
state_delta={
    "final_path": event.to,
    "temp_path": event.temp_path,
    "initial_path_at_start": previous.path,
},
```

- [ ] **Step 5: Widen `_STATE_DELTA_KEYS` entries**

```python
TimelineActionName.CREATE_SIDECAR:  frozenset({"sidecar_path", "sidecar_id", "language"}),
TimelineActionName.SLOW_COPY_START: frozenset({"final_path", "temp_path", "initial_path_at_start"}),
```

- [ ] **Step 6: Run all engine tests**

Run: `uv run pytest tests/engine -q`

Expected: pass.

- [ ] **Step 7: Lint, format, type-check, commit**

```bash
git add src/chaos_librarian/engine/events.py \
        tests/engine/test_events_filesystem.py \
        tests/engine/test_events_slow_copy.py
git commit -m "$(cat <<'EOF'
feat(engine): additive state_delta keys for create_sidecar and slow_copy_start

create_sidecar gains ``language``; slow_copy_start gains
``initial_path_at_start`` (previous on-disk path) so phase B can drive
purely from the journal. Both are additive — state_delta is dict[str,
object] and accepts extra keys without a schema bump. _STATE_DELTA_KEYS
entries widen to require the new keys, locked by the parametrized
drift-lock test.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Lifecycle simulator extensions (archive_file, move_between_roots)

**Files:**
- Modify: `src/chaos_librarian/validation/rules/timeline_lifecycle.py`.
- Test: `tests/validation/rules/test_timeline_lifecycle.py` (extend).

- [ ] **Step 1: Write the failing tests**

```python
def test_archive_file_on_unplaced_asset_raises_lifecycle_invalid():
    raw = _build_scenario_raw(
        assets=["asset_hd_main"],
        timeline=[
            {"id": "ev_del", "at": "0ns", "action": "delete_file", "target": "asset_hd_main"},
            {"id": "ev_arch", "at": "1ns", "action": "archive_file", "target": "asset_hd_main"},
        ],
    )
    collector = _run_lifecycle_rule(raw)
    codes = [issue.code for issue in collector.issues]
    assert E_LIFECYCLE_INVALID in codes
    arch_issue = next(i for i in collector.issues if "archive_file" in i.message)
    assert "unplaced" in arch_issue.message


def test_archive_file_keeps_asset_placed():
    """archive_file is a passthrough — the asset remains placed afterward."""
    raw = _build_scenario_raw(
        assets=["asset_hd_main"],
        timeline=[
            {"id": "ev_arch", "at": "0ns", "action": "archive_file", "target": "asset_hd_main"},
            {"id": "ev_move", "at": "1ns", "action": "move_asset",
             "target": "asset_hd_main", "to": "movies-hd/new.mkv"},
        ],
    )
    collector = _run_lifecycle_rule(raw)
    assert not collector.has_errors  # move on still-placed asset is valid


def test_archive_file_on_pending_slow_copy_raises():
    raw = _build_scenario_raw(
        assets=["asset_hd_main"],
        timeline=[
            {"id": "scs", "at": "0ns", "action": "slow_copy_start",
             "target": "asset_hd_main", "to": "movies-hd/final.mkv",
             "temp_path": "movies-hd/temp.mkv", "duration": "1ns"},
            {"id": "ev_arch", "at": "0ns", "action": "archive_file", "target": "asset_hd_main"},
        ],
    )
    collector = _run_lifecycle_rule(raw)
    arch_issue = next(i for i in collector.issues if "archive_file" in i.message)
    assert "pending slow_copy" in arch_issue.message


def test_move_between_roots_on_unplaced_asset_raises():
    # … parallel structure to archive_file test
    ...


def test_move_between_roots_on_pending_slow_copy_raises():
    # … parallel structure
    ...
```

- [ ] **Step 2: Run the tests to verify failure**

Run: `uv run pytest tests/validation/rules/test_timeline_lifecycle.py -v`

Expected: archive/move_between_roots events fall through the lifecycle simulator's `if/elif` chain, leaving them un-checked (the tests assert specific error messages that don't appear).

- [ ] **Step 3: Extend `_LOCATION_DEPENDENT_PASSTHROUGH` and add `_PATH_MUTATING_PASSTHROUGH` set**

In `src/chaos_librarian/validation/rules/timeline_lifecycle.py`:

```python
_LOCATION_DEPENDENT_PASSTHROUGH: frozenset[str] = frozenset(
    {
        TimelineActionName.REENCODE_VIDEO,
        TimelineActionName.REENCODE_AUDIO,
        TimelineActionName.CREATE_SIDECAR,
        TimelineActionName.ARCHIVE_FILE,
        TimelineActionName.MOVE_BETWEEN_ROOTS,
    }
)

_PATH_MUTATING_PASSTHROUGH: frozenset[str] = frozenset(
    {
        TimelineActionName.ARCHIVE_FILE,
        TimelineActionName.MOVE_BETWEEN_ROOTS,
    }
)
```

Update `_lifecycle_check_passthrough` to honor the pending-copy guard for the two new actions:

```python
def _lifecycle_check_passthrough(
    *,
    action: str,
    target: str,
    state: _LifecycleState,
    emit: _Emit,
    loc: _Loc,
) -> None:
    if target not in state.placed:
        emit(message=f"{action} on unplaced asset {target!r}", loc=loc)
    if action in _PATH_MUTATING_PASSTHROUGH and target in state.assets_with_pending_copy:
        emit(message=f"{action} on asset {target!r} with a pending slow_copy", loc=loc)
```

(The existing reencode/create_sidecar passthrough does NOT enforce the pending-copy rule — those don't move bytes on disk. Only the new path-mutating passthroughs need the guard.)

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/validation/rules/test_timeline_lifecycle.py -v`

Expected: pass.

- [ ] **Step 5: Lint, format, type-check, commit**

```bash
git add src/chaos_librarian/validation/rules/timeline_lifecycle.py \
        tests/validation/rules/test_timeline_lifecycle.py
git commit -m "$(cat <<'EOF'
feat(validation): lifecycle covers archive_file and move_between_roots

Both actions require the target placed and keep it placed. Neither may run
on an asset with a pending slow_copy — the path-mutating subset of the
passthrough set enforces the same guard the mutation set already does for
move/rename/delete.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: `E_ROOT_UNKNOWN` validation rule

**Files:**
- Modify: `src/chaos_librarian/validation/codes.py` — add constant.
- Modify: `src/chaos_librarian/validation/rules/target_unknown.py` — add new `rule_root_unknown`.
- Modify: `src/chaos_librarian/validation/pipeline.py` — register the new rule.
- Test: `tests/validation/rules/test_target_unknown.py` (extend).

Also: add at least one fixture in `tests/fixtures/scenarios/invalid/` exercising the new code, with `# expected: E_ROOT_UNKNOWN` first line.

- [ ] **Step 1: Write the failing tests**

```python
def test_move_between_roots_unknown_from_root_id_emits_e_root_unknown():
    raw = _build_scenario_raw(
        assets=["asset_hd_main"],
        roots=[("movies-hd", "library/movies-hd")],
        timeline=[
            {"id": "ev_mbr", "at": "0ns", "action": "move_between_roots",
             "target": "asset_hd_main",
             "from_root_id": "missing-root", "to_root_id": "movies-hd"},
        ],
    )
    collector = _run_rule(rule_root_unknown, raw)
    codes = [issue.code for issue in collector.issues]
    assert codes == [E_ROOT_UNKNOWN]
    assert "missing-root" in collector.issues[0].message
    assert collector.issues[0].loc == "$.timeline[0].from_root_id"


def test_move_between_roots_unknown_to_root_id_emits_e_root_unknown():
    # … same shape, error on to_root_id
    ...


def test_archive_root_unknown_emits_e_root_unknown():
    raw = _build_scenario_raw(
        assets=["asset_hd_main"],
        roots=[("movies-hd", "library/movies-hd")],
        archive_root="ghost-root",
        timeline=[],
    )
    collector = _run_rule(rule_root_unknown, raw)
    codes = [issue.code for issue in collector.issues]
    assert codes == [E_ROOT_UNKNOWN]
    assert collector.issues[0].loc == "$.library.archive_root"


def test_archive_root_sentinel_value_valid():
    raw = _build_scenario_raw(
        assets=["asset_hd_main"],
        roots=[("movies-hd", "library/movies-hd")],
        archive_root="archive",
        timeline=[],
    )
    collector = _run_rule(rule_root_unknown, raw)
    assert not collector.has_errors


def test_archive_root_none_valid():
    raw = _build_scenario_raw(
        assets=["asset_hd_main"],
        roots=[("movies-hd", "library/movies-hd")],
        archive_root=None,
        timeline=[],
    )
    collector = _run_rule(rule_root_unknown, raw)
    assert not collector.has_errors


def test_archive_root_referencing_declared_root_valid():
    raw = _build_scenario_raw(
        assets=["asset_hd_main"],
        roots=[
            ("movies-hd", "library/movies-hd"),
            ("cold-storage", "library/cold-storage"),
        ],
        archive_root="cold-storage",
        timeline=[],
    )
    collector = _run_rule(rule_root_unknown, raw)
    assert not collector.has_errors
```

Helper `_build_scenario_raw` should accept `archive_root` and emit it under `library.archive_root` in the raw mapping.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/validation/rules/test_target_unknown.py -v -k root_unknown`

Expected: `rule_root_unknown` not defined.

- [ ] **Step 3: Add the code constant**

In `src/chaos_librarian/validation/codes.py`:

```python
E_ROOT_UNKNOWN: Final = "E_ROOT_UNKNOWN"
```

- [ ] **Step 4: Add the rule function**

In `src/chaos_librarian/validation/rules/target_unknown.py`:

```python
def rule_root_unknown(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject move_between_roots/archive_file/archive_root referencing unknown roots.

    The closed set of valid root ids is ``library.roots[].id`` plus the
    sentinel ``"archive"`` (only for ``library.archive_root``).
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    library = raw.get("library")
    if not isinstance(library, Mapping):
        return  # Pydantic owns shape
    roots = library.get("roots", [])
    declared_ids: set[str] = set()
    if isinstance(roots, list):
        for root in roots:
            if isinstance(root, Mapping) and isinstance(root.get("id"), str):
                declared_ids.add(root["id"])

    archive_root = library.get("archive_root")
    if isinstance(archive_root, str) and archive_root != "archive":
        if archive_root not in declared_ids:
            reporter.error(
                code=E_ROOT_UNKNOWN,
                message=f"library.archive_root {archive_root!r} is not a declared root id",
                loc=("library", "archive_root"),
            )

    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        if action != TimelineActionName.MOVE_BETWEEN_ROOTS:
            continue
        for field in ("from_root_id", "to_root_id"):
            value = event.get(field)
            if not isinstance(value, str):
                continue  # Pydantic owns shape
            if value not in declared_ids:
                reporter.error(
                    code=E_ROOT_UNKNOWN,
                    message=f"{field} {value!r} is not a declared root id",
                    loc=("timeline", idx, field),
                )
```

Add `__all__` entry and update the imports at the top:

```python
from chaos_librarian.validation.codes import E_ROOT_UNKNOWN, E_TARGET_UNKNOWN
from chaos_librarian.validation.rules._common import (
    Reporter,
    _iter_timeline_events,
    iter_asset_ids,
)

__all__ = ["rule_root_unknown", "rule_target_unknown"]
```

- [ ] **Step 5: Register the rule in the pipeline**

Open `src/chaos_librarian/validation/pipeline.py` and find the rule list (likely `_SEMANTIC_RULES` or similar). Add `rule_root_unknown` near `rule_target_unknown`.

- [ ] **Step 6: Add an invalid-corpus fixture**

Create `tests/fixtures/scenarios/invalid/move-between-roots-unknown-root.yaml`:

```yaml
# expected: E_ROOT_UNKNOWN
schema_version: 4
scenario_id: sc_invalid_root
seed: 42
duration_scale: short
library:
  roots:
    - id: movies-hd
      path: library/movies-hd
works:
  - id: work_001
    title: Test Movie
    variants:
      - id: variant_001
        label: hd
        bundle:
          id: bundle_001
          assets:
            - id: asset_hd_main
              role: main
              container: mkv
              duration_seconds: 1.0
              video:
                source: mandelbrot
                codec: h264
                resolution: hd
timeline:
  - id: ev_mbr_001
    at: 0ns
    action: move_between_roots
    target: asset_hd_main
    from_root_id: movies-hd
    to_root_id: missing-root
```

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/validation -v && uv run pytest tests/validation/test_invalid_corpus.py -v`

Expected: pass.

- [ ] **Step 8: Lint, format, type-check, commit**

```bash
git add src/chaos_librarian/validation/codes.py \
        src/chaos_librarian/validation/rules/target_unknown.py \
        src/chaos_librarian/validation/pipeline.py \
        tests/validation/rules/test_target_unknown.py \
        tests/fixtures/scenarios/invalid/move-between-roots-unknown-root.yaml
git commit -m "$(cat <<'EOF'
feat(validation): E_ROOT_UNKNOWN rejects unknown root_id references

Closed-set validation for from_root_id / to_root_id (move_between_roots) and
archive_root (Library). Sentinel value "archive" stays valid even without a
declared root with that id. The rule lives alongside rule_target_unknown
since both validate closed-set identifier references.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: `E_SLOW_COPY_PATH_COLLISION` validation rule

**Files:**
- Modify: `src/chaos_librarian/validation/codes.py`.
- Modify: `src/chaos_librarian/validation/rules/slow_copy.py` — add `rule_slow_copy_path_collision`.
- Modify: `src/chaos_librarian/validation/pipeline.py` — register.
- Test: `tests/validation/rules/test_slow_copy.py` (extend).
- Add invalid corpus fixture(s).

- [ ] **Step 1: Write the failing tests**

```python
def test_slow_copy_rejects_temp_equals_final():
    raw = _build_scenario_raw(
        assets=["asset_hd_main"],
        roots=[("movies-hd", "library/movies-hd")],
        timeline=[
            {"id": "scs", "at": "0ns", "action": "slow_copy_start",
             "target": "asset_hd_main", "to": "movies-hd/final.mkv",
             "temp_path": "movies-hd/final.mkv", "duration": "1ns"},
            {"id": "scc", "at": "1ns", "action": "slow_copy_commit", "for": "scs"},
        ],
    )
    collector = _run_rule(rule_slow_copy_path_collision, raw)
    codes = [issue.code for issue in collector.issues]
    assert E_SLOW_COPY_PATH_COLLISION in codes
    assert "temp_path equals to" in collector.issues[0].message


def test_slow_copy_rejects_temp_equals_initial_path():
    raw = _build_scenario_raw(
        assets=["asset_hd_main"],
        roots=[("movies-hd", "library/movies-hd")],
        timeline=[
            {"id": "scs", "at": "0ns", "action": "slow_copy_start",
             "target": "asset_hd_main", "to": "movies-hd/final.mkv",
             "temp_path": "library/movies-hd/asset_hd_main.mkv",
             "duration": "1ns"},
            {"id": "scc", "at": "1ns", "action": "slow_copy_commit", "for": "scs"},
        ],
    )
    collector = _run_rule(rule_slow_copy_path_collision, raw)
    codes = [issue.code for issue in collector.issues]
    assert E_SLOW_COPY_PATH_COLLISION in codes
    assert "initial path" in collector.issues[0].message.lower()


def test_slow_copy_path_collision_allows_distinct_paths():
    raw = _build_scenario_raw(
        assets=["asset_hd_main"],
        roots=[("movies-hd", "library/movies-hd")],
        timeline=[
            {"id": "scs", "at": "0ns", "action": "slow_copy_start",
             "target": "asset_hd_main", "to": "movies-hd/final.mkv",
             "temp_path": "movies-hd/temp.mkv", "duration": "1ns"},
            {"id": "scc", "at": "1ns", "action": "slow_copy_commit", "for": "scs"},
        ],
    )
    collector = _run_rule(rule_slow_copy_path_collision, raw)
    assert not collector.has_errors


def test_slow_copy_rejects_temp_equals_initial_via_dot_segment():
    """A `.` segment in temp_path must not let it slip past the rule.

    Without normalization, raw `==` would treat `library/./movies-hd/...`
    as distinct from `library/movies-hd/...` even though they describe
    the same on-disk path.
    """
    raw = _build_scenario_raw(
        assets=["asset_hd_main"],
        roots=[("movies-hd", "library/movies-hd")],
        timeline=[
            {"id": "scs", "at": "0ns", "action": "slow_copy_start",
             "target": "asset_hd_main", "to": "movies-hd/final.mkv",
             "temp_path": "library/./movies-hd/asset_hd_main.mkv",
             "duration": "1ns"},
            {"id": "scc", "at": "1ns", "action": "slow_copy_commit",
             "for": "scs"},
        ],
    )
    collector = _run_rule(rule_slow_copy_path_collision, raw)
    codes = [issue.code for issue in collector.issues]
    assert E_SLOW_COPY_PATH_COLLISION in codes
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/validation/rules/test_slow_copy.py -v -k path_collision`

Expected: `rule_slow_copy_path_collision` not defined.

- [ ] **Step 3: Add the code constant**

```python
E_SLOW_COPY_PATH_COLLISION: Final = "E_SLOW_COPY_PATH_COLLISION"
```

- [ ] **Step 4: Add the rule**

In `src/chaos_librarian/validation/rules/slow_copy.py`:

```python
import os

from chaos_librarian.contract.paths import INITIAL_PATH_TEMPLATE

# ... existing imports ...


def _normalize(path: str) -> str:
    """Canonicalize a YAML-authored path for equality comparison.

    Uses ``os.path.normpath`` — stdlib, no filesystem I/O, no symlink
    resolution. We compare normalized forms because the run-dir doesn't
    exist at validation time, but two scenario paths that differ only by
    ``.`` / ``..`` / trailing slash describe the same on-disk location.
    """
    return os.path.normpath(path)


def rule_slow_copy_path_collision(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """5c: reject ``temp_path == to`` and ``temp_path == initial_path``.

    Phase B's commit helper unlinks ``initial_path`` and then ``replace``s
    ``temp_path → final_path``. If ``temp_path == to`` the multi-phase
    visibility contract collapses; if ``temp_path == initial_path`` the
    unlink wipes the temp before the replace runs. Both cases emit
    ``E_SLOW_COPY_PATH_COLLISION``.

    Path equality is checked on the ``os.path.normpath``-normalized form
    so a ``.``-segment or trailing-slash variant cannot slip past the
    rule. Normalization is purely lexical — no I/O, no symlink resolution.

    Initial paths are derived via ``contract.paths.INITIAL_PATH_TEMPLATE``
    formatted with the asset's primary-root path and container — no other
    source of truth.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    primary_root_path, asset_containers = _index_asset_paths(raw)
    if primary_root_path is None:
        return  # Pydantic owns shape on missing roots[0]
    for idx, event in _iter_timeline_events(raw):
        if event.get("action") != TimelineActionName.SLOW_COPY_START:
            continue
        target = event.get("target")
        temp_path = event.get("temp_path")
        final_path = event.get("to")
        if not isinstance(target, str) or not isinstance(temp_path, str):
            continue
        if isinstance(final_path, str) and _normalize(temp_path) == _normalize(final_path):
            reporter.error(
                code=E_SLOW_COPY_PATH_COLLISION,
                message=(
                    f"slow_copy_start temp_path equals to (final): "
                    f"{temp_path!r}; the multi-phase visibility contract "
                    f"requires the three paths to be pairwise distinct"
                ),
                loc=("timeline", idx, "temp_path"),
            )
            continue  # one error per event
        container = asset_containers.get(target)
        if container is None:
            continue  # asset undeclared; rule_target_unknown owns that
        initial_path = INITIAL_PATH_TEMPLATE.format(
            root_path=primary_root_path,
            asset_id=target,
            container=container,
        )
        if _normalize(temp_path) == _normalize(initial_path):
            reporter.error(
                code=E_SLOW_COPY_PATH_COLLISION,
                message=(
                    f"slow_copy_start temp_path equals the asset's initial "
                    f"path {initial_path!r}; the commit's unlink(initial) "
                    f"would wipe the temp file before the replace runs"
                ),
                loc=("timeline", idx, "temp_path"),
            )


def _index_asset_paths(
    raw: Mapping[str, object],
) -> tuple[str | None, dict[str, str]]:
    """Return (primary_root_path, asset_id -> container).

    Shape-defensive: returns (None, {}) if the library subtree is missing
    or malformed (Pydantic flags that case).
    """
    library = raw.get("library")
    if not isinstance(library, Mapping):
        return (None, {})
    roots = library.get("roots", [])
    if not isinstance(roots, list) or not roots:
        return (None, {})
    primary = roots[0]
    if not isinstance(primary, Mapping):
        return (None, {})
    primary_path = primary.get("path")
    if not isinstance(primary_path, str):
        return (None, {})
    containers: dict[str, str] = {}
    works = raw.get("works", [])
    if isinstance(works, list):
        for work in works:
            if not isinstance(work, Mapping):
                continue
            for variant in work.get("variants", []):
                if not isinstance(variant, Mapping):
                    continue
                bundle = variant.get("bundle")
                if not isinstance(bundle, Mapping):
                    continue
                for asset in bundle.get("assets", []):
                    if not isinstance(asset, Mapping):
                        continue
                    asset_id = asset.get("id")
                    container = asset.get("container")
                    if isinstance(asset_id, str) and isinstance(container, str):
                        containers[asset_id] = container
    return (primary_path, containers)
```

Update `__all__`:

```python
__all__ = [
    "rule_slow_copy_path_collision",
    "rule_slow_copy_timing",
    "rule_slow_copy_unpaired",
]
```

- [ ] **Step 5: Register in the pipeline**

Add `rule_slow_copy_path_collision` next to `rule_slow_copy_unpaired` / `rule_slow_copy_timing` in `pipeline.py`.

- [ ] **Step 6: Add invalid-corpus fixtures**

Create `tests/fixtures/scenarios/invalid/slow-copy-temp-equals-final.yaml` and `slow-copy-temp-equals-initial.yaml` (first line `# expected: E_SLOW_COPY_PATH_COLLISION`).

- [ ] **Step 7: Run tests**

Run: `uv run pytest tests/validation -v`

- [ ] **Step 8: Lint, format, type-check, commit**

```bash
git add src/chaos_librarian/validation/codes.py \
        src/chaos_librarian/validation/rules/slow_copy.py \
        src/chaos_librarian/validation/pipeline.py \
        tests/validation/rules/test_slow_copy.py \
        tests/fixtures/scenarios/invalid/slow-copy-temp-equals-final.yaml \
        tests/fixtures/scenarios/invalid/slow-copy-temp-equals-initial.yaml
git commit -m "$(cat <<'EOF'
feat(validation): E_SLOW_COPY_PATH_COLLISION rejects degenerate temp_path

Two collision cases both break the phase-B commit contract: temp == final
collapses the multi-phase visibility signal; temp == initial_path lets the
unlink(initial) wipe the temp file before the replace runs. The rule
derives initial_path from INITIAL_PATH_TEMPLATE (contract/paths.py) so the
on-disk convention stays single-sourced.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: Path containment for synthesized to_path (archive_file, move_between_roots)

**Files:**
- Modify: `src/chaos_librarian/validation/rules/path_containment.py` — add synthesis for the two new actions.
- Test: `tests/validation/rules/test_path_containment.py` (extend).

- [ ] **Step 1: Read the existing rule**

Read `src/chaos_librarian/validation/rules/path_containment.py` end-to-end to understand the per-event-field traversal style. Match it exactly when adding the new branches.

- [ ] **Step 2: Write the failing tests**

```python
def test_archive_file_path_synthesis_respects_containment():
    # archive_root points at a root path that escapes library/ via `..`
    raw = _build_scenario_raw(
        assets=["asset_hd_main"],
        roots=[
            ("movies-hd", "library/movies-hd"),
            ("escape", "library/../../../etc"),
        ],
        archive_root="escape",
        timeline=[
            {"id": "ev_arch", "at": "0ns", "action": "archive_file",
             "target": "asset_hd_main"},
        ],
    )
    collector = _run_rule(rule_path_containment, raw)
    codes = [issue.code for issue in collector.issues]
    assert E_PATH_CONTAINMENT in codes


def test_move_between_roots_path_synthesis_respects_containment():
    raw = _build_scenario_raw(
        assets=["asset_hd_main"],
        roots=[
            ("movies-hd", "library/movies-hd"),
            ("escape", "library/../../../etc"),
        ],
        timeline=[
            {"id": "ev_mbr", "at": "0ns", "action": "move_between_roots",
             "target": "asset_hd_main",
             "from_root_id": "movies-hd", "to_root_id": "escape"},
        ],
    )
    collector = _run_rule(rule_path_containment, raw)
    codes = [issue.code for issue in collector.issues]
    assert E_PATH_CONTAINMENT in codes
```

- [ ] **Step 3: Run tests to verify failure**

- [ ] **Step 4: Extend the rule**

Add per-event branches to the containment rule's main loop:

```python
# Pseudocode — match the existing loop structure exactly. The key insight
# is that archive_file/move_between_roots don't have a `to:` field on the
# event itself, so the rule has to synthesize one from library config.

if action == TimelineActionName.ARCHIVE_FILE:
    target = event.get("target")
    if not isinstance(target, str):
        continue
    archive_path = _synthesize_archive_path(library_info, target, asset_containers)
    if archive_path is not None:
        resolve_under_library(archive_path, loc=(...), reporter=reporter)

elif action == TimelineActionName.MOVE_BETWEEN_ROOTS:
    target = event.get("target")
    to_root_id = event.get("to_root_id")
    if not isinstance(target, str) or not isinstance(to_root_id, str):
        continue
    if to_root_id in declared_roots:
        to_root_path = declared_roots[to_root_id]
        synthesized = f"{to_root_path}/{target}.{asset_containers[target]}"
        resolve_under_library(synthesized, loc=(...), reporter=reporter)
```

Reuse the existing `resolve_under_library` helper from `paths.py`. The exact synthesis helper signatures should match the file's existing style.

- [ ] **Step 5: Run tests, lint, format, type-check, commit**

```bash
git add src/chaos_librarian/validation/rules/path_containment.py \
        tests/validation/rules/test_path_containment.py
git commit -m "$(cat <<'EOF'
feat(validation): path containment covers archive_file and move_between_roots

Both actions synthesize their destination from library config rather than
declaring a to: field on the event. Containment validation derives the path
the same way the engine handlers will (via state.archive_path_for /
state.root_path_for + container) and runs it through resolve_under_library.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: `derive_path_history` + AssetReport wiring

**Files:**
- Create: `src/chaos_librarian/engine/path_history.py`.
- Modify: `src/chaos_librarian/engine/reports.py` — call `derive_path_history(asset.id, journal)` per asset.
- Test: `tests/engine/test_path_history.py` (new file).
- Test: `tests/engine/test_reports.py` (extend — ensure built reports carry path_history).

- [ ] **Step 1: Write the failing tests for the pure projection**

Create `tests/engine/test_path_history.py`:

```python
"""Tests for ``derive_path_history`` — pure journal projection."""

from __future__ import annotations

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.engine.path_history import derive_path_history


def _atomic(
    *, event_id, action, logical_time_ns, target, **state_delta
):
    """Build a dict shaped like an AtomicJournalEntry for projection tests."""
    return {
        "schema_version": 1,
        "event_id": event_id,
        "scenario_id": "sc_test",
        "run_id": "1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01",
        "logical_time_ns": logical_time_ns,
        "action": action.value,
        "target_ids": [target],
        "input_version_ids": [],
        "output_version_ids": [],
        "location_ids": [],
        "state_delta": state_delta,
        "phase": "atomic",
    }


def test_path_history_empty_for_asset_with_no_filesystem_events():
    journal = []
    assert derive_path_history("asset_hd_main", journal) == []


def test_path_history_orders_by_logical_time_ns():
    journal = [
        _validated_entry(_atomic(
            event_id="ev_move_1", action=TimelineActionName.MOVE_ASSET,
            logical_time_ns=1_000_000_000, target="asset_hd_main",
            from_path="a", to_path="b",
        )),
        _validated_entry(_atomic(
            event_id="ev_rename_1", action=TimelineActionName.RENAME_FILE,
            logical_time_ns=2_000_000_000, target="asset_hd_main",
            from_path="b", to_path="c",
        )),
    ]
    history = derive_path_history("asset_hd_main", journal)
    assert [e.event_id for e in history] == ["ev_move_1", "ev_rename_1"]
    assert history[0].from_path == "a"
    assert history[1].to_path == "c"


def test_path_history_filters_non_filesystem_actions():
    journal = [
        _validated_entry(_atomic(
            event_id="ev_reencode", action=TimelineActionName.REENCODE_VIDEO,
            logical_time_ns=1, target="asset_hd_main",
            resolution="1080p", codec="h264",
        )),
    ]
    assert derive_path_history("asset_hd_main", journal) == []


def test_path_history_filters_other_assets():
    journal = [
        _validated_entry(_atomic(
            event_id="ev_other", action=TimelineActionName.MOVE_ASSET,
            logical_time_ns=1, target="asset_other",
            from_path="x", to_path="y",
        )),
    ]
    assert derive_path_history("asset_hd_main", journal) == []


def test_path_history_includes_slow_copy_pair():
    journal = [...]
    # … assert both start (with temp_path) and commit (with final_path) appear


def test_path_history_includes_archive_file_and_move_between_roots():
    # … assert both action types surface with correct from/to paths
    ...
```

Use `JournalEntry.model_validate()` (or the TypeAdapter wrapper) to convert the raw dicts into typed entries (mirroring how `journal_io.py` does it). The `_validated_entry` helper:

```python
def _validated_entry(payload):
    from chaos_librarian.contract.journal import _JOURNAL_ENTRY_ADAPTER
    return _JOURNAL_ENTRY_ADAPTER.validate_python(payload)
```

If `_JOURNAL_ENTRY_ADAPTER` doesn't exist with that name, find the correct adapter used by `journal_io.py` and import it via the canonical name.

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/engine/test_path_history.py -v`

Expected: `ImportError: derive_path_history`.

- [ ] **Step 3: Implement `derive_path_history`**

Create `src/chaos_librarian/engine/path_history.py`:

```python
"""Project the journal to one asset's filesystem-affecting subset.

Sprint 6: ``AssetReport.path_history`` carries a typed projection of the
journal's filesystem events for the asset under report. The function is
mode-agnostic — both plan-only and materialize call it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.reports import PathHistoryEntry
from chaos_librarian.contract.scenario import TimelineActionName

__all__ = ["derive_path_history"]


_FILESYSTEM_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.MOVE_ASSET,
        TimelineActionName.RENAME_FILE,
        TimelineActionName.DELETE_FILE,
        TimelineActionName.ADD_FILE,
        TimelineActionName.CREATE_SIDECAR,
        TimelineActionName.SLOW_COPY_START,
        TimelineActionName.SLOW_COPY_COMMIT,
        TimelineActionName.ARCHIVE_FILE,
        TimelineActionName.MOVE_BETWEEN_ROOTS,
    }
)
"""Actions whose journal entries describe an on-disk change.

ADD_FILE stays in the set even though Sprint 6's materializer rejects it
at preflight — plan-only journals are still allowed to contain add_file
events, and path_history is a logical projection (not a materialize-only
audit). Sprint 7 removes the materialize gate without touching this set.
"""


def derive_path_history(
    asset_id: str, journal: Iterable[JournalEntry]
) -> list[PathHistoryEntry]:
    """Filter ``journal`` to filesystem entries targeting ``asset_id``.

    Returns entries in journal order (callers should pass a journal that
    is already sorted by ``logical_time_ns`` — same convention as Sprint
    4's ``AssetHistoryEntry`` derivation).
    """
    history: list[PathHistoryEntry] = []
    for entry in journal:
        action = TimelineActionName(entry.action)
        if action not in _FILESYSTEM_ACTIONS:
            continue
        if asset_id not in entry.target_ids:
            continue
        delta = entry.state_delta
        history.append(
            PathHistoryEntry(
                event_id=entry.event_id,
                action=action,
                logical_time_ns=entry.logical_time_ns,
                from_path=(
                    _maybe_str(delta.get("from_path"))
                    or _maybe_str(delta.get("removed_path"))
                    or _maybe_str(delta.get("initial_path_at_start"))
                ),
                to_path=(
                    _maybe_str(delta.get("to_path"))
                    or _maybe_str(delta.get("added_path"))
                    or _maybe_str(delta.get("final_path"))
                    or _maybe_str(delta.get("sidecar_path"))
                ),
                temp_path=_maybe_str(delta.get("temp_path")),
            )
        )
    return history


def _maybe_str(value: object) -> str | None:
    """Return ``value`` if it is a str, else None.

    state_delta values are typed ``object`` at the schema level (the field
    is ``dict[str, object]``). Defensive cast keeps the PathHistoryEntry's
    typed fields honest even if a future handler emits a non-string value
    in one of the path keys.
    """
    return value if isinstance(value, str) else None
```

- [ ] **Step 4: Wire into `engine/reports.py`**

Read `engine/reports.py:build_report_set` (or the equivalent builder for AssetReport). Add a call:

```python
asset_report = AssetReport(
    schema_version=3,
    asset_id=asset.id,
    initial=initial_snapshot,
    history=history_entries,
    current=current_snapshot,
    path_history=derive_path_history(asset.id, journal),
)
```

Import: `from chaos_librarian.engine.path_history import derive_path_history`.

- [ ] **Step 5: Update `tests/engine/test_reports.py`**

Find the existing AssetReport-construction tests; add assertions on `report.path_history`. At minimum: one test asserts an empty path_history for a static-library scenario; another asserts a populated path_history for the identity-move-rename scenario.

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/engine -q`

- [ ] **Step 7: Lint, format, type-check, commit**

```bash
git add src/chaos_librarian/engine/path_history.py \
        src/chaos_librarian/engine/reports.py \
        tests/engine/test_path_history.py \
        tests/engine/test_reports.py
git commit -m "$(cat <<'EOF'
feat(engine): per-asset path_history projection on AssetReport

Pure function that filters the journal to one asset's filesystem-affecting
entries and flattens path-bearing state_delta keys into PathHistoryEntry's
typed fields. Mode-agnostic — plan-only and materialize both pass through
the same builder.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: New scenario fixtures (archive-file, move-between-roots, slow-copy-materialize)

**Files:**
- Create: `tests/fixtures/scenarios/archive-file.yaml`.
- Create: `tests/fixtures/scenarios/move-between-roots.yaml`.
- Create: `tests/fixtures/scenarios/slow-copy-materialize.yaml` (for the Layer 4 real-tool run; mandelbrot video source).
- Re-verify: `tests/contract/test_sample_scenarios.py` picks up new fixtures via its corpus walker (no test changes needed; the file iterates the directory).

- [ ] **Step 1: Write `archive-file.yaml`**

```yaml
schema_version: 4
scenario_id: sc_archive_file
seed: 42
duration_scale: short
library:
  roots:
    - id: movies-hd
      path: library/movies-hd
  archive_root: null
works:
  - id: work_001
    title: Test Movie For Archive
    variants:
      - id: variant_001
        label: hd
        bundle:
          id: bundle_001
          assets:
            - id: asset_hd_main
              role: main
              container: mkv
              duration_seconds: 1.0
              video:
                source: mandelbrot
                codec: h264
                resolution: hd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: en
timeline:
  - id: ev_archive_001
    at: 0ns
    action: archive_file
    target: asset_hd_main
```

- [ ] **Step 2: Write `move-between-roots.yaml`**

```yaml
schema_version: 4
scenario_id: sc_move_between_roots
seed: 42
duration_scale: short
library:
  roots:
    - id: movies-hd
      path: library/movies-hd
    - id: cold-storage
      path: library/cold-storage
works:
  - id: work_001
    title: Test Movie For Move-Between-Roots
    variants:
      - id: variant_001
        label: hd
        bundle:
          id: bundle_001
          assets:
            - id: asset_hd_main
              role: main
              container: mkv
              duration_seconds: 1.0
              video:
                source: mandelbrot
                codec: h264
                resolution: hd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: en
timeline:
  - id: ev_mbr_001
    at: 0ns
    action: move_between_roots
    target: asset_hd_main
    from_root_id: movies-hd
    to_root_id: cold-storage
```

- [ ] **Step 3: Write `slow-copy-materialize.yaml`**

Mirror the existing `slow-copy.yaml` but use `video.source: mandelbrot` (the Layer 4 real-tool test needs a source the synthesizer supports; the legacy `slow-copy.yaml` keeps `noise` for the plan-only corpus).

- [ ] **Step 4: Run the corpus test**

Run: `uv run pytest tests/contract/test_sample_scenarios.py -v`

Expected: all fixtures (existing + three new) load through `Scenario.model_validate` without error.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/scenarios/archive-file.yaml \
        tests/fixtures/scenarios/move-between-roots.yaml \
        tests/fixtures/scenarios/slow-copy-materialize.yaml
git commit -m "$(cat <<'EOF'
test(fixtures): add archive-file, move-between-roots, slow-copy-materialize

Three new corpus fixtures exercising the two new timeline actions and a
mandelbrot-source slow-copy scenario sized for the Layer 4 real-tool tests.
The existing slow-copy.yaml keeps video.source=noise for the plan-only
corpus where ffmpeg never runs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Materializer `FilesystemActionError`

**Files:**
- Modify: `src/chaos_librarian/materializer/errors.py`.
- Test: `tests/materializer/test_errors.py` (extend).

- [ ] **Step 1: Write the failing test**

```python
def test_filesystem_action_error_carries_event_id_action_errno():
    cause = OSError(2, "No such file or directory")
    err = FilesystemActionError(
        "move_asset failed for event move_001: no such file",
        event_id="move_001",
        cause=cause,
        action=TimelineActionName.MOVE_ASSET,
        asset_id="asset_hd_main",
    )
    assert err.error_code == "E_MATERIALIZE_FS_FAILED"
    assert err.event_id == "move_001"
    assert err.cause is cause
    assert err.action is TimelineActionName.MOVE_ASSET
    assert err.payload["event_id"] == "move_001"
    assert err.payload["action"] == "move_asset"
    assert err.payload["errno"] == 2
```

- [ ] **Step 2: Run test to verify failure**

- [ ] **Step 3: Implement the class**

In `src/chaos_librarian/materializer/errors.py`, add after `ProbeParseError`:

```python
from chaos_librarian.contract.scenario import TimelineActionName  # add to imports

class FilesystemActionError(MaterializationError):
    """A phase-B helper raised OSError; library/ must be wiped."""

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
        merged_payload: dict[str, object] = dict(payload or {})
        merged_payload.setdefault("event_id", event_id)
        merged_payload.setdefault("action", action.value)
        merged_payload.setdefault("errno", cause.errno)
        super().__init__(message, asset_id=asset_id, field=field, payload=merged_payload)
        self.event_id = event_id
        self.cause = cause
        self.action = action
```

- [ ] **Step 4: Run test, lint, format, type-check, commit**

```bash
git add src/chaos_librarian/materializer/errors.py tests/materializer/test_errors.py
git commit -m "$(cat <<'EOF'
feat(materializer): add FilesystemActionError for phase-B OSError wrapping

Wraps OSError raised by phase-B helpers with event_id, action, and errno on
the payload so the CLI handler can format the failure as JSON without
introspecting __cause__.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 16: Materializer preflight gate (`SUPPORTED_S6_ACTIONS`, `preflight_timeline`)

**Files:**
- Modify: `src/chaos_librarian/materializer/preflight.py`.
- Test: `tests/materializer/test_preflight.py` (create or extend).

- [ ] **Step 1: Write the failing tests**

```python
def test_preflight_timeline_accepts_supported_actions():
    scenario = _scenario_with_timeline([
        ("move_asset", "asset_hd_main", {"to": "movies-hd/new.mkv"}),
        ("rename_file", "asset_hd_main", {"to": "movies-hd/renamed.mkv"}),
        ("archive_file", "asset_hd_main", {}),
        ("move_between_roots", "asset_hd_main",
            {"from_root_id": "movies-hd", "to_root_id": "cold-storage"}),
    ])
    # Should not raise.
    preflight_timeline(scenario)


def test_preflight_timeline_rejects_add_file():
    scenario = _scenario_with_timeline([
        ("delete_file", "asset_hd_main", {}),
        ("add_file", "asset_hd_main", {"to": "movies-hd/new.mkv"}),
    ])
    with pytest.raises(TimelineUnsupportedError) as exc_info:
        preflight_timeline(scenario)
    assert exc_info.value.error_code == "E_MATERIALIZE_TIMELINE_UNSUPPORTED"
    assert exc_info.value.payload["action"] == "add_file"
    assert "add_file" not in exc_info.value.payload["supported"]


def test_preflight_timeline_rejects_reencode_video():
    scenario = _scenario_with_timeline([
        ("reencode_video", "asset_hd_main", {"resolution": "sd", "codec": "h264"}),
    ])
    with pytest.raises(TimelineUnsupportedError):
        preflight_timeline(scenario)


def test_preflight_timeline_empty_timeline_accepted():
    scenario = _scenario_with_timeline([])
    preflight_timeline(scenario)  # no-op
```

- [ ] **Step 2: Run tests to verify failure**

- [ ] **Step 3: Add `SUPPORTED_S6_ACTIONS` and `preflight_timeline`**

In `src/chaos_librarian/materializer/preflight.py` (append):

```python
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer.errors import TimelineUnsupportedError

SUPPORTED_S6_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.MOVE_ASSET,
        TimelineActionName.RENAME_FILE,
        TimelineActionName.DELETE_FILE,
        TimelineActionName.CREATE_SIDECAR,
        TimelineActionName.SLOW_COPY_START,
        TimelineActionName.SLOW_COPY_COMMIT,
        TimelineActionName.ARCHIVE_FILE,
        TimelineActionName.MOVE_BETWEEN_ROOTS,
    }
)
# add_file is intentionally excluded; preflight rejects it with
# E_MATERIALIZE_TIMELINE_UNSUPPORTED (deferred to Sprint 7 alongside
# recipe-driven byte synthesis).


def preflight_timeline(scenario: Scenario) -> None:
    """Reject any timeline event whose action is outside SUPPORTED_S6_ACTIONS.

    Raised before phase A so the matrix-rejection contract (no run-dir
    allocation, exit 5, E_MATERIALIZE_TIMELINE_UNSUPPORTED) holds.
    """
    for index, event in enumerate(scenario.timeline):
        if event.action not in SUPPORTED_S6_ACTIONS:
            raise TimelineUnsupportedError(
                f"timeline action {event.action.value!r} not supported in Sprint 6",
                field=f"timeline[{index}].action",
                payload={
                    "event_id": event.id,
                    "action": event.action.value,
                    "supported": sorted(a.value for a in SUPPORTED_S6_ACTIONS),
                },
            )
```

Update `__all__` to include `SUPPORTED_S6_ACTIONS` and `preflight_timeline`.

- [ ] **Step 4: Run tests, lint, format, type-check, commit**

```bash
git add src/chaos_librarian/materializer/preflight.py tests/materializer/test_preflight.py
git commit -m "$(cat <<'EOF'
feat(materializer): preflight_timeline gates Sprint 6 timeline actions

SUPPORTED_S6_ACTIONS lists the eight filesystem actions Sprint 6 executes.
preflight_timeline raises TimelineUnsupportedError (existing code
E_MATERIALIZE_TIMELINE_UNSUPPORTED, re-purposed from Sprint 5's
"any-non-empty" semantic) on the first event outside that set, before
phase A allocates a run-dir.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 17: Materializer `filesystem.py` — per-action helpers, dispatcher, `apply_phase_b`

**The bulkiest task.** Split into sub-steps; commit only at the end.

**Files:**
- Create: `src/chaos_librarian/materializer/filesystem.py`.
- Test: `tests/materializer/test_filesystem.py` (new file).

- [ ] **Step 1: Sketch the module skeleton**

Create `src/chaos_librarian/materializer/filesystem.py`:

```python
"""Phase-B disk effects for materialize mode (Sprint 6+).

The dispatcher walks the engine-produced journal and applies real
filesystem effects against ``<run-dir>/library/``. Composition is
strictly one-directional: this module imports engine + contract but
no engine module imports back.

``_PhaseBContext`` carries three pieces of incremental state alongside
the walk: ``pending_slow_copy`` (start→commit bookkeeping),
``phase_b_sidecar_hashes`` (drained after the walk by
``manifest_build.augment_timeline_sidecars``), and a read-only
``scenario_assets`` lookup for metadata. Each per-action helper reads
its source path from ``entry.state_delta`` — the journal is the truth
source — so there is no cached path-tracking map.

Raises ``FilesystemActionError`` on the first ``OSError`` so the
orchestrator can route through ``cleanup_failed_run``.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.materialization import FilesystemAction
from chaos_librarian.contract.scenario import (
    Asset,
    Scenario,
    TimelineActionName,
)
from chaos_librarian.materializer.errors import FilesystemActionError
from chaos_librarian.materializer.recipes import srt_payload

__all__ = ["apply_phase_b"]


@dataclass(frozen=True, slots=True)
class _PendingSlowCopy:
    asset_id: str
    initial_path: str
    temp_path: str


@dataclass(slots=True)
class _PhaseBContext:
    library_root: Path
    scenario_assets: Mapping[str, Asset]
    resolved_seed: int
    pending_slow_copy: dict[str, _PendingSlowCopy] = field(default_factory=dict)
    phase_b_sidecar_hashes: dict[str, str] = field(default_factory=dict)


def apply_phase_b(
    *,
    library_root: Path,
    journal: Sequence[JournalEntry],
    scenario: Scenario,
    resolved_seed: int,
) -> tuple[list[FilesystemAction], dict[str, str]]:
    """Walk the journal and apply real filesystem effects.

    Returns:
        (filesystem_actions, phase_b_sidecar_hashes). The hash dict is
        consumed by ``manifest_build.augment_timeline_sidecars`` to stamp
        ``content_hash`` on timeline-created ``ManifestSidecar`` rows.

    Raises:
        FilesystemActionError: on the first ``OSError`` from a phase-B
            helper. The orchestrator catches it, routes through
            ``cleanup_failed_run``, and exits 5.
    """
    ctx = _PhaseBContext(
        library_root=library_root,
        scenario_assets=_index_assets(scenario),
        resolved_seed=resolved_seed,
    )
    actions: list[FilesystemAction] = []
    for entry in journal:
        action = _dispatch_one(ctx, entry)
        if action is not None:
            actions.append(action)
    return actions, dict(ctx.phase_b_sidecar_hashes)


def _index_assets(scenario: Scenario) -> dict[str, Asset]:
    out: dict[str, Asset] = {}
    for work in scenario.works:
        for variant in work.variants:
            for asset in variant.bundle.assets:
                out[asset.id] = asset
    return out


def _dispatch_one(ctx: _PhaseBContext, entry: JournalEntry) -> FilesystemAction | None:
    """Dispatch one journal entry to its helper; fill duration_ns.

    Returns None if the action is not a filesystem effect (i.e. it is in
    the engine's journal but the materializer does not act on it — e.g.
    a media mutation; though Sprint 6 preflight prevents this case from
    reaching apply_phase_b).
    """
    action = TimelineActionName(entry.action)
    handler = _DISPATCH.get(action)
    if handler is None:
        return None
    started = time.monotonic_ns()
    try:
        result = handler(ctx, entry)
    except OSError as exc:
        target_asset = entry.target_ids[0] if entry.target_ids else None
        raise FilesystemActionError(
            f"{entry.action} failed for event {entry.event_id}: {exc}",
            event_id=entry.event_id,
            cause=exc,
            action=action,
            asset_id=target_asset,
        ) from exc
    return result.model_copy(update={"duration_ns": time.monotonic_ns() - started})


# … per-action helpers below …
```

- [ ] **Step 2: Add the per-action helpers**

Append the seven helpers. Each follows the same shape: read paths from
`entry.state_delta`, perform the I/O, update `ctx.pending_slow_copy` /
`ctx.phase_b_sidecar_hashes` as appropriate, and return a
`FilesystemAction` with `duration_ns=0`. The journal is the truth source
for source paths — no helper caches them in incremental state.

```python
def _move_asset(ctx: _PhaseBContext, entry: JournalEntry) -> FilesystemAction:
    """Move a file in-place. Shared body for move_asset / rename_file /
    archive_file / move_between_roots."""
    asset_id = entry.target_ids[0]
    from_path = str(entry.state_delta["from_path"])
    to_path = str(entry.state_delta["to_path"])
    src = ctx.library_root / from_path
    dst = ctx.library_root / to_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.replace(dst)
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName(entry.action),
        target_asset_id=asset_id,
        from_path=from_path,
        to_path=to_path,
        temp_path=None,
        duration_ns=0,
    )


def _delete_file(ctx: _PhaseBContext, entry: JournalEntry) -> FilesystemAction:
    asset_id = entry.target_ids[0]
    removed_path = str(entry.state_delta["removed_path"])
    (ctx.library_root / removed_path).unlink()
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.DELETE_FILE,
        target_asset_id=asset_id,
        from_path=removed_path,
        to_path=None,
        temp_path=None,
        duration_ns=0,
    )


def _create_sidecar(ctx: _PhaseBContext, entry: JournalEntry) -> FilesystemAction:
    import hashlib

    asset_id = entry.target_ids[0]
    sidecar_path = str(entry.state_delta["sidecar_path"])
    sidecar_id = str(entry.state_delta["sidecar_id"])
    language = str(entry.state_delta["language"])
    asset = ctx.scenario_assets[asset_id]
    body = srt_payload(
        language=language,
        duration_s=asset.duration_seconds,
        seed=ctx.resolved_seed,
    )
    dst = ctx.library_root / sidecar_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(body)
    ctx.phase_b_sidecar_hashes[sidecar_id] = hashlib.sha256(body).hexdigest()
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.CREATE_SIDECAR,
        target_asset_id=asset_id,
        from_path=None,
        to_path=sidecar_path,
        temp_path=None,
        duration_ns=0,
    )


def _slow_copy_start(ctx: _PhaseBContext, entry: JournalEntry) -> FilesystemAction:
    asset_id = entry.target_ids[0]
    initial_path = str(entry.state_delta["initial_path_at_start"])
    temp_path = str(entry.state_delta["temp_path"])
    src = ctx.library_root / initial_path
    dst = ctx.library_root / temp_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(src.read_bytes())
    ctx.pending_slow_copy[entry.event_id] = _PendingSlowCopy(
        asset_id=asset_id,
        initial_path=initial_path,
        temp_path=temp_path,
    )
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.SLOW_COPY_START,
        target_asset_id=asset_id,
        from_path=initial_path,
        to_path=str(entry.state_delta["final_path"]),
        temp_path=temp_path,
        duration_ns=0,
    )


def _slow_copy_commit(ctx: _PhaseBContext, entry: JournalEntry) -> FilesystemAction:
    pending_id = entry.related_event_id
    pending = ctx.pending_slow_copy.pop(pending_id)
    final_path = str(entry.state_delta["final_path"])
    if pending.initial_path != final_path:
        (ctx.library_root / pending.initial_path).unlink(missing_ok=True)
    (ctx.library_root / pending.temp_path).replace(ctx.library_root / final_path)
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.SLOW_COPY_COMMIT,
        target_asset_id=pending.asset_id,
        from_path=pending.temp_path,
        to_path=final_path,
        temp_path=None,
        duration_ns=0,
    )


_DISPATCH: Final[dict[TimelineActionName, Callable[..., FilesystemAction]]] = {
    TimelineActionName.MOVE_ASSET: _move_asset,
    TimelineActionName.RENAME_FILE: _move_asset,
    TimelineActionName.DELETE_FILE: _delete_file,
    TimelineActionName.CREATE_SIDECAR: _create_sidecar,
    TimelineActionName.SLOW_COPY_START: _slow_copy_start,
    TimelineActionName.SLOW_COPY_COMMIT: _slow_copy_commit,
    TimelineActionName.ARCHIVE_FILE: _move_asset,
    TimelineActionName.MOVE_BETWEEN_ROOTS: _move_asset,
}
```

Re-check: `srt_payload` exists in `materializer/recipes.py`? Verify via `rg "def srt_payload" src/chaos_librarian/materializer/`. If the existing helper has a different name (e.g. `generate_srt_payload`), adjust the import. If no equivalent exists, file an issue (per CLAUDE.md Rule 13) and stub it in this task with a TODO referencing the issue.

- [ ] **Step 3: Write the per-action helper tests**

Create `tests/materializer/test_filesystem.py`. One test per dispatch case, each running against a `tmp_path` library_root:

```python
def test_apply_move_asset_renames_file(tmp_path):
    library = tmp_path / "library"
    (library / "movies-hd").mkdir(parents=True)
    (library / "movies-hd" / "asset_hd_main.mkv").write_bytes(b"bytes")
    scenario = _build_minimal_scenario(...)
    journal = [_atomic_entry(
        event_id="move_001",
        action=TimelineActionName.MOVE_ASSET,
        target="asset_hd_main",
        state_delta={
            "from_path": "movies-hd/asset_hd_main.mkv",
            "to_path": "movies-hd/renamed.mkv",
        },
    )]
    actions, sidecar_hashes = apply_phase_b(
        library_root=library,
        journal=journal,
        scenario=scenario,
        resolved_seed=1234,
    )
    assert not (library / "movies-hd" / "asset_hd_main.mkv").exists()
    assert (library / "movies-hd" / "renamed.mkv").read_bytes() == b"bytes"
    assert len(actions) == 1
    assert actions[0].action == TimelineActionName.MOVE_ASSET
    assert actions[0].duration_ns > 0


def test_apply_rename_file_is_alias_of_move(tmp_path):
    # Same body as move; assert action field carries RENAME_FILE not MOVE_ASSET
    ...


def test_apply_delete_file_unlinks(tmp_path):
    ...


def test_apply_archive_file_moves_to_archive_root(tmp_path):
    ...


def test_apply_archive_file_with_explicit_root(tmp_path):
    ...


def test_apply_move_between_roots_crosses_roots(tmp_path):
    ...


def test_apply_create_sidecar_writes_srt_and_returns_hash_keyed_by_sidecar_id(tmp_path):
    library = tmp_path / "library"
    library.mkdir()
    scenario = _build_minimal_scenario(...)
    journal = [_atomic_entry(
        event_id="cs_001",
        action=TimelineActionName.CREATE_SIDECAR,
        target="asset_hd_main",
        state_delta={
            "sidecar_path": "movies-hd/asset_hd_main.en.srt",
            "sidecar_id": "sidecar_0001",
            "language": "en",
        },
    )]
    _, sidecar_hashes = apply_phase_b(
        library_root=library,
        journal=journal,
        scenario=scenario,
        resolved_seed=1234,
    )
    assert (library / "movies-hd" / "asset_hd_main.en.srt").exists()
    assert "sidecar_0001" in sidecar_hashes
    # Hash must be sha256-shaped (hex, 64 chars).
    assert len(sidecar_hashes["sidecar_0001"]) == 64


def test_apply_slow_copy_start_writes_full_bytes_to_temp_path(tmp_path):
    ...


def test_apply_slow_copy_commit_renames_temp_to_final(tmp_path):
    ...


def test_apply_slow_copy_commit_unlinks_initial_when_different_from_final(tmp_path):
    ...


def test_apply_unknown_action_returns_none_from_dispatch(tmp_path):
    """Defense in depth: a journal entry whose action is not in _DISPATCH
    is dropped (not raised). Sprint 6 preflight prevents this case but the
    dispatcher must not crash if a future sprint adds an engine-only action."""
    ...


def test_apply_oserror_wraps_into_FilesystemActionError(tmp_path, monkeypatch):
    library = tmp_path / "library"
    library.mkdir()
    scenario = _build_minimal_scenario(...)
    # Move a file that doesn't exist.
    journal = [_atomic_entry(
        event_id="move_missing",
        action=TimelineActionName.MOVE_ASSET,
        target="asset_hd_main",
        state_delta={"from_path": "ghost.mkv", "to_path": "movies-hd/new.mkv"},
    )]
    with pytest.raises(FilesystemActionError) as exc_info:
        apply_phase_b(
            library_root=library,
            journal=journal,
            scenario=scenario,
            resolved_seed=1234,
        )
    err = exc_info.value
    assert err.event_id == "move_missing"
    assert err.action == TimelineActionName.MOVE_ASSET
    assert err.payload["errno"] == 2
```

The `_atomic_entry` helper constructs a typed `AtomicJournalEntry` via the appropriate adapter.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/materializer/test_filesystem.py -v`

- [ ] **Step 5: Lint, format, type-check, commit**

```bash
git add src/chaos_librarian/materializer/filesystem.py tests/materializer/test_filesystem.py
git commit -m "$(cat <<'EOF'
feat(materializer): phase-B dispatcher + per-action filesystem helpers

apply_phase_b walks the engine-produced journal and applies real filesystem
effects against <run-dir>/library/. Each per-action helper reads paths from
state_delta and updates incremental state (pending_slow_copy,
phase_b_sidecar_hashes). OSError wraps into FilesystemActionError so the
orchestrator can route through cleanup_failed_run.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 18: `manifest_build.augment_timeline_sidecars`

**Files:**
- Modify: `src/chaos_librarian/materializer/manifest_build.py`.
- Test: `tests/materializer/test_manifest_build.py` (or wherever existing `augment_manifest` tests live).

- [ ] **Step 1: Read `manifest_build.py`**

Confirm the augment-pattern convention (mutate-in-place vs return-new) and follow it. Look at how `augment_manifest` modifies sidecar rows in particular — `augment_timeline_sidecars` should match.

- [ ] **Step 2: Write the failing test**

```python
def test_augment_timeline_sidecars_stamps_hash_on_matching_row():
    manifest = _build_manifest_with_sidecar(
        sidecar_id="sidecar_0001",
        asset_id="asset_hd_main",
        language="en",
        path="movies-hd/asset_hd_main.en.srt",
        content_hash=None,
    )
    augment_timeline_sidecars(
        manifest,
        {"sidecar_0001": "abc123" * 10 + "abc1"},  # 64-char fake sha
    )
    sidecar = next(s for s in manifest.sidecars if s.id == "sidecar_0001")
    assert sidecar.content_hash == "abc123" * 10 + "abc1"


def test_augment_timeline_sidecars_leaves_unmatched_rows_alone():
    """Declared sidecars (whose content_hash was populated by augment_manifest)
    must not be touched by augment_timeline_sidecars."""
    manifest = _build_manifest_with_sidecar(
        sidecar_id="sidecar_declared",
        asset_id="asset_hd_main",
        language="en",
        path="...",
        content_hash="declared-hash",
    )
    augment_timeline_sidecars(manifest, {"sidecar_timeline": "timeline-hash"})
    sidecar = next(s for s in manifest.sidecars if s.id == "sidecar_declared")
    assert sidecar.content_hash == "declared-hash"


def test_augment_timeline_sidecars_empty_dict_noop():
    manifest = _build_manifest_with_sidecar(...)
    augment_timeline_sidecars(manifest, {})
    # … assert unchanged
```

- [ ] **Step 3: Implement `augment_timeline_sidecars`**

In `src/chaos_librarian/materializer/manifest_build.py`:

```python
def augment_timeline_sidecars(
    manifest: Manifest, phase_b_sidecar_hashes: Mapping[str, str]
) -> None:
    """Stamp content_hash on timeline-created sidecar rows by sidecar_id.

    Sprint 5's ``augment_manifest`` covers declared subtitles (keyed by
    ``(asset_id, language)``); Sprint 6's timeline-created sidecars need
    a separate path because the engine handler allocates a fresh sidecar_id
    and the bytes are hashed inside phase B, not phase A.

    Rows whose ``id`` is not present in ``phase_b_sidecar_hashes`` are
    left unchanged — declared subtitles stay at their phase-A hash, and
    timeline sidecars whose hash didn't make it into the map (impossible
    in practice; defensive) keep ``content_hash=None``.
    """
    # Follow the in-place-mutation pattern of augment_manifest. If
    # Manifest is frozen, this function should return a new Manifest;
    # adjust accordingly after reading manifest_build.py.
    ...
```

If `Manifest` is frozen, the function returns a new `Manifest`; `run.py` rebinds. If not, mutate in place.

- [ ] **Step 4: Run tests, lint, format, type-check, commit**

```bash
git add src/chaos_librarian/materializer/manifest_build.py tests/materializer/test_manifest_build.py
git commit -m "$(cat <<'EOF'
feat(materializer): augment_timeline_sidecars stamps phase-B sidecar hashes

Mirrors Sprint 5's augment_manifest for declared subtitles, but keys on
sidecar_id (engine-allocated) rather than (asset_id, language). The two
augment helpers never share keys: declared sidecars are hashed in phase A,
timeline sidecars in phase B.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 19: `run.py` orchestration — remove static-only gate, wire preflight + phase B + augment

**The most-interacting task.** Touches the materialize entry point.

**Files:**
- Modify: `src/chaos_librarian/materializer/run.py`.
- Modify: `src/chaos_librarian/materializer/finalize.py` — thread `filesystem_actions` through `MaterializationReport`.
- Test: `tests/materializer/test_run.py` (extend).

- [ ] **Step 1: Write the failing orchestrator tests**

```python
def test_materialize_filesystem_only_timeline_runs_phase_b(
    tmp_path, monkeypatch
):
    """Identity-move-rename scenario; ffmpeg / probe patched."""
    _mock_ffmpeg(monkeypatch, stub_bytes=b"\x00" * 100)
    _mock_probe(monkeypatch)
    out_dir = tmp_path / "run-001"
    artifacts = materialize_scenario(
        Path("tests/fixtures/scenarios/identity-move-rename.yaml"),
        out_dir,
    )
    assert artifacts.outcome == Outcome.SUCCESS
    library = out_dir / "library"
    # The fixture moves then renames — final path is the rename target.
    # Read the fixture or hardcode the assertion based on its events.
    assert (library / "movies-hd" / "Blazar.mkv").exists()
    report = _load_materialization_report(out_dir)
    assert len(report.filesystem_actions) == 2


def test_materialize_reencode_video_rejected_at_preflight(tmp_path, monkeypatch):
    """Mixed scenario: pre-flight rejects before any FS work."""
    out_dir = tmp_path / "run-001"
    with pytest.raises(TimelineUnsupportedError) as exc_info:
        materialize_scenario(
            Path("tests/fixtures/scenarios/reencode-video.yaml"),  # add if missing
            out_dir,
        )
    assert not out_dir.exists()  # lazy allocation invariant
    assert exc_info.value.payload["action"] == "reencode_video"


def test_materialize_phase_b_oserror_aborts_and_cleans_up(tmp_path, monkeypatch):
    _mock_ffmpeg(monkeypatch, stub_bytes=b"\x00" * 100)
    _mock_probe(monkeypatch)
    # Monkeypatch _move_asset to raise on the 3rd call.
    call_count = {"n": 0}
    original = filesystem._move_asset

    def crashing_move(ctx, entry):
        call_count["n"] += 1
        if call_count["n"] == 3:
            raise OSError(2, "No such file or directory")
        return original(ctx, entry)

    monkeypatch.setattr(filesystem, "_move_asset", crashing_move)
    monkeypatch.setattr(filesystem, "_DISPATCH", {
        **filesystem._DISPATCH,
        TimelineActionName.MOVE_ASSET: crashing_move,
        TimelineActionName.RENAME_FILE: crashing_move,
    })
    out_dir = tmp_path / "run-001"
    with pytest.raises(FilesystemActionError):
        materialize_scenario(Path("tests/fixtures/scenarios/identity-move-rename.yaml"), out_dir)
    assert not (out_dir / "library").exists()  # library/ wiped on cleanup
    report = _load_materialization_report(out_dir)
    assert report.outcome == Outcome.FS_FAILED
    assert any(f.stage == FailureStage.FILESYSTEM for f in report.failures)
```

- [ ] **Step 2: Update `run.py`**

In `src/chaos_librarian/materializer/run.py`, modify `materialize_scenario`:

1. Remove the `if scenario.timeline: raise TimelineUnsupportedError(...)` block at lines ~87-92.
2. Add `preflight_timeline(scenario)` immediately after the validation pass (before capability detection — preflight is cheap and matrix-rejection-style, so it should run before any other gate).
3. Below the existing per-asset synthesis loop in `_run_synthesis`, add the phase-B call:

```python
def _run_synthesis(ctx: RunContext, scenario: Scenario) -> MaterializeArtifacts:
    invocations: list[ToolInvocation] = []
    materialized: list[MaterializedAsset] = []
    filesystem_actions: list[FilesystemAction] = []
    try:
        # Phase A — synthesis loop, unchanged from Sprint 5.
        for invocation_index, asset in enumerate(iter_assets(scenario)):
            invocation, materialized_asset, probed, sidecar_hashes = materialize_one_asset(
                asset,
                ctx.plan_artifacts.replay_bundle.resolved_seed,
                ctx.out_dir,
                ctx.caps,
                invocation_index,
            )
            invocations.append(invocation)
            materialized.append(materialized_asset)
            augment_manifest(
                ctx.plan_artifacts.current_manifest,
                asset,
                materialized_asset,
                probed,
                sidecar_hashes,
            )

        # Phase B — timeline application. New in Sprint 6.
        filesystem_actions, phase_b_sidecar_hashes = apply_phase_b(
            library_root=ctx.out_dir / "library",
            journal=ctx.plan_artifacts.journal,
            scenario=ctx.run_input.scenario,
            resolved_seed=ctx.plan_artifacts.replay_bundle.resolved_seed,
        )
        augment_timeline_sidecars(
            ctx.plan_artifacts.current_manifest, phase_b_sidecar_hashes
        )
    except (ToolFailedError, ProbeParseError) as exc:
        if isinstance(exc, ToolFailedError):
            invocations.append(exc.invocation)
        finalize_failure(ctx, exc, Outcome.TOOL_FAILED, invocations, materialized)
        raise
    except FilesystemActionError as exc:
        finalize_failure_filesystem(
            ctx, exc, invocations, materialized, filesystem_actions,
        )
        raise
    return finalize_success(
        ctx, invocations, materialized, filesystem_actions,
    )
```

Add the new imports at the top:

```python
from chaos_librarian.contract.materialization import FilesystemAction
from chaos_librarian.materializer.errors import FilesystemActionError
from chaos_librarian.materializer.filesystem import apply_phase_b
from chaos_librarian.materializer.manifest_build import augment_timeline_sidecars
from chaos_librarian.materializer.preflight import preflight_timeline
```

- [ ] **Step 3: Update `finalize.py`**

In `src/chaos_librarian/materializer/finalize.py`, extend `finalize_success` and `finalize_failure` to accept a `filesystem_actions` parameter and thread it into `build_report`. Add a new helper `finalize_failure_filesystem` that:

1. Builds a `MaterializationFailure(asset_id=exc.asset_id, stage=FailureStage.FILESYSTEM, exit_code=None, stderr_tail=str(exc.cause), invocation_index=None)`.
2. Runs `shutil.rmtree(ctx.out_dir / "library", ignore_errors=True)`.
3. Writes the report with `outcome=Outcome.FS_FAILED`.
4. Flips the sentinel to `complete` (matching Sprint 5's clean-failure model).

Read the existing `finalize_failure` and mirror its shape.

- [ ] **Step 4: Run the orchestrator tests**

Run: `uv run pytest tests/materializer/test_run.py -v`

If a new fixture is needed (e.g. `tests/fixtures/scenarios/reencode-video.yaml` for the rejection test), add it.

- [ ] **Step 5: Run the full materializer test suite**

Run: `uv run pytest tests/materializer -v`

Expected: pass (including the existing tests that constructed `MaterializationReport(schema_version=2, ...)` — Task 3 may have marked some as skip/TODO; un-skip them now and bump the literal to 3).

- [ ] **Step 6: Lint, format, type-check, commit**

```bash
git add src/chaos_librarian/materializer/run.py \
        src/chaos_librarian/materializer/finalize.py \
        tests/materializer/test_run.py \
        tests/fixtures/scenarios/reencode-video.yaml  # if added
git commit -m "$(cat <<'EOF'
feat(materializer): wire phase B into the orchestrator

materialize_scenario no longer rejects non-empty timelines; instead
preflight_timeline gates Sprint 6's supported action set. After phase A,
apply_phase_b walks the journal and applies real filesystem effects;
augment_timeline_sidecars stamps content_hash on timeline-created sidecar
rows. On FilesystemActionError, library/ is wiped and the report records
outcome=fs_failed.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 20: CLI materialize dispatch — handle `FilesystemActionError`

**Files:**
- Modify: `src/chaos_librarian/cli/app.py` (or `cli/run.py`, whichever owns the materialize entry).
- Test: `tests/cli/test_materialize_sprint6.py` (new file).

- [ ] **Step 1: Find the CLI dispatcher**

Read the existing materialize-command implementation in `src/chaos_librarian/cli/`. The dispatch pattern is per-exception-subclass:

```python
try:
    artifacts = materialize_scenario(scenario_path, out_dir)
except TimelineUnsupportedError as exc:
    _emit_error_json(exc); raise typer.Exit(5)
except ToolFailedError as exc:
    ...
```

- [ ] **Step 2: Write the failing CLI test**

```python
def test_cli_materialize_fs_failed_exits_5_with_event_id_in_payload(
    tmp_path, monkeypatch
):
    """End-to-end CLI test: mocked orchestrator raises FilesystemActionError."""
    def boom(*args, **kwargs):
        raise FilesystemActionError(
            "move_asset failed for event move_001: no such file",
            event_id="move_001",
            cause=OSError(2, "No such file or directory"),
            action=TimelineActionName.MOVE_ASSET,
            asset_id="asset_hd_main",
        )
    monkeypatch.setattr("chaos_librarian.cli.app.materialize_scenario", boom)
    result = runner.invoke(
        app, ["materialize", "tests/fixtures/scenarios/identity-move-rename.yaml",
              "--out", str(tmp_path / "run-001")],
    )
    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "E_MATERIALIZE_FS_FAILED"
    assert payload["event_id"] == "move_001"
    assert payload["action"] == "move_asset"
    assert payload["asset_id"] == "asset_hd_main"
    assert payload["errno"] == 2
```

- [ ] **Step 3: Add the dispatch branch**

Pattern-match the existing `ToolFailedError` dispatch. The new branch:

```python
except FilesystemActionError as exc:
    _emit_materialize_error_json(exc, out_dir, include_report=True)
    raise typer.Exit(5) from exc
```

`include_report=True` causes the JSON to include `materialization_report_path` (Sprint 5's existing pattern for failures that did write a report).

- [ ] **Step 4: Run tests, lint, format, type-check, commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_materialize_sprint6.py
git commit -m "$(cat <<'EOF'
feat(cli): materialize dispatches FilesystemActionError to exit 5

JSON payload carries error_code, event_id, action, asset_id, errno, and
materialization_report_path so adapters can correlate the failure with
the on-disk report.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 21: Layer 4 real-tool integration tests

**Files:**
- Create: `tests/integration/test_materialize_sprint6_real.py`.

These tests run `materialize_scenario` against real ffmpeg/ffprobe. They are `pytest.mark.skipif(not _ffmpeg_meets_minimum(), ...)`-gated; CI runs them on an ffmpeg-equipped runner.

**The EXIT CRITERION lives here:** `test_identity_move_rename_end_to_end`.

- [ ] **Step 1: Read the existing real-tool tests**

Read `tests/integration/test_materialize_real.py` (Sprint 5) to understand the `_ffmpeg_meets_minimum` gate and the existing test patterns. Copy the skipif marker, fixture layout, and bytes-comparison style.

- [ ] **Step 2: Write the exit-criterion test**

```python
def test_identity_move_rename_end_to_end(tmp_path):
    """EXIT CRITERION. Identity-move-rename runs end-to-end on a real directory."""
    out_dir = tmp_path / "run-001"
    artifacts = materialize_scenario(
        Path("tests/fixtures/scenarios/identity-move-rename.yaml"),
        out_dir,
    )
    assert artifacts.outcome == Outcome.SUCCESS

    library = out_dir / "library"
    # Read the fixture's final-event target — current fixture renames to
    # Blazar.mkv; update if the fixture changes.
    final_path = library / "movies-hd" / "Blazar.mkv"
    assert final_path.exists()
    assert sha256_of(final_path) == _initial_sha256_for("asset_hd_main", out_dir)

    initial_path = library / "movies-hd" / "asset_hd_main.mkv"
    assert not initial_path.exists()

    manifest = _load_current_manifest(out_dir)
    asset_loc = next(
        loc for loc in manifest.locations if loc.asset_id == "asset_hd_main"
    )
    assert asset_loc.path == "movies-hd/Blazar.mkv"

    asset_report = _load_asset_report(out_dir, "asset_hd_main")
    assert [e.action for e in asset_report.path_history] == [
        TimelineActionName.MOVE_ASSET,
        TimelineActionName.RENAME_FILE,
    ]

    materialization_report = _load_materialization_report(out_dir)
    assert len(materialization_report.filesystem_actions) == 2

    replay_bundle = _load_replay_bundle(out_dir)
    assert replay_bundle.applied_events == 2
```

- [ ] **Step 3: Write the remaining Layer 4 tests**

Each test follows the same pattern — invoke `materialize_scenario`, assert on-disk state + report contents. The tests:

- `test_slow_copy_real_visibility` — runs `slow-copy-materialize.yaml` (Task 14 fixture). Asserts:
  - After phase B, `library/movies-hd/Nova.mkv` exists.
  - `library/movies-hd/Nova.mkv.part` does NOT exist (commit cleaned up).
  - `manifest.current` shows `location.path = "movies-hd/Nova.mkv"`, `temp_path = None`.
  - `content_hash` matches the file's actual sha256.

- `test_archive_file_real` — runs `archive-file.yaml` with default `archive_root: null`. Asserts the file ends up at `library/movies-hd/archive/asset_hd_main.mkv`.

- `test_archive_file_real_with_explicit_root` — variant fixture with `archive_root: "cold-storage"`. Asserts file ends up under the named root.

- `test_move_between_roots_real` — runs `move-between-roots.yaml`. Asserts the file crossed from `movies-hd/` to `cold-storage/`.

- `test_create_sidecar_real_via_timeline` — new fixture with a timeline `create_sidecar` event (not declared on `asset.subtitles`). Asserts: SRT file exists at the event's `to:` path, `manifest.sidecars` carries the row with `content_hash` populated, the row's `id` matches the event's allocated `sidecar_id` (read from the journal).

- `test_create_sidecar_collides_with_declared_subtitle` — fixture declares one English subtitle + a `create_sidecar` event for the same `(asset_id, language)`. Asserts:
  - `manifest.sidecars` contains TWO entries for that `(asset_id, language)`.
  - Distinct `sidecar_id` values.
  - Distinct on-disk paths (declared in `manifest.augment_manifest`'s output, timeline at the event's `to:`).
  - Both `content_hash` values populated (declared from phase A, timeline from phase B).

- `test_phase_b_failure_cleans_library` — hand-crafted scenario where a `delete_file` targets an asset whose path was tampered with (a `pytest.fixture` pre-deletes the file before phase B runs). Asserts:
  - Exit 5.
  - `library/` wiped.
  - `materialization.json` present with `outcome="fs_failed"`, `failures[0].stage="filesystem"`, `failures[0].invocation_index=None`.

- `test_mixed_supported_unsupported_action_rejected` — scenario with one `move_asset` (supported) and one `reencode_video` (unsupported). Asserts: exit 5 with `E_MATERIALIZE_TIMELINE_UNSUPPORTED`, no run-dir allocated (`not out_dir.exists()`).

For each test, populate the assertions referenced above; do NOT leave placeholders. Use the helpers from existing Sprint 5 real-tool tests (`sha256_of`, `_load_current_manifest`, etc.).

- [ ] **Step 4: Run the Layer 4 tests**

Run: `uv run pytest tests/integration/test_materialize_sprint6_real.py -v`

On a system without ffmpeg, they should skip cleanly. On a system with ffmpeg >= the project minimum, they should all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_materialize_sprint6_real.py \
        tests/fixtures/scenarios/  # any fixtures added for sidecar collision, etc.
git commit -m "$(cat <<'EOF'
test(integration): Sprint 6 exit criterion + supporting real-tool tests

Identity-move-rename runs end-to-end on a real directory; slow_copy
visibility, archive_file, move_between_roots, timeline-created sidecars
(including the (asset_id, language) collision case), phase-B failure
cleanup, and mixed-unsupported rejection round out the Layer 4 surface.
Skip-if-not-installed gate matches the existing Sprint 5 convention.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 22: Final verification

**No code changes.** Final pass over the whole sprint output before requesting review.

- [ ] **Step 1: Schema drift gate is clean**

Run: `uv run python -m chaos_librarian.schema_export --check`

Expected: exit 0. If it fails, the contract source-of-truth and the committed JSON Schema disagree; rerun `--write` and add the diff to a commit.

- [ ] **Step 2: Full pytest suite**

Run: `uv run pytest -q`

Expected: all tests pass. Layer 4 tests skip if ffmpeg is unavailable.

Then explicitly run the Layer 4 integration tests and assert they did NOT skip — `pytest -q` prints "all passed" even when ffmpeg-gated tests are quietly skipped, which would let the exit-criterion check pass without ever running:

```bash
uv run pytest tests/integration/test_materialize_sprint6_real.py -v \
  --no-header 2>&1 | tee /tmp/s6-integ.log
if grep -q "SKIPPED" /tmp/s6-integ.log; then
  echo "ERROR: Layer 4 tests skipped — exit criterion is unverified."
  echo "Install ffmpeg >= the project minimum and re-run."
  exit 1
fi
```

Expected: every test ran (PASSED) with no SKIPPED markers. If ffmpeg is unavailable on the development machine, mark this step as BLOCKED in the task list and run on an ffmpeg-equipped machine (or CI) before opening the PR — do not tick the box.

- [ ] **Step 3: Ruff lint + format**

Run: `uv run ruff check . && uv run ruff format --check .`

Expected: no warnings, no formatting drift.

- [ ] **Step 4: ty type check**

Run: `uv run ty check src tests`

Expected: clean.

- [ ] **Step 5: prek hooks**

Run: `prek run --all-files`

Expected: pass.

- [ ] **Step 6: Re-read the spec; cross-check every requirement has a task**

Open `docs/superpowers/specs/2026-05-19-sprint-6-design.md` and walk each section. Verify:

- Every new contract field, model, enum, event variant is committed (Tasks 1-3).
- Every engine handler / state extension / state_delta key is committed (Tasks 4-8).
- Every validation rule, lifecycle extension, path containment branch is committed (Tasks 9-12).
- Every materializer module / phase-B helper / orchestration wiring is committed (Tasks 15-20).
- Every fixture in the Layer 1-5 corpus is committed (Tasks 14, 21).
- `test_identity_move_rename_end_to_end` actually executed (not skipped) — the SKIPPED-check in Step 2 covers this; cross-reference here for clarity.

If any spec requirement has no committing task, file a GitHub issue (per CLAUDE.md Rule 13) with title "Sprint 6 spec coverage gap: <thing>".

- [ ] **Step 7: Final commit (if any)**

If any of Steps 1-6 surfaced trivial fixes (formatting drift, a missing schema regen, etc.), commit them with a `chore(sprint-6): final cleanup` message.

- [ ] **Step 8: Open the pull request**

Use the project convention (see CLAUDE.md and `gh pr create`):

```bash
gh pr create --title "Sprint 6: filesystem mutations + per-asset path_history" \
  --body "$(cat <<'EOF'
## Summary

- Lift the static-only timeline gate in `materialize`: eight filesystem actions execute against `<run-dir>/library/` via a phase-B dispatcher (`materializer/filesystem.py`).
- Add `archive_file` and `move_between_roots` to the scenario contract; `Library.archive_root` gates the archive destination.
- New per-asset `AssetReport.path_history` projection populated in both plan-only and materialize modes.
- `MaterializationReport.filesystem_actions` records every phase-B operation; `Outcome.FS_FAILED` + `FailureStage.FILESYSTEM` cover phase-B failures.
- Two new validation rules: `E_ROOT_UNKNOWN` (closed-set root references) and `E_SLOW_COPY_PATH_COLLISION` (rejects degenerate `temp_path`).
- `_STATE_DELTA_KEYS` documents the per-handler emit contract; a parametrized lock test guards against silent drift.
- Schemas bumped: `scenario v4`, `asset-report v3`, `materialization v3`. Existing fixtures migrated.

## Exit criterion

- ✅ Identity-Move/Rename end-to-end on a real directory: `tests/integration/test_materialize_sprint6_real.py::test_identity_move_rename_end_to_end`.

## Test plan

- [ ] `uv run pytest` passes locally.
- [ ] `uv run python -m chaos_librarian.schema_export --check` clean.
- [ ] `uv run ruff check . && uv run ruff format --check .` clean.
- [ ] `uv run ty check src tests` clean.
- [ ] Layer 4 real-tool tests executed (paste the `pytest -v` summary line below to prove no SKIPPED tests).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Confirm with the user before pushing or opening the PR; do not assume the branch is ready to merge.

---

## Self-Review Checklist (run after writing, before handoff)

The implementation plan author runs these checks ONCE before the executor starts. Treat them as a release gate.

1. **Spec coverage.** Every section of `docs/superpowers/specs/2026-05-19-sprint-6-design.md` is touched by at least one task. Specifically verified:
   - Goal items 1-4 → Tasks 1, 3, 13, 17.
   - Design Decisions 1-11 → contract/engine/validation/materializer tasks.
   - Engine Changes (handlers, WorldState, state_delta contract, lifecycle, validation rules, path containment) → Tasks 4-12.
   - Materializer Phase-B Dispatcher → Tasks 17-19.
   - Report Changes (PathHistoryEntry, AssetReport.path_history) → Tasks 2, 13.
   - MaterializationReport Changes → Task 3.
   - Error Model → Tasks 10, 11, 15.
   - Testing Strategy Layers 1-5 → Tasks 1-3 (Layer 1), Tasks 4-18 (Layer 2), Task 19 (Layer 3), Task 21 (Layer 4), Task 20 (Layer 5).
   - Alternatives Rejected (add_file deferral) → Task 16's preflight excludes add_file.
   - Exit Criteria → Task 21.

2. **Placeholder scan.** No "TBD", "TODO", "fill in later", or untyped "Similar to Task N". All code blocks are concrete. The only intentional "implementer chooses" branches are: (a) the `_minimal_scenario_for_action` per-action constructors in Task 5 (each branch is documented), (b) the fixture-update logic in `invalid/` corpus checks (impossible to enumerate every fixture's interaction without reading the corpus).

3. **Type / name consistency.**
   - `_STATE_DELTA_KEYS` referenced consistently across Tasks 5, 6, 7, 8.
   - `_PhaseBContext` field names match between the design spec (Task 17 step 1) and the per-action helpers (step 2).
   - `FilesystemActionError(message, *, event_id, cause, action, asset_id=, field=, payload=)` signature is the same in Task 15 and the dispatcher call sites in Task 17.
   - `augment_timeline_sidecars(manifest, phase_b_sidecar_hashes)` signature matches between Tasks 17 (caller) and 18 (definition).
   - `apply_phase_b` return type `tuple[list[FilesystemAction], dict[str, str]]` consistent between Task 17 and Task 19.

4. **TDD ordering.** Every task writes the failing test before the implementation. Every task ends with a commit. Schema regen is bundled with the contract change that triggers it.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-05-19-sprint-6-filesystem-mutations.md`.
