"""Per-entity report schemas (adapter-facing contract).

Reports are emitted by ``plan`` and ``step`` into ``<run-dir>/reports/`` as
parallel entity sub-trees. External consumers (voom-v2) key on
``schema_version`` and load the matching exported schema.

Asset reports carry content hashes, probed media facts, a typed
projection of filesystem-affecting events, and a typed projection of
version-affecting events at ``schema_version: 7``; hierarchy reports
start at ``schema_version: 1`` because they describe manifest topology
only.
"""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from chaos_librarian.contract.domain import ParentKind
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

    schema_version: Literal[7]
    asset_id: str
    parent_kind: ParentKind
    parent_id: str
    movie_id: str | None = None
    series_id: str | None = None
    season_id: str | None = None
    episode_id: str | None = None
    artist_id: str | None = None
    album_id: str | None = None
    disc_id: str | None = None
    track_id: str | None = None
    variant_id: str
    bundle_id: str
    initial: AssetSnapshot
    history: list[AssetHistoryEntry] = Field(default_factory=list)
    current: AssetSnapshot | None
    path_history: list[PathHistoryEntry] = Field(default_factory=list)
    version_history: list[VersionHistoryEntry] = Field(default_factory=list)


class MovieReport(BaseModel):
    """Per-movie report — variants + transitive asset ids."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    movie_id: str
    title: str
    variant_ids: list[str]
    asset_ids: list[str]


class SeriesReport(BaseModel):
    """Per-series report — seasons, episodes, and transitive asset ids."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    series_id: str
    title: str
    season_ids: list[str]
    episode_ids: list[str]
    asset_ids: list[str]


class SeasonReport(BaseModel):
    """Per-season report — episodes and transitive asset ids."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    season_id: str
    series_id: str
    season_number: int
    title: str
    episode_ids: list[str]
    asset_ids: list[str]


class EpisodeReport(BaseModel):
    """Per-episode report — variants + transitive asset ids."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    episode_id: str
    season_id: str
    episode_number: int
    title: str
    aired_on: date | None = None
    absolute_number: int | None = None
    variant_ids: list[str]
    asset_ids: list[str]


class ArtistReport(BaseModel):
    """Per-artist report — albums, tracks, and transitive asset ids."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    artist_id: str
    name: str
    album_ids: list[str]
    track_ids: list[str]
    asset_ids: list[str]


class AlbumReport(BaseModel):
    """Per-album report — discs, tracks, and transitive asset ids."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    album_id: str
    artist_id: str
    title: str
    release_year: int | None = None
    disc_ids: list[str]
    track_ids: list[str]
    asset_ids: list[str]


class DiscReport(BaseModel):
    """Per-disc report — tracks and transitive asset ids."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    disc_id: str
    album_id: str
    disc_number: int
    track_ids: list[str]
    asset_ids: list[str]


class TrackReport(BaseModel):
    """Per-track report — variants + transitive asset ids."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    track_id: str
    disc_id: str
    track_number: int
    title: str
    performers: list[str]
    variant_ids: list[str]
    asset_ids: list[str]


class VariantReport(BaseModel):
    """Per-variant report — owning hierarchy parent, bundle, member assets."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    variant_id: str
    parent_kind: ParentKind
    parent_id: str
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
