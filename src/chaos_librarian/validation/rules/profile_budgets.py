"""Rule: performance profiles impose static source-fixture ceilings."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from chaos_librarian.contract.profiles import ProfileName
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_PROFILE_BUDGET_EXCEEDED
from chaos_librarian.validation.rules._common import (
    NS_ASSET_ID,
    NS_BUNDLE_ID,
    NS_VARIANT_ID,
    Reporter,
    _as_list,
    _iter_timeline_events,
    iter_declared_sidecars,
    iter_global_namespaces,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector


@dataclass(frozen=True, slots=True)
class _StaticBudget:
    assets: int
    works: int
    variants: int
    bundles: int
    sidecars: int
    timeline_events: int


_PERFORMANCE_BUDGETS: Final[dict[str, _StaticBudget]] = {
    ProfileName.PERFORMANCE_SMOKE.value: _StaticBudget(
        assets=40,
        works=40,
        variants=60,
        bundles=8,
        sidecars=120,
        timeline_events=160,
    ),
    ProfileName.PERFORMANCE_SCALE.value: _StaticBudget(
        assets=250,
        works=250,
        variants=400,
        bundles=50,
        sidecars=750,
        timeline_events=1_200,
    ),
    ProfileName.PERFORMANCE_STRESS.value: _StaticBudget(
        assets=1_000,
        works=1_000,
        variants=1_800,
        bundles=200,
        sidecars=3_000,
        timeline_events=6_000,
    ),
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
        profile: budget for profile, budget in _PERFORMANCE_BUDGETS.items() if profile in selected
    }
    if not active_budgets:
        return

    reporter = Reporter(collector=collector, line_index=line_index)
    counts = _static_counts(raw)
    for profile, budget in active_budgets.items():
        _check_budget(profile=profile, budget=budget, counts=counts, reporter=reporter)


def _static_counts(raw: Mapping[str, object]) -> _StaticBudget:
    namespaces = list(iter_global_namespaces(raw))
    return _StaticBudget(
        assets=sum(1 for namespace, _, _ in namespaces if namespace == NS_ASSET_ID),
        works=_count_works(raw),
        variants=sum(1 for namespace, _, _ in namespaces if namespace == NS_VARIANT_ID),
        bundles=sum(1 for namespace, _, _ in namespaces if namespace == NS_BUNDLE_ID),
        sidecars=_count_declared_and_timeline_sidecars(raw),
        timeline_events=sum(1 for _ in _iter_timeline_events(raw)),
    )


def _count_works(raw: Mapping[str, object]) -> int:
    return len(_as_list(raw.get("works")) or [])


def _count_declared_and_timeline_sidecars(raw: Mapping[str, object]) -> int:
    declared = sum(1 for _ in iter_declared_sidecars(raw))
    timeline = 0
    for _, event in _iter_timeline_events(raw):
        action = event.get("action")
        if action in {
            TimelineActionName.CREATE_SIDECAR.value,
            TimelineActionName.EXTRACT_SUBTITLE.value,
        }:
            timeline += 1
    return declared + timeline


def _check_budget(
    *,
    profile: str,
    budget: _StaticBudget,
    counts: _StaticBudget,
    reporter: Reporter,
) -> None:
    for field_name, label in (
        ("assets", "assets"),
        ("works", "works"),
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
