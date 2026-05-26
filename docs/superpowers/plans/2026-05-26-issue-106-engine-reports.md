# Issue 106 Engine Reports Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the engine/reports slice by making plan-only reports reflect current hierarchy metadata after hierarchy timeline actions.

**Architecture:** Keep `build_report_set(initial, current, journal)` as the single report builder. Asset reports still use `initial` for the required initial snapshot and journal filtering, but topology fields and domain reports must be derived from `current` so `move_episode_to_season` and `move_track_to_disc` are visible in `reports/` after plan and step. No compatibility path for `works`.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, ruff, ty.

---

## Context

The parent plan is `docs/superpowers/plans/2026-05-26-issue-106-media-hierarchies.md`.
Contract/renderer and validation child plans have already landed on
`feat/issue-106-media-hierarchies`. Most engine work is already present:

- `build_initial_state()` renders initial asset paths from hierarchy topology.
- Hierarchy event handlers mutate `WorldState` metadata and current paths.
- `derive_path_history()` projects hierarchy `path_moves`.
- `engine.writer` emits domain report directories.

The remaining engine risk from review is that `engine.reports` builds domain
reports from `initial`, not `current`, so hierarchy moves can make
`manifest.current.json` correct while report JSON remains stale.

## Files

- Modify: `src/chaos_librarian/engine/reports.py`
- Modify: `tests/engine/test_reports.py`
- Modify: `tests/engine/test_writer.py`

## Task 1: Current-State Domain Reports

**Files:**
- Modify: `tests/engine/test_reports.py`
- Modify: `src/chaos_librarian/engine/reports.py`

- [ ] **Step 1: Add failing report tests**

Add tests to `TestBuildReportSet` proving report topology follows
`current`, not `initial`.

```python
    def test_episode_move_reports_current_season_topology(self) -> None:
        """WHY: hierarchy timeline moves must update report topology, not just manifest."""
        initial = _manifest_with_domain_hierarchy()
        current = _manifest_with_domain_hierarchy()
        current.seasons.append(
            ManifestSeason(
                id="season_two",
                series_id="series_starline",
                season_number=2,
                title="Second",
            )
        )
        current.episodes[0] = current.episodes[0].model_copy(update={"season_id": "season_two"})

        rs = build_report_set(initial=initial, current=current, journal=[])

        seasons = {report.season_id: report for report in rs.seasons}
        assert rs.assets[1].season_id == "season_two"
        assert rs.episodes[0].season_id == "season_two"
        assert seasons["season_specials"].episode_ids == []
        assert seasons["season_specials"].asset_ids == []
        assert seasons["season_two"].episode_ids == ["episode_signal"]
        assert seasons["season_two"].asset_ids == ["asset_episode"]

    def test_track_move_reports_current_disc_topology(self) -> None:
        """WHY: music hierarchy moves must update report topology, not just manifest."""
        initial = _manifest_with_domain_hierarchy()
        current = _manifest_with_domain_hierarchy()
        current.discs.append(
            ManifestDisc(id="disc_winter_02", album_id="album_winter", disc_number=2)
        )
        current.tracks[0] = current.tracks[0].model_copy(update={"disc_id": "disc_winter_02"})

        rs = build_report_set(initial=initial, current=current, journal=[])

        discs = {report.disc_id: report for report in rs.discs}
        assert rs.assets[2].disc_id == "disc_winter_02"
        assert rs.tracks[0].disc_id == "disc_winter_02"
        assert discs["disc_winter_01"].track_ids == []
        assert discs["disc_winter_01"].asset_ids == []
        assert discs["disc_winter_02"].track_ids == ["track_opening"]
        assert discs["disc_winter_02"].asset_ids == ["asset_track"]
```

- [ ] **Step 2: Run tests to verify RED**

Run:

```bash
uv run pytest tests/engine/test_reports.py::TestBuildReportSet::test_episode_move_reports_current_season_topology tests/engine/test_reports.py::TestBuildReportSet::test_track_move_reports_current_disc_topology -q --no-cov
```

Expected: both tests fail because reports are still derived from `initial`.

- [ ] **Step 3: Make report builders use current topology**

In `src/chaos_librarian/engine/reports.py`:

- Build `movies`, `series`, `seasons`, `episodes`, `artists`, `albums`,
  `discs`, `tracks`, `variants`, and `bundles` from `current`.
- Pass both `initial` and `current` into `_build_asset_report()`.
- Use `current` when computing asset topology fields for `AssetReport`.
- Preserve `initial` for the required initial asset snapshot and history target
  set so deleted assets still get reports.

The key shape should be:

```python
_build_asset_report(asset.id, initial, current, journal_list)
_build_episode_report(episode, current)
_asset_topology_for(variant, current)
```

- [ ] **Step 4: Run focused report tests**

Run:

```bash
uv run pytest tests/engine/test_reports.py -q --no-cov
```

Expected: all report tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/engine/reports.py tests/engine/test_reports.py
git commit -m "fix: report current hierarchy topology"
```

## Task 2: Report Directory Regression Coverage

**Files:**
- Modify: `tests/engine/test_writer.py`

- [ ] **Step 1: Add failing writer regression if needed**

Add an assertion to `TestWriterEmitsReports.test_reports_subdirs_exist` that
`reports/works` is absent for a real plan output:

```python
        assert not (out / "reports" / "works").exists()
```

- [ ] **Step 2: Run focused writer test**

Run:

```bash
uv run pytest tests/engine/test_writer.py::TestWriterEmitsReports::test_reports_subdirs_exist -q --no-cov
```

Expected: pass if the writer is already migrated; fail only if a legacy
`reports/works` directory is still emitted.

- [ ] **Step 3: Fix only if the test fails**

If the test fails, remove legacy `works` emission from `engine.writer`. Do not
change materializer or docs here; those belong to later child plans.

- [ ] **Step 4: Commit if changed**

```bash
git add src/chaos_librarian/engine/writer.py tests/engine/test_writer.py
git commit -m "test: assert engine omits works reports"
```

If only the test changed, omit `src/chaos_librarian/engine/writer.py` from
`git add`.

## Task 3: Engine Verification

**Files:**
- No source edits expected.

- [ ] **Step 1: Run focused engine suite**

```bash
uv run pytest tests/engine/test_state.py tests/engine/test_events_hierarchy.py tests/engine/test_path_history.py tests/engine/test_reports.py tests/engine/test_writer.py -q --no-cov
```

Expected: all tests pass.

- [ ] **Step 2: Run project gates required by parent plan**

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Expected: all commands pass with no warnings or schema drift.

- [ ] **Step 3: Confirm engine slice has no legacy work references**

```bash
rg -n "works|work_id|ManifestWork|WorkReport|work-report|reports/works" src/chaos_librarian/engine tests/engine
```

Expected: no matches.
