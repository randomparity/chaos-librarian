"""Content-source capability reporting."""

from __future__ import annotations

from typing import Final

from chaos_librarian.contract.content_sources import (
    ContentSourceCapabilities,
    ContentSourceProviderCapability,
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
    VideoVfrCadence,
)
from chaos_librarian.materializer.content.media_sources import (
    AUDIO_RECIPES,
    PROVIDER_NAME,
    VIDEO_RECIPES,
)
from chaos_librarian.media_matrix import SUPPORTED_AUDIO_SAMPLE_RATES

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
