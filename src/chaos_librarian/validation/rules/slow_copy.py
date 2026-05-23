"""Rules 5a + 5b + 5c: slow-copy structural / timing / path-collision checks.

5a (E_SLOW_COPY_UNPAIRED) and 5b (E_SLOW_COPY_TIMING) walk the same
start/commit index, so they share the ``_index_starts_and_commits``
helper in this module. 5c (E_SLOW_COPY_PATH_COLLISION) walks each
``slow_copy_start`` event independently and joins against the asset's
declared container to compute the initial path.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.paths import INITIAL_PATH_TEMPLATE
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import (
    E_SLOW_COPY_PATH_COLLISION,
    E_SLOW_COPY_TIMING,
    E_SLOW_COPY_UNPAIRED,
)
from chaos_librarian.validation.rules._common import (
    Reporter,
    _iter_timeline_events,
    _RawMapping,
    asset_containers,
    primary_root_path,
    try_parse_duration,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = [
    "rule_slow_copy_path_collision",
    "rule_slow_copy_timing",
    "rule_slow_copy_unpaired",
]


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


def _normalize(path: str) -> str:
    """Canonicalize a YAML-authored path for equality comparison.

    Uses ``os.path.normpath`` -- stdlib, no filesystem I/O, no symlink
    resolution. We compare normalized forms because the run-dir doesn't
    exist at validation time, but two scenario paths that differ only by
    ``.`` / ``..`` / trailing slash describe the same on-disk location.
    """
    return os.path.normpath(path)


def rule_slow_copy_path_collision(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """5c: reject ``temp_path == to`` and ``temp_path == initial_path``.

    Phase B's commit helper unlinks ``initial_path`` and then ``replace``s
    ``temp_path -> final_path``. If ``temp_path == to`` the multi-phase
    visibility contract collapses; if ``temp_path == initial_path`` the
    unlink wipes the temp before the replace runs. Both cases emit
    ``E_SLOW_COPY_PATH_COLLISION``.

    Path equality is checked on the ``os.path.normpath``-normalized form
    so a ``.``-segment or trailing-slash variant cannot slip past the
    rule. Normalization is purely lexical -- no I/O, no symlink resolution.

    Initial paths are derived via ``contract.paths.INITIAL_PATH_TEMPLATE``
    formatted with the asset's primary-root path and container -- no other
    source of truth.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    primary_path = primary_root_path(raw)
    if primary_path is None:
        return  # Pydantic owns shape on missing roots[0]
    containers_by_asset = asset_containers(raw)
    for idx, event in _iter_timeline_events(raw):
        if event.get("action") != TimelineActionName.SLOW_COPY_START:
            continue
        target = event.get("target")
        temp_path = event.get("temp_path")
        final_path = event.get("to")
        if not isinstance(target, str) or not isinstance(temp_path, str):
            continue
        if isinstance(final_path, str) and _normalize(temp_path) == _normalize(final_path):
            reporter.error(
                code=E_SLOW_COPY_PATH_COLLISION,
                message=(
                    f"slow_copy_start temp_path equals to (final): "
                    f"{temp_path!r}; the multi-phase visibility contract "
                    f"requires the three paths to be pairwise distinct"
                ),
                loc=("timeline", idx, "temp_path"),
            )
            continue  # one error per event
        container = containers_by_asset.get(target)
        if container is None:
            continue  # asset undeclared; rule_target_unknown owns that
        initial_path = INITIAL_PATH_TEMPLATE.format(
            root_path=primary_path,
            asset_id=target,
            container=container,
        )
        if _normalize(temp_path) == _normalize(initial_path):
            reporter.error(
                code=E_SLOW_COPY_PATH_COLLISION,
                message=(
                    f"slow_copy_start temp_path equals the asset's initial "
                    f"path {initial_path!r}; the commit's unlink(initial) "
                    f"would wipe the temp file before the replace runs"
                ),
                loc=("timeline", idx, "temp_path"),
            )
