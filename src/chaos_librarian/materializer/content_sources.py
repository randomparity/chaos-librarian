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
from chaos_librarian.contract.scenario import (
    AudioSource,
    VideoColorRange,
    VideoColorSpace,
    VideoFieldOrder,
    VideoHdrMode,
    VideoSource,
    VideoVfrCadence,
)
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.tooling.recipes import (
    VFR_BASE_FPS,
    FFmpegInput,
    apply_interlaced_field_order,
    apply_vfr_cadence,
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
VFR_CAPABILITY_SOURCES: Final[tuple[str, ...]] = tuple(
    f"video:vfr:{cadence.value}" for cadence in VideoVfrCadence
)
INTERLACED_CAPABILITY_SOURCES: Final[tuple[str, ...]] = tuple(
    f"video:interlaced:{field_order.value}" for field_order in VideoFieldOrder
)
COLOR_SPACE_CAPABILITY_SOURCES: Final[tuple[str, ...]] = tuple(
    f"video:color_space:{color_space.value}" for color_space in VideoColorSpace
)
COLOR_RANGE_CAPABILITY_SOURCES: Final[tuple[str, ...]] = tuple(
    f"video:color_range:{color_range.value}" for color_range in VideoColorRange
)
HDR_CAPABILITY_SOURCES: Final[tuple[str, ...]] = tuple(
    f"video:hdr:{hdr_mode.value}" for hdr_mode in VideoHdrMode
)


@dataclass(frozen=True, slots=True)
class VideoSourceRequest:
    asset_id: str
    seed: int
    duration_s: float
    width: int
    height: int
    fps: int
    vfr_cadence: VideoVfrCadence | None = None
    field_order: VideoFieldOrder | None = None
    color_space: VideoColorSpace | None = None
    color_range: VideoColorRange | None = None
    hdr_mode: VideoHdrMode | None = None
    track_index: None = None


@dataclass(frozen=True, slots=True)
class AudioSourceRequest:
    asset_id: str
    track_index: int
    seed: int
    duration_s: float
    channels: str


@dataclass(frozen=True, slots=True)
class SourceResolution:
    ffmpeg_input: FFmpegInput
    evidence: ContentSourceEvidence


class ContentSourceProvider(Protocol):
    def resolve_video(
        self,
        *,
        source: VideoSource,
        request: VideoSourceRequest,
    ) -> SourceResolution:
        """Resolve a video source to an FFmpeg input plus replay evidence."""

    def resolve_audio(
        self,
        *,
        source: AudioSource,
        request: AudioSourceRequest,
    ) -> SourceResolution:
        """Resolve an audio source to an FFmpeg input plus replay evidence."""

    def resolve_video_input(
        self,
        *,
        source: VideoSource,
        request: VideoSourceRequest,
    ) -> FFmpegInput:
        """Resolve a video source to an FFmpeg input without replay evidence."""

    def resolve_audio_input(
        self,
        *,
        source: AudioSource,
        request: AudioSourceRequest,
    ) -> FFmpegInput:
        """Resolve an audio source to an FFmpeg input without replay evidence."""

    def capability(
        self, *, ffmpeg_available: bool, hdr_available: bool
    ) -> ContentSourceProviderCapability:
        """Report provider capability for the current host."""


@dataclass(frozen=True, slots=True)
class _BuiltinLavfiProvider:
    video_source_keys: tuple[VideoSource, ...] = tuple(VIDEO_RECIPES)
    audio_source_keys: tuple[AudioSource, ...] = tuple(AUDIO_RECIPES)

    def resolve_video(
        self,
        *,
        source: VideoSource,
        request: VideoSourceRequest,
    ) -> SourceResolution:
        ffmpeg_input = self.resolve_video_input(source=source, request=request)
        return SourceResolution(
            ffmpeg_input=ffmpeg_input,
            evidence=_builtin_evidence(
                source=source,
                track_kind=ContentTrackKind.VIDEO,
                request=request,
                ffmpeg_input=ffmpeg_input,
            ),
        )

    def resolve_audio(
        self,
        *,
        source: AudioSource,
        request: AudioSourceRequest,
    ) -> SourceResolution:
        ffmpeg_input = self.resolve_audio_input(source=source, request=request)
        return SourceResolution(
            ffmpeg_input=ffmpeg_input,
            evidence=_builtin_evidence(
                source=source,
                track_kind=ContentTrackKind.AUDIO,
                request=request,
                ffmpeg_input=ffmpeg_input,
            ),
        )

    def resolve_video_input(
        self,
        *,
        source: VideoSource,
        request: VideoSourceRequest,
    ) -> FFmpegInput:
        if source not in VIDEO_RECIPES:
            raise _unsupported_source("video.source", VIDEO_RECIPES)
        if request.vfr_cadence is not None and request.field_order is not None:
            raise UnsupportedMaterializationError(
                "field_order cannot be combined with vfr_cadence",
                field="video.field_order",
                payload={
                    "vfr_cadence": request.vfr_cadence.value,
                    "field_order": request.field_order.value,
                },
            )
        recipe = VIDEO_RECIPES[source]
        fps = _recipe_fps(request)
        ffmpeg_input = recipe(
            width=request.width,
            height=request.height,
            fps=fps,
            duration_s=request.duration_s,
            seed=request.seed,
        )
        if request.field_order is not None:
            return apply_interlaced_field_order(
                ffmpeg_input,
                field_order=request.field_order,
            )
        if request.vfr_cadence is not None:
            return apply_vfr_cadence(
                ffmpeg_input,
                cadence=request.vfr_cadence,
                duration_s=request.duration_s,
            )
        return ffmpeg_input

    def resolve_audio_input(
        self,
        *,
        source: AudioSource,
        request: AudioSourceRequest,
    ) -> FFmpegInput:
        if source not in AUDIO_RECIPES:
            raise _unsupported_source("audio.source", AUDIO_RECIPES)
        recipe = AUDIO_RECIPES[source]
        return recipe(
            channels=request.channels,
            duration_s=request.duration_s,
            seed=request.seed,
        )

    def capability(
        self, *, ffmpeg_available: bool, hdr_available: bool
    ) -> ContentSourceProviderCapability:
        hdr_sources = HDR_CAPABILITY_SOURCES if hdr_available else ()
        return _builtin_capability(
            ffmpeg_available=ffmpeg_available,
            sources=[
                *(f"audio:{source.value}" for source in self.audio_source_keys),
                *(f"video:{source.value}" for source in self.video_source_keys),
                *VFR_CAPABILITY_SOURCES,
                *INTERLACED_CAPABILITY_SOURCES,
                *COLOR_SPACE_CAPABILITY_SOURCES,
                *COLOR_RANGE_CAPABILITY_SOURCES,
                *hdr_sources,
            ],
        )


_BUILTIN_PROVIDER: Final[ContentSourceProvider] = _BuiltinLavfiProvider()
_VIDEO_PROVIDERS: Final[dict[VideoSource, ContentSourceProvider]] = {
    source: _BUILTIN_PROVIDER for source in VIDEO_RECIPES
}
_AUDIO_PROVIDERS: Final[dict[AudioSource, ContentSourceProvider]] = {
    source: _BUILTIN_PROVIDER for source in AUDIO_RECIPES
}


def resolve_video_source(source: VideoSource, request: VideoSourceRequest) -> SourceResolution:
    """Resolve a video source through the registered provider."""
    provider = _VIDEO_PROVIDERS.get(source)
    if provider is None:
        raise _unsupported_source("video.source", _VIDEO_PROVIDERS)
    return provider.resolve_video(source=source, request=request)


def resolve_audio_source(source: AudioSource, request: AudioSourceRequest) -> SourceResolution:
    """Resolve an audio source through the registered provider."""
    provider = _AUDIO_PROVIDERS.get(source)
    if provider is None:
        raise _unsupported_source("audio.source", _AUDIO_PROVIDERS)
    return provider.resolve_audio(source=source, request=request)


def _recipe_fps(request: VideoSourceRequest) -> int:
    if request.vfr_cadence is not None:
        return VFR_BASE_FPS
    if request.field_order is not None:
        return request.fps * 2
    return request.fps


def resolve_video_input(source: VideoSource, request: VideoSourceRequest) -> FFmpegInput:
    """Resolve a video source through the registered provider without evidence."""
    provider = _VIDEO_PROVIDERS.get(source)
    if provider is None:
        raise _unsupported_source("video.source", _VIDEO_PROVIDERS)
    return provider.resolve_video_input(source=source, request=request)


def resolve_audio_input(source: AudioSource, request: AudioSourceRequest) -> FFmpegInput:
    """Resolve an audio source through the registered provider without evidence."""
    provider = _AUDIO_PROVIDERS.get(source)
    if provider is None:
        raise _unsupported_source("audio.source", _AUDIO_PROVIDERS)
    return provider.resolve_audio_input(source=source, request=request)


def collect_content_source_capabilities(
    ffmpeg_available: bool, *, hdr_available: bool = False
) -> ContentSourceCapabilities:
    """Collect content-source capabilities for all registered providers."""
    return ContentSourceCapabilities(
        providers=[
            _BUILTIN_PROVIDER.capability(
                ffmpeg_available=ffmpeg_available,
                hdr_available=hdr_available,
            )
        ],
    )


def _builtin_evidence(
    *,
    source: VideoSource | AudioSource,
    track_kind: ContentTrackKind,
    request: VideoSourceRequest | AudioSourceRequest,
    ffmpeg_input: FFmpegInput,
) -> ContentSourceEvidence:
    return ContentSourceEvidence(
        asset_id=request.asset_id,
        track_kind=track_kind,
        source=source.value,
        provider=PROVIDER_NAME,
        recipe_digest=_recipe_digest(
            source=source,
            track_kind=track_kind,
            request=request,
            ffmpeg_input=ffmpeg_input,
        ),
        color_space=(request.color_space if isinstance(request, VideoSourceRequest) else None),
        color_range=(request.color_range if isinstance(request, VideoSourceRequest) else None),
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


def _unsupported_source(
    field: str,
    supported: Iterable[VideoSource | AudioSource],
) -> UnsupportedMaterializationError:
    return UnsupportedMaterializationError(
        f"{field} is not supported",
        field=field,
        payload={"supported": sorted(source.value for source in supported)},
    )


def _recipe_digest(
    *,
    source: VideoSource | AudioSource,
    track_kind: ContentTrackKind,
    request: VideoSourceRequest | AudioSourceRequest,
    ffmpeg_input: FFmpegInput,
) -> str:
    payload = {
        "ffmpeg_input": _ffmpeg_input_payload(ffmpeg_input),
        "provider": PROVIDER_NAME,
        "request": _request_payload(source=source, track_kind=track_kind, request=request),
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return f"sha256:{hashlib.sha256(serialized).hexdigest()}"


def _request_payload(
    *,
    source: VideoSource | AudioSource,
    track_kind: ContentTrackKind,
    request: VideoSourceRequest | AudioSourceRequest,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "asset_id": request.asset_id,
        "track_kind": track_kind.value,
        "track_index": request.track_index,
        "source": source.value,
        "seed": request.seed,
        "duration_s": request.duration_s,
    }
    if isinstance(request, VideoSourceRequest):
        payload.update(
            {
                "width": request.width,
                "height": request.height,
                "fps": request.fps,
                "vfr_cadence": (None if request.vfr_cadence is None else request.vfr_cadence.value),
                "field_order": (None if request.field_order is None else request.field_order.value),
                "color_space": (None if request.color_space is None else request.color_space.value),
                "color_range": (None if request.color_range is None else request.color_range.value),
                "hdr_mode": (None if request.hdr_mode is None else request.hdr_mode.value),
                "channels": None,
            }
        )
    else:
        payload.update(
            {
                "width": None,
                "height": None,
                "fps": None,
                "channels": request.channels,
            }
        )
    return payload


def _ffmpeg_input_payload(ffmpeg_input: FFmpegInput) -> dict[str, object]:
    payload: dict[str, object] = {"extra_flags": list(ffmpeg_input.extra_flags)}
    if ffmpeg_input.lavfi is not None:
        payload["kind"] = "lavfi"
        payload["lavfi"] = ffmpeg_input.lavfi
        return payload
    if ffmpeg_input.file_path is not None:
        payload["kind"] = "file_path"
        payload["file_name"] = ffmpeg_input.file_path.name
        return payload
    raise ValueError("FFmpegInput requires lavfi or file_path")
