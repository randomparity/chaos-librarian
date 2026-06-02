"""Rule: selected profiles impose static source-fixture ceilings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from chaos_librarian.contract.profiles import FuzzProfileName, ProfileName
from chaos_librarian.contract.scenario import (
    SubtitleMode,
    TimelineActionName,
    generation_budget_for,
)
from chaos_librarian.validation.codes import E_PROFILE_BUDGET_EXCEEDED
from chaos_librarian.validation.rules.core.raw_helpers import (
    Reporter,
    _as_list,
    _as_mapping,
    _enum,
    _iter_timeline_events,
)

if TYPE_CHECKING:
    from chaos_librarian.validation.reporting import IssueCollector
    from chaos_librarian.validation.scenario_io import LineIndex


@dataclass(frozen=True, slots=True)
class _StaticBudget:
    assets: int
    movies: int
    series: int
    seasons: int
    episodes: int
    artists: int
    albums: int
    discs: int
    tracks: int
    variants: int
    bundles: int
    sidecars: int
    timeline_events: int


def _fuzz_budget(profile: FuzzProfileName) -> _StaticBudget:
    budget = generation_budget_for(profile)
    return _StaticBudget(
        assets=budget.assets,
        movies=budget.movies,
        series=budget.series,
        seasons=budget.seasons,
        episodes=budget.episodes,
        artists=budget.artists,
        albums=budget.albums,
        discs=budget.discs,
        tracks=budget.tracks,
        variants=budget.variants,
        bundles=budget.bundles,
        sidecars=budget.sidecars,
        timeline_events=budget.timeline_events,
    )


_STATIC_PROFILE_BUDGETS: Final[dict[str, _StaticBudget]] = {
    ProfileName.PERFORMANCE_SMOKE.value: _StaticBudget(
        assets=40,
        movies=40,
        series=40,
        seasons=40,
        episodes=40,
        artists=40,
        albums=40,
        discs=40,
        tracks=40,
        variants=60,
        bundles=8,
        sidecars=120,
        timeline_events=160,
    ),
    ProfileName.PERFORMANCE_SCALE.value: _StaticBudget(
        assets=250,
        movies=250,
        series=250,
        seasons=250,
        episodes=250,
        artists=250,
        albums=250,
        discs=250,
        tracks=250,
        variants=400,
        bundles=50,
        sidecars=750,
        timeline_events=1_200,
    ),
    ProfileName.PERFORMANCE_STRESS.value: _StaticBudget(
        assets=1_000,
        movies=1_000,
        series=1_000,
        seasons=1_000,
        episodes=1_000,
        artists=1_000,
        albums=1_000,
        discs=1_000,
        tracks=1_000,
        variants=1_800,
        bundles=200,
        sidecars=3_000,
        timeline_events=6_000,
    ),
    ProfileName.FUZZ_SMOKE.value: _fuzz_budget(FuzzProfileName.FUZZ_SMOKE),
    ProfileName.FUZZ_REGRESSION.value: _fuzz_budget(FuzzProfileName.FUZZ_REGRESSION),
}


def rule_profile_budgets(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject static source fixtures that exceed selected performance budgets."""
    profiles = raw.get("profiles", [])
    if not isinstance(profiles, list):
        return
    selected = [profile for profile in profiles if isinstance(profile, str)]
    active_budgets = {
        profile: budget
        for profile, budget in _STATIC_PROFILE_BUDGETS.items()
        if profile in selected
    }
    if not active_budgets:
        return

    reporter = Reporter(collector=collector, line_index=line_index)
    counts = _static_counts(raw)
    for profile, budget in active_budgets.items():
        _check_budget(profile=profile, budget=budget, counts=counts, reporter=reporter)


def _static_counts(raw: Mapping[str, object]) -> _StaticBudget:
    return _StaticBudget(
        assets=sum(1 for _ in _iter_asset_mappings(raw)),
        movies=len(_as_list(raw.get("movies")) or []),
        series=len(_as_list(raw.get("series")) or []),
        seasons=sum(1 for _ in _iter_season_mappings(raw)),
        episodes=sum(1 for _ in _iter_episode_mappings(raw)),
        artists=len(_as_list(raw.get("artists")) or []),
        albums=sum(1 for _ in _iter_album_mappings(raw)),
        discs=sum(1 for _ in _iter_disc_mappings(raw)),
        tracks=sum(1 for _ in _iter_track_mappings(raw)),
        variants=sum(1 for _ in _iter_variant_mappings(raw)),
        bundles=sum(1 for _ in _iter_bundle_mappings(raw)),
        sidecars=_count_declared_and_timeline_sidecars(raw),
        timeline_events=sum(1 for _ in _iter_timeline_events(raw)),
    )


def _iter_mapping_items(node: object):
    for item in _as_list(node) or []:
        mapping = _as_mapping(item)
        if mapping is not None:
            yield mapping


def _iter_season_mappings(raw: Mapping[str, object]):
    for series in _iter_mapping_items(raw.get("series")):
        yield from _iter_mapping_items(series.get("seasons"))


def _iter_episode_mappings(raw: Mapping[str, object]):
    for season in _iter_season_mappings(raw):
        yield from _iter_mapping_items(season.get("episodes"))


def _iter_album_mappings(raw: Mapping[str, object]):
    for artist in _iter_mapping_items(raw.get("artists")):
        yield from _iter_mapping_items(artist.get("albums"))


def _iter_disc_mappings(raw: Mapping[str, object]):
    for album in _iter_album_mappings(raw):
        yield from _iter_mapping_items(album.get("discs"))


def _iter_track_mappings(raw: Mapping[str, object]):
    for disc in _iter_disc_mappings(raw):
        yield from _iter_mapping_items(disc.get("tracks"))


def _iter_variant_mappings(raw: Mapping[str, object]):
    for movie in _iter_mapping_items(raw.get("movies")):
        yield from _iter_mapping_items(movie.get("variants"))
    for episode in _iter_episode_mappings(raw):
        yield from _iter_mapping_items(episode.get("variants"))
    for track in _iter_track_mappings(raw):
        yield from _iter_mapping_items(track.get("variants"))


def _iter_bundle_mappings(raw: Mapping[str, object]):
    for variant in _iter_variant_mappings(raw):
        bundle = _as_mapping(variant.get("bundle"))
        if bundle is not None:
            yield bundle


def _iter_asset_mappings(raw: Mapping[str, object]):
    for bundle in _iter_bundle_mappings(raw):
        yield from _iter_mapping_items(bundle.get("assets"))


def _count_declared_and_timeline_sidecars(raw: Mapping[str, object]) -> int:
    declared = sum(1 for asset in _iter_asset_mappings(raw) for _ in _declared_sidecars(asset))
    timeline = 0
    for _, event in _iter_timeline_events(raw):
        action = event.get("action")
        if action in {
            TimelineActionName.CREATE_SIDECAR.value,
            TimelineActionName.EXTRACT_SUBTITLE.value,
        }:
            timeline += 1
    return declared + timeline


def _declared_sidecars(asset: Mapping[str, object]):
    for sub in _iter_mapping_items(asset.get("subtitles")):
        if _enum(SubtitleMode, sub.get("mode")) is SubtitleMode.SIDECAR:
            yield sub


def _check_budget(
    *,
    profile: str,
    budget: _StaticBudget,
    counts: _StaticBudget,
    reporter: Reporter,
) -> None:
    for field_name, label in (
        ("assets", "assets"),
        ("movies", "movies"),
        ("series", "series"),
        ("seasons", "seasons"),
        ("episodes", "episodes"),
        ("artists", "artists"),
        ("albums", "albums"),
        ("discs", "discs"),
        ("tracks", "tracks"),
        ("variants", "variants"),
        ("bundles", "bundles"),
        ("sidecars", "sidecars"),
        ("timeline_events", "timeline events"),
    ):
        count = getattr(counts, field_name)
        limit = getattr(budget, field_name)
        if count <= limit:
            continue
        reporter.error(
            code=E_PROFILE_BUDGET_EXCEEDED,
            message=f"{profile} allows at most {limit} {label}; scenario declares {count}",
            loc=("profiles",),
        )
