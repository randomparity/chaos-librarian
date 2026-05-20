"""Rule 9: E_PATH_CONTAINMENT on asset.id / asset.container."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.paths import is_safe_path_component
from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.validation.codes import E_PATH_CONTAINMENT
from chaos_librarian.validation.rules._common import iter_assets_with_loc

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_asset_id_container_safe"]


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
