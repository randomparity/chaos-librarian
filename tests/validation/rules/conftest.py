"""Shared fixtures for ``tests/validation/rules/``.

Exposes one factory fixture (``minimal_scenario``) plus three tiny helpers
(``empty_index``, ``as_list``, ``as_dict``). Every per-rule test module
draws from this conftest via pytest's auto-injection — no cross-test
imports needed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest

from chaos_librarian.scenario_io import LineIndex

ListNarrower = Callable[[object], list[dict[str, object]]]
DictNarrower = Callable[[object], dict[str, object]]
ScenarioBuilder = Callable[..., dict[str, object]]


@pytest.fixture
def empty_index() -> LineIndex:
    """A fresh empty ``LineIndex`` for tests that don't drive the line-mapping."""
    return LineIndex()


@pytest.fixture
def as_list() -> ListNarrower:
    """Narrow ``object`` to a typed list for test-site subscripting.

    The scenario tree returned by ``minimal_scenario`` types everything as
    ``object`` (matching what semantic rules see). Tests know the concrete
    shape and use this fixture to drill in without sprinkling casts.
    """

    def _narrow(node: object) -> list[dict[str, object]]:
        return cast("list[dict[str, object]]", node)

    return _narrow


@pytest.fixture
def as_dict() -> DictNarrower:
    """Narrow ``object`` to a typed dict; mirror of ``as_list``."""

    def _narrow(node: object) -> dict[str, object]:
        return cast("dict[str, object]", node)

    return _narrow


@pytest.fixture
def minimal_scenario() -> ScenarioBuilder:
    """Factory: build a minimal valid-shape scenario. Overrides can add duplicates."""

    def _build(
        timeline: list[dict[str, object]] | None = None,
        asset_id: str = "a",
        asset_subtitles: list[dict[str, object]] | None = None,
        **overrides: object,
    ) -> dict[str, object]:
        asset: dict[str, object] = {
            "id": asset_id,
            "role": "main",
            "container": "mkv",
            "duration_seconds": 1,
            "video": {"source": "color_bars", "codec": "h264", "resolution": "sd"},
            "audio": [{"source": "sine", "codec": "aac", "channels": "stereo", "language": "eng"}],
        }
        if asset_subtitles is not None:
            asset["subtitles"] = asset_subtitles
        base: dict[str, object] = {
            "schema_version": 14,
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
        base.update(overrides)
        return base

    return _build


@pytest.fixture
def series_scenario() -> ScenarioBuilder:
    """Factory: build a minimal valid-shape series hierarchy scenario."""

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
            "audio": [{"source": "sine", "codec": "aac", "channels": "stereo", "language": "eng"}],
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
            "schema_version": 14,
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
    """Factory: build a minimal valid-shape music hierarchy scenario."""

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
            "audio": [{"source": "sine", "codec": "flac", "channels": "stereo", "language": "eng"}],
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
            "schema_version": 14,
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
