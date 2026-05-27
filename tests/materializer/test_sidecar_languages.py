from __future__ import annotations

import pytest

from chaos_librarian.contract.scenario import (
    CreateSidecarEvent,
    Scenario,
    SidecarKind,
)
from chaos_librarian.errors import ChaosLibrarianValueError
from chaos_librarian.materializer import replay as replay_module
from chaos_librarian.materializer import run as run_module
from chaos_librarian.materializer import wall_clock as wall_clock_module
from chaos_librarian.materializer.phase_b.sidecar_languages import timeline_sidecar_languages


def _scenario_with_timeline(*events: CreateSidecarEvent) -> Scenario:
    scenario = _movie_scenario()
    return scenario.model_copy(update={"timeline": events})


def _movie_scenario() -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 16,
            "scenario_id": "materializer-sidecar-language-test",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "movies-hd", "path": "library/movies-hd"}]},
            "movies": [
                {
                    "id": "movie_001",
                    "title": "Movie 1",
                    "layout": "movie_flat",
                    "variants": [
                        {
                            "id": "variant_001",
                            "label": "default",
                            "bundle": {
                                "id": "bundle_001",
                                "assets": [
                                    {
                                        "id": "asset_hd_main",
                                        "role": "primary_video",
                                        "container": "mkv",
                                        "duration_seconds": 1,
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
            "series": [],
            "artists": [],
            "timeline": [],
        }
    )


def test_timeline_sidecar_languages_rejects_subtitle_without_language() -> None:
    event = CreateSidecarEvent(
        id="cs1",
        at="0ns",
        target="asset_hd_main",
        to="library/movies-hd/asset_hd_main.eng.srt",
        language="eng",
    ).model_copy(update={"language": None})
    scenario = _scenario_with_timeline(event)

    with pytest.raises(ChaosLibrarianValueError, match="subtitle sidecar"):
        timeline_sidecar_languages(scenario)


def test_timeline_sidecar_languages_ignores_non_subtitle_sidecars() -> None:
    subtitle_event = CreateSidecarEvent(
        id="cs1",
        at="0ns",
        target="asset_hd_main",
        to="library/movies-hd/asset_hd_main.eng.srt",
        language="eng",
    )
    poster_event = CreateSidecarEvent(
        id="cs2",
        at="1ns",
        target="asset_hd_main",
        to="library/movies-hd/poster.jpg",
        kind=SidecarKind.POSTER,
    )
    scenario = _scenario_with_timeline(subtitle_event, poster_event)

    assert timeline_sidecar_languages(scenario) == {"asset_hd_main": frozenset({"eng"})}


def test_materializer_entrypoints_do_not_reexport_private_language_helper() -> None:
    assert not hasattr(run_module, "_timeline_sidecar_languages")
    assert not hasattr(replay_module, "_timeline_sidecar_languages")
    assert not hasattr(wall_clock_module, "_timeline_sidecar_languages")
