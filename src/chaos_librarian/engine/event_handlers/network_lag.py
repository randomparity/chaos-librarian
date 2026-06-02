"""Network-lag window event handlers."""

from __future__ import annotations

from chaos_librarian.clock import parse_duration
from chaos_librarian.contract.journal import (
    CommittedJournalEntry,
    JournalEntry,
    JournalPhase,
    StartedJournalEntry,
)
from chaos_librarian.contract.scenario import (
    NetworkLagCommitEvent,
    NetworkLagStartEvent,
    TimelineActionName,
)
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.engine.context import EngineEventContext
from chaos_librarian.engine.event_handlers.common import _checked_event, _location_ids_for_target
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState
from chaos_librarian.errors import ChaosLibrarianValueError


def _handle_network_lag_start(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, NetworkLagStartEvent)
    if ctx.previous_event_delta is None or ctx.previous_event_delta[0] != event.after:
        raise ChaosLibrarianValueError(
            f"network_lag_start must immediately follow after event {event.after!r}"
        )
    source_delta = ctx.previous_event_delta[1]
    duration_ns = parse_duration(event.duration)
    state_delta = _network_lag_delta(
        event=event,
        source_delta=source_delta,
        logical_start_ns=resolved.at_ns,
        requested_duration_ns=duration_ns,
    )
    ctx.pending_network_lags[event.id] = state_delta
    entry = StartedJournalEntry(
        schema_version=1,
        event_id=event.id,
        scenario_id=ctx.scenario_id,
        run_id=ctx.run_id,
        logical_time_ns=resolved.at_ns,
        action=TimelineActionName.NETWORK_LAG_START,
        target_ids=[event.target],
        location_ids=_location_ids_for_target(state, event.target),
        state_delta=state_delta,
        phase=JournalPhase.STARTED,
        temp_path=_network_lag_temp_path(event.id),
    )
    return (entry,)


def _handle_network_lag_commit(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, NetworkLagCommitEvent)
    state_delta = ctx.pending_network_lags.pop(event.for_)
    target_ref = state_delta.get("target_ref")
    target_ids = [target_ref] if isinstance(target_ref, str) else []
    entry = CommittedJournalEntry(
        schema_version=1,
        event_id=event.id,
        scenario_id=ctx.scenario_id,
        run_id=ctx.run_id,
        logical_time_ns=resolved.at_ns,
        action=TimelineActionName.NETWORK_LAG_COMMIT,
        target_ids=target_ids,
        location_ids=_location_ids_for_target(state, target_ref),
        state_delta=dict(state_delta),
        phase=JournalPhase.COMMITTED,
        related_event_id=event.for_,
    )
    return (entry,)


def _network_lag_delta(
    *,
    event: NetworkLagStartEvent,
    source_delta: dict[str, object],
    logical_start_ns: int,
    requested_duration_ns: int,
) -> dict[str, object]:
    return {
        "effect": event.effect.value,
        "target_ref": event.target,
        "after_event_id": event.after,
        "logical_start_ns": logical_start_ns,
        "logical_commit_ns": logical_start_ns + requested_duration_ns,
        "requested_duration_ns": requested_duration_ns,
        "from_path": _first_string(
            source_delta,
            ("from_path", "input_path", "removed_path", "sidecar_path"),
        ),
        "to_path": _first_string(
            source_delta,
            ("to_path", "output_path", "added_path", "final_path", "sidecar_path"),
        ),
    }


def _first_string(source: dict[str, object], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = source.get(key)
        if isinstance(value, str):
            return value
    return None


def _network_lag_temp_path(event_id: str) -> str:
    return f".chaos-librarian/network-lag/{event_id}"
