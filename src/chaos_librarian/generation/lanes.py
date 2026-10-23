"""Lane coverage primitives and profile derivation for fuzz generation.

Lane configuration (``LaneConfig``/``LANE_CONFIGS``) lives in
``generation.planner`` alongside the event builders that satisfy each lane's
required coverage cells, so the required cells and the events that produce
them cannot drift apart. This module owns the coverage vocabulary (cell
constants and ``coverage_for_payload``) and derives each lane's required
profile labels from the contract's profile-gating policy.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final, cast

from chaos_librarian.contract.profile_policy import REQUIRED_PROFILES_BY_ACTION
from chaos_librarian.contract.profiles import FuzzProfileName, ProfileName
from chaos_librarian.contract.scenario import NetworkLagEffect, SidecarKind, TimelineActionName


@dataclass(frozen=True, slots=True)
class CoverageReport:
    cells: frozenset[str]

    def missing_required_cells(self, required: frozenset[str]) -> frozenset[str]:
        return required - self.cells


CELL_ACTION_PREFIX: Final = "action:"
CELL_SIDE_SUBTITLE: Final = "sidecar:subtitle"
CELL_SIDE_NFO_OR_POSTER: Final = "sidecar:nfo-or-poster"
CELL_LAG_EFFECT_PREFIX: Final = "network-lag:"
CORE_PATH_CELLS: Final = frozenset(
    {"path:unicode-basename", "path:unicode-parent", "path:leading-dash"}
)
_LONG_COMPONENT_BYTES = 240
_DEEP_PATH_BYTES = 512
_ASCII_C0_LIMIT = 32
_ASCII_DELETE = 127


def path_shape_cells(path: str) -> frozenset[str]:
    """Classify explicit locator spellings, independently of media properties."""
    parts = PurePosixPath(path).parts
    if not parts:
        return frozenset()
    basename = parts[-1]
    cells: set[str] = set()
    if not basename.isascii():
        cells.add("path:unicode-basename")
        for form in ("NFC", "NFD"):
            if unicodedata.is_normalized(form, basename):
                cells.add(f"path:{form.lower()}")
    if any(not part.isascii() for part in parts[:-1]):
        cells.add("path:unicode-parent")
    if basename.startswith("-"):
        cells.add("path:leading-dash")
    if any(character.isspace() for character in path):
        cells.add("path:whitespace")
    if any(character in ";&$[]*?()!`\"'" for character in path):
        cells.add("path:metacharacters")
    if any(
        ord(character) < _ASCII_C0_LIMIT or ord(character) == _ASCII_DELETE for character in path
    ):
        cells.add("path:control")
    if any(len(part.encode("utf-8")) >= _LONG_COMPONENT_BYTES for part in parts):
        cells.add("path:long-component")
    if len(path.encode("utf-8")) > _DEEP_PATH_BYTES:
        cells.add("path:deep")
    return frozenset(cells)


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


def _timeline_action(value: object) -> TimelineActionName | None:
    if not isinstance(value, str):
        return None
    try:
        return TimelineActionName(value)
    except ValueError:
        return None


def _sidecar_kind(value: object) -> SidecarKind | None:
    if not isinstance(value, str):
        return None
    try:
        return SidecarKind(value)
    except ValueError:
        return None


def _network_lag_effect(value: object) -> NetworkLagEffect | None:
    if not isinstance(value, str):
        return None
    try:
        return NetworkLagEffect(value)
    except ValueError:
        return None


def coverage_for_payload(payload: Mapping[str, object]) -> CoverageReport:
    cells: set[str] = set()
    raw = payload.get("timeline", [])
    if not isinstance(raw, list):
        return CoverageReport(cells=frozenset())
    for event in raw:
        if not isinstance(event, dict):
            continue
        event = cast(Mapping[str, object], event)
        action = _timeline_action(event.get("action"))
        if action is not None:
            cells.add(action_cell(action))
        destination = event.get("to")
        if action in {TimelineActionName.RENAME_FILE, TimelineActionName.MOVE_ASSET} and isinstance(
            destination, str
        ):
            cells.update(path_shape_cells(destination))
        kind = _sidecar_kind(event.get("kind"))
        if action is TimelineActionName.CREATE_SIDECAR and kind is not None:
            if kind is SidecarKind.SUBTITLE:
                cells.add(CELL_SIDE_SUBTITLE)
            elif kind in {SidecarKind.NFO, SidecarKind.POSTER}:
                cells.add(CELL_SIDE_NFO_OR_POSTER)
        effect = _network_lag_effect(event.get("effect"))
        if action is TimelineActionName.NETWORK_LAG_START and effect is not None:
            cells.add(f"{CELL_LAG_EFFECT_PREFIX}{effect.value}")
    return CoverageReport(cells=frozenset(cells))
