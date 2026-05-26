# Issue 106 Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move semantic validation from the removed `works` tree to first-class movie, TV, and music hierarchies, using the shared topology and path renderer for identifiers, targets, paths, lifecycle projections, and media compatibility.

**Architecture:** Keep raw validation walkers in `validation/rules/_common.py` because semantic rules operate on raw YAML after the shape pass and need YAML locations for error paths. Add one hierarchy rule module for domain invariants and rendered-path simulation, then update existing rule modules to consume the new shared walkers instead of re-walking `works`. Do not add a compatibility shim: `works` remains rejected by Scenario v12 shape validation.

**Tech Stack:** Python 3.13, Pydantic v2 scenario contracts, raw semantic validation rules, shared `chaos_librarian.topology`, shared `chaos_librarian.path_rendering`, pytest, ruff, ty.

---

## Source Context

Read these files before implementation:

- Parent plan: `docs/superpowers/plans/2026-05-26-issue-106-media-hierarchies.md`, section `## Child Plan 2: Validation`.
- Design spec: `docs/superpowers/specs/2026-05-26-issue-106-media-hierarchies-design.md`, sections `## Reusable Tail`, `## Layout And Path Rendering`, `## Timeline Actions`, `## Path Semantics For Hierarchy Actions`, and `## Validation`.
- Shared typed topology helper already on target: `src/chaos_librarian/topology.py`.
- Shared path renderer already on target: `src/chaos_librarian/path_rendering.py`.

This plan assumes Child Plan 1 has already landed on the target branch and that `src/chaos_librarian/contract/scenario.py` contains Scenario v12 with `movies`, `series`, `artists`, hierarchy timeline actions, and no `works` field.

## File Structure

Create:

- `src/chaos_librarian/validation/rules/hierarchy.py`
  - Raw domain numbering and naming-recipe checks.
  - Initial rendered path collision checks.
  - Timeline hierarchy action simulation against a mutable raw topology snapshot.
  - Video/subtitle-only action rejection for audio-only track assets.
- `tests/validation/rules/test_hierarchy_rules.py`
  - Focused semantic tests for domain hierarchy, rendered paths, hierarchy action targets, lifecycle constraints, and track media-action compatibility.

Modify:

- `src/chaos_librarian/validation/codes.py`
  - Add `E_HIERARCHY_INVALID`.
  - Add `E_PATH_COLLISION`.
- `src/chaos_librarian/validation/rules/_common.py`
  - Replace `works` raw walkers with movie, series, and artist hierarchy walkers.
  - Add raw asset context helpers and rendered-path helper functions.
  - Add hierarchy entity indexes for target resolution and timeline projections.
- `src/chaos_librarian/validation/rules/id_duplicate.py`
  - Replace `work_id` with movie, series, season, episode, artist, album, disc, track, variant, bundle, asset, timeline, and root IDs in one global ID pool.
- `src/chaos_librarian/validation/rules/target_unknown.py`
  - Resolve asset-targeted actions against assets.
  - Resolve hierarchy actions against the required entity kind.
  - Resolve `to_season` and `to_disc` references.
- `src/chaos_librarian/validation/rules/path_containment.py`
  - Replace asset-id path synthesis with `render_asset_path()` and `replace_root_prefix()`.
  - Include rendered hierarchy action paths in containment checks.
- `src/chaos_librarian/validation/rules/asset_path_safety.py`
  - Validate rendered paths and display-derived components through the shared renderer instead of validating only `asset.id` and `asset.container`.
- `src/chaos_librarian/validation/rules/materialize_media_matrix.py`
  - Enforce movie/episode video asset requirements and track audio-only requirements.
- `src/chaos_librarian/validation/rules/slow_copy.py`
  - Compare slow-copy temp paths against rendered initial paths.
- `src/chaos_librarian/validation/rules/timeline_lifecycle.py`
  - Reject hierarchy actions while a slow copy is pending under the mutated hierarchy entity.
  - Keep sidecar projections in rendered declared-sidecar paths.
- `src/chaos_librarian/validation/rules/sidecar_target.py`
  - Seed declared sidecars with `render_declared_sidecar_path(media_path, language)`.
- `src/chaos_librarian/validation/rules/extract_track_unknown.py`
  - Continue to use the hierarchy asset walker.
- `src/chaos_librarian/validation/semantic.py`
  - Register the new hierarchy rules in a deterministic order.
- `tests/validation/rules/conftest.py`
  - Replace the default `minimal_scenario()` raw fixture with Scenario v12 movie shape.
  - Add small builder helpers for series and music hierarchy scenarios used by validation rule tests.
- Existing validation-owned tests under `tests/validation/` that still construct `works`.
- Existing validation-owned invalid fixtures under `tests/fixtures/scenarios/invalid/` that still use `works`.

Do not modify engine, materializer, adapter, generation, public docs, or checked-in schemas in this child plan unless a validation-owned test import forces a narrow mechanical test fixture update. If implementation discovers validation needs engine/materializer state that is not yet present, add an explicit note to the child plan implementer's final report and do not implement that downstream code.

## Task 1: Raw Hierarchy Walkers

**Files:**

- Modify: `src/chaos_librarian/validation/rules/_common.py`
- Modify: `tests/validation/rules/conftest.py`
- Create: `tests/validation/rules/test_hierarchy_rules.py`

- [ ] **Step 1: Replace `minimal_scenario()` with Scenario v12 movie shape**

Edit `tests/validation/rules/conftest.py` so the default raw scenario has this shape:

```python
base: dict[str, object] = {
    "schema_version": 12,
    "scenario_id": "t",
    "seed": 1,
    "duration_scale": "short",
    "library": {"roots": [{"id": "r", "path": "r"}]},
    "movies": [
        {
            "id": "movie_t",
            "title": "Test Movie",
            "layout": "movie_flat",
            "variants": [
                {
                    "id": "v",
                    "label": "l",
                    "bundle": {
                        "id": "b",
                        "assets": [asset],
                    },
                }
            ],
        }
    ],
    "series": [],
    "artists": [],
    "timeline": timeline or [],
}
```

Keep the existing `asset_id`, `asset_subtitles`, `timeline`, and `**overrides` parameters so existing tests can be converted mechanically.

- [ ] **Step 2: Add raw hierarchy fixture builders**

Add these helpers inside `tests/validation/rules/conftest.py`:

```python
@pytest.fixture
def series_scenario() -> ScenarioBuilder:
    def _build(
        *,
        episode_naming: str = "sxxexx_title",
        episode: dict[str, object] | None = None,
        timeline: list[dict[str, object]] | None = None,
        **overrides: object,
    ) -> dict[str, object]:
        asset = {
            "id": "asset_episode",
            "role": "main",
            "container": "mkv",
            "duration_seconds": 1,
            "video": {"source": "color_bars", "codec": "h264", "resolution": "sd"},
            "audio": [
                {"source": "sine", "codec": "aac", "channels": "stereo", "language": "eng"}
            ],
        }
        episode_payload = episode or {
            "id": "episode_one",
            "episode_number": 1,
            "title": "Pilot",
            "aired_on": "2024-05-01",
            "absolute_number": 1,
            "variants": [
                {
                    "id": "variant_episode",
                    "label": "HD",
                    "bundle": {"id": "bundle_episode", "assets": [asset]},
                }
            ],
        }
        base: dict[str, object] = {
            "schema_version": 12,
            "scenario_id": "series-test",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "tv", "path": "TV"}]},
            "movies": [],
            "series": [
                {
                    "id": "series_starline",
                    "title": "Starline",
                    "layout": "season_folders",
                    "episode_naming": episode_naming,
                    "seasons": [
                        {
                            "id": "season_one",
                            "season_number": 1,
                            "title": "Season 1",
                            "episodes": [episode_payload],
                        }
                    ],
                }
            ],
            "artists": [],
            "timeline": timeline or [],
        }
        base.update(overrides)
        return base

    return _build


@pytest.fixture
def music_scenario() -> ScenarioBuilder:
    def _build(
        *,
        track: dict[str, object] | None = None,
        timeline: list[dict[str, object]] | None = None,
        **overrides: object,
    ) -> dict[str, object]:
        asset = {
            "id": "asset_track",
            "role": "main",
            "container": "flac",
            "duration_seconds": 1,
            "audio": [
                {"source": "sine", "codec": "flac", "channels": "stereo", "language": "eng"}
            ],
        }
        track_payload = track or {
            "id": "track_one",
            "track_number": 1,
            "title": "Opening",
            "performers": ["North Index"],
            "variants": [
                {
                    "id": "variant_track",
                    "label": "Lossless",
                    "bundle": {"id": "bundle_track", "assets": [asset]},
                }
            ],
        }
        base: dict[str, object] = {
            "schema_version": 12,
            "scenario_id": "music-test",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "music", "path": "Music"}]},
            "movies": [],
            "series": [],
            "artists": [
                {
                    "id": "artist_north",
                    "name": "North Index",
                    "layout": "artist_album_disc",
                    "track_naming": "track_number_title",
                    "albums": [
                        {
                            "id": "album_winter",
                            "title": "Winter Index",
                            "release_year": 2024,
                            "discs": [
                                {
                                    "id": "disc_one",
                                    "disc_number": 1,
                                    "tracks": [track_payload],
                                }
                            ],
                        }
                    ],
                }
            ],
            "timeline": timeline or [],
        }
        base.update(overrides)
        return base

    return _build
```

- [ ] **Step 3: Write failing walker smoke tests**

Create `tests/validation/rules/test_hierarchy_rules.py` with these initial tests:

```python
"""Hierarchy validation tests for Scenario v12 semantic rules."""

from __future__ import annotations

from typing import cast

from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


def _items(node: object) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", node)


def _mapping(node: object) -> dict[str, object]:
    return cast("dict[str, object]", node)


def _issues_for(raw: dict[str, object], empty_index) -> list[object]:
    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)
    return collector.issues


def test_movie_asset_target_is_found_by_raw_hierarchy_walker(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(timeline=[{"id": "ev", "at": "1s", "action": "delete_file", "target": "a"}])

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_TARGET_UNKNOWN for issue in issues)


def test_episode_asset_target_is_found_by_raw_hierarchy_walker(
    series_scenario, empty_index
) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "delete_file",
                "target": "asset_episode",
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_TARGET_UNKNOWN for issue in issues)


def test_track_asset_target_is_found_by_raw_hierarchy_walker(
    music_scenario, empty_index
) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "delete_file",
                "target": "asset_track",
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_TARGET_UNKNOWN for issue in issues)
```

- [ ] **Step 4: Run the new smoke tests and verify failure**

Run:

```bash
uv run pytest tests/validation/rules/test_hierarchy_rules.py::test_movie_asset_target_is_found_by_raw_hierarchy_walker tests/validation/rules/test_hierarchy_rules.py::test_episode_asset_target_is_found_by_raw_hierarchy_walker tests/validation/rules/test_hierarchy_rules.py::test_track_asset_target_is_found_by_raw_hierarchy_walker -q --no-cov
```

Expected: at least one test fails because `_common.py` still walks `works`.

- [ ] **Step 5: Implement raw hierarchy walkers in `_common.py`**

In `src/chaos_librarian/validation/rules/_common.py`, replace the `works` walker with explicit raw walkers for:

```text
movies[*].variants[*].bundle.assets[*]
series[*].seasons[*].episodes[*].variants[*].bundle.assets[*]
artists[*].albums[*].discs[*].tracks[*].variants[*].bundle.assets[*]
```

Add namespace constants:

```python
NS_MOVIE_ID: Final = "movie_id"
NS_SERIES_ID: Final = "series_id"
NS_SEASON_ID: Final = "season_id"
NS_EPISODE_ID: Final = "episode_id"
NS_ARTIST_ID: Final = "artist_id"
NS_ALBUM_ID: Final = "album_id"
NS_DISC_ID: Final = "disc_id"
NS_TRACK_ID: Final = "track_id"
NS_VARIANT_ID: Final = "variant_id"
NS_BUNDLE_ID: Final = "bundle_id"
NS_ASSET_ID: Final = "asset_id"
```

Add dataclasses:

```python
@dataclass(frozen=True, slots=True)
class RawAssetContext:
    asset: _RawMapping
    asset_loc: _Loc
    parent_kind: str
    parent_id: str
    movie: _RawMapping | None
    movie_loc: _Loc | None
    series: _RawMapping | None
    series_loc: _Loc | None
    season: _RawMapping | None
    season_loc: _Loc | None
    episode: _RawMapping | None
    episode_loc: _Loc | None
    artist: _RawMapping | None
    artist_loc: _Loc | None
    album: _RawMapping | None
    album_loc: _Loc | None
    disc: _RawMapping | None
    disc_loc: _Loc | None
    track: _RawMapping | None
    track_loc: _Loc | None
    variant: _RawMapping
    variant_loc: _Loc
    bundle: _RawMapping
    bundle_loc: _Loc
    bundle_asset_count: int
```

Expose these helpers in `__all__`:

```python
"NS_MOVIE_ID",
"NS_SERIES_ID",
"NS_SEASON_ID",
"NS_EPISODE_ID",
"NS_ARTIST_ID",
"NS_ALBUM_ID",
"NS_DISC_ID",
"NS_TRACK_ID",
"RawAssetContext",
"entity_ids_by_kind",
"iter_asset_contexts",
"iter_entity_ids",
"iter_global_namespaces",
"rendered_asset_paths",
```

Implement `iter_asset_contexts(raw)` as the only nested asset walker. Rebuild `iter_assets_with_loc(raw)`, `iter_asset_ids(raw)`, and `asset_containers(raw)` from `iter_asset_contexts(raw)`.

Keep malformed subtree handling identical to the current rule style: skip non-mapping and non-list nodes because the shape pass owns `E_FIELD_TYPE` and `E_FIELD_SHAPE`.

- [ ] **Step 6: Implement raw render context helper**

In `_common.py`, add `renderable_context_for(raw_context, root_path)` that returns `RenderableAssetContext | None`. It must:

- Convert `parent_kind` to `ParentKind`.
- Convert layout strings to `MovieLayout`, `SeriesLayout`, or `ArtistLayout`.
- Convert naming strings to `EpisodeNaming` or `TrackNaming`.
- Parse `aired_on` with `date.fromisoformat()` when it is a string.
- Return `None` when required fields are missing or enum parsing fails, because shape and hierarchy rules own those reports.
- Pass `variant.label`, `asset.role`, `asset.container`, and `bundle_asset_count` through to the renderer.

Add `rendered_asset_paths(raw)` that uses `primary_root_path(raw)` and returns:

```python
dict[str, tuple[str, _Loc]]
```

where each key is `asset_id` and each value is `(rendered_path, asset_loc)`.

- [ ] **Step 7: Run the walker smoke tests and existing target tests**

Run:

```bash
uv run pytest tests/validation/rules/test_hierarchy_rules.py::test_movie_asset_target_is_found_by_raw_hierarchy_walker tests/validation/rules/test_hierarchy_rules.py::test_episode_asset_target_is_found_by_raw_hierarchy_walker tests/validation/rules/test_hierarchy_rules.py::test_track_asset_target_is_found_by_raw_hierarchy_walker tests/validation/rules/test_target_unknown.py -q --no-cov
```

Expected: smoke tests pass after target resolution is updated in Task 3; `test_target_unknown.py` may still fail before that task.

- [ ] **Step 8: Commit Task 1**

Run:

```bash
git add src/chaos_librarian/validation/rules/_common.py tests/validation/rules/conftest.py tests/validation/rules/test_hierarchy_rules.py
git commit -m "test: add hierarchy validation walker coverage"
```

Commit only if the task's focused tests are in the expected state described above.

## Task 2: Global ID Validation

**Files:**

- Modify: `src/chaos_librarian/validation/rules/_common.py`
- Modify: `src/chaos_librarian/validation/rules/id_duplicate.py`
- Modify: `tests/validation/rules/test_id_duplicate.py`
- Modify: `tests/validation/rules/test_hierarchy_rules.py`

- [ ] **Step 1: Add duplicate ID tests for domain entities and cross-kind collisions**

Add these tests to `tests/validation/rules/test_hierarchy_rules.py`:

```python
def test_duplicate_id_across_root_and_movie_is_rejected(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario()
    _items(raw["movies"])[0]["id"] = "r"

    issues = _issues_for(raw, empty_index)

    dup = [issue for issue in issues if issue.code == codes.E_ID_DUPLICATE]
    assert len(dup) == 1
    assert "movie_id" in dup[0].message
    assert "'r'" in dup[0].message


def test_duplicate_id_across_episode_and_asset_is_rejected(series_scenario, empty_index) -> None:
    raw = series_scenario()
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    _items(season["episodes"])[0]["id"] = "asset_episode"

    issues = _issues_for(raw, empty_index)

    assert any(
        issue.code == codes.E_ID_DUPLICATE
        and "episode_id" in issue.message
        and "'asset_episode'" in issue.message
        for issue in issues
    )


def test_duplicate_id_across_album_and_timeline_event_is_rejected(
    music_scenario, empty_index
) -> None:
    raw = music_scenario(
        timeline=[{"id": "album_winter", "at": "1s", "action": "delete_file", "target": "asset_track"}]
    )

    issues = _issues_for(raw, empty_index)

    assert any(
        issue.code == codes.E_ID_DUPLICATE
        and "timeline_id" in issue.message
        and "'album_winter'" in issue.message
        for issue in issues
    )
```

- [ ] **Step 2: Run duplicate tests and verify failure**

Run:

```bash
uv run pytest tests/validation/rules/test_hierarchy_rules.py::test_duplicate_id_across_root_and_movie_is_rejected tests/validation/rules/test_hierarchy_rules.py::test_duplicate_id_across_episode_and_asset_is_rejected tests/validation/rules/test_hierarchy_rules.py::test_duplicate_id_across_album_and_timeline_event_is_rejected -q --no-cov
```

Expected: fail because `id_duplicate.py` still has `NS_WORK_ID` and per-namespace duplicate maps.

- [ ] **Step 3: Update namespace walking in `_common.py`**

Make `iter_global_namespaces(raw)` yield every hierarchy and tail ID in declaration order with exact raw locs:

```python
("movies", m_idx, "id")
("movies", m_idx, "variants", v_idx, "id")
("movies", m_idx, "variants", v_idx, "bundle", "id")
("movies", m_idx, "variants", v_idx, "bundle", "assets", a_idx, "id")
("series", s_idx, "id")
("series", s_idx, "seasons", season_idx, "id")
("series", s_idx, "seasons", season_idx, "episodes", ep_idx, "id")
("series", s_idx, "seasons", season_idx, "episodes", ep_idx, "variants", v_idx, "id")
("artists", artist_idx, "id")
("artists", artist_idx, "albums", album_idx, "id")
("artists", artist_idx, "albums", album_idx, "discs", disc_idx, "id")
("artists", artist_idx, "albums", album_idx, "discs", disc_idx, "tracks", track_idx, "id")
```

Do not yield root IDs or timeline IDs from `iter_global_namespaces`; `id_duplicate.py` should add those two top-level collections itself so it can label their namespaces as `root_id` and `timeline_id`.

- [ ] **Step 4: Update `id_duplicate.py` to one global ID pool**

Remove `NS_WORK_ID`. Add root and timeline IDs to the same `seen: dict[str, tuple[str, _Loc]]` pool as every namespace yielded by `iter_global_namespaces(raw)`.

Report the second occurrence with the existing `E_ID_DUPLICATE` code and this message shape:

```python
message = (
    f"duplicate {namespace} {value!r} "
    f"(first defined as {first_namespace} at {first_path})"
)
```

This keeps the namespace label visible while enforcing the spec's global uniqueness requirement across roots, domain entities, variants, bundles, assets, and timeline events.

- [ ] **Step 5: Convert existing duplicate tests from `works` to hierarchy**

Update `tests/validation/rules/test_id_duplicate.py`:

- Replace `raw["works"]` with `raw["movies"]`.
- Replace `work_id` assertions with `movie_id`.
- Replace comments that mention `works[0]` with `movies[0]`.
- Keep the existing tests for duplicate asset, variant, bundle, root, and timeline IDs.
- Add one test for duplicate `series_id`, one for `season_id`, one for `artist_id`, and one for `disc_id`.

- [ ] **Step 6: Run duplicate ID tests**

Run:

```bash
uv run pytest tests/validation/rules/test_id_duplicate.py tests/validation/rules/test_hierarchy_rules.py::test_duplicate_id_across_root_and_movie_is_rejected tests/validation/rules/test_hierarchy_rules.py::test_duplicate_id_across_episode_and_asset_is_rejected tests/validation/rules/test_hierarchy_rules.py::test_duplicate_id_across_album_and_timeline_event_is_rejected -q --no-cov
```

Expected: pass.

- [ ] **Step 7: Commit Task 2**

Run:

```bash
git add src/chaos_librarian/validation/rules/_common.py src/chaos_librarian/validation/rules/id_duplicate.py tests/validation/rules/test_id_duplicate.py tests/validation/rules/test_hierarchy_rules.py
git commit -m "fix: validate hierarchy ids globally"
```

## Task 3: Target Resolution

**Files:**

- Modify: `src/chaos_librarian/validation/rules/_common.py`
- Modify: `src/chaos_librarian/validation/rules/target_unknown.py`
- Modify: `tests/validation/rules/test_target_unknown.py`
- Modify: `tests/validation/rules/test_hierarchy_rules.py`

- [ ] **Step 1: Add target resolution tests for hierarchy actions**

Add these tests to `tests/validation/rules/test_hierarchy_rules.py`:

```python
def test_renumber_episode_requires_episode_target(series_scenario, empty_index) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "renumber_episode",
                "target": "season_one",
                "episode_number": 2,
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_TARGET_UNKNOWN for issue in issues)


def test_move_episode_to_season_requires_known_destination_season(
    series_scenario, empty_index
) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "move_episode_to_season",
                "target": "episode_one",
                "to_season": "season_missing",
                "episode_number": 2,
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(
        issue.code == codes.E_TARGET_UNKNOWN and issue.path == "$.timeline[0].to_season"
        for issue in issues
    )


def test_move_track_to_disc_requires_track_target(music_scenario, empty_index) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "move_track_to_disc",
                "target": "disc_one",
                "to_disc": "disc_one",
                "track_number": 2,
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_TARGET_UNKNOWN for issue in issues)


def test_move_track_to_disc_requires_known_destination_disc(
    music_scenario, empty_index
) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "move_track_to_disc",
                "target": "track_one",
                "to_disc": "disc_missing",
                "track_number": 2,
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(
        issue.code == codes.E_TARGET_UNKNOWN and issue.path == "$.timeline[0].to_disc"
        for issue in issues
    )
```

- [ ] **Step 2: Run target tests and verify failure**

Run:

```bash
uv run pytest tests/validation/rules/test_hierarchy_rules.py::test_renumber_episode_requires_episode_target tests/validation/rules/test_hierarchy_rules.py::test_move_episode_to_season_requires_known_destination_season tests/validation/rules/test_hierarchy_rules.py::test_move_track_to_disc_requires_track_target tests/validation/rules/test_hierarchy_rules.py::test_move_track_to_disc_requires_known_destination_disc -q --no-cov
```

Expected: fail because `rule_target_unknown` still treats every `target` as an asset ID.

- [ ] **Step 3: Add entity indexes in `_common.py`**

Add:

```python
def entity_ids_by_kind(raw: _RawMapping) -> dict[str, set[str]]:
    ids: dict[str, set[str]] = {
        "movie": set(),
        "series": set(),
        "season": set(),
        "episode": set(),
        "artist": set(),
        "album": set(),
        "disc": set(),
        "track": set(),
        "variant": set(),
        "bundle": set(),
        "asset": set(),
    }
    for namespace, value, _loc in iter_global_namespaces(raw):
        kind = namespace.removesuffix("_id")
        ids[kind].add(value)
    return ids
```

Build the sets from hierarchy walkers, not from ad hoc searches in `target_unknown.py`.

- [ ] **Step 4: Update `target_unknown.py`**

Define these action groups:

```python
_ASSET_TARGET_ACTIONS: frozenset[str] = frozenset(
    {
        TimelineActionName.MOVE_ASSET,
        TimelineActionName.RENAME_FILE,
        TimelineActionName.DELETE_FILE,
        TimelineActionName.ADD_FILE,
        TimelineActionName.REENCODE_VIDEO,
        TimelineActionName.REENCODE_AUDIO,
        TimelineActionName.CREATE_SIDECAR,
        TimelineActionName.SLOW_COPY_START,
        TimelineActionName.ARCHIVE_FILE,
        TimelineActionName.MOVE_BETWEEN_ROOTS,
        TimelineActionName.REMUX_CONTAINER,
        TimelineActionName.EDIT_METADATA,
        TimelineActionName.EMBED_SUBTITLE,
        TimelineActionName.EXTRACT_SUBTITLE,
        TimelineActionName.REMOVE_SIDECAR,
        TimelineActionName.UPDATE_SIDECAR,
        TimelineActionName.CORRUPT_CONTAINER_HEADER,
        TimelineActionName.TRUNCATE_FILE,
        TimelineActionName.CORRUPT_PACKET_RANGE,
        TimelineActionName.WRITE_INVALID_DURATION_METADATA,
        TimelineActionName.TOUCH_MTIME,
        TimelineActionName.WRONG_ORACLE_HASH,
        TimelineActionName.NETWORK_LAG_START,
    }
)

_HIERARCHY_TARGET_KIND_BY_ACTION: dict[str, str] = {
    TimelineActionName.RENUMBER_EPISODE: "episode",
    TimelineActionName.MOVE_EPISODE_TO_SEASON: "episode",
    TimelineActionName.RENAME_SEASON: "season",
    TimelineActionName.RENUMBER_DISC: "disc",
    TimelineActionName.MOVE_TRACK_TO_DISC: "track",
}
```

Rules:

- Asset-targeted actions validate `target` against `entity_ids["asset"]`.
- Hierarchy actions validate `target` against the mapped kind.
- `move_episode_to_season.to_season` validates against `entity_ids["season"]`.
- `move_track_to_disc.to_disc` validates against `entity_ids["disc"]`.
- `slow_copy_commit` and `network_lag_commit` have no `target` and stay skipped.

Use `E_TARGET_UNKNOWN` for wrong-kind hierarchy targets and unknown destination references. Preserve existing root validation in `rule_root_unknown`.

- [ ] **Step 5: Convert existing target tests from `works` to Scenario v12**

Update `tests/validation/rules/test_target_unknown.py` so each raw scenario uses `minimal_scenario()` or the v12 movie shape. Keep existing assertions for unknown asset targets and unknown roots.

- [ ] **Step 6: Run target tests**

Run:

```bash
uv run pytest tests/validation/rules/test_target_unknown.py tests/validation/rules/test_hierarchy_rules.py::test_renumber_episode_requires_episode_target tests/validation/rules/test_hierarchy_rules.py::test_move_episode_to_season_requires_known_destination_season tests/validation/rules/test_hierarchy_rules.py::test_move_track_to_disc_requires_track_target tests/validation/rules/test_hierarchy_rules.py::test_move_track_to_disc_requires_known_destination_disc -q --no-cov
```

Expected: pass.

- [ ] **Step 7: Commit Task 3**

Run:

```bash
git add src/chaos_librarian/validation/rules/_common.py src/chaos_librarian/validation/rules/target_unknown.py tests/validation/rules/test_target_unknown.py tests/validation/rules/test_hierarchy_rules.py
git commit -m "fix: resolve hierarchy timeline targets"
```

## Task 4: Domain Numbering And Naming Recipe Validation

**Files:**

- Create: `src/chaos_librarian/validation/rules/hierarchy.py`
- Modify: `src/chaos_librarian/validation/codes.py`
- Modify: `src/chaos_librarian/validation/semantic.py`
- Modify: `tests/validation/rules/test_hierarchy_rules.py`

- [ ] **Step 1: Add hierarchy validation codes**

Add to `src/chaos_librarian/validation/codes.py`:

```python
E_HIERARCHY_INVALID: Final = "E_HIERARCHY_INVALID"
E_PATH_COLLISION: Final = "E_PATH_COLLISION"
```

- [ ] **Step 2: Add hierarchy invariant tests**

Add these tests to `tests/validation/rules/test_hierarchy_rules.py`:

```python
def test_season_zero_specials_is_valid(series_scenario, empty_index) -> None:
    raw = series_scenario()
    series = _items(raw["series"])[0]
    _items(series["seasons"])[0]["season_number"] = 0

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_duplicate_episode_number_in_one_season_is_rejected(
    series_scenario, empty_index
) -> None:
    raw = series_scenario()
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    episodes = _items(season["episodes"])
    duplicate = dict(episodes[0])
    duplicate["id"] = "episode_two"
    episodes.append(duplicate)

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_date_title_requires_aired_on(series_scenario, empty_index) -> None:
    raw = series_scenario(episode_naming="date_title")
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    _items(season["episodes"])[0].pop("aired_on")

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_absolute_3_digit_title_requires_absolute_number(
    series_scenario, empty_index
) -> None:
    raw = series_scenario(episode_naming="absolute_3_digit_title")
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    _items(season["episodes"])[0].pop("absolute_number")

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_duplicate_disc_number_in_one_album_is_rejected(music_scenario, empty_index) -> None:
    raw = music_scenario()
    artist = _items(raw["artists"])[0]
    album = _items(artist["albums"])[0]
    duplicate = {
        "id": "disc_two",
        "disc_number": 1,
        "tracks": [],
    }
    _items(album["discs"]).append(duplicate)

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_duplicate_track_number_in_one_disc_is_rejected(music_scenario, empty_index) -> None:
    raw = music_scenario()
    artist = _items(raw["artists"])[0]
    album = _items(artist["albums"])[0]
    disc = _items(album["discs"])[0]
    tracks = _items(disc["tracks"])
    duplicate = dict(tracks[0])
    duplicate["id"] = "track_two"
    duplicate["variants"] = []
    tracks.append(duplicate)

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)
```

- [ ] **Step 3: Run hierarchy invariant tests and verify failure**

Run:

```bash
uv run pytest tests/validation/rules/test_hierarchy_rules.py::test_duplicate_episode_number_in_one_season_is_rejected tests/validation/rules/test_hierarchy_rules.py::test_date_title_requires_aired_on tests/validation/rules/test_hierarchy_rules.py::test_absolute_3_digit_title_requires_absolute_number tests/validation/rules/test_hierarchy_rules.py::test_duplicate_disc_number_in_one_album_is_rejected tests/validation/rules/test_hierarchy_rules.py::test_duplicate_track_number_in_one_disc_is_rejected -q --no-cov
```

Expected: fail because no hierarchy invariant rule is registered.

- [ ] **Step 4: Implement `hierarchy.py` invariant rule**

Create `src/chaos_librarian/validation/rules/hierarchy.py` with:

```python
"""Domain hierarchy semantic validation for Scenario v12."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import EpisodeNaming
from chaos_librarian.validation.codes import E_HIERARCHY_INVALID
from chaos_librarian.validation.rules._common import (
    Reporter,
    _as_list,
    _as_mapping,
    _Loc,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_hierarchy_invariants"]
```

Implement `rule_hierarchy_invariants(raw, line_index, collector)` with helpers that:

- For each `series[*].seasons[*]`, reject duplicate `episode_number` values within that season.
- For each `series` with `episode_naming == "date_title"`, reject each episode missing string `aired_on`.
- For each `series` with `episode_naming == "absolute_3_digit_title"`, reject each episode without positive integer `absolute_number`.
- For each `artists[*].albums[*]`, reject duplicate `disc_number` within the album.
- For each `artists[*].albums[*].discs[*]`, reject duplicate `track_number` within the disc.

Use `E_HIERARCHY_INVALID` and locs on the duplicate or missing field:

```python
("series", s_idx, "seasons", season_idx, "episodes", ep_idx, "episode_number")
("series", s_idx, "seasons", season_idx, "episodes", ep_idx, "aired_on")
("series", s_idx, "seasons", season_idx, "episodes", ep_idx, "absolute_number")
("artists", artist_idx, "albums", album_idx, "discs", disc_idx, "disc_number")
("artists", artist_idx, "albums", album_idx, "discs", disc_idx, "tracks", track_idx, "track_number")
```

Do not duplicate Pydantic numeric bounds for `season_number`, `episode_number`, `disc_number`, or `track_number`; Scenario v12 already maps negative and zero-for-positive cases to shape errors. This semantic rule owns scope uniqueness and naming-recipe dependencies.

- [ ] **Step 5: Register the hierarchy invariant rule**

In `src/chaos_librarian/validation/semantic.py`, import and register:

```python
from chaos_librarian.validation.rules.hierarchy import rule_hierarchy_invariants
```

Place `rule_hierarchy_invariants` after `rule_root_unknown` and before slow-copy/lifecycle rules. It depends only on raw hierarchy shape and should run before timeline simulations.

- [ ] **Step 6: Run hierarchy invariant tests**

Run:

```bash
uv run pytest tests/validation/rules/test_hierarchy_rules.py::test_season_zero_specials_is_valid tests/validation/rules/test_hierarchy_rules.py::test_duplicate_episode_number_in_one_season_is_rejected tests/validation/rules/test_hierarchy_rules.py::test_date_title_requires_aired_on tests/validation/rules/test_hierarchy_rules.py::test_absolute_3_digit_title_requires_absolute_number tests/validation/rules/test_hierarchy_rules.py::test_duplicate_disc_number_in_one_album_is_rejected tests/validation/rules/test_hierarchy_rules.py::test_duplicate_track_number_in_one_disc_is_rejected tests/validation/test_rule_import_isolation.py tests/validation/test_rule_no_cross_imports.py -q --no-cov
```

Expected: pass.

- [ ] **Step 7: Commit Task 4**

Run:

```bash
git add src/chaos_librarian/validation/codes.py src/chaos_librarian/validation/rules/hierarchy.py src/chaos_librarian/validation/semantic.py tests/validation/rules/test_hierarchy_rules.py
git commit -m "fix: validate hierarchy numbering rules"
```

## Task 5: Rendered Initial Path Safety And Collisions

**Files:**

- Modify: `src/chaos_librarian/validation/rules/_common.py`
- Modify: `src/chaos_librarian/validation/rules/hierarchy.py`
- Modify: `src/chaos_librarian/validation/rules/path_containment.py`
- Modify: `src/chaos_librarian/validation/rules/asset_path_safety.py`
- Modify: `tests/validation/rules/test_hierarchy_rules.py`
- Modify: `tests/validation/rules/test_path_containment.py`
- Modify: `tests/validation/rules/test_asset_path_safety.py`

- [ ] **Step 1: Add rendered-path collision and safety tests**

Add these tests to `tests/validation/rules/test_hierarchy_rules.py`:

```python
def test_rendered_initial_asset_path_collision_is_rejected(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario()
    movie = _items(raw["movies"])[0]
    _items(movie["variants"]).append(
        {
            "id": "variant_two",
            "label": "l",
            "bundle": {
                "id": "bundle_two",
                "assets": [
                    {
                        "id": "asset_two",
                        "role": "main",
                        "container": "mkv",
                        "duration_seconds": 1,
                    }
                ],
            },
        }
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_PATH_COLLISION for issue in issues)


def test_rendered_title_dot_segment_is_rejected(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario()
    _items(raw["movies"])[0]["title"] = "."

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_PATH_CONTAINMENT for issue in issues)


def test_rendered_track_path_uses_music_layout_for_collision_check(
    music_scenario, empty_index
) -> None:
    raw = music_scenario()
    artist = _items(raw["artists"])[0]
    album = _items(artist["albums"])[0]
    disc = _items(album["discs"])[0]
    tracks = _items(disc["tracks"])
    duplicate = dict(tracks[0])
    duplicate["id"] = "track_two"
    duplicate["variants"] = [
        {
            "id": "variant_track_two",
            "label": "Lossless",
            "bundle": {
                "id": "bundle_track_two",
                "assets": [
                    {
                        "id": "asset_track_two",
                        "role": "main",
                        "container": "flac",
                        "duration_seconds": 1,
                        "audio": [
                            {
                                "source": "sine",
                                "codec": "flac",
                                "channels": "stereo",
                                "language": "eng",
                            }
                        ],
                    }
                ],
            },
        }
    ]
    tracks.append(duplicate)

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_PATH_COLLISION for issue in issues)
```

- [ ] **Step 2: Run rendered-path tests and verify failure**

Run:

```bash
uv run pytest tests/validation/rules/test_hierarchy_rules.py::test_rendered_initial_asset_path_collision_is_rejected tests/validation/rules/test_hierarchy_rules.py::test_rendered_title_dot_segment_is_rejected tests/validation/rules/test_hierarchy_rules.py::test_rendered_track_path_uses_music_layout_for_collision_check -q --no-cov
```

Expected: fail because no rule checks rendered initial paths.

- [ ] **Step 3: Implement rendered initial path collision rule**

In `src/chaos_librarian/validation/rules/hierarchy.py`, add `rule_rendered_path_collisions(raw, line_index, collector)`.

Behavior:

- Call `_common.rendered_asset_paths(raw)`.
- If rendering raises `ValueError`, emit `E_PATH_CONTAINMENT` from `asset_path_safety.py`, not this collision rule.
- Normalize rendered paths lexically with `os.path.normpath`.
- Emit `E_PATH_COLLISION` when two declared assets render to the same path.
- Report the second asset's `asset_loc` and include the first path with `format_jsonpath(first_loc)` in the message.

Register `rule_rendered_path_collisions` in `semantic.py` after `rule_hierarchy_invariants` and before slow-copy rules.

- [ ] **Step 4: Update asset path safety to use renderer**

Replace `rule_asset_id_container_safe` behavior:

- Remove direct `is_safe_path_component(asset.id)` checks; asset IDs no longer determine rendered paths.
- For each `RawAssetContext`, call `renderable_context_for()` and then `render_asset_path()`.
- Catch `ValueError` from renderer and emit `E_PATH_CONTAINMENT`.
- Use locs for the display field that caused the invalid component when known:
  - movie title: `movie_loc + ("title",)`
  - series title: `series_loc + ("title",)`
  - episode title: `episode_loc + ("title",)`
  - artist name: `artist_loc + ("name",)`
  - album title: `album_loc + ("title",)`
  - track title: `track_loc + ("title",)`
  - variant label: `variant_loc + ("label",)`
  - asset role/container fallback: `asset_loc + ("role",)` or `asset_loc + ("container",)`
- Keep `asset.container` checked through renderer's `_clean_asset_container()` path; a container containing `.`, `/`, `\`, or NUL still emits `E_PATH_CONTAINMENT`.

- [ ] **Step 5: Update path containment to use rendered paths**

In `path_containment.py`:

- Keep root path containment checks.
- Keep explicit timeline path checks for `to`, `temp_path`, and `sidecar_path` fields where applicable.
- For `archive_file`, derive the archive destination by replacing the root part of the current rendered path with the archive base and keeping the rendered domain suffix.
- For `move_between_roots`, derive the destination with `replace_root_prefix(current_path, from_root=from_root_path, to_root=to_root_path)`.
- Do not use `INITIAL_PATH_TEMPLATE`.

If the helper cannot render a target because the scenario shape is already invalid, skip and let shape/hierarchy rules own the error.

- [ ] **Step 6: Convert existing path safety tests from `works`**

Update:

- `tests/validation/rules/test_path_containment.py`
- `tests/validation/rules/test_asset_path_safety.py`

Use `minimal_scenario()` v12 movie shape. Replace expectations that unsafe `asset.id` alone fails; add one assertion that an unsafe `asset.container` still fails because the extension is rendered into the path.

- [ ] **Step 7: Run path tests**

Run:

```bash
uv run pytest tests/validation/rules/test_hierarchy_rules.py::test_rendered_initial_asset_path_collision_is_rejected tests/validation/rules/test_hierarchy_rules.py::test_rendered_title_dot_segment_is_rejected tests/validation/rules/test_hierarchy_rules.py::test_rendered_track_path_uses_music_layout_for_collision_check tests/validation/rules/test_path_containment.py tests/validation/rules/test_asset_path_safety.py -q --no-cov
```

Expected: pass.

- [ ] **Step 8: Commit Task 5**

Run:

```bash
git add src/chaos_librarian/validation/rules/_common.py src/chaos_librarian/validation/rules/hierarchy.py src/chaos_librarian/validation/rules/path_containment.py src/chaos_librarian/validation/rules/asset_path_safety.py src/chaos_librarian/validation/semantic.py tests/validation/rules/test_hierarchy_rules.py tests/validation/rules/test_path_containment.py tests/validation/rules/test_asset_path_safety.py
git commit -m "fix: validate rendered hierarchy paths"
```

## Task 6: Media Compatibility For Track Assets

**Files:**

- Modify: `src/chaos_librarian/media_matrix.py`
- Modify: `src/chaos_librarian/validation/rules/materialize_media_matrix.py`
- Modify: `src/chaos_librarian/validation/rules/hierarchy.py`
- Modify: `tests/validation/rules/test_materialize_media_matrix.py`
- Modify: `tests/validation/rules/test_hierarchy_rules.py`

- [ ] **Step 1: Add static media matrix tests**

Add to `tests/validation/rules/test_hierarchy_rules.py`:

```python
def test_track_asset_allows_audio_only_flac(music_scenario, empty_index) -> None:
    raw = music_scenario()

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)


def test_track_asset_rejects_video_stream(music_scenario, empty_index) -> None:
    raw = music_scenario()
    artist = _items(raw["artists"])[0]
    album = _items(artist["albums"])[0]
    disc = _items(album["discs"])[0]
    track = _items(disc["tracks"])[0]
    variant = _items(track["variants"])[0]
    bundle = _mapping(variant["bundle"])
    asset = _items(bundle["assets"])[0]
    asset["video"] = {"source": "color_bars", "codec": "h264", "resolution": "sd"}

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)


def test_movie_asset_rejects_audio_only(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario()
    movie = _items(raw["movies"])[0]
    variant = _items(movie["variants"])[0]
    bundle = _mapping(variant["bundle"])
    asset = _items(bundle["assets"])[0]
    asset["audio"] = [
        {"source": "sine", "codec": "flac", "channels": "stereo", "language": "eng"}
    ]

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)


def test_track_asset_rejects_mp4_aac_video_container(music_scenario, empty_index) -> None:
    raw = music_scenario()
    artist = _items(raw["artists"])[0]
    album = _items(artist["albums"])[0]
    disc = _items(album["discs"])[0]
    track = _items(disc["tracks"])[0]
    variant = _items(track["variants"])[0]
    bundle = _mapping(variant["bundle"])
    asset = _items(bundle["assets"])[0]
    asset["container"] = "mp4"
    _items(asset["audio"])[0]["codec"] = "aac"

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)
```

- [ ] **Step 2: Add media action compatibility tests**

Add to `tests/validation/rules/test_hierarchy_rules.py`:

```python
def test_reencode_video_rejects_audio_only_track_asset(music_scenario, empty_index) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "reencode_video",
                "target": "asset_track",
                "codec": "h264",
                "resolution": "sd",
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)


def test_extract_subtitle_rejects_audio_only_track_asset(music_scenario, empty_index) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "extract_subtitle",
                "target": "asset_track",
                "to": "Music/extracted.srt",
                "language": "eng",
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(
        issue.code in {codes.E_MATERIALIZE_UNSUPPORTED, codes.E_EXTRACT_TRACK_UNKNOWN}
        for issue in issues
    )


def test_reencode_audio_allows_audio_only_track_asset(music_scenario, empty_index) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "reencode_audio",
                "target": "asset_track",
                "from_channels": "stereo",
                "to_channels": "mono",
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)
```

- [ ] **Step 3: Run media tests and verify failure**

Run:

```bash
uv run pytest tests/validation/rules/test_hierarchy_rules.py::test_track_asset_allows_audio_only_flac tests/validation/rules/test_hierarchy_rules.py::test_track_asset_rejects_video_stream tests/validation/rules/test_hierarchy_rules.py::test_movie_asset_rejects_audio_only tests/validation/rules/test_hierarchy_rules.py::test_track_asset_rejects_mp4_aac_video_container tests/validation/rules/test_hierarchy_rules.py::test_reencode_video_rejects_audio_only_track_asset tests/validation/rules/test_hierarchy_rules.py::test_reencode_audio_allows_audio_only_track_asset -q --no-cov
```

Expected: fail because the static matrix still assumes only `mkv`/`mp4` plus video assets.

- [ ] **Step 4: Extend media matrix constants**

In `src/chaos_librarian/media_matrix.py`, add:

```python
SUPPORTED_VIDEO_CONTAINERS: Final[frozenset[str]] = frozenset({"mkv", "mp4"})
SUPPORTED_AUDIO_ONLY_CONTAINERS: Final[frozenset[str]] = frozenset({"flac", "mp3", "m4a"})
SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER: Final[dict[str, frozenset[str]]] = {
    "flac": frozenset({"flac"}),
    "mp3": frozenset({"mp3"}),
    "m4a": frozenset({"aac"}),
}
SUPPORTED_CONTAINERS: Final[frozenset[str]] = (
    SUPPORTED_VIDEO_CONTAINERS | SUPPORTED_AUDIO_ONLY_CONTAINERS
)
SUPPORTED_AUDIO_CODECS: Final[frozenset[str]] = frozenset({"aac", "flac", "mp3"})
```

Keep existing video constants unchanged.

- [ ] **Step 5: Update `materialize_media_matrix.py`**

Switch from `iter_assets_with_loc(raw)` to `iter_asset_contexts(raw)` so parent kind is available.

Rules:

- Movie and episode assets must have a `video` mapping.
- Movie and episode assets must use `SUPPORTED_VIDEO_CONTAINERS`.
- Movie and episode assets may use existing `SUPPORTED_AUDIO_CODECS`, but for this slice their video stream remains required.
- Track assets must not have a `video` mapping.
- Track assets must not declare subtitle tracks.
- Track assets must declare exactly one audio stream.
- Track asset container and audio codec must match `SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER`.
- Emit `E_MATERIALIZE_UNSUPPORTED` for every unsupported static media condition.

- [ ] **Step 6: Add media action compatibility to `hierarchy.py`**

Add `rule_media_action_compatible_with_parent(raw, line_index, collector)`.

Build `asset_id -> RawAssetContext` from `iter_asset_contexts(raw)`. For timeline events:

- Reject `reencode_video` on track assets with `E_MATERIALIZE_UNSUPPORTED`.
- Reject `embed_subtitle` and `extract_subtitle` on track assets with `E_MATERIALIZE_UNSUPPORTED` unless the existing `E_EXTRACT_TRACK_UNKNOWN` rule already reports missing subtitle streams. It is acceptable for `extract_subtitle` to produce both codes; do not suppress existing `E_EXTRACT_TRACK_UNKNOWN`.
- Reject `corrupt_packet_range` on track assets when `stream` is `video` or `subtitle`.
- Allow `reencode_audio`, file-level actions, `edit_metadata`, `touch_mtime`, `wrong_oracle_hash`, `network_lag_start`, and slow-copy actions on track assets.

Register this rule in `semantic.py` after `rule_materialize_media_matrix` and before sidecar rules.

- [ ] **Step 7: Convert materialize media matrix tests from `works`**

Update `tests/validation/rules/test_materialize_media_matrix.py` to use Scenario v12 `movies` for existing video tests. Add one direct test each for valid `flac`, valid `mp3`, and valid `m4a` track assets.

- [ ] **Step 8: Run media tests**

Run:

```bash
uv run pytest tests/validation/rules/test_materialize_media_matrix.py tests/validation/rules/test_hierarchy_rules.py::test_track_asset_allows_audio_only_flac tests/validation/rules/test_hierarchy_rules.py::test_track_asset_rejects_video_stream tests/validation/rules/test_hierarchy_rules.py::test_movie_asset_rejects_audio_only tests/validation/rules/test_hierarchy_rules.py::test_track_asset_rejects_mp4_aac_video_container tests/validation/rules/test_hierarchy_rules.py::test_reencode_video_rejects_audio_only_track_asset tests/validation/rules/test_hierarchy_rules.py::test_extract_subtitle_rejects_audio_only_track_asset tests/validation/rules/test_hierarchy_rules.py::test_reencode_audio_allows_audio_only_track_asset -q --no-cov
```

Expected: pass.

- [ ] **Step 9: Commit Task 6**

Run:

```bash
git add src/chaos_librarian/media_matrix.py src/chaos_librarian/validation/rules/materialize_media_matrix.py src/chaos_librarian/validation/rules/hierarchy.py src/chaos_librarian/validation/semantic.py tests/validation/rules/test_materialize_media_matrix.py tests/validation/rules/test_hierarchy_rules.py
git commit -m "fix: validate audio-only track media"
```

## Task 7: Slow-Copy, Sidecar, And Extract Projections

**Files:**

- Modify: `src/chaos_librarian/validation/rules/_common.py`
- Modify: `src/chaos_librarian/validation/rules/slow_copy.py`
- Modify: `src/chaos_librarian/validation/rules/sidecar_target.py`
- Modify: `src/chaos_librarian/validation/rules/timeline_lifecycle.py`
- Modify: `src/chaos_librarian/validation/rules/extract_track_unknown.py`
- Modify: `tests/validation/rules/test_slow_copy.py`
- Modify: `tests/validation/rules/test_sidecar_target.py`
- Modify: `tests/validation/rules/test_timeline_lifecycle.py`
- Modify: `tests/validation/rules/test_extract_track_unknown.py`
- Modify: `tests/validation/rules/test_hierarchy_rules.py`

- [ ] **Step 1: Add rendered declared-sidecar projection test**

Add to `tests/validation/rules/test_hierarchy_rules.py`:

```python
def test_declared_sidecar_uses_rendered_media_stem(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        asset_subtitles=[
            {
                "source": "generated_srt",
                "codec": "srt",
                "language": "eng",
                "mode": "sidecar",
            }
        ],
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "remove_sidecar",
                "target": "a",
                "sidecar_path": "r/Test Movie - l.eng.srt",
            }
        ],
    )

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_SIDECAR_TARGET_UNKNOWN for issue in issues)
```

- [ ] **Step 2: Add slow-copy rendered initial path test**

Add to `tests/validation/rules/test_hierarchy_rules.py`:

```python
def test_slow_copy_temp_equal_to_rendered_initial_path_is_rejected(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        timeline=[
            {
                "id": "copy",
                "at": "1s",
                "action": "slow_copy_start",
                "target": "a",
                "to": "r/Copy.mkv",
                "temp_path": "r/Test Movie - l.mkv",
                "duration": "1s",
            },
            {"id": "commit", "at": "2s", "action": "slow_copy_commit", "for": "copy"},
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_SLOW_COPY_PATH_COLLISION for issue in issues)
```

- [ ] **Step 3: Run projection tests and verify failure**

Run:

```bash
uv run pytest tests/validation/rules/test_hierarchy_rules.py::test_declared_sidecar_uses_rendered_media_stem tests/validation/rules/test_hierarchy_rules.py::test_slow_copy_temp_equal_to_rendered_initial_path_is_rejected -q --no-cov
```

Expected: fail because declared sidecars and slow-copy initial paths still use the old `<asset_id>.<language>.srt` and `INITIAL_PATH_TEMPLATE` conventions.

- [ ] **Step 4: Update declared sidecar helper**

In `_common.iter_declared_sidecars(raw)`:

- Iterate `iter_asset_contexts(raw)`.
- Render the media path with:

```python
root_path = primary_root_path(raw)
renderable = renderable_context_for(context, root_path)
if renderable is None:
    continue
media_path = render_asset_path(renderable)
```

- For subtitle tracks with `mode == "sidecar"` and string `language`, compute the sidecar path with `render_declared_sidecar_path(media_path, language)`.
- Yield `DeclaredSidecar(asset_id=asset_id, path=rendered_sidecar_path, kind="subtitle", language=language)`.

If rendering fails, skip here; `asset_path_safety` owns the renderer error.

- [ ] **Step 5: Update slow-copy initial collision**

In `slow_copy.py`:

- Replace `asset_containers(raw)` plus `INITIAL_PATH_TEMPLATE` with `rendered_asset_paths(raw)`.
- Compare `temp_path` against the rendered path for the event target.
- Keep the existing normalized `temp_path == to` check.
- Keep `E_SLOW_COPY_PATH_COLLISION`.

- [ ] **Step 6: Update sidecar and extract modules to hierarchy walkers**

In `sidecar_target.py` and `timeline_lifecycle.py`, no direct behavior change should be needed after `iter_declared_sidecars(raw)` returns rendered sidecar paths. Update comments and tests to remove old `<asset_id>.<language>.srt` language.

In `extract_track_unknown.py`, keep the same logic but ensure it imports and uses the updated `iter_assets_with_loc(raw)` so TV and music assets are visible.

- [ ] **Step 7: Convert existing projection tests from `works`**

Update:

- `tests/validation/rules/test_slow_copy.py`
- `tests/validation/rules/test_sidecar_target.py`
- `tests/validation/rules/test_timeline_lifecycle.py`
- `tests/validation/rules/test_extract_track_unknown.py`

Use Scenario v12 movie shape for existing movie/video cases. Replace old declared sidecar paths like `a0.eng.srt` with rendered paths like `r/Test Movie - l.eng.srt` according to the fixture's title, variant label, and root.

- [ ] **Step 8: Run projection tests**

Run:

```bash
uv run pytest tests/validation/rules/test_slow_copy.py tests/validation/rules/test_sidecar_target.py tests/validation/rules/test_timeline_lifecycle.py tests/validation/rules/test_extract_track_unknown.py tests/validation/rules/test_hierarchy_rules.py::test_declared_sidecar_uses_rendered_media_stem tests/validation/rules/test_hierarchy_rules.py::test_slow_copy_temp_equal_to_rendered_initial_path_is_rejected -q --no-cov
```

Expected: pass.

- [ ] **Step 9: Commit Task 7**

Run:

```bash
git add src/chaos_librarian/validation/rules/_common.py src/chaos_librarian/validation/rules/slow_copy.py src/chaos_librarian/validation/rules/sidecar_target.py src/chaos_librarian/validation/rules/timeline_lifecycle.py src/chaos_librarian/validation/rules/extract_track_unknown.py tests/validation/rules/test_slow_copy.py tests/validation/rules/test_sidecar_target.py tests/validation/rules/test_timeline_lifecycle.py tests/validation/rules/test_extract_track_unknown.py tests/validation/rules/test_hierarchy_rules.py
git commit -m "fix: validate rendered sidecar and slow-copy paths"
```

## Task 8: Hierarchy Timeline Simulation

**Files:**

- Modify: `src/chaos_librarian/validation/rules/hierarchy.py`
- Modify: `src/chaos_librarian/validation/rules/timeline_lifecycle.py`
- Modify: `tests/validation/rules/test_hierarchy_rules.py`

- [ ] **Step 1: Add hierarchy action path collision tests**

Add to `tests/validation/rules/test_hierarchy_rules.py`:

```python
def test_renumber_episode_rejects_duplicate_number_after_mutation(
    series_scenario, empty_index
) -> None:
    raw = series_scenario()
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    _items(season["episodes"]).append(
        {
            "id": "episode_two",
            "episode_number": 2,
            "title": "Second",
            "aired_on": "2024-05-02",
            "absolute_number": 2,
            "variants": [],
        }
    )
    raw["timeline"] = [
        {
            "id": "ev",
            "at": "1s",
            "action": "renumber_episode",
            "target": "episode_one",
            "episode_number": 2,
        }
    ]

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_move_track_to_disc_rejects_duplicate_track_number_after_mutation(
    music_scenario, empty_index
) -> None:
    raw = music_scenario()
    artist = _items(raw["artists"])[0]
    album = _items(artist["albums"])[0]
    _items(album["discs"]).append(
        {
            "id": "disc_two",
            "disc_number": 2,
            "tracks": [
                {
                    "id": "track_two",
                    "track_number": 1,
                    "title": "Second",
                    "performers": ["North Index"],
                    "variants": [],
                }
            ],
        }
    )
    raw["timeline"] = [
        {
            "id": "ev",
            "at": "1s",
            "action": "move_track_to_disc",
            "target": "track_one",
            "to_disc": "disc_two",
            "track_number": 1,
        }
    ]

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_sequential_hierarchy_actions_render_from_mutated_metadata(
    series_scenario, empty_index
) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "rename",
                "at": "1s",
                "action": "rename_season",
                "target": "season_one",
                "title": "Renamed Season",
            },
            {
                "id": "renumber",
                "at": "2s",
                "action": "renumber_episode",
                "target": "episode_one",
                "episode_number": 2,
            },
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_PATH_COLLISION for issue in issues)
    assert not any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)
```

- [ ] **Step 2: Add hierarchy action slow-copy lifecycle test**

Add to `tests/validation/rules/test_hierarchy_rules.py`:

```python
def test_hierarchy_action_under_pending_slow_copy_is_rejected(
    series_scenario, empty_index
) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "copy",
                "at": "1s",
                "action": "slow_copy_start",
                "target": "asset_episode",
                "to": "TV/Copy.mkv",
                "temp_path": "TV/Copy.mkv.part",
                "duration": "2s",
            },
            {
                "id": "renumber",
                "at": "2s",
                "action": "renumber_episode",
                "target": "episode_one",
                "episode_number": 2,
            },
            {"id": "commit", "at": "3s", "action": "slow_copy_commit", "for": "copy"},
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_LIFECYCLE_INVALID for issue in issues)
```

- [ ] **Step 3: Run hierarchy timeline tests and verify failure**

Run:

```bash
uv run pytest tests/validation/rules/test_hierarchy_rules.py::test_renumber_episode_rejects_duplicate_number_after_mutation tests/validation/rules/test_hierarchy_rules.py::test_move_track_to_disc_rejects_duplicate_track_number_after_mutation tests/validation/rules/test_hierarchy_rules.py::test_sequential_hierarchy_actions_render_from_mutated_metadata tests/validation/rules/test_hierarchy_rules.py::test_hierarchy_action_under_pending_slow_copy_is_rejected -q --no-cov
```

Expected: fail because hierarchy timeline actions are not simulated.

- [ ] **Step 4: Implement mutable hierarchy projection in `hierarchy.py`**

Add small dataclasses local to `hierarchy.py` for mutable metadata:

```python
@dataclass(slots=True)
class _EpisodeState:
    id: str
    season_id: str
    episode_number: int
    title: str
    aired_on: str | None
    absolute_number: int | None


@dataclass(slots=True)
class _SeasonState:
    id: str
    series_id: str
    season_number: int
    title: str
    episode_ids: list[str]


@dataclass(slots=True)
class _DiscState:
    id: str
    album_id: str
    disc_number: int
    track_ids: list[str]


@dataclass(slots=True)
class _TrackState:
    id: str
    disc_id: str
    track_number: int
    title: str
```

Build the initial projection from raw `series` and `artists`. Add `rule_hierarchy_timeline(raw, line_index, collector)` that replays timeline actions in order:

- `renumber_episode`: update target episode number and optional absolute number.
- `move_episode_to_season`: move episode ID from old season list to destination season list, update episode number and optional absolute number.
- `rename_season`: update season title.
- `renumber_disc`: update disc number.
- `move_track_to_disc`: move track ID from old disc list to destination disc list and update track number.

After each hierarchy action:

- Recheck duplicate episode numbers within affected seasons.
- Recheck duplicate disc numbers within affected albums.
- Recheck duplicate track numbers within affected discs.
- Render affected asset paths from the mutated metadata snapshot.
- Emit `E_PATH_COLLISION` if a rendered destination collides with any current path outside the move set.

The renderer must use the metadata after prior hierarchy actions, not the original raw scenario metadata. If a required downstream render context for mutable snapshots is not available from Child Plan 1, keep the logic local to validation and note in the final report that engine/materializer must not reuse it.

- [ ] **Step 5: Update lifecycle to reject hierarchy actions under pending slow copy**

In `timeline_lifecycle.py`:

- Use `asset_ids_under_target` equivalent raw helper from `_common.py`, or add `_common.asset_ids_by_hierarchy_target(raw)`.
- For hierarchy actions, compute affected asset IDs:
  - `renumber_episode`: assets under episode target.
  - `move_episode_to_season`: assets under episode target.
  - `rename_season`: assets under season target.
  - `renumber_disc`: assets under disc target.
  - `move_track_to_disc`: assets under track target.
- If any affected asset ID is in `state.assets_with_pending_copy`, emit `E_LIFECYCLE_INVALID`.
- Do not move or delete asset lifecycle state for hierarchy actions; they keep assets placed.

- [ ] **Step 6: Register hierarchy timeline rule**

In `semantic.py`, import and register:

```python
from chaos_librarian.validation.rules.hierarchy import (
    rule_hierarchy_invariants,
    rule_hierarchy_timeline,
    rule_media_action_compatible_with_parent,
    rule_rendered_path_collisions,
)
```

Place `rule_hierarchy_timeline` after `rule_timeline_lifecycle`, because lifecycle owns pending slow-copy rejection and the timeline rule owns path/numbering projection.

- [ ] **Step 7: Run hierarchy timeline tests**

Run:

```bash
uv run pytest tests/validation/rules/test_hierarchy_rules.py::test_renumber_episode_rejects_duplicate_number_after_mutation tests/validation/rules/test_hierarchy_rules.py::test_move_track_to_disc_rejects_duplicate_track_number_after_mutation tests/validation/rules/test_hierarchy_rules.py::test_sequential_hierarchy_actions_render_from_mutated_metadata tests/validation/rules/test_hierarchy_rules.py::test_hierarchy_action_under_pending_slow_copy_is_rejected tests/validation/rules/test_timeline_lifecycle.py -q --no-cov
```

Expected: pass.

- [ ] **Step 8: Commit Task 8**

Run:

```bash
git add src/chaos_librarian/validation/rules/hierarchy.py src/chaos_librarian/validation/rules/timeline_lifecycle.py src/chaos_librarian/validation/semantic.py tests/validation/rules/test_hierarchy_rules.py tests/validation/rules/test_timeline_lifecycle.py
git commit -m "fix: validate hierarchy timeline mutations"
```

## Task 9: Convert Validation-Owned Tests And Fixtures

**Files:**

- Modify: `tests/validation/test_pipeline.py`
- Modify: `tests/validation/test_codes.py`
- Modify: `tests/validation/test_shape.py`
- Modify: `tests/validation/test_input.py`
- Modify: validation-owned files under `tests/fixtures/scenarios/invalid/`
- Modify: validation-owned files under `tests/fixtures/scenarios/` only when they are used directly by validation tests

- [ ] **Step 1: Locate remaining validation-owned `works` references**

Run:

```bash
rg -n "works|work_id|scenario\\.works" tests/validation tests/fixtures/scenarios/invalid tests/fixtures/scenarios
```

Record only references owned by validation tests and invalid corpus fixtures for this child plan. Leave engine, materializer, adapter, generation, and docs fixture conversion to later child plans unless the validation test suite directly loads that fixture.

- [ ] **Step 2: Convert validation shape and input tests**

Update `tests/validation/test_pipeline.py`, `tests/validation/test_shape.py`, and `tests/validation/test_input.py`:

- Replace `schema_version: 11` with `schema_version: 12`.
- Replace `works: []` with:

```yaml
movies: []
series: []
artists: []
```

- Replace any immutability assertions on `run_input.scenario.works` with `run_input.scenario.movies`, `run_input.scenario.series`, and `run_input.scenario.artists`.
- Replace comments that name `works` as the collection example with `movies`, `series`, and `artists`.

- [ ] **Step 3: Convert validation JSONPath test**

Update `tests/validation/test_codes.py` expected path examples from:

```python
("works", 0, "variants", 1, "bundle", "assets", 2, "id")
"$.works[0].variants[1].bundle.assets[2].id"
```

to:

```python
("movies", 0, "variants", 1, "bundle", "assets", 2, "id")
"$.movies[0].variants[1].bundle.assets[2].id"
```

- [ ] **Step 4: Convert invalid corpus fixtures used by validation**

For each file under `tests/fixtures/scenarios/invalid/` that still uses `works`, convert the domain tree to a movie scenario unless the fixture is specifically about TV/music hierarchy. Use this movie wrapper:

```yaml
movies:
  - id: movie_001
    title: Fixture Movie
    layout: movie_flat
    variants:
      - id: variant_main
        label: main
        bundle:
          id: bundle_main
          assets:
            - id: asset_main
              role: main
              container: mkv
              duration_seconds: 1
              video:
                source: color_bars
                codec: h264
                resolution: sd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []
```

Preserve each fixture's first-line `# expected: E_<CODE>` marker and preserve the original invalid condition. Do not convert fixtures owned by later child plans if validation does not load them in this slice.

- [ ] **Step 5: Run validation-owned tests after conversion**

Run:

```bash
uv run pytest tests/validation -q --no-cov
```

Expected: pass or fail only on validation behavior still addressed by Tasks 1-8. Do not ignore fixture collection failures; invalid fixtures without expected markers must be fixed immediately.

- [ ] **Step 6: Confirm no validation-owned `works` references remain**

Run:

```bash
rg -n "works|work_id|scenario\\.works" tests/validation tests/fixtures/scenarios/invalid
```

Expected: no matches.

- [ ] **Step 7: Commit Task 9**

Run:

```bash
git add tests/validation tests/fixtures/scenarios/invalid
git commit -m "test: convert validation fixtures to hierarchies"
```

## Task 10: Focused Verification And Drift Gates

**Files:**

- No new files.
- Possible final formatting changes in files touched by Tasks 1-9.

- [ ] **Step 1: Run focused validation rule tests**

Run:

```bash
uv run pytest tests/validation/rules/test_hierarchy_rules.py tests/validation/rules/test_id_duplicate.py tests/validation/rules/test_target_unknown.py tests/validation/rules/test_path_containment.py tests/validation/rules/test_asset_path_safety.py tests/validation/rules/test_materialize_media_matrix.py tests/validation/rules/test_slow_copy.py tests/validation/rules/test_timeline_lifecycle.py tests/validation/rules/test_sidecar_target.py tests/validation/rules/test_extract_track_unknown.py -q --no-cov
```

Expected: pass.

- [ ] **Step 2: Run full validation tests**

Run:

```bash
uv run pytest tests/validation -q --no-cov
```

Expected: pass.

- [ ] **Step 3: Run lint**

Run:

```bash
uv run ruff check .
```

Expected: pass with no warnings.

- [ ] **Step 4: Run format check**

Run:

```bash
uv run ruff format --check .
```

Expected: pass.

- [ ] **Step 5: Run type check**

Run:

```bash
uv run ty check src tests
```

Expected: pass with no warnings.

- [ ] **Step 6: Run schema drift check if validation touched contracts**

This child plan should not edit `src/chaos_librarian/contract/` or `schemas/`. Run the drift gate anyway if any contract file changed during implementation:

```bash
uv run python -m chaos_librarian.schema_export --check
```

Expected: pass. If it fails because validation implementation required a contract edit, stop and report the contract dependency; do not silently regenerate schemas in this child plan unless the parent/lead explicitly expands the slice.

- [ ] **Step 7: Review local diff**

Run:

```bash
git diff --check
git diff --stat
git diff -- src/chaos_librarian/validation tests/validation tests/fixtures/scenarios/invalid
```

Expected:

- No whitespace errors from `git diff --check`.
- Diff is limited to validation code, validation tests, validation-owned invalid fixtures, and `src/chaos_librarian/media_matrix.py`.
- No compatibility acceptance path for `works`.

- [ ] **Step 8: Final commit if Task 10 made changes**

If formatting or fixture cleanup changed files after Task 9, run:

```bash
git add src/chaos_librarian/validation src/chaos_librarian/media_matrix.py tests/validation tests/fixtures/scenarios/invalid
git commit -m "chore: finish hierarchy validation gates"
```

Do not create an empty commit.

## Open Dependency Notes

- Engine and materializer hierarchy path move behavior is out of scope for this validation child plan. Validation should simulate enough mutable topology to reject impossible hierarchy timelines, but it must not implement engine state updates or filesystem moves.
- Materializer audio-only synthesis is out of scope here. This plan updates validation and shared media matrix constants so unsupported music assets fail before planning; Child Plan 4 must implement actual preflight and synthesis support.
- Adapter, generation, docs, and checked-in schema conversion are out of scope unless validation tests directly import a fixture that still uses `works`.
