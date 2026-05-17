"""Manifest schema: current expected library state.

Describes external library reality (works/variants/bundles/assets/locations
etc.). Does NOT describe application policy outcomes.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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
    content_hash: str | None = None


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


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    works: list[ManifestWork]
    variants: list[ManifestVariant]
    bundles: list[ManifestBundle]
    assets: list[ManifestAsset]
    versions: list[ManifestVersion]
    locations: list[ManifestLocation]
    sidecars: list[ManifestSidecar] = Field(default_factory=list)
