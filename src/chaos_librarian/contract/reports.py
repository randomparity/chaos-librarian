"""Per-entity report schemas (adapter-facing contract).

Reports are emitted by ``plan`` and ``step`` into ``<run-dir>/reports/``
as four parallel sub-trees (``assets/``, ``works/``, ``variants/``,
``bundles/``). External consumers (voom-v2) key on ``schema_version`` and
load the matching exported schema.

Asset reports carry content hashes, probed media facts, a typed
projection of filesystem-affecting events, and a typed projection of
version-affecting events at ``schema_version: 6``; the other three
entity reports remain at ``schema_version: 1`` because they describe
manifest topology only.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.profiles import CorruptionRecord
from chaos_librarian.contract.scenario import TimelineActionName


class AssetSnapshot(BaseModel):
    """A point-in-time view of one asset's location + version binding."""

    model_config = ConfigDict(extra="forbid")

    location_path: str | None  # None if the asset is currently deleted
    version_id: str
    version_index: int
    content_hash: str | None = None
    probed: ProbedMedia | None = None
    corruption: CorruptionRecord | None = None


class AssetHistoryEntry(BaseModel):
    """One journal event that targets this asset, verbatim."""

    model_config = ConfigDict(extra="forbid")

    logical_time_ns: int
    event_id: str
    action: str
    state_delta: dict[str, object]


class PathHistoryEntry(BaseModel):
    """One filesystem-affecting event projected for a single asset.

    Derived from the journal by ``derive_path_history``. Mirrors the
    verbatim ``AssetHistoryEntry`` but flattens the path-bearing
    ``state_delta`` keys into typed ``str | None`` fields so external
    consumers (voom-v2 adapter) can read them without parsing dicts.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: TimelineActionName
    logical_time_ns: int
    from_path: str | None = None
    to_path: str | None = None
    temp_path: str | None = None


class VersionHistoryEntry(BaseModel):
    """One version-affecting journal event projected for a single asset.

    Derived from the journal by ``derive_version_history``. Mirrors
    Sprint 6's ``PathHistoryEntry`` shape for the version-allocating
    subset of actions (reencode_video / reencode_audio / remux_container
    / edit_metadata / embed_subtitle). ``extract_subtitle`` does NOT
    appear here — it's a read-only extract that allocates a sidecar but
    not a version.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str
    action: TimelineActionName
    logical_time_ns: int
    input_version_id: str | None = None
    output_version_id: str | None = None
    state_delta_summary: dict[str, object] = Field(default_factory=dict)


class AssetReport(BaseModel):
    """Per-asset history report — initial snapshot, ordered history, current snapshot.

    ``current`` is ``None`` if the asset has been deleted; ``history``
    still includes the ``delete_file`` entry in that case.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[6]
    asset_id: str
    initial: AssetSnapshot
    history: list[AssetHistoryEntry] = Field(default_factory=list)
    current: AssetSnapshot | None
    path_history: list[PathHistoryEntry] = Field(default_factory=list)
    version_history: list[VersionHistoryEntry] = Field(default_factory=list)


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
