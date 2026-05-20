"""Rules 5a + 5b: E_SLOW_COPY_UNPAIRED and E_SLOW_COPY_TIMING.

Both rules walk the same start/commit index, so they share the
``_index_starts_and_commits`` helper in this module.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_SLOW_COPY_TIMING, E_SLOW_COPY_UNPAIRED
from chaos_librarian.validation.rules._common import (
    Reporter,
    _iter_timeline_events,
    _RawMapping,
    try_parse_duration,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_slow_copy_timing", "rule_slow_copy_unpaired"]


def rule_slow_copy_unpaired(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """5a: structural pairing of slow_copy_start <-> slow_copy_commit."""
    reporter = Reporter(collector=collector, line_index=line_index)
    starts, commits = _index_starts_and_commits(raw)
    commits_per_start: dict[str, int] = {sid: 0 for sid in starts}
    for c_idx, commit in commits:
        ref = commit.get("for")
        if not isinstance(ref, str):
            continue  # Pydantic owns shape
        if ref not in starts:
            reporter.error(
                code=E_SLOW_COPY_UNPAIRED,
                message=f"slow_copy_commit references unknown slow_copy_start {ref!r}",
                loc=("timeline", c_idx, "for"),
            )
            continue
        commits_per_start[ref] += 1
    _report_orphan_starts(commits_per_start=commits_per_start, starts=starts, reporter=reporter)


def rule_slow_copy_timing(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """5b: strict equality ``commit.at == start.at + start.duration``.

    Preconditions: durations on both events parse (Rule 3 already flagged
    otherwise) AND structural pairing holds (Rule 5a already flagged
    orphans). Skipping here prevents double-reporting.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    starts, commits = _index_starts_and_commits(raw)
    for c_idx, commit in commits:
        ref = commit.get("for")
        if not isinstance(ref, str) or ref not in starts:
            continue  # Rule 5a flagged orphan
        _, start = starts[ref]
        _check_pair_timing(c_idx=c_idx, commit=commit, start=start, reporter=reporter)


def _index_starts_and_commits(
    raw: _RawMapping,
) -> tuple[dict[str, tuple[int, _RawMapping]], list[tuple[int, _RawMapping]]]:
    """Split the timeline into ``(starts_by_id, commits)`` for slow-copy rules.

    Entries preserve the original timeline index for error ``loc`` reporting.
    Used by Rule 5a (which inspects both) and Rule 5b (which only needs starts).
    """
    starts: dict[str, tuple[int, _RawMapping]] = {}
    commits: list[tuple[int, _RawMapping]] = []
    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        ev_id = event.get("id")
        if action == TimelineActionName.SLOW_COPY_START and isinstance(ev_id, str):
            starts[ev_id] = (idx, event)
        elif action == TimelineActionName.SLOW_COPY_COMMIT:
            commits.append((idx, event))
    return starts, commits


def _report_orphan_starts(
    *,
    commits_per_start: dict[str, int],
    starts: dict[str, tuple[int, _RawMapping]],
    reporter: Reporter,
) -> None:
    """Emit E_SLOW_COPY_UNPAIRED for any start with zero or >1 matching commits."""
    for sid, count in commits_per_start.items():
        if count == 0:
            message = f"slow_copy_start {sid!r} has no matching slow_copy_commit"
        elif count > 1:
            message = f"slow_copy_start {sid!r} has {count} matching commits (expected 1)"
        else:
            continue
        s_idx, _ = starts[sid]
        reporter.error(
            code=E_SLOW_COPY_UNPAIRED,
            message=message,
            loc=("timeline", s_idx, "id"),
        )


def _check_pair_timing(
    *,
    c_idx: int,
    commit: _RawMapping,
    start: _RawMapping,
    reporter: Reporter,
) -> None:
    """Validate one matched pair's ``commit.at == start.at + start.duration``.

    Skips silently when any of the three durations fail to parse — Rule 3
    has already flagged that case, and double-reporting would be noise.
    """
    start_at = start.get("at")
    start_dur = start.get("duration")
    commit_at = commit.get("at")
    if not isinstance(start_at, str):
        return  # Rule 3 / Pydantic flagged
    if not isinstance(start_dur, str) or not isinstance(commit_at, str):
        return  # Rule 3 / Pydantic flagged
    start_at_ns = try_parse_duration(start_at)
    start_dur_ns = try_parse_duration(start_dur)
    commit_at_ns = try_parse_duration(commit_at)
    if start_at_ns is None or start_dur_ns is None or commit_at_ns is None:
        return  # Rule 3 flagged the unparseable string
    expected = start_at_ns + start_dur_ns
    if commit_at_ns != expected:
        reporter.error(
            code=E_SLOW_COPY_TIMING,
            message=(
                f"slow_copy_commit.at {commit_at!r} != "
                f"start.at {start_at!r} + duration {start_dur!r}"
            ),
            loc=("timeline", c_idx, "at"),
        )
