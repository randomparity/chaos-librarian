"""Typed topology walkers for scenario hierarchy contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Protocol

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    Album,
    Artist,
    ArtistLayout,
    Asset,
    Bundle,
    Disc,
    Episode,
    EpisodeNaming,
    Movie,
    MovieLayout,
    Podcast,
    PodcastEpisode,
    PodcastEpisodeNaming,
    PodcastLayout,
    Scenario,
    Season,
    Series,
    SeriesLayout,
    Track,
    TrackNaming,
    Variant,
)
from chaos_librarian.errors import ChaosLibrarianValueError
from chaos_librarian.path_rendering import RenderableAssetContext

__all__ = [
    "AssetContext",
    "asset_contexts_by_id",
    "asset_ids_under_target",
    "iter_asset_contexts",
    "renderable_asset_context",
]


@dataclass(frozen=True, slots=True)
class AssetContext:
    parent_kind: ParentKind
    parent_id: str
    movie: Movie | None
    series: Series | None
    season: Season | None
    episode: Episode | None
    artist: Artist | None
    album: Album | None
    disc: Disc | None
    track: Track | None
    podcast: Podcast | None
    podcast_episode: PodcastEpisode | None
    variant: Variant
    bundle: Bundle
    asset: Asset
    bundle_asset_count: int


class _Identified(Protocol):
    id: str


_TargetGetter = Callable[[AssetContext], _Identified | None]

_TARGET_GETTERS: dict[str, _TargetGetter] = {
    "movie": lambda context: context.movie,
    "series": lambda context: context.series,
    "season": lambda context: context.season,
    "episode": lambda context: context.episode,
    "artist": lambda context: context.artist,
    "album": lambda context: context.album,
    "disc": lambda context: context.disc,
    "track": lambda context: context.track,
    "podcast": lambda context: context.podcast,
    "podcast_episode": lambda context: context.podcast_episode,
    "variant": lambda context: context.variant,
    "bundle": lambda context: context.bundle,
    "asset": lambda context: context.asset,
}


def iter_asset_contexts(scenario: Scenario) -> Iterator[AssetContext]:
    """Yield every playable/listenable asset context in declaration order."""
    yield from _movie_asset_contexts(scenario)
    yield from _episode_asset_contexts(scenario)
    yield from _track_asset_contexts(scenario)
    yield from _podcast_episode_asset_contexts(scenario)


def _asset_context(
    *,
    parent_kind: ParentKind,
    parent_id: str,
    variant: Variant,
    bundle: Bundle,
    asset: Asset,
    movie: Movie | None = None,
    series: Series | None = None,
    season: Season | None = None,
    episode: Episode | None = None,
    artist: Artist | None = None,
    album: Album | None = None,
    disc: Disc | None = None,
    track: Track | None = None,
    podcast: Podcast | None = None,
    podcast_episode: PodcastEpisode | None = None,
) -> AssetContext:
    """Build an AssetContext, defaulting the irrelevant domain rows to None.

    Each walker passes only the domain objects on its branch; the rest stay
    None and ``bundle_asset_count`` is derived from the bundle.
    """
    return AssetContext(
        parent_kind=parent_kind,
        parent_id=parent_id,
        movie=movie,
        series=series,
        season=season,
        episode=episode,
        artist=artist,
        album=album,
        disc=disc,
        track=track,
        podcast=podcast,
        podcast_episode=podcast_episode,
        variant=variant,
        bundle=bundle,
        asset=asset,
        bundle_asset_count=len(bundle.assets),
    )


def _movie_asset_contexts(scenario: Scenario) -> Iterator[AssetContext]:
    for movie in scenario.movies:
        for variant in movie.variants:
            bundle = variant.bundle
            for asset in bundle.assets:
                yield _asset_context(
                    parent_kind=ParentKind.MOVIE,
                    parent_id=movie.id,
                    movie=movie,
                    variant=variant,
                    bundle=bundle,
                    asset=asset,
                )


def _episode_asset_contexts(scenario: Scenario) -> Iterator[AssetContext]:
    for series in scenario.series:
        for season in series.seasons:
            for episode in season.episodes:
                for variant in episode.variants:
                    bundle = variant.bundle
                    for asset in bundle.assets:
                        yield _asset_context(
                            parent_kind=ParentKind.EPISODE,
                            parent_id=episode.id,
                            series=series,
                            season=season,
                            episode=episode,
                            variant=variant,
                            bundle=bundle,
                            asset=asset,
                        )


def _track_asset_contexts(scenario: Scenario) -> Iterator[AssetContext]:
    for artist in scenario.artists:
        for album in artist.albums:
            for disc in album.discs:
                for track in disc.tracks:
                    for variant in track.variants:
                        bundle = variant.bundle
                        for asset in bundle.assets:
                            yield _asset_context(
                                parent_kind=ParentKind.TRACK,
                                parent_id=track.id,
                                artist=artist,
                                album=album,
                                disc=disc,
                                track=track,
                                variant=variant,
                                bundle=bundle,
                                asset=asset,
                            )


def _podcast_episode_asset_contexts(scenario: Scenario) -> Iterator[AssetContext]:
    for podcast in scenario.podcasts:
        for episode in podcast.episodes:
            for variant in episode.variants:
                bundle = variant.bundle
                for asset in bundle.assets:
                    yield _asset_context(
                        parent_kind=ParentKind.PODCAST_EPISODE,
                        parent_id=episode.id,
                        podcast=podcast,
                        podcast_episode=episode,
                        variant=variant,
                        bundle=bundle,
                        asset=asset,
                    )


def asset_contexts_by_id(scenario: Scenario) -> dict[str, AssetContext]:
    """Return asset id to context for every declared asset."""
    return {context.asset.id: context for context in iter_asset_contexts(scenario)}


def asset_ids_under_target(
    scenario: Scenario, *, target_kind: str, target_id: str
) -> tuple[str, ...]:
    """Return initially declared asset ids under a target in manifest order."""
    if target_kind not in _TARGET_GETTERS:
        raise ValueError(f"unknown target_kind: {target_kind}")

    matched: list[str] = []
    for context in iter_asset_contexts(scenario):
        if _context_matches_target(context, target_kind=target_kind, target_id=target_id):
            matched.append(context.asset.id)
    return tuple(matched)


def _context_matches_target(context: AssetContext, *, target_kind: str, target_id: str) -> bool:
    target = _TARGET_GETTERS[target_kind](context)
    return target is not None and target.id == target_id


def renderable_asset_context(context: AssetContext, root_path: str) -> RenderableAssetContext:
    """Convert a typed ``AssetContext`` plus ``root_path`` to a renderer input.

    The single source of the ``AssetContext -> RenderableAssetContext`` field
    copy, shared by engine initial-state and materializer synthesis so the two
    cannot drift. Path shape itself stays owned by ``path_rendering``.
    """
    return RenderableAssetContext(
        parent_kind=context.parent_kind,
        root_path=root_path,
        layout=_layout_for_context(context),
        naming=_naming_for_context(context),
        movie_title=context.movie.title if context.movie is not None else None,
        series_title=context.series.title if context.series is not None else None,
        season_number=context.season.season_number if context.season is not None else None,
        episode_number=context.episode.episode_number if context.episode is not None else None,
        episode_title=_episode_title_for_context(context),
        aired_on=context.episode.aired_on if context.episode is not None else None,
        absolute_number=context.episode.absolute_number if context.episode is not None else None,
        artist_name=context.artist.name if context.artist is not None else None,
        album_title=context.album.title if context.album is not None else None,
        disc_number=context.disc.disc_number if context.disc is not None else None,
        track_number=context.track.track_number if context.track is not None else None,
        track_title=context.track.title if context.track is not None else None,
        podcast_title=context.podcast.title if context.podcast is not None else None,
        published_at=(
            context.podcast_episode.published_at if context.podcast_episode is not None else None
        ),
        episode_slug=(
            context.podcast_episode.slug if context.podcast_episode is not None else None
        ),
        edition=context.variant.edition,
        variant_label=context.variant.label,
        asset_role=context.asset.role,
        asset_container=context.asset.container,
        bundle_asset_count=context.bundle_asset_count,
    )


def _layout_for_context(
    context: AssetContext,
) -> MovieLayout | SeriesLayout | ArtistLayout | PodcastLayout:
    if context.movie is not None:
        return context.movie.layout
    if context.series is not None:
        return context.series.layout
    if context.artist is not None:
        return context.artist.layout
    if context.podcast is not None:
        return context.podcast.layout
    raise ChaosLibrarianValueError(f"asset {context.asset.id} has no hierarchy layout")


def _naming_for_context(
    context: AssetContext,
) -> EpisodeNaming | TrackNaming | PodcastEpisodeNaming | None:
    if context.series is not None:
        return context.series.episode_naming
    if context.artist is not None:
        return context.artist.track_naming
    if context.podcast is not None:
        return context.podcast.episode_naming
    return None


def _episode_title_for_context(context: AssetContext) -> str | None:
    if context.episode is not None:
        return context.episode.title
    if context.podcast_episode is not None:
        return context.podcast_episode.title
    return None
