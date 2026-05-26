"""Audio-only materializer coverage for track assets."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    AudioChannelLayout,
    AudioSource,
    AudioTrack,
    SubtitleMode,
    SubtitleTrack,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.preflight import preflight_asset
from chaos_librarian.materializer.tooling.ffmpeg import BITEXACT_FLAGS, build_command
from chaos_librarian.materializer.tooling.recipes import recipe_sine


def _audio(codec: str) -> AudioTrack:
    return AudioTrack(
        source=AudioSource.SINE,
        codec=codec,
        channels=AudioChannelLayout.STEREO,
        language="eng",
    )


def _video() -> VideoTrack:
    return VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution="hd")


@pytest.mark.parametrize(
    ("container", "codec"),
    [("flac", "flac"), ("mp3", "mp3"), ("m4a", "aac")],
)
def test_track_audio_only_cells_pass_preflight(container: str, codec: str) -> None:
    preflight_asset(
        parent_kind=ParentKind.TRACK,
        video=None,
        audios=[_audio(codec)],
        subtitles=[],
        container=container,
    )


@pytest.mark.parametrize(
    ("container", "codec", "encoder"),
    [("flac", "flac", "flac"), ("mp3", "mp3", "libmp3lame"), ("m4a", "aac", "aac")],
)
def test_track_audio_only_cells_build_ffmpeg_command(
    container: str,
    codec: str,
    encoder: str,
    tmp_path: Path,
) -> None:
    output_path = tmp_path / f"asset.{container}"

    argv = build_command(
        video=None,
        video_input=None,
        audios=[_audio(codec)],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=output_path,
    )

    assert "-c:v" not in argv
    map_values = [argv[index + 1] for index, arg in enumerate(argv) if arg == "-map"]
    assert map_values == ["0:a:0"]
    assert argv[argv.index("-c:a") + 1] == encoder
    for flag in BITEXACT_FLAGS:
        assert flag in argv
    assert argv[-1] == str(output_path)


def test_track_with_video_rejected_by_preflight() -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc_info:
        preflight_asset(
            parent_kind=ParentKind.TRACK,
            video=_video(),
            audios=[_audio("flac")],
            subtitles=[],
            container="flac",
        )

    assert exc_info.value.field == "video"


def test_track_with_subtitle_rejected_by_preflight() -> None:
    subtitle = SubtitleTrack(codec="srt", language="eng", mode=SubtitleMode.SIDECAR)

    with pytest.raises(UnsupportedMaterializationError) as exc_info:
        preflight_asset(
            parent_kind=ParentKind.TRACK,
            video=None,
            audios=[_audio("flac")],
            subtitles=[subtitle],
            container="flac",
        )

    assert exc_info.value.field == "subtitles"


def test_track_without_audio_rejected_by_preflight() -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc_info:
        preflight_asset(
            parent_kind=ParentKind.TRACK,
            video=None,
            audios=[],
            subtitles=[],
            container="flac",
        )

    assert exc_info.value.field == "audio"


def test_track_with_multiple_audio_streams_rejected_by_preflight() -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc_info:
        preflight_asset(
            parent_kind=ParentKind.TRACK,
            video=None,
            audios=[_audio("flac"), _audio("flac")],
            subtitles=[],
            container="flac",
        )

    assert exc_info.value.field == "audio"


@pytest.mark.parametrize(
    ("container", "codec", "field"),
    [("mkv", "flac", "container"), ("flac", "aac", "audio[0].codec")],
)
def test_track_unsupported_audio_only_cell_rejected(container: str, codec: str, field: str) -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc_info:
        preflight_asset(
            parent_kind=ParentKind.TRACK,
            video=None,
            audios=[_audio(codec)],
            subtitles=[],
            container=container,
        )

    assert exc_info.value.field == field


@pytest.mark.parametrize("parent_kind", [ParentKind.MOVIE, ParentKind.EPISODE])
def test_video_parent_without_video_rejected(parent_kind: ParentKind) -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc_info:
        preflight_asset(
            parent_kind=parent_kind,
            video=None,
            audios=[_audio("aac")],
            subtitles=[],
            container="mkv",
        )

    assert exc_info.value.field == "video"
