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
    recipe_color_bars,
    recipe_sine,
)


def _video(resolution: str = "hd") -> VideoTrack:
    return VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution=resolution)


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


def test_unsupported_video_source_rejected(tmp_path: Path) -> None:
    """WHY: noise is a valid scenario source (slow-copy.yaml uses it) but
    Sprint 5's materializer rejects it; the check belongs in the builder
    because that's where source-to-recipe dispatch lives."""
    video = VideoTrack(source=VideoSource.NOISE, codec="h264", resolution="hd")
    output = tmp_path / "asset.mkv"
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=video,
            video_input=recipe_color_bars(width=1280, height=720, fps=24, duration_s=1.0, seed=1),
            audios=[_audio()],
            audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
            output_path=output,
        )
    assert exc.value.field == "video.source"
