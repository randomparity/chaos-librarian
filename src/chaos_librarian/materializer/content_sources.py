"""Content-source provider registry used by Phase-A synthesis."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Protocol

from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceCapabilities,
    ContentSourceEvidence,
    ContentSourceProviderCapability,
    ContentTrackKind,
)
from chaos_librarian.contract.scenario import AudioSource, VideoSource
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.tooling.recipes import (
    FFmpegInput,
    recipe_channel_tones,
    recipe_color_bars,
    recipe_mandelbrot,
    recipe_silence,
    recipe_sine,
    recipe_solid_color,
)

FPS_DEFAULT: Final = 24
RESOLUTION_PIXELS: Final[dict[str, tuple[int, int]]] = {
    "sd": (640, 480),
    "hd": (1280, 720),
    "1080p": (1920, 1080),
}
PROVIDER_NAME: Final = "builtin-lavfi"

VideoRecipe = Callable[..., FFmpegInput]
AudioRecipe = Callable[..., FFmpegInput]

VIDEO_RECIPES: Final[dict[VideoSource, VideoRecipe]] = {
    VideoSource.MANDELBROT: recipe_mandelbrot,
    VideoSource.COLOR_BARS: recipe_color_bars,
    VideoSource.SOLID_COLOR: recipe_solid_color,
}
AUDIO_RECIPES: Final[dict[AudioSource, AudioRecipe]] = {
    AudioSource.SINE: recipe_sine,
    AudioSource.SILENCE: recipe_silence,
    AudioSource.CHANNEL_TONES: recipe_channel_tones,
}


@dataclass(frozen=True, slots=True)
class SourceRequest:
    asset_id: str
    track_kind: ContentTrackKind
    track_index: int | None
    source: str
    seed: int
    duration_s: float
    width: int | None
    height: int | None
    fps: int | None
    channels: str | None


@dataclass(frozen=True, slots=True)
class SourceResolution:
    ffmpeg_input: FFmpegInput
    evidence: ContentSourceEvidence


class ContentSourceProvider(Protocol):
    provider_name: str

    def resolve(
        self,
        *,
        source: VideoSource | AudioSource,
        request: SourceRequest,
    ) -> SourceResolution:
        """Resolve a scenario source to an FFmpeg input plus replay evidence."""

    def capability(self, *, ffmpeg_available: bool) -> ContentSourceProviderCapability:
        """Report provider capability for the current host."""


@dataclass(frozen=True, slots=True)
class _BuiltinLavfiVideoProvider:
    provider_name: str = PROVIDER_NAME

    def resolve(
        self,
        *,
        source: VideoSource | AudioSource,
        request: SourceRequest,
    ) -> SourceResolution:
        if not isinstance(source, VideoSource) or source not in VIDEO_RECIPES:
            raise _unsupported_source("video.source", VIDEO_RECIPES)
        if request.width is None or request.height is None or request.fps is None:
            raise UnsupportedMaterializationError(
                "video source request requires width, height, and fps",
                field="video.source",
                payload={},
            )
        recipe = VIDEO_RECIPES[source]
        ffmpeg_input = recipe(
            width=request.width,
            height=request.height,
            fps=request.fps,
            duration_s=request.duration_s,
            seed=request.seed,
        )
        return SourceResolution(
            ffmpeg_input=ffmpeg_input,
            evidence=_builtin_evidence(request),
        )

    def capability(self, *, ffmpeg_available: bool) -> ContentSourceProviderCapability:
        return _builtin_capability(ffmpeg_available=ffmpeg_available)


@dataclass(frozen=True, slots=True)
class _BuiltinLavfiAudioProvider:
    provider_name: str = PROVIDER_NAME

    def resolve(
        self,
        *,
        source: VideoSource | AudioSource,
        request: SourceRequest,
    ) -> SourceResolution:
        if not isinstance(source, AudioSource) or source not in AUDIO_RECIPES:
            raise _unsupported_source("audio.source", AUDIO_RECIPES)
        if request.channels is None:
            raise UnsupportedMaterializationError(
                "audio source request requires channels",
                field="audio.source",
                payload={},
            )
        recipe = AUDIO_RECIPES[source]
        ffmpeg_input = recipe(
            channels=request.channels,
            duration_s=request.duration_s,
            seed=request.seed,
        )
        return SourceResolution(
            ffmpeg_input=ffmpeg_input,
            evidence=_builtin_evidence(request),
        )

    def capability(self, *, ffmpeg_available: bool) -> ContentSourceProviderCapability:
        return _builtin_capability(ffmpeg_available=ffmpeg_available)


_VIDEO_PROVIDER: Final[ContentSourceProvider] = _BuiltinLavfiVideoProvider()
_AUDIO_PROVIDER: Final[ContentSourceProvider] = _BuiltinLavfiAudioProvider()


def resolve_video_source(source: VideoSource, request: SourceRequest) -> SourceResolution:
    """Resolve a video source through the registered provider."""
    if source not in VIDEO_RECIPES:
        raise _unsupported_source("video.source", VIDEO_RECIPES)
    return _VIDEO_PROVIDER.resolve(source=source, request=request)


def resolve_audio_source(source: AudioSource, request: SourceRequest) -> SourceResolution:
    """Resolve an audio source through the registered provider."""
    if source not in AUDIO_RECIPES:
        raise _unsupported_source("audio.source", AUDIO_RECIPES)
    return _AUDIO_PROVIDER.resolve(source=source, request=request)


def collect_content_source_capabilities(ffmpeg_available: bool) -> ContentSourceCapabilities:
    """Collect content-source capabilities for all registered providers."""
    return ContentSourceCapabilities(
        providers=[_builtin_capability(ffmpeg_available=ffmpeg_available)],
    )


def _builtin_evidence(request: SourceRequest) -> ContentSourceEvidence:
    return ContentSourceEvidence(
        asset_id=request.asset_id,
        track_kind=request.track_kind,
        source=request.source,
        provider=PROVIDER_NAME,
        recipe_digest=_recipe_digest(request),
        track_index=request.track_index,
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
    )


def _builtin_capability(*, ffmpeg_available: bool) -> ContentSourceProviderCapability:
    return ContentSourceProviderCapability(
        name=PROVIDER_NAME,
        available=ffmpeg_available,
        requires_network=False,
        requires_cache=False,
        required_tool="ffmpeg",
        reason=None if ffmpeg_available else "required tool unavailable: ffmpeg",
        sources=_capability_sources(),
    )


def _capability_sources() -> tuple[str, ...]:
    sources = [f"video:{source.value}" for source in VIDEO_RECIPES]
    sources.extend(f"audio:{source.value}" for source in AUDIO_RECIPES)
    return tuple(sorted(sources))


def _unsupported_source(
    field: str,
    supported: dict[VideoSource, VideoRecipe] | dict[AudioSource, AudioRecipe],
) -> UnsupportedMaterializationError:
    return UnsupportedMaterializationError(
        f"{field} is not supported",
        field=field,
        payload={"supported": sorted(source.value for source in supported)},
    )


def _recipe_digest(request: SourceRequest) -> str:
    payload = {
        "asset_id": request.asset_id,
        "track_kind": request.track_kind.value,
        "track_index": request.track_index,
        "source": request.source,
        "seed": request.seed,
        "duration_s": request.duration_s,
        "width": request.width,
        "height": request.height,
        "fps": request.fps,
        "channels": request.channels,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"
