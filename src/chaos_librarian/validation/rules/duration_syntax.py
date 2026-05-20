"""Rule 3: E_DURATION_SYNTAX — reject unparseable duration strings.

``try_parse_duration`` (used by Rules 5b and 7 to skip pairs Rule 3 has
already flagged) lives in ``rules/_common.py`` so rule modules depend on
each other only through ``semantic.py``'s ``_RULES`` registry.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.clock import DurationParseError, parse_duration
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.validation.codes import E_DURATION_SYNTAX
from chaos_librarian.validation.rules._common import _iter_timeline_events, _Loc

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_duration_syntax"]


def rule_duration_syntax(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject unparseable duration strings on timeline events.

    Fields checked: ``timeline[*].at`` (every event) and
    ``slow_copy_start.duration`` (only when ``action == "slow_copy_start"``).
    """
    for idx, event in _iter_timeline_events(raw):
        at = event.get("at")
        if isinstance(at, str):
            _check_duration(
                raw_str=at,
                loc=("timeline", idx, "at"),
                field_label="at duration",
                line_index=line_index,
                collector=collector,
            )
        if event.get("action") == TimelineActionName.SLOW_COPY_START:
            duration = event.get("duration")
            if isinstance(duration, str):
                _check_duration(
                    raw_str=duration,
                    loc=("timeline", idx, "duration"),
                    field_label="duration",
                    line_index=line_index,
                    collector=collector,
                )


def _check_duration(
    *,
    raw_str: str,
    loc: _Loc,
    field_label: str,
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Parse one duration string; on failure, emit one E_DURATION_SYNTAX issue."""
    try:
        parse_duration(raw_str)
    except DurationParseError as e:
        collector.add(
            code=E_DURATION_SYNTAX,
            severity=ValidationSeverity.ERROR,
            message=f"invalid {field_label} {raw_str!r}: {e.reason}",
            loc=loc,
            line_index=line_index,
        )
