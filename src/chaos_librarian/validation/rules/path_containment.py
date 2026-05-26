"""Rule 6: E_PATH_CONTAINMENT — reject paths that escape library containment."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from chaos_librarian.contract.paths import (
    PathContainmentError,
    resolve_under_library,
)
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.path_rendering import replace_root_prefix
from chaos_librarian.validation.codes import E_PATH_CONTAINMENT
from chaos_librarian.validation.rules._common import (
    Reporter,
    _as_mapping,
    _iter_timeline_events,
    _list_at_path,
    _Loc,
    _RawMapping,
    iter_declared_roots,
    primary_root_path,
    rendered_asset_paths,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_path_containment"]


_SYNTHETIC_LIBRARY_ROOT: Path = Path("/__chaos_librarian_validate__/library")

# Per-action-variant path field names. Keys are the discriminator values
# declared on TimelineEvent variants in contract/scenario.py; using the
# StrEnum binds this map to the contract symbol set at the type level —
# adding/renaming an action surfaces here, not as a silent miss.
_PATH_FIELDS_BY_ACTION: dict[str, tuple[str, ...]] = {
    TimelineActionName.MOVE_ASSET: ("to",),
    TimelineActionName.RENAME_FILE: ("to",),
    TimelineActionName.ADD_FILE: ("to",),
    TimelineActionName.CREATE_SIDECAR: ("to",),
    TimelineActionName.SLOW_COPY_START: ("to", "temp_path"),
    TimelineActionName.EXTRACT_SUBTITLE: ("to",),
}


def rule_path_containment(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject paths that violate library-root containment.

    Uses ``contract.paths.resolve_under_library`` against a synthetic
    absolute root. The helper's structural checks (absolute, ``..``,
    empty) do not require the root to exist on the filesystem.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    _check_root_paths(raw, reporter)
    _check_timeline_paths(raw, reporter)
    _check_synthesized_timeline_paths(raw, reporter)


def _check_root_paths(raw: Mapping[str, object], reporter: Reporter) -> None:
    """Containment-check every ``library.roots[*].path``."""
    roots = _list_at_path(raw, ("library", "roots"))
    if roots is None:
        return
    for idx, root_obj in enumerate(roots):
        root = _as_mapping(root_obj)
        if root is None:
            continue
        path = root.get("path")
        if isinstance(path, str):
            _check_containment(path, loc=("library", "roots", idx, "path"), reporter=reporter)


def _check_timeline_paths(raw: Mapping[str, object], reporter: Reporter) -> None:
    """Containment-check every ``to:`` / ``temp_path:`` on timeline events."""
    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        if not isinstance(action, str):
            continue
        for field_name in _PATH_FIELDS_BY_ACTION.get(action, ()):
            value = event.get(field_name)
            if isinstance(value, str):
                _check_containment(value, loc=("timeline", idx, field_name), reporter=reporter)


def _check_synthesized_timeline_paths(raw: _RawMapping, reporter: Reporter) -> None:
    """Containment-check synthesized destinations for actions with no ``to:`` field.

    ``archive_file`` and ``move_between_roots`` derive their destination
    from library config (the archive root / target root path plus the
    asset container) the same way the engine handlers do via
    ``state.archive_path_for`` and ``state.root_path_for``. The rule
    must run the synthesized path through containment so an escape via
    library config is caught at validate-time, not at materialize-time.
    """
    declared_roots = {
        root_id: path for root_id, path in iter_declared_roots(raw) if path is not None
    }
    archive_base = _archive_base_path(raw, declared_roots)
    current_paths = {asset_id: path for asset_id, (path, _loc) in rendered_asset_paths(raw).items()}
    pending_slow_copies: dict[str, tuple[str, str]] = {}

    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        if action == TimelineActionName.ARCHIVE_FILE:
            _check_archive_file(
                event,
                idx=idx,
                archive_base=archive_base,
                declared_roots=declared_roots,
                current_paths=current_paths,
                reporter=reporter,
            )
        elif action == TimelineActionName.MOVE_BETWEEN_ROOTS:
            _check_move_between_roots(
                event,
                idx=idx,
                declared_roots=declared_roots,
                current_paths=current_paths,
                reporter=reporter,
            )
        elif action in {
            TimelineActionName.MOVE_ASSET,
            TimelineActionName.RENAME_FILE,
            TimelineActionName.ADD_FILE,
        }:
            _project_to_field_path(event, current_paths)
        elif action == TimelineActionName.SLOW_COPY_START:
            _project_slow_copy_start(event, pending_slow_copies)
        elif action == TimelineActionName.SLOW_COPY_COMMIT:
            _project_slow_copy_commit(event, pending_slow_copies, current_paths)
        elif action == TimelineActionName.DELETE_FILE:
            _project_deleted_path(event, current_paths)


def _check_archive_file(
    event: _RawMapping,
    *,
    idx: int,
    archive_base: str | None,
    declared_roots: Mapping[str, str],
    current_paths: dict[str, str],
    reporter: Reporter,
) -> None:
    """Synthesize and check the archive destination for one ``archive_file``."""
    target = event.get("target")
    if not isinstance(target, str) or archive_base is None:
        return
    current_path = current_paths.get(target)
    if current_path is None:
        return
    try:
        current_root = _current_root_for_path(current_path, declared_roots)
        synthesized = replace_root_prefix(
            current_path,
            from_root=current_root,
            to_root=archive_base,
        )
    except ValueError as error:
        reporter.error(code=E_PATH_CONTAINMENT, message=str(error), loc=("timeline", idx, "target"))
        return
    _check_containment(synthesized, loc=("timeline", idx, "target"), reporter=reporter)
    current_paths[target] = synthesized


def _check_move_between_roots(
    event: _RawMapping,
    *,
    idx: int,
    declared_roots: Mapping[str, str],
    current_paths: dict[str, str],
    reporter: Reporter,
) -> None:
    """Synthesize and check the destination for one ``move_between_roots``."""
    target = event.get("target")
    from_root_id = event.get("from_root_id")
    to_root_id = event.get("to_root_id")
    if not isinstance(target, str):
        return
    if not isinstance(from_root_id, str) or not isinstance(to_root_id, str):
        return
    from_root_path = declared_roots.get(from_root_id)
    to_root_path = declared_roots.get(to_root_id)
    current_path = current_paths.get(target)
    if from_root_path is None or to_root_path is None or current_path is None:
        return
    try:
        synthesized = replace_root_prefix(
            current_path,
            from_root=from_root_path,
            to_root=to_root_path,
        )
    except ValueError as error:
        reporter.error(
            code=E_PATH_CONTAINMENT,
            message=str(error),
            loc=("timeline", idx, "to_root_id"),
        )
        return
    _check_containment(synthesized, loc=("timeline", idx, "to_root_id"), reporter=reporter)
    current_paths[target] = synthesized


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


def _current_root_for_path(path: str, declared_roots: Mapping[str, str]) -> str:
    root_paths: list[str] = list(declared_roots.values())
    root_paths.sort(key=len, reverse=True)
    for root_path in root_paths:
        if path == root_path or path.startswith(f"{root_path}/"):
            return root_path
    raise ValueError("current path does not start with a declared root")


def _archive_base_path(
    raw: _RawMapping,
    declared_roots: Mapping[str, str],
) -> str | None:
    """Return the archive base path, mirroring ``build_initial_state``.

    Sentinel ``"archive"`` and ``None`` both resolve to
    ``<primary_root.path>/archive``. A named ``archive_root`` resolves to
    that declared root's path. Returns ``None`` when the library subtree
    is malformed enough to defeat the lookup — the shape pass (or
    ``rule_root_unknown``) owns those error reports.
    """
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


def _check_containment(raw_path: str, *, loc: _Loc, reporter: Reporter) -> None:
    try:
        resolve_under_library(Path(raw_path), _SYNTHETIC_LIBRARY_ROOT)
    except PathContainmentError as e:
        reporter.error(code=E_PATH_CONTAINMENT, message=str(e), loc=loc)
