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
    AudioNoiseColor,
    AudioSampleFormat,
    AudioSource,
    AudioTrack,
    VideoColorRange,
    VideoColorSpace,
    VideoFieldOrder,
    VideoHdrMode,
    VideoResolutionSequence,
    VideoSource,
    VideoTrack,
    VideoVfrCadence,
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


def _video_request(
    *,
    vfr_cadence: VideoVfrCadence | None = None,
    field_order: VideoFieldOrder | None = None,
    color_space: VideoColorSpace | None = None,
    color_range: VideoColorRange | None = None,
    hdr_mode: VideoHdrMode | None = None,
    resolution_sequence: VideoResolutionSequence | None = None,
) -> VideoSourceRequest:
    return VideoSourceRequest(
        asset_id="asset_main",
        track_index=None,
        seed=42,
        duration_s=2.0,
        width=640,
        height=480,
        fps=24,
        vfr_cadence=vfr_cadence,
        field_order=field_order,
        color_space=color_space,
        color_range=color_range,
        hdr_mode=hdr_mode,
        resolution_sequence=resolution_sequence,
    )


def _audio_request(
    *,
    noise_color: AudioNoiseColor | None = None,
    sample_rate: int = 48000,
    sample_format: AudioSampleFormat | None = None,
) -> AudioSourceRequest:
    return AudioSourceRequest(
        asset_id="asset_main",
        track_index=0,
        seed=42,
        duration_s=2.0,
        channels="stereo",
        noise_color=noise_color,
        sample_rate=sample_rate,
        sample_format=sample_format,
    )


def _video(
    field_order: VideoFieldOrder | None = None,
    color_space: VideoColorSpace | None = None,
    color_range: VideoColorRange | None = None,
    hdr_mode: VideoHdrMode | None = None,
    resolution_sequence: VideoResolutionSequence | None = None,
) -> VideoTrack:
    return VideoTrack(
        source=VideoSource.COLOR_BARS,
        codec="h264",
        resolution="sd",
        field_order=field_order,
        color_space=color_space,
        color_range=color_range,
        hdr_mode=hdr_mode,
        resolution_sequence=resolution_sequence,
    )


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


def test_resolve_audio_source_records_recipe_parameters() -> None:
    resolution = resolve_audio_source(
        source=AudioSource.NOISE,
        request=_audio_request(
            noise_color=AudioNoiseColor.PINK,
            sample_rate=88200,
            sample_format=AudioSampleFormat.S24,
        ),
    )

    assert resolution.evidence.track_kind is ContentTrackKind.AUDIO
    assert resolution.evidence.source == "noise"
    assert resolution.evidence.noise_color is AudioNoiseColor.PINK
    assert resolution.evidence.sample_rate == 88200
    assert resolution.evidence.sample_format is AudioSampleFormat.S24


def test_audio_recipe_parameters_change_digest() -> None:
    default = resolve_audio_source(source=AudioSource.SINE, request=_audio_request())
    rate_changed = resolve_audio_source(
        source=AudioSource.SINE,
        request=_audio_request(sample_rate=96000),
    )
    format_changed = resolve_audio_source(
        source=AudioSource.SINE,
        request=_audio_request(sample_format=AudioSampleFormat.S16),
    )

    assert rate_changed.evidence.recipe_digest != default.evidence.recipe_digest
    assert format_changed.evidence.recipe_digest != default.evidence.recipe_digest


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


def test_vfr_video_source_uses_select_filter_and_records_cadence() -> None:
    request = _video_request(vfr_cadence=VideoVfrCadence.TWENTY_FOUR_TO_THIRTY)

    resolution = resolve_video_source(source=VideoSource.COLOR_BARS, request=request)

    assert resolution.ffmpeg_input.lavfi is not None
    assert "rate=120" in resolution.ffmpeg_input.lavfi
    assert "select=" in resolution.ffmpeg_input.lavfi
    assert "mod(n,5)" in resolution.ffmpeg_input.lavfi
    assert "mod(n,4)" in resolution.ffmpeg_input.lavfi


def test_vfr_cadence_changes_recipe_digest() -> None:
    cfr = resolve_video_source(source=VideoSource.COLOR_BARS, request=_video_request())
    vfr = resolve_video_source(
        source=VideoSource.COLOR_BARS,
        request=_video_request(vfr_cadence=VideoVfrCadence.THIRTY_TO_SIXTY),
    )

    assert vfr.evidence.recipe_digest != cfr.evidence.recipe_digest


@pytest.mark.parametrize(
    ("field_order", "expected_filter"),
    [
        (
            VideoFieldOrder.TOP_FIELD_FIRST,
            "tinterlace=mode=interleave_top,setfield=tff",
        ),
        (
            VideoFieldOrder.BOTTOM_FIELD_FIRST,
            "tinterlace=mode=interleave_bottom,setfield=bff",
        ),
    ],
)
def test_interlaced_video_source_uses_double_rate_field_filter(
    field_order: VideoFieldOrder, expected_filter: str
) -> None:
    request = _video_request(field_order=field_order)

    resolution = resolve_video_source(source=VideoSource.COLOR_BARS, request=request)

    assert resolution.ffmpeg_input.lavfi is not None
    assert "rate=48" in resolution.ffmpeg_input.lavfi
    assert expected_filter in resolution.ffmpeg_input.lavfi


def test_field_order_changes_recipe_digest() -> None:
    progressive = resolve_video_source(source=VideoSource.COLOR_BARS, request=_video_request())
    interlaced = resolve_video_source(
        source=VideoSource.COLOR_BARS,
        request=_video_request(field_order=VideoFieldOrder.TOP_FIELD_FIRST),
    )

    assert interlaced.evidence.recipe_digest != progressive.evidence.recipe_digest


def test_field_order_rejects_vfr_cadence() -> None:
    request = _video_request(
        vfr_cadence=VideoVfrCadence.TWENTY_FOUR_TO_THIRTY,
        field_order=VideoFieldOrder.TOP_FIELD_FIRST,
    )

    with pytest.raises(UnsupportedMaterializationError) as exc:
        resolve_video_source(source=VideoSource.COLOR_BARS, request=request)

    assert exc.value.field == "video.field_order"


def test_color_space_changes_recipe_digest() -> None:
    default = resolve_video_source(source=VideoSource.COLOR_BARS, request=_video_request())
    signaled = resolve_video_source(
        source=VideoSource.COLOR_BARS,
        request=_video_request(color_space=VideoColorSpace.BT709),
    )

    assert signaled.evidence.recipe_digest != default.evidence.recipe_digest
    assert signaled.evidence.color_space is VideoColorSpace.BT709
    assert default.evidence.color_space is None


def test_color_range_changes_recipe_digest() -> None:
    default = resolve_video_source(source=VideoSource.COLOR_BARS, request=_video_request())
    signaled = resolve_video_source(
        source=VideoSource.COLOR_BARS,
        request=_video_request(color_range=VideoColorRange.FULL),
    )

    assert signaled.evidence.recipe_digest != default.evidence.recipe_digest
    assert signaled.evidence.color_range is VideoColorRange.FULL
    assert default.evidence.color_range is None


def test_hdr_mode_changes_recipe_digest() -> None:
    default = resolve_video_source(source=VideoSource.COLOR_BARS, request=_video_request())
    hdr10 = resolve_video_source(
        source=VideoSource.COLOR_BARS,
        request=_video_request(hdr_mode=VideoHdrMode.HDR10),
    )
    hlg = resolve_video_source(
        source=VideoSource.COLOR_BARS,
        request=_video_request(hdr_mode=VideoHdrMode.HLG),
    )

    assert hdr10.evidence.recipe_digest != default.evidence.recipe_digest
    assert hlg.evidence.recipe_digest != default.evidence.recipe_digest
    assert hdr10.evidence.recipe_digest != hlg.evidence.recipe_digest


def test_resolution_sequence_changes_recipe_digest_and_evidence() -> None:
    default = resolve_video_source(source=VideoSource.COLOR_BARS, request=_video_request())
    switched = resolve_video_source(
        source=VideoSource.COLOR_BARS,
        request=_video_request(resolution_sequence=VideoResolutionSequence.SD_TO_HD),
    )

    assert switched.evidence.recipe_digest != default.evidence.recipe_digest
    assert switched.evidence.resolution_sequence is VideoResolutionSequence.SD_TO_HD
    assert default.evidence.resolution_sequence is None


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


def test_preflight_asset_accepts_resolution_switch_video() -> None:
    preflight_asset(
        parent_kind=ParentKind.MOVIE,
        video=_video(resolution_sequence=VideoResolutionSequence.SD_TO_HD),
        audios=[],
        subtitles=[],
        container="ts",
    )


def test_preflight_resolution_switch_rejects_vfr_cadence() -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc:
        preflight_asset(
            parent_kind=ParentKind.MOVIE,
            video=VideoTrack(
                source=VideoSource.COLOR_BARS,
                codec="h264",
                resolution="sd",
                vfr_cadence=VideoVfrCadence.TWENTY_FOUR_TO_THIRTY,
                resolution_sequence=VideoResolutionSequence.SD_TO_HD,
            ),
            audios=[],
            subtitles=[],
            container="ts",
        )

    assert exc.value.field == "video.vfr_cadence"


def test_collect_content_source_capabilities_reports_builtin_provider() -> None:
    capabilities = collect_content_source_capabilities(
        ffmpeg_available=True,
        hdr_available=True,
        resolution_sequence_available=True,
    )

    assert [provider.name for provider in capabilities.providers] == ["builtin-lavfi"]
    provider = capabilities.providers[0]
    assert provider.available is True
    assert "video:color_bars" in provider.sources
    assert "video:interlaced:top_field_first" in provider.sources
    assert "video:interlaced:bottom_field_first" in provider.sources
    assert "video:color_space:bt709" in provider.sources
    assert "video:color_range:full" in provider.sources
    assert "video:hdr:hdr10" in provider.sources
    assert "video:hdr:hlg" in provider.sources
    assert "video:resolution_sequence:sd_to_hd" in provider.sources


def test_collect_content_source_capabilities_marks_builtin_unavailable_without_ffmpeg() -> None:
    capabilities = collect_content_source_capabilities(ffmpeg_available=False)

    provider = capabilities.providers[0]
    assert provider.name == "builtin-lavfi"
    assert provider.available is False
    assert provider.reason == "required tool unavailable: ffmpeg"


def test_collect_content_source_capabilities_omits_hdr_when_unavailable() -> None:
    capabilities = collect_content_source_capabilities(ffmpeg_available=True, hdr_available=False)

    provider = capabilities.providers[0]
    assert "video:hdr:hdr10" not in provider.sources
    assert "video:hdr:hlg" not in provider.sources


def test_collect_content_source_capabilities_omits_resolution_sequence_when_unavailable() -> None:
    capabilities = collect_content_source_capabilities(
        ffmpeg_available=True,
        resolution_sequence_available=False,
    )

    provider = capabilities.providers[0]
    assert "video:resolution_sequence:sd_to_hd" not in provider.sources


def test_collect_content_source_capabilities_omits_audio_recipe_markers_when_unavailable() -> None:
    capabilities = collect_content_source_capabilities(
        ffmpeg_available=True,
        audio_recipes_available=False,
    )

    provider = capabilities.providers[0]
    assert "audio:noise" not in provider.sources
    assert "audio:noise:pink" not in provider.sources
    assert "audio:sample_rate:96000" not in provider.sources
    assert "audio:sample_format:flt" not in provider.sources


def test_collect_content_source_capabilities_reports_registered_source_union() -> None:
    capabilities = collect_content_source_capabilities(
        ffmpeg_available=True,
        hdr_available=True,
        resolution_sequence_available=True,
        audio_recipes_available=True,
    )

    assert len(capabilities.providers) == 1
    provider = capabilities.providers[0]
    assert provider.name == "builtin-lavfi"
    assert provider.sources == (
        "audio:channel_tones",
        "audio:noise",
        "audio:noise:brown",
        "audio:noise:pink",
        "audio:noise:white",
        "audio:sample_format:flt",
        "audio:sample_format:s16",
        "audio:sample_format:s24",
        "audio:sample_rate:22050",
        "audio:sample_rate:44100",
        "audio:sample_rate:48000",
        "audio:sample_rate:8000",
        "audio:sample_rate:88200",
        "audio:sample_rate:96000",
        "audio:silence",
        "audio:sine",
        "video:color_bars",
        "video:color_range:full",
        "video:color_range:limited",
        "video:color_space:bt2020",
        "video:color_space:bt601",
        "video:color_space:bt709",
        "video:hdr:hdr10",
        "video:hdr:hlg",
        "video:interlaced:bottom_field_first",
        "video:interlaced:top_field_first",
        "video:mandelbrot",
        "video:resolution_sequence:sd_to_hd",
        "video:solid_color",
        "video:vfr:24_30_60",
        "video:vfr:24_to_30",
        "video:vfr:30_to_60",
    )
