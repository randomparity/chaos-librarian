"""Video and audio content-source resolution."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceEvidence,
    ContentTrackKind,
)
from chaos_librarian.contract.scenario import (
    AudioNoiseColor,
    AudioSampleFormat,
    AudioSource,
    VideoColorRange,
    VideoColorSpace,
    VideoFieldOrder,
    VideoHdrMode,
    VideoResolutionSequence,
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
    recipe_noise,
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
    AudioSource.NOISE: recipe_noise,
}


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
    resolution_sequence: VideoResolutionSequence | None = None
    track_index: None = None


@dataclass(frozen=True, slots=True)
class AudioSourceRequest:
    asset_id: str
    track_index: int
    seed: int
    duration_s: float
    channels: str
    noise_color: AudioNoiseColor | None = None
    sample_rate: int = 48000
    sample_format: AudioSampleFormat | None = None


@dataclass(frozen=True, slots=True)
class SourceResolution:
    ffmpeg_input: FFmpegInput
    evidence: ContentSourceEvidence


def resolve_video_source(source: VideoSource, request: VideoSourceRequest) -> SourceResolution:
    """Resolve a video source to an FFmpeg input plus replay evidence."""
    ffmpeg_input = resolve_video_input(source=source, request=request)
    return SourceResolution(
        ffmpeg_input=ffmpeg_input,
        evidence=_builtin_evidence(
            source=source,
            track_kind=ContentTrackKind.VIDEO,
            request=request,
            ffmpeg_input=ffmpeg_input,
        ),
    )


def resolve_audio_source(source: AudioSource, request: AudioSourceRequest) -> SourceResolution:
    """Resolve an audio source to an FFmpeg input plus replay evidence."""
    ffmpeg_input = resolve_audio_input(source=source, request=request)
    return SourceResolution(
        ffmpeg_input=ffmpeg_input,
        evidence=_builtin_evidence(
            source=source,
            track_kind=ContentTrackKind.AUDIO,
            request=request,
            ffmpeg_input=ffmpeg_input,
        ),
    )


def resolve_video_input(source: VideoSource, request: VideoSourceRequest) -> FFmpegInput:
    """Resolve a video source to an FFmpeg input without replay evidence."""
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
    ffmpeg_input = recipe(
        width=request.width,
        height=request.height,
        fps=_recipe_fps(request),
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


def resolve_audio_input(source: AudioSource, request: AudioSourceRequest) -> FFmpegInput:
    """Resolve an audio source to an FFmpeg input without replay evidence."""
    if source not in AUDIO_RECIPES:
        raise _unsupported_source("audio.source", AUDIO_RECIPES)
    recipe = AUDIO_RECIPES[source]
    return recipe(
        channels=request.channels,
        duration_s=request.duration_s,
        seed=request.seed,
        noise_color=request.noise_color,
        sample_rate=request.sample_rate,
        sample_format=request.sample_format,
    )


def _recipe_fps(request: VideoSourceRequest) -> int:
    if request.vfr_cadence is not None:
        return VFR_BASE_FPS
    if request.field_order is not None:
        return request.fps * 2
    return request.fps


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
        resolution_sequence=(
            request.resolution_sequence if isinstance(request, VideoSourceRequest) else None
        ),
        noise_color=(request.noise_color if isinstance(request, AudioSourceRequest) else None),
        sample_rate=(request.sample_rate if isinstance(request, AudioSourceRequest) else None),
        sample_format=(request.sample_format if isinstance(request, AudioSourceRequest) else None),
        track_index=request.track_index,
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
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
                "resolution_sequence": (
                    None
                    if request.resolution_sequence is None
                    else request.resolution_sequence.value
                ),
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
                "noise_color": None if request.noise_color is None else request.noise_color.value,
                "sample_rate": request.sample_rate,
                "sample_format": None
                if request.sample_format is None
                else request.sample_format.value,
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
