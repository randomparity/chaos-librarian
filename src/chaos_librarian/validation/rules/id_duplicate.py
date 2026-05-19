"""Rule 1: E_ID_DUPLICATE — reject duplicate IDs across namespaces."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING, Final

from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.validation.codes import E_ID_DUPLICATE, format_jsonpath
from chaos_librarian.validation.rules._common import (
    _as_list,
    _as_mapping,
    _list_at_path,
    _Loc,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["iter_asset_ids", "rule_id_duplicate"]


# Namespace labels used in E_ID_DUPLICATE messages and as control-flow keys
# (e.g., ``rule_target_unknown`` filters ``iter_global_namespaces`` on
# ``NS_ASSET_ID``). String literals would silently break that filter on typo.
NS_ROOT_ID: Final = "root_id"
NS_WORK_ID: Final = "work_id"
NS_TIMELINE_ID: Final = "timeline_id"
NS_VARIANT_ID: Final = "variant_id"
NS_BUNDLE_ID: Final = "bundle_id"
NS_ASSET_ID: Final = "asset_id"


def rule_id_duplicate(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject duplicate IDs per the namespace table in the Sprint 1 spec.

    Global namespaces (across the whole scenario): variant_id, bundle_id,
    asset_id. Top-level namespaces: root_id, work_id, timeline_id.
    """
    _check_top_level_dups(
        raw=raw,
        namespace=NS_ROOT_ID,
        path_parts=("library", "roots"),
        line_index=line_index,
        collector=collector,
    )
    _check_top_level_dups(
        raw=raw,
        namespace=NS_WORK_ID,
        path_parts=("works",),
        line_index=line_index,
        collector=collector,
    )
    _check_top_level_dups(
        raw=raw,
        namespace=NS_TIMELINE_ID,
        path_parts=("timeline",),
        line_index=line_index,
        collector=collector,
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
            line_index=line_index,
            collector=collector,
        )


def iter_global_namespaces(
    raw: Mapping[str, object],
) -> Iterator[tuple[str, str, _Loc]]:
    """Yield ``(namespace, id_value, loc)`` for every variant/bundle/asset id.

    Walks ``works[*].variants[*].bundle.assets[*]`` and skips any sub-tree
    whose shape Pydantic would have rejected; shape errors are surfaced by
    the shape pass, not here.
    """
    works = _as_list(raw.get("works"))
    if works is None:
        return
    for w_idx, work_obj in enumerate(works):
        work = _as_mapping(work_obj)
        if work is None:
            continue
        variants = _as_list(work.get("variants"))
        if variants is None:
            continue
        for v_idx, variant in enumerate(variants):
            yield from _iter_variant(variant, w_idx=w_idx, v_idx=v_idx)


def iter_asset_ids(raw: Mapping[str, object]) -> Iterator[str]:
    """Yield every ``asset_id`` value defined in the scenario.

    Implemented as a filter over ``iter_global_namespaces`` rather than a
    fresh walker so the shape-skipping logic stays in one place; Rule 1
    needs the locs (and the variant/bundle namespaces), Rules 4 and 8
    only need the asset-id values.
    """
    for namespace, value, _ in iter_global_namespaces(raw):
        if namespace == NS_ASSET_ID:
            yield value


def _iter_variant(
    variant_obj: object,
    *,
    w_idx: int,
    v_idx: int,
) -> Iterator[tuple[str, str, _Loc]]:
    """Yield ids for one variant and the bundle/assets nested below it."""
    variant = _as_mapping(variant_obj)
    if variant is None:
        return
    v_id = variant.get("id")
    if isinstance(v_id, str):
        yield NS_VARIANT_ID, v_id, ("works", w_idx, "variants", v_idx, "id")
    bundle = _as_mapping(variant.get("bundle"))
    if bundle is None:
        return
    b_id = bundle.get("id")
    bundle_path: _Loc = ("works", w_idx, "variants", v_idx, "bundle")
    if isinstance(b_id, str):
        yield NS_BUNDLE_ID, b_id, (*bundle_path, "id")
    yield from _iter_bundle_assets(bundle.get("assets"), bundle_path=bundle_path)


def _iter_bundle_assets(
    assets_obj: object,
    *,
    bundle_path: _Loc,
) -> Iterator[tuple[str, str, _Loc]]:
    """Yield ``asset_id`` triples for each well-shaped asset under a bundle."""
    assets = _as_list(assets_obj)
    if assets is None:
        return
    for a_idx, asset_obj in enumerate(assets):
        asset = _as_mapping(asset_obj)
        if asset is None:
            continue
        a_id = asset.get("id")
        if isinstance(a_id, str):
            yield NS_ASSET_ID, a_id, (*bundle_path, "assets", a_idx, "id")


def _check_top_level_dups(
    *,
    raw: Mapping[str, object],
    namespace: str,
    path_parts: tuple[str, ...],
    line_index: LineIndex,
    collector: IssueCollector,
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
            line_index=line_index,
            collector=collector,
        )


def _record_or_report(
    *,
    namespace: str,
    value: str,
    loc: _Loc,
    seen: dict[str, _Loc],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    if value in seen:
        first_path = format_jsonpath(seen[value])
        collector.add(
            code=E_ID_DUPLICATE,
            severity=ValidationSeverity.ERROR,
            message=f"duplicate {namespace} {value!r} (first defined at {first_path})",
            loc=loc,
            line_index=line_index,
        )
    else:
        seen[value] = loc
