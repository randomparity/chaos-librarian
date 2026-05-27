"""FFmpeg argv builder and subprocess wrapper.

``build_command`` is pure — given a video-backed or audio-only asset shape
and the output path, returns the argv tuple. Unsupported combinations raise
``UnsupportedMaterializationError`` with the exact scenario field name.

``run_ffmpeg`` is the subprocess wrapper. Returns the ``ToolInvocation``
plus the last 2 KB of stderr (UTF-8 lossy). Never lets ffmpeg inherit
stdin.
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Final

from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.scenario import (
    AUDIO_CHANNEL_COUNTS_BY_NAME,
    AudioTrack,
    VideoColorRange,
    VideoColorSpace,
    VideoFieldOrder,
    VideoHdrMode,
    VideoTrack,
)
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.tooling.recipes import FFmpegInput
from chaos_librarian.media_matrix import (
    AUDIO_ENCODER_BY_CODEC,
    HEVC_VIDEO_CODECS,
    SUPPORTED_AUDIO_CODECS,
    SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER,
    SUPPORTED_CONTAINERS,
    SUPPORTED_RESOLUTIONS,
    SUPPORTED_VIDEO_CODECS,
    SUPPORTED_VIDEO_CONTAINERS,
    VIDEO_ENCODER_BY_CODEC,
)

_BITEXACT_OUTPUT_FLAGS: Final[tuple[str, ...]] = (
    # ``-fflags +bitexact`` MUST appear on the output side: that's the only
    # position where it propagates to the matroska muxer, which otherwise
    # writes a random ``SegmentUID`` and ``WritingApp`` string per file and
    # breaks same-toolchain bit-exactness on ``.mkv`` outputs.
    "-fflags",
    "+bitexact",
    "-flags",
    "+bitexact",
    "-map_metadata",
    "-1",
    "-metadata",
    "creation_time=1970-01-01T00:00:00Z",
)
BITEXACT_FLAGS: Final[tuple[str, ...]] = _BITEXACT_OUTPUT_FLAGS

_CONTAINER_FROM_EXTENSION: Final[dict[str, str]] = {
    ".flac": "flac",
    ".m4a": "m4a",
    ".mkv": "mkv",
    ".mp3": "mp3",
    ".mp4": "mp4",
}
_X264_FIELD_ORDER_PARAMS: Final[dict[VideoFieldOrder, str]] = {
    VideoFieldOrder.TOP_FIELD_FIRST: "tff=1",
    VideoFieldOrder.BOTTOM_FIELD_FIRST: "bff=1",
}
_X265_FIELD_ORDER_PARAMS: Final[dict[VideoFieldOrder, str]] = {
    VideoFieldOrder.TOP_FIELD_FIRST: "interlace=tff",
    VideoFieldOrder.BOTTOM_FIELD_FIRST: "interlace=bff",
}
_COLOR_SPACE_OUTPUT_ARGS: Final[dict[VideoColorSpace, str]] = {
    VideoColorSpace.BT601: "smpte170m",
    VideoColorSpace.BT709: "bt709",
    VideoColorSpace.BT2020: "bt2020nc",
}
_COLOR_RANGE_OUTPUT_ARGS: Final[dict[VideoColorRange, str]] = {
    VideoColorRange.LIMITED: "tv",
    VideoColorRange.FULL: "pc",
}
_HDR_FILTERS: Final[dict[VideoHdrMode, str]] = {
    VideoHdrMode.HDR10: (
        "setparams=color_primaries=bt2020:color_trc=smpte2084:"
        "colorspace=bt2020nc:range=tv,format=yuv420p10le"
    ),
    VideoHdrMode.HLG: (
        "setparams=color_primaries=bt2020:color_trc=arib-std-b67:"
        "colorspace=bt2020nc:range=tv,format=yuv420p10le"
    ),
}
_HDR10_MASTER_DISPLAY: Final = (
    "G(13250,34500)B(7500,3000)R(34000,16000)WP(15635,16450)L(10000000,1)"
)
_HDR_X265_PARAMS: Final[dict[VideoHdrMode, tuple[str, ...]]] = {
    VideoHdrMode.HDR10: (
        "hdr10=1",
        "repeat-headers=1",
        "colorprim=bt2020",
        "transfer=smpte2084",
        "colormatrix=bt2020nc",
        "range=limited",
        f"master-display={_HDR10_MASTER_DISPLAY}",
        "max-cll=1000,400",
    ),
    VideoHdrMode.HLG: (
        "repeat-headers=1",
        "colorprim=bt2020",
        "transfer=arib-std-b67",
        "colormatrix=bt2020nc",
        "range=limited",
    ),
}


def _require(value: object, supported: Iterable[object], field: str) -> None:
    """Raise ``UnsupportedMaterializationError`` if ``value`` is not in ``supported``.

    The error's ``payload['supported']`` is the sorted ``str()`` of each
    supported value so the JSON-rendered payload is stable across runs.
    """
    supported_tuple = tuple(supported)
    if value not in supported_tuple:
        raise UnsupportedMaterializationError(
            f"{field}={value!r} is not supported",
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
            payload={"supported": sorted(SUPPORTED_CONTAINERS)},
        )
    _require(container, SUPPORTED_CONTAINERS, "container")
    return container


def _validate_video(video: VideoTrack) -> None:
    """Reject video tracks outside the codec/resolution matrix."""
    _require(video.codec, SUPPORTED_VIDEO_CODECS, "video.codec")
    _require(video.resolution, SUPPORTED_RESOLUTIONS, "video.resolution")


def _validate_audio(audios: Sequence[AudioTrack]) -> None:
    """Reject any audio track outside the codec matrix."""
    for index, audio in enumerate(audios):
        _require(audio.codec, SUPPORTED_AUDIO_CODECS, f"audio[{index}].codec")


def _interlaced_video_args(video: VideoTrack) -> list[str]:
    if video.field_order is None:
        return []
    if video.codec == "h264":
        return ["-x264-params", _X264_FIELD_ORDER_PARAMS[video.field_order]]
    if video.codec in HEVC_VIDEO_CODECS:
        return ["-x265-params", _X265_FIELD_ORDER_PARAMS[video.field_order]]
    raise UnsupportedMaterializationError(
        f"interlaced video codec {video.codec!r} is not supported",
        field="video.codec",
        payload={"supported": sorted(SUPPORTED_VIDEO_CODECS)},
    )


def _hdr_video_args(video: VideoTrack) -> list[str]:
    if video.hdr_mode is None:
        return []
    if video.codec not in HEVC_VIDEO_CODECS:
        raise UnsupportedMaterializationError(
            "HDR signaling requires HEVC/H.265 video materialization",
            field="video.hdr_mode",
            payload={"supported_codecs": sorted(HEVC_VIDEO_CODECS)},
        )
    if video.color_space not in {None, VideoColorSpace.BT2020}:
        raise UnsupportedMaterializationError(
            "HDR signaling requires color_space='bt2020' when color_space is set",
            field="video.color_space",
            payload={"supported": [VideoColorSpace.BT2020.value]},
        )
    if video.color_range not in {None, VideoColorRange.LIMITED}:
        raise UnsupportedMaterializationError(
            "HDR signaling requires color_range='limited' when color_range is set",
            field="video.color_range",
            payload={"supported": [VideoColorRange.LIMITED.value]},
        )
    if video.vfr_cadence is not None:
        raise UnsupportedMaterializationError(
            "HDR signaling cannot be combined with vfr_cadence",
            field="video.hdr_mode",
            payload={"vfr_cadence": video.vfr_cadence.value},
        )
    if video.field_order is not None:
        raise UnsupportedMaterializationError(
            "HDR signaling cannot be combined with field_order",
            field="video.hdr_mode",
            payload={"field_order": video.field_order.value},
        )
    return [
        "-vf",
        _HDR_FILTERS[video.hdr_mode],
        "-x265-params",
        ":".join(_HDR_X265_PARAMS[video.hdr_mode]),
    ]


def _color_signal_args(video: VideoTrack) -> list[str]:
    if video.hdr_mode is not None:
        return []
    args: list[str] = []
    if video.color_space is not None:
        args.extend(["-colorspace", _COLOR_SPACE_OUTPUT_ARGS[video.color_space]])
    if video.color_range is not None:
        args.extend(["-color_range", _COLOR_RANGE_OUTPUT_ARGS[video.color_range]])
    return args


def _validate_audio_only(container: str, audios: Sequence[AudioTrack]) -> None:
    """Reject audio-only output outside the container-specific codec matrix."""
    supported_codecs = SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER[container]
    for index, audio in enumerate(audios):
        _require(audio.codec, supported_codecs, f"audio[{index}].codec")


def _require_audio_only_track_counts(
    audios: Sequence[AudioTrack],
    audio_inputs: Sequence[FFmpegInput],
) -> None:
    """Audio-only assets are currently single-stream track assets."""
    if len(audios) != 1 or len(audio_inputs) != 1:
        raise UnsupportedMaterializationError(
            "audio-only assets must declare exactly one resolved audio stream",
            field="audio",
            payload={
                "audio_count": len(audios),
                "audio_input_count": len(audio_inputs),
            },
        )


def _input_args(ffmpeg_input: FFmpegInput, *, field: str) -> list[str]:
    """Argv slice for one resolved input.

    ``extra_flags`` (e.g. ``-t 2.0``) are emitted BEFORE ``-i`` because
    ffmpeg treats them as per-input options only when they precede the
    ``-i`` they qualify. Emitted after ``-i`` they bind to the next
    output (or input), which truncates the wrong stream.
    """
    if ffmpeg_input.lavfi is not None:
        return [*ffmpeg_input.extra_flags, "-f", "lavfi", "-i", ffmpeg_input.lavfi]
    if ffmpeg_input.file_path is not None:
        return [*ffmpeg_input.extra_flags, "-i", str(ffmpeg_input.file_path)]
    raise UnsupportedMaterializationError(
        "FFmpegInput must carry lavfi or file_path",
        field=field,
        payload={},
    )


def _video_input_args(video_input: FFmpegInput) -> list[str]:
    """Argv slice for the resolved video input."""
    return _input_args(video_input, field="video.source")


def _audio_input_args(audio_inputs: Sequence[FFmpegInput]) -> list[str]:
    """Argv slice covering all resolved audio inputs."""
    args: list[str] = []
    for audio_input in audio_inputs:
        args.extend(_input_args(audio_input, field="audio.source"))
    return args


def _map_args(audio_inputs: Sequence[FFmpegInput], *, first_audio_input_index: int) -> list[str]:
    """Argv slice selecting only the resolved video and audio streams."""
    args: list[str] = []
    if first_audio_input_index > 0:
        args.extend(["-map", "0:v:0"])
    for index, _audio_input in enumerate(audio_inputs, start=first_audio_input_index):
        args.extend(["-map", f"{index}:a:0"])
    return args


def _build_video_command(
    *,
    container: str,
    video: VideoTrack,
    video_input: FFmpegInput,
    audios: Sequence[AudioTrack],
    audio_inputs: Sequence[FFmpegInput],
    output_path: Path,
) -> list[str]:
    _require(container, SUPPORTED_VIDEO_CONTAINERS, "container")
    _validate_video(video)
    _validate_audio(audios)
    argv: list[str] = ["ffmpeg", "-hide_banner", "-y"]
    argv.extend(_video_input_args(video_input))
    argv.extend(_audio_input_args(audio_inputs))
    argv.extend(_map_args(audio_inputs, first_audio_input_index=1))
    argv.extend(["-c:v", VIDEO_ENCODER_BY_CODEC[video.codec], "-preset", "medium"])
    argv.extend(_hdr_video_args(video))
    argv.extend(_interlaced_video_args(video))
    argv.extend(_color_signal_args(video))
    argv.extend(["-c:a", "aac"])
    argv.extend(_BITEXACT_OUTPUT_FLAGS)
    argv.append("-shortest")
    argv.append(str(output_path))
    return argv


def _build_audio_only_command(
    *,
    container: str,
    audios: Sequence[AudioTrack],
    audio_inputs: Sequence[FFmpegInput],
    output_path: Path,
) -> list[str]:
    _require(container, SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER, "container")
    _require_audio_only_track_counts(audios, audio_inputs)
    _validate_audio_only(container, audios)
    argv: list[str] = ["ffmpeg", "-hide_banner", "-y"]
    argv.extend(_audio_input_args(audio_inputs))
    argv.extend(_map_args(audio_inputs, first_audio_input_index=0))
    argv.extend(["-c:a", AUDIO_ENCODER_BY_CODEC[audios[0].codec]])
    channel_count = AUDIO_CHANNEL_COUNTS_BY_NAME[audios[0].channels.value]
    argv.extend(["-ac", str(channel_count)])
    argv.extend(_BITEXACT_OUTPUT_FLAGS)
    argv.append("-shortest")
    argv.append(str(output_path))
    return argv


def build_command(
    *,
    video: VideoTrack | None,
    video_input: FFmpegInput | None,
    audios: Sequence[AudioTrack],
    audio_inputs: Sequence[FFmpegInput],
    output_path: Path,
) -> list[str]:
    """Build the ffmpeg argv for one asset.

    The caller has already turned the scenario's source enums into
    FFmpegInput recipes; this function focuses on muxing + codec wiring.

    Raises:
        UnsupportedMaterializationError: any element of the (container,
            video codec/resolution, audio codec) tuple falls outside the
            supported matrix, or an FFmpegInput is missing its input.
    """
    container = _resolve_container(output_path)
    if video is None:
        if video_input is not None:
            raise UnsupportedMaterializationError(
                "audio-only assets must not pass a video input",
                field="video_input",
                payload={},
            )
        return _build_audio_only_command(
            container=container,
            audios=audios,
            audio_inputs=audio_inputs,
            output_path=output_path,
        )
    if video_input is None:
        raise UnsupportedMaterializationError(
            "video assets must pass a video input",
            field="video_input",
            payload={},
        )
    return _build_video_command(
        container=container,
        video=video,
        video_input=video_input,
        audios=audios,
        audio_inputs=audio_inputs,
        output_path=output_path,
    )


def run_ffmpeg(
    argv: list[str],
    *,
    ffmpeg_version: str,
    timeout_s: float = 60.0,
) -> tuple[ToolInvocation, str]:
    """Invoke ffmpeg. Returns ``(invocation, stderr_tail)`` regardless of exit code.

    ``stderr_tail`` is the last 2 KB of stderr decoded UTF-8 lossy.
    """
    start = time.monotonic_ns()
    completed = subprocess.run(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    duration_ns = time.monotonic_ns() - start
    stderr_bytes = completed.stderr or b""
    stderr_tail = stderr_bytes[-2048:].decode("utf-8", errors="replace")
    invocation = ToolInvocation(
        tool="ffmpeg",
        version=ffmpeg_version,
        command=list(argv),
        exit_code=completed.returncode,
        duration_ns=duration_ns,
    )
    return invocation, stderr_tail
