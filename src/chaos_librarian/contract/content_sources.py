"""Content-source capability and replay-evidence contract models."""

from __future__ import annotations

import enum

from pydantic import BaseModel, ConfigDict, Field

SHA256_URI_PATTERN = r"^sha256:[0-9a-f]{64}$"


class ContentTrackKind(enum.StrEnum):
    """Track family a content source resolved."""

    VIDEO = "video"
    AUDIO = "audio"
    SUBTITLE = "subtitle"


class CacheDisposition(enum.StrEnum):
    """How a provider used the content-source cache for one resolution."""

    NOT_CACHEABLE = "not_cacheable"
    HIT = "hit"
    MISS_STORED = "miss_stored"


class ContentSourceEvidence(BaseModel):
    """Replay evidence for one resolved content source."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    track_kind: ContentTrackKind
    source: str
    provider: str
    recipe_digest: str = Field(pattern=SHA256_URI_PATTERN)
    track_index: int | None = Field(default=None, ge=0)
    cache_disposition: CacheDisposition
    cache_key: str | None = Field(default=None, pattern=SHA256_URI_PATTERN)
    content_hash: str | None = Field(default=None, pattern=SHA256_URI_PATTERN)
    origin_uri: str | None = None
    license: str | None = None


class ContentSourceProviderCapability(BaseModel):
    """Capability report for one registered content-source provider."""

    model_config = ConfigDict(extra="forbid")

    name: str
    available: bool
    requires_network: bool
    requires_cache: bool
    required_tool: str | None = None
    cache_dir: str | None = None
    cache_writable: bool | None = None
    reason: str | None = None
    sources: tuple[str, ...] = Field(default_factory=tuple)


class ContentSourceCapabilities(BaseModel):
    """All registered content-source providers visible to capabilities."""

    model_config = ConfigDict(extra="forbid")

    providers: list[ContentSourceProviderCapability] = Field(default_factory=list)
