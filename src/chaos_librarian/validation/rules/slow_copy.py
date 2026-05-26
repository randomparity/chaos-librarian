"""Rules 5a + 5b + 5c: slow-copy structural / timing / path-collision checks.

5a (E_SLOW_COPY_UNPAIRED) and 5b (E_SLOW_COPY_TIMING) walk the same
start/commit index, so they share the ``_index_starts_and_commits``
helper in this module. 5c (E_SLOW_COPY_PATH_COLLISION) walks each
``slow_copy_start`` event independently and joins against the asset's
current projected path.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.path_rendering import replace_root_prefix
from chaos_librarian.validation.codes import (
    E_SLOW_COPY_PATH_COLLISION,
    E_SLOW_COPY_TIMING,
    E_SLOW_COPY_UNPAIRED,
)
from chaos_librarian.validation.rules._common import (
    Reporter,
    _as_mapping,
    _iter_timeline_events,
    _RawMapping,
    build_hierarchy_projection,
    is_hierarchy_action,
    iter_declared_roots,
    primary_root_path,
    rendered_asset_paths,
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
    """5c: reject ``temp_path == to`` and ``temp_path == current_path``.

    Phase B's commit helper unlinks ``initial_path`` and then ``replace``s
    ``temp_path -> final_path``. If ``temp_path == to`` the multi-phase
    visibility contract collapses; if ``temp_path == current_path`` the
    unlink wipes the temp before the replace runs. Both cases emit
    ``E_SLOW_COPY_PATH_COLLISION``.

    Path equality is checked on the ``os.path.normpath``-normalized form
    so a ``.``-segment or trailing-slash variant cannot slip past the
    rule. Normalization is purely lexical -- no I/O, no symlink resolution.

    Current paths are seeded through the same hierarchy-aware renderer used
    by initial-state construction, then projected through prior timeline
    path mutations before each slow_copy_start.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    current_paths = {asset_id: path for asset_id, (path, _loc) in rendered_asset_paths(raw).items()}
    pending_slow_copies: dict[str, tuple[str, str]] = {}
    hierarchy_projection = build_hierarchy_projection(raw)
    declared_roots = {
        root_id: path for root_id, path in iter_declared_roots(raw) if path is not None
    }
    archive_base = _archive_base_path(raw, declared_roots)
    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        if action == TimelineActionName.SLOW_COPY_START:
            _check_slow_copy_start_path_collision(
                event,
                idx=idx,
                current_paths=current_paths,
                pending_slow_copies=pending_slow_copies,
                reporter=reporter,
            )
        elif action == TimelineActionName.SLOW_COPY_COMMIT:
            _project_slow_copy_commit(event, pending_slow_copies, current_paths)
        elif action in {
            TimelineActionName.MOVE_ASSET,
            TimelineActionName.RENAME_FILE,
            TimelineActionName.ADD_FILE,
        }:
            _project_to_field_path(event, current_paths)
        elif action == TimelineActionName.DELETE_FILE:
            _project_deleted_path(event, current_paths)
        elif action == TimelineActionName.ARCHIVE_FILE:
            _project_archive_file(
                event,
                archive_base=archive_base,
                roots=declared_roots,
                current_paths=current_paths,
            )
        elif action == TimelineActionName.MOVE_BETWEEN_ROOTS:
            _project_move_between_roots(event, roots=declared_roots, current_paths=current_paths)
        elif action == TimelineActionName.REMUX_CONTAINER:
            _project_remux_container(event, current_paths)
        elif is_hierarchy_action(action):
            _project_hierarchy_action(event, hierarchy_projection, current_paths)


def _check_slow_copy_start_path_collision(
    event: _RawMapping,
    *,
    idx: int,
    current_paths: dict[str, str],
    pending_slow_copies: dict[str, tuple[str, str]],
    reporter: Reporter,
) -> None:
    """Check one slow_copy_start against final and current paths."""
    target = event.get("target")
    temp_path = event.get("temp_path")
    final_path = event.get("to")
    if not isinstance(target, str) or not isinstance(temp_path, str):
        return
    if isinstance(final_path, str):
        _project_slow_copy_start(event, pending_slow_copies)
        if _normalize(temp_path) == _normalize(final_path):
            reporter.error(
                code=E_SLOW_COPY_PATH_COLLISION,
                message=(
                    f"slow_copy_start temp_path equals to (final): "
                    f"{temp_path!r}; the multi-phase visibility contract "
                    f"requires the three paths to be pairwise distinct"
                ),
                loc=("timeline", idx, "temp_path"),
            )
            return  # one error per event
    current_path = current_paths.get(target)
    if current_path is None:
        return  # asset undeclared or currently deleted; other rules own that
    if _normalize(temp_path) == _normalize(current_path):
        reporter.error(
            code=E_SLOW_COPY_PATH_COLLISION,
            message=(
                f"slow_copy_start temp_path equals the asset's current "
                f"path {current_path!r}; the commit's unlink(current) "
                f"would wipe the temp file before the replace runs"
            ),
            loc=("timeline", idx, "temp_path"),
        )


def _project_to_field_path(event: _RawMapping, current_paths: dict[str, str]) -> None:
    target = event.get("target")
    path = event.get("to")
    if isinstance(target, str) and isinstance(path, str):
        current_paths[target] = path


def _project_deleted_path(event: _RawMapping, current_paths: dict[str, str]) -> None:
    target = event.get("target")
    if isinstance(target, str):
        current_paths.pop(target, None)


def _project_slow_copy_start(
    event: _RawMapping,
    pending_slow_copies: dict[str, tuple[str, str]],
) -> None:
    event_id = event.get("id")
    target = event.get("target")
    final_path = event.get("to")
    if isinstance(event_id, str) and isinstance(target, str) and isinstance(final_path, str):
        pending_slow_copies[event_id] = (target, final_path)


def _project_slow_copy_commit(
    event: _RawMapping,
    pending_slow_copies: dict[str, tuple[str, str]],
    current_paths: dict[str, str],
) -> None:
    start_id = event.get("for")
    if not isinstance(start_id, str):
        return
    pending = pending_slow_copies.pop(start_id, None)
    if pending is None:
        return
    target, final_path = pending
    current_paths[target] = final_path


def _project_archive_file(
    event: _RawMapping,
    *,
    archive_base: str | None,
    roots: Mapping[str, str],
    current_paths: dict[str, str],
) -> None:
    target = event.get("target")
    if not isinstance(target, str) or archive_base is None:
        return
    current_path = current_paths.get(target)
    if current_path is None:
        return
    try:
        current_root = _current_root_for_path(current_path, roots)
        current_paths[target] = replace_root_prefix(
            current_path,
            from_root=current_root,
            to_root=archive_base,
        )
    except ValueError:
        return


def _project_move_between_roots(
    event: _RawMapping,
    *,
    roots: Mapping[str, str],
    current_paths: dict[str, str],
) -> None:
    target = event.get("target")
    from_root_id = event.get("from_root_id")
    to_root_id = event.get("to_root_id")
    if not isinstance(target, str):
        return
    if not isinstance(from_root_id, str) or not isinstance(to_root_id, str):
        return
    from_root_path = roots.get(from_root_id)
    to_root_path = roots.get(to_root_id)
    current_path = current_paths.get(target)
    if from_root_path is None or to_root_path is None or current_path is None:
        return
    try:
        current_paths[target] = replace_root_prefix(
            current_path,
            from_root=from_root_path,
            to_root=to_root_path,
        )
    except ValueError:
        return


def _project_remux_container(event: _RawMapping, current_paths: dict[str, str]) -> None:
    target = event.get("target")
    to_container = event.get("to_container")
    if not isinstance(target, str) or not isinstance(to_container, str):
        return
    current_path = current_paths.get(target)
    if current_path is None:
        return
    current_paths[target] = _swap_extension(current_path, to_container)


def _project_hierarchy_action(event, hierarchy_projection, current_paths: dict[str, str]) -> None:
    mutation = hierarchy_projection.apply(event)
    for asset_id in mutation.affected_asset_ids:
        path = hierarchy_projection.current_paths.get(asset_id)
        if path is None:
            current_paths.pop(asset_id, None)
        else:
            current_paths[asset_id] = path


def _current_root_for_path(path: str, roots: Mapping[str, str]) -> str:
    root_paths: list[str] = list(roots.values())
    root_paths.sort(key=len, reverse=True)
    for root_path in root_paths:
        if path == root_path or path.startswith(f"{root_path}/"):
            return root_path
    raise ValueError("current path does not start with a declared root")


def _archive_base_path(raw: _RawMapping, declared_roots: Mapping[str, str]) -> str | None:
    primary_path = primary_root_path(raw)
    if primary_path is None:
        return None
    library = _as_mapping(raw.get("library"))
    archive_root = library.get("archive_root") if library is not None else None
    if archive_root is None or archive_root == "archive":
        return f"{primary_path}/archive"
    if isinstance(archive_root, str):
        return declared_roots.get(archive_root)
    return None


def _swap_extension(path: str, new_ext: str) -> str:
    basename = path.rsplit("/", 1)[-1]
    if "." in basename:
        base = path.rsplit(".", 1)[0]
        return f"{base}.{new_ext}"
    return f"{path}.{new_ext}"
