"""Rule: import_source.path must lexically resolve inside the scenario dir.

Validation rules never touch the filesystem, so containment is proven by
shape alone: a relative, non-empty path whose every component passes
``is_safe_path_component`` (which rejects ``..``, separators, and control
characters) can only resolve strictly under the scenario file's directory.
Existence and symlink escapes are re-checked by the materializer (ADR 0012).
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

from chaos_librarian.contract.paths import is_safe_path_component
from chaos_librarian.validation.codes import E_IMPORT_SOURCE_INVALID
from chaos_librarian.validation.rules.core.raw_helpers import (
    Reporter,
    _as_mapping,
    _Loc,
)
from chaos_librarian.validation.rules.hierarchy.walkers import iter_asset_contexts

if TYPE_CHECKING:
    from chaos_librarian.validation.reporting import IssueCollector
    from chaos_librarian.validation.scenario_io import LineIndex

__all__ = ["rule_import_source"]


def rule_import_source(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject import_source paths that could escape the scenario bundle."""
    reporter = Reporter(collector=collector, line_index=line_index)
    for context in iter_asset_contexts(raw):
        source = _as_mapping(context.asset.get("import_source"))
        if source is None:
            continue
        path_value = source.get("path")
        if not isinstance(path_value, str):
            continue  # Pydantic owns the type check
        _check_shape(path_value, (*context.asset_loc, "import_source", "path"), reporter)


def _check_shape(path_value: str, loc: _Loc, reporter: Reporter) -> None:
    if (
        not path_value
        or PurePosixPath(path_value).is_absolute()
        or path_value.startswith(("/", "\\"))
    ):
        reporter.error(
            code=E_IMPORT_SOURCE_INVALID,
            message="import_source.path must be relative and non-empty",
            loc=loc,
        )
        return
    parts = PurePosixPath(path_value).parts
    # PurePosixPath('.') and PurePosixPath('').parts are both () — reject the
    # empty-parts case explicitly, mirroring resolve_under_library's filter.
    if not parts or ".." in parts:
        reporter.error(
            code=E_IMPORT_SOURCE_INVALID,
            message="import_source.path must be non-empty and contain no '..'",
            loc=loc,
        )
        return
    for part in parts:
        if not is_safe_path_component(part):
            reporter.error(
                code=E_IMPORT_SOURCE_INVALID,
                message=f"import_source.path has unsafe component {part!r}",
                loc=loc,
            )
            return
