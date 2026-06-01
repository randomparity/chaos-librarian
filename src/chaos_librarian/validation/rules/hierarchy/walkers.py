"""Raw hierarchy walkers shared by validation rules."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Final

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.validation.rules.core.raw_helpers import (
    _as_list,
    _as_mapping,
    _list_at_path,
    _Loc,
    _RawMapping,
)


@dataclass(frozen=True, slots=True)
class RawAssetContext:
    """One raw asset plus its surrounding hierarchy and YAML-path locations."""

    asset: _RawMapping
    asset_loc: _Loc
    parent_kind: str
    parent_id: str
    movie: _RawMapping | None
    movie_loc: _Loc | None
    series: _RawMapping | None
    series_loc: _Loc | None
    season: _RawMapping | None
    season_loc: _Loc | None
    episode: _RawMapping | None
    episode_loc: _Loc | None
    artist: _RawMapping | None
    artist_loc: _Loc | None
    album: _RawMapping | None
    album_loc: _Loc | None
    disc: _RawMapping | None
    disc_loc: _Loc | None
    track: _RawMapping | None
    track_loc: _Loc | None
    podcast: _RawMapping | None = None
    podcast_loc: _Loc | None = None
    podcast_episode: _RawMapping | None = None
    podcast_episode_loc: _Loc | None = None
    variant: _RawMapping = field(default_factory=dict)
    variant_loc: _Loc = ()
    bundle: _RawMapping = field(default_factory=dict)
    bundle_loc: _Loc = ()
    bundle_asset_count: int = 0


# Typo-safe namespace keys for ``iter_global_namespaces`` callers — string
# literals would silently break the namespace filter / per-namespace dicts.
NS_MOVIE_ID: Final = "movie_id"
NS_SERIES_ID: Final = "series_id"
NS_SEASON_ID: Final = "season_id"
NS_EPISODE_ID: Final = "episode_id"
NS_ARTIST_ID: Final = "artist_id"
NS_ALBUM_ID: Final = "album_id"
NS_DISC_ID: Final = "disc_id"
NS_TRACK_ID: Final = "track_id"
NS_PODCAST_ID: Final = "podcast_id"
NS_PODCAST_EPISODE_ID: Final = "podcast_episode_id"
NS_VARIANT_ID: Final = "variant_id"
NS_BUNDLE_ID: Final = "bundle_id"
NS_ASSET_ID: Final = "asset_id"


def iter_declared_roots(raw: _RawMapping) -> Iterator[tuple[str, str | None]]:
    """Yield ``(root_id, root_path)`` for each well-shaped ``library.roots[]`` entry.

    ``root_id`` is guaranteed to be a string (entries with non-string ids
    are skipped — Pydantic's shape pass owns those errors). ``root_path``
    is ``None`` when the entry's ``path`` field is missing or non-string;
    callers needing both fields filter on ``p is not None``.
    """
    for root_obj in _list_at_path(raw, ("library", "roots")) or []:
        root = _as_mapping(root_obj)
        if root is None:
            continue
        root_id = root.get("id")
        if not isinstance(root_id, str):
            continue
        path = root.get("path")
        yield root_id, path if isinstance(path, str) else None


def primary_root_path(raw: _RawMapping) -> str | None:
    """Return ``library.roots[0].path`` if well-shaped, else ``None``.

    Mirrors ``build_initial_state``'s primary-root convention: the engine
    synthesizes every initial asset location under
    ``<library.roots[0].path>/...``. Strictly inspects the *first* entry —
    if it's malformed, returns ``None`` rather than falling through to a
    later root (the engine would have failed on ``roots[0]`` too). Returns
    ``None`` when the library is empty or the first entry's path doesn't
    narrow to a string — Pydantic's shape pass owns those errors.
    """
    roots = _list_at_path(raw, ("library", "roots")) or []
    if not roots:
        return None
    primary = _as_mapping(roots[0])
    if primary is None:
        return None
    path = primary.get("path")
    return path if isinstance(path, str) else None


def iter_global_namespaces(
    raw: _RawMapping,
) -> Iterator[tuple[str, str, _Loc]]:
    """Yield ``(namespace, id_value, loc)`` for every hierarchy and tail id.

    Walks the current Scenario movie, series, and artist hierarchy tails in
    declaration order and skips malformed sub-trees whose shape Pydantic would
    have rejected. Root and timeline ids are intentionally handled by
    ``id_duplicate.py``.
    """
    yield from iter_entity_ids(raw)


def iter_asset_ids(raw: _RawMapping) -> Iterator[str]:
    """Yield every ``asset_id`` value defined in the scenario.

    Implemented as a filter over ``iter_asset_contexts`` so asset-targeted
    rules share exactly one raw hierarchy traversal.
    """
    for context in iter_asset_contexts(raw):
        asset_id = context.asset.get("id")
        if isinstance(asset_id, str):
            yield asset_id


def iter_assets_with_loc(
    raw: _RawMapping,
) -> Iterator[tuple[_RawMapping, _Loc]]:
    """Yield ``(asset_mapping, loc)`` for every well-shaped asset.

    Reuses ``iter_asset_contexts`` so rules inspect a single Scenario
    hierarchy walk.
    """
    for context in iter_asset_contexts(raw):
        yield context.asset, context.asset_loc


def iter_entity_ids(raw: _RawMapping) -> Iterator[tuple[str, str, _Loc]]:
    """Yield hierarchy and tail ids in declaration order with raw locations."""
    yield from _iter_movie_entity_ids(raw)
    yield from _iter_series_entity_ids(raw)
    yield from _iter_artist_entity_ids(raw)
    yield from _iter_podcast_entity_ids(raw)


def entity_ids_by_kind(raw: _RawMapping) -> dict[str, set[str]]:
    """Return ``kind -> ids`` for hierarchy and tail ids."""
    ids: dict[str, set[str]] = {
        "movie": set(),
        "series": set(),
        "season": set(),
        "episode": set(),
        "artist": set(),
        "album": set(),
        "disc": set(),
        "track": set(),
        "podcast": set(),
        "podcast_episode": set(),
        "variant": set(),
        "bundle": set(),
        "asset": set(),
    }
    for namespace, value, _loc in iter_global_namespaces(raw):
        kind = namespace.removesuffix("_id")
        ids[kind].add(value)
    return ids


def iter_asset_contexts(raw: _RawMapping) -> Iterator[RawAssetContext]:
    """Yield every well-shaped raw asset context in declaration order."""
    yield from _iter_movie_asset_contexts(raw)
    yield from _iter_episode_asset_contexts(raw)
    yield from _iter_track_asset_contexts(raw)
    yield from _iter_podcast_episode_asset_contexts(raw)


def _iter_movie_entity_ids(raw: _RawMapping) -> Iterator[tuple[str, str, _Loc]]:
    movies = _as_list(raw.get("movies"))
    if movies is None:
        return
    for m_idx, movie_obj in enumerate(movies):
        movie = _as_mapping(movie_obj)
        if movie is None:
            continue
        movie_loc: _Loc = ("movies", m_idx)
        yield from _entity_id(movie, namespace=NS_MOVIE_ID, loc=movie_loc)
        yield from _iter_variant_entity_ids(
            movie.get("variants"), variants_path=(*movie_loc, "variants")
        )


def _iter_series_entity_ids(raw: _RawMapping) -> Iterator[tuple[str, str, _Loc]]:
    series_items = _as_list(raw.get("series"))
    if series_items is None:
        return
    for s_idx, series_obj in enumerate(series_items):
        series = _as_mapping(series_obj)
        if series is None:
            continue
        series_loc: _Loc = ("series", s_idx)
        yield from _entity_id(series, namespace=NS_SERIES_ID, loc=series_loc)
        seasons = _as_list(series.get("seasons"))
        if seasons is None:
            continue
        for season_idx, season_obj in enumerate(seasons):
            season = _as_mapping(season_obj)
            if season is None:
                continue
            season_loc = (*series_loc, "seasons", season_idx)
            yield from _entity_id(season, namespace=NS_SEASON_ID, loc=season_loc)
            yield from _iter_episode_entity_ids(season, season_loc=season_loc)


def _iter_episode_entity_ids(
    season: _RawMapping, *, season_loc: _Loc
) -> Iterator[tuple[str, str, _Loc]]:
    episodes = _as_list(season.get("episodes"))
    if episodes is None:
        return
    for ep_idx, episode_obj in enumerate(episodes):
        episode = _as_mapping(episode_obj)
        if episode is None:
            continue
        episode_loc = (*season_loc, "episodes", ep_idx)
        yield from _entity_id(episode, namespace=NS_EPISODE_ID, loc=episode_loc)
        yield from _iter_variant_entity_ids(
            episode.get("variants"), variants_path=(*episode_loc, "variants")
        )


def _iter_artist_entity_ids(raw: _RawMapping) -> Iterator[tuple[str, str, _Loc]]:
    artists = _as_list(raw.get("artists"))
    if artists is None:
        return
    for artist_idx, artist_obj in enumerate(artists):
        artist = _as_mapping(artist_obj)
        if artist is None:
            continue
        artist_loc: _Loc = ("artists", artist_idx)
        yield from _entity_id(artist, namespace=NS_ARTIST_ID, loc=artist_loc)
        albums = _as_list(artist.get("albums"))
        if albums is None:
            continue
        for album_idx, album_obj in enumerate(albums):
            album = _as_mapping(album_obj)
            if album is None:
                continue
            album_loc = (*artist_loc, "albums", album_idx)
            yield from _entity_id(album, namespace=NS_ALBUM_ID, loc=album_loc)
            yield from _iter_disc_entity_ids(album, album_loc=album_loc)


def _iter_disc_entity_ids(
    album: _RawMapping, *, album_loc: _Loc
) -> Iterator[tuple[str, str, _Loc]]:
    discs = _as_list(album.get("discs"))
    if discs is None:
        return
    for disc_idx, disc_obj in enumerate(discs):
        disc = _as_mapping(disc_obj)
        if disc is None:
            continue
        disc_loc = (*album_loc, "discs", disc_idx)
        yield from _entity_id(disc, namespace=NS_DISC_ID, loc=disc_loc)
        yield from _iter_track_entity_ids(disc, disc_loc=disc_loc)


def _iter_track_entity_ids(disc: _RawMapping, *, disc_loc: _Loc) -> Iterator[tuple[str, str, _Loc]]:
    tracks = _as_list(disc.get("tracks"))
    if tracks is None:
        return
    for track_idx, track_obj in enumerate(tracks):
        track = _as_mapping(track_obj)
        if track is None:
            continue
        track_loc = (*disc_loc, "tracks", track_idx)
        yield from _entity_id(track, namespace=NS_TRACK_ID, loc=track_loc)
        yield from _iter_variant_entity_ids(
            track.get("variants"), variants_path=(*track_loc, "variants")
        )


def _iter_podcast_entity_ids(raw: _RawMapping) -> Iterator[tuple[str, str, _Loc]]:
    podcasts = _as_list(raw.get("podcasts"))
    if podcasts is None:
        return
    for podcast_idx, podcast_obj in enumerate(podcasts):
        podcast = _as_mapping(podcast_obj)
        if podcast is None:
            continue
        podcast_loc: _Loc = ("podcasts", podcast_idx)
        yield from _entity_id(podcast, namespace=NS_PODCAST_ID, loc=podcast_loc)
        episodes = _as_list(podcast.get("episodes"))
        if episodes is None:
            continue
        for ep_idx, episode_obj in enumerate(episodes):
            episode = _as_mapping(episode_obj)
            if episode is None:
                continue
            episode_loc = (*podcast_loc, "episodes", ep_idx)
            yield from _entity_id(episode, namespace=NS_PODCAST_EPISODE_ID, loc=episode_loc)
            yield from _iter_variant_entity_ids(
                episode.get("variants"), variants_path=(*episode_loc, "variants")
            )


def _entity_id(
    entity: _RawMapping, *, namespace: str, loc: _Loc
) -> Iterator[tuple[str, str, _Loc]]:
    value = entity.get("id")
    if isinstance(value, str):
        yield namespace, value, (*loc, "id")


def _iter_variant_entity_ids(
    variants_obj: object, *, variants_path: _Loc
) -> Iterator[tuple[str, str, _Loc]]:
    variants = _as_list(variants_obj)
    if variants is None:
        return
    for v_idx, variant_obj in enumerate(variants):
        variant = _as_mapping(variant_obj)
        if variant is None:
            continue
        variant_loc = (*variants_path, v_idx)
        yield from _entity_id(variant, namespace=NS_VARIANT_ID, loc=variant_loc)
        bundle = _as_mapping(variant.get("bundle"))
        if bundle is None:
            continue
        bundle_loc = (*variant_loc, "bundle")
        yield from _entity_id(bundle, namespace=NS_BUNDLE_ID, loc=bundle_loc)
        yield from _iter_bundle_assets(bundle.get("assets"), bundle_path=bundle_loc)


def _iter_bundle_assets(
    assets_obj: object, *, bundle_path: _Loc
) -> Iterator[tuple[str, str, _Loc]]:
    """Yield asset ids for each well-shaped asset under one bundle."""
    assets = _as_list(assets_obj)
    if assets is None:
        return
    for a_idx, asset_obj in enumerate(assets):
        asset = _as_mapping(asset_obj)
        if asset is None:
            continue
        a_id = asset.get("id")
        if isinstance(a_id, str):
            yield NS_ASSET_ID, a_id, (*bundle_path, "assets", a_idx, "id")


def _iter_movie_asset_contexts(raw: _RawMapping) -> Iterator[RawAssetContext]:
    movies = _as_list(raw.get("movies"))
    if movies is None:
        return
    for m_idx, movie_obj in enumerate(movies):
        movie = _as_mapping(movie_obj)
        if movie is None:
            continue
        movie_loc: _Loc = ("movies", m_idx)
        for tail in _iter_variant_asset_tail(movie.get("variants"), (*movie_loc, "variants")):
            yield RawAssetContext(
                asset=tail.asset,
                asset_loc=tail.asset_loc,
                parent_kind=ParentKind.MOVIE.value,
                parent_id=_id_or_empty(movie),
                movie=movie,
                movie_loc=movie_loc,
                series=None,
                series_loc=None,
                season=None,
                season_loc=None,
                episode=None,
                episode_loc=None,
                artist=None,
                artist_loc=None,
                album=None,
                album_loc=None,
                disc=None,
                disc_loc=None,
                track=None,
                track_loc=None,
                variant=tail.variant,
                variant_loc=tail.variant_loc,
                bundle=tail.bundle,
                bundle_loc=tail.bundle_loc,
                bundle_asset_count=tail.bundle_asset_count,
            )


def _iter_episode_asset_contexts(raw: _RawMapping) -> Iterator[RawAssetContext]:
    series_items = _as_list(raw.get("series"))
    if series_items is None:
        return
    for s_idx, series_obj in enumerate(series_items):
        series = _as_mapping(series_obj)
        if series is None:
            continue
        series_loc: _Loc = ("series", s_idx)
        yield from _iter_series_asset_contexts(series, series_loc=series_loc)


def _iter_series_asset_contexts(
    series: _RawMapping, *, series_loc: _Loc
) -> Iterator[RawAssetContext]:
    seasons = _as_list(series.get("seasons"))
    if seasons is None:
        return
    for season_idx, season_obj in enumerate(seasons):
        season = _as_mapping(season_obj)
        if season is None:
            continue
        season_loc = (*series_loc, "seasons", season_idx)
        yield from _iter_season_asset_contexts(
            series, series_loc=series_loc, season=season, season_loc=season_loc
        )


def _iter_season_asset_contexts(
    series: _RawMapping,
    *,
    series_loc: _Loc,
    season: _RawMapping,
    season_loc: _Loc,
) -> Iterator[RawAssetContext]:
    episodes = _as_list(season.get("episodes"))
    if episodes is None:
        return
    for ep_idx, episode_obj in enumerate(episodes):
        episode = _as_mapping(episode_obj)
        if episode is None:
            continue
        episode_loc = (*season_loc, "episodes", ep_idx)
        for tail in _iter_variant_asset_tail(episode.get("variants"), (*episode_loc, "variants")):
            yield RawAssetContext(
                asset=tail.asset,
                asset_loc=tail.asset_loc,
                parent_kind=ParentKind.EPISODE.value,
                parent_id=_id_or_empty(episode),
                movie=None,
                movie_loc=None,
                series=series,
                series_loc=series_loc,
                season=season,
                season_loc=season_loc,
                episode=episode,
                episode_loc=episode_loc,
                artist=None,
                artist_loc=None,
                album=None,
                album_loc=None,
                disc=None,
                disc_loc=None,
                track=None,
                track_loc=None,
                variant=tail.variant,
                variant_loc=tail.variant_loc,
                bundle=tail.bundle,
                bundle_loc=tail.bundle_loc,
                bundle_asset_count=tail.bundle_asset_count,
            )


def _iter_track_asset_contexts(raw: _RawMapping) -> Iterator[RawAssetContext]:
    artists = _as_list(raw.get("artists"))
    if artists is None:
        return
    for artist_idx, artist_obj in enumerate(artists):
        artist = _as_mapping(artist_obj)
        if artist is None:
            continue
        artist_loc: _Loc = ("artists", artist_idx)
        yield from _iter_artist_asset_contexts(artist, artist_loc=artist_loc)


def _iter_artist_asset_contexts(
    artist: _RawMapping, *, artist_loc: _Loc
) -> Iterator[RawAssetContext]:
    albums = _as_list(artist.get("albums"))
    if albums is None:
        return
    for album_idx, album_obj in enumerate(albums):
        album = _as_mapping(album_obj)
        if album is None:
            continue
        album_loc = (*artist_loc, "albums", album_idx)
        yield from _iter_album_asset_contexts(
            artist, artist_loc=artist_loc, album=album, album_loc=album_loc
        )


def _iter_album_asset_contexts(
    artist: _RawMapping,
    *,
    artist_loc: _Loc,
    album: _RawMapping,
    album_loc: _Loc,
) -> Iterator[RawAssetContext]:
    discs = _as_list(album.get("discs"))
    if discs is None:
        return
    for disc_idx, disc_obj in enumerate(discs):
        disc = _as_mapping(disc_obj)
        if disc is None:
            continue
        disc_loc = (*album_loc, "discs", disc_idx)
        yield from _iter_disc_asset_contexts(
            artist=artist,
            artist_loc=artist_loc,
            album=album,
            album_loc=album_loc,
            disc=disc,
            disc_loc=disc_loc,
        )


def _iter_disc_asset_contexts(
    *,
    artist: _RawMapping,
    artist_loc: _Loc,
    album: _RawMapping,
    album_loc: _Loc,
    disc: _RawMapping,
    disc_loc: _Loc,
) -> Iterator[RawAssetContext]:
    tracks = _as_list(disc.get("tracks"))
    if tracks is None:
        return
    for track_idx, track_obj in enumerate(tracks):
        track = _as_mapping(track_obj)
        if track is None:
            continue
        track_loc = (*disc_loc, "tracks", track_idx)
        for tail in _iter_variant_asset_tail(track.get("variants"), (*track_loc, "variants")):
            yield RawAssetContext(
                asset=tail.asset,
                asset_loc=tail.asset_loc,
                parent_kind=ParentKind.TRACK.value,
                parent_id=_id_or_empty(track),
                movie=None,
                movie_loc=None,
                series=None,
                series_loc=None,
                season=None,
                season_loc=None,
                episode=None,
                episode_loc=None,
                artist=artist,
                artist_loc=artist_loc,
                album=album,
                album_loc=album_loc,
                disc=disc,
                disc_loc=disc_loc,
                track=track,
                track_loc=track_loc,
                variant=tail.variant,
                variant_loc=tail.variant_loc,
                bundle=tail.bundle,
                bundle_loc=tail.bundle_loc,
                bundle_asset_count=tail.bundle_asset_count,
            )


def _iter_podcast_episode_asset_contexts(raw: _RawMapping) -> Iterator[RawAssetContext]:
    podcasts = _as_list(raw.get("podcasts"))
    if podcasts is None:
        return
    for podcast_idx, podcast_obj in enumerate(podcasts):
        podcast = _as_mapping(podcast_obj)
        if podcast is None:
            continue
        podcast_loc: _Loc = ("podcasts", podcast_idx)
        yield from _iter_podcast_episode_contexts(podcast, podcast_loc=podcast_loc)


def _iter_podcast_episode_contexts(
    podcast: _RawMapping, *, podcast_loc: _Loc
) -> Iterator[RawAssetContext]:
    episodes = _as_list(podcast.get("episodes"))
    if episodes is None:
        return
    for ep_idx, episode_obj in enumerate(episodes):
        episode = _as_mapping(episode_obj)
        if episode is None:
            continue
        episode_loc = (*podcast_loc, "episodes", ep_idx)
        for tail in _iter_variant_asset_tail(episode.get("variants"), (*episode_loc, "variants")):
            yield RawAssetContext(
                asset=tail.asset,
                asset_loc=tail.asset_loc,
                parent_kind=ParentKind.PODCAST_EPISODE.value,
                parent_id=_id_or_empty(episode),
                movie=None,
                movie_loc=None,
                series=None,
                series_loc=None,
                season=None,
                season_loc=None,
                episode=None,
                episode_loc=None,
                artist=None,
                artist_loc=None,
                album=None,
                album_loc=None,
                disc=None,
                disc_loc=None,
                track=None,
                track_loc=None,
                podcast=podcast,
                podcast_loc=podcast_loc,
                podcast_episode=episode,
                podcast_episode_loc=episode_loc,
                variant=tail.variant,
                variant_loc=tail.variant_loc,
                bundle=tail.bundle,
                bundle_loc=tail.bundle_loc,
                bundle_asset_count=tail.bundle_asset_count,
            )


@dataclass(frozen=True, slots=True)
class _RawTailContext:
    asset: _RawMapping
    asset_loc: _Loc
    variant: _RawMapping
    variant_loc: _Loc
    bundle: _RawMapping
    bundle_loc: _Loc
    bundle_asset_count: int


def _iter_variant_asset_tail(
    variants_obj: object, variants_path: _Loc
) -> Iterator[_RawTailContext]:
    variants = _as_list(variants_obj)
    if variants is None:
        return
    for v_idx, variant_obj in enumerate(variants):
        variant = _as_mapping(variant_obj)
        if variant is None:
            continue
        variant_loc = (*variants_path, v_idx)
        bundle = _as_mapping(variant.get("bundle"))
        if bundle is None:
            continue
        bundle_loc = (*variant_loc, "bundle")
        assets = _as_list(bundle.get("assets"))
        if assets is None:
            continue
        for a_idx, asset_obj in enumerate(assets):
            asset = _as_mapping(asset_obj)
            if asset is None:
                continue
            yield _RawTailContext(
                asset=asset,
                asset_loc=(*bundle_loc, "assets", a_idx),
                variant=variant,
                variant_loc=variant_loc,
                bundle=bundle,
                bundle_loc=bundle_loc,
                bundle_asset_count=len(assets),
            )


def _id_or_empty(mapping: _RawMapping) -> str:
    value = mapping.get("id")
    return value if isinstance(value, str) else ""
