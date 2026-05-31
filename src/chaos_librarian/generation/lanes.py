"""Lane coverage primitives and profile derivation for fuzz generation.

Lane configuration (``LaneConfig``/``LANE_CONFIGS``) lives in
``generation.planner`` alongside the event builders that satisfy each lane's
required coverage cells, so the required cells and the events that produce
them cannot drift apart. This module owns the coverage vocabulary (cell
constants and ``coverage_for_payload``) and derives each lane's required
profile labels from the contract's profile-gating policy.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, cast

from chaos_librarian.contract.profile_policy import REQUIRED_PROFILES_BY_ACTION
from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName, ProfileName
from chaos_librarian.contract.scenario import SidecarKind, TimelineActionName

if TYPE_CHECKING:
    from chaos_librarian.generation.planner import TimelinePlanner


@dataclass(frozen=True, slots=True)
class LaneConfig:
    profile: FuzzProfileName
    lane: FuzzLaneName
    profiles: tuple[ProfileName, ...]
    movies: int
    series: int
    artists: int
    timeline_events: int
    required_cells: frozenset[str]
    required_events: Callable[[TimelinePlanner], None]


@dataclass(frozen=True, slots=True)
class CoverageReport:
    cells: frozenset[str]

    def missing_required_cells(self, required: frozenset[str]) -> frozenset[str]:
        return required - self.cells


CELL_ACTION_PREFIX: Final = "action:"
CELL_SIDE_SUBTITLE: Final = "sidecar:subtitle"
CELL_SIDE_NFO_OR_POSTER: Final = "sidecar:nfo-or-poster"
CELL_LAG_EFFECT_PREFIX: Final = "network-lag:"


def action_cell(action: TimelineActionName) -> str:
    return f"{CELL_ACTION_PREFIX}{action.value}"


def derive_required_profiles(
    base: FuzzProfileName,
    required_cells: frozenset[str],
) -> tuple[ProfileName, ...]:
    """Return the profile labels a lane must declare for its required cells.

    The base fuzz profile is always first. Any profile-gated action present in
    ``required_cells`` contributes its required profile, derived from the
    contract's :data:`REQUIRED_PROFILES_BY_ACTION` so generation cannot drift
    from the rule that would reject the generated scenario. Gated profiles are
    appended in their first-appearance order within the contract map for
    deterministic output.
    """
    base_profile = ProfileName(base.value)
    gated_actions: set[TimelineActionName] = set()
    for cell in required_cells:
        if not cell.startswith(CELL_ACTION_PREFIX):
            continue
        try:
            gated_actions.add(TimelineActionName(cell.removeprefix(CELL_ACTION_PREFIX)))
        except ValueError:
            continue
    profiles: list[ProfileName] = [base_profile]
    seen: set[ProfileName] = {base_profile}
    for action, profile in REQUIRED_PROFILES_BY_ACTION.items():
        if action not in gated_actions:
            continue
        if profile not in seen:
            seen.add(profile)
            profiles.append(profile)
    return tuple(profiles)


def coverage_for_payload(payload: Mapping[str, object]) -> CoverageReport:
    cells: set[str] = set()
    raw = payload.get("timeline", [])
    if not isinstance(raw, list):
        return CoverageReport(cells=frozenset())
    for event in raw:
        if not isinstance(event, dict):
            continue
        event = cast(Mapping[str, object], event)
        action = event.get("action")
        if isinstance(action, str):
            cells.add(f"{CELL_ACTION_PREFIX}{action}")
        kind = event.get("kind")
        if action == TimelineActionName.CREATE_SIDECAR.value and isinstance(kind, str):
            if kind == SidecarKind.SUBTITLE.value:
                cells.add(CELL_SIDE_SUBTITLE)
            elif kind in {SidecarKind.NFO.value, SidecarKind.POSTER.value}:
                cells.add(CELL_SIDE_NFO_OR_POSTER)
        effect = event.get("effect")
        if action == TimelineActionName.NETWORK_LAG_START.value and isinstance(effect, str):
            cells.add(f"{CELL_LAG_EFFECT_PREFIX}{effect}")
    return CoverageReport(cells=frozenset(cells))
