"""Rule 9: E_PATH_CONTAINMENT on asset.id / asset.container."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.paths import is_safe_path_component
from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.validation.codes import E_PATH_CONTAINMENT
from chaos_librarian.validation.rules._common import _as_list, _as_mapping, _Loc, _RawMapping

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["iter_assets_with_loc", "rule_asset_id_container_safe"]


def rule_asset_id_container_safe(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject ``asset.id`` / ``asset.container`` values that escape containment.

    ``build_initial_state`` synthesizes the initial location path as
    ``f"{root.path}/{asset.id}.{asset.container}"``. Without this rule a
    scenario could write a manifest path outside the library root by
    embedding a separator or a ``..`` segment in either field. Reuses
    ``E_PATH_CONTAINMENT`` because the guarantee is the same as for
    timeline paths — keep the consumer-facing taxonomy small.
    """
    for asset, asset_loc in iter_assets_with_loc(raw):
        for field_name in ("id", "container"):
            value = asset.get(field_name)
            if not isinstance(value, str):
                continue  # Pydantic owns "field is a string"
            if not is_safe_path_component(value):
                collector.add(
                    code=E_PATH_CONTAINMENT,
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"asset.{field_name} {value!r} is not a safe path component "
                        f"(would escape library containment when used in synthesized paths)"
                    ),
                    loc=(*asset_loc, field_name),
                    line_index=line_index,
                )


def iter_assets_with_loc(
    raw: Mapping[str, object],
) -> Iterator[tuple[_RawMapping, _Loc]]:
    """Yield ``(asset_mapping, loc)`` for every well-shaped asset.

    Reuses the same walk shape as ``iter_global_namespaces`` but yields
    the full asset sub-mapping so rules can inspect any field on it.
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
        for v_idx, variant_obj in enumerate(variants):
            variant = _as_mapping(variant_obj)
            if variant is None:
                continue
            bundle = _as_mapping(variant.get("bundle"))
            if bundle is None:
                continue
            assets = _as_list(bundle.get("assets"))
            if assets is None:
                continue
            for a_idx, asset_obj in enumerate(assets):
                asset = _as_mapping(asset_obj)
                if asset is None:
                    continue
                loc: _Loc = (
                    "works",
                    w_idx,
                    "variants",
                    v_idx,
                    "bundle",
                    "assets",
                    a_idx,
                )
                yield asset, loc
