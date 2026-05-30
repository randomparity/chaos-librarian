"""Manifest schema: current expected library state.

Describes external library reality (hierarchy rows, variants, bundles,
assets, locations, etc.). Does NOT describe application policy outcomes.
"""

from __future__ import annotations

import enum
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.patterns import SHA256_URI_PATTERN
from chaos_librarian.contract.profiles import CorruptionRecord


class StreamKind(enum.StrEnum):
    """Kind of a probed media stream."""

    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"


class ProbedChapter(BaseModel):
    """One chapter from ``ffprobe -show_chapters``."""

    model_config = ConfigDict(extra="forbid")

    index: int = Field(ge=0)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(ge=0)
    title: str | None = None


class ProbedStream(BaseModel):
    """One stream from ``ffprobe -show_streams``.

    Optional fields are populated only for the matching ``kind``; ffprobe
    silently omits the others, and ``exclude_none=True`` keeps the serialized
    output compact.
    """

    model_config = ConfigDict(extra="forbid")

    kind: StreamKind
    codec: str
    language: str | None = None
    width: int | None = None  # video-only
    height: int | None = None  # video-only
    fps: float | None = None  # video-only
    channels: int | None = None  # audio-only
    channel_layout: str | None = None  # audio-only
    sample_rate: int | None = None  # audio-only
    title: str | None = None  # stream metadata
    role: str | None = None  # audio-only stream metadata
    attached_pic: bool | None = None  # video-only
    default: bool | None = None  # subtitle-only
    forced: bool | None = None  # subtitle-only


class ProbedMedia(BaseModel):
    """Output of ``ffprobe`` mapped into a model."""

    model_config = ConfigDict(extra="forbid")

    container: str
    duration_seconds: float
    size_bytes: int
    streams: list[ProbedStream]
    chapters: list[ProbedChapter] = Field(default_factory=list)


class ManifestMovie(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    layout: str


class ManifestSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    layout: str
    episode_naming: str


class ManifestSeason(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    series_id: str
    season_number: int
    title: str


class ManifestEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    season_id: str
    episode_number: int
    title: str
    aired_on: date | None = None
    absolute_number: int | None = None


class ManifestArtist(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    name: str
    layout: str
    track_naming: str


class ManifestAlbum(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    artist_id: str
    title: str
    release_year: int | None = None


class ManifestDisc(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    album_id: str
    disc_number: int


class ManifestTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    disc_id: str
    track_number: int
    title: str
    performers: list[str] = Field(default_factory=list)


class ManifestVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    parent_kind: ParentKind
    parent_id: str
    label: str


class ManifestBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    variant_id: str


class ManifestAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    bundle_id: str
    role: str
    container: str
    duration_seconds: float


class ManifestVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    asset_id: str
    index: int
    content_hash: str | None = Field(default=None, pattern=SHA256_URI_PATTERN)
    probed: ProbedMedia | None = None
    corruption: CorruptionRecord | None = None


class ManifestLocation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    asset_id: str
    path: str
    # Multi-phase in-flight state, set between *_start and *_commit events.
    temp_path: str | None = None
    bytes_written: int | None = None


class ManifestSidecar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    asset_id: str
    kind: str
    path: str
    # Optional from manifest v4 (Sprint 7): poster / NFO sidecars carry
    # no language. Subtitle sidecars still always carry one — enforced
    # at the scenario layer by CreateSidecarEvent.model_validator and at
    # the materializer layer by per-handler defaults.
    language: str | None = None
    content_hash: str | None = Field(default=None, pattern=SHA256_URI_PATTERN)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[9]
    movies: list[ManifestMovie]
    series: list[ManifestSeries]
    seasons: list[ManifestSeason]
    episodes: list[ManifestEpisode]
    artists: list[ManifestArtist]
    albums: list[ManifestAlbum]
    discs: list[ManifestDisc]
    tracks: list[ManifestTrack]
    variants: list[ManifestVariant]
    bundles: list[ManifestBundle]
    assets: list[ManifestAsset]
    versions: list[ManifestVersion]
    locations: list[ManifestLocation]
    sidecars: list[ManifestSidecar] = Field(default_factory=list)
