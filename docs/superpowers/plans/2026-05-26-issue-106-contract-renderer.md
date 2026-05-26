# Issue 106 Contract Renderer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the public works-based contracts with movie, TV, and music hierarchy contracts, then add the shared topology and path renderer APIs that later validation, engine, materializer, and adapter slices will reuse.

**Architecture:** This is a breaking contract replacement with no compatibility shim. Contract modules own Pydantic wire shapes and import only other contract modules; runtime tree walking lives in `chaos_librarian.topology`, and path construction lives in `chaos_librarian.path_rendering`. The slice is complete only when checked-in schemas match the new contracts and live imports/type checks no longer reference removed `Work`/`work_id`/`WorkReport` symbols.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, ruff, ty, JSON Schema draft 2020-12, checked-in `schemas/*.schema.json`.

---

## Source Inputs

- Parent plan: `docs/superpowers/plans/2026-05-26-issue-106-media-hierarchies.md`
- Design spec: `docs/superpowers/specs/2026-05-26-issue-106-media-hierarchies-design.md`
- Target branch: `feat/issue-106-media-hierarchies`

## Scope Boundary

This child slice owns:

- Scenario v12 contract shape and hierarchy timeline event classes.
- `ScenarioGeneration.profile_version == 3` and domain-shaped generation budgets.
- Shared `ParentKind`, topology walkers, and path renderer.
- Manifest v7 normalized hierarchy rows.
- Report contract replacement: eight domain reports, `VariantReport.parent_kind/parent_id`,
  `AssetReport` topology fields, and removal of `WorkReport`.
- Observed-state v2 normalized hierarchy rows and parent-reference validation.
- Replay bundle schema version bump to v7 because replay embeds scenario YAML.
- Schema export model list and checked-in schema artifacts.
- Live source/test import cleanup for removed public symbols so `ty check src tests` passes.

This child slice does not implement semantic hierarchy validation, hierarchy event execution,
materialized filesystem moves, audio-only synthesis, adapter comparison scoring, generation
lanes, or docs prose. Those are covered by later issue-106 child plans.

## File Map

Create:

- `src/chaos_librarian/contract/domain.py` - shared contract enums that are safe for
  contract modules to import.
- `src/chaos_librarian/topology.py` - typed scenario tree walkers and target-to-asset
  lookups.
- `src/chaos_librarian/path_rendering.py` - display component cleanup, hierarchy path
  rendering, derived sidecar path rendering, and root prefix replacement.
- `tests/contract/test_hierarchy_path_rendering.py` - renderer contract tests.
- `tests/contract/test_topology.py` - topology helper contract tests.
- `tests/contract/test_contract_import_boundaries.py` - guard against contract modules
  importing runtime topology helpers.

Modify:

- `src/chaos_librarian/contract/__init__.py`
- `src/chaos_librarian/contract/scenario.py`
- `src/chaos_librarian/contract/manifest.py`
- `src/chaos_librarian/contract/reports.py`
- `src/chaos_librarian/contract/observed_state.py`
- `src/chaos_librarian/contract/replay_bundle.py`
- `src/chaos_librarian/schema_export.py`
- `tests/contract/test_contract_constants.py`
- `tests/contract/test_scenario.py`
- `tests/contract/test_manifest.py`
- `tests/contract/test_reports.py`
- `tests/contract/test_observed_state.py`
- `tests/contract/test_replay_bundle.py`
- `tests/contract/test_schema_export.py`
- `tests/contract/test_canonicalize.py`
- Live import sites found by the cleanup command in Task 10.

Delete:

- `schemas/work-report.schema.json`

Regenerate:

- `schemas/scenario.schema.json`
- `schemas/manifest.schema.json`
- `schemas/replay-bundle.schema.json`
- `schemas/asset-report.schema.json`
- `schemas/variant-report.schema.json`
- `schemas/observed-state.schema.json`
- New domain report schemas:
  `schemas/movie-report.schema.json`,
  `schemas/series-report.schema.json`,
  `schemas/season-report.schema.json`,
  `schemas/episode-report.schema.json`,
  `schemas/artist-report.schema.json`,
  `schemas/album-report.schema.json`,
  `schemas/disc-report.schema.json`,
  `schemas/track-report.schema.json`

## Task 1: Write Scenario V12 Contract Tests

**Files:**

- Modify: `tests/contract/test_scenario.py`

- [ ] **Step 1: Replace the scenario test imports**

Use the new hierarchy symbols in the scenario tests:

```python
from chaos_librarian.contract.scenario import (
    Album,
    Artist,
    ArtistLayout,
    Asset,
    AudioChannelLayout,
    AudioTrack,
    Bundle,
    Disc,
    DurationScale,
    Episode,
    EpisodeNaming,
    Library,
    LibraryRoot,
    Movie,
    MovieLayout,
    Scenario,
    Season,
    Series,
    SeriesLayout,
    TimelineActionName,
    Track,
    TrackNaming,
    Variant,
    VideoSource,
    VideoTrack,
)
```

- [ ] **Step 2: Add a reusable payload helper**

Keep negative tests payload-based, matching the repository's ty-friendly convention:

```python
def _video_asset_payload(asset_id: str = "asset_main") -> dict[str, object]:
    return {
        "id": asset_id,
        "role": "feature",
        "container": "mkv",
        "duration_seconds": 60.0,
        "video": {"source": "mandelbrot", "codec": "h264", "resolution": "1080p"},
        "audio": [{"codec": "aac", "channels": "stereo", "language": "eng"}],
        "subtitles": [],
    }


def _audio_asset_payload(asset_id: str = "asset_track") -> dict[str, object]:
    return {
        "id": asset_id,
        "role": "main",
        "container": "flac",
        "duration_seconds": 180.0,
        "audio": [{"codec": "flac", "channels": "stereo", "language": "zxx"}],
        "subtitles": [],
    }


def _variant_payload(asset: dict[str, object]) -> dict[str, object]:
    return {
        "id": f"variant_{asset['id']}",
        "label": "1080p" if asset["container"] == "mkv" else "lossless",
        "bundle": {"id": f"bundle_{asset['id']}", "assets": [asset]},
    }


def _base_payload() -> dict[str, object]:
    return {
        "schema_version": SCENARIO_SCHEMA_VERSION,
        "scenario_id": "contract-hierarchy",
        "seed": 1,
        "duration_scale": "short",
        "profiles": [],
        "library": {"roots": [{"id": "primary", "path": "Library"}]},
        "movies": [],
        "series": [],
        "artists": [],
        "timeline": [],
    }
```

- [ ] **Step 3: Add movie-only, TV-only specials, and music-only tests**

```python
def test_movie_only_scenario_v12_payload() -> None:
    payload = _base_payload()
    payload["movies"] = [
        {
            "id": "movie_orbit",
            "title": "Orbit",
            "layout": "movie_flat",
            "variants": [_variant_payload(_video_asset_payload("asset_orbit"))],
        }
    ]

    scenario = Scenario.model_validate(payload)

    assert scenario.schema_version == 12
    assert scenario.movies[0].layout is MovieLayout.MOVIE_FLAT
    assert scenario.series == ()
    assert scenario.artists == ()


def test_tv_only_scenario_accepts_season_zero_specials() -> None:
    payload = _base_payload()
    payload["series"] = [
        {
            "id": "series_starline",
            "title": "Starline",
            "layout": "season_folders",
            "episode_naming": "sxxexx_title",
            "seasons": [
                {
                    "id": "season_specials",
                    "season_number": 0,
                    "title": "Specials",
                    "episodes": [
                        {
                            "id": "episode_special_01",
                            "episode_number": 1,
                            "title": "First Signal",
                            "aired_on": "2024-05-01",
                            "absolute_number": 7,
                            "variants": [_variant_payload(_video_asset_payload("asset_special"))],
                        }
                    ],
                }
            ],
        }
    ]

    scenario = Scenario.model_validate(payload)

    assert scenario.series[0].layout is SeriesLayout.SEASON_FOLDERS
    assert scenario.series[0].episode_naming is EpisodeNaming.SXXEXX_TITLE
    assert scenario.series[0].seasons[0].season_number == 0


def test_music_only_scenario_v12_payload() -> None:
    payload = _base_payload()
    payload["artists"] = [
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
                            "id": "disc_winter_01",
                            "disc_number": 1,
                            "tracks": [
                                {
                                    "id": "track_opening",
                                    "track_number": 1,
                                    "title": "Opening",
                                    "performers": ["North Index"],
                                    "variants": [_variant_payload(_audio_asset_payload())],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    scenario = Scenario.model_validate(payload)

    assert scenario.artists[0].layout is ArtistLayout.ARTIST_ALBUM_DISC
    assert scenario.artists[0].track_naming is TrackNaming.TRACK_NUMBER_TITLE
    assert scenario.artists[0].albums[0].discs[0].tracks[0].performers == ("North Index",)
```

- [ ] **Step 4: Add rejection coverage for the removed `works` field**

```python
def test_scenario_v12_rejects_works_field() -> None:
    payload = _base_payload()
    payload["works"] = [{"id": "work_old", "title": "Old", "variants": []}]

    with pytest.raises(ValidationError) as exc_info:
        Scenario.model_validate(payload)

    assert "works" in str(exc_info.value)
```

- [ ] **Step 5: Add hierarchy timeline event contract tests**

```python
@pytest.mark.parametrize(
    ("event", "expected_type"),
    [
        (
            {
                "id": "ev_renumber_episode",
                "at": "1s",
                "action": "renumber_episode",
                "target": "episode_special_01",
                "episode_number": 2,
                "absolute_number": 8,
            },
            "RenumberEpisodeEvent",
        ),
        (
            {
                "id": "ev_move_episode",
                "at": "2s",
                "action": "move_episode_to_season",
                "target": "episode_special_01",
                "to_season": "season_starline_01",
                "episode_number": 1,
            },
            "MoveEpisodeToSeasonEvent",
        ),
        (
            {
                "id": "ev_rename_season",
                "at": "3s",
                "action": "rename_season",
                "target": "season_specials",
                "title": "Special Episodes",
            },
            "RenameSeasonEvent",
        ),
        (
            {
                "id": "ev_renumber_disc",
                "at": "4s",
                "action": "renumber_disc",
                "target": "disc_winter_01",
                "disc_number": 2,
            },
            "RenumberDiscEvent",
        ),
        (
            {
                "id": "ev_move_track",
                "at": "5s",
                "action": "move_track_to_disc",
                "target": "track_opening",
                "to_disc": "disc_winter_02",
                "track_number": 4,
            },
            "MoveTrackToDiscEvent",
        ),
    ],
)
def test_hierarchy_timeline_event_discriminators(
    event: dict[str, object], expected_type: str
) -> None:
    payload = _base_payload()
    payload["timeline"] = [event]

    scenario = Scenario.model_validate(payload)

    assert type(scenario.timeline[0]).__name__ == expected_type
```

- [ ] **Step 6: Add generation metadata tests for version and budgets**

Carry the old work budget counts into `movies`; TV and music generation coverage is added by
the generation child plan.

```python
def test_generation_budget_uses_domain_counts() -> None:
    budget = generation_budget_for(FuzzProfileName.FUZZ_SMOKE)

    assert FUZZ_GENERATION_PROFILE_VERSION == 3
    assert budget.movies == 3
    assert budget.series == 0
    assert budget.seasons == 0
    assert budget.episodes == 0
    assert budget.artists == 0
    assert budget.albums == 0
    assert budget.discs == 0
    assert budget.tracks == 0
    assert budget.variants == 4
    assert budget.assets == 4
    assert not hasattr(budget, "works")
```

- [ ] **Step 7: Run the scenario tests and confirm they fail for the current contract**

Run:

```bash
uv run pytest tests/contract/test_scenario.py -q --no-cov
```

Expected: fail with validation/import errors because `Scenario` still requires `works`
and the hierarchy models do not exist.

## Task 2: Write Renderer And Topology Tests

**Files:**

- Create: `tests/contract/test_hierarchy_path_rendering.py`
- Create: `tests/contract/test_topology.py`

- [ ] **Step 1: Add renderer tests for every first-slice layout and naming recipe**

Create `tests/contract/test_hierarchy_path_rendering.py` with direct
`RenderableAssetContext` instances. The expected strings below are contract fixtures.

```python
from __future__ import annotations

from datetime import date

import pytest

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    ArtistLayout,
    EpisodeNaming,
    MovieLayout,
    SeriesLayout,
    TrackNaming,
)
from chaos_librarian.path_rendering import (
    RenderableAssetContext,
    clean_display_component,
    render_asset_path,
    render_declared_sidecar_path,
    replace_root_prefix,
)


def _ctx(**overrides: object) -> RenderableAssetContext:
    fields: dict[str, object] = {
        "parent_kind": ParentKind.MOVIE,
        "root_path": "Movies",
        "layout": MovieLayout.MOVIE_FLAT,
        "naming": None,
        "movie_title": "Orbit",
        "series_title": None,
        "season_number": None,
        "episode_number": None,
        "episode_title": None,
        "aired_on": None,
        "absolute_number": None,
        "artist_name": None,
        "album_title": None,
        "disc_number": None,
        "track_number": None,
        "track_title": None,
        "variant_label": "1080p",
        "asset_role": "feature",
        "asset_container": "mkv",
        "bundle_asset_count": 1,
    }
    fields.update(overrides)
    return RenderableAssetContext(**fields)


def test_clean_display_component_normalizes_display_text() -> None:
    assert clean_display_component("  A / B\t C  ") == "A - B C"
    assert clean_display_component("A\\B\x00C") == "A-B-C"


@pytest.mark.parametrize("value", ["", "   ", ".", " .. "])
def test_clean_display_component_rejects_invalid_components(value: str) -> None:
    with pytest.raises(ValueError):
        clean_display_component(value)


def test_movie_flat_path() -> None:
    assert render_asset_path(_ctx()) == "Movies/Orbit - 1080p.mkv"


def test_movie_folder_path() -> None:
    assert render_asset_path(_ctx(layout=MovieLayout.MOVIE_FOLDER)) == (
        "Movies/Orbit/Orbit - 1080p.mkv"
    )


def test_tv_sxxexx_season_folder_path() -> None:
    assert render_asset_path(
        _ctx(
            parent_kind=ParentKind.EPISODE,
            root_path="TV",
            layout=SeriesLayout.SEASON_FOLDERS,
            naming=EpisodeNaming.SXXEXX_TITLE,
            movie_title=None,
            series_title="Starline",
            season_number=1,
            episode_number=1,
            episode_title="Pilot",
            aired_on=date(2024, 5, 1),
            absolute_number=7,
        )
    ) == "TV/Starline/Season 01/Starline - S01E01 - Pilot - 1080p.mkv"


def test_tv_one_xx_flat_path() -> None:
    assert render_asset_path(
        _ctx(
            parent_kind=ParentKind.EPISODE,
            root_path="TV",
            layout=SeriesLayout.SERIES_FLAT,
            naming=EpisodeNaming.ONE_XX_TITLE,
            movie_title=None,
            series_title="Starline",
            season_number=1,
            episode_number=1,
            episode_title="Pilot",
        )
    ) == "TV/Starline/Starline - 1x01 - Pilot - 1080p.mkv"


def test_tv_absolute_number_path() -> None:
    assert render_asset_path(
        _ctx(
            parent_kind=ParentKind.EPISODE,
            root_path="TV",
            layout=SeriesLayout.SERIES_FLAT,
            naming=EpisodeNaming.ABSOLUTE_3_DIGIT_TITLE,
            movie_title=None,
            series_title="Starline",
            season_number=1,
            episode_number=7,
            episode_title="Signal",
            absolute_number=7,
        )
    ) == "TV/Starline/Starline - 007 - Signal - 1080p.mkv"


def test_tv_date_path() -> None:
    assert render_asset_path(
        _ctx(
            parent_kind=ParentKind.EPISODE,
            root_path="TV",
            layout=SeriesLayout.SERIES_FLAT,
            naming=EpisodeNaming.DATE_TITLE,
            movie_title=None,
            series_title="Starline",
            season_number=1,
            episode_number=1,
            episode_title="Pilot",
            aired_on=date(2024, 5, 1),
        )
    ) == "TV/Starline/Starline - 2024-05-01 - Pilot - 1080p.mkv"


def test_music_disc_folder_track_number_path() -> None:
    assert render_asset_path(
        _ctx(
            parent_kind=ParentKind.TRACK,
            root_path="Music",
            layout=ArtistLayout.ARTIST_ALBUM_DISC,
            naming=TrackNaming.TRACK_NUMBER_TITLE,
            movie_title=None,
            artist_name="North Index",
            album_title="Winter Index",
            disc_number=1,
            track_number=1,
            track_title="Opening",
            variant_label="lossless",
            asset_container="flac",
        )
    ) == "Music/North Index/Winter Index/Disc 01/01 - Opening - lossless.flac"


def test_music_flat_disc_track_number_path() -> None:
    assert render_asset_path(
        _ctx(
            parent_kind=ParentKind.TRACK,
            root_path="Music",
            layout=ArtistLayout.ARTIST_ALBUM_FLAT,
            naming=TrackNaming.DISC_TRACK_NUMBER_TITLE,
            movie_title=None,
            artist_name="North Index",
            album_title="Winter Index",
            disc_number=1,
            track_number=1,
            track_title="Opening",
            variant_label="lossless",
            asset_container="flac",
        )
    ) == "Music/North Index/Winter Index/01-01 - Opening - lossless.flac"


def test_multi_asset_bundle_uses_asset_role_suffix() -> None:
    assert render_asset_path(
        _ctx(layout=MovieLayout.MOVIE_FOLDER, bundle_asset_count=2)
    ) == "Movies/Orbit/Orbit - 1080p - feature.mkv"
```

- [ ] **Step 2: Add invalid path and sidecar/root helper tests**

```python
@pytest.mark.parametrize(
    "root_path",
    ["/Movies", "C:/Movies", "Movies//HD", "Movies/../HD", "Movies/./HD"],
)
def test_render_asset_path_rejects_invalid_root_segments(root_path: str) -> None:
    with pytest.raises(ValueError):
        render_asset_path(_ctx(root_path=root_path))


@pytest.mark.parametrize(
    "overrides",
    [
        {"movie_title": ".."},
        {"variant_label": "."},
        {"asset_container": "../mkv"},
        {"asset_container": "mkv/evil"},
    ],
)
def test_render_asset_path_rejects_invalid_rendered_components(
    overrides: dict[str, object]
) -> None:
    with pytest.raises(ValueError):
        render_asset_path(_ctx(**overrides))


def test_render_declared_sidecar_path_stays_next_to_media_stem() -> None:
    assert render_declared_sidecar_path("TV/Starline/Pilot.mkv", "eng") == (
        "TV/Starline/Pilot.eng.srt"
    )


def test_replace_root_prefix_swaps_only_the_root_component() -> None:
    assert replace_root_prefix(
        "Movies/Orbit/Orbit - 1080p.mkv",
        from_root="Movies",
        to_root="Archive",
    ) == "Archive/Orbit/Orbit - 1080p.mkv"


def test_replace_root_prefix_rejects_non_root_prefix_match() -> None:
    with pytest.raises(ValueError):
        replace_root_prefix(
            "Movies-HD/Orbit.mkv",
            from_root="Movies",
            to_root="Archive",
        )
```

- [ ] **Step 3: Add topology helper tests**

Create `tests/contract/test_topology.py` with a v12 scenario that contains one movie,
one TV episode, and one music track.

```python
from __future__ import annotations

import pytest

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.topology import (
    asset_contexts_by_id,
    asset_ids_under_target,
    iter_asset_contexts,
)


def _scenario() -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 12,
            "scenario_id": "topology",
            "seed": 1,
            "duration_scale": "short",
            "profiles": [],
            "library": {"roots": [{"id": "primary", "path": "Library"}]},
            "movies": [
                {
                    "id": "movie_orbit",
                    "title": "Orbit",
                    "layout": "movie_folder",
                    "variants": [
                        {
                            "id": "variant_movie",
                            "label": "1080p",
                            "bundle": {
                                "id": "bundle_movie",
                                "assets": [
                                    {
                                        "id": "asset_movie",
                                        "role": "feature",
                                        "container": "mkv",
                                        "duration_seconds": 60,
                                        "video": {
                                            "source": "mandelbrot",
                                            "codec": "h264",
                                            "resolution": "1080p",
                                        },
                                        "audio": [
                                            {
                                                "codec": "aac",
                                                "channels": "stereo",
                                                "language": "eng",
                                            }
                                        ],
                                        "subtitles": [],
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
            "series": [
                {
                    "id": "series_starline",
                    "title": "Starline",
                    "layout": "season_folders",
                    "episode_naming": "sxxexx_title",
                    "seasons": [
                        {
                            "id": "season_01",
                            "season_number": 1,
                            "title": "Season 1",
                            "episodes": [
                                {
                                    "id": "episode_01",
                                    "episode_number": 1,
                                    "title": "Pilot",
                                    "aired_on": "2024-05-01",
                                    "absolute_number": 1,
                                    "variants": [
                                        {
                                            "id": "variant_episode",
                                            "label": "1080p",
                                            "bundle": {
                                                "id": "bundle_episode",
                                                "assets": [
                                                    {
                                                        "id": "asset_episode",
                                                        "role": "feature",
                                                        "container": "mkv",
                                                        "duration_seconds": 60,
                                                        "video": {
                                                            "source": "mandelbrot",
                                                            "codec": "h264",
                                                            "resolution": "1080p",
                                                        },
                                                        "audio": [
                                                            {
                                                                "codec": "aac",
                                                                "channels": "stereo",
                                                                "language": "eng",
                                                            }
                                                        ],
                                                        "subtitles": [],
                                                    }
                                                ],
                                            },
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
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
                                    "id": "disc_01",
                                    "disc_number": 1,
                                    "tracks": [
                                        {
                                            "id": "track_01",
                                            "track_number": 1,
                                            "title": "Opening",
                                            "performers": ["North Index"],
                                            "variants": [
                                                {
                                                    "id": "variant_track",
                                                    "label": "lossless",
                                                    "bundle": {
                                                        "id": "bundle_track",
                                                        "assets": [
                                                            {
                                                                "id": "asset_track",
                                                                "role": "main",
                                                                "container": "flac",
                                                                "duration_seconds": 180,
                                                                "audio": [
                                                                    {
                                                                        "codec": "flac",
                                                                        "channels": "stereo",
                                                                        "language": "zxx",
                                                                    }
                                                                ],
                                                                "subtitles": [],
                                                            }
                                                        ],
                                                    },
                                                }
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
            "timeline": [],
        }
    )


def test_iter_asset_contexts_preserves_manifest_declaration_order() -> None:
    contexts = list(iter_asset_contexts(_scenario()))

    assert [context.asset.id for context in contexts] == [
        "asset_movie",
        "asset_episode",
        "asset_track",
    ]
    assert [context.parent_kind for context in contexts] == [
        ParentKind.MOVIE,
        ParentKind.EPISODE,
        ParentKind.TRACK,
    ]
    assert contexts[1].series is not None
    assert contexts[2].album is not None


def test_asset_contexts_by_id_returns_every_asset() -> None:
    contexts = asset_contexts_by_id(_scenario())

    assert set(contexts) == {"asset_movie", "asset_episode", "asset_track"}
    assert contexts["asset_track"].parent_id == "track_01"


@pytest.mark.parametrize(
    ("target_kind", "target_id", "asset_ids"),
    [
        ("movie", "movie_orbit", ("asset_movie",)),
        ("series", "series_starline", ("asset_episode",)),
        ("season", "season_01", ("asset_episode",)),
        ("episode", "episode_01", ("asset_episode",)),
        ("artist", "artist_north", ("asset_track",)),
        ("album", "album_winter", ("asset_track",)),
        ("disc", "disc_01", ("asset_track",)),
        ("track", "track_01", ("asset_track",)),
        ("variant", "variant_movie", ("asset_movie",)),
        ("bundle", "bundle_track", ("asset_track",)),
        ("asset", "asset_movie", ("asset_movie",)),
    ],
)
def test_asset_ids_under_target(
    target_kind: str, target_id: str, asset_ids: tuple[str, ...]
) -> None:
    assert asset_ids_under_target(
        _scenario(), target_kind=target_kind, target_id=target_id
    ) == asset_ids


def test_asset_ids_under_target_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown target_kind"):
        asset_ids_under_target(_scenario(), target_kind="work", target_id="work_001")
```

- [ ] **Step 4: Run the new tests and confirm they fail for missing modules**

Run:

```bash
uv run pytest \
  tests/contract/test_hierarchy_path_rendering.py \
  tests/contract/test_topology.py \
  -q --no-cov
```

Expected: fail with import errors for `chaos_librarian.path_rendering`,
`chaos_librarian.topology`, and `chaos_librarian.contract.domain`.

## Task 3: Add Contract Import Boundary Test

**Files:**

- Create: `tests/contract/test_contract_import_boundaries.py`

- [ ] **Step 1: Add a structure-aware import guard**

```python
from __future__ import annotations

import ast
from pathlib import Path


CONTRACT_DIR = Path(__file__).resolve().parents[2] / "src" / "chaos_librarian" / "contract"


def test_contract_modules_do_not_import_runtime_topology_helpers() -> None:
    offenders: list[str] = []
    for path in sorted(CONTRACT_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "chaos_librarian.topology":
                        offenders.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.ImportFrom) and node.module == "chaos_librarian.topology":
                offenders.append(f"{path.name}:{node.lineno}")

    assert offenders == []
```

- [ ] **Step 2: Run the boundary test**

Run:

```bash
uv run pytest tests/contract/test_contract_import_boundaries.py -q --no-cov
```

Expected: pass before implementation and continue passing after implementation.

## Task 4: Replace Scenario Contract And Add ParentKind

**Files:**

- Create: `src/chaos_librarian/contract/domain.py`
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/contract/replay_bundle.py`
- Modify: `tests/contract/test_contract_constants.py`
- Modify: `tests/contract/test_replay_bundle.py`

- [ ] **Step 1: Update contract constants**

In `src/chaos_librarian/contract/__init__.py`:

```python
SCENARIO_SCHEMA_VERSION: Final = 12
MANIFEST_SCHEMA_VERSION: Final = 7
REPLAY_BUNDLE_SCHEMA_VERSION: Final = 7
ASSET_REPORT_SCHEMA_VERSION: Final = 7
VARIANT_REPORT_SCHEMA_VERSION: Final = 2
MOVIE_REPORT_SCHEMA_VERSION: Final = 1
SERIES_REPORT_SCHEMA_VERSION: Final = 1
SEASON_REPORT_SCHEMA_VERSION: Final = 1
EPISODE_REPORT_SCHEMA_VERSION: Final = 1
ARTIST_REPORT_SCHEMA_VERSION: Final = 1
ALBUM_REPORT_SCHEMA_VERSION: Final = 1
DISC_REPORT_SCHEMA_VERSION: Final = 1
TRACK_REPORT_SCHEMA_VERSION: Final = 1
OBSERVED_STATE_SCHEMA_VERSION: Final = 2
```

Remove `WORK_REPORT_SCHEMA_VERSION`.

- [ ] **Step 2: Add `ParentKind`**

Create `src/chaos_librarian/contract/domain.py`:

```python
"""Shared domain enums for public contracts."""

from __future__ import annotations

import enum


class ParentKind(enum.StrEnum):
    """Playable/listenable parent kinds for variants and assets."""

    MOVIE = "movie"
    EPISODE = "episode"
    TRACK = "track"
```

- [ ] **Step 3: Replace work models with domain hierarchy models**

In `src/chaos_librarian/contract/scenario.py`, delete `Work` and add these enums
and Pydantic models after `Variant`:

```python
class MovieLayout(enum.StrEnum):
    MOVIE_FLAT = "movie_flat"
    MOVIE_FOLDER = "movie_folder"


class SeriesLayout(enum.StrEnum):
    SEASON_FOLDERS = "season_folders"
    SERIES_FLAT = "series_flat"


class EpisodeNaming(enum.StrEnum):
    SXXEXX_TITLE = "sxxexx_title"
    ONE_XX_TITLE = "one_xx_title"
    ABSOLUTE_3_DIGIT_TITLE = "absolute_3_digit_title"
    DATE_TITLE = "date_title"


class ArtistLayout(enum.StrEnum):
    ARTIST_ALBUM_DISC = "artist_album_disc"
    ARTIST_ALBUM_FLAT = "artist_album_flat"


class TrackNaming(enum.StrEnum):
    TRACK_NUMBER_TITLE = "track_number_title"
    DISC_TRACK_NUMBER_TITLE = "disc_track_number_title"


class Movie(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    layout: MovieLayout
    variants: tuple[Variant, ...]


class Episode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    episode_number: int = Field(ge=1)
    title: str
    aired_on: date | None = None
    absolute_number: int | None = Field(default=None, ge=1)
    variants: tuple[Variant, ...]


class Season(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    season_number: int = Field(ge=0)
    title: str
    episodes: tuple[Episode, ...]


class Series(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    layout: SeriesLayout
    episode_naming: EpisodeNaming
    seasons: tuple[Season, ...]


class Track(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    track_number: int = Field(ge=1)
    title: str
    performers: tuple[str, ...] = Field(default_factory=tuple)
    variants: tuple[Variant, ...]


class Disc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    disc_number: int = Field(ge=1)
    tracks: tuple[Track, ...]


class Album(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    release_year: int | None = None
    discs: tuple[Disc, ...]


class Artist(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    name: str
    layout: ArtistLayout
    track_naming: TrackNaming
    albums: tuple[Album, ...]
```

Add `from datetime import date` at the top. Do not import `chaos_librarian.topology`
from this or any other `contract/*` module.

- [ ] **Step 4: Add hierarchy timeline actions to the scenario union**

Add enum members:

```python
RENUMBER_EPISODE = "renumber_episode"
MOVE_EPISODE_TO_SEASON = "move_episode_to_season"
RENAME_SEASON = "rename_season"
RENUMBER_DISC = "renumber_disc"
MOVE_TRACK_TO_DISC = "move_track_to_disc"
```

Add event classes:

```python
class RenumberEpisodeEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.RENUMBER_EPISODE] = (
        TimelineActionName.RENUMBER_EPISODE
    )
    target: str
    episode_number: int = Field(ge=1)
    absolute_number: int | None = Field(default=None, ge=1)


class MoveEpisodeToSeasonEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.MOVE_EPISODE_TO_SEASON] = (
        TimelineActionName.MOVE_EPISODE_TO_SEASON
    )
    target: str
    to_season: str
    episode_number: int = Field(ge=1)
    absolute_number: int | None = Field(default=None, ge=1)


class RenameSeasonEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.RENAME_SEASON] = TimelineActionName.RENAME_SEASON
    target: str
    title: str


class RenumberDiscEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.RENUMBER_DISC] = TimelineActionName.RENUMBER_DISC
    target: str
    disc_number: int = Field(ge=1)


class MoveTrackToDiscEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.MOVE_TRACK_TO_DISC] = (
        TimelineActionName.MOVE_TRACK_TO_DISC
    )
    target: str
    to_disc: str
    track_number: int = Field(ge=1)
```

Insert all five classes into the `TimelineEvent` discriminated union. The current
target branch has no `_STATE_DELTA_KEYS`; confirm with:

```bash
rg -n "_STATE_DELTA_KEYS" src/chaos_librarian
```

Expected: no output.

- [ ] **Step 5: Update generation metadata shape**

In `src/chaos_librarian/contract/scenario.py`:

```python
class GenerationBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    movies: int = Field(ge=0)
    series: int = Field(ge=0)
    seasons: int = Field(ge=0)
    episodes: int = Field(ge=0)
    artists: int = Field(ge=0)
    albums: int = Field(ge=0)
    discs: int = Field(ge=0)
    tracks: int = Field(ge=0)
    variants: int = Field(ge=0)
    bundles: int = Field(ge=0)
    assets: int = Field(ge=0)
    sidecars: int = Field(ge=0)
    timeline_events: int = Field(ge=0)


class ScenarioGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generator: Literal["chaos-librarian"] = "chaos-librarian"
    profile: FuzzProfileName
    lane: FuzzLaneName
    profile_version: Literal[3]
    seed: int = Field(ge=0)
    budgets: GenerationBudget


FUZZ_GENERATION_PROFILE_VERSION: Final = 3

FUZZ_GENERATION_BUDGETS: Final[dict[FuzzProfileName, GenerationBudget]] = {
    FuzzProfileName.FUZZ_SMOKE: GenerationBudget(
        movies=3,
        series=0,
        seasons=0,
        episodes=0,
        artists=0,
        albums=0,
        discs=0,
        tracks=0,
        variants=4,
        bundles=4,
        assets=4,
        sidecars=8,
        timeline_events=12,
    ),
    FuzzProfileName.FUZZ_REGRESSION: GenerationBudget(
        movies=12,
        series=0,
        seasons=0,
        episodes=0,
        artists=0,
        albums=0,
        discs=0,
        tracks=0,
        variants=18,
        bundles=18,
        assets=18,
        sidecars=54,
        timeline_events=80,
    ),
}
```

- [ ] **Step 6: Update `Scenario` top-level fields**

```python
class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)

    schema_version: Literal[12]
    scenario_id: str
    seed: int | Literal["random"]
    duration_scale: DurationScale
    profiles: tuple[ProfileName, ...] = Field(default_factory=tuple)
    generation: ScenarioGeneration | None = None
    library: Library
    movies: tuple[Movie, ...]
    series: tuple[Series, ...]
    artists: tuple[Artist, ...]
    timeline: tuple[TimelineEvent, ...]
```

- [ ] **Step 7: Bump replay bundle literal**

In `src/chaos_librarian/contract/replay_bundle.py`, set:

```python
schema_version: Literal[7]
```

Update the nearby comment to say v7 is for the embedded scenario v12 hierarchy
shape.

- [ ] **Step 8: Update constants and replay tests**

In `tests/contract/test_contract_constants.py`, remove `WORK_REPORT_SCHEMA_VERSION`
from imports and the positive-integer list, then add the eight domain report
constants. Pin the new values:

```python
def test_issue_106_contract_schema_versions() -> None:
    assert SCENARIO_SCHEMA_VERSION == 12
    assert MANIFEST_SCHEMA_VERSION == 7
    assert REPLAY_BUNDLE_SCHEMA_VERSION == 7
    assert ASSET_REPORT_SCHEMA_VERSION == 7
    assert VARIANT_REPORT_SCHEMA_VERSION == 2
    assert OBSERVED_STATE_SCHEMA_VERSION == 2
```

In `tests/contract/test_replay_bundle.py`, keep behavior the same but update the
trace stream that currently says `work_id`:

```python
AllocTraceEntry(kind=ExecutionTraceKind.ALLOC, stream="movie_id", value="movie_orbit")
```

- [ ] **Step 9: Run scenario and constants tests**

Run:

```bash
uv run pytest \
  tests/contract/test_scenario.py \
  tests/contract/test_contract_constants.py \
  tests/contract/test_replay_bundle.py \
  -q --no-cov
```

Expected: scenario and replay tests that exercise only changed contracts pass; tests
that import manifest/report symbols still fail until Tasks 7 and 8.

- [ ] **Step 10: Commit the scenario contract change**

```bash
git add \
  src/chaos_librarian/contract/__init__.py \
  src/chaos_librarian/contract/domain.py \
  src/chaos_librarian/contract/scenario.py \
  src/chaos_librarian/contract/replay_bundle.py \
  tests/contract/test_contract_constants.py \
  tests/contract/test_scenario.py \
  tests/contract/test_replay_bundle.py
git commit -m "feat: replace scenario hierarchy contract"
```

## Task 5: Implement Path Renderer

**Files:**

- Create: `src/chaos_librarian/path_rendering.py`

- [ ] **Step 1: Add the public dataclass and function signatures**

```python
"""Domain-aware media path rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    ArtistLayout,
    EpisodeNaming,
    MovieLayout,
    SeriesLayout,
    TrackNaming,
)


@dataclass(frozen=True, slots=True)
class RenderableAssetContext:
    parent_kind: ParentKind
    root_path: str
    layout: MovieLayout | SeriesLayout | ArtistLayout
    naming: EpisodeNaming | TrackNaming | None
    movie_title: str | None
    series_title: str | None
    season_number: int | None
    episode_number: int | None
    episode_title: str | None
    aired_on: date | None
    absolute_number: int | None
    artist_name: str | None
    album_title: str | None
    disc_number: int | None
    track_number: int | None
    track_title: str | None
    variant_label: str
    asset_role: str
    asset_container: str
    bundle_asset_count: int
```

- [ ] **Step 2: Implement component and path validation**

Use explicit helpers; do not slugify or lowercase.

```python
_WINDOWS_DRIVE_PREFIX_LENGTH = 2


def clean_display_component(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    cleaned = cleaned.replace("/", "-").replace("\\", "-").replace("\x00", "-")
    if cleaned in {"", ".", ".."}:
        raise ValueError("display component must not be empty, '.', or '..'")
    return cleaned


def _validate_relative_posix_path(path: str) -> str:
    if path == "" or path.startswith("/") or "\\" in path or "\x00" in path:
        raise ValueError("path must be a relative POSIX path")
    first_segment = path.split("/", 1)[0]
    has_drive_prefix = (
        len(first_segment) == _WINDOWS_DRIVE_PREFIX_LENGTH
        and first_segment[1] == ":"
        and first_segment[0].isalpha()
    )
    if has_drive_prefix:
        raise ValueError("path must not contain a Windows drive prefix")
    if any(segment in {"", ".", ".."} for segment in path.split("/")):
        raise ValueError("path must not contain empty, dot, or parent segments")
    return path


def _join_path(*parts: str) -> str:
    return _validate_relative_posix_path("/".join(parts))
```

- [ ] **Step 3: Implement media file rendering**

```python
def render_asset_path(ctx: RenderableAssetContext) -> str:
    root = _validate_relative_posix_path(ctx.root_path)
    if ctx.parent_kind is ParentKind.MOVIE:
        parts = _movie_parts(root, ctx)
    elif ctx.parent_kind is ParentKind.EPISODE:
        parts = _episode_parts(root, ctx)
    elif ctx.parent_kind is ParentKind.TRACK:
        parts = _track_parts(root, ctx)
    else:
        raise ValueError(f"unsupported parent_kind: {ctx.parent_kind}")
    return _join_path(*parts)


def _filename(stem: str, ctx: RenderableAssetContext) -> str:
    label = clean_display_component(ctx.variant_label)
    role_suffix = ""
    if ctx.bundle_asset_count > 1:
        role_suffix = f" - {clean_display_component(ctx.asset_role)}"
    container = clean_display_component(ctx.asset_container)
    if "." in container:
        raise ValueError("asset_container must not contain dot path syntax")
    return f"{stem} - {label}{role_suffix}.{container}"
```

Use private helpers that exactly encode the templates from the design:

```python
def _movie_parts(root: str, ctx: RenderableAssetContext) -> tuple[str, ...]:
    if not isinstance(ctx.layout, MovieLayout):
        raise ValueError("movie context requires MovieLayout")
    movie_title = _required(ctx.movie_title, "movie_title")
    title = clean_display_component(movie_title)
    filename = _filename(title, ctx)
    if ctx.layout is MovieLayout.MOVIE_FLAT:
        return (root, filename)
    if ctx.layout is MovieLayout.MOVIE_FOLDER:
        return (root, title, filename)
    raise ValueError(f"unsupported movie layout: {ctx.layout}")
```

The episode helper must implement all four stems:

```python
def _episode_stem(ctx: RenderableAssetContext) -> str:
    series = clean_display_component(_required(ctx.series_title, "series_title"))
    title = clean_display_component(_required(ctx.episode_title, "episode_title"))
    season_number = _required_int(ctx.season_number, "season_number")
    episode_number = _required_int(ctx.episode_number, "episode_number")
    if ctx.naming is EpisodeNaming.SXXEXX_TITLE:
        return f"{series} - S{season_number:02d}E{episode_number:02d} - {title}"
    if ctx.naming is EpisodeNaming.ONE_XX_TITLE:
        return f"{series} - {season_number}x{episode_number:02d} - {title}"
    if ctx.naming is EpisodeNaming.ABSOLUTE_3_DIGIT_TITLE:
        absolute = _required_int(ctx.absolute_number, "absolute_number")
        return f"{series} - {absolute:03d} - {title}"
    if ctx.naming is EpisodeNaming.DATE_TITLE:
        aired_on = _required(ctx.aired_on, "aired_on")
        return f"{series} - {aired_on.isoformat()} - {title}"
    raise ValueError("episode context requires EpisodeNaming")
```

The track helper must implement both stems:

```python
def _track_stem(ctx: RenderableAssetContext) -> str:
    title = clean_display_component(_required(ctx.track_title, "track_title"))
    disc_number = _required_int(ctx.disc_number, "disc_number")
    track_number = _required_int(ctx.track_number, "track_number")
    if ctx.naming is TrackNaming.TRACK_NUMBER_TITLE:
        return f"{track_number:02d} - {title}"
    if ctx.naming is TrackNaming.DISC_TRACK_NUMBER_TITLE:
        return f"{disc_number:02d}-{track_number:02d} - {title}"
    raise ValueError("track context requires TrackNaming")
```

- [ ] **Step 4: Implement sidecar and root replacement helpers**

```python
def render_declared_sidecar_path(media_path: str, language: str) -> str:
    media_path = _validate_relative_posix_path(media_path)
    language = clean_display_component(language)
    stem, separator, _extension = media_path.rpartition(".")
    if not separator:
        raise ValueError("media_path must include a file extension")
    return _validate_relative_posix_path(f"{stem}.{language}.srt")


def replace_root_prefix(path: str, *, from_root: str, to_root: str) -> str:
    path = _validate_relative_posix_path(path)
    from_root = _validate_relative_posix_path(from_root)
    to_root = _validate_relative_posix_path(to_root)
    if path == from_root:
        return to_root
    prefix = f"{from_root}/"
    if not path.startswith(prefix):
        raise ValueError("path does not start with from_root as a path component")
    return _validate_relative_posix_path(f"{to_root}/{path[len(prefix):]}")
```

- [ ] **Step 5: Run renderer tests**

Run:

```bash
uv run pytest tests/contract/test_hierarchy_path_rendering.py -q --no-cov
```

Expected: pass.

- [ ] **Step 6: Commit the renderer**

```bash
git add src/chaos_librarian/path_rendering.py tests/contract/test_hierarchy_path_rendering.py
git commit -m "feat: add hierarchy path renderer"
```

## Task 6: Implement Topology Helpers

**Files:**

- Create: `src/chaos_librarian/topology.py`

- [ ] **Step 1: Add the public dataclass and imports**

```python
"""Typed topology walkers for scenario hierarchy contracts."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    Album,
    Artist,
    Asset,
    Bundle,
    Disc,
    Episode,
    Movie,
    Scenario,
    Season,
    Series,
    Track,
    Variant,
)


@dataclass(frozen=True, slots=True)
class AssetContext:
    parent_kind: ParentKind
    parent_id: str
    movie: Movie | None
    series: Series | None
    season: Season | None
    episode: Episode | None
    artist: Artist | None
    album: Album | None
    disc: Disc | None
    track: Track | None
    variant: Variant
    bundle: Bundle
    asset: Asset
    bundle_asset_count: int
```

- [ ] **Step 2: Implement declaration-order asset contexts**

```python
def iter_asset_contexts(scenario: Scenario) -> Iterator[AssetContext]:
    """Yield every playable/listenable asset context in declaration order."""
    for movie in scenario.movies:
        for variant in movie.variants:
            bundle = variant.bundle
            for asset in bundle.assets:
                yield AssetContext(
                    parent_kind=ParentKind.MOVIE,
                    parent_id=movie.id,
                    movie=movie,
                    series=None,
                    season=None,
                    episode=None,
                    artist=None,
                    album=None,
                    disc=None,
                    track=None,
                    variant=variant,
                    bundle=bundle,
                    asset=asset,
                    bundle_asset_count=len(bundle.assets),
                )

    for series in scenario.series:
        for season in series.seasons:
            for episode in season.episodes:
                for variant in episode.variants:
                    bundle = variant.bundle
                    for asset in bundle.assets:
                        yield AssetContext(
                            parent_kind=ParentKind.EPISODE,
                            parent_id=episode.id,
                            movie=None,
                            series=series,
                            season=season,
                            episode=episode,
                            artist=None,
                            album=None,
                            disc=None,
                            track=None,
                            variant=variant,
                            bundle=bundle,
                            asset=asset,
                            bundle_asset_count=len(bundle.assets),
                        )

    for artist in scenario.artists:
        for album in artist.albums:
            for disc in album.discs:
                for track in disc.tracks:
                    for variant in track.variants:
                        bundle = variant.bundle
                        for asset in bundle.assets:
                            yield AssetContext(
                                parent_kind=ParentKind.TRACK,
                                parent_id=track.id,
                                movie=None,
                                series=None,
                                season=None,
                                episode=None,
                                artist=artist,
                                album=album,
                                disc=disc,
                                track=track,
                                variant=variant,
                                bundle=bundle,
                                asset=asset,
                                bundle_asset_count=len(bundle.assets),
                            )
```

- [ ] **Step 3: Implement lookup helpers**

```python
def asset_contexts_by_id(scenario: Scenario) -> dict[str, AssetContext]:
    """Return `asset_id -> AssetContext` for every declared asset."""
    return {context.asset.id: context for context in iter_asset_contexts(scenario)}


def asset_ids_under_target(
    scenario: Scenario, *, target_kind: str, target_id: str
) -> tuple[str, ...]:
    """Return initially declared asset ids under a target in manifest order."""
    matched: list[str] = []
    for context in iter_asset_contexts(scenario):
        if _context_matches_target(context, target_kind=target_kind, target_id=target_id):
            matched.append(context.asset.id)
    if not matched and target_kind not in _SUPPORTED_TARGET_KINDS:
        raise ValueError(f"unknown target_kind: {target_kind}")
    return tuple(matched)
```

`_context_matches_target` must support exactly these `target_kind` values:
`movie`, `series`, `season`, `episode`, `artist`, `album`, `disc`, `track`,
`variant`, `bundle`, and `asset`.

- [ ] **Step 4: Run topology tests**

Run:

```bash
uv run pytest tests/contract/test_topology.py -q --no-cov
```

Expected: pass.

- [ ] **Step 5: Run the contract import boundary test**

Run:

```bash
uv run pytest tests/contract/test_contract_import_boundaries.py -q --no-cov
```

Expected: pass, proving `contract/*` does not import `chaos_librarian.topology`.

- [ ] **Step 6: Commit topology helpers**

```bash
git add \
  src/chaos_librarian/topology.py \
  tests/contract/test_topology.py \
  tests/contract/test_contract_import_boundaries.py
git commit -m "feat: add hierarchy topology helpers"
```

## Task 7: Replace Manifest V7 Contract

**Files:**

- Modify: `src/chaos_librarian/contract/manifest.py`
- Modify: `tests/contract/test_manifest.py`
- Modify: `tests/contract/test_canonicalize.py`

- [ ] **Step 1: Update manifest tests first**

Use `ParentKind` for variant parent references and pin every normalized domain row.

```python
from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAlbum,
    ManifestArtist,
    ManifestAsset,
    ManifestBundle,
    ManifestDisc,
    ManifestEpisode,
    ManifestLocation,
    ManifestMovie,
    ManifestSeason,
    ManifestSeries,
    ManifestSidecar,
    ManifestTrack,
    ManifestVariant,
    ManifestVersion,
)


def _empty_manifest() -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        movies=[],
        series=[],
        seasons=[],
        episodes=[],
        artists=[],
        albums=[],
        discs=[],
        tracks=[],
        variants=[],
        bundles=[],
        assets=[],
        versions=[],
        locations=[],
        sidecars=[],
    )


def test_populated_manifest_v7_roundtrip() -> None:
    manifest = Manifest(
        schema_version=7,
        movies=[ManifestMovie(id="movie_orbit", title="Orbit", layout="movie_folder")],
        series=[
            ManifestSeries(
                id="series_starline",
                title="Starline",
                layout="season_folders",
                episode_naming="sxxexx_title",
            )
        ],
        seasons=[
            ManifestSeason(
                id="season_specials",
                series_id="series_starline",
                season_number=0,
                title="Specials",
            )
        ],
        episodes=[
            ManifestEpisode(
                id="episode_special_01",
                season_id="season_specials",
                episode_number=1,
                title="First Signal",
                aired_on=None,
                absolute_number=None,
            )
        ],
        artists=[
            ManifestArtist(
                id="artist_north",
                name="North Index",
                layout="artist_album_disc",
                track_naming="track_number_title",
            )
        ],
        albums=[
            ManifestAlbum(
                id="album_winter",
                artist_id="artist_north",
                title="Winter Index",
                release_year=2024,
            )
        ],
        discs=[ManifestDisc(id="disc_winter_01", album_id="album_winter", disc_number=1)],
        tracks=[
            ManifestTrack(
                id="track_opening",
                disc_id="disc_winter_01",
                track_number=1,
                title="Opening",
                performers=["North Index"],
            )
        ],
        variants=[
            ManifestVariant(
                id="variant_movie",
                parent_kind=ParentKind.MOVIE,
                parent_id="movie_orbit",
                label="1080p",
            )
        ],
        bundles=[ManifestBundle(id="bundle_movie", variant_id="variant_movie")],
        assets=[
            ManifestAsset(
                id="asset_movie",
                bundle_id="bundle_movie",
                role="feature",
                container="mkv",
                duration_seconds=60,
            )
        ],
        versions=[ManifestVersion(id="version_0001", asset_id="asset_movie", index=0)],
        locations=[
            ManifestLocation(
                id="location_0001",
                asset_id="asset_movie",
                path="Movies/Orbit/Orbit - 1080p.mkv",
            )
        ],
        sidecars=[],
    )

    assert Manifest.model_validate_json(manifest.model_dump_json()) == manifest
```

Add an absence check for the removed row:

```python
def test_manifest_contract_removes_manifest_work() -> None:
    import chaos_librarian.contract.manifest as manifest_module

    assert not hasattr(manifest_module, "ManifestWork")
```

- [ ] **Step 2: Implement manifest rows**

In `src/chaos_librarian/contract/manifest.py`, delete `ManifestWork`, replace
`ManifestVariant.work_id`, and add:

```python
from chaos_librarian.contract.domain import ParentKind


class ManifestMovie(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    layout: str


class ManifestSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    layout: str
    episode_naming: str


class ManifestSeason(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    series_id: str
    season_number: int
    title: str


class ManifestEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    season_id: str
    episode_number: int
    title: str
    aired_on: date | None = None
    absolute_number: int | None = None


class ManifestArtist(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    layout: str
    track_naming: str


class ManifestAlbum(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    artist_id: str
    title: str
    release_year: int | None = None


class ManifestDisc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    album_id: str
    disc_number: int


class ManifestTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    disc_id: str
    track_number: int
    title: str
    performers: list[str] = Field(default_factory=list)


class ManifestVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    parent_kind: ParentKind
    parent_id: str
    label: str
```

Update `Manifest`:

```python
class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[7]
    movies: list[ManifestMovie]
    series: list[ManifestSeries]
    seasons: list[ManifestSeason]
    episodes: list[ManifestEpisode]
    artists: list[ManifestArtist]
    albums: list[ManifestAlbum]
    discs: list[ManifestDisc]
    tracks: list[ManifestTrack]
    variants: list[ManifestVariant]
    bundles: list[ManifestBundle]
    assets: list[ManifestAsset]
    versions: list[ManifestVersion]
    locations: list[ManifestLocation]
    sidecars: list[ManifestSidecar] = Field(default_factory=list)
```

- [ ] **Step 3: Update canonicalization tests**

Replace `ManifestWork` construction in `tests/contract/test_canonicalize.py` with
`ManifestMovie` and `ManifestVariant(parent_kind=ParentKind.MOVIE, parent_id=...)`.
Update structural assertions from `out["works"]` to `out["movies"]`.

- [ ] **Step 4: Run manifest tests**

Run:

```bash
uv run pytest \
  tests/contract/test_manifest.py \
  tests/contract/test_canonicalize.py \
  -q --no-cov
```

Expected: pass.

- [ ] **Step 5: Commit manifest v7**

```bash
git add \
  src/chaos_librarian/contract/manifest.py \
  tests/contract/test_manifest.py \
  tests/contract/test_canonicalize.py
git commit -m "feat: replace manifest hierarchy contract"
```

## Task 8: Replace Report Contracts

**Files:**

- Modify: `src/chaos_librarian/contract/reports.py`
- Modify: `tests/contract/test_reports.py`

- [ ] **Step 1: Write report contract tests**

Update imports:

```python
from chaos_librarian.contract import (
    ALBUM_REPORT_SCHEMA_VERSION,
    ARTIST_REPORT_SCHEMA_VERSION,
    ASSET_REPORT_SCHEMA_VERSION,
    BUNDLE_REPORT_SCHEMA_VERSION,
    DISC_REPORT_SCHEMA_VERSION,
    EPISODE_REPORT_SCHEMA_VERSION,
    MOVIE_REPORT_SCHEMA_VERSION,
    SEASON_REPORT_SCHEMA_VERSION,
    SERIES_REPORT_SCHEMA_VERSION,
    TRACK_REPORT_SCHEMA_VERSION,
    VARIANT_REPORT_SCHEMA_VERSION,
)
from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.reports import (
    AlbumReport,
    ArtistReport,
    AssetReport,
    BundleReport,
    DiscReport,
    EpisodeReport,
    MovieReport,
    SeasonReport,
    SeriesReport,
    TrackReport,
    VariantReport,
)
```

Add round-trip tests for every domain report:

```python
def test_domain_reports_round_trip() -> None:
    reports = [
        MovieReport(
            schema_version=1,
            movie_id="movie_orbit",
            title="Orbit",
            variant_ids=["variant_movie"],
            asset_ids=["asset_movie"],
        ),
        SeriesReport(
            schema_version=1,
            series_id="series_starline",
            title="Starline",
            season_ids=["season_01"],
            episode_ids=["episode_01"],
            asset_ids=["asset_episode"],
        ),
        SeasonReport(
            schema_version=1,
            season_id="season_01",
            series_id="series_starline",
            season_number=1,
            title="Season 1",
            episode_ids=["episode_01"],
            asset_ids=["asset_episode"],
        ),
        EpisodeReport(
            schema_version=1,
            episode_id="episode_01",
            season_id="season_01",
            episode_number=1,
            title="Pilot",
            aired_on=None,
            absolute_number=None,
            variant_ids=["variant_episode"],
            asset_ids=["asset_episode"],
        ),
        ArtistReport(
            schema_version=1,
            artist_id="artist_north",
            name="North Index",
            album_ids=["album_winter"],
            track_ids=["track_opening"],
            asset_ids=["asset_track"],
        ),
        AlbumReport(
            schema_version=1,
            album_id="album_winter",
            artist_id="artist_north",
            title="Winter Index",
            release_year=2024,
            disc_ids=["disc_01"],
            track_ids=["track_opening"],
            asset_ids=["asset_track"],
        ),
        DiscReport(
            schema_version=1,
            disc_id="disc_01",
            album_id="album_winter",
            disc_number=1,
            track_ids=["track_opening"],
            asset_ids=["asset_track"],
        ),
        TrackReport(
            schema_version=1,
            track_id="track_opening",
            disc_id="disc_01",
            track_number=1,
            title="Opening",
            performers=["North Index"],
            variant_ids=["variant_track"],
            asset_ids=["asset_track"],
        ),
    ]

    for report in reports:
        assert type(report).model_validate_json(report.model_dump_json()) == report
```

Pin variant and asset topology:

```python
def test_variant_report_uses_parent_kind_and_parent_id() -> None:
    report = VariantReport(
        schema_version=2,
        variant_id="variant_movie",
        parent_kind=ParentKind.MOVIE,
        parent_id="movie_orbit",
        label="1080p",
        bundle_id="bundle_movie",
        asset_ids=["asset_movie"],
    )

    assert VariantReport.model_validate_json(report.model_dump_json()) == report


def test_asset_report_v7_carries_topology_fields() -> None:
    snapshot = AssetSnapshot(location_path=None, version_id="version_0001", version_index=0)
    report = AssetReport(
        schema_version=7,
        asset_id="asset_episode",
        parent_kind=ParentKind.EPISODE,
        parent_id="episode_01",
        movie_id=None,
        series_id="series_starline",
        season_id="season_01",
        episode_id="episode_01",
        artist_id=None,
        album_id=None,
        disc_id=None,
        track_id=None,
        variant_id="variant_episode",
        bundle_id="bundle_episode",
        initial=snapshot,
        current=snapshot,
    )

    assert AssetReport.model_validate_json(report.model_dump_json()) == report
```

Add absence and constants checks:

```python
def test_work_report_is_removed() -> None:
    import chaos_librarian.contract.reports as reports_module

    assert not hasattr(reports_module, "WorkReport")


def test_domain_report_constants_start_at_one() -> None:
    assert MOVIE_REPORT_SCHEMA_VERSION == 1
    assert SERIES_REPORT_SCHEMA_VERSION == 1
    assert SEASON_REPORT_SCHEMA_VERSION == 1
    assert EPISODE_REPORT_SCHEMA_VERSION == 1
    assert ARTIST_REPORT_SCHEMA_VERSION == 1
    assert ALBUM_REPORT_SCHEMA_VERSION == 1
    assert DISC_REPORT_SCHEMA_VERSION == 1
    assert TRACK_REPORT_SCHEMA_VERSION == 1
    assert VARIANT_REPORT_SCHEMA_VERSION == 2
    assert ASSET_REPORT_SCHEMA_VERSION == 7
```

- [ ] **Step 2: Implement domain report models**

In `src/chaos_librarian/contract/reports.py`, remove `WorkReport`. Add imports:

```python
from datetime import date

from chaos_librarian.contract.domain import ParentKind
```

Add the eight domain report models with the field names from the design. Use
`schema_version: Literal[1]` on each. Update `AssetReport` and `VariantReport`:

```python
class AssetReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[7]
    asset_id: str
    parent_kind: ParentKind
    parent_id: str
    movie_id: str | None = None
    series_id: str | None = None
    season_id: str | None = None
    episode_id: str | None = None
    artist_id: str | None = None
    album_id: str | None = None
    disc_id: str | None = None
    track_id: str | None = None
    variant_id: str
    bundle_id: str
    initial: AssetSnapshot
    history: list[AssetHistoryEntry] = Field(default_factory=list)
    current: AssetSnapshot | None
    path_history: list[PathHistoryEntry] = Field(default_factory=list)
    version_history: list[VersionHistoryEntry] = Field(default_factory=list)


class VariantReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    variant_id: str
    parent_kind: ParentKind
    parent_id: str
    label: str
    bundle_id: str
    asset_ids: list[str]
```

- [ ] **Step 3: Run report tests**

Run:

```bash
uv run pytest tests/contract/test_reports.py -q --no-cov
```

Expected: pass.

- [ ] **Step 4: Commit report contracts**

```bash
git add src/chaos_librarian/contract/reports.py tests/contract/test_reports.py
git commit -m "feat: replace report hierarchy contracts"
```

## Task 9: Replace Observed-State V2 Contract

**Files:**

- Modify: `src/chaos_librarian/contract/observed_state.py`
- Modify: `tests/contract/test_observed_state.py`

- [ ] **Step 1: Update observed-state tests to v2 topology**

Use `schema_version: 2` in test payloads. Replace works with domain rows:

```python
def _topology_payload() -> dict[str, object]:
    payload = valid_observed_payload()
    asset = _first_asset(payload)
    asset["variant_ref"] = "variant-1"
    asset["bundle_ref"] = "bundle-1"
    asset["sidecars"] = [
        {
            "observed_ref": "sidecar-1",
            "kind": "subtitle",
            "path": "movies/Synthetic.eng.srt",
        }
    ]
    payload["movies"] = [{"observed_ref": "movie-1", "title": "Synthetic"}]
    payload["series"] = [{"observed_ref": "series-1", "title": "Starline"}]
    payload["seasons"] = [
        {
            "observed_ref": "season-1",
            "series_ref": "series-1",
            "season_number": 1,
            "title": "Season 1",
        }
    ]
    payload["episodes"] = [
        {
            "observed_ref": "episode-1",
            "season_ref": "season-1",
            "episode_number": 1,
            "title": "Pilot",
            "aired_on": None,
            "absolute_number": None,
        }
    ]
    payload["artists"] = [{"observed_ref": "artist-1", "name": "North Index"}]
    payload["albums"] = [
        {
            "observed_ref": "album-1",
            "artist_ref": "artist-1",
            "title": "Winter Index",
            "release_year": 2024,
        }
    ]
    payload["discs"] = [
        {"observed_ref": "disc-1", "album_ref": "album-1", "disc_number": 1}
    ]
    payload["tracks"] = [
        {
            "observed_ref": "track-1",
            "disc_ref": "disc-1",
            "track_number": 1,
            "title": "Opening",
            "performers": ["North Index"],
        }
    ]
    payload["variants"] = [
        {
            "observed_ref": "variant-1",
            "parent_kind": "movie",
            "parent_ref": "movie-1",
            "label": "hd",
        }
    ]
    payload["bundles"] = [
        {
            "observed_ref": "bundle-1",
            "variant_ref": "variant-1",
            "asset_refs": ["obs-asset-1"],
            "sidecar_refs": [{"asset_ref": "obs-asset-1", "sidecar_ref": "sidecar-1"}],
        }
    ]
    return payload
```

Add validator tests:

```python
def test_observed_state_rejects_old_work_ref() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["work_ref"] = "work-1"

    _assert_invalid(payload)


def test_observed_state_rejects_duplicate_domain_refs_across_domain_rows() -> None:
    payload = _topology_payload()
    payload["series"] = [{"observed_ref": "movie-1", "title": "Duplicate Ref"}]

    _assert_invalid(payload)


def test_observed_state_rejects_dangling_domain_parent_ref() -> None:
    payload = _topology_payload()
    payload["seasons"] = [
        {
            "observed_ref": "season-1",
            "series_ref": "missing-series",
            "season_number": 1,
            "title": "Season 1",
        }
    ]

    _assert_invalid(payload)


def test_observed_state_rejects_variant_parent_ref_with_wrong_kind() -> None:
    payload = _topology_payload()
    payload["variants"] = [
        {
            "observed_ref": "variant-1",
            "parent_kind": "track",
            "parent_ref": "movie-1",
            "label": "hd",
        }
    ]

    _assert_invalid(payload)
```

- [ ] **Step 2: Implement observed domain rows**

In `src/chaos_librarian/contract/observed_state.py`, import `ParentKind`, remove
`ObservedWork`, remove `ObservedAsset.work_ref`, and replace `ObservedVariant`:

```python
from chaos_librarian.contract.domain import ParentKind


class ObservedMovie(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_ref: str
    title: str | None = None


class ObservedSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_ref: str
    title: str | None = None


class ObservedSeason(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_ref: str
    series_ref: str
    season_number: int | None = None
    title: str | None = None


class ObservedEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_ref: str
    season_ref: str
    episode_number: int | None = None
    title: str | None = None
    aired_on: date | None = None
    absolute_number: int | None = None


class ObservedArtist(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_ref: str
    name: str | None = None


class ObservedAlbum(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_ref: str
    artist_ref: str
    title: str | None = None
    release_year: int | None = None


class ObservedDisc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_ref: str
    album_ref: str
    disc_number: int | None = None


class ObservedTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_ref: str
    disc_ref: str
    track_number: int | None = None
    title: str | None = None
    performers: list[str] = Field(default_factory=list)


class ObservedVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    observed_ref: str
    parent_kind: ParentKind
    parent_ref: str
    label: str | None = None
```

Update `ObservedState` fields:

```python
schema_version: Literal[2]
consumer: ObservedConsumer
run_id: uuid.UUID
observed_at: datetime
assets: list[ObservedAsset]
movies: list[ObservedMovie] = Field(default_factory=list)
series: list[ObservedSeries] = Field(default_factory=list)
seasons: list[ObservedSeason] = Field(default_factory=list)
episodes: list[ObservedEpisode] = Field(default_factory=list)
artists: list[ObservedArtist] = Field(default_factory=list)
albums: list[ObservedAlbum] = Field(default_factory=list)
discs: list[ObservedDisc] = Field(default_factory=list)
tracks: list[ObservedTrack] = Field(default_factory=list)
variants: list[ObservedVariant] = Field(default_factory=list)
bundles: list[ObservedBundle] = Field(default_factory=list)
events: list[ObservedEvent] = Field(default_factory=list)
```

- [ ] **Step 3: Implement duplicate and parent-ref validators**

Build domain maps in `_validate_topology_references` and validate all parent refs:

```python
domain_refs = [
    *(movie.observed_ref for movie in state.movies),
    *(series.observed_ref for series in state.series),
    *(season.observed_ref for season in state.seasons),
    *(episode.observed_ref for episode in state.episodes),
    *(artist.observed_ref for artist in state.artists),
    *(album.observed_ref for album in state.albums),
    *(disc.observed_ref for disc in state.discs),
    *(track.observed_ref for track in state.tracks),
]
_ensure_unique(domain_refs, kind="domain observed_ref")
```

Then validate:

- `ObservedSeason.series_ref` exists in `series`.
- `ObservedEpisode.season_ref` exists in `seasons`.
- `ObservedAlbum.artist_ref` exists in `artists`.
- `ObservedDisc.album_ref` exists in `albums`.
- `ObservedTrack.disc_ref` exists in `discs`.
- `ObservedVariant.parent_ref` exists in the map selected by `parent_kind`.
- `ObservedAsset.variant_ref` and `ObservedAsset.bundle_ref` still resolve when present.
- Bundle `asset_refs` and scoped `sidecar_refs` keep the current validation behavior.

- [ ] **Step 4: Run observed-state tests**

Run:

```bash
uv run pytest tests/contract/test_observed_state.py -q --no-cov
```

Expected: pass.

- [ ] **Step 5: Commit observed-state v2**

```bash
git add src/chaos_librarian/contract/observed_state.py tests/contract/test_observed_state.py
git commit -m "feat: replace observed state hierarchy contract"
```

## Task 10: Update Live Import Sites For Removed Symbols

**Files:**

- Modify: `src/chaos_librarian/engine/state.py`
- Modify: `src/chaos_librarian/engine/reports.py`
- Modify: `src/chaos_librarian/engine/writer.py`
- Modify: `src/chaos_librarian/adapter/fixture.py`
- Modify: `src/chaos_librarian/adapter/index.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Modify: `src/chaos_librarian/materializer/phase_b/__init__.py`
- Modify: `src/chaos_librarian/materializer/persistence/reports.py`
- Modify: `src/chaos_librarian/materializer/persistence/writer.py`
- Modify: `src/chaos_librarian/generation.py`
- Modify: `src/chaos_librarian/generation_lanes.py`
- Modify: `src/chaos_librarian/generation_planner.py`
- Modify: `src/chaos_librarian/validation/rules/profile_budgets.py`
- Modify: `src/chaos_librarian/cli/commands/inspect.py`
- Modify: `tests/support/adapter.py`
- Modify: existing tests under `tests/contract/`, `tests/engine/`, `tests/materializer/`,
  `tests/adapter/`, `tests/docs/`, and `tests/validation/` that import removed symbols.

- [ ] **Step 1: Get the exact stale-symbol list**

Run:

```bash
rg -n "Scenario\\.works|ManifestWork|WorkReport|ObservedWork|WORK_REPORT_SCHEMA_VERSION|\\bwork_id\\b|\\bwork_ref\\b" \
  src tests \
  --glob '!tests/fixtures/**'
```

Expected before this task: matches in source and tests. Expected after this task:
no output.

- [ ] **Step 2: Update `engine/state.py` to build normalized initial state**

Replace `works` with domain dictionaries on `WorldState`:

```python
movies: dict[str, ManifestMovie] = field(default_factory=dict)
series: dict[str, ManifestSeries] = field(default_factory=dict)
seasons: dict[str, ManifestSeason] = field(default_factory=dict)
episodes: dict[str, ManifestEpisode] = field(default_factory=dict)
artists: dict[str, ManifestArtist] = field(default_factory=dict)
albums: dict[str, ManifestAlbum] = field(default_factory=dict)
discs: dict[str, ManifestDisc] = field(default_factory=dict)
tracks: dict[str, ManifestTrack] = field(default_factory=dict)
```

Use `iter_asset_contexts()` and `render_asset_path()` for initial locations. The
minimal pattern:

```python
for context in iter_asset_contexts(scenario):
    state.variants[context.variant.id] = ManifestVariant(
        id=context.variant.id,
        parent_kind=context.parent_kind,
        parent_id=context.parent_id,
        label=context.variant.label,
    )
    state.bundles[context.bundle.id] = ManifestBundle(
        id=context.bundle.id,
        variant_id=context.variant.id,
    )
    state.assets[context.asset.id] = ManifestAsset(
        id=context.asset.id,
        bundle_id=context.bundle.id,
        role=context.asset.role,
        container=context.asset.container,
        duration_seconds=context.asset.duration_seconds,
    )
```

Seed domain rows in separate loops over `scenario.movies`, `scenario.series`, and
`scenario.artists` so rows are not duplicated by multi-asset bundles. Build each
initial `ManifestLocation.path` with a private adapter from `AssetContext` to
`RenderableAssetContext` and `scenario.library.roots[0].path`.

- [ ] **Step 3: Update report builders and writers to the new report set**

In `src/chaos_librarian/engine/reports.py`, replace `ReportSet.works` with:

```python
movies: tuple[MovieReport, ...]
series: tuple[SeriesReport, ...]
seasons: tuple[SeasonReport, ...]
episodes: tuple[EpisodeReport, ...]
artists: tuple[ArtistReport, ...]
albums: tuple[AlbumReport, ...]
discs: tuple[DiscReport, ...]
tracks: tuple[TrackReport, ...]
```

Build domain reports from `initial` manifest rows and transitive asset ids. Keep
asset, variant, and bundle report building sorted by id. Update
`src/chaos_librarian/engine/writer.py` to emit these directories:

```python
REPORT_DIRS = (
    "assets",
    "movies",
    "series",
    "seasons",
    "episodes",
    "artists",
    "albums",
    "discs",
    "tracks",
    "variants",
    "bundles",
)
```

Use each report's id field for filenames:
`movie_id`, `series_id`, `season_id`, `episode_id`, `artist_id`, `album_id`,
`disc_id`, `track_id`, `variant_id`, `bundle_id`, and `asset_id`.

- [ ] **Step 4: Update adapter fixture/report loading names**

In `src/chaos_librarian/adapter/fixture.py`, replace `OracleReports.works` with
domain report maps:

```python
movies: Mapping[str, MovieReport]
series: Mapping[str, SeriesReport]
seasons: Mapping[str, SeasonReport]
episodes: Mapping[str, EpisodeReport]
artists: Mapping[str, ArtistReport]
albums: Mapping[str, AlbumReport]
discs: Mapping[str, DiscReport]
tracks: Mapping[str, TrackReport]
```

Load the corresponding report directories and validate them against
`initial_manifest.movies`, `initial_manifest.series`, `initial_manifest.seasons`,
`initial_manifest.episodes`, `initial_manifest.artists`, `initial_manifest.albums`,
`initial_manifest.discs`, and `initial_manifest.tracks`.

- [ ] **Step 5: Update direct scenario walkers in runtime modules**

Replace direct `for work in scenario.works` loops with `iter_asset_contexts(scenario)` in:

- `src/chaos_librarian/materializer/preflight.py`
- `src/chaos_librarian/materializer/phase_b/__init__.py`

Where a module only needs assets, use `context.asset`. Where it needs parent
topology, use `context.parent_kind` and `context.parent_id`.

- [ ] **Step 6: Update generation budget references without adding new lanes**

In `src/chaos_librarian/generation_lanes.py`, replace lane config `works` with
`movies`. In `generation_planner.py` and `generation.py`, emit movie-shaped
payloads:

```python
return {
    "movies": _movies_payload(...),
    "series": [],
    "artists": [],
}
```

Keep the generated lane names unchanged in this slice. The `tv-topology` and
`music-topology` lanes belong to the generation/docs child plan.

- [ ] **Step 7: Update inspect counts**

In `src/chaos_librarian/cli/commands/inspect.py`, replace the old work count with
domain counts:

```python
"movies": len(manifest_current.movies),
"series": len(manifest_current.series),
"seasons": len(manifest_current.seasons),
"episodes": len(manifest_current.episodes),
"artists": len(manifest_current.artists),
"albums": len(manifest_current.albums),
"discs": len(manifest_current.discs),
"tracks": len(manifest_current.tracks),
```

Update the text output to print these counts on two concise lines so no removed
`works` key remains in source.

- [ ] **Step 8: Update type-checked tests/support helpers**

Convert support fixtures to movie-shaped contracts. Example replacement for old
manifest construction:

```python
Manifest(
    schema_version=7,
    movies=[ManifestMovie(id="movie-a", title="Synthetic", layout="movie_flat")],
    series=[],
    seasons=[],
    episodes=[],
    artists=[],
    albums=[],
    discs=[],
    tracks=[],
    variants=[
        ManifestVariant(
            id="variant-a",
            parent_kind=ParentKind.MOVIE,
            parent_id="movie-a",
            label="hd",
        )
    ],
    bundles=[ManifestBundle(id="bundle-a", variant_id="variant-a")],
    assets=[...],
    versions=[...],
    locations=[...],
    sidecars=[],
)
```

Convert observed topology helpers to `movies` plus
`ObservedVariant(parent_kind="movie", parent_ref="consumer-movie")`. Remove every
`work_ref`.

- [ ] **Step 9: Prove stale symbols are gone**

Run:

```bash
rg -n "Scenario\\.works|ManifestWork|WorkReport|ObservedWork|WORK_REPORT_SCHEMA_VERSION|\\bwork_id\\b|\\bwork_ref\\b" \
  src tests \
  --glob '!tests/fixtures/**'
```

Expected: no output.

- [ ] **Step 10: Run type check for import coherence**

Run:

```bash
uv run ty check src tests
```

Expected: exits `0`. Any type error caused by removed hierarchy symbols is fixed in
this task, not passed to a later child plan.

- [ ] **Step 11: Commit live import cleanup**

```bash
git add src tests
git commit -m "feat: update imports for hierarchy contracts"
```

## Task 11: Export Schemas

**Files:**

- Modify: `src/chaos_librarian/schema_export.py`
- Modify: `tests/contract/test_schema_export.py`
- Delete: `schemas/work-report.schema.json`
- Regenerate: `schemas/*.schema.json`

- [ ] **Step 1: Update schema export imports and model list**

Remove `WorkReport`; import every domain report:

```python
from chaos_librarian.contract.reports import (
    AlbumReport,
    ArtistReport,
    AssetReport,
    BundleReport,
    DiscReport,
    EpisodeReport,
    MovieReport,
    SeasonReport,
    SeriesReport,
    TrackReport,
    VariantReport,
)
```

Update `MODELS`:

```python
("asset-report.schema.json", AssetReport),
("movie-report.schema.json", MovieReport),
("series-report.schema.json", SeriesReport),
("season-report.schema.json", SeasonReport),
("episode-report.schema.json", EpisodeReport),
("artist-report.schema.json", ArtistReport),
("album-report.schema.json", AlbumReport),
("disc-report.schema.json", DiscReport),
("track-report.schema.json", TrackReport),
("variant-report.schema.json", VariantReport),
("bundle-report.schema.json", BundleReport),
```

- [ ] **Step 2: Update schema export tests**

In `tests/contract/test_schema_export.py`, replace the expected schema name set
with:

```python
assert names == {
    "album-report.schema.json",
    "artist-report.schema.json",
    "asset-report.schema.json",
    "bundle-report.schema.json",
    "capabilities.schema.json",
    "disc-report.schema.json",
    "divergence.schema.json",
    "episode-report.schema.json",
    "journal.schema.json",
    "manifest.schema.json",
    "materialization.schema.json",
    "movie-report.schema.json",
    "observed-state.schema.json",
    "replay-bundle.schema.json",
    "run-sentinel.schema.json",
    "scenario.schema.json",
    "season-report.schema.json",
    "series-report.schema.json",
    "track-report.schema.json",
    "validation.schema.json",
    "variant-report.schema.json",
}
```

Update the generation profile version assertion:

```python
assert profile_version["const"] == 3
```

- [ ] **Step 3: Remove the old work-report schema and regenerate**

Run:

```bash
git rm schemas/work-report.schema.json
uv run python -m chaos_librarian.schema_export --write
```

Expected: schema export writes the new report schemas and does not recreate
`schemas/work-report.schema.json`.

- [ ] **Step 4: Run schema tests and drift gate**

Run:

```bash
uv run pytest tests/contract/test_schema_export.py -q --no-cov
uv run python -m chaos_librarian.schema_export --check
```

Expected:

- `pytest` passes.
- Drift gate prints `All 21 schemas up-to-date.`

- [ ] **Step 5: Commit schema export and artifacts**

```bash
git add src/chaos_librarian/schema_export.py tests/contract/test_schema_export.py schemas
git commit -m "feat: export hierarchy contract schemas"
```

## Task 12: Final Focused Verification

**Files:**

- All files changed in Tasks 1-11.

- [ ] **Step 1: Run focused contract and renderer tests**

Run:

```bash
uv run pytest \
  tests/contract/test_contract_constants.py \
  tests/contract/test_contract_import_boundaries.py \
  tests/contract/test_scenario.py \
  tests/contract/test_hierarchy_path_rendering.py \
  tests/contract/test_topology.py \
  tests/contract/test_manifest.py \
  tests/contract/test_reports.py \
  tests/contract/test_observed_state.py \
  tests/contract/test_replay_bundle.py \
  tests/contract/test_schema_export.py \
  tests/contract/test_canonicalize.py \
  -q --no-cov
```

Expected: all selected tests pass.

- [ ] **Step 2: Run stale-symbol and import-boundary searches**

Run:

```bash
rg -n "Scenario\\.works|ManifestWork|WorkReport|ObservedWork|WORK_REPORT_SCHEMA_VERSION|\\bwork_id\\b|\\bwork_ref\\b" \
  src tests \
  --glob '!tests/fixtures/**'
rg -n "chaos_librarian\\.topology|from chaos_librarian import topology" \
  src/chaos_librarian/contract
```

Expected: both commands produce no output.

- [ ] **Step 3: Run required quality gates**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Expected:

- `ruff check` exits `0`.
- `ruff format --check` exits `0`.
- `ty check src tests` exits `0`.
- Schema drift gate prints `All 21 schemas up-to-date.`

- [ ] **Step 4: Review the final diff for scope**

Run:

```bash
git diff --stat HEAD
git diff --name-only HEAD
```

Expected changed paths are limited to the files listed in this plan plus regenerated
schema artifacts. No docs prose, validation rules, materializer audio synthesis,
adapter comparison logic, or generation topology lanes are included in this slice.

- [ ] **Step 5: Commit final fixes if verification required edits**

If Step 3 or Step 4 required edits, commit the focused fixes:

```bash
git add src tests schemas
git commit -m "fix: complete hierarchy contract verification"
```

If no edits were needed after Task 11, keep the branch as-is.

## Self-Review Checklist For Implementers

Before marking this child plan complete, verify:

- Scenario v12 accepts movie-only, TV-only with `season_number: 0`, and music-only payloads.
- Scenario v12 rejects `works`.
- `Work`, `ManifestWork`, `WorkReport`, `ObservedWork`, `work_id`, and `work_ref`
  are gone from live source and type-checked tests.
- `ParentKind` lives only in `chaos_librarian.contract.domain`; no contract module
  imports `chaos_librarian.topology`.
- `topology.py` exposes exactly `AssetContext`, `iter_asset_contexts`,
  `asset_contexts_by_id`, and `asset_ids_under_target` as public helpers.
- `path_rendering.py` exposes exactly `RenderableAssetContext`,
  `clean_display_component`, `render_asset_path`, `render_declared_sidecar_path`,
  and `replace_root_prefix` as public helpers.
- Renderer tests pin all movie, TV, and music layout/naming recipes and invalid
  path cases from the spec.
- Manifest v7 uses normalized domain lists and `ManifestVariant.parent_kind/parent_id`.
- Reports remove work-report and add all eight domain report schemas.
- Observed-state v2 uses normalized domain refs and validates duplicates plus
  parent refs.
- `schema_export.MODELS` has no `work-report.schema.json` entry and includes all
  domain report schemas.
- `schemas/work-report.schema.json` is deleted and schema drift check passes.
