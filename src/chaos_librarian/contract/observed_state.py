"""Consumer-exported observed-state contract for adapter comparisons."""

from __future__ import annotations

import enum
import uuid
from collections.abc import Sequence
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator, model_validator

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.patterns import SHA256_URI_PATTERN


class ObservedAction(enum.StrEnum):
    """Path-affecting action vocabulary accepted from consumers."""

    MOVE_ASSET = "move_asset"
    RENAME_FILE = "rename_file"
    DELETE_FILE = "delete_file"
    ADD_FILE = "add_file"
    SLOW_COPY_START = "slow_copy_start"
    SLOW_COPY_COMMIT = "slow_copy_commit"
    ARCHIVE_FILE = "archive_file"
    MOVE_BETWEEN_ROOTS = "move_between_roots"
    RENUMBER_EPISODE = "renumber_episode"
    MOVE_EPISODE_TO_SEASON = "move_episode_to_season"
    RENAME_SEASON = "rename_season"
    RENUMBER_DISC = "renumber_disc"
    MOVE_TRACK_TO_DISC = "move_track_to_disc"


_MOVE_ACTIONS = frozenset(
    {
        ObservedAction.MOVE_ASSET,
        ObservedAction.RENAME_FILE,
        ObservedAction.ARCHIVE_FILE,
        ObservedAction.MOVE_BETWEEN_ROOTS,
        ObservedAction.RENUMBER_EPISODE,
        ObservedAction.MOVE_EPISODE_TO_SEASON,
        ObservedAction.RENAME_SEASON,
        ObservedAction.RENUMBER_DISC,
        ObservedAction.MOVE_TRACK_TO_DISC,
    }
)
_WINDOWS_DRIVE_PREFIX_LENGTH = 2


def _validate_observed_path(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    if value == "" or value.startswith("/") or "\\" in value or "\x00" in value:
        raise ValueError(f"{field_name} must be a relative POSIX path")
    first_segment = value.split("/", 1)[0]
    has_drive_prefix = (
        len(first_segment) == _WINDOWS_DRIVE_PREFIX_LENGTH
        and first_segment[1] == ":"
        and first_segment[0].isalpha()
    )
    if has_drive_prefix:
        raise ValueError(f"{field_name} must not contain a Windows drive prefix")
    if any(part in {"", ".", ".."} for part in value.split("/")):
        raise ValueError(f"{field_name} must not contain empty, dot, or parent segments")
    return value


def _validate_action_paths(
    *,
    action: ObservedAction,
    from_path: str | None,
    to_path: str | None,
    temp_path: str | None,
) -> None:
    if action in _MOVE_ACTIONS and (from_path is None or to_path is None):
        raise ValueError(f"{action.value} requires from_path and to_path")
    if action is ObservedAction.DELETE_FILE and from_path is None:
        raise ValueError("delete_file requires from_path")
    if action is ObservedAction.ADD_FILE and to_path is None:
        raise ValueError("add_file requires to_path")
    if action is ObservedAction.SLOW_COPY_START and (
        from_path is None or to_path is None or temp_path is None
    ):
        raise ValueError("slow_copy_start requires from_path, to_path, and temp_path")
    if action is ObservedAction.SLOW_COPY_COMMIT and to_path is None:
        raise ValueError("slow_copy_commit requires to_path")


def _field_name(info: ValidationInfo) -> str:
    return info.field_name if info.field_name is not None else "path"


def _ensure_unique(values: Sequence[str], *, kind: str) -> None:
    seen: set[str] = set()
    for value in values:
        if value in seen:
            raise ValueError(f"duplicate {kind}: {value}")
        seen.add(value)


class ObservedConsumer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    version: str | None = None


class ObservedSidecar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    kind: str
    path: str
    content_hash: str | None = Field(default=None, pattern=SHA256_URI_PATTERN)

    @field_validator("path")
    @classmethod
    def path_is_relative_posix(cls, value: str, info: ValidationInfo) -> str:
        return _validate_observed_path(value, field_name=_field_name(info)) or value


class ObservedPathHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_event_ref: str | None = None
    related_observed_event_ref: str | None = None
    action: ObservedAction
    observed_at: datetime | None = None
    from_path: str | None = None
    to_path: str | None = None
    temp_path: str | None = None

    @field_validator("from_path", "to_path", "temp_path")
    @classmethod
    def paths_are_relative_posix(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _validate_observed_path(value, field_name=_field_name(info))

    @model_validator(mode="after")
    def action_paths_are_complete(self) -> ObservedPathHistoryEntry:
        _validate_action_paths(
            action=self.action,
            from_path=self.from_path,
            to_path=self.to_path,
            temp_path=self.temp_path,
        )
        return self


class ObservedAsset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    current_path: str | None
    content_hash: str | None = Field(default=None, pattern=SHA256_URI_PATTERN)
    probed: ProbedMedia | None = None
    variant_ref: str | None = None
    bundle_ref: str | None = None
    sidecars: list[ObservedSidecar] = Field(default_factory=list)
    path_history: list[ObservedPathHistoryEntry] = Field(default_factory=list)

    @field_validator("current_path")
    @classmethod
    def current_path_is_relative_posix(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _validate_observed_path(value, field_name=_field_name(info))


class ObservedMovie(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    title: str | None = None


class ObservedSeries(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    title: str | None = None


class ObservedSeason(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    series_ref: str
    season_number: int | None = None
    title: str | None = None


class ObservedEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    season_ref: str
    episode_number: int | None = None
    title: str | None = None
    aired_on: date | None = None
    absolute_number: int | None = None


class ObservedArtist(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    name: str | None = None


class ObservedAlbum(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    artist_ref: str
    title: str | None = None
    release_year: int | None = None


class ObservedDisc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    album_ref: str
    disc_number: int | None = None


class ObservedTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    disc_ref: str
    track_number: int | None = None
    title: str | None = None
    performers: list[str] = Field(default_factory=list)


class ObservedVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    parent_kind: ParentKind
    parent_ref: str
    label: str | None = None


class ObservedBundleSidecarRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ref: str
    sidecar_ref: str


class ObservedBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_ref: str
    variant_ref: str | None = None
    asset_refs: list[str] = Field(default_factory=list)
    sidecar_refs: list[ObservedBundleSidecarRef] = Field(default_factory=list)


class ObservedEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observed_event_ref: str
    related_observed_event_ref: str | None = None
    observed_ref: str | None = None
    before_observed_ref: str | None = None
    after_observed_ref: str | None = None
    action: ObservedAction
    observed_at: datetime | None = None
    path: str | None = None
    from_path: str | None = None
    to_path: str | None = None
    temp_path: str | None = None

    @field_validator("path", "from_path", "to_path", "temp_path")
    @classmethod
    def paths_are_relative_posix(cls, value: str | None, info: ValidationInfo) -> str | None:
        return _validate_observed_path(value, field_name=_field_name(info))

    @model_validator(mode="after")
    def action_paths_and_identity_are_complete(self) -> ObservedEvent:
        _validate_action_paths(
            action=self.action,
            from_path=self.from_path,
            to_path=self.to_path,
            temp_path=self.temp_path,
        )
        has_observed_ref = self.observed_ref is not None
        has_before_after = (
            self.before_observed_ref is not None and self.after_observed_ref is not None
        )
        has_partial_before_after = (
            self.before_observed_ref is not None or self.after_observed_ref is not None
        )
        if has_observed_ref == has_before_after or (has_observed_ref and has_partial_before_after):
            raise ValueError("ObservedEvent requires exactly one identity mode")
        return self


class ObservedState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[4]
    consumer: ObservedConsumer
    run_id: uuid.UUID
    observed_at: datetime
    assets: list[ObservedAsset]
    movies: list[ObservedMovie] = Field(default_factory=list)
    series: list[ObservedSeries] = Field(default_factory=list)
    seasons: list[ObservedSeason] = Field(default_factory=list)
    episodes: list[ObservedEpisode] = Field(default_factory=list)
    artists: list[ObservedArtist] = Field(default_factory=list)
    albums: list[ObservedAlbum] = Field(default_factory=list)
    discs: list[ObservedDisc] = Field(default_factory=list)
    tracks: list[ObservedTrack] = Field(default_factory=list)
    variants: list[ObservedVariant] = Field(default_factory=list)
    bundles: list[ObservedBundle] = Field(default_factory=list)
    events: list[ObservedEvent] = Field(default_factory=list)

    @model_validator(mode="after")
    def references_and_history_are_consistent(self) -> ObservedState:
        _validate_topology_references(self)
        for asset in self.assets:
            _validate_grouped_lifecycle_links(asset.path_history, scope=asset.observed_ref)
        _validate_grouped_lifecycle_links(self.events, scope="events")
        return self


def _validate_topology_references(state: ObservedState) -> None:
    _ensure_unique([asset.observed_ref for asset in state.assets], kind="asset observed_ref")
    _ensure_unique(
        [variant.observed_ref for variant in state.variants],
        kind="variant observed_ref",
    )
    _ensure_unique([bundle.observed_ref for bundle in state.bundles], kind="bundle observed_ref")
    _ensure_unique(_domain_refs(state), kind="domain observed_ref")

    assets = {asset.observed_ref: asset for asset in state.assets}
    variants = {variant.observed_ref: variant for variant in state.variants}
    bundles = {bundle.observed_ref: bundle for bundle in state.bundles}
    sidecars = _sidecar_refs_by_asset(state.assets)

    parent_refs = _variant_parent_refs_by_kind(state)
    _validate_domain_parent_refs(state)
    _validate_asset_topology_refs(state.assets, variants, bundles)
    _validate_variant_refs(state.variants, parent_refs)
    _validate_bundle_refs(state.bundles, assets, variants, sidecars)
    _validate_topology_agreement(state.assets, bundles)


def _domain_refs(state: ObservedState) -> list[str]:
    return [
        *(movie.observed_ref for movie in state.movies),
        *(series.observed_ref for series in state.series),
        *(season.observed_ref for season in state.seasons),
        *(episode.observed_ref for episode in state.episodes),
        *(artist.observed_ref for artist in state.artists),
        *(album.observed_ref for album in state.albums),
        *(disc.observed_ref for disc in state.discs),
        *(track.observed_ref for track in state.tracks),
    ]


def _variant_parent_refs_by_kind(state: ObservedState) -> dict[ParentKind, set[str]]:
    return {
        ParentKind.MOVIE: {movie.observed_ref for movie in state.movies},
        ParentKind.EPISODE: {episode.observed_ref for episode in state.episodes},
        ParentKind.TRACK: {track.observed_ref for track in state.tracks},
        ParentKind.PODCAST_EPISODE: set(),
    }


def _validate_domain_parent_refs(state: ObservedState) -> None:
    series_refs = {series.observed_ref for series in state.series}
    season_refs = {season.observed_ref for season in state.seasons}
    artist_refs = {artist.observed_ref for artist in state.artists}
    album_refs = {album.observed_ref for album in state.albums}
    disc_refs = {disc.observed_ref for disc in state.discs}

    for season in state.seasons:
        if season.series_ref not in series_refs:
            raise ValueError(f"invalid season series_ref: {season.series_ref}")
    for episode in state.episodes:
        if episode.season_ref not in season_refs:
            raise ValueError(f"invalid episode season_ref: {episode.season_ref}")
    for album in state.albums:
        if album.artist_ref not in artist_refs:
            raise ValueError(f"invalid album artist_ref: {album.artist_ref}")
    for disc in state.discs:
        if disc.album_ref not in album_refs:
            raise ValueError(f"invalid disc album_ref: {disc.album_ref}")
    for track in state.tracks:
        if track.disc_ref not in disc_refs:
            raise ValueError(f"invalid track disc_ref: {track.disc_ref}")


def _sidecar_refs_by_asset(assets: Sequence[ObservedAsset]) -> dict[str, set[str]]:
    refs: dict[str, set[str]] = {}
    for asset in assets:
        sidecar_refs = [sidecar.observed_ref for sidecar in asset.sidecars]
        _ensure_unique(sidecar_refs, kind=f"sidecar observed_ref under {asset.observed_ref}")
        refs[asset.observed_ref] = set(sidecar_refs)
    return refs


def _validate_asset_topology_refs(
    assets: Sequence[ObservedAsset],
    variants: dict[str, ObservedVariant],
    bundles: dict[str, ObservedBundle],
) -> None:
    for asset in assets:
        if asset.variant_ref is not None and asset.variant_ref not in variants:
            raise ValueError(f"invalid variant_ref: {asset.variant_ref}")
        if asset.bundle_ref is not None and asset.bundle_ref not in bundles:
            raise ValueError(f"invalid bundle_ref: {asset.bundle_ref}")


def _validate_variant_refs(
    variants: Sequence[ObservedVariant], parent_refs: dict[ParentKind, set[str]]
) -> None:
    for variant in variants:
        if variant.parent_ref not in parent_refs[variant.parent_kind]:
            raise ValueError(f"invalid variant parent_ref: {variant.parent_ref}")


def _validate_bundle_refs(
    bundles: Sequence[ObservedBundle],
    assets: dict[str, ObservedAsset],
    variants: dict[str, ObservedVariant],
    sidecars: dict[str, set[str]],
) -> None:
    for bundle in bundles:
        if bundle.variant_ref is not None and bundle.variant_ref not in variants:
            raise ValueError(f"invalid bundle variant_ref: {bundle.variant_ref}")
        for asset_ref in bundle.asset_refs:
            if asset_ref not in assets:
                raise ValueError(f"invalid bundle asset_ref: {asset_ref}")
        for sidecar_ref in bundle.sidecar_refs:
            if sidecar_ref.asset_ref not in bundle.asset_refs:
                raise ValueError(f"bundle sidecar asset_ref not in bundle: {sidecar_ref.asset_ref}")
            if sidecar_ref.sidecar_ref not in sidecars.get(sidecar_ref.asset_ref, set()):
                raise ValueError(f"invalid bundle sidecar_ref: {sidecar_ref.sidecar_ref}")


def _validate_topology_agreement(
    assets: Sequence[ObservedAsset],
    bundles: dict[str, ObservedBundle],
) -> None:
    for asset in assets:
        if asset.bundle_ref is not None:
            bundle = bundles[asset.bundle_ref]
            _validate_asset_bundle_agreement(asset, bundle)
    for bundle in bundles.values():
        for asset in assets:
            if asset.observed_ref in bundle.asset_refs:
                _validate_asset_listed_in_bundle(asset, bundle)


def _validate_asset_bundle_agreement(asset: ObservedAsset, bundle: ObservedBundle) -> None:
    if bundle.asset_refs and asset.observed_ref not in bundle.asset_refs:
        raise ValueError("asset bundle_ref contradicts bundle asset_refs")
    if (
        bundle.variant_ref is not None
        and asset.variant_ref is not None
        and bundle.variant_ref != asset.variant_ref
    ):
        raise ValueError("asset variant_ref contradicts bundle variant_ref")


def _validate_asset_listed_in_bundle(asset: ObservedAsset, bundle: ObservedBundle) -> None:
    if asset.bundle_ref is not None and asset.bundle_ref != bundle.observed_ref:
        raise ValueError("bundle asset_refs contradict asset bundle_ref")
    if (
        asset.variant_ref is not None
        and bundle.variant_ref is not None
        and asset.variant_ref != bundle.variant_ref
    ):
        raise ValueError("bundle variant_ref contradicts asset variant_ref")


def _validate_grouped_lifecycle_links(
    entries: Sequence[ObservedPathHistoryEntry | ObservedEvent], *, scope: str
) -> None:
    _reject_duplicate_event_refs(entries, scope=scope)
    by_ref = {entry.observed_event_ref: entry for entry in entries if entry.observed_event_ref}
    for index, entry in enumerate(entries):
        _validate_explicit_link(entry, by_ref, scope=scope)
        _validate_incomplete_group_link(entry, entries, index=index, scope=scope)
    _validate_implicit_grouping(entries, scope=scope)


def _reject_duplicate_event_refs(
    entries: Sequence[ObservedPathHistoryEntry | ObservedEvent], *, scope: str
) -> None:
    seen: set[str] = set()
    for entry in entries:
        ref = entry.observed_event_ref
        if ref is None:
            continue
        if ref in seen:
            raise ValueError(f"duplicate observed_event_ref in {scope}: {ref}")
        seen.add(ref)


def _validate_explicit_link(
    entry: ObservedPathHistoryEntry | ObservedEvent,
    by_ref: dict[str, ObservedPathHistoryEntry | ObservedEvent],
    *,
    scope: str,
) -> None:
    related_ref = entry.related_observed_event_ref
    if related_ref is None:
        return
    if entry.observed_event_ref is None:
        raise ValueError(f"one-sided related_observed_event_ref in {scope}")
    related = by_ref.get(related_ref)
    if related is None:
        raise ValueError(f"dangling related_observed_event_ref in {scope}: {related_ref}")
    if related.related_observed_event_ref != entry.observed_event_ref:
        raise ValueError(f"non-reciprocal related_observed_event_ref in {scope}")
    if not _entries_are_compatible_group(entry, related):
        raise ValueError(f"incompatible grouped lifecycle links in {scope}")


def _validate_incomplete_group_link(
    entry: ObservedPathHistoryEntry | ObservedEvent,
    entries: Sequence[ObservedPathHistoryEntry | ObservedEvent],
    *,
    index: int,
    scope: str,
) -> None:
    has_event_ref = entry.observed_event_ref is not None
    has_related_ref = entry.related_observed_event_ref is not None
    if has_event_ref == has_related_ref:
        return
    if has_related_ref or _has_compatible_group_counterpart(entry, entries, index=index):
        raise ValueError(f"mixed explicit and implicit lifecycle links in {scope}")


def _validate_implicit_grouping(
    entries: Sequence[ObservedPathHistoryEntry | ObservedEvent], *, scope: str
) -> None:
    for index, entry in enumerate(entries):
        if _has_any_event_ref(entry):
            continue
        later = _compatible_later_implicit_entries(entry, entries[index + 1 :])
        earlier = _compatible_earlier_implicit_entries(entry, entries[:index])
        if len(later) > 1 or len(earlier) > 1:
            raise ValueError(f"ambiguous implicit lifecycle links in {scope}")


def _has_any_event_ref(entry: ObservedPathHistoryEntry | ObservedEvent) -> bool:
    return entry.observed_event_ref is not None or entry.related_observed_event_ref is not None


def _has_compatible_group_counterpart(
    entry: ObservedPathHistoryEntry | ObservedEvent,
    entries: Sequence[ObservedPathHistoryEntry | ObservedEvent],
    *,
    index: int,
) -> bool:
    for other_index, other in enumerate(entries):
        if other_index != index and _entries_are_compatible_group(entry, other):
            return True
    return False


def _compatible_later_implicit_entries(
    entry: ObservedPathHistoryEntry | ObservedEvent,
    later: Sequence[ObservedPathHistoryEntry | ObservedEvent],
) -> list[ObservedPathHistoryEntry | ObservedEvent]:
    return [
        other for other in later if not _has_any_event_ref(other) and _ordered_group(entry, other)
    ]


def _compatible_earlier_implicit_entries(
    entry: ObservedPathHistoryEntry | ObservedEvent,
    earlier: Sequence[ObservedPathHistoryEntry | ObservedEvent],
) -> list[ObservedPathHistoryEntry | ObservedEvent]:
    return [
        other for other in earlier if not _has_any_event_ref(other) and _ordered_group(other, entry)
    ]


def _entries_are_compatible_group(
    left: ObservedPathHistoryEntry | ObservedEvent,
    right: ObservedPathHistoryEntry | ObservedEvent,
) -> bool:
    return _ordered_group(left, right) or _ordered_group(right, left)


def _ordered_group(
    first: ObservedPathHistoryEntry | ObservedEvent,
    second: ObservedPathHistoryEntry | ObservedEvent,
) -> bool:
    if first.action is ObservedAction.DELETE_FILE and second.action is ObservedAction.ADD_FILE:
        return True
    if first.action is ObservedAction.SLOW_COPY_START:
        return second.action is ObservedAction.SLOW_COPY_COMMIT and first.to_path == second.to_path
    return False
