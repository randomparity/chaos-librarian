"""Rule 2: E_PATH_DUPLICATE — warn on library roots that share a path."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.validation.codes import E_PATH_DUPLICATE, format_jsonpath
from chaos_librarian.validation.rules._common import _as_mapping, _list_at_path, _Loc

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_path_duplicate"]


def rule_path_duplicate(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Warn on two library roots with the same ``path`` (distinct IDs).

    WARNING severity — does not flip ``report.ok``. Authors who genuinely
    want to alias a directory under two ID namespaces can ignore it.
    """
    roots = _list_at_path(raw, ("library", "roots"))
    if roots is None:
        return
    seen: dict[str, _Loc] = {}
    for idx, root_obj in enumerate(roots):
        root = _as_mapping(root_obj)
        if root is None:
            continue
        path = root.get("path")
        if not isinstance(path, str):
            continue
        loc: _Loc = ("library", "roots", idx, "path")
        if path in seen:
            first_path = format_jsonpath(seen[path])
            collector.add(
                code=E_PATH_DUPLICATE,
                severity=ValidationSeverity.WARNING,
                message=f"root path {path!r} already used at {first_path}",
                loc=loc,
                line_index=line_index,
            )
        else:
            seen[path] = loc
