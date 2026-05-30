"""Content-dedup / shared-inode reference checks (E_TARGET_UNKNOWN).

``rule_content_reference`` resolves the asset-id references introduced by the
content-dedup fields ``same_content_as`` and ``hash_collision_with`` (scenario
v25) and the shared-inode field ``hardlinked_to`` (scenario v26). A reference is
rejected with ``E_TARGET_UNKNOWN`` when it names an undeclared asset, names the
referencing asset itself, or names an asset declared *later* than the referrer.

The earlier-declaration requirement is load-bearing: the materializer copies the
referent's already-written bytes / ``os.link``s its already-written file / reads
its already-stamped recorded hash in a single declaration-ordered pass, so a
forward reference does not resolve at the point it is needed. The forward case
reuses ``E_TARGET_UNKNOWN`` (a documented semantic stretch — see ADR 0004 Q4 and
ADR 0005 Q2) so the rule carries one code.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.validation.codes import E_TARGET_UNKNOWN
from chaos_librarian.validation.rules._common import (
    Reporter,
    _Loc,
    entity_ids_by_kind,
    iter_assets_with_loc,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_content_reference"]


_CONTENT_REFERENCE_FIELDS: tuple[str, ...] = (
    "same_content_as",
    "hash_collision_with",
    "hardlinked_to",
)


def rule_content_reference(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject same_content_as / hash_collision_with references that do not resolve.

    Walks assets in declaration order, tracking the ids seen so far so a forward
    or self reference is caught alongside the unknown-id case.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    declared_ids = entity_ids_by_kind(raw)["asset"]
    seen_ids: set[str] = set()
    for asset, asset_loc in iter_assets_with_loc(raw):
        asset_id = asset.get("id")
        for field in _CONTENT_REFERENCE_FIELDS:
            _check_reference(
                asset=asset,
                asset_id=asset_id,
                field=field,
                declared_ids=declared_ids,
                seen_ids=seen_ids,
                asset_loc=asset_loc,
                reporter=reporter,
            )
        if isinstance(asset_id, str):
            seen_ids.add(asset_id)


def _check_reference(
    *,
    asset: Mapping[str, object],
    asset_id: object,
    field: str,
    declared_ids: set[str],
    seen_ids: set[str],
    asset_loc: _Loc,
    reporter: Reporter,
) -> None:
    reference = asset.get(field)
    if not isinstance(reference, str):
        return  # Pydantic owns shape; None / non-string is not this rule's concern.
    loc = (*asset_loc, field)
    if reference not in declared_ids:
        reporter.error(
            code=E_TARGET_UNKNOWN,
            message=f"{field} references unknown asset {reference!r}",
            loc=loc,
        )
        return
    if reference == asset_id:
        reporter.error(
            code=E_TARGET_UNKNOWN,
            message=f"{field} must not reference the asset itself",
            loc=loc,
        )
        return
    if reference not in seen_ids:
        reporter.error(
            code=E_TARGET_UNKNOWN,
            message=f"{field} {reference!r} must reference an earlier-declared asset",
            loc=loc,
        )
