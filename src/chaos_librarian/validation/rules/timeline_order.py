"""Rule 7: E_TIMELINE_ORDER — reject out-of-order timeline events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.validation.codes import E_TIMELINE_ORDER
from chaos_librarian.validation.rules.raw_helpers import (
    Reporter,
    _iter_timeline_events,
    try_parse_duration,
)

if TYPE_CHECKING:
    from chaos_librarian.validation.reporting import IssueCollector
    from chaos_librarian.validation.scenario_io import LineIndex

__all__ = ["rule_timeline_order"]


def rule_timeline_order(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject timeline events whose ``at:`` is earlier than the previous one.

    Ties are allowed. Pairs where either ``at:`` is unparseable are
    skipped (Rule 3 already flagged the unparseable string).
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    last_ns: int | None = None
    last_idx: int = -1
    for idx, event in _iter_timeline_events(raw):
        at = event.get("at")
        if not isinstance(at, str):
            continue
        at_ns = try_parse_duration(at)
        if at_ns is None:
            # Rule 3 (E_DURATION_SYNTAX) already reported the unparseable
            # string; don't re-flag it as an order violation here.
            continue
        if last_ns is not None and at_ns < last_ns:
            reporter.error(
                code=E_TIMELINE_ORDER,
                message=f"timeline event at {at!r} precedes previous event at index {last_idx}",
                loc=("timeline", idx, "at"),
            )
        last_ns = at_ns
        last_idx = idx
