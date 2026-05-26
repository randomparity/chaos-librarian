"""Typed topology walkers for scenario hierarchy contracts."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Protocol

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    Album,
    Artist,
    Asset,
    Bundle,
    Disc,
    Episode,
    Movie,
    Scenario,
    Season,
    Series,
    Track,
    Variant,
)

__all__ = [
    "AssetContext",
    "asset_contexts_by_id",
    "asset_ids_under_target",
    "iter_asset_contexts",
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
    "variant": lambda context: context.variant,
    "bundle": lambda context: context.bundle,
    "asset": lambda context: context.asset,
}


def iter_asset_contexts(scenario: Scenario) -> Iterator[AssetContext]:
    """Yield every playable/listenable asset context in declaration order."""
    yield from _movie_asset_contexts(scenario)
    yield from _episode_asset_contexts(scenario)
    yield from _track_asset_contexts(scenario)


def _movie_asset_contexts(scenario: Scenario) -> Iterator[AssetContext]:
    for movie in scenario.movies:
        for variant in movie.variants:
            bundle = variant.bundle
            for asset in bundle.assets:
                yield AssetContext(
                    parent_kind=ParentKind.MOVIE,
                    parent_id=movie.id,
                    movie=movie,
                    series=None,
                    season=None,
                    episode=None,
                    artist=None,
                    album=None,
                    disc=None,
                    track=None,
                    variant=variant,
                    bundle=bundle,
                    asset=asset,
                    bundle_asset_count=len(bundle.assets),
                )


def _episode_asset_contexts(scenario: Scenario) -> Iterator[AssetContext]:
    for series in scenario.series:
        for season in series.seasons:
            for episode in season.episodes:
                for variant in episode.variants:
                    bundle = variant.bundle
                    for asset in bundle.assets:
                        yield AssetContext(
                            parent_kind=ParentKind.EPISODE,
                            parent_id=episode.id,
                            movie=None,
                            series=series,
                            season=season,
                            episode=episode,
                            artist=None,
                            album=None,
                            disc=None,
                            track=None,
                            variant=variant,
                            bundle=bundle,
                            asset=asset,
                            bundle_asset_count=len(bundle.assets),
                        )


def _track_asset_contexts(scenario: Scenario) -> Iterator[AssetContext]:
    for artist in scenario.artists:
        for album in artist.albums:
            for disc in album.discs:
                for track in disc.tracks:
                    for variant in track.variants:
                        bundle = variant.bundle
                        for asset in bundle.assets:
                            yield AssetContext(
                                parent_kind=ParentKind.TRACK,
                                parent_id=track.id,
                                movie=None,
                                series=None,
                                season=None,
                                episode=None,
                                artist=artist,
                                album=album,
                                disc=disc,
                                track=track,
                                variant=variant,
                                bundle=bundle,
                                asset=asset,
                                bundle_asset_count=len(bundle.assets),
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
