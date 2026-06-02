"""Typed topology walkers for scenario hierarchy contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final, Protocol

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
    "AssetContextBranch",
    "EpisodeAssetBranch",
    "MovieAssetBranch",
    "PodcastEpisodeAssetBranch",
    "TrackAssetBranch",
    "asset_contexts_by_id",
    "asset_ids_under_target",
    "iter_asset_contexts",
    "renderable_asset_context",
]


@dataclass(frozen=True, slots=True)
class MovieAssetBranch:
    movie: Movie

    @property
    def parent_kind(self) -> ParentKind:
        return ParentKind.MOVIE

    @property
    def parent_id(self) -> str:
        return self.movie.id


@dataclass(frozen=True, slots=True)
class EpisodeAssetBranch:
    series: Series
    season: Season
    episode: Episode

    @property
    def parent_kind(self) -> ParentKind:
        return ParentKind.EPISODE

    @property
    def parent_id(self) -> str:
        return self.episode.id


@dataclass(frozen=True, slots=True)
class TrackAssetBranch:
    artist: Artist
    album: Album
    disc: Disc
    track: Track

    @property
    def parent_kind(self) -> ParentKind:
        return ParentKind.TRACK

    @property
    def parent_id(self) -> str:
        return self.track.id


@dataclass(frozen=True, slots=True)
class PodcastEpisodeAssetBranch:
    podcast: Podcast
    podcast_episode: PodcastEpisode

    @property
    def parent_kind(self) -> ParentKind:
        return ParentKind.PODCAST_EPISODE

    @property
    def parent_id(self) -> str:
        return self.podcast_episode.id


type AssetContextBranch = (
    MovieAssetBranch | EpisodeAssetBranch | TrackAssetBranch | PodcastEpisodeAssetBranch
)


@dataclass(frozen=True, slots=True)
class AssetContext:
    branch: AssetContextBranch
    variant: Variant
    bundle: Bundle
    asset: Asset
    bundle_asset_count: int

    @property
    def parent_kind(self) -> ParentKind:
        return self.branch.parent_kind

    @property
    def parent_id(self) -> str:
        return self.branch.parent_id


class _Identified(Protocol):
    id: str


_TargetGetter = Callable[[AssetContext], _Identified]


_OUTER_TARGET_GETTERS: dict[str, _TargetGetter] = {
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
    branch: AssetContextBranch,
    variant: Variant,
    bundle: Bundle,
    asset: Asset,
) -> AssetContext:
    """Build an AssetContext and derive bundle-wide tail metadata."""
    return AssetContext(
        branch=branch,
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
                    branch=MovieAssetBranch(movie=movie),
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
                            branch=EpisodeAssetBranch(
                                series=series,
                                season=season,
                                episode=episode,
                            ),
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
                                branch=TrackAssetBranch(
                                    artist=artist,
                                    album=album,
                                    disc=disc,
                                    track=track,
                                ),
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
                        branch=PodcastEpisodeAssetBranch(
                            podcast=podcast,
                            podcast_episode=episode,
                        ),
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
    if target_kind not in _KNOWN_TARGET_KINDS:
        raise ValueError(f"unknown target_kind: {target_kind}")

    matched: list[str] = []
    for context in iter_asset_contexts(scenario):
        if _context_matches_target(context, target_kind=target_kind, target_id=target_id):
            matched.append(context.asset.id)
    return tuple(matched)


def _context_matches_target(context: AssetContext, *, target_kind: str, target_id: str) -> bool:
    target = _target_for_context(context, target_kind)
    return target is not None and target.id == target_id


_KNOWN_TARGET_KINDS: Final = frozenset(
    {
        "movie",
        "series",
        "season",
        "episode",
        "artist",
        "album",
        "disc",
        "track",
        "podcast",
        "podcast_episode",
        *_OUTER_TARGET_GETTERS,
    }
)


def _target_for_context(context: AssetContext, target_kind: str) -> _Identified | None:
    outer = _OUTER_TARGET_GETTERS.get(target_kind)
    if outer is not None:
        return outer(context)
    branch = context.branch
    if isinstance(branch, MovieAssetBranch):
        return branch.movie if target_kind == "movie" else None
    if isinstance(branch, EpisodeAssetBranch):
        return _episode_branch_target(branch, target_kind)
    if isinstance(branch, TrackAssetBranch):
        return _track_branch_target(branch, target_kind)
    if isinstance(branch, PodcastEpisodeAssetBranch):
        return _podcast_branch_target(branch, target_kind)
    return None


def _episode_branch_target(branch: EpisodeAssetBranch, target_kind: str) -> _Identified | None:
    if target_kind == "series":
        return branch.series
    if target_kind == "season":
        return branch.season
    if target_kind == "episode":
        return branch.episode
    return None


def _track_branch_target(branch: TrackAssetBranch, target_kind: str) -> _Identified | None:
    if target_kind == "artist":
        return branch.artist
    if target_kind == "album":
        return branch.album
    if target_kind == "disc":
        return branch.disc
    if target_kind == "track":
        return branch.track
    return None


def _podcast_branch_target(
    branch: PodcastEpisodeAssetBranch, target_kind: str
) -> _Identified | None:
    if target_kind == "podcast":
        return branch.podcast
    if target_kind == "podcast_episode":
        return branch.podcast_episode
    return None


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
        movie_title=_movie_title_for_context(context),
        series_title=_series_title_for_context(context),
        season_number=_season_number_for_context(context),
        episode_number=_episode_number_for_context(context),
        episode_title=_episode_title_for_context(context),
        aired_on=_aired_on_for_context(context),
        absolute_number=_absolute_number_for_context(context),
        artist_name=_artist_name_for_context(context),
        album_title=_album_title_for_context(context),
        disc_number=_disc_number_for_context(context),
        track_number=_track_number_for_context(context),
        track_title=_track_title_for_context(context),
        podcast_title=_podcast_title_for_context(context),
        published_at=_published_at_for_context(context),
        episode_slug=_episode_slug_for_context(context),
        edition=context.variant.edition,
        variant_label=context.variant.label,
        asset_role=context.asset.role,
        asset_container=context.asset.container,
        bundle_asset_count=context.bundle_asset_count,
    )


def _layout_for_context(
    context: AssetContext,
) -> MovieLayout | SeriesLayout | ArtistLayout | PodcastLayout:
    branch = context.branch
    if isinstance(branch, MovieAssetBranch):
        return branch.movie.layout
    if isinstance(branch, EpisodeAssetBranch):
        return branch.series.layout
    if isinstance(branch, TrackAssetBranch):
        return branch.artist.layout
    if isinstance(branch, PodcastEpisodeAssetBranch):
        return branch.podcast.layout
    raise ChaosLibrarianValueError(f"asset {context.asset.id} has no hierarchy layout")


def _naming_for_context(
    context: AssetContext,
) -> EpisodeNaming | TrackNaming | PodcastEpisodeNaming | None:
    branch = context.branch
    if isinstance(branch, EpisodeAssetBranch):
        return branch.series.episode_naming
    if isinstance(branch, TrackAssetBranch):
        return branch.artist.track_naming
    if isinstance(branch, PodcastEpisodeAssetBranch):
        return branch.podcast.episode_naming
    return None


def _movie_title_for_context(context: AssetContext) -> str | None:
    branch = context.branch
    return branch.movie.title if isinstance(branch, MovieAssetBranch) else None


def _series_title_for_context(context: AssetContext) -> str | None:
    branch = context.branch
    return branch.series.title if isinstance(branch, EpisodeAssetBranch) else None


def _season_number_for_context(context: AssetContext) -> int | None:
    branch = context.branch
    return branch.season.season_number if isinstance(branch, EpisodeAssetBranch) else None


def _episode_number_for_context(context: AssetContext) -> int | None:
    branch = context.branch
    return branch.episode.episode_number if isinstance(branch, EpisodeAssetBranch) else None


def _episode_title_for_context(context: AssetContext) -> str | None:
    branch = context.branch
    if isinstance(branch, EpisodeAssetBranch):
        return branch.episode.title
    if isinstance(branch, PodcastEpisodeAssetBranch):
        return branch.podcast_episode.title
    return None


def _aired_on_for_context(context: AssetContext) -> date | None:
    branch = context.branch
    return branch.episode.aired_on if isinstance(branch, EpisodeAssetBranch) else None


def _absolute_number_for_context(context: AssetContext) -> int | None:
    branch = context.branch
    return branch.episode.absolute_number if isinstance(branch, EpisodeAssetBranch) else None


def _artist_name_for_context(context: AssetContext) -> str | None:
    branch = context.branch
    return branch.artist.name if isinstance(branch, TrackAssetBranch) else None


def _album_title_for_context(context: AssetContext) -> str | None:
    branch = context.branch
    return branch.album.title if isinstance(branch, TrackAssetBranch) else None


def _disc_number_for_context(context: AssetContext) -> int | None:
    branch = context.branch
    return branch.disc.disc_number if isinstance(branch, TrackAssetBranch) else None


def _track_number_for_context(context: AssetContext) -> int | None:
    branch = context.branch
    return branch.track.track_number if isinstance(branch, TrackAssetBranch) else None


def _track_title_for_context(context: AssetContext) -> str | None:
    branch = context.branch
    return branch.track.title if isinstance(branch, TrackAssetBranch) else None


def _podcast_title_for_context(context: AssetContext) -> str | None:
    branch = context.branch
    return branch.podcast.title if isinstance(branch, PodcastEpisodeAssetBranch) else None


def _published_at_for_context(context: AssetContext) -> datetime | None:
    branch = context.branch
    if isinstance(branch, PodcastEpisodeAssetBranch):
        return branch.podcast_episode.published_at
    return None


def _episode_slug_for_context(context: AssetContext) -> str | None:
    branch = context.branch
    return branch.podcast_episode.slug if isinstance(branch, PodcastEpisodeAssetBranch) else None
