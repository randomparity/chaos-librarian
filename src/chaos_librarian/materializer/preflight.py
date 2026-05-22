"""Preflight checks + recipe tables shared by preflight and synthesis.

Constants:
    RESOLUTION_PIXELS, FPS_DEFAULT, VIDEO_RECIPES, AUDIO_RECIPES — recipe
    lookup tables; ``synthesis.materialize_one_asset`` re-uses them so
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
from typing import Final

from chaos_librarian.contract.scenario import (
    Asset,
    AudioSource,
    AudioTrack,
    Scenario,
    SubtitleMode,
    SubtitleSource,
    SubtitleTrack,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.materializer.actions import SUPPORTED_S6_ACTIONS, SUPPORTED_S10_ACTIONS
from chaos_librarian.materializer.errors import (
    TimelineUnsupportedError,
    UnsupportedMaterializationError,
)
from chaos_librarian.materializer.ffmpeg import build_command
from chaos_librarian.materializer.recipes import (
    FFmpegInput,
    recipe_channel_tones,
    recipe_color_bars,
    recipe_mandelbrot,
    recipe_silence,
    recipe_sine,
    recipe_solid_color,
)

__all__ = [
    "AUDIO_RECIPES",
    "FPS_DEFAULT",
    "RESOLUTION_PIXELS",
    "SUPPORTED_S6_ACTIONS",
    "SUPPORTED_S10_ACTIONS",
    "VIDEO_RECIPES",
    "iter_assets",
    "preflight_asset",
    "preflight_timeline",
]


RESOLUTION_PIXELS: Final[dict[str, tuple[int, int]]] = {
    "sd": (640, 480),
    "hd": (1280, 720),
    "1080p": (1920, 1080),
}
FPS_DEFAULT: Final = 24

VIDEO_RECIPES = {
    VideoSource.MANDELBROT: recipe_mandelbrot,
    VideoSource.COLOR_BARS: recipe_color_bars,
    VideoSource.SOLID_COLOR: recipe_solid_color,
}
AUDIO_RECIPES = {
    AudioSource.SINE: recipe_sine,
    AudioSource.SILENCE: recipe_silence,
    AudioSource.CHANNEL_TONES: recipe_channel_tones,
}


def iter_assets(scenario: Scenario) -> Iterator[Asset]:
    """Iterate all assets in scenario order."""
    for work in scenario.works:
        for variant in work.variants:
            yield from variant.bundle.assets


def preflight_asset(
    video: VideoTrack | None,
    audios: Sequence[AudioTrack],
    subtitles: Sequence[SubtitleTrack],
    container: str,
) -> None:
    """Run build_command in a dry mode — raises UnsupportedMaterializationError fast.

    Subtitle checks are inline: only ``codec=srt, source=generated_srt,
    mode=sidecar`` is supported. Without these gates, ``mode=embedded`` or
    ``codec=ass`` would fall through and the materialize "success" would
    silently drop the requested subtitles.
    """
    if video is None:
        raise UnsupportedMaterializationError(
            "every asset must declare a video track.",
            field="video",
            payload={},
        )
    video_recipe = VIDEO_RECIPES.get(video.source)
    if video_recipe is None:
        raise UnsupportedMaterializationError(
            f"video source {video.source!r} not supported",
            field="video.source",
            payload={"supported": sorted(s.value for s in VIDEO_RECIPES)},
        )
    audio_inputs = _preflight_audio_inputs(audios)
    _preflight_subtitles(subtitles)
    width, height = RESOLUTION_PIXELS.get(video.resolution, (1, 1))
    video_input = video_recipe(width=width, height=height, fps=FPS_DEFAULT, duration_s=1.0, seed=0)
    build_command(
        video=video,
        video_input=video_input,
        audios=audios,
        audio_inputs=audio_inputs,
        output_path=Path(f"preflight.{container}"),
    )


def _preflight_audio_inputs(audios: Sequence[AudioTrack]) -> list[FFmpegInput]:
    """Build the audio FFmpegInput list at preflight time, raising on unknown sources."""
    inputs: list[FFmpegInput] = []
    for audio in audios:
        recipe = AUDIO_RECIPES.get(audio.source)
        if recipe is None:
            raise UnsupportedMaterializationError(
                f"audio source {audio.source!r} not supported",
                field="audio.source",
                payload={"supported": sorted(s.value for s in AUDIO_RECIPES)},
            )
        inputs.append(recipe(channels=audio.channels, duration_s=1.0, seed=0))
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


def preflight_timeline(scenario: Scenario) -> None:
    """Reject any timeline event outside current materialize support.

    Raised before phase A so the matrix-rejection contract (no run-dir
    allocation, exit 5, E_MATERIALIZE_TIMELINE_UNSUPPORTED) holds.
    """
    for index, event in enumerate(scenario.timeline):
        if event.action not in SUPPORTED_S10_ACTIONS:
            raise TimelineUnsupportedError(
                f"timeline action {event.action.value!r} not supported",
                field=f"timeline[{index}].action",
                payload={
                    "event_id": event.id,
                    "action": event.action.value,
                    "supported": sorted(a.value for a in SUPPORTED_S10_ACTIONS),
                },
            )
