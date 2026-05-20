"""Rule 1: E_ID_DUPLICATE — reject duplicate IDs across namespaces."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from chaos_librarian.validation.codes import E_ID_DUPLICATE, format_jsonpath
from chaos_librarian.validation.rules._common import (
    NS_ASSET_ID,
    NS_BUNDLE_ID,
    NS_VARIANT_ID,
    Reporter,
    _as_mapping,
    _list_at_path,
    _Loc,
    iter_global_namespaces,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_id_duplicate"]


# Top-level namespace labels used only by ``_check_top_level_dups`` below.
# Global namespaces (variant/bundle/asset) live in ``_common`` because
# ``iter_global_namespaces`` yields them and other rule modules consume
# them via the walker.
NS_ROOT_ID: Final = "root_id"
NS_WORK_ID: Final = "work_id"
NS_TIMELINE_ID: Final = "timeline_id"


def rule_id_duplicate(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject duplicate IDs per the namespace table in the Sprint 1 spec.

    Global namespaces (across the whole scenario): variant_id, bundle_id,
    asset_id. Top-level namespaces: root_id, work_id, timeline_id.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    for namespace, path_parts in (
        (NS_ROOT_ID, ("library", "roots")),
        (NS_WORK_ID, ("works",)),
        (NS_TIMELINE_ID, ("timeline",)),
    ):
        _check_top_level_dups(
            raw=raw, namespace=namespace, path_parts=path_parts, reporter=reporter
        )

    seen: dict[str, dict[str, _Loc]] = {
        NS_VARIANT_ID: {},
        NS_BUNDLE_ID: {},
        NS_ASSET_ID: {},
    }
    for namespace, value, loc in iter_global_namespaces(raw):
        _record_or_report(
            namespace=namespace,
            value=value,
            loc=loc,
            seen=seen[namespace],
            reporter=reporter,
        )


def _check_top_level_dups(
    *,
    raw: Mapping[str, object],
    namespace: str,
    path_parts: tuple[str, ...],
    reporter: Reporter,
) -> None:
    """Top-level duplicate-id check: walk one list field and report collisions."""
    items = _list_at_path(raw, path_parts)
    if items is None:
        return
    seen: dict[str, _Loc] = {}
    for idx, item_obj in enumerate(items):
        item = _as_mapping(item_obj)
        if item is None:
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str):
            continue
        loc = (*path_parts, idx, "id")
        _record_or_report(
            namespace=namespace,
            value=item_id,
            loc=loc,
            seen=seen,
            reporter=reporter,
        )


def _record_or_report(
    *,
    namespace: str,
    value: str,
    loc: _Loc,
    seen: dict[str, _Loc],
    reporter: Reporter,
) -> None:
    if value in seen:
        first_path = format_jsonpath(seen[value])
        reporter.error(
            code=E_ID_DUPLICATE,
            message=f"duplicate {namespace} {value!r} (first defined at {first_path})",
            loc=loc,
        )
    else:
        seen[value] = loc
