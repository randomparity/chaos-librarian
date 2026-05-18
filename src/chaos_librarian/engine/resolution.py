"""Timeline resolution.

Converts a validated Scenario's string-typed ``timeline[*].at`` values into
ordered numeric (``at_ns``, declared index, event) triples. Sprint 1's
validation pipeline has already proven every ``at:`` parses and the
timeline is non-decreasing; this module re-parses for the integer value
and does not re-validate semantics. Ordering on ties preserves declared
order, matching docs/specs/chaos-librarian-design.md §"Mutation Model".
"""

from __future__ import annotations

from dataclasses import dataclass

from chaos_librarian.clock import parse_duration
from chaos_librarian.contract.scenario import Scenario, TimelineEvent


@dataclass(frozen=True)
class ResolvedEvent:
    """One timeline event with its parsed numeric timestamp."""

    at_ns: int
    declared_index: int
    event: TimelineEvent


def resolve_timeline(scenario: Scenario) -> list[ResolvedEvent]:
    """Return the scenario's timeline as numeric, ordered ``ResolvedEvent``s.

    Args:
        scenario: A validated Scenario instance.

    Returns:
        Events ordered by ``(at_ns, declared_index)``. Empty if the scenario
        has an empty timeline.
    """
    resolved = [
        ResolvedEvent(at_ns=parse_duration(event.at), declared_index=idx, event=event)
        for idx, event in enumerate(scenario.timeline)
    ]
    resolved.sort(key=lambda r: (r.at_ns, r.declared_index))
    return resolved
