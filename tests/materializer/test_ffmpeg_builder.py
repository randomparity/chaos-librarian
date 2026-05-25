"""Layer 2 — FFmpeg command builder matrix coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.scenario import (
    AudioChannelLayout,
    AudioSource,
    AudioTrack,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.tooling.ffmpeg import (
    BITEXACT_FLAGS,
    build_command,
)
from chaos_librarian.materializer.tooling.recipes import (
    FFmpegInput,
    recipe_color_bars,
    recipe_sine,
)


def _video(resolution: str = "hd", codec: str = "h264") -> VideoTrack:
    return VideoTrack(source=VideoSource.COLOR_BARS, codec=codec, resolution=resolution)


def _audio(channels: AudioChannelLayout = AudioChannelLayout.STEREO) -> AudioTrack:
    return AudioTrack(source=AudioSource.SINE, codec="aac", channels=channels, language="eng")


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
