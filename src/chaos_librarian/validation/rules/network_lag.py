"""Rule: network-lag event pairs must be deterministic and executable."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_LIFECYCLE_INVALID
from chaos_librarian.validation.rules._common import (
    Reporter,
    _iter_timeline_events,
    _RawMapping,
    try_parse_duration,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_network_lag"]


@dataclass(frozen=True, slots=True)
class _LagStart:
    idx: int
    event: _RawMapping
    event_id: str


@dataclass(frozen=True, slots=True)
class _LagCommit:
    idx: int
    event: _RawMapping


def rule_network_lag(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject network-lag pairs that the wall-clock runner cannot execute."""
    reporter = Reporter(collector=collector, line_index=line_index)
    timeline = list(_iter_timeline_events(raw))
    starts, commits = _index_starts_and_commits(timeline)
    commits_by_start = _check_pairing(starts=starts, commits=commits, reporter=reporter)
    events_by_id = _events_by_id(timeline)
    for start in starts.values():
        _check_start_reference(start=start, events_by_id=events_by_id, reporter=reporter)
        _check_commit_timing(
            start=start,
            commits=commits_by_start.get(start.event_id, []),
            reporter=reporter,
        )
        _check_same_target_window(
            start=start,
            commits=commits_by_start.get(start.event_id, []),
            timeline=timeline,
            reporter=reporter,
        )


def _index_starts_and_commits(
    timeline: list[tuple[int, _RawMapping]],
) -> tuple[dict[str, _LagStart], list[_LagCommit]]:
    starts: dict[str, _LagStart] = {}
    commits: list[_LagCommit] = []
    for idx, event in timeline:
        action = event.get("action")
        event_id = event.get("id")
        if action == TimelineActionName.NETWORK_LAG_START and isinstance(event_id, str):
            starts[event_id] = _LagStart(idx=idx, event=event, event_id=event_id)
        elif action == TimelineActionName.NETWORK_LAG_COMMIT:
            commits.append(_LagCommit(idx=idx, event=event))
    return starts, commits


def _check_pairing(
    *,
    starts: dict[str, _LagStart],
    commits: list[_LagCommit],
    reporter: Reporter,
) -> dict[str, list[_LagCommit]]:
    commits_by_start: dict[str, list[_LagCommit]] = {start_id: [] for start_id in starts}
    for commit in commits:
        ref = commit.event.get("for")
        if not isinstance(ref, str):
            continue
        if ref not in starts:
            reporter.error(
                code=E_LIFECYCLE_INVALID,
                message=f"network_lag_commit references unknown network_lag_start {ref!r}",
                loc=("timeline", commit.idx, "for"),
            )
            continue
        commits_by_start[ref].append(commit)
    for start_id, matching_commits in commits_by_start.items():
        if len(matching_commits) == 1:
            continue
        _report_start_pairing(
            start=starts[start_id],
            matching_commit_count=len(matching_commits),
            reporter=reporter,
        )
    return commits_by_start


def _report_start_pairing(
    *,
    start: _LagStart,
    matching_commit_count: int,
    reporter: Reporter,
) -> None:
    if matching_commit_count == 0:
        message = f"network_lag_start {start.event_id!r} has no matching network_lag_commit"
    else:
        message = (
            f"network_lag_start {start.event_id!r} has {matching_commit_count} "
            "matching commits (expected 1)"
        )
    reporter.error(code=E_LIFECYCLE_INVALID, message=message, loc=("timeline", start.idx, "id"))


def _events_by_id(timeline: list[tuple[int, _RawMapping]]) -> dict[str, tuple[int, _RawMapping]]:
    events: dict[str, tuple[int, _RawMapping]] = {}
    for idx, event in timeline:
        event_id = event.get("id")
        if isinstance(event_id, str):
            events[event_id] = (idx, event)
    return events


def _check_start_reference(
    *,
    start: _LagStart,
    events_by_id: dict[str, tuple[int, _RawMapping]],
    reporter: Reporter,
) -> None:
    after_id = start.event.get("after")
    if not isinstance(after_id, str):
        return
    after = events_by_id.get(after_id)
    if after is None:
        reporter.error(
            code=E_LIFECYCLE_INVALID,
            message=f"network_lag_start references unknown after event {after_id!r}",
            loc=("timeline", start.idx, "after"),
        )
        return
    after_idx, after_event = after
    _check_after_order(start=start, after_id=after_id, after_idx=after_idx, reporter=reporter)
    _check_after_target(start=start, after_id=after_id, after_event=after_event, reporter=reporter)


def _check_after_order(
    *,
    start: _LagStart,
    after_id: str,
    after_idx: int,
    reporter: Reporter,
) -> None:
    if after_idx >= start.idx:
        reporter.error(
            code=E_LIFECYCLE_INVALID,
            message=f"network_lag_start after event {after_id!r} must precede the lag start",
            loc=("timeline", start.idx, "after"),
        )
    if after_idx != start.idx - 1:
        reporter.error(
            code=E_LIFECYCLE_INVALID,
            message=f"network_lag_start must immediately follow after event {after_id!r}",
            loc=("timeline", start.idx, "after"),
        )


def _check_after_target(
    *,
    start: _LagStart,
    after_id: str,
    after_event: _RawMapping,
    reporter: Reporter,
) -> None:
    target = start.event.get("target")
    after_target = after_event.get("target")
    if not isinstance(target, str) or not isinstance(after_target, str):
        return
    if target != after_target:
        reporter.error(
            code=E_LIFECYCLE_INVALID,
            message=(
                f"network_lag_start target {target!r} does not match "
                f"after event {after_id!r} target {after_target!r}"
            ),
            loc=("timeline", start.idx, "target"),
        )


def _check_commit_timing(
    *,
    start: _LagStart,
    commits: list[_LagCommit],
    reporter: Reporter,
) -> None:
    if len(commits) != 1:
        return
    commit = commits[0]
    start_at_ns = _parse_event_duration(start.event, "at")
    duration_ns = _parse_event_duration(start.event, "duration")
    commit_at_ns = _parse_event_duration(commit.event, "at")
    if start_at_ns is None or duration_ns is None or commit_at_ns is None:
        return
    if duration_ns <= 0:
        reporter.error(
            code=E_LIFECYCLE_INVALID,
            message="network_lag_start duration must be positive",
            loc=("timeline", start.idx, "duration"),
        )
        return
    expected = start_at_ns + duration_ns
    if commit_at_ns != expected:
        reporter.error(
            code=E_LIFECYCLE_INVALID,
            message=(f"network_lag_commit.at must equal start.at + duration ({expected}ns)"),
            loc=("timeline", commit.idx, "at"),
        )


def _parse_event_duration(event: _RawMapping, field: str) -> int | None:
    value = event.get(field)
    if not isinstance(value, str):
        return None
    return try_parse_duration(value)


def _check_same_target_window(
    *,
    start: _LagStart,
    commits: list[_LagCommit],
    timeline: list[tuple[int, _RawMapping]],
    reporter: Reporter,
) -> None:
    if len(commits) != 1:
        return
    commit = commits[0]
    if commit.idx <= start.idx:
        reporter.error(
            code=E_LIFECYCLE_INVALID,
            message="network_lag_commit must follow its network_lag_start",
            loc=("timeline", commit.idx, "for"),
        )
        return
    target = start.event.get("target")
    if not isinstance(target, str):
        return
    for idx, event in timeline[start.idx + 1 : commit.idx]:
        if event.get("target") != target:
            continue
        reporter.error(
            code=E_LIFECYCLE_INVALID,
            message=f"event mutates target {target!r} during a pending network lag window",
            loc=("timeline", idx, "target"),
        )
