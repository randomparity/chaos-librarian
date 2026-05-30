"""Network-fs-chaos target containment and open/close pairing rules.

``rule_network_fs_chaos_target`` checks the three path-or-asset actions
(``change_permissions``, ``toggle_readonly``, ``unmount_path``): a ``target``
that is not a declared asset id is treated as a library-relative subtree path and
must resolve under ``<run-dir>/library/`` (escape → ``E_PATH_CONTAINMENT``). The
asset-only actions (``simulate_quota_exceeded`` / ``simulate_stale_handle`` /
``acquire_lock``) are checked by ``rule_target_unknown`` (``E_TARGET_UNKNOWN``) and
are not this rule's concern.

``rule_network_fs_chaos_pairing`` validates the paired open/close actions
(``acquire_lock``/``release_lock`` and ``unmount_path``/``remount_path``) the way
``rule_network_lag`` validates ``network_lag_start``/``network_lag_commit``: a close
references its open by event id, exactly one close per open, the close follows the
open in declaration order, the close's ``at`` is not earlier than the open's ``at``
(otherwise the resolved timeline would execute the close first), and no other event
mutates the same target inside the open window (``E_LIFECYCLE_INVALID``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from chaos_librarian.contract.paths import PathContainmentError, resolve_under_library
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_LIFECYCLE_INVALID, E_PATH_CONTAINMENT
from chaos_librarian.validation.rules._common import (
    Reporter,
    _iter_timeline_events,
    _RawMapping,
    entity_ids_by_kind,
    index_start_commit_events,
    report_unpaired_start,
    try_parse_duration,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_network_fs_chaos_pairing", "rule_network_fs_chaos_target"]


_PATH_OR_ASSET_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        TimelineActionName.CHANGE_PERMISSIONS.value,
        TimelineActionName.TOGGLE_READONLY.value,
        TimelineActionName.UNMOUNT_PATH.value,
    }
)

_SYNTHETIC_LIBRARY_DIR: Final[Path] = Path("/__chaos_librarian_validate__/library")


# --- target containment -----------------------------------------------------


def rule_network_fs_chaos_target(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject path-form chaos targets that escape the library root.

    A ``target`` matching a declared asset id is an asset target (validated by
    ``rule_target_unknown``); any other ``target`` is a library-relative subtree
    path and must resolve under the library root.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    asset_ids = entity_ids_by_kind(raw).get("asset", set())
    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        if action not in _PATH_OR_ASSET_ACTIONS:
            continue
        target = event.get("target")
        if not isinstance(target, str) or target in asset_ids:
            continue
        try:
            resolve_under_library(Path(target), _SYNTHETIC_LIBRARY_DIR)
        except PathContainmentError as exc:
            reporter.error(
                code=E_PATH_CONTAINMENT,
                message=f"network-fs-chaos target {target!r} escapes the library root: {exc}",
                loc=("timeline", idx, "target"),
            )


# --- open/close pairing -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class _PairSpec:
    open_action: TimelineActionName
    close_action: TimelineActionName
    open_noun: str
    close_noun: str


_PAIR_SPECS: Final[tuple[_PairSpec, ...]] = (
    _PairSpec(
        open_action=TimelineActionName.ACQUIRE_LOCK,
        close_action=TimelineActionName.RELEASE_LOCK,
        open_noun="acquire_lock",
        close_noun="release_lock",
    ),
    _PairSpec(
        open_action=TimelineActionName.UNMOUNT_PATH,
        close_action=TimelineActionName.REMOUNT_PATH,
        open_noun="unmount_path",
        close_noun="remount_path",
    ),
)


def rule_network_fs_chaos_pairing(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Validate acquire/release and unmount/remount open/close windows."""
    reporter = Reporter(collector=collector, line_index=line_index)
    timeline = list(_iter_timeline_events(raw))
    for spec in _PAIR_SPECS:
        _check_pair(spec=spec, timeline=timeline, reporter=reporter)


def _check_pair(
    *,
    spec: _PairSpec,
    timeline: list[tuple[int, _RawMapping]],
    reporter: Reporter,
) -> None:
    starts, commits = index_start_commit_events(
        timeline,
        start_action=spec.open_action.value,
        commit_action=spec.close_action.value,
    )
    commits_by_start: dict[str, list[tuple[int, _RawMapping]]] = {sid: [] for sid in starts}
    for commit_idx, commit in commits:
        ref = commit.get("for")
        if not isinstance(ref, str):
            continue
        if ref not in starts:
            reporter.error(
                code=E_LIFECYCLE_INVALID,
                message=f"{spec.close_noun} references unknown {spec.open_noun} {ref!r}",
                loc=("timeline", commit_idx, "for"),
            )
            continue
        commits_by_start[ref].append((commit_idx, commit))
    for start_id, (start_idx, _start_event) in starts.items():
        matching = commits_by_start[start_id]
        report_unpaired_start(
            reporter=reporter,
            code=E_LIFECYCLE_INVALID,
            start_noun=spec.open_noun,
            commit_noun=spec.close_noun,
            event_id=start_id,
            idx=start_idx,
            matching_commit_count=len(matching),
        )
        if len(matching) != 1:
            continue
        _check_window(
            spec=spec,
            start_id=start_id,
            start_idx=start_idx,
            start_event=starts[start_id][1],
            commit_idx=matching[0][0],
            commit_event=matching[0][1],
            timeline=timeline,
            reporter=reporter,
        )


def _check_window(
    *,
    spec: _PairSpec,
    start_id: str,
    start_idx: int,
    start_event: _RawMapping,
    commit_idx: int,
    commit_event: _RawMapping,
    timeline: list[tuple[int, _RawMapping]],
    reporter: Reporter,
) -> None:
    if commit_idx <= start_idx:
        reporter.error(
            code=E_LIFECYCLE_INVALID,
            message=f"{spec.close_noun} must follow its {spec.open_noun} {start_id!r}",
            loc=("timeline", commit_idx, "for"),
        )
        return
    if _close_at_precedes_open(start_event, commit_event):
        reporter.error(
            code=E_LIFECYCLE_INVALID,
            message=(
                f"{spec.close_noun}.at must not precede its {spec.open_noun} {start_id!r} at value"
            ),
            loc=("timeline", commit_idx, "at"),
        )
        return
    target = start_event.get("target")
    if not isinstance(target, str):
        return
    for idx, event in timeline[start_idx + 1 : commit_idx]:
        if event.get("target") != target:
            continue
        event_id = event.get("id")
        label = f" {event_id!r}" if isinstance(event_id, str) else ""
        reporter.error(
            code=E_LIFECYCLE_INVALID,
            message=(
                f"event{label} mutates target {target!r} during an open {spec.open_noun} window"
            ),
            loc=("timeline", idx, "target"),
        )


def _close_at_precedes_open(start_event: _RawMapping, commit_event: _RawMapping) -> bool:
    start_at = _event_at_ns(start_event)
    commit_at = _event_at_ns(commit_event)
    if start_at is None or commit_at is None:
        return False
    return commit_at < start_at


def _event_at_ns(event: _RawMapping) -> int | None:
    value = event.get("at")
    if not isinstance(value, str):
        return None
    return try_parse_duration(value)
