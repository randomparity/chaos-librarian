"""Rule 4: E_TARGET_UNKNOWN — reject timeline targets not declared as assets."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.validation.codes import E_TARGET_UNKNOWN
from chaos_librarian.validation.rules._common import (
    Reporter,
    _iter_timeline_events,
    iter_asset_ids,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_target_unknown"]


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
