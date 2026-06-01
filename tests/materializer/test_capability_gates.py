"""Direct tests for scenario-dependent materializer capability gates."""

from __future__ import annotations

import pytest

from chaos_librarian.contract import CAPABILITIES_SCHEMA_VERSION
from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.content_sources import ContentSourceCapabilities
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.materializer.errors import CapabilityGateError
from chaos_librarian.materializer.preparation.capability_gates import (
    assert_capable_for_audio_recipes,
    assert_capable_for_hdr_video,
    assert_capable_for_matroska_muxing_profiles,
    assert_capable_for_resolution_switch_video,
    assert_capable_for_webm_video,
)


def test_audio_recipe_gate_reports_required_recipe_fields() -> None:
    """The audio gate payload is the CLI contract for missing recipe support."""
    scenario = _scenario_with_asset(
        {
            "id": "asset_noise",
            "role": "main",
            "container": "mkv",
            "duration_seconds": 1.0,
            "audio": [
                {
                    "source": "noise",
                    "codec": "aac",
                    "channels": "stereo",
                    "language": "eng",
                    "noise_color": "pink",
                    "sample_rate": 96000,
                    "sample_format": "flt",
                }
            ],
        }
    )

    with pytest.raises(CapabilityGateError) as exc_info:
        assert_capable_for_audio_recipes(
            scenario,
            _capabilities(materialize_audio_recipes=False),
        )

    error = exc_info.value
    assert error.asset_id == "asset_noise"
    assert error.field == "ready_for.materialize_audio_recipes"
    assert error.payload == {
        "capability": "ready_for.materialize_audio_recipes",
        "required_filter": "anoisesrc",
        "audio_source": "noise",
        "noise_color": "pink",
        "sample_rate": 96000,
        "sample_format": "flt",
    }


def test_matroska_muxing_profile_gate_reports_required_tool() -> None:
    """Muxing-profile failures must identify the missing mkvmerge dependency."""
    scenario = _scenario_with_asset(
        {
            "id": "asset_mux",
            "role": "main",
            "container": "mkv",
            "duration_seconds": 1.0,
            "matroska_muxing_profile": "no_cues",
            "video": {"source": "color_bars", "codec": "h264", "resolution": "sd"},
        }
    )

    with pytest.raises(CapabilityGateError) as exc_info:
        assert_capable_for_matroska_muxing_profiles(
            scenario,
            _capabilities(materialize_matroska_muxing_profiles=False),
        )

    error = exc_info.value
    assert error.asset_id == "asset_mux"
    assert error.field == "ready_for.materialize_matroska_muxing_profiles"
    assert error.payload == {
        "capability": "ready_for.materialize_matroska_muxing_profiles",
        "required_tool": "mkvmerge",
    }


def test_webm_video_gate_reports_required_encoder() -> None:
    """WebM failures must name libvpx-vp9 so users know what FFmpeg lacks."""
    scenario = _scenario_with_asset(
        {
            "id": "asset_webm",
            "role": "main",
            "container": "webm",
            "duration_seconds": 1.0,
            "video": {"source": "color_bars", "codec": "vp9", "resolution": "sd"},
        }
    )

    with pytest.raises(CapabilityGateError) as exc_info:
        assert_capable_for_webm_video(
            scenario,
            _capabilities(materialize_webm_video=False),
        )

    error = exc_info.value
    assert error.asset_id == "asset_webm"
    assert error.field == "ready_for.materialize_webm_video"
    assert error.payload == {
        "capability": "ready_for.materialize_webm_video",
        "required_encoder": "libvpx-vp9",
    }


def test_hdr_video_gate_reports_required_encoder_filter_and_pixel_format() -> None:
    """HDR failures need all FFmpeg capabilities that make HDR materializable."""
    scenario = _scenario_with_asset(
        {
            "id": "asset_hdr",
            "role": "main",
            "container": "mkv",
            "duration_seconds": 1.0,
            "video": {
                "source": "color_bars",
                "codec": "hevc",
                "resolution": "sd",
                "hdr_mode": "hdr10",
            },
        }
    )

    with pytest.raises(CapabilityGateError) as exc_info:
        assert_capable_for_hdr_video(
            scenario,
            _capabilities(materialize_hdr_video=False),
        )

    error = exc_info.value
    assert error.asset_id == "asset_hdr"
    assert error.field == "ready_for.materialize_hdr_video"
    assert error.payload == {
        "capability": "ready_for.materialize_hdr_video",
        "required_encoder": "libx265",
        "required_filter": "setparams",
        "required_pixel_format": "yuv420p10le",
        "hdr_mode": "hdr10",
    }


def test_resolution_switch_gate_reports_required_encoder_and_sequence() -> None:
    """Resolution-switch failures must preserve the requested sequence value."""
    scenario = _scenario_with_asset(
        {
            "id": "asset_switch",
            "role": "main",
            "container": "ts",
            "duration_seconds": 1.0,
            "video": {
                "source": "color_bars",
                "codec": "h264",
                "resolution": "sd",
                "resolution_sequence": "sd_to_hd",
            },
        }
    )

    with pytest.raises(CapabilityGateError) as exc_info:
        assert_capable_for_resolution_switch_video(
            scenario,
            _capabilities(materialize_resolution_switch_video=False),
        )

    error = exc_info.value
    assert error.asset_id == "asset_switch"
    assert error.field == "ready_for.materialize_resolution_switch_video"
    assert error.payload == {
        "capability": "ready_for.materialize_resolution_switch_video",
        "required_encoder": "libx264",
        "resolution_sequence": "sd_to_hd",
    }


def _scenario_with_asset(asset: dict[str, object]) -> Scenario:
    raw: dict[str, object] = {
        "schema_version": 32,
        "scenario_id": "capability-gate-test",
        "seed": 1,
        "duration_scale": "short",
        "library": {"roots": [{"id": "movies", "path": "movies"}]},
        "movies": [
            {
                "id": "movie_gate",
                "title": "Capability Gate",
                "layout": "movie_flat",
                "variants": [
                    {
                        "id": "variant_gate",
                        "label": "default",
                        "bundle": {"id": "bundle_gate", "assets": [asset]},
                    }
                ],
            }
        ],
        "series": [],
        "artists": [],
        "timeline": [],
    }
    return Scenario.model_validate(raw)


def _capabilities(
    *,
    materialize_hdr_video: bool = True,
    materialize_resolution_switch_video: bool = True,
    materialize_audio_recipes: bool = True,
    materialize_matroska_muxing_profiles: bool = True,
    materialize_webm_video: bool = True,
) -> Capabilities:
    return Capabilities(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=False,
            materialize_hevc_video=True,
            materialize_hdr_video=materialize_hdr_video,
            materialize_resolution_switch_video=materialize_resolution_switch_video,
            materialize_audio_recipes=materialize_audio_recipes,
            materialize_matroska_muxing_profiles=materialize_matroska_muxing_profiles,
            materialize_webm_video=materialize_webm_video,
        ),
    )
