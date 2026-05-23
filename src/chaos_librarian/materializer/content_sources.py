"""Content-source provider registry used by Phase-A synthesis."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
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
    source_keys: tuple[VideoSource, ...] = tuple(VIDEO_RECIPES)

    def resolve(
        self,
        *,
        source: VideoSource | AudioSource,
        request: SourceRequest,
    ) -> SourceResolution:
        if not isinstance(source, VideoSource) or source not in VIDEO_RECIPES:
            raise _unsupported_source("video.source", VIDEO_RECIPES)
        _validate_request_source(field="video.source", expected=source.value, actual=request.source)
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
        return _builtin_capability(
            ffmpeg_available=ffmpeg_available,
            sources=[f"video:{source.value}" for source in self.source_keys],
        )


@dataclass(frozen=True, slots=True)
class _BuiltinLavfiAudioProvider:
    provider_name: str = PROVIDER_NAME
    source_keys: tuple[AudioSource, ...] = tuple(AUDIO_RECIPES)

    def resolve(
        self,
        *,
        source: VideoSource | AudioSource,
        request: SourceRequest,
    ) -> SourceResolution:
        if not isinstance(source, AudioSource) or source not in AUDIO_RECIPES:
            raise _unsupported_source("audio.source", AUDIO_RECIPES)
        _validate_request_source(field="audio.source", expected=source.value, actual=request.source)
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
        return _builtin_capability(
            ffmpeg_available=ffmpeg_available,
            sources=[f"audio:{source.value}" for source in self.source_keys],
        )


_VIDEO_PROVIDER: Final[ContentSourceProvider] = _BuiltinLavfiVideoProvider()
_AUDIO_PROVIDER: Final[ContentSourceProvider] = _BuiltinLavfiAudioProvider()
_VIDEO_PROVIDERS: Final[dict[VideoSource, ContentSourceProvider]] = {
    source: _VIDEO_PROVIDER for source in VIDEO_RECIPES
}
_AUDIO_PROVIDERS: Final[dict[AudioSource, ContentSourceProvider]] = {
    source: _AUDIO_PROVIDER for source in AUDIO_RECIPES
}


def resolve_video_source(source: VideoSource, request: SourceRequest) -> SourceResolution:
    """Resolve a video source through the registered provider."""
    provider = _VIDEO_PROVIDERS.get(source)
    if provider is None:
        raise _unsupported_source("video.source", _VIDEO_PROVIDERS)
    return provider.resolve(source=source, request=request)


def resolve_audio_source(source: AudioSource, request: SourceRequest) -> SourceResolution:
    """Resolve an audio source through the registered provider."""
    provider = _AUDIO_PROVIDERS.get(source)
    if provider is None:
        raise _unsupported_source("audio.source", _AUDIO_PROVIDERS)
    return provider.resolve(source=source, request=request)


def collect_content_source_capabilities(ffmpeg_available: bool) -> ContentSourceCapabilities:
    """Collect content-source capabilities for all registered providers."""
    return ContentSourceCapabilities(
        providers=_merge_provider_capabilities(
            provider.capability(ffmpeg_available=ffmpeg_available)
            for provider in _registered_providers()
        ),
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


def _builtin_capability(
    *,
    ffmpeg_available: bool,
    sources: list[str],
) -> ContentSourceProviderCapability:
    return ContentSourceProviderCapability(
        name=PROVIDER_NAME,
        available=ffmpeg_available,
        requires_network=False,
        requires_cache=False,
        required_tool="ffmpeg",
        reason=None if ffmpeg_available else "required tool unavailable: ffmpeg",
        sources=tuple(sorted(sources)),
    )


def _registered_providers() -> tuple[ContentSourceProvider, ...]:
    providers: list[ContentSourceProvider] = []
    seen: set[int] = set()
    for provider in (*_VIDEO_PROVIDERS.values(), *_AUDIO_PROVIDERS.values()):
        provider_id = id(provider)
        if provider_id in seen:
            continue
        providers.append(provider)
        seen.add(provider_id)
    return tuple(providers)


def _merge_provider_capabilities(
    capabilities: Iterable[ContentSourceProviderCapability],
) -> list[ContentSourceProviderCapability]:
    merged: dict[str, ContentSourceProviderCapability] = {}
    sources_by_provider: dict[str, set[str]] = {}
    for capability in capabilities:
        existing = merged.get(capability.name)
        if existing is None:
            merged[capability.name] = capability
            sources_by_provider[capability.name] = set(capability.sources)
            continue
        sources_by_provider[capability.name].update(capability.sources)
        merged[capability.name] = existing.model_copy(
            update={
                "available": existing.available and capability.available,
                "reason": existing.reason or capability.reason,
                "sources": tuple(sorted(sources_by_provider[capability.name])),
            }
        )
    return [merged[name] for name in sorted(merged)]


def _unsupported_source(
    field: str,
    supported: Iterable[VideoSource | AudioSource],
) -> UnsupportedMaterializationError:
    return UnsupportedMaterializationError(
        f"{field} is not supported",
        field=field,
        payload={"supported": sorted(source.value for source in supported)},
    )


def _validate_request_source(*, field: str, expected: str, actual: str) -> None:
    if actual == expected:
        return
    raise UnsupportedMaterializationError(
        f"{field} request source does not match resolver source",
        field=field,
        payload={"expected": expected, "actual": actual},
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
