"""Manifest schema: current expected library state.

Describes external library reality (works/variants/bundles/assets/locations
etc.). Does NOT describe application policy outcomes.
"""

from __future__ import annotations

import enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StreamKind(enum.StrEnum):
    """Kind of a probed media stream."""

    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"


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
    sample_rate: int | None = None  # audio-only
    default: bool | None = None  # subtitle-only
    forced: bool | None = None  # subtitle-only


class ProbedMedia(BaseModel):
    """Output of ``ffprobe -show_format -show_streams`` mapped into a model."""

    model_config = ConfigDict(extra="forbid")

    container: str
    duration_seconds: float
    size_bytes: int
    streams: list[ProbedStream]


class ManifestWork(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str


class ManifestVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    work_id: str
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
    content_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    probed: ProbedMedia | None = None


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
    # Language tag (e.g. "en", "eng", "fr"), required from manifest v3.
    # Every producer carries one: materializer takes it from the
    # scenario's subtitle declarations, and the engine's ``create_sidecar``
    # handler reads ``event.language`` (required from scenario v3). The
    # ``(asset_id, language)`` pair is the lookup key in
    # ``_find_sidecar_for`` and replaces a path-substring match that
    # mis-resolved when two language tags collided as substrings of each
    # other (e.g. "en"/"eng").
    language: str
    content_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[3]
    works: list[ManifestWork]
    variants: list[ManifestVariant]
    bundles: list[ManifestBundle]
    assets: list[ManifestAsset]
    versions: list[ManifestVersion]
    locations: list[ManifestLocation]
    sidecars: list[ManifestSidecar] = Field(default_factory=list)
