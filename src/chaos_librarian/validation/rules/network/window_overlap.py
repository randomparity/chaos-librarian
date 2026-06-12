"""Rule: network lag and path-form network-fs-chaos windows must not overlap."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_LIFECYCLE_INVALID
from chaos_librarian.validation.rules.core.raw_helpers import (
    Reporter,
    _iter_timeline_events,
)
from chaos_librarian.validation.rules.hierarchy.projection import (
    HierarchyProjection,
    build_hierarchy_projection,
    is_hierarchy_action,
)
from chaos_librarian.validation.rules.hierarchy.walkers import entity_ids_by_kind

if TYPE_CHECKING:
    from chaos_librarian.validation.reporting import IssueCollector
    from chaos_librarian.validation.scenario_io import LineIndex

__all__ = ["rule_network_window_overlap"]


@dataclass(frozen=True, slots=True)
class _LagWindow:
    event_id: str
    target: str


@dataclass(frozen=True, slots=True)
class _UnmountWindow:
    event_id: str
    target_path: str


def rule_network_window_overlap(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject overlapping network lag and path-form unmount windows."""
    reporter = Reporter(collector=collector, line_index=line_index)
    asset_ids = entity_ids_by_kind(raw).get("asset", set())
    projection = build_hierarchy_projection(raw)
    pending_slow_copies: dict[str, tuple[str, str]] = {}
    active_lags: dict[str, _LagWindow] = {}
    active_unmounts: dict[str, _UnmountWindow] = {}

    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        if action == TimelineActionName.NETWORK_LAG_START:
            _start_lag_window(
                event,
                idx=idx,
                projection=projection,
                active_lags=active_lags,
                active_unmounts=active_unmounts,
                reporter=reporter,
            )
        elif action == TimelineActionName.NETWORK_LAG_COMMIT:
            _close_window(event, active_lags)
        elif action == TimelineActionName.UNMOUNT_PATH:
            _start_unmount_window(
                event,
                idx=idx,
                asset_ids=asset_ids,
                projection=projection,
                active_lags=active_lags,
                active_unmounts=active_unmounts,
                reporter=reporter,
            )
        elif action == TimelineActionName.REMOUNT_PATH:
            _close_window(event, active_unmounts)
        _project_event(event, projection=projection, pending_slow_copies=pending_slow_copies)


def _start_lag_window(
    event: Mapping[str, object],
    *,
    idx: int,
    projection: HierarchyProjection,
    active_lags: dict[str, _LagWindow],
    active_unmounts: dict[str, _UnmountWindow],
    reporter: Reporter,
) -> None:
    event_id = event.get("id")
    target = event.get("target")
    if not isinstance(event_id, str) or not isinstance(target, str):
        return
    active_lags[event_id] = _LagWindow(event_id=event_id, target=target)
    asset_path = projection.current_paths.get(target)
    if asset_path is None:
        return
    for unmount in active_unmounts.values():
        if _path_contains(unmount.target_path, asset_path):
            reporter.error(
                code=E_LIFECYCLE_INVALID,
                message=(
                    f"network_lag_start {event_id!r} for asset {target!r} at "
                    f"{asset_path!r} overlaps unmount_path {unmount.event_id!r} "
                    f"target {unmount.target_path!r}"
                ),
                loc=("timeline", idx, "target"),
            )


def _start_unmount_window(
    event: Mapping[str, object],
    *,
    idx: int,
    asset_ids: set[str],
    projection: HierarchyProjection,
    active_lags: dict[str, _LagWindow],
    active_unmounts: dict[str, _UnmountWindow],
    reporter: Reporter,
) -> None:
    event_id = event.get("id")
    target = event.get("target")
    if not isinstance(event_id, str) or not isinstance(target, str):
        return
    if target in asset_ids:
        return
    active_unmounts[event_id] = _UnmountWindow(event_id=event_id, target_path=target)
    for lag in active_lags.values():
        asset_path = projection.current_paths.get(lag.target)
        if asset_path is None or not _path_contains(target, asset_path):
            continue
        reporter.error(
            code=E_LIFECYCLE_INVALID,
            message=(
                f"unmount_path {event_id!r} target {target!r} overlaps "
                f"network_lag_start {lag.event_id!r} for asset {lag.target!r} "
                f"at {asset_path!r}"
            ),
            loc=("timeline", idx, "target"),
        )


def _close_window[T](event: Mapping[str, object], windows: dict[str, T]) -> None:
    ref = event.get("for")
    if isinstance(ref, str):
        windows.pop(ref, None)


def _project_event(
    event: Mapping[str, object],
    *,
    projection: HierarchyProjection,
    pending_slow_copies: dict[str, tuple[str, str]],
) -> None:
    action = event.get("action")
    if is_hierarchy_action(action):
        projection.apply(event)
    else:
        projection.project_non_hierarchy_event(event, pending_slow_copies)


def _path_contains(parent: str, child: str) -> bool:
    parent_parts = PurePosixPath(parent).parts
    child_parts = PurePosixPath(child).parts
    return (
        len(parent_parts) <= len(child_parts) and child_parts[: len(parent_parts)] == parent_parts
    )
