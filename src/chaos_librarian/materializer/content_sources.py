"""Content-source resolution used by Phase-A synthesis."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Final

from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceCapabilities,
    ContentSourceEvidence,
    ContentSourceProviderCapability,
    ContentTrackKind,
)
from chaos_librarian.contract.scenario import (
    AudioNoiseColor,
    AudioSampleFormat,
    AudioSource,
    EmbeddedChapters,
    EmbeddedCoverArt,
    MatroskaMuxingProfile,
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
from chaos_librarian.media_matrix import SUPPORTED_AUDIO_SAMPLE_RATES

FPS_DEFAULT: Final = 24
RESOLUTION_PIXELS: Final[dict[str, tuple[int, int]]] = {
    "sd": (640, 480),
    "hd": (1280, 720),
    "1080p": (1920, 1080),
}
# ffmpeg lavfi geometry for generated cover art; matches CoverArtResolution.SQUARE_320.
COVER_ART_SIZE: Final = "320x320"
PROVIDER_NAME: Final = "builtin-lavfi"
CHAPTER_PROVIDER_NAME: Final = "builtin-chapters"
COVER_ART_PROVIDER_NAME: Final = "builtin-cover-art"
MUXING_PROVIDER_NAME: Final = "builtin-mkvmerge"

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
AUDIO_NOISE_CAPABILITY_SOURCES: Final[tuple[str, ...]] = tuple(
    f"audio:noise:{color.value}" for color in AudioNoiseColor
)
AUDIO_SAMPLE_RATE_CAPABILITY_SOURCES: Final[tuple[str, ...]] = tuple(
    f"audio:sample_rate:{rate}" for rate in SUPPORTED_AUDIO_SAMPLE_RATES
)
AUDIO_SAMPLE_FORMAT_CAPABILITY_SOURCES: Final[tuple[str, ...]] = tuple(
    f"audio:sample_format:{sample_format.value}" for sample_format in AudioSampleFormat
)
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
RESOLUTION_SEQUENCE_CAPABILITY_SOURCES: Final[tuple[str, ...]] = tuple(
    f"video:resolution_sequence:{sequence.value}" for sequence in VideoResolutionSequence
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
class ChapterSpec:
    index: int
    start_ms: int
    end_ms: int
    title: str


@dataclass(frozen=True, slots=True)
class ChapterSourceRequest:
    asset_id: str
    seed: int
    duration_s: float
    chapters: EmbeddedChapters


@dataclass(frozen=True, slots=True)
class CoverArtSourceRequest:
    asset_id: str
    seed: int
    cover_art: EmbeddedCoverArt


@dataclass(frozen=True, slots=True)
class MuxingSourceRequest:
    asset_id: str
    seed: int
    container: str
    profile: MatroskaMuxingProfile


@dataclass(frozen=True, slots=True)
class SourceResolution:
    ffmpeg_input: FFmpegInput
    evidence: ContentSourceEvidence


@dataclass(frozen=True, slots=True)
class ChapterSourceResolution:
    chapters: tuple[ChapterSpec, ...]
    evidence: ContentSourceEvidence


@dataclass(frozen=True, slots=True)
class CoverArtSourceResolution:
    color: str
    evidence: ContentSourceEvidence


@dataclass(frozen=True, slots=True)
class MuxingSourceResolution:
    deterministic_seed: int
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


def resolve_chapter_source(request: ChapterSourceRequest) -> ChapterSourceResolution:
    """Resolve deterministic embedded chapters plus replay evidence."""
    chapters = _chapter_specs(request)
    evidence = ContentSourceEvidence(
        asset_id=request.asset_id,
        track_kind=ContentTrackKind.CHAPTERS,
        source="even",
        provider=CHAPTER_PROVIDER_NAME,
        recipe_digest=_chapter_recipe_digest(request=request, chapters=chapters),
        chapter_count=request.chapters.count,
        chapter_title_prefix=request.chapters.title_prefix,
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
    )
    return ChapterSourceResolution(chapters=chapters, evidence=evidence)


def resolve_cover_art_source(request: CoverArtSourceRequest) -> CoverArtSourceResolution:
    """Resolve deterministic embedded cover art color plus replay evidence."""
    color = _cover_art_color(request)
    evidence = ContentSourceEvidence(
        asset_id=request.asset_id,
        track_kind=ContentTrackKind.COVER_ART,
        source=request.cover_art.source.value,
        provider=COVER_ART_PROVIDER_NAME,
        recipe_digest=_cover_art_recipe_digest(request=request, color=color),
        cover_art_image_format=request.cover_art.image_format,
        cover_art_resolution=request.cover_art.resolution,
        cover_art_color=color,
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
    )
    return CoverArtSourceResolution(color=color, evidence=evidence)


def resolve_muxing_source(request: MuxingSourceRequest) -> MuxingSourceResolution:
    """Resolve deterministic mkvmerge profile evidence."""
    deterministic_seed = _muxing_deterministic_seed(request)
    evidence = ContentSourceEvidence(
        asset_id=request.asset_id,
        track_kind=ContentTrackKind.MUXING,
        source=request.profile.value,
        provider=MUXING_PROVIDER_NAME,
        recipe_digest=_muxing_recipe_digest(
            request=request,
            deterministic_seed=deterministic_seed,
        ),
        matroska_muxing_profile=request.profile,
        container=request.container,
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
    )
    return MuxingSourceResolution(deterministic_seed=deterministic_seed, evidence=evidence)


def _recipe_fps(request: VideoSourceRequest) -> int:
    if request.vfr_cadence is not None:
        return VFR_BASE_FPS
    if request.field_order is not None:
        return request.fps * 2
    return request.fps


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


def collect_content_source_capabilities(
    ffmpeg_available: bool,
    *,
    hdr_available: bool = False,
    resolution_sequence_available: bool = False,
    audio_recipes_available: bool = False,
) -> ContentSourceCapabilities:
    """Collect built-in content-source capabilities for the current host."""
    return ContentSourceCapabilities(
        providers=[
            _builtin_capability(
                ffmpeg_available=ffmpeg_available,
                sources=_builtin_capability_sources(
                    hdr_available=hdr_available,
                    resolution_sequence_available=resolution_sequence_available,
                    audio_recipes_available=audio_recipes_available,
                ),
            )
        ],
    )


def _builtin_capability_sources(
    *,
    hdr_available: bool,
    resolution_sequence_available: bool,
    audio_recipes_available: bool,
) -> list[str]:
    hdr_sources = HDR_CAPABILITY_SOURCES if hdr_available else ()
    resolution_sequence_sources = (
        RESOLUTION_SEQUENCE_CAPABILITY_SOURCES if resolution_sequence_available else ()
    )
    audio_recipe_sources = (
        (
            f"audio:{AudioSource.NOISE.value}",
            *AUDIO_NOISE_CAPABILITY_SOURCES,
            *AUDIO_SAMPLE_RATE_CAPABILITY_SOURCES,
            *AUDIO_SAMPLE_FORMAT_CAPABILITY_SOURCES,
        )
        if audio_recipes_available
        else ()
    )
    return [
        *(f"audio:{source.value}" for source in AUDIO_RECIPES if source is not AudioSource.NOISE),
        *audio_recipe_sources,
        *(f"video:{source.value}" for source in VIDEO_RECIPES),
        *VFR_CAPABILITY_SOURCES,
        *INTERLACED_CAPABILITY_SOURCES,
        *COLOR_SPACE_CAPABILITY_SOURCES,
        *COLOR_RANGE_CAPABILITY_SOURCES,
        *hdr_sources,
        *resolution_sequence_sources,
    ]


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


def _chapter_specs(request: ChapterSourceRequest) -> tuple[ChapterSpec, ...]:
    duration_ms = round(request.duration_s * 1000)
    if duration_ms < request.chapters.count:
        raise UnsupportedMaterializationError(
            "embedded_chapters.count requires at least one millisecond per chapter",
            field="embedded_chapters.count",
            asset_id=request.asset_id,
            payload={"duration_ms": duration_ms, "count": request.chapters.count},
        )
    specs: list[ChapterSpec] = []
    for index in range(request.chapters.count):
        start_ms = round(index * duration_ms / request.chapters.count)
        end_ms = round((index + 1) * duration_ms / request.chapters.count)
        specs.append(
            ChapterSpec(
                index=index,
                start_ms=start_ms,
                end_ms=end_ms,
                title=_chapter_title(request=request, index=index),
            )
        )
    return tuple(specs)


def _chapter_title(*, request: ChapterSourceRequest, index: int) -> str:
    payload = {
        "asset_id": request.asset_id,
        "index": index,
        "seed": request.seed,
        "title_prefix": request.chapters.title_prefix,
    }
    suffix = _sha256_hex(payload)[:6]
    return f"{request.chapters.title_prefix} {index + 1:02d} {suffix}"


def _cover_art_color(request: CoverArtSourceRequest) -> str:
    payload = {
        "asset_id": request.asset_id,
        "image_format": request.cover_art.image_format.value,
        "resolution": request.cover_art.resolution.value,
        "seed": request.seed,
        "source": request.cover_art.source.value,
    }
    return f"#{_sha256_hex(payload)[:6]}"


def _muxing_deterministic_seed(request: MuxingSourceRequest) -> int:
    payload = {
        "asset_id": request.asset_id,
        "container": request.container,
        "profile": request.profile.value,
        "provider": MUXING_PROVIDER_NAME,
        "seed": request.seed,
    }
    return int(_sha256_hex(payload)[:8], 16)


def _chapter_recipe_digest(
    *,
    request: ChapterSourceRequest,
    chapters: tuple[ChapterSpec, ...],
) -> str:
    payload = {
        "chapters": [
            {
                "end_ms": chapter.end_ms,
                "index": chapter.index,
                "start_ms": chapter.start_ms,
                "title": chapter.title,
            }
            for chapter in chapters
        ],
        "provider": CHAPTER_PROVIDER_NAME,
        "request": {
            "asset_id": request.asset_id,
            "count": request.chapters.count,
            "duration_s": request.duration_s,
            "seed": request.seed,
            "title_prefix": request.chapters.title_prefix,
            "track_kind": ContentTrackKind.CHAPTERS.value,
        },
    }
    return f"sha256:{_sha256_hex(payload)}"


def _cover_art_recipe_digest(*, request: CoverArtSourceRequest, color: str) -> str:
    payload = {
        "color": color,
        "provider": COVER_ART_PROVIDER_NAME,
        "request": {
            "asset_id": request.asset_id,
            "image_format": request.cover_art.image_format.value,
            "resolution": request.cover_art.resolution.value,
            "seed": request.seed,
            "source": request.cover_art.source.value,
            "track_kind": ContentTrackKind.COVER_ART.value,
        },
    }
    return f"sha256:{_sha256_hex(payload)}"


def _muxing_recipe_digest(
    *,
    request: MuxingSourceRequest,
    deterministic_seed: int,
) -> str:
    payload = {
        "deterministic_seed": deterministic_seed,
        "provider": MUXING_PROVIDER_NAME,
        "request": {
            "asset_id": request.asset_id,
            "container": request.container,
            "profile": request.profile.value,
            "seed": request.seed,
            "track_kind": ContentTrackKind.MUXING.value,
        },
    }
    return f"sha256:{_sha256_hex(payload)}"


def _sha256_hex(payload: object) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()


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
