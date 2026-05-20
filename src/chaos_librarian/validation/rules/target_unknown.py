"""Rules 4 + 12: closed-set identifier checks.

``rule_target_unknown`` (E_TARGET_UNKNOWN) rejects timeline targets that
don't resolve to a declared asset id. ``rule_root_unknown``
(E_ROOT_UNKNOWN) rejects ``move_between_roots`` events that reference
unknown ``from_root_id`` / ``to_root_id`` values and rejects
``library.archive_root`` values that don't match any declared root id
(sentinel ``"archive"`` and ``None`` are both valid).

Both rules validate closed-set identifier references — keeping them
in one module keeps the helper imports and the "declared-id walk"
pattern together.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_ROOT_UNKNOWN, E_TARGET_UNKNOWN
from chaos_librarian.validation.rules._common import (
    Reporter,
    _as_mapping,
    _iter_timeline_events,
    _list_at_path,
    iter_asset_ids,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_root_unknown", "rule_target_unknown"]


def rule_target_unknown(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject timeline events whose ``target:`` is not a defined asset id.

    Events with no string ``target`` (e.g. ``slow_copy_commit``) are
    skipped: Pydantic's shape pass owns "the field must exist."
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    asset_ids = set(iter_asset_ids(raw))
    for idx, event in _iter_timeline_events(raw):
        target = event.get("target")
        if not isinstance(target, str):
            continue
        if target not in asset_ids:
            reporter.error(
                code=E_TARGET_UNKNOWN,
                message=f"target asset {target!r} is not defined in any bundle",
                loc=("timeline", idx, "target"),
            )


def rule_root_unknown(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject move_between_roots / archive_root referencing unknown roots.

    The closed set of valid root ids is ``library.roots[].id`` plus the
    sentinel ``"archive"`` (only for ``library.archive_root``). Non-string
    or absent values are skipped — Pydantic's shape pass owns shape errors.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    library = _as_mapping(raw.get("library"))
    if library is None:
        return  # Pydantic owns shape
    roots = _list_at_path(raw, ("library", "roots")) or []
    declared_ids: set[str] = set()
    for root_obj in roots:
        root = _as_mapping(root_obj)
        if root is None:
            continue
        root_id = root.get("id")
        if isinstance(root_id, str):
            declared_ids.add(root_id)

    archive_root = library.get("archive_root")
    if (
        isinstance(archive_root, str)
        and archive_root != "archive"
        and archive_root not in declared_ids
    ):
        reporter.error(
            code=E_ROOT_UNKNOWN,
            message=f"library.archive_root {archive_root!r} is not a declared root id",
            loc=("library", "archive_root"),
        )

    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        if action != TimelineActionName.MOVE_BETWEEN_ROOTS:
            continue
        for field in ("from_root_id", "to_root_id"):
            value = event.get(field)
            if not isinstance(value, str):
                continue  # Pydantic owns shape
            if value not in declared_ids:
                reporter.error(
                    code=E_ROOT_UNKNOWN,
                    message=f"{field} {value!r} is not a declared root id",
                    loc=("timeline", idx, field),
                )
