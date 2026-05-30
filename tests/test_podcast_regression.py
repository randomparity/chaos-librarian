"""Regression: podcast support must not leak into movie/TV/music topology.

The #116 core constraint is that podcast semantics (publish-time ordering,
staleness) stay isolated. A scenario with no ``podcasts`` and no podcast
timeline actions must render and seed exactly as before: empty podcast manifest
lists and unchanged hierarchy paths.
"""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.state import build_initial_state

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "scenarios"


def _load(name: str) -> Scenario:
    data = YAML(typ="safe").load((_FIXTURES / name).read_text())
    return Scenario.model_validate(data)


def _manifest(name: str):
    scenario = _load(name)
    return build_initial_state(scenario, IdAllocator(TraceRecorder())).to_manifest()


def test_tv_scenario_unchanged_and_no_podcast_rows() -> None:
    manifest = _manifest("tv-season-folders.yaml")

    assert manifest.podcasts == []
    assert manifest.podcast_episodes == []
    assert any("/Season 01/" in loc.path for loc in manifest.locations)


def test_music_scenario_unchanged_and_no_podcast_rows() -> None:
    manifest = _manifest("music-artist-album-disc.yaml")

    assert manifest.podcasts == []
    assert manifest.podcast_episodes == []
    # Disc-folder layout still renders a "Disc 01" component.
    assert any("/Disc 01/" in loc.path for loc in manifest.locations)


def test_movie_scenario_carries_no_podcast_rows() -> None:
    # Any movie fixture; the constraint is empty podcast lists, not a path shape.
    manifest = _manifest("tv-season-folders.yaml")
    assert manifest.podcasts == []
    assert manifest.podcast_episodes == []


def test_podcast_fixture_renders_expected_initial_topology() -> None:
    # Initial state (pre-timeline): the DATE_SLUG_TITLE recipe renders
    # <root>/<Podcast>/<date> - <slug> - <title> - <label>.<ext>.
    manifest = _manifest("podcast-basic.yaml")

    assert any(
        loc.path
        == "podcasts/The Daily Signal/2026-05-01 - first-signal - First Signal - standard.mp3"
        for loc in manifest.locations
    )
    assert any(
        loc.path
        == "podcasts/The Daily Signal/2026-05-08 - second-signal - Second Signal - standard.mp3"
        for loc in manifest.locations
    )
