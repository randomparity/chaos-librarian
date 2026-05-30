"""Rule 1: E_ID_DUPLICATE — reject duplicate IDs across namespaces."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Final

from chaos_librarian.validation.codes import E_ID_DUPLICATE, format_jsonpath
from chaos_librarian.validation.rules._common import (
    Reporter,
    _as_mapping,
    _list_at_path,
    _Loc,
    first_or_duplicate,
    iter_global_namespaces,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_id_duplicate"]


# Top-level namespace labels used by the raw top-level ID walker.
# Hierarchy and tail namespaces live in ``_common`` because
# ``iter_global_namespaces`` yields them and other rule modules consume them.
NS_ROOT_ID: Final = "root_id"
NS_TIMELINE_ID: Final = "timeline_id"


def rule_id_duplicate(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject duplicate IDs across the scenario-global ID pool.

    Root, hierarchy, variant, bundle, asset, and timeline ids must all be
    unique because downstream target resolution and oracle state are flat by id.
    """
    reporter = Reporter(collector=collector, line_index=line_index)

    seen: dict[str, tuple[str, _Loc]] = {}
    for namespace, value, loc in _iter_top_level_ids(
        raw=raw, namespace=NS_ROOT_ID, path_parts=("library", "roots")
    ):
        _record_or_report(
            namespace=namespace,
            value=value,
            loc=loc,
            seen=seen,
            reporter=reporter,
        )

    for namespace, value, loc in iter_global_namespaces(raw):
        _record_or_report(
            namespace=namespace,
            value=value,
            loc=loc,
            seen=seen,
            reporter=reporter,
        )

    for namespace, value, loc in _iter_top_level_ids(
        raw=raw, namespace=NS_TIMELINE_ID, path_parts=("timeline",)
    ):
        _record_or_report(
            namespace=namespace,
            value=value,
            loc=loc,
            seen=seen,
            reporter=reporter,
        )


def _iter_top_level_ids(
    *,
    raw: Mapping[str, object],
    namespace: str,
    path_parts: tuple[str, ...],
) -> Iterator[tuple[str, str, _Loc]]:
    """Yield ids from one top-level list field with raw locations."""
    items = _list_at_path(raw, path_parts)
    if items is None:
        return
    for idx, item_obj in enumerate(items):
        item = _as_mapping(item_obj)
        if item is None:
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str):
            continue
        yield namespace, item_id, (*path_parts, idx, "id")


def _record_or_report(
    *,
    namespace: str,
    value: str,
    loc: _Loc,
    seen: dict[str, tuple[str, _Loc]],
    reporter: Reporter,
) -> None:
    first = first_or_duplicate(seen, value, (namespace, loc))
    if first is None:
        return
    first_namespace, first_loc = first
    first_path = format_jsonpath(first_loc)
    reporter.error(
        code=E_ID_DUPLICATE,
        message=(
            f"duplicate {namespace} {value!r} (first defined as {first_namespace} at {first_path})"
        ),
        loc=loc,
    )
