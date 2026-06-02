"""Embedded chapter and cover-art content-source resolution."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Final

from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceEvidence,
    ContentTrackKind,
)
from chaos_librarian.contract.scenario import EmbeddedChapters, EmbeddedCoverArt
from chaos_librarian.materializer.errors import UnsupportedMaterializationError

# ffmpeg lavfi geometry for generated cover art; matches CoverArtResolution.SQUARE_320.
COVER_ART_SIZE: Final = "320x320"
CHAPTER_PROVIDER_NAME: Final = "builtin-chapters"
COVER_ART_PROVIDER_NAME: Final = "builtin-cover-art"


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
class ChapterSourceResolution:
    chapters: tuple[ChapterSpec, ...]
    evidence: ContentSourceEvidence


@dataclass(frozen=True, slots=True)
class CoverArtSourceResolution:
    color: str
    evidence: ContentSourceEvidence


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


def _sha256_hex(payload: object) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(serialized).hexdigest()
