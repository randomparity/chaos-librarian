"""Normalized evidence indexes for adapter matching."""

from __future__ import annotations

from collections.abc import Callable, Hashable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import NamedTuple, TypedDict

from chaos_librarian.adapter.fixture import OracleFixture
from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.manifest import (
    ManifestAlbum,
    ManifestArtist,
    ManifestDisc,
    ManifestEpisode,
    ManifestMovie,
    ManifestSeason,
    ManifestSeries,
    ManifestSidecar,
    ManifestTrack,
    ProbedMedia,
)
from chaos_librarian.contract.observed_state import (
    ObservedAlbum,
    ObservedArtist,
    ObservedAsset,
    ObservedBundle,
    ObservedDisc,
    ObservedEpisode,
    ObservedEvent,
    ObservedMovie,
    ObservedPathHistoryEntry,
    ObservedSeason,
    ObservedSeries,
    ObservedSidecar,
    ObservedState,
    ObservedTrack,
)
from chaos_librarian.contract.reports import PathHistoryEntry


@dataclass(frozen=True)
class OracleAssetView:
    asset_id: str
    bundle_id: str
    current_path: str | None
    content_hash: str | None
    probed: ProbedMedia | None
    path_history: tuple[PathHistoryEntry, ...]
    sidecars: tuple[ManifestSidecar, ...]


@dataclass(frozen=True)
class ObservedAssetView:
    observed_ref: str
    current_path: str | None
    content_hash: str | None
    probed: ProbedMedia | None
    variant_ref: str | None
    bundle_ref: str | None
    sidecars: tuple[ObservedSidecar, ...]
    path_history: tuple[ObservedPathHistoryEntry, ...]


@dataclass(frozen=True)
class OracleTopologyView:
    asset_id: str
    bundle_id: str
    variant_id: str
    parent_kind: ParentKind
    parent_id: str
    movie_title: str | None = None
    series_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    episode_title: str | None = None
    artist_name: str | None = None
    album_title: str | None = None
    disc_number: int | None = None
    track_number: int | None = None
    track_title: str | None = None
    variant_label: str | None = None
    bundle_asset_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObservedTopologyView:
    observed_ref: str
    bundle_ref: str | None
    variant_ref: str | None
    parent_kind: ParentKind | None
    parent_ref: str | None
    movie_title: str | None = None
    series_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    episode_title: str | None = None
    artist_name: str | None = None
    album_title: str | None = None
    disc_number: int | None = None
    track_number: int | None = None
    track_title: str | None = None
    variant_label: str | None = None
    bundle_asset_refs: tuple[str, ...] = ()


class TopologyKey(NamedTuple):
    kind: str
    components: tuple[str, ...]


class _TopologyDomainFields(TypedDict, total=False):
    movie_title: str | None
    series_title: str | None
    season_number: int | None
    episode_number: int | None
    episode_title: str | None
    artist_name: str | None
    album_title: str | None
    disc_number: int | None
    track_number: int | None
    track_title: str | None


@dataclass(frozen=True)
class _OracleDomainLookups:
    movies: Mapping[str, ManifestMovie]
    series: Mapping[str, ManifestSeries]
    seasons: Mapping[str, ManifestSeason]
    episodes: Mapping[str, ManifestEpisode]
    artists: Mapping[str, ManifestArtist]
    albums: Mapping[str, ManifestAlbum]
    discs: Mapping[str, ManifestDisc]
    tracks: Mapping[str, ManifestTrack]


@dataclass(frozen=True)
class _ObservedDomainLookups:
    movies: Mapping[str, ObservedMovie]
    series: Mapping[str, ObservedSeries]
    seasons: Mapping[str, ObservedSeason]
    episodes: Mapping[str, ObservedEpisode]
    artists: Mapping[str, ObservedArtist]
    albums: Mapping[str, ObservedAlbum]
    discs: Mapping[str, ObservedDisc]
    tracks: Mapping[str, ObservedTrack]


@dataclass(frozen=True)
class OracleIndex:
    assets: Mapping[str, OracleAssetView]
    topology: Mapping[str, OracleTopologyView] = field(default_factory=dict)
    current_path_to_asset_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    historical_path_to_asset_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    hash_to_asset_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    topology_key_to_asset_ids: Mapping[TopologyKey, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_views(
        cls,
        *,
        assets: Sequence[OracleAssetView],
        topology: Sequence[OracleTopologyView] = (),
    ) -> OracleIndex:
        asset_map = {asset.asset_id: asset for asset in assets}
        topology_map = {view.asset_id: view for view in topology}
        return cls(
            assets=asset_map,
            topology=topology_map,
            current_path_to_asset_ids=_lookup_by(
                assets,
                id_of=lambda asset: asset.asset_id,
                keys_of=lambda asset: (asset.current_path,),
            ),
            historical_path_to_asset_ids=_lookup_by(
                assets,
                id_of=lambda asset: asset.asset_id,
                keys_of=_oracle_history_paths,
            ),
            hash_to_asset_ids=_lookup_by(
                assets,
                id_of=lambda asset: asset.asset_id,
                keys_of=lambda asset: (asset.content_hash,),
            ),
            topology_key_to_asset_ids=_lookup_by(
                topology,
                id_of=lambda view: view.asset_id,
                keys_of=lambda view: (
                    topology_key(
                        parent_kind=view.parent_kind,
                        variant_label=view.variant_label,
                        bundle_member_count=len(view.bundle_asset_ids),
                        movie_title=view.movie_title,
                        series_title=view.series_title,
                        season_number=view.season_number,
                        episode_number=view.episode_number,
                        episode_title=view.episode_title,
                        artist_name=view.artist_name,
                        album_title=view.album_title,
                        disc_number=view.disc_number,
                        track_number=view.track_number,
                        track_title=view.track_title,
                    ),
                ),
            ),
        )

    @classmethod
    def from_fixture(cls, fixture: OracleFixture) -> OracleIndex:
        sidecars_by_asset = _manifest_sidecars_by_asset(fixture.current_manifest.sidecars)
        versions_by_asset = {
            version.asset_id: version for version in fixture.current_manifest.versions
        }
        locations_by_asset = {
            location.asset_id: location for location in fixture.current_manifest.locations
        }
        assets = []
        for manifest_asset in fixture.initial_manifest.assets:
            version = versions_by_asset.get(manifest_asset.id)
            location = locations_by_asset.get(manifest_asset.id)
            report = fixture.reports.assets[manifest_asset.id]
            assets.append(
                OracleAssetView(
                    asset_id=manifest_asset.id,
                    bundle_id=manifest_asset.bundle_id,
                    current_path=location.path if location is not None else None,
                    content_hash=version.content_hash if version is not None else None,
                    probed=version.probed if version is not None else None,
                    path_history=tuple(report.path_history),
                    sidecars=tuple(sidecars_by_asset.get(manifest_asset.id, ())),
                )
            )
        return cls.from_views(assets=tuple(assets), topology=_oracle_topology(fixture))


@dataclass(frozen=True)
class ObservedIndex:
    assets: Mapping[str, ObservedAssetView]
    topology: Mapping[str, ObservedTopologyView] = field(default_factory=dict)
    events: tuple[ObservedEvent, ...] = ()
    current_path_to_refs: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    historical_path_to_refs: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    hash_to_refs: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    topology_key_to_refs: Mapping[TopologyKey, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_views(
        cls,
        *,
        assets: Sequence[ObservedAssetView],
        topology: Sequence[ObservedTopologyView] = (),
        events: Sequence[ObservedEvent] = (),
    ) -> ObservedIndex:
        asset_map = {asset.observed_ref: asset for asset in assets}
        topology_map = {view.observed_ref: view for view in topology}
        return cls(
            assets=asset_map,
            topology=topology_map,
            events=tuple(events),
            current_path_to_refs=_lookup_by(
                assets,
                id_of=lambda asset: asset.observed_ref,
                keys_of=lambda asset: (asset.current_path,),
            ),
            historical_path_to_refs=_lookup_by(
                assets,
                id_of=lambda asset: asset.observed_ref,
                keys_of=lambda asset: (asset.current_path, *_observed_history_paths(asset)),
            ),
            hash_to_refs=_lookup_by(
                assets,
                id_of=lambda asset: asset.observed_ref,
                keys_of=lambda asset: (asset.content_hash,),
            ),
            topology_key_to_refs=_lookup_by(
                topology,
                id_of=lambda view: view.observed_ref,
                keys_of=lambda view: (
                    topology_key(
                        parent_kind=view.parent_kind,
                        variant_label=view.variant_label,
                        bundle_member_count=len(view.bundle_asset_refs),
                        movie_title=view.movie_title,
                        series_title=view.series_title,
                        season_number=view.season_number,
                        episode_number=view.episode_number,
                        episode_title=view.episode_title,
                        artist_name=view.artist_name,
                        album_title=view.album_title,
                        disc_number=view.disc_number,
                        track_number=view.track_number,
                        track_title=view.track_title,
                    ),
                ),
            ),
        )

    @classmethod
    def from_state(cls, state: ObservedState) -> ObservedIndex:
        assets = tuple(_observed_asset_view(asset) for asset in state.assets)
        return cls.from_views(
            assets=assets,
            topology=_observed_topology(state),
            events=state.events,
        )


def topology_key(
    *,
    parent_kind: ParentKind | None,
    variant_label: str | None,
    bundle_member_count: int,
    movie_title: str | None = None,
    series_title: str | None = None,
    season_number: int | None = None,
    episode_number: int | None = None,
    episode_title: str | None = None,
    artist_name: str | None = None,
    album_title: str | None = None,
    disc_number: int | None = None,
    track_number: int | None = None,
    track_title: str | None = None,
) -> TopologyKey | None:
    """Return the consumer-neutral domain topology key when enough facts exist."""
    label = variant_label or ""
    key: TopologyKey | None = None
    if parent_kind is ParentKind.MOVIE and movie_title is not None:
        key = TopologyKey("movie", (movie_title, label, str(bundle_member_count)))
    elif (
        parent_kind is ParentKind.EPISODE
        and series_title is not None
        and season_number is not None
        and episode_number is not None
    ):
        key = TopologyKey(
            "episode",
            (
                series_title,
                str(season_number),
                str(episode_number),
                episode_title or "",
                label,
                str(bundle_member_count),
            ),
        )
    elif (
        parent_kind is ParentKind.TRACK
        and artist_name is not None
        and album_title is not None
        and disc_number is not None
        and track_number is not None
    ):
        key = TopologyKey(
            "track",
            (
                artist_name,
                album_title,
                str(disc_number),
                str(track_number),
                track_title or "",
                label,
                str(bundle_member_count),
            ),
        )
    return key


def format_topology_key(key: TopologyKey) -> str:
    """Return the human-readable topology evidence value for a structured key."""
    components = key.components[:-1] if key.kind in {"episode", "track"} else key.components
    return f"{key.kind}:{'|'.join(components)}"


def _lookup_by[T, K: Hashable](
    items: Sequence[T],
    *,
    id_of: Callable[[T], str],
    keys_of: Callable[[T], Sequence[K | None]],
) -> dict[K, tuple[str, ...]]:
    values: dict[K, list[str]] = {}
    for item in items:
        item_id = id_of(item)
        for key in keys_of(item):
            if key is not None:
                values.setdefault(key, []).append(item_id)
    return {key: tuple(sorted(ids)) for key, ids in values.items()}


def _oracle_history_paths(asset: OracleAssetView) -> tuple[str, ...]:
    paths: list[str] = []
    for entry in asset.path_history:
        paths.extend(path for path in (entry.from_path, entry.to_path, entry.temp_path) if path)
    return tuple(paths)


def _observed_history_paths(asset: ObservedAssetView) -> tuple[str, ...]:
    paths: list[str] = []
    for entry in asset.path_history:
        paths.extend(path for path in (entry.from_path, entry.to_path, entry.temp_path) if path)
    return tuple(paths)


def _manifest_sidecars_by_asset(
    sidecars: Sequence[ManifestSidecar],
) -> dict[str, list[ManifestSidecar]]:
    result: dict[str, list[ManifestSidecar]] = {}
    for sidecar in sidecars:
        result.setdefault(sidecar.asset_id, []).append(sidecar)
    return result


def _oracle_topology(fixture: OracleFixture) -> tuple[OracleTopologyView, ...]:
    manifest = fixture.current_manifest
    bundles = {bundle.id: bundle for bundle in manifest.bundles}
    variants = {variant.id: variant for variant in manifest.variants}
    current_assets = {asset.id: asset for asset in manifest.assets}
    domain_lookups = _OracleDomainLookups(
        movies={movie.id: movie for movie in manifest.movies},
        series={series.id: series for series in manifest.series},
        seasons={season.id: season for season in manifest.seasons},
        episodes={episode.id: episode for episode in manifest.episodes},
        artists={artist.id: artist for artist in manifest.artists},
        albums={album.id: album for album in manifest.albums},
        discs={disc.id: disc for disc in manifest.discs},
        tracks={track.id: track for track in manifest.tracks},
    )
    bundle_members: dict[str, list[str]] = {}
    for asset in manifest.assets:
        bundle_members.setdefault(asset.bundle_id, []).append(asset.id)
    views: list[OracleTopologyView] = []
    for initial_asset in fixture.initial_manifest.assets:
        asset = current_assets.get(initial_asset.id)
        if asset is None:
            continue
        bundle = bundles[asset.bundle_id]
        variant = variants[bundle.variant_id]
        domain_fields = _oracle_domain_fields(
            domain_lookups,
            variant.parent_kind,
            variant.parent_id,
        )
        views.append(
            OracleTopologyView(
                asset_id=asset.id,
                bundle_id=bundle.id,
                variant_id=variant.id,
                parent_kind=variant.parent_kind,
                parent_id=variant.parent_id,
                variant_label=variant.label,
                bundle_asset_ids=tuple(sorted(bundle_members[bundle.id])),
                **domain_fields,
            )
        )
    return tuple(views)


def _observed_asset_view(asset: ObservedAsset) -> ObservedAssetView:
    return ObservedAssetView(
        observed_ref=asset.observed_ref,
        current_path=asset.current_path,
        content_hash=asset.content_hash,
        probed=asset.probed,
        variant_ref=asset.variant_ref,
        bundle_ref=asset.bundle_ref,
        sidecars=tuple(asset.sidecars),
        path_history=tuple(asset.path_history),
    )


def _observed_topology(state: ObservedState) -> tuple[ObservedTopologyView, ...]:
    variants = {variant.observed_ref: variant for variant in state.variants}
    bundles = {bundle.observed_ref: bundle for bundle in state.bundles}
    domain_lookups = _ObservedDomainLookups(
        movies={movie.observed_ref: movie for movie in state.movies},
        series={series.observed_ref: series for series in state.series},
        seasons={season.observed_ref: season for season in state.seasons},
        episodes={episode.observed_ref: episode for episode in state.episodes},
        artists={artist.observed_ref: artist for artist in state.artists},
        albums={album.observed_ref: album for album in state.albums},
        discs={disc.observed_ref: disc for disc in state.discs},
        tracks={track.observed_ref: track for track in state.tracks},
    )
    containing_bundle = _observed_containing_bundle(state)
    views: list[ObservedTopologyView] = []
    for asset in state.assets:
        bundle = bundles.get(asset.bundle_ref or "") or containing_bundle.get(asset.observed_ref)
        variant_ref = asset.variant_ref or (bundle.variant_ref if bundle else None)
        variant = variants.get(variant_ref or "")
        parent_kind = variant.parent_kind if variant else None
        parent_ref = variant.parent_ref if variant else None
        domain_fields = _observed_domain_fields(domain_lookups, parent_kind, parent_ref)
        views.append(
            ObservedTopologyView(
                observed_ref=asset.observed_ref,
                bundle_ref=bundle.observed_ref if bundle else asset.bundle_ref,
                variant_ref=variant_ref,
                parent_kind=parent_kind,
                parent_ref=parent_ref,
                variant_label=variant.label if variant else None,
                bundle_asset_refs=tuple(sorted(bundle.asset_refs)) if bundle else (),
                **domain_fields,
            )
        )
    return tuple(views)


def _oracle_domain_fields(
    lookups: _OracleDomainLookups,
    parent_kind: ParentKind,
    parent_id: str,
) -> _TopologyDomainFields:
    if parent_kind is ParentKind.MOVIE:
        movie = lookups.movies[parent_id]
        return {"movie_title": movie.title}
    if parent_kind is ParentKind.EPISODE:
        episode = lookups.episodes[parent_id]
        season = lookups.seasons[episode.season_id]
        series = lookups.series[season.series_id]
        return {
            "series_title": series.title,
            "season_number": season.season_number,
            "episode_number": episode.episode_number,
            "episode_title": episode.title,
        }
    track = lookups.tracks[parent_id]
    disc = lookups.discs[track.disc_id]
    album = lookups.albums[disc.album_id]
    artist = lookups.artists[album.artist_id]
    return {
        "artist_name": artist.name,
        "album_title": album.title,
        "disc_number": disc.disc_number,
        "track_number": track.track_number,
        "track_title": track.title,
    }


def _observed_domain_fields(
    lookups: _ObservedDomainLookups,
    parent_kind: ParentKind | None,
    parent_ref: str | None,
) -> _TopologyDomainFields:
    if parent_kind is None or parent_ref is None:
        return {}
    if parent_kind is ParentKind.MOVIE:
        movie = lookups.movies.get(parent_ref)
        return {"movie_title": movie.title if movie else None}
    if parent_kind is ParentKind.EPISODE:
        episode = lookups.episodes.get(parent_ref)
        if episode is None:
            return {}
        season = lookups.seasons.get(episode.season_ref)
        series = lookups.series.get(season.series_ref) if season is not None else None
        return {
            "series_title": series.title if series else None,
            "season_number": season.season_number if season else None,
            "episode_number": episode.episode_number,
            "episode_title": episode.title,
        }
    track = lookups.tracks.get(parent_ref)
    if track is None:
        return {}
    disc = lookups.discs.get(track.disc_ref)
    album = lookups.albums.get(disc.album_ref) if disc is not None else None
    artist = lookups.artists.get(album.artist_ref) if album is not None else None
    return {
        "artist_name": artist.name if artist else None,
        "album_title": album.title if album else None,
        "disc_number": disc.disc_number if disc else None,
        "track_number": track.track_number if track else None,
        "track_title": track.title,
    }


def _observed_containing_bundle(state: ObservedState) -> dict[str, ObservedBundle]:
    result: dict[str, ObservedBundle] = {}
    for bundle in state.bundles:
        for asset_ref in bundle.asset_refs:
            result[asset_ref] = bundle
    return result
