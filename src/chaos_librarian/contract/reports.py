"""Per-entity report schemas (adapter-facing contract).

Sprint 4 reports are derived purely from manifest + journal data. They do
NOT carry content hashes or probed media facts — those land in Sprint 5
under ``schema_version: 2`` (per the project-wide field-add rule).

Reports are emitted by ``plan`` and ``step`` into ``<run-dir>/reports/``
as four parallel sub-trees (``assets/``, ``works/``, ``variants/``,
``bundles/``). External consumers (voom-v2) key on ``schema_version`` and
load the matching exported schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssetSnapshot(BaseModel):
    """A point-in-time view of one asset's location + version binding."""

    model_config = ConfigDict(extra="forbid")

    location_path: str | None  # None if the asset is currently deleted
    version_id: str
    version_index: int


class AssetHistoryEntry(BaseModel):
    """One journal event that targets this asset, verbatim."""

    model_config = ConfigDict(extra="forbid")

    logical_time_ns: int
    event_id: str
    action: str
    state_delta: dict[str, object]


class AssetReport(BaseModel):
    """Per-asset history report — initial snapshot, ordered history, current snapshot.

    ``current`` is ``None`` if the asset has been deleted; ``history``
    still includes the ``delete_file`` entry in that case.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    asset_id: str
    initial: AssetSnapshot
    history: list[AssetHistoryEntry] = Field(default_factory=list)
    current: AssetSnapshot | None


class WorkReport(BaseModel):
    """Per-work report — variants + transitive asset ids."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    work_id: str
    title: str
    variant_ids: list[str]
    asset_ids: list[str]


class VariantReport(BaseModel):
    """Per-variant report — owning work, bundle, member assets."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    variant_id: str
    work_id: str
    label: str
    bundle_id: str
    asset_ids: list[str]


class BundleReport(BaseModel):
    """Per-bundle report — owning variant, member assets, currently-bound sidecars."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    bundle_id: str
    variant_id: str
    asset_ids: list[str]
    sidecar_ids: list[str] = Field(default_factory=list)
