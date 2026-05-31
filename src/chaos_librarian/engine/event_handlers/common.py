"""Shared primitives for plan-engine event handlers."""

from __future__ import annotations

from collections.abc import Callable

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalEntry, JournalPhase
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.engine.context import EngineEventContext
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState
from chaos_librarian.errors import ChaosLibrarianValueError


def _checked_event[EventT](resolved: ResolvedEvent, event_type: type[EventT]) -> EventT:
    event = resolved.event
    if not isinstance(event, event_type):
        raise ChaosLibrarianValueError(
            f"{event.action}: expected {event_type.__name__}, got {type(event).__name__}"
        )
    return event


_Handler = Callable[
    [WorldState, ResolvedEvent, IdAllocator, EngineEventContext],
    tuple[JournalEntry, ...],
]


def _new_atomic_entry(
    *,
    resolved: ResolvedEvent,
    ctx: EngineEventContext,
    action: str,
    target_ids: list[str],
    location_ids: list[str],
    state_delta: dict[str, object],
    input_version_ids: list[str] | None = None,
    output_version_ids: list[str] | None = None,
) -> AtomicJournalEntry:
    return AtomicJournalEntry(
        schema_version=1,
        event_id=resolved.event.id,
        scenario_id=ctx.scenario_id,
        run_id=ctx.run_id,
        logical_time_ns=resolved.at_ns,
        action=action,
        target_ids=target_ids,
        input_version_ids=input_version_ids or [],
        output_version_ids=output_version_ids or [],
        location_ids=location_ids,
        state_delta=state_delta,
        phase=JournalPhase.ATOMIC,
    )


def _location_ids_for_target(state: WorldState, target: object) -> list[str]:
    if not isinstance(target, str) or not state.has_location(target):
        return []
    return [state.location_id_for_asset(target)]
