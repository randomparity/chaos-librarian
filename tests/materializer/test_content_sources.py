"""Content-source provider registry coverage."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentTrackKind,
)
from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    AudioChannelLayout,
    AudioSource,
    AudioTrack,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.materializer import content_sources
from chaos_librarian.materializer.content_sources import (
    AudioSourceRequest,
    VideoSourceRequest,
    collect_content_source_capabilities,
    resolve_audio_source,
    resolve_video_source,
)
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.preflight import preflight_asset
from chaos_librarian.materializer.tooling.recipes import FFmpegInput


def _video_request() -> VideoSourceRequest:
    return VideoSourceRequest(
        asset_id="asset_main",
        track_index=None,
        seed=42,
        duration_s=2.0,
        width=640,
        height=480,
        fps=24,
    )


def _audio_request() -> AudioSourceRequest:
    return AudioSourceRequest(
        asset_id="asset_main",
        track_index=0,
        seed=42,
        duration_s=2.0,
        channels="stereo",
    )


def _video() -> VideoTrack:
    return VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution="sd")


def _audio() -> AudioTrack:
    return AudioTrack(
        source=AudioSource.SINE,
        codec="aac",
        channels=AudioChannelLayout.STEREO,
        language="eng",
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


def test_resolve_video_source_digest_changes_with_recipe_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _video_request()
    original = resolve_video_source(source=VideoSource.COLOR_BARS, request=request)

    def alternate_color_bars(
        *,
        width: int,
        height: int,
        fps: int,
        duration_s: float,
        seed: int,
    ) -> FFmpegInput:
        del width, height, fps, duration_s, seed
        return FFmpegInput(lavfi="testsrc=size=640x480:rate=24")

    monkeypatch.setitem(
        content_sources.VIDEO_RECIPES,
        VideoSource.COLOR_BARS,
        alternate_color_bars,
    )

    changed = resolve_video_source(source=VideoSource.COLOR_BARS, request=request)

    assert changed.evidence.recipe_digest != original.evidence.recipe_digest


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
        resolve_video_source(source=VideoSource.NOISE, request=_video_request())

    assert exc.value.field == "video.source"


def test_preflight_asset_does_not_build_content_source_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_recipe_digest(**_kwargs):
        raise AssertionError("preflight should not compute replay evidence")

    monkeypatch.setattr(content_sources, "_recipe_digest", fail_recipe_digest)

    preflight_asset(
        parent_kind=ParentKind.MOVIE,
        video=_video(),
        audios=[_audio()],
        subtitles=[],
        container="mkv",
    )


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


def test_collect_content_source_capabilities_reports_registered_source_union() -> None:
    capabilities = collect_content_source_capabilities(ffmpeg_available=True)

    assert len(capabilities.providers) == 1
    provider = capabilities.providers[0]
    assert provider.name == "builtin-lavfi"
    assert provider.sources == (
        "audio:channel_tones",
        "audio:silence",
        "audio:sine",
        "video:color_bars",
        "video:mandelbrot",
        "video:solid_color",
    )
