"""Rule 6: E_PATH_CONTAINMENT — reject paths that escape library containment."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from chaos_librarian.contract.paths import PathContainmentError, resolve_under_library
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_PATH_CONTAINMENT
from chaos_librarian.validation.rules._common import (
    Reporter,
    _as_mapping,
    _iter_timeline_events,
    _list_at_path,
    _Loc,
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


def _check_containment(raw_path: str, *, loc: _Loc, reporter: Reporter) -> None:
    try:
        resolve_under_library(Path(raw_path), _SYNTHETIC_LIBRARY_ROOT)
    except PathContainmentError as e:
        reporter.error(code=E_PATH_CONTAINMENT, message=str(e), loc=loc)
