"""Per-entity report builders.

``build_report_set`` is a pure function: it takes the initial manifest,
the current manifest, and the journal, and returns a ``ReportSet`` of
sorted, immutable report tuples. Both ``run_plan`` (after the timeline
loop) and ``step_fixture`` (after each advance) call it; neither owns
any persistence. See ``engine/writer.py`` for that.

Iteration order is lexicographic on id so report files are bit-identical
for the same logical state.

Relationship lookups go through a ``_ReportIndex`` built once per manifest
(``_build_index``); the builders never re-scan the manifest's lists.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
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
    ManifestAsset,
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


@dataclass(frozen=True)
class _ReportIndex:
    """Pre-computed relationship lookups for one manifest.

    By-id maps cover identity lookups; the ``*_by_*`` maps hold child ids
    grouped under their parent and pre-sorted, so callers neither re-scan nor
    re-sort. ``current_version_by_asset`` keeps the highest-index version per
    asset; ``location_by_asset`` keeps the first location per asset (matching
    the prior linear-search semantics).
    """

    assets: dict[str, ManifestAsset]
    bundles: dict[str, ManifestBundle]
    variants: dict[str, ManifestVariant]
    movies: dict[str, ManifestMovie]
    series: dict[str, ManifestSeries]
    seasons: dict[str, ManifestSeason]
    episodes: dict[str, ManifestEpisode]
    artists: dict[str, ManifestArtist]
    albums: dict[str, ManifestAlbum]
    discs: dict[str, ManifestDisc]
    tracks: dict[str, ManifestTrack]
    bundle_id_by_variant: dict[str, str]
    asset_ids_by_bundle: dict[str, list[str]]
    variant_ids_by_parent: dict[tuple[ParentKind, str], list[str]]
    album_ids_by_artist: dict[str, list[str]]
    season_ids_by_series: dict[str, list[str]]
    episode_ids_by_season: dict[str, list[str]]
    disc_ids_by_album: dict[str, list[str]]
    track_ids_by_disc: dict[str, list[str]]
    sidecar_ids_by_asset: dict[str, list[str]]
    current_version_by_asset: dict[str, ManifestVersion]
    location_by_asset: dict[str, ManifestLocation]


def _group_ids[K](pairs: Iterable[tuple[K, str]]) -> dict[K, list[str]]:
    """Group ids under their key and sort each group lexicographically."""
    grouped: dict[K, list[str]] = {}
    for key, value in pairs:
        grouped.setdefault(key, []).append(value)
    return {key: sorted(values) for key, values in grouped.items()}


def _build_index(manifest: Manifest) -> _ReportIndex:
    current_version_by_asset: dict[str, ManifestVersion] = {}
    for version in manifest.versions:
        existing = current_version_by_asset.get(version.asset_id)
        if existing is None or version.index > existing.index:
            current_version_by_asset[version.asset_id] = version
    location_by_asset: dict[str, ManifestLocation] = {}
    for location in manifest.locations:
        location_by_asset.setdefault(location.asset_id, location)
    return _ReportIndex(
        assets={asset.id: asset for asset in manifest.assets},
        bundles={bundle.id: bundle for bundle in manifest.bundles},
        variants={variant.id: variant for variant in manifest.variants},
        movies={movie.id: movie for movie in manifest.movies},
        series={series.id: series for series in manifest.series},
        seasons={season.id: season for season in manifest.seasons},
        episodes={episode.id: episode for episode in manifest.episodes},
        artists={artist.id: artist for artist in manifest.artists},
        albums={album.id: album for album in manifest.albums},
        discs={disc.id: disc for disc in manifest.discs},
        tracks={track.id: track for track in manifest.tracks},
        bundle_id_by_variant={bundle.variant_id: bundle.id for bundle in manifest.bundles},
        asset_ids_by_bundle=_group_ids((asset.bundle_id, asset.id) for asset in manifest.assets),
        variant_ids_by_parent=_group_ids(
            ((variant.parent_kind, variant.parent_id), variant.id) for variant in manifest.variants
        ),
        album_ids_by_artist=_group_ids((album.artist_id, album.id) for album in manifest.albums),
        season_ids_by_series=_group_ids(
            (season.series_id, season.id) for season in manifest.seasons
        ),
        episode_ids_by_season=_group_ids(
            (episode.season_id, episode.id) for episode in manifest.episodes
        ),
        disc_ids_by_album=_group_ids((disc.album_id, disc.id) for disc in manifest.discs),
        track_ids_by_disc=_group_ids((track.disc_id, track.id) for track in manifest.tracks),
        sidecar_ids_by_asset=_group_ids(
            (sidecar.asset_id, sidecar.id) for sidecar in manifest.sidecars
        ),
        current_version_by_asset=current_version_by_asset,
        location_by_asset=location_by_asset,
    )


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
    initial_index = _build_index(initial)
    current_index = _build_index(current)

    def sorted_reports[Row, Report](
        rows: Iterable[Row],
        builder: Callable[[Row, _ReportIndex], Report],
        key: Callable[[Report], str],
    ) -> tuple[Report, ...]:
        return tuple(sorted((builder(row, current_index) for row in rows), key=key))

    assets = tuple(
        sorted(
            (
                _build_asset_report(asset_id, initial_index, current_index, journal_list)
                for asset_id in initial_index.assets
            ),
            key=lambda a: a.asset_id,
        )
    )
    return ReportSet(
        assets=assets,
        movies=sorted_reports(
            current_index.movies.values(),
            _build_movie_report,
            lambda report: report.movie_id,
        ),
        series=sorted_reports(
            current_index.series.values(),
            _build_series_report,
            lambda report: report.series_id,
        ),
        seasons=sorted_reports(
            current_index.seasons.values(),
            _build_season_report,
            lambda report: report.season_id,
        ),
        episodes=sorted_reports(
            current_index.episodes.values(),
            _build_episode_report,
            lambda report: report.episode_id,
        ),
        artists=sorted_reports(
            current_index.artists.values(),
            _build_artist_report,
            lambda report: report.artist_id,
        ),
        albums=sorted_reports(
            current_index.albums.values(),
            _build_album_report,
            lambda report: report.album_id,
        ),
        discs=sorted_reports(
            current_index.discs.values(),
            _build_disc_report,
            lambda report: report.disc_id,
        ),
        tracks=sorted_reports(
            current_index.tracks.values(),
            _build_track_report,
            lambda report: report.track_id,
        ),
        variants=sorted_reports(
            current_index.variants.values(),
            _build_variant_report,
            lambda report: report.variant_id,
        ),
        bundles=sorted_reports(
            current_index.bundles.values(),
            _build_bundle_report,
            lambda report: report.bundle_id,
        ),
    )


def _snapshot_for(asset_id: str, index: _ReportIndex) -> AssetSnapshot | None:
    version = index.current_version_by_asset.get(asset_id)
    if version is None:
        return None
    location = index.location_by_asset.get(asset_id)
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


def _build_asset_report(
    asset_id: str,
    initial: _ReportIndex,
    current: _ReportIndex,
    journal: list[JournalEntry],
) -> AssetReport:
    initial_snapshot = _snapshot_for(asset_id, initial)
    if initial_snapshot is None:
        raise ChaosLibrarianValueError(f"asset {asset_id} missing from initial manifest")
    bundle = _bundle_for_asset(asset_id, initial)
    variant = _variant_for_bundle(bundle, current)
    topology = _asset_topology_for(variant, current)
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


def _build_movie_report(movie: ManifestMovie, index: _ReportIndex) -> MovieReport:
    variant_ids = _variant_ids_for_parent(index, ParentKind.MOVIE, movie.id)
    return MovieReport(
        schema_version=MOVIE_REPORT_SCHEMA_VERSION,
        movie_id=movie.id,
        title=movie.title,
        variant_ids=variant_ids,
        asset_ids=_asset_ids_for_variants(index, variant_ids),
    )


def _build_series_report(series: ManifestSeries, index: _ReportIndex) -> SeriesReport:
    season_ids = index.season_ids_by_series.get(series.id, [])
    episode_ids = _episode_ids_for_seasons(index, season_ids)
    return SeriesReport(
        schema_version=SERIES_REPORT_SCHEMA_VERSION,
        series_id=series.id,
        title=series.title,
        season_ids=season_ids,
        episode_ids=episode_ids,
        asset_ids=_asset_ids_for_parents(index, ParentKind.EPISODE, episode_ids),
    )


def _build_season_report(season: ManifestSeason, index: _ReportIndex) -> SeasonReport:
    episode_ids = _episode_ids_for_seasons(index, [season.id])
    return SeasonReport(
        schema_version=SEASON_REPORT_SCHEMA_VERSION,
        season_id=season.id,
        series_id=season.series_id,
        season_number=season.season_number,
        title=season.title,
        episode_ids=episode_ids,
        asset_ids=_asset_ids_for_parents(index, ParentKind.EPISODE, episode_ids),
    )


def _build_episode_report(episode: ManifestEpisode, index: _ReportIndex) -> EpisodeReport:
    variant_ids = _variant_ids_for_parent(index, ParentKind.EPISODE, episode.id)
    return EpisodeReport(
        schema_version=EPISODE_REPORT_SCHEMA_VERSION,
        episode_id=episode.id,
        season_id=episode.season_id,
        episode_number=episode.episode_number,
        title=episode.title,
        aired_on=episode.aired_on,
        absolute_number=episode.absolute_number,
        variant_ids=variant_ids,
        asset_ids=_asset_ids_for_variants(index, variant_ids),
    )


def _build_artist_report(artist: ManifestArtist, index: _ReportIndex) -> ArtistReport:
    album_ids = index.album_ids_by_artist.get(artist.id, [])
    disc_ids = _disc_ids_for_albums(index, album_ids)
    track_ids = _track_ids_for_discs(index, disc_ids)
    return ArtistReport(
        schema_version=ARTIST_REPORT_SCHEMA_VERSION,
        artist_id=artist.id,
        name=artist.name,
        album_ids=album_ids,
        track_ids=track_ids,
        asset_ids=_asset_ids_for_parents(index, ParentKind.TRACK, track_ids),
    )


def _build_album_report(album: ManifestAlbum, index: _ReportIndex) -> AlbumReport:
    disc_ids = _disc_ids_for_albums(index, [album.id])
    track_ids = _track_ids_for_discs(index, disc_ids)
    return AlbumReport(
        schema_version=ALBUM_REPORT_SCHEMA_VERSION,
        album_id=album.id,
        artist_id=album.artist_id,
        title=album.title,
        release_year=album.release_year,
        disc_ids=disc_ids,
        track_ids=track_ids,
        asset_ids=_asset_ids_for_parents(index, ParentKind.TRACK, track_ids),
    )


def _build_disc_report(disc: ManifestDisc, index: _ReportIndex) -> DiscReport:
    track_ids = _track_ids_for_discs(index, [disc.id])
    return DiscReport(
        schema_version=DISC_REPORT_SCHEMA_VERSION,
        disc_id=disc.id,
        album_id=disc.album_id,
        disc_number=disc.disc_number,
        track_ids=track_ids,
        asset_ids=_asset_ids_for_parents(index, ParentKind.TRACK, track_ids),
    )


def _build_track_report(track: ManifestTrack, index: _ReportIndex) -> TrackReport:
    variant_ids = _variant_ids_for_parent(index, ParentKind.TRACK, track.id)
    return TrackReport(
        schema_version=TRACK_REPORT_SCHEMA_VERSION,
        track_id=track.id,
        disc_id=track.disc_id,
        track_number=track.track_number,
        title=track.title,
        performers=list(track.performers),
        variant_ids=variant_ids,
        asset_ids=_asset_ids_for_variants(index, variant_ids),
    )


def _build_variant_report(variant: ManifestVariant, index: _ReportIndex) -> VariantReport:
    bundle = _bundle_for_variant(variant.id, index)
    return VariantReport(
        schema_version=VARIANT_REPORT_SCHEMA_VERSION,
        variant_id=variant.id,
        parent_kind=variant.parent_kind,
        parent_id=variant.parent_id,
        label=variant.label,
        bundle_id=bundle.id,
        asset_ids=index.asset_ids_by_bundle.get(bundle.id, []),
    )


def _build_bundle_report(bundle: ManifestBundle, index: _ReportIndex) -> BundleReport:
    asset_ids = index.asset_ids_by_bundle.get(bundle.id, [])
    sidecar_ids: list[str] = []
    for asset_id in asset_ids:
        sidecar_ids.extend(index.sidecar_ids_by_asset.get(asset_id, []))
    return BundleReport(
        schema_version=BUNDLE_REPORT_SCHEMA_VERSION,
        bundle_id=bundle.id,
        variant_id=bundle.variant_id,
        asset_ids=asset_ids,
        sidecar_ids=sorted(sidecar_ids),
    )


def _variant_ids_for_parent(
    index: _ReportIndex,
    parent_kind: ParentKind,
    parent_id: str,
) -> list[str]:
    return index.variant_ids_by_parent.get((parent_kind, parent_id), [])


def _asset_ids_for_parents(
    index: _ReportIndex,
    parent_kind: ParentKind,
    parent_ids: Iterable[str],
) -> list[str]:
    asset_ids: list[str] = []
    for parent_id in parent_ids:
        variant_ids = _variant_ids_for_parent(index, parent_kind, parent_id)
        asset_ids.extend(_asset_ids_for_variants(index, variant_ids))
    return sorted(asset_ids)


def _asset_ids_for_variants(index: _ReportIndex, variant_ids: Iterable[str]) -> list[str]:
    asset_ids: list[str] = []
    for variant_id in variant_ids:
        bundle = _bundle_for_variant(variant_id, index)
        asset_ids.extend(index.asset_ids_by_bundle.get(bundle.id, []))
    return sorted(asset_ids)


def _episode_ids_for_seasons(index: _ReportIndex, season_ids: Iterable[str]) -> list[str]:
    episode_ids: list[str] = []
    for season_id in season_ids:
        episode_ids.extend(index.episode_ids_by_season.get(season_id, []))
    return sorted(episode_ids)


def _disc_ids_for_albums(index: _ReportIndex, album_ids: Iterable[str]) -> list[str]:
    disc_ids: list[str] = []
    for album_id in album_ids:
        disc_ids.extend(index.disc_ids_by_album.get(album_id, []))
    return sorted(disc_ids)


def _track_ids_for_discs(index: _ReportIndex, disc_ids: Iterable[str]) -> list[str]:
    track_ids: list[str] = []
    for disc_id in disc_ids:
        track_ids.extend(index.track_ids_by_disc.get(disc_id, []))
    return sorted(track_ids)


def _bundle_for_asset(asset_id: str, index: _ReportIndex) -> ManifestBundle:
    asset = index.assets.get(asset_id)
    if asset is None:
        raise ChaosLibrarianValueError(f"asset {asset_id} missing from initial manifest")
    bundle = index.bundles.get(asset.bundle_id)
    if bundle is None:
        raise ChaosLibrarianValueError(f"asset {asset_id} references missing bundle")
    return bundle


def _variant_for_bundle(bundle: ManifestBundle, index: _ReportIndex) -> ManifestVariant:
    variant = index.variants.get(bundle.variant_id)
    if variant is None:
        raise ChaosLibrarianValueError(f"bundle {bundle.id} references missing variant")
    return variant


def _bundle_for_variant(variant_id: str, index: _ReportIndex) -> ManifestBundle:
    bundle_id = index.bundle_id_by_variant.get(variant_id)
    if bundle_id is None:
        raise ChaosLibrarianValueError(f"variant {variant_id} has no bundle")
    return index.bundles[bundle_id]


def _asset_topology_for(variant: ManifestVariant, index: _ReportIndex) -> _AssetTopology:
    if variant.parent_kind is ParentKind.MOVIE:
        _require_movie(variant.parent_id, index)
        return _AssetTopology(movie_id=variant.parent_id)
    if variant.parent_kind is ParentKind.EPISODE:
        episode = _require_episode(variant.parent_id, index)
        season = _require_season(episode.season_id, index)
        series = _require_series(season.series_id, index)
        return _AssetTopology(
            series_id=series.id,
            season_id=season.id,
            episode_id=episode.id,
        )
    if variant.parent_kind is ParentKind.TRACK:
        track = _require_track(variant.parent_id, index)
        disc = _require_disc(track.disc_id, index)
        album = _require_album(disc.album_id, index)
        artist = _require_artist(album.artist_id, index)
        return _AssetTopology(
            artist_id=artist.id,
            album_id=album.id,
            disc_id=disc.id,
            track_id=track.id,
        )
    raise ChaosLibrarianValueError(f"unsupported variant parent kind: {variant.parent_kind}")


def _require_movie(movie_id: str, index: _ReportIndex) -> ManifestMovie:
    movie = index.movies.get(movie_id)
    if movie is None:
        raise ChaosLibrarianValueError(f"variant references missing movie {movie_id!r}")
    return movie


def _require_series(series_id: str, index: _ReportIndex) -> ManifestSeries:
    series = index.series.get(series_id)
    if series is None:
        raise ChaosLibrarianValueError(f"season references missing series {series_id!r}")
    return series


def _require_season(season_id: str, index: _ReportIndex) -> ManifestSeason:
    season = index.seasons.get(season_id)
    if season is None:
        raise ChaosLibrarianValueError(f"episode references missing season {season_id!r}")
    return season


def _require_episode(episode_id: str, index: _ReportIndex) -> ManifestEpisode:
    episode = index.episodes.get(episode_id)
    if episode is None:
        raise ChaosLibrarianValueError(f"variant references missing episode {episode_id!r}")
    return episode


def _require_artist(artist_id: str, index: _ReportIndex) -> ManifestArtist:
    artist = index.artists.get(artist_id)
    if artist is None:
        raise ChaosLibrarianValueError(f"album references missing artist {artist_id!r}")
    return artist


def _require_album(album_id: str, index: _ReportIndex) -> ManifestAlbum:
    album = index.albums.get(album_id)
    if album is None:
        raise ChaosLibrarianValueError(f"disc references missing album {album_id!r}")
    return album


def _require_disc(disc_id: str, index: _ReportIndex) -> ManifestDisc:
    disc = index.discs.get(disc_id)
    if disc is None:
        raise ChaosLibrarianValueError(f"track references missing disc {disc_id!r}")
    return disc


def _require_track(track_id: str, index: _ReportIndex) -> ManifestTrack:
    track = index.tracks.get(track_id)
    if track is None:
        raise ChaosLibrarianValueError(f"variant references missing track {track_id!r}")
    return track
