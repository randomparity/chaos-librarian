"""Content-source provider registry coverage."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.content_sources import CacheDisposition, ContentTrackKind
from chaos_librarian.contract.scenario import AudioSource, VideoSource
from chaos_librarian.materializer.content_sources import (
    SourceRequest,
    collect_content_source_capabilities,
    resolve_audio_source,
    resolve_video_source,
)
from chaos_librarian.materializer.errors import UnsupportedMaterializationError


def _video_request(source: str = "color_bars") -> SourceRequest:
    return SourceRequest(
        asset_id="asset_main",
        track_kind=ContentTrackKind.VIDEO,
        track_index=None,
        source=source,
        seed=42,
        duration_s=2.0,
        width=640,
        height=480,
        fps=24,
        channels=None,
    )


def _audio_request(source: str = "sine") -> SourceRequest:
    return SourceRequest(
        asset_id="asset_main",
        track_kind=ContentTrackKind.AUDIO,
        track_index=0,
        source=source,
        seed=42,
        duration_s=2.0,
        width=None,
        height=None,
        fps=None,
        channels="stereo",
    )


def test_resolve_video_source_returns_input_and_evidence() -> None:
    resolution = resolve_video_source(
        source=VideoSource.COLOR_BARS,
        request=_video_request(),
    )

    assert resolution.ffmpeg_input.lavfi == "smptebars=size=640x480:rate=24"
    assert resolution.evidence.asset_id == "asset_main"
    assert resolution.evidence.provider == "builtin-lavfi"
    assert resolution.evidence.cache_disposition == CacheDisposition.NOT_CACHEABLE


def test_resolve_audio_source_records_track_index() -> None:
    resolution = resolve_audio_source(
        source=AudioSource.SINE,
        request=_audio_request(),
    )

    assert resolution.ffmpeg_input.lavfi is not None
    assert resolution.evidence.track_kind == ContentTrackKind.AUDIO
    assert resolution.evidence.track_index == 0


def test_unregistered_video_source_is_rejected() -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc:
        resolve_video_source(source=VideoSource.NOISE, request=_video_request(source="noise"))

    assert exc.value.field == "video.source"


def test_collect_content_source_capabilities_reports_builtin_provider() -> None:
    capabilities = collect_content_source_capabilities(ffmpeg_available=True)

    assert [provider.name for provider in capabilities.providers] == ["builtin-lavfi"]
    provider = capabilities.providers[0]
    assert provider.available is True
    assert "video:color_bars" in provider.sources


def test_collect_content_source_capabilities_marks_builtin_unavailable_without_ffmpeg() -> None:
    capabilities = collect_content_source_capabilities(ffmpeg_available=False)

    provider = capabilities.providers[0]
    assert provider.name == "builtin-lavfi"
    assert provider.available is False
    assert provider.reason == "required tool unavailable: ffmpeg"
