"""Rule: network-lag event pairs must be deterministic and executable."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from chaos_librarian.contract.scenario import NetworkLagEffect, TimelineActionName
from chaos_librarian.validation.codes import E_LIFECYCLE_INVALID
from chaos_librarian.validation.rules.core.raw_helpers import (
    Reporter,
    _iter_timeline_events,
    _RawMapping,
    index_start_commit_events,
    report_unpaired_start,
    try_parse_duration,
)

if TYPE_CHECKING:
    from chaos_librarian.validation.reporting import IssueCollector
    from chaos_librarian.validation.scenario_io import LineIndex

__all__ = ["rule_network_lag"]


_DELAYED_VISIBILITY_AFTER_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        TimelineActionName.ADD_FILE.value,
        TimelineActionName.CREATE_SIDECAR.value,
        TimelineActionName.SLOW_COPY_COMMIT.value,
        TimelineActionName.REENCODE_VIDEO.value,
        TimelineActionName.REENCODE_AUDIO.value,
        TimelineActionName.REMUX_CONTAINER.value,
        TimelineActionName.EDIT_METADATA.value,
        TimelineActionName.EMBED_SUBTITLE.value,
        TimelineActionName.EXTRACT_SUBTITLE.value,
        TimelineActionName.UPDATE_SIDECAR.value,
    }
)
_DELAYED_RENAME_AFTER_ACTIONS: Final[frozenset[str]] = frozenset(
    {
        TimelineActionName.MOVE_ASSET.value,
        TimelineActionName.RENAME_FILE.value,
        TimelineActionName.ARCHIVE_FILE.value,
        TimelineActionName.MOVE_BETWEEN_ROOTS.value,
    }
)
_AFTER_ACTIONS_BY_EFFECT: Final[dict[str, frozenset[str]]] = {
    NetworkLagEffect.DELAYED_VISIBILITY.value: _DELAYED_VISIBILITY_AFTER_ACTIONS,
    NetworkLagEffect.DELAYED_RENAME.value: _DELAYED_RENAME_AFTER_ACTIONS,
}


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
            events_by_id=events_by_id,
            reporter=reporter,
        )


def _index_starts_and_commits(
    timeline: list[tuple[int, _RawMapping]],
) -> tuple[dict[str, _LagStart], list[_LagCommit]]:
    raw_starts, raw_commits = index_start_commit_events(
        timeline,
        start_action=TimelineActionName.NETWORK_LAG_START,
        commit_action=TimelineActionName.NETWORK_LAG_COMMIT,
    )
    starts = {
        event_id: _LagStart(idx=idx, event=event, event_id=event_id)
        for event_id, (idx, event) in raw_starts.items()
    }
    commits = [_LagCommit(idx=idx, event=event) for idx, event in raw_commits]
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
        start = starts[start_id]
        report_unpaired_start(
            reporter=reporter,
            code=E_LIFECYCLE_INVALID,
            start_noun="network_lag_start",
            commit_noun="network_lag_commit",
            event_id=start.event_id,
            idx=start.idx,
            matching_commit_count=len(matching_commits),
        )
    return commits_by_start


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
    _check_after_timing(start=start, after_id=after_id, after_event=after_event, reporter=reporter)
    _check_after_target(
        start=start,
        after_id=after_id,
        after_event=after_event,
        events_by_id=events_by_id,
        reporter=reporter,
    )
    _check_after_effect(start=start, after_id=after_id, after_event=after_event, reporter=reporter)


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
    events_by_id: dict[str, tuple[int, _RawMapping]],
    reporter: Reporter,
) -> None:
    target = start.event.get("target")
    after_target = _event_target(after_event, events_by_id)
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


def _check_after_timing(
    *,
    start: _LagStart,
    after_id: str,
    after_event: _RawMapping,
    reporter: Reporter,
) -> None:
    start_at_ns = _parse_event_duration(start.event, "at")
    after_at_ns = _parse_event_duration(after_event, "at")
    if start_at_ns is None or after_at_ns is None:
        return
    if start_at_ns == after_at_ns:
        return
    reporter.error(
        code=E_LIFECYCLE_INVALID,
        message=f"network_lag_start must use the same at value as after event {after_id!r}",
        loc=("timeline", start.idx, "at"),
    )


def _check_after_effect(
    *,
    start: _LagStart,
    after_id: str,
    after_event: _RawMapping,
    reporter: Reporter,
) -> None:
    effect = start.event.get("effect")
    after_action = after_event.get("action")
    if not isinstance(effect, str) or not isinstance(after_action, str):
        return
    allowed_actions = _AFTER_ACTIONS_BY_EFFECT.get(effect)
    if allowed_actions is None or after_action in allowed_actions:
        return
    reporter.error(
        code=E_LIFECYCLE_INVALID,
        message=(
            f"network_lag_start effect {effect!r} cannot wrap "
            f"{after_action!r} after event {after_id!r}"
        ),
        loc=("timeline", start.idx, "effect"),
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
    events_by_id: dict[str, tuple[int, _RawMapping]],
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
        if _event_target(event, events_by_id) != target:
            continue
        event_id = event.get("id")
        event_label = f" {event_id!r}" if isinstance(event_id, str) else ""
        reporter.error(
            code=E_LIFECYCLE_INVALID,
            message=(
                f"event{event_label} mutates target {target!r} during a pending network lag window"
            ),
            loc=("timeline", idx, _target_loc_field(event)),
        )


def _event_target(
    event: _RawMapping,
    events_by_id: dict[str, tuple[int, _RawMapping]],
) -> str | None:
    target = event.get("target")
    if isinstance(target, str):
        return target
    if event.get("action") != TimelineActionName.SLOW_COPY_COMMIT:
        return None
    start_id = event.get("for")
    if not isinstance(start_id, str):
        return None
    start = events_by_id.get(start_id)
    if start is None:
        return None
    start_target = start[1].get("target")
    return start_target if isinstance(start_target, str) else None


def _target_loc_field(event: _RawMapping) -> str:
    if event.get("action") == TimelineActionName.SLOW_COPY_COMMIT:
        return "for"
    return "target"
