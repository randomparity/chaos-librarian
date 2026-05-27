"""Contract tests for content-source capability and evidence models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import scenario as scenario_contract
from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceEvidence,
    ContentSourceProviderCapability,
    ContentTrackKind,
)
from chaos_librarian.contract.scenario import (
    AudioNoiseColor,
    AudioSampleFormat,
    VideoColorRange,
    VideoColorSpace,
)


def test_content_source_evidence_round_trips_builtin_video() -> None:
    evidence = ContentSourceEvidence(
        asset_id="asset_main",
        track_kind=ContentTrackKind.VIDEO,
        track_index=None,
        source="color_bars",
        provider="builtin-lavfi",
        recipe_digest="sha256:" + "0" * 64,
        color_space=VideoColorSpace.BT709,
        color_range=VideoColorRange.FULL,
        resolution_sequence=scenario_contract.VideoResolutionSequence.SD_TO_HD,
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
        cache_key=None,
        content_hash=None,
        origin_uri=None,
        license=None,
    )

    loaded = ContentSourceEvidence.model_validate_json(evidence.model_dump_json())

    assert loaded == evidence
    assert loaded.color_space is VideoColorSpace.BT709
    assert loaded.color_range is VideoColorRange.FULL
    assert loaded.resolution_sequence is scenario_contract.VideoResolutionSequence.SD_TO_HD


def test_content_source_evidence_round_trips_cached_audio() -> None:
    evidence = ContentSourceEvidence.model_validate(
        {
            "asset_id": "asset_main",
            "track_kind": "audio",
            "track_index": 0,
            "source": "future_tts",
            "provider": "example-tts",
            "recipe_digest": "sha256:" + "1" * 64,
            "cache_disposition": "miss_stored",
            "cache_key": "sha256:" + "2" * 64,
            "content_hash": "sha256:" + "3" * 64,
            "origin_uri": "tts:example:voice-a",
            "license": "generated-test-fixture",
        }
    )

    loaded = ContentSourceEvidence.model_validate_json(evidence.model_dump_json())

    assert loaded.track_kind is ContentTrackKind.AUDIO
    assert loaded.cache_disposition is CacheDisposition.MISS_STORED
    assert loaded.cache_key == "sha256:" + "2" * 64
    assert loaded.content_hash == "sha256:" + "3" * 64
    assert loaded.origin_uri == "tts:example:voice-a"
    assert loaded.license == "generated-test-fixture"


def test_content_source_evidence_round_trips_audio_recipe_parameters() -> None:
    evidence = ContentSourceEvidence(
        asset_id="asset_main",
        track_kind=ContentTrackKind.AUDIO,
        track_index=0,
        source="noise",
        provider="builtin-lavfi",
        recipe_digest="sha256:" + "4" * 64,
        noise_color=AudioNoiseColor.BROWN,
        sample_rate=88200,
        sample_format=AudioSampleFormat.FLT,
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
    )

    loaded = ContentSourceEvidence.model_validate_json(evidence.model_dump_json())

    assert loaded == evidence
    assert loaded.noise_color is AudioNoiseColor.BROWN
    assert loaded.sample_rate == 88200
    assert loaded.sample_format is AudioSampleFormat.FLT


def test_content_source_evidence_rejects_bad_recipe_digest() -> None:
    payload = {
        "asset_id": "asset_main",
        "track_kind": "video",
        "source": "color_bars",
        "provider": "builtin-lavfi",
        "recipe_digest": "not-a-digest",
        "cache_disposition": "not_cacheable",
    }

    with pytest.raises(ValidationError):
        ContentSourceEvidence.model_validate(payload)


def test_content_source_provider_capability_round_trips() -> None:
    capability = ContentSourceProviderCapability(
        name="builtin-lavfi",
        available=True,
        requires_network=False,
        requires_cache=False,
        required_tool="ffmpeg",
        cache_dir=None,
        cache_writable=None,
        reason=None,
        sources=(
            "audio:channel_tones",
            "audio:silence",
            "audio:sine",
            "video:color_bars",
            "video:mandelbrot",
            "video:solid_color",
        ),
    )

    loaded = ContentSourceProviderCapability.model_validate_json(capability.model_dump_json())

    assert loaded == capability
