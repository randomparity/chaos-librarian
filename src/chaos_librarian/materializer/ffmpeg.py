"""FFmpeg argv builder and subprocess wrapper.

``build_command`` is pure — given a video track, an audio list, and the
output path, returns the argv tuple. Unsupported combinations raise
``UnsupportedMaterializationError`` with the exact scenario field name.

``run_ffmpeg`` is the subprocess wrapper. Captures stderr_tail and times
execution. Never lets ffmpeg inherit stdin.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.scenario import (
    AudioSource,
    AudioTrack,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.recipes import FFmpegInput

BITEXACT_FLAGS: Final[tuple[str, ...]] = (
    "-fflags",
    "+bitexact",
    "-flags",
    "+bitexact",
    "-map_metadata",
    "-1",
    "-metadata",
    "creation_time=1970-01-01T00:00:00Z",
)

_SUPPORTED_CONTAINERS: Final[frozenset[str]] = frozenset({"mkv", "mp4"})
_SUPPORTED_RESOLUTIONS: Final[frozenset[str]] = frozenset({"sd", "hd", "1080p"})
_SUPPORTED_VIDEO_CODECS: Final[frozenset[str]] = frozenset({"h264"})
_SUPPORTED_AUDIO_CODECS: Final[frozenset[str]] = frozenset({"aac"})
_SUPPORTED_VIDEO_SOURCES: Final[frozenset[VideoSource]] = frozenset(
    {VideoSource.MANDELBROT, VideoSource.COLOR_BARS, VideoSource.SOLID_COLOR}
)
_SUPPORTED_AUDIO_SOURCES: Final[frozenset[AudioSource]] = frozenset(
    {AudioSource.SINE, AudioSource.SILENCE, AudioSource.CHANNEL_TONES}
)

_CONTAINER_FROM_EXTENSION: Final[dict[str, str]] = {".mkv": "mkv", ".mp4": "mp4"}


def _require(value: object, supported: Iterable[object], field: str) -> None:
    """Raise ``UnsupportedMaterializationError`` if ``value`` is not in ``supported``.

    The error's ``payload['supported']`` is the sorted ``str()`` of each
    supported value so the JSON-rendered payload is stable across runs.
    """
    supported_tuple = tuple(supported)
    if value not in supported_tuple:
        raise UnsupportedMaterializationError(
            f"{field}={value!r} is not supported in Sprint 5",
            field=field,
            payload={"supported": sorted(str(v) for v in supported_tuple)},
        )


def _resolve_container(output_path: Path) -> str:
    """Map ``output_path.suffix`` to a container name, raising on unknown ext."""
    container = _CONTAINER_FROM_EXTENSION.get(output_path.suffix)
    if container is None:
        raise UnsupportedMaterializationError(
            f"unknown container extension: {output_path.suffix!r}",
            field="container",
            payload={"supported": sorted(_SUPPORTED_CONTAINERS)},
        )
    _require(container, _SUPPORTED_CONTAINERS, "container")
    return container


def _validate_video(video: VideoTrack) -> None:
    """Reject video tracks outside the Sprint 5 matrix."""
    _require(video.source, _SUPPORTED_VIDEO_SOURCES, "video.source")
    _require(video.codec, _SUPPORTED_VIDEO_CODECS, "video.codec")
    _require(video.resolution, _SUPPORTED_RESOLUTIONS, "video.resolution")


def _validate_audios(audios: list[AudioTrack]) -> None:
    """Reject any audio track outside the Sprint 5 matrix."""
    for index, audio in enumerate(audios):
        _require(audio.source, _SUPPORTED_AUDIO_SOURCES, f"audio[{index}].source")
        _require(audio.codec, _SUPPORTED_AUDIO_CODECS, f"audio[{index}].codec")


def _video_input_args(video_input: FFmpegInput) -> list[str]:
    """Argv slice for the video input — lavfi is mandatory in Sprint 5."""
    if video_input.lavfi is None:
        raise UnsupportedMaterializationError(
            "video FFmpegInput must carry a lavfi expression",
            field="video.source",
            payload={},
        )
    return ["-f", "lavfi", "-i", video_input.lavfi, *video_input.extra_flags]


def _audio_input_args(audio_inputs: list[FFmpegInput]) -> list[str]:
    """Argv slice covering all audio inputs — lavfi mandatory."""
    args: list[str] = []
    for audio_input in audio_inputs:
        if audio_input.lavfi is None:
            raise UnsupportedMaterializationError(
                "audio FFmpegInput must carry a lavfi expression",
                field="audio.source",
                payload={},
            )
        args.extend(["-f", "lavfi", "-i", audio_input.lavfi, *audio_input.extra_flags])
    return args


def build_command(
    *,
    video: VideoTrack,
    video_input: FFmpegInput,
    audios: list[AudioTrack],
    audio_inputs: list[FFmpegInput],
    output_path: Path,
) -> list[str]:
    """Build the ffmpeg argv for one asset.

    The caller has already turned the scenario's source enums into
    FFmpegInput recipes; this function focuses on muxing + codec wiring.

    Raises:
        UnsupportedMaterializationError: any element of the (container,
            video source/codec/resolution, audio source/codec) tuple falls
            outside the Sprint 5 matrix, or an FFmpegInput is missing its
            lavfi expression.
    """
    _resolve_container(output_path)
    _validate_video(video)
    _validate_audios(audios)
    argv: list[str] = ["ffmpeg", "-hide_banner", "-y", *BITEXACT_FLAGS]
    argv.extend(_video_input_args(video_input))
    argv.extend(_audio_input_args(audio_inputs))
    argv.extend(["-c:v", "libx264", "-preset", "medium"])
    argv.extend(["-c:a", "aac"])
    argv.append("-shortest")
    argv.append(str(output_path))
    return argv


def run_ffmpeg(
    argv: list[str],
    *,
    ffmpeg_version: str,
    timeout_s: float = 60.0,
) -> ToolInvocation:
    """Invoke ffmpeg. Returns a ToolInvocation regardless of exit code.

    Stderr tail (last 2 KB, UTF-8 lossy) is recorded on the invocation's
    command list as the final element prefixed with ``__stderr_tail__``
    so callers can extract it without a second subprocess round-trip.
    """
    start = time.monotonic_ns()
    completed = subprocess.run(
        argv,
        capture_output=True,
        timeout=timeout_s,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    duration_ns = time.monotonic_ns() - start
    stderr_bytes = completed.stderr or b""
    stderr_tail = stderr_bytes[-2048:].decode("utf-8", errors="replace")
    command = [*argv, f"__stderr_tail__{stderr_tail}"]
    return ToolInvocation(
        tool="ffmpeg",
        version=ffmpeg_version,
        command=command,
        exit_code=completed.returncode,
        duration_ns=duration_ns,
    )
