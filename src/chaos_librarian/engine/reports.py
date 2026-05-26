"""Per-entity report builders.

``build_report_set`` is a pure function: it takes the initial manifest,
the current manifest, and the journal, and returns a ``ReportSet`` of
sorted, immutable report tuples. Both ``run_plan`` (after the timeline
loop) and ``step_fixture`` (after each advance) call it; neither owns
any persistence. See ``engine/writer.py`` for that.

Iteration order is lexicographic on id so report files are bit-identical
for the same logical state.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from chaos_librarian.contract import (
    ALBUM_REPORT_SCHEMA_VERSION,
    ARTIST_REPORT_SCHEMA_VERSION,
    ASSET_REPORT_SCHEMA_VERSION,
    BUNDLE_REPORT_SCHEMA_VERSION,
    DISC_REPORT_SCHEMA_VERSION,
    EPISODE_REPORT_SCHEMA_VERSION,
    MOVIE_REPORT_SCHEMA_VERSION,
    SEASON_REPORT_SCHEMA_VERSION,
    SERIES_REPORT_SCHEMA_VERSION,
    TRACK_REPORT_SCHEMA_VERSION,
    VARIANT_REPORT_SCHEMA_VERSION,
)
from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAlbum,
    ManifestArtist,
    ManifestBundle,
    ManifestDisc,
    ManifestEpisode,
    ManifestLocation,
    ManifestMovie,
    ManifestSeason,
    ManifestSeries,
    ManifestTrack,
    ManifestVariant,
    ManifestVersion,
)
from chaos_librarian.contract.reports import (
    AlbumReport,
    ArtistReport,
    AssetHistoryEntry,
    AssetReport,
    AssetSnapshot,
    BundleReport,
    DiscReport,
    EpisodeReport,
    MovieReport,
    SeasonReport,
    SeriesReport,
    TrackReport,
    VariantReport,
)
from chaos_librarian.engine.path_history import derive_path_history
from chaos_librarian.engine.version_history import derive_version_history
from chaos_librarian.errors import ChaosLibrarianValueError


@dataclass(frozen=True)
class ReportSet:
    """Sorted, immutable bundle of every per-entity report a fixture emits."""

    assets: tuple[AssetReport, ...]
    movies: tuple[MovieReport, ...]
    series: tuple[SeriesReport, ...]
    seasons: tuple[SeasonReport, ...]
    episodes: tuple[EpisodeReport, ...]
    artists: tuple[ArtistReport, ...]
    albums: tuple[AlbumReport, ...]
    discs: tuple[DiscReport, ...]
    tracks: tuple[TrackReport, ...]
    variants: tuple[VariantReport, ...]
    bundles: tuple[BundleReport, ...]


@dataclass(frozen=True)
class _AssetTopology:
    movie_id: str | None = None
    series_id: str | None = None
    season_id: str | None = None
    episode_id: str | None = None
    artist_id: str | None = None
    album_id: str | None = None
    disc_id: str | None = None
    track_id: str | None = None


def build_report_set(
    *,
    initial: Manifest,
    current: Manifest,
    journal: Iterable[JournalEntry],
) -> ReportSet:
    """Derive per-entity reports from manifest + journal state.

    Args:
        initial: The initial manifest emitted at ``t=0``.
        current: The manifest reflecting the state after the journal's
            last entry.
        journal: Every journal entry in the run so far. Iterated once.

    Returns:
        ``ReportSet`` sorted lexicographically by id within each tuple.
    """
    journal_list = list(journal)
    assets = tuple(
        sorted(
            (
                _build_asset_report(asset.id, initial, current, journal_list)
                for asset in initial.assets
            ),
            key=lambda a: a.asset_id,
        )
    )
    movies = tuple(
        sorted(
            (_build_movie_report(movie, initial) for movie in initial.movies),
            key=lambda report: report.movie_id,
        )
    )
    series = tuple(
        sorted(
            (_build_series_report(series_row, initial) for series_row in initial.series),
            key=lambda report: report.series_id,
        )
    )
    seasons = tuple(
        sorted(
            (_build_season_report(season, initial) for season in initial.seasons),
            key=lambda report: report.season_id,
        )
    )
    episodes = tuple(
        sorted(
            (_build_episode_report(episode, initial) for episode in initial.episodes),
            key=lambda report: report.episode_id,
        )
    )
    artists = tuple(
        sorted(
            (_build_artist_report(artist, initial) for artist in initial.artists),
            key=lambda report: report.artist_id,
        )
    )
    albums = tuple(
        sorted(
            (_build_album_report(album, initial) for album in initial.albums),
            key=lambda report: report.album_id,
        )
    )
    discs = tuple(
        sorted(
            (_build_disc_report(disc, initial) for disc in initial.discs),
            key=lambda report: report.disc_id,
        )
    )
    tracks = tuple(
        sorted(
            (_build_track_report(track, initial) for track in initial.tracks),
            key=lambda report: report.track_id,
        )
    )
    variants = tuple(
        sorted(
            (_build_variant_report(variant, initial) for variant in initial.variants),
            key=lambda report: report.variant_id,
        )
    )
    bundles = tuple(
        sorted(
            (_build_bundle_report(bundle, initial, current) for bundle in initial.bundles),
            key=lambda report: report.bundle_id,
        )
    )
    return ReportSet(
        assets=assets,
        movies=movies,
        series=series,
        seasons=seasons,
        episodes=episodes,
        artists=artists,
        albums=albums,
        discs=discs,
        tracks=tracks,
        variants=variants,
        bundles=bundles,
    )


def _snapshot_for(asset_id: str, manifest: Manifest) -> AssetSnapshot | None:
    version = _current_version_for(asset_id, manifest.versions)
    if version is None:
        return None
    location = _find_by_asset_id(asset_id, manifest.locations)
    if location is None:
        return None
    return AssetSnapshot(
        location_path=location.path,
        version_id=version.id,
        version_index=version.index,
        content_hash=version.content_hash,
        probed=version.probed,
        corruption=version.corruption,
    )


def _current_version_for(asset_id: str, versions: list[ManifestVersion]) -> ManifestVersion | None:
    matches = [version for version in versions if version.asset_id == asset_id]
    if not matches:
        return None
    return max(matches, key=lambda version: version.index)


def _find_by_asset_id[T: ManifestVersion | ManifestLocation](
    asset_id: str, items: list[T]
) -> T | None:
    """Linear search by ``asset_id`` over a manifest sub-collection."""
    for item in items:
        if item.asset_id == asset_id:
            return item
    return None


def _build_asset_report(
    asset_id: str,
    initial: Manifest,
    current: Manifest,
    journal: list[JournalEntry],
) -> AssetReport:
    initial_snapshot = _snapshot_for(asset_id, initial)
    if initial_snapshot is None:
        raise ChaosLibrarianValueError(f"asset {asset_id} missing from initial manifest")
    bundle = _bundle_for_asset(asset_id, initial)
    variant = _variant_for_bundle(bundle, initial)
    topology = _asset_topology_for(variant, initial)
    history = [
        AssetHistoryEntry(
            logical_time_ns=entry.logical_time_ns,
            event_id=entry.event_id,
            action=entry.action,
            state_delta=dict(entry.state_delta),
        )
        for entry in journal
        if asset_id in entry.target_ids
    ]
    return AssetReport(
        schema_version=ASSET_REPORT_SCHEMA_VERSION,
        asset_id=asset_id,
        parent_kind=variant.parent_kind,
        parent_id=variant.parent_id,
        movie_id=topology.movie_id,
        series_id=topology.series_id,
        season_id=topology.season_id,
        episode_id=topology.episode_id,
        artist_id=topology.artist_id,
        album_id=topology.album_id,
        disc_id=topology.disc_id,
        track_id=topology.track_id,
        variant_id=variant.id,
        bundle_id=bundle.id,
        initial=initial_snapshot,
        history=history,
        current=_snapshot_for(asset_id, current),
        path_history=derive_path_history(asset_id, journal),
        version_history=derive_version_history(asset_id, journal),
    )


def _build_movie_report(movie: ManifestMovie, initial: Manifest) -> MovieReport:
    variant_ids = _variant_ids_for_parent(initial, ParentKind.MOVIE, movie.id)
    return MovieReport(
        schema_version=MOVIE_REPORT_SCHEMA_VERSION,
        movie_id=movie.id,
        title=movie.title,
        variant_ids=variant_ids,
        asset_ids=_asset_ids_for_variants(initial, variant_ids),
    )


def _build_series_report(series: ManifestSeries, initial: Manifest) -> SeriesReport:
    season_ids = sorted(season.id for season in initial.seasons if season.series_id == series.id)
    episode_ids = _episode_ids_for_seasons(initial, season_ids)
    return SeriesReport(
        schema_version=SERIES_REPORT_SCHEMA_VERSION,
        series_id=series.id,
        title=series.title,
        season_ids=season_ids,
        episode_ids=episode_ids,
        asset_ids=_asset_ids_for_parents(initial, ParentKind.EPISODE, episode_ids),
    )


def _build_season_report(season: ManifestSeason, initial: Manifest) -> SeasonReport:
    episode_ids = _episode_ids_for_seasons(initial, [season.id])
    return SeasonReport(
        schema_version=SEASON_REPORT_SCHEMA_VERSION,
        season_id=season.id,
        series_id=season.series_id,
        season_number=season.season_number,
        title=season.title,
        episode_ids=episode_ids,
        asset_ids=_asset_ids_for_parents(initial, ParentKind.EPISODE, episode_ids),
    )


def _build_episode_report(episode: ManifestEpisode, initial: Manifest) -> EpisodeReport:
    variant_ids = _variant_ids_for_parent(initial, ParentKind.EPISODE, episode.id)
    return EpisodeReport(
        schema_version=EPISODE_REPORT_SCHEMA_VERSION,
        episode_id=episode.id,
        season_id=episode.season_id,
        episode_number=episode.episode_number,
        title=episode.title,
        aired_on=episode.aired_on,
        absolute_number=episode.absolute_number,
        variant_ids=variant_ids,
        asset_ids=_asset_ids_for_variants(initial, variant_ids),
    )


def _build_artist_report(artist: ManifestArtist, initial: Manifest) -> ArtistReport:
    album_ids = sorted(album.id for album in initial.albums if album.artist_id == artist.id)
    disc_ids = _disc_ids_for_albums(initial, album_ids)
    track_ids = _track_ids_for_discs(initial, disc_ids)
    return ArtistReport(
        schema_version=ARTIST_REPORT_SCHEMA_VERSION,
        artist_id=artist.id,
        name=artist.name,
        album_ids=album_ids,
        track_ids=track_ids,
        asset_ids=_asset_ids_for_parents(initial, ParentKind.TRACK, track_ids),
    )


def _build_album_report(album: ManifestAlbum, initial: Manifest) -> AlbumReport:
    disc_ids = _disc_ids_for_albums(initial, [album.id])
    track_ids = _track_ids_for_discs(initial, disc_ids)
    return AlbumReport(
        schema_version=ALBUM_REPORT_SCHEMA_VERSION,
        album_id=album.id,
        artist_id=album.artist_id,
        title=album.title,
        release_year=album.release_year,
        disc_ids=disc_ids,
        track_ids=track_ids,
        asset_ids=_asset_ids_for_parents(initial, ParentKind.TRACK, track_ids),
    )


def _build_disc_report(disc: ManifestDisc, initial: Manifest) -> DiscReport:
    track_ids = _track_ids_for_discs(initial, [disc.id])
    return DiscReport(
        schema_version=DISC_REPORT_SCHEMA_VERSION,
        disc_id=disc.id,
        album_id=disc.album_id,
        disc_number=disc.disc_number,
        track_ids=track_ids,
        asset_ids=_asset_ids_for_parents(initial, ParentKind.TRACK, track_ids),
    )


def _build_track_report(track: ManifestTrack, initial: Manifest) -> TrackReport:
    variant_ids = _variant_ids_for_parent(initial, ParentKind.TRACK, track.id)
    return TrackReport(
        schema_version=TRACK_REPORT_SCHEMA_VERSION,
        track_id=track.id,
        disc_id=track.disc_id,
        track_number=track.track_number,
        title=track.title,
        performers=list(track.performers),
        variant_ids=variant_ids,
        asset_ids=_asset_ids_for_variants(initial, variant_ids),
    )


def _build_variant_report(variant: ManifestVariant, initial: Manifest) -> VariantReport:
    bundle = _bundle_for_variant(variant.id, initial)
    asset_ids = sorted(asset.id for asset in initial.assets if asset.bundle_id == bundle.id)
    return VariantReport(
        schema_version=VARIANT_REPORT_SCHEMA_VERSION,
        variant_id=variant.id,
        parent_kind=variant.parent_kind,
        parent_id=variant.parent_id,
        label=variant.label,
        bundle_id=bundle.id,
        asset_ids=asset_ids,
    )


def _build_bundle_report(
    bundle: ManifestBundle, initial: Manifest, current: Manifest
) -> BundleReport:
    asset_ids = sorted(asset.id for asset in initial.assets if asset.bundle_id == bundle.id)
    asset_id_set = set(asset_ids)
    sidecar_ids = sorted(
        sidecar.id for sidecar in current.sidecars if sidecar.asset_id in asset_id_set
    )
    return BundleReport(
        schema_version=BUNDLE_REPORT_SCHEMA_VERSION,
        bundle_id=bundle.id,
        variant_id=bundle.variant_id,
        asset_ids=asset_ids,
        sidecar_ids=sidecar_ids,
    )


def _variant_ids_for_parent(
    initial: Manifest,
    parent_kind: ParentKind,
    parent_id: str,
) -> list[str]:
    return sorted(
        variant.id
        for variant in initial.variants
        if variant.parent_kind is parent_kind and variant.parent_id == parent_id
    )


def _asset_ids_for_parents(
    initial: Manifest,
    parent_kind: ParentKind,
    parent_ids: Iterable[str],
) -> list[str]:
    asset_ids: list[str] = []
    for parent_id in parent_ids:
        variant_ids = _variant_ids_for_parent(initial, parent_kind, parent_id)
        asset_ids.extend(_asset_ids_for_variants(initial, variant_ids))
    return sorted(asset_ids)


def _asset_ids_for_variants(initial: Manifest, variant_ids: Iterable[str]) -> list[str]:
    asset_ids: list[str] = []
    for variant_id in variant_ids:
        bundle = _bundle_for_variant(variant_id, initial)
        asset_ids.extend(asset.id for asset in initial.assets if asset.bundle_id == bundle.id)
    return sorted(asset_ids)


def _episode_ids_for_seasons(initial: Manifest, season_ids: Iterable[str]) -> list[str]:
    season_id_set = set(season_ids)
    return sorted(episode.id for episode in initial.episodes if episode.season_id in season_id_set)


def _disc_ids_for_albums(initial: Manifest, album_ids: Iterable[str]) -> list[str]:
    album_id_set = set(album_ids)
    return sorted(disc.id for disc in initial.discs if disc.album_id in album_id_set)


def _track_ids_for_discs(initial: Manifest, disc_ids: Iterable[str]) -> list[str]:
    disc_id_set = set(disc_ids)
    return sorted(track.id for track in initial.tracks if track.disc_id in disc_id_set)


def _bundle_for_asset(asset_id: str, initial: Manifest) -> ManifestBundle:
    asset = next((item for item in initial.assets if item.id == asset_id), None)
    if asset is None:
        raise ChaosLibrarianValueError(f"asset {asset_id} missing from initial manifest")
    bundle = next((item for item in initial.bundles if item.id == asset.bundle_id), None)
    if bundle is None:
        raise ChaosLibrarianValueError(f"asset {asset_id} references missing bundle")
    return bundle


def _variant_for_bundle(bundle: ManifestBundle, initial: Manifest) -> ManifestVariant:
    variant = next(
        (item for item in initial.variants if item.id == bundle.variant_id),
        None,
    )
    if variant is None:
        raise ChaosLibrarianValueError(f"bundle {bundle.id} references missing variant")
    return variant


def _bundle_for_variant(variant_id: str, initial: Manifest) -> ManifestBundle:
    bundle = next((item for item in initial.bundles if item.variant_id == variant_id), None)
    if bundle is None:
        raise ChaosLibrarianValueError(f"variant {variant_id} has no bundle")
    return bundle


def _asset_topology_for(variant: ManifestVariant, initial: Manifest) -> _AssetTopology:
    if variant.parent_kind is ParentKind.MOVIE:
        _require_movie(variant.parent_id, initial)
        return _AssetTopology(movie_id=variant.parent_id)
    if variant.parent_kind is ParentKind.EPISODE:
        episode = _require_episode(variant.parent_id, initial)
        season = _require_season(episode.season_id, initial)
        series = _require_series(season.series_id, initial)
        return _AssetTopology(
            series_id=series.id,
            season_id=season.id,
            episode_id=episode.id,
        )
    if variant.parent_kind is ParentKind.TRACK:
        track = _require_track(variant.parent_id, initial)
        disc = _require_disc(track.disc_id, initial)
        album = _require_album(disc.album_id, initial)
        artist = _require_artist(album.artist_id, initial)
        return _AssetTopology(
            artist_id=artist.id,
            album_id=album.id,
            disc_id=disc.id,
            track_id=track.id,
        )
    raise ChaosLibrarianValueError(f"unsupported variant parent kind: {variant.parent_kind}")


def _require_movie(movie_id: str, initial: Manifest) -> ManifestMovie:
    movie = next((item for item in initial.movies if item.id == movie_id), None)
    if movie is None:
        raise ChaosLibrarianValueError(f"variant references missing movie {movie_id!r}")
    return movie


def _require_series(series_id: str, initial: Manifest) -> ManifestSeries:
    series = next((item for item in initial.series if item.id == series_id), None)
    if series is None:
        raise ChaosLibrarianValueError(f"season references missing series {series_id!r}")
    return series


def _require_season(season_id: str, initial: Manifest) -> ManifestSeason:
    season = next((item for item in initial.seasons if item.id == season_id), None)
    if season is None:
        raise ChaosLibrarianValueError(f"episode references missing season {season_id!r}")
    return season


def _require_episode(episode_id: str, initial: Manifest) -> ManifestEpisode:
    episode = next((item for item in initial.episodes if item.id == episode_id), None)
    if episode is None:
        raise ChaosLibrarianValueError(f"variant references missing episode {episode_id!r}")
    return episode


def _require_artist(artist_id: str, initial: Manifest) -> ManifestArtist:
    artist = next((item for item in initial.artists if item.id == artist_id), None)
    if artist is None:
        raise ChaosLibrarianValueError(f"album references missing artist {artist_id!r}")
    return artist


def _require_album(album_id: str, initial: Manifest) -> ManifestAlbum:
    album = next((item for item in initial.albums if item.id == album_id), None)
    if album is None:
        raise ChaosLibrarianValueError(f"disc references missing album {album_id!r}")
    return album


def _require_disc(disc_id: str, initial: Manifest) -> ManifestDisc:
    disc = next((item for item in initial.discs if item.id == disc_id), None)
    if disc is None:
        raise ChaosLibrarianValueError(f"track references missing disc {disc_id!r}")
    return disc


def _require_track(track_id: str, initial: Manifest) -> ManifestTrack:
    track = next((item for item in initial.tracks if item.id == track_id), None)
    if track is None:
        raise ChaosLibrarianValueError(f"variant references missing track {track_id!r}")
    return track
