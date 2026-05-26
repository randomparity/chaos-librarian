"""Preflight checks shared by preflight and synthesis.

Constants:
    RESOLUTION_PIXELS, FPS_DEFAULT, VIDEO_RECIPES, AUDIO_RECIPES — recipe
    lookup tables; synthesis re-uses them through the source registry so
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
    SubtitleSource,
    SubtitleTrack,
    VideoTrack,
)
from chaos_librarian.materializer.actions import (
    NETWORK_LAG_ACTIONS,
    SUPPORTED_S6_ACTIONS,
    SUPPORTED_S10_ACTIONS,
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
from chaos_librarian.media_matrix import SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER
from chaos_librarian.topology import iter_asset_contexts

__all__ = [
    "AUDIO_RECIPES",
    "FPS_DEFAULT",
    "NETWORK_LAG_ACTIONS",
    "RESOLUTION_PIXELS",
    "SUPPORTED_S6_ACTIONS",
    "SUPPORTED_S10_ACTIONS",
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
        ),
    )
    build_command(
        video=video,
        video_input=video_input,
        audios=audios,
        audio_inputs=audio_inputs,
        output_path=Path(f"preflight.{container}"),
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
    _preflight_audio_inputs(audios)


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
            ),
        )
        inputs.append(audio_input)
    return inputs


def _preflight_subtitles(subtitles: Sequence[SubtitleTrack]) -> None:
    """Subtitle matrix: SRT + generated + sidecar only."""
    for index, sub in enumerate(subtitles):
        if sub.codec != "srt":
            raise UnsupportedMaterializationError(
                f"subtitle codec {sub.codec!r} not supported",
                field=f"subtitle[{index}].codec",
                payload={"supported": ["srt"]},
            )
        if sub.source is not SubtitleSource.GENERATED_SRT:
            raise UnsupportedMaterializationError(
                f"subtitle source {sub.source!r} not supported",
                field=f"subtitle[{index}].source",
                payload={"supported": [SubtitleSource.GENERATED_SRT.value]},
            )
        if sub.mode is not SubtitleMode.SIDECAR:
            raise UnsupportedMaterializationError(
                f"subtitle mode {sub.mode!r} not supported",
                field=f"subtitle[{index}].mode",
                payload={"supported": ["sidecar"]},
            )


def preflight_timeline(scenario: Scenario, *, allow_network_lag: bool = False) -> None:
    """Reject any timeline event outside current materialize support.

    Raised before phase A so the matrix-rejection contract (no run-dir
    allocation, exit 5, E_MATERIALIZE_TIMELINE_UNSUPPORTED) holds.
    """
    supported_actions = SUPPORTED_S10_ACTIONS
    if allow_network_lag:
        supported_actions = supported_actions | NETWORK_LAG_ACTIONS
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
