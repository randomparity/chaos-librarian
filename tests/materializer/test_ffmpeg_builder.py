"""Layer 2 — FFmpeg command builder matrix coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.scenario import (
    AudioChannelLayout,
    AudioSource,
    AudioTrack,
    VideoColorRange,
    VideoColorSpace,
    VideoFieldOrder,
    VideoHdrMode,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.tooling.ffmpeg import (
    BITEXACT_FLAGS,
    build_command,
    build_resolution_switch_concat_command,
    build_resolution_switch_segment_command,
)
from chaos_librarian.materializer.tooling.recipes import (
    FFmpegInput,
    recipe_color_bars,
    recipe_sine,
)


def _video(
    resolution: str = "hd",
    codec: str = "h264",
    field_order: VideoFieldOrder | None = None,
    color_space: VideoColorSpace | None = None,
    color_range: VideoColorRange | None = None,
    hdr_mode: VideoHdrMode | None = None,
) -> VideoTrack:
    return VideoTrack(
        source=VideoSource.COLOR_BARS,
        codec=codec,
        resolution=resolution,
        field_order=field_order,
        color_space=color_space,
        color_range=color_range,
        hdr_mode=hdr_mode,
    )


def _audio(
    channels: AudioChannelLayout = AudioChannelLayout.STEREO,
    *,
    codec: str = "aac",
) -> AudioTrack:
    return AudioTrack(source=AudioSource.SINE, codec=codec, channels=channels, language="eng")


@pytest.mark.parametrize("container", ["mkv", "mp4"])
@pytest.mark.parametrize("resolution", ["sd", "hd", "1080p"])
@pytest.mark.parametrize(
    "channels",
    [AudioChannelLayout.MONO, AudioChannelLayout.STEREO, AudioChannelLayout.FIVE_ONE],
)
def test_matrix_cell_produces_argv_with_bitexact_flags(
    container: str, resolution: str, channels: AudioChannelLayout, tmp_path: Path
) -> None:
    """WHY: 2 containers x 3 resolutions x 3 channel layouts = 18 cells that
    must all produce a stable argv. BITEXACT_FLAGS must appear in every cell
    so cross-run determinism holds."""
    video = _video(resolution=resolution)
    audio = _audio(channels=channels)
    output = tmp_path / f"asset.{container}"
    video_input = recipe_color_bars(width=640, height=480, fps=24, duration_s=2.0, seed=1)
    audio_input = recipe_sine(channels=channels, duration_s=2.0, seed=1)
    argv = build_command(
        video=video,
        video_input=video_input,
        audios=[audio],
        audio_inputs=[audio_input],
        output_path=output,
    )
    assert argv[0] == "ffmpeg"
    for flag in BITEXACT_FLAGS:
        assert flag in argv
    assert str(output) in argv


def test_unsupported_audio_codec_rejected(tmp_path: Path) -> None:
    """WHY: Sprint 5 supports only aac; opus must raise before any subprocess
    starts so the orchestrator can record E_MATERIALIZE_UNSUPPORTED with
    field='audio[0].codec'."""
    video = _video()
    audio = AudioTrack(
        source=AudioSource.SINE,
        codec="opus",
        channels=AudioChannelLayout.STEREO,
        language="eng",
    )
    output = tmp_path / "asset.mkv"
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=video,
            video_input=recipe_color_bars(width=640, height=480, fps=24, duration_s=1.0, seed=1),
            audios=[audio],
            audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
            output_path=output,
        )
    assert exc.value.field == "audio[0].codec"
    assert exc.value.payload["supported"] == ["aac"]


@pytest.mark.parametrize(
    ("codec", "encoder"),
    [("h264", "libx264"), ("hevc", "libx265"), ("h265", "libx265")],
)
def test_video_codec_selects_expected_encoder(codec: str, encoder: str, tmp_path: Path) -> None:
    output = tmp_path / "asset.mkv"
    argv = build_command(
        video=_video(codec=codec),
        video_input=recipe_color_bars(width=1280, height=720, fps=24, duration_s=1.0, seed=1),
        audios=[_audio()],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=output,
    )

    assert argv[argv.index("-c:v") + 1] == encoder


@pytest.mark.parametrize(
    ("codec", "field_order", "param_name", "param_value"),
    [
        ("h264", VideoFieldOrder.TOP_FIELD_FIRST, "-x264-params", "tff=1"),
        ("h264", VideoFieldOrder.BOTTOM_FIELD_FIRST, "-x264-params", "bff=1"),
        ("hevc", VideoFieldOrder.TOP_FIELD_FIRST, "-x265-params", "interlace=tff"),
        ("h265", VideoFieldOrder.BOTTOM_FIELD_FIRST, "-x265-params", "interlace=bff"),
    ],
)
def test_interlaced_video_adds_codec_field_order_params(
    codec: str,
    field_order: VideoFieldOrder,
    param_name: str,
    param_value: str,
    tmp_path: Path,
) -> None:
    output = tmp_path / "asset.mkv"
    argv = build_command(
        video=_video(codec=codec, field_order=field_order),
        video_input=recipe_color_bars(width=1280, height=720, fps=48, duration_s=1.0, seed=1),
        audios=[_audio()],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=output,
    )

    assert argv[argv.index(param_name) + 1] == param_value


@pytest.mark.parametrize(
    ("color_space", "ffmpeg_value"),
    [
        (VideoColorSpace.BT601, "smpte170m"),
        (VideoColorSpace.BT709, "bt709"),
        (VideoColorSpace.BT2020, "bt2020nc"),
    ],
)
def test_video_color_space_adds_ffmpeg_output_arg(
    color_space: VideoColorSpace, ffmpeg_value: str, tmp_path: Path
) -> None:
    output = tmp_path / "asset.mkv"
    argv = build_command(
        video=_video(color_space=color_space),
        video_input=recipe_color_bars(width=1280, height=720, fps=24, duration_s=1.0, seed=1),
        audios=[_audio()],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=output,
    )

    assert argv[argv.index("-colorspace") + 1] == ffmpeg_value


@pytest.mark.parametrize(
    ("color_range", "ffmpeg_value"),
    [
        (VideoColorRange.LIMITED, "tv"),
        (VideoColorRange.FULL, "pc"),
    ],
)
def test_video_color_range_adds_ffmpeg_output_arg(
    color_range: VideoColorRange, ffmpeg_value: str, tmp_path: Path
) -> None:
    output = tmp_path / "asset.mkv"
    argv = build_command(
        video=_video(color_range=color_range),
        video_input=recipe_color_bars(width=1280, height=720, fps=24, duration_s=1.0, seed=1),
        audios=[_audio()],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=output,
    )

    assert argv[argv.index("-color_range") + 1] == ffmpeg_value


@pytest.mark.parametrize(
    ("hdr_mode", "transfer"),
    [
        (VideoHdrMode.HDR10, "smpte2084"),
        (VideoHdrMode.HLG, "arib-std-b67"),
    ],
)
def test_hdr_video_adds_10_bit_filter_and_x265_params(
    hdr_mode: VideoHdrMode, transfer: str, tmp_path: Path
) -> None:
    output = tmp_path / "asset.mkv"
    argv = build_command(
        video=_video(codec="hevc", hdr_mode=hdr_mode),
        video_input=recipe_color_bars(width=1280, height=720, fps=24, duration_s=1.0, seed=1),
        audios=[_audio()],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=output,
    )

    vf = argv[argv.index("-vf") + 1]
    x265_params = argv[argv.index("-x265-params") + 1]
    assert "format=yuv420p10le" in vf
    assert "color_primaries=bt2020" in vf
    assert f"color_trc={transfer}" in vf
    assert "colorspace=bt2020nc" in vf
    assert "range=tv" in vf
    assert "colorprim=bt2020" in x265_params
    assert f"transfer={transfer}" in x265_params
    assert "colormatrix=bt2020nc" in x265_params
    assert "range=limited" in x265_params


def test_hdr10_video_adds_static_metadata_params(tmp_path: Path) -> None:
    argv = build_command(
        video=_video(codec="hevc", hdr_mode=VideoHdrMode.HDR10),
        video_input=recipe_color_bars(width=1280, height=720, fps=24, duration_s=1.0, seed=1),
        audios=[_audio()],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=tmp_path / "asset.mkv",
    )

    x265_params = argv[argv.index("-x265-params") + 1]
    assert "hdr10=1" in x265_params
    assert "master-display=" in x265_params
    assert "max-cll=1000,400" in x265_params


def test_hlg_video_omits_hdr10_static_metadata_params(tmp_path: Path) -> None:
    argv = build_command(
        video=_video(codec="hevc", hdr_mode=VideoHdrMode.HLG),
        video_input=recipe_color_bars(width=1280, height=720, fps=24, duration_s=1.0, seed=1),
        audios=[_audio()],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=tmp_path / "asset.mkv",
    )

    x265_params = argv[argv.index("-x265-params") + 1]
    assert "master-display=" not in x265_params
    assert "max-cll=" not in x265_params


def test_hdr_video_owns_color_signal_args(tmp_path: Path) -> None:
    argv = build_command(
        video=_video(
            codec="hevc",
            color_space=VideoColorSpace.BT2020,
            color_range=VideoColorRange.LIMITED,
            hdr_mode=VideoHdrMode.HDR10,
        ),
        video_input=recipe_color_bars(width=1280, height=720, fps=24, duration_s=1.0, seed=1),
        audios=[_audio()],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=tmp_path / "asset.mkv",
    )

    assert "-colorspace" not in argv
    assert "-color_range" not in argv


def test_hdr_video_rejects_non_hevc_codec(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=_video(codec="h264", hdr_mode=VideoHdrMode.HDR10),
            video_input=recipe_color_bars(width=1280, height=720, fps=24, duration_s=1.0, seed=1),
            audios=[_audio()],
            audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
            output_path=tmp_path / "asset.mkv",
        )

    assert exc.value.field == "video.hdr_mode"


def test_unsupported_container_rejected(tmp_path: Path) -> None:
    video = _video()
    output = tmp_path / "asset.webm"
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=video,
            video_input=recipe_color_bars(width=640, height=480, fps=24, duration_s=1.0, seed=1),
            audios=[_audio()],
            audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
            output_path=output,
        )
    assert exc.value.field == "container"


def test_unsupported_resolution_rejected(tmp_path: Path) -> None:
    video = VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution="4k")
    output = tmp_path / "asset.mkv"
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=video,
            video_input=recipe_color_bars(width=3840, height=2160, fps=24, duration_s=1.0, seed=1),
            audios=[_audio()],
            audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
            output_path=output,
        )
    assert exc.value.field == "video.resolution"


def test_file_backed_video_input_uses_file_path(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake media")
    output = tmp_path / "asset.mkv"

    argv = build_command(
        video=_video(),
        video_input=FFmpegInput(file_path=source),
        audios=[_audio()],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=output,
    )

    source_index = argv.index(str(source))
    assert "-f" not in argv[:source_index]
    assert str(source) in argv
    assert argv[argv.index("-map") + 1] == "0:v:0"
    assert argv[argv.index("-map", argv.index("-map") + 1) + 1] == "1:a:0"
    last_input_index = argv.index("-i", argv.index("-i") + 1)
    first_map_index = argv.index("-map")
    video_codec_index = argv.index("-c:v")
    assert last_input_index < first_map_index < video_codec_index


def test_build_command_maps_multiple_audio_inputs_explicitly(tmp_path: Path) -> None:
    output = tmp_path / "asset.mkv"
    first_audio = _audio(channels=AudioChannelLayout.MONO)
    second_audio = _audio(channels=AudioChannelLayout.STEREO)

    argv = build_command(
        video=_video(),
        video_input=recipe_color_bars(width=640, height=480, fps=24, duration_s=1.0, seed=1),
        audios=[first_audio, second_audio],
        audio_inputs=[
            recipe_sine(channels="mono", duration_s=1.0, seed=1),
            recipe_sine(channels="stereo", duration_s=1.0, seed=2),
        ],
        output_path=output,
    )

    map_values = [argv[index + 1] for index, arg in enumerate(argv) if arg == "-map"]
    assert map_values == ["0:v:0", "1:a:0", "2:a:0"]
    input_indexes = [index for index, arg in enumerate(argv) if arg == "-i"]
    first_map_index = argv.index("-map")
    video_codec_index = argv.index("-c:v")
    assert max(input_indexes) < first_map_index < video_codec_index


@pytest.mark.parametrize(
    ("container", "codec", "encoder"),
    [("flac", "flac", "flac"), ("mp3", "mp3", "libmp3lame"), ("m4a", "aac", "aac")],
)
def test_audio_only_command_maps_audio_without_video_codec(
    container: str, codec: str, encoder: str, tmp_path: Path
) -> None:
    output = tmp_path / f"asset.{container}"

    argv = build_command(
        video=None,
        video_input=None,
        audios=[_audio(codec=codec)],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=output,
    )

    assert "-c:v" not in argv
    map_values = [argv[index + 1] for index, arg in enumerate(argv) if arg == "-map"]
    assert map_values == ["0:a:0"]
    assert argv[argv.index("-c:a") + 1] == encoder
    assert argv[argv.index("-ac") + 1] == "2"
    for flag in BITEXACT_FLAGS:
        assert flag in argv
    assert argv[-1] == str(output)
    input_indexes = [index for index, arg in enumerate(argv) if arg == "-i"]
    first_map_index = argv.index("-map")
    audio_codec_index = argv.index("-c:a")
    channel_count_index = argv.index("-ac")
    assert max(input_indexes) < first_map_index < audio_codec_index < channel_count_index
    assert channel_count_index < len(argv) - 1


@pytest.mark.parametrize(
    ("channels", "expected_count"),
    [
        (AudioChannelLayout.MONO, "1"),
        (AudioChannelLayout.STEREO, "2"),
        (AudioChannelLayout.FIVE_ONE, "6"),
    ],
)
def test_audio_only_command_enforces_declared_channel_count(
    channels: AudioChannelLayout,
    expected_count: str,
    tmp_path: Path,
) -> None:
    argv = build_command(
        video=None,
        video_input=None,
        audios=[_audio(channels=channels, codec="flac")],
        audio_inputs=[recipe_sine(channels=channels, duration_s=1.0, seed=1)],
        output_path=tmp_path / "asset.flac",
    )

    assert argv[argv.index("-ac") + 1] == expected_count


def test_audio_only_command_rejects_wrong_codec_for_container(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=None,
            video_input=None,
            audios=[_audio(codec="aac")],
            audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
            output_path=tmp_path / "asset.flac",
        )

    assert exc.value.field == "audio[0].codec"


@pytest.mark.parametrize(
    ("audios", "audio_inputs"),
    [
        ([], []),
        (
            [_audio(codec="flac"), _audio(codec="flac")],
            [
                recipe_sine(channels="stereo", duration_s=1.0, seed=1),
                recipe_sine(channels="stereo", duration_s=1.0, seed=2),
            ],
        ),
        (
            [_audio(codec="flac")],
            [
                recipe_sine(channels="stereo", duration_s=1.0, seed=1),
                recipe_sine(channels="stereo", duration_s=1.0, seed=2),
            ],
        ),
    ],
)
def test_audio_only_command_rejects_audio_count_mismatch(
    audios: list[AudioTrack],
    audio_inputs: list[FFmpegInput],
    tmp_path: Path,
) -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=None,
            video_input=None,
            audios=audios,
            audio_inputs=audio_inputs,
            output_path=tmp_path / "asset.flac",
        )

    assert exc.value.field == "audio"


def test_audio_only_command_rejects_video_input(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=None,
            video_input=recipe_color_bars(width=640, height=480, fps=24, duration_s=1.0, seed=1),
            audios=[_audio(codec="flac")],
            audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
            output_path=tmp_path / "asset.flac",
        )

    assert exc.value.field == "video_input"


def test_video_command_rejects_missing_video_input(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=_video(),
            video_input=None,
            audios=[_audio()],
            audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
            output_path=tmp_path / "asset.mkv",
        )

    assert exc.value.field == "video_input"


def test_build_command_does_not_own_source_support_after_resolution(tmp_path: Path) -> None:
    """WHY: source support belongs to content providers after recipe resolution;
    build_command only receives the resolved FFmpegInput."""
    video = VideoTrack(source=VideoSource.NOISE, codec="h264", resolution="hd")
    output = tmp_path / "asset.mkv"
    argv = build_command(
        video=video,
        video_input=recipe_color_bars(width=1280, height=720, fps=24, duration_s=1.0, seed=1),
        audios=[_audio()],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=output,
    )
    assert str(output) in argv


def test_ffmpeg_input_rejects_missing_input() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        FFmpegInput()


def test_ffmpeg_input_rejects_two_inputs(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="exactly one"):
        FFmpegInput(lavfi="color=s=1x1", file_path=tmp_path / "source.mp4")


def test_resolution_switch_segment_command_uses_h264_mpegts(tmp_path: Path) -> None:
    segment = build_resolution_switch_segment_command(
        video_input=FFmpegInput(
            lavfi="smptebars=size=640x480:rate=24",
            extra_flags=("-t", "0.5"),
        ),
        output_path=tmp_path / "segment.ts",
    )

    assert segment[:3] == ["ffmpeg", "-hide_banner", "-y"]
    assert "-f" in segment
    assert "mpegts" in segment
    assert segment[segment.index("-c:v") + 1] == "libx264"
    assert segment[segment.index("-map") + 1] == "0:v:0"
    for flag in BITEXACT_FLAGS:
        assert flag in segment


def test_resolution_switch_concat_command_stream_copies_segments(tmp_path: Path) -> None:
    concat = build_resolution_switch_concat_command(
        concat_list_path=tmp_path / "concat.txt",
        output_path=tmp_path / "asset.ts",
    )

    assert concat[:7] == ["ffmpeg", "-hide_banner", "-y", "-f", "concat", "-safe", "0"]
    assert concat[concat.index("-c") + 1] == "copy"
    for flag in BITEXACT_FLAGS:
        assert flag in concat
