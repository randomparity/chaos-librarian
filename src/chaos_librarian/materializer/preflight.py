"""Preflight checks shared by preflight and synthesis.

Constants:
    RESOLUTION_PIXELS, FPS_DEFAULT, VIDEO_RECIPES, AUDIO_RECIPES — recipe
    lookup tables; synthesis re-uses them through content-source resolution so
    preflight rejection and real synthesis stay in lock-step.

Public helpers:
    iter_assets — walk every asset in a scenario in declared order.
    preflight_asset — dry-build the ffmpeg command for one asset and
        raise ``UnsupportedMaterializationError`` on any unsupported
        codec/source/mode before the real synthesis loop starts.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from pathlib import Path

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    Asset,
    AudioTrack,
    Scenario,
    SubtitleMode,
    SubtitleTrack,
    VideoTrack,
)
from chaos_librarian.materializer.actions import (
    BASE_FILESYSTEM_ACTIONS,
    MATERIALIZE_SUPPORTED_ACTIONS,
    NETWORK_FS_CHAOS_ACTIONS,
    NETWORK_LAG_ACTIONS,
)
from chaos_librarian.materializer.content_sources import (
    AUDIO_RECIPES,
    FPS_DEFAULT,
    RESOLUTION_PIXELS,
    VIDEO_RECIPES,
    AudioSourceRequest,
    VideoSourceRequest,
    resolve_audio_input,
    resolve_video_input,
)
from chaos_librarian.materializer.errors import (
    TimelineUnsupportedError,
    UnsupportedMaterializationError,
)
from chaos_librarian.materializer.tooling.ffmpeg import build_command
from chaos_librarian.materializer.tooling.recipes import FFmpegInput
from chaos_librarian.materializer.tooling.subtitles import supported_subtitle_encodings
from chaos_librarian.media_matrix import (
    RESOLUTION_SWITCH_VIDEO_CODEC,
    RESOLUTION_SWITCH_VIDEO_CONTAINER,
    RESOLUTION_SWITCH_VIDEO_RESOLUTION,
    RESOLUTION_SWITCH_VIDEO_SOURCE,
    SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER,
)
from chaos_librarian.topology import iter_asset_contexts

__all__ = [
    "AUDIO_RECIPES",
    "BASE_FILESYSTEM_ACTIONS",
    "FPS_DEFAULT",
    "MATERIALIZE_SUPPORTED_ACTIONS",
    "NETWORK_FS_CHAOS_ACTIONS",
    "NETWORK_LAG_ACTIONS",
    "RESOLUTION_PIXELS",
    "VIDEO_RECIPES",
    "iter_assets",
    "preflight_asset",
    "preflight_timeline",
]


def iter_assets(scenario: Scenario) -> Iterator[Asset]:
    """Iterate all assets in scenario order."""
    for context in iter_asset_contexts(scenario):
        yield context.asset


def preflight_asset(
    *,
    parent_kind: ParentKind,
    video: VideoTrack | None,
    audios: Sequence[AudioTrack],
    subtitles: Sequence[SubtitleTrack],
    container: str,
) -> None:
    """Reject unsupported media shapes before run-dir allocation.

    Movie and episode assets resolve video/audio sources, then dry-build the
    video-backed FFmpeg command through ``build_command``. Track assets enforce
    the audio-only policy and resolve audio inputs.

    Subtitle checks are inline: only ``codec=srt, source=generated_srt,
    mode=sidecar`` is supported. Without these gates, ``mode=embedded`` or
    ``codec=ass`` would fall through and the materialize "success" would
    silently drop the requested subtitles.
    """
    if parent_kind is ParentKind.TRACK:
        _preflight_track_asset(
            video=video,
            audios=audios,
            subtitles=subtitles,
            container=container,
        )
        return

    if video is None:
        raise UnsupportedMaterializationError(
            "every asset must declare a video track.",
            field="video",
            payload={},
        )
    if video.resolution_sequence is not None:
        _preflight_resolution_switch_asset(
            video=video,
            audios=audios,
            subtitles=subtitles,
            container=container,
        )
        return
    audio_inputs = _preflight_audio_inputs(audios)
    _preflight_subtitles(subtitles)
    width, height = RESOLUTION_PIXELS.get(video.resolution, (1, 1))
    video_input = resolve_video_input(
        source=video.source,
        request=VideoSourceRequest(
            asset_id="preflight",
            seed=0,
            duration_s=1.0,
            width=width,
            height=height,
            fps=FPS_DEFAULT,
            vfr_cadence=video.vfr_cadence,
            field_order=video.field_order,
            color_space=video.color_space,
            color_range=video.color_range,
            hdr_mode=video.hdr_mode,
        ),
    )
    build_command(
        video=video,
        video_input=video_input,
        audios=audios,
        audio_inputs=audio_inputs,
        output_path=Path(f"preflight.{container}"),
    )


def _preflight_resolution_switch_asset(
    *,
    video: VideoTrack,
    audios: Sequence[AudioTrack],
    subtitles: Sequence[SubtitleTrack],
    container: str,
) -> None:
    _require_resolution_switch_value(
        value=container,
        expected=RESOLUTION_SWITCH_VIDEO_CONTAINER,
        field="container",
    )
    _require_resolution_switch_value(
        value=video.source.value,
        expected=RESOLUTION_SWITCH_VIDEO_SOURCE,
        field="video.source",
    )
    _require_resolution_switch_value(
        value=video.codec,
        expected=RESOLUTION_SWITCH_VIDEO_CODEC,
        field="video.codec",
    )
    _require_resolution_switch_value(
        value=video.resolution,
        expected=RESOLUTION_SWITCH_VIDEO_RESOLUTION,
        field="video.resolution",
    )
    if audios:
        raise UnsupportedMaterializationError(
            "resolution-switch video materialization does not support audio streams",
            field="audio",
            payload={"count": len(audios)},
        )
    if subtitles:
        raise UnsupportedMaterializationError(
            "resolution-switch video materialization does not support subtitles",
            field="subtitles",
            payload={"count": len(subtitles)},
        )
    for field_name, value in (
        ("vfr_cadence", video.vfr_cadence),
        ("field_order", video.field_order),
        ("color_space", video.color_space),
        ("color_range", video.color_range),
        ("hdr_mode", video.hdr_mode),
    ):
        if value is None:
            continue
        raise UnsupportedMaterializationError(
            f"resolution-switch video materialization cannot combine {field_name}",
            field=f"video.{field_name}",
            payload={field_name: value.value},
        )
    for width, height in (RESOLUTION_PIXELS["sd"], RESOLUTION_PIXELS["hd"]):
        resolve_video_input(
            source=video.source,
            request=VideoSourceRequest(
                asset_id="preflight",
                seed=0,
                duration_s=0.5,
                width=width,
                height=height,
                fps=FPS_DEFAULT,
                resolution_sequence=video.resolution_sequence,
            ),
        )


def _require_resolution_switch_value(*, value: str, expected: str, field: str) -> None:
    if value == expected:
        return
    raise UnsupportedMaterializationError(
        f"resolution-switch video materialization requires {field}={expected!r}",
        field=field,
        payload={"expected": expected, "actual": value},
    )


def _preflight_track_asset(
    *,
    video: VideoTrack | None,
    audios: Sequence[AudioTrack],
    subtitles: Sequence[SubtitleTrack],
    container: str,
) -> None:
    """Reject track assets outside the audio-only materializer matrix."""
    if video is not None:
        raise UnsupportedMaterializationError(
            "track assets must not declare a video track.",
            field="video",
            payload={},
        )
    if subtitles:
        raise UnsupportedMaterializationError(
            "track assets must not declare subtitles.",
            field="subtitles",
            payload={},
        )
    if len(audios) != 1:
        raise UnsupportedMaterializationError(
            "track assets must declare exactly one audio stream.",
            field="audio",
            payload={"count": len(audios)},
        )
    supported_codecs = SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER.get(container)
    if supported_codecs is None:
        raise UnsupportedMaterializationError(
            f"audio-only container {container!r} is not supported",
            field="container",
            payload={"supported": sorted(SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER)},
        )
    audio = audios[0]
    if audio.codec not in supported_codecs:
        raise UnsupportedMaterializationError(
            f"audio codec {audio.codec!r} is not supported for {container!r}",
            field="audio[0].codec",
            payload={"supported": sorted(supported_codecs)},
        )
    audio_inputs = _preflight_audio_inputs(audios)
    build_command(
        video=None,
        video_input=None,
        audios=audios,
        audio_inputs=audio_inputs,
        output_path=Path(f"preflight.{container}"),
    )


def _preflight_audio_inputs(audios: Sequence[AudioTrack]) -> list[FFmpegInput]:
    """Build the audio FFmpegInput list at preflight time, raising on unknown sources."""
    inputs: list[FFmpegInput] = []
    for index, audio in enumerate(audios):
        audio_input = resolve_audio_input(
            source=audio.source,
            request=AudioSourceRequest(
                asset_id="preflight",
                track_index=index,
                seed=0,
                duration_s=1.0,
                channels=audio.channels.value,
                noise_color=audio.noise_color,
                sample_rate=audio.sample_rate,
                sample_format=audio.sample_format,
            ),
        )
        inputs.append(audio_input)
    return inputs


def _preflight_subtitles(subtitles: Sequence[SubtitleTrack]) -> None:
    """Reject declared subtitle recipes outside the materializer matrix."""
    for index, sub in enumerate(subtitles):
        if sub.mode is not SubtitleMode.SIDECAR:
            raise UnsupportedMaterializationError(
                f"subtitle mode {sub.mode!r} not supported",
                field=f"subtitle[{index}].mode",
                payload={"supported": ["sidecar"]},
            )
        supported_encodings = supported_subtitle_encodings(codec=sub.codec, source=sub.source)
        if supported_encodings is None:
            raise UnsupportedMaterializationError(
                f"subtitle codec/source recipe {sub.codec.value}/{sub.source.value} not supported",
                field=f"subtitle[{index}].source",
                payload={
                    "codec": sub.codec.value,
                    "source": sub.source.value,
                },
            )
        if sub.encoding in supported_encodings:
            continue
        raise UnsupportedMaterializationError(
            f"subtitle encoding {sub.encoding.value!r} not supported",
            field=f"subtitle[{index}].encoding",
            payload={"supported": sorted(encoding.value for encoding in supported_encodings)},
        )


def preflight_timeline(
    scenario: Scenario,
    *,
    allow_network_lag: bool = False,
    allow_network_fs_chaos: bool = False,
) -> None:
    """Reject any timeline event outside current materialize support.

    Raised before phase A so the matrix-rejection contract (no run-dir
    allocation, exit 5, E_MATERIALIZE_TIMELINE_UNSUPPORTED) holds. The
    network-lag and network-fs-chaos families are wall-clock-only; static
    ``materialize`` passes neither flag and so rejects both.
    """
    supported_actions = MATERIALIZE_SUPPORTED_ACTIONS
    if allow_network_lag:
        supported_actions = supported_actions | NETWORK_LAG_ACTIONS
    if allow_network_fs_chaos:
        supported_actions = supported_actions | NETWORK_FS_CHAOS_ACTIONS
    for index, event in enumerate(scenario.timeline):
        if event.action not in supported_actions:
            raise TimelineUnsupportedError(
                f"timeline action {event.action.value!r} not supported",
                field=f"timeline[{index}].action",
                payload={
                    "event_id": event.id,
                    "action": event.action.value,
                    "supported": sorted(a.value for a in supported_actions),
                },
            )
