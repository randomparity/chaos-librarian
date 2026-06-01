"""Domain topology views and matching keys for adapter comparisons."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import NamedTuple

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
    ManifestTrack,
)
from chaos_librarian.contract.observed_state import (
    ObservedAlbum,
    ObservedArtist,
    ObservedBundle,
    ObservedDisc,
    ObservedEpisode,
    ObservedMovie,
    ObservedSeason,
    ObservedSeries,
    ObservedState,
    ObservedTrack,
)


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


class UnsupportedTopologyParentKindError(ValueError):
    """Raised when adapter topology receives a parent kind it cannot compare yet."""

    def __init__(
        self,
        *,
        side: str,
        parent_kind: ParentKind,
        parent_ref: str | None,
    ) -> None:
        super().__init__(f"{side} topology does not support parent_kind: {parent_kind.value}")
        self.side = side
        self.parent_kind = parent_kind
        self.parent_ref = parent_ref

    @property
    def details(self) -> dict[str, object | None]:
        return {
            "side": self.side,
            "parent_kind": self.parent_kind.value,
            "parent_ref": self.parent_ref,
        }


@dataclass(frozen=True)
class _TopologyDomainFields:
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


def movie_topology_key(
    *,
    movie_title: str,
    variant_label: str | None,
    bundle_member_count: int,
) -> TopologyKey:
    """Return the domain topology key for a movie asset."""
    return TopologyKey("movie", (movie_title, variant_label or "", str(bundle_member_count)))


def episode_topology_key(
    *,
    series_title: str,
    season_number: int,
    episode_number: int,
    episode_title: str | None,
    variant_label: str | None,
    bundle_member_count: int,
) -> TopologyKey:
    """Return the domain topology key for an episode asset."""
    return TopologyKey(
        "episode",
        (
            series_title,
            str(season_number),
            str(episode_number),
            episode_title or "",
            variant_label or "",
            str(bundle_member_count),
        ),
    )


def track_topology_key(
    *,
    artist_name: str,
    album_title: str,
    disc_number: int,
    track_number: int,
    track_title: str | None,
    variant_label: str | None,
    bundle_member_count: int,
) -> TopologyKey:
    """Return the domain topology key for a track asset."""
    return TopologyKey(
        "track",
        (
            artist_name,
            album_title,
            str(disc_number),
            str(track_number),
            track_title or "",
            variant_label or "",
            str(bundle_member_count),
        ),
    )


def _topology_key_for_domain_fields(
    *,
    parent_kind: ParentKind | None,
    variant_label: str | None,
    bundle_member_count: int,
    fields: _TopologyDomainFields,
) -> TopologyKey | None:
    """Return the consumer-neutral domain topology key when enough facts exist."""
    key: TopologyKey | None = None
    if parent_kind is ParentKind.MOVIE and fields.movie_title is not None:
        key = movie_topology_key(
            movie_title=fields.movie_title,
            variant_label=variant_label,
            bundle_member_count=bundle_member_count,
        )
    elif (
        parent_kind is ParentKind.EPISODE
        and fields.series_title is not None
        and fields.season_number is not None
        and fields.episode_number is not None
    ):
        key = episode_topology_key(
            series_title=fields.series_title,
            season_number=fields.season_number,
            episode_number=fields.episode_number,
            episode_title=fields.episode_title,
            variant_label=variant_label,
            bundle_member_count=bundle_member_count,
        )
    elif (
        parent_kind is ParentKind.TRACK
        and fields.artist_name is not None
        and fields.album_title is not None
        and fields.disc_number is not None
        and fields.track_number is not None
    ):
        key = track_topology_key(
            artist_name=fields.artist_name,
            album_title=fields.album_title,
            disc_number=fields.disc_number,
            track_number=fields.track_number,
            track_title=fields.track_title,
            variant_label=variant_label,
            bundle_member_count=bundle_member_count,
        )
    return key


def oracle_topology_key(view: OracleTopologyView) -> TopologyKey | None:
    return _topology_key_for_domain_fields(
        parent_kind=view.parent_kind,
        variant_label=view.variant_label,
        bundle_member_count=len(view.bundle_asset_ids),
        fields=_TopologyDomainFields(
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
    )


def observed_topology_key(view: ObservedTopologyView) -> TopologyKey | None:
    return _topology_key_for_domain_fields(
        parent_kind=view.parent_kind,
        variant_label=view.variant_label,
        bundle_member_count=len(view.bundle_asset_refs),
        fields=_TopologyDomainFields(
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
    )


def format_topology_key(key: TopologyKey) -> str:
    """Return the human-readable topology evidence value for a structured key."""
    components = key.components[:-1] if key.kind in {"episode", "track"} else key.components
    return f"{key.kind}:{'|'.join(components)}"


def oracle_topology(fixture: OracleFixture) -> tuple[OracleTopologyView, ...]:
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
                movie_title=domain_fields.movie_title,
                series_title=domain_fields.series_title,
                season_number=domain_fields.season_number,
                episode_number=domain_fields.episode_number,
                episode_title=domain_fields.episode_title,
                artist_name=domain_fields.artist_name,
                album_title=domain_fields.album_title,
                disc_number=domain_fields.disc_number,
                track_number=domain_fields.track_number,
                track_title=domain_fields.track_title,
                variant_label=variant.label,
                bundle_asset_ids=tuple(sorted(bundle_members[bundle.id])),
            )
        )
    return tuple(views)


def observed_topology(state: ObservedState) -> tuple[ObservedTopologyView, ...]:
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
                movie_title=domain_fields.movie_title,
                series_title=domain_fields.series_title,
                season_number=domain_fields.season_number,
                episode_number=domain_fields.episode_number,
                episode_title=domain_fields.episode_title,
                artist_name=domain_fields.artist_name,
                album_title=domain_fields.album_title,
                disc_number=domain_fields.disc_number,
                track_number=domain_fields.track_number,
                track_title=domain_fields.track_title,
                variant_label=variant.label if variant else None,
                bundle_asset_refs=tuple(sorted(bundle.asset_refs)) if bundle else (),
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
        return _TopologyDomainFields(movie_title=movie.title)
    if parent_kind is ParentKind.EPISODE:
        episode = lookups.episodes[parent_id]
        season = lookups.seasons[episode.season_id]
        series = lookups.series[season.series_id]
        return _TopologyDomainFields(
            series_title=series.title,
            season_number=season.season_number,
            episode_number=episode.episode_number,
            episode_title=episode.title,
        )
    if parent_kind is ParentKind.TRACK:
        track = lookups.tracks[parent_id]
        disc = lookups.discs[track.disc_id]
        album = lookups.albums[disc.album_id]
        artist = lookups.artists[album.artist_id]
        return _TopologyDomainFields(
            artist_name=artist.name,
            album_title=album.title,
            disc_number=disc.disc_number,
            track_number=track.track_number,
            track_title=track.title,
        )
    raise UnsupportedTopologyParentKindError(
        side="oracle",
        parent_kind=parent_kind,
        parent_ref=parent_id,
    )


def _observed_domain_fields(
    lookups: _ObservedDomainLookups,
    parent_kind: ParentKind | None,
    parent_ref: str | None,
) -> _TopologyDomainFields:
    if parent_kind is None or parent_ref is None:
        return _TopologyDomainFields()
    if parent_kind is ParentKind.MOVIE:
        movie = lookups.movies.get(parent_ref)
        return _TopologyDomainFields(movie_title=movie.title if movie else None)
    if parent_kind is ParentKind.EPISODE:
        episode = lookups.episodes.get(parent_ref)
        if episode is None:
            return _TopologyDomainFields()
        season = lookups.seasons.get(episode.season_ref)
        series = lookups.series.get(season.series_ref) if season is not None else None
        return _TopologyDomainFields(
            series_title=series.title if series else None,
            season_number=season.season_number if season else None,
            episode_number=episode.episode_number,
            episode_title=episode.title,
        )
    if parent_kind is ParentKind.TRACK:
        track = lookups.tracks.get(parent_ref)
        if track is None:
            return _TopologyDomainFields()
        disc = lookups.discs.get(track.disc_ref)
        album = lookups.albums.get(disc.album_ref) if disc is not None else None
        artist = lookups.artists.get(album.artist_ref) if album is not None else None
        return _TopologyDomainFields(
            artist_name=artist.name if artist else None,
            album_title=album.title if album else None,
            disc_number=disc.disc_number if disc else None,
            track_number=track.track_number,
            track_title=track.title,
        )
    raise UnsupportedTopologyParentKindError(
        side="observed",
        parent_kind=parent_kind,
        parent_ref=parent_ref,
    )


def _observed_containing_bundle(state: ObservedState) -> dict[str, ObservedBundle]:
    result: dict[str, ObservedBundle] = {}
    for bundle in state.bundles:
        for asset_ref in bundle.asset_refs:
            result[asset_ref] = bundle
    return result
