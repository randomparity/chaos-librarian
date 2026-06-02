"""Network-filesystem chaos event handlers."""

from __future__ import annotations

from chaos_librarian.contract.journal import (
    CommittedJournalEntry,
    JournalEntry,
    JournalPhase,
    StartedJournalEntry,
)
from chaos_librarian.contract.scenario import (
    AcquireLockEvent,
    ChangePermissionsEvent,
    ReleaseLockEvent,
    RemountPathEvent,
    SimulateQuotaExceededEvent,
    SimulateStaleHandleEvent,
    TimelineActionName,
    ToggleReadonlyEvent,
    UnmountPathEvent,
)
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.engine.context import EngineEventContext
from chaos_librarian.engine.event_handlers.common import (
    _checked_event,
    _location_ids_for_target,
    _new_atomic_entry,
)
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState

# Neutral errno / condition strings recorded in the network-fs-chaos journal
# state_delta. Kept as plain strings here so the engine stays decoupled from the
# materialization-report enum; the wall-clock layer maps them to
# NetworkFsChaosCondition.
_CHAOS_CONDITION_EACCES = "eacces"
_CHAOS_CONDITION_ENOSPC = "enospc"
_CHAOS_CONDITION_ESTALE = "estale"
_CHAOS_CONDITION_EAGAIN = "eagain"
_CHAOS_CONDITION_UNAVAILABLE = "unavailable"


def _chaos_target_ids(state: WorldState, target: str) -> list[str]:
    """Asset-id target ids, or empty for a subtree-path target (no asset id)."""
    return [target] if state.has_location(target) else []


def _chaos_resolved_path(state: WorldState, target: str) -> str:
    """Library-relative path the chaos action acts on.

    For an asset-id target, the current rendered location path; for a
    subtree-path target, the target string itself. The wall-clock runner
    resolves this under ``library/`` to find the real-chmod target.
    """
    if state.has_location(target):
        return state.locations[state.location_id_for_asset(target)].path
    return target


def _chaos_window_temp_path(event_id: str) -> str:
    """Synthetic ``temp_path`` for a network-fs-chaos open (StartedJournalEntry).

    A lock/unmount window stages no file, but ``StartedJournalEntry`` requires a
    ``temp_path`` field; mirror the network-lag handler's synthetic path so the
    journal schema is unchanged.
    """
    return f".chaos-librarian/network-fs-chaos/{event_id}"


def _handle_change_permissions(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, ChangePermissionsEvent)
    return (
        _new_atomic_entry(
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.CHANGE_PERMISSIONS,
            target_ids=_chaos_target_ids(state, event.target),
            location_ids=_location_ids_for_target(state, event.target),
            state_delta={
                "target_ref": event.target,
                "path": _chaos_resolved_path(state, event.target),
                "condition": _CHAOS_CONDITION_EACCES,
                "mode": event.mode,
            },
        ),
    )


def _handle_simulate_quota_exceeded(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, SimulateQuotaExceededEvent)
    return (
        _new_atomic_entry(
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.SIMULATE_QUOTA_EXCEEDED,
            target_ids=_chaos_target_ids(state, event.target),
            location_ids=_location_ids_for_target(state, event.target),
            state_delta={
                "target_ref": event.target,
                "path": _chaos_resolved_path(state, event.target),
                "condition": _CHAOS_CONDITION_ENOSPC,
            },
        ),
    )


def _handle_toggle_readonly(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, ToggleReadonlyEvent)
    return (
        _new_atomic_entry(
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.TOGGLE_READONLY,
            target_ids=_chaos_target_ids(state, event.target),
            location_ids=_location_ids_for_target(state, event.target),
            state_delta={
                "target_ref": event.target,
                "path": _chaos_resolved_path(state, event.target),
                "condition": _CHAOS_CONDITION_EACCES,
                "readonly_state": event.mode.value,
            },
        ),
    )


def _handle_simulate_stale_handle(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, SimulateStaleHandleEvent)
    return (
        _new_atomic_entry(
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.SIMULATE_STALE_HANDLE,
            target_ids=_chaos_target_ids(state, event.target),
            location_ids=_location_ids_for_target(state, event.target),
            state_delta={
                "target_ref": event.target,
                "path": _chaos_resolved_path(state, event.target),
                "condition": _CHAOS_CONDITION_ESTALE,
            },
        ),
    )


def _handle_acquire_lock(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, AcquireLockEvent)
    state_delta: dict[str, object] = {
        "target_ref": event.target,
        "path": _chaos_resolved_path(state, event.target),
        "condition": _CHAOS_CONDITION_EAGAIN,
        "lock_type": event.lock_type.value,
    }
    ctx.pending_locks[event.id] = state_delta
    return (
        StartedJournalEntry(
            schema_version=1,
            event_id=event.id,
            scenario_id=ctx.scenario_id,
            run_id=ctx.run_id,
            logical_time_ns=resolved.at_ns,
            action=TimelineActionName.ACQUIRE_LOCK,
            target_ids=_chaos_target_ids(state, event.target),
            location_ids=_location_ids_for_target(state, event.target),
            state_delta=state_delta,
            phase=JournalPhase.STARTED,
            temp_path=_chaos_window_temp_path(event.id),
        ),
    )


def _handle_release_lock(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, ReleaseLockEvent)
    state_delta = ctx.pending_locks.pop(event.for_)
    target_ref = state_delta.get("target_ref")
    return (
        CommittedJournalEntry(
            schema_version=1,
            event_id=event.id,
            scenario_id=ctx.scenario_id,
            run_id=ctx.run_id,
            logical_time_ns=resolved.at_ns,
            action=TimelineActionName.RELEASE_LOCK,
            target_ids=[target_ref] if isinstance(target_ref, str) else [],
            location_ids=_location_ids_for_target(state, target_ref),
            state_delta=dict(state_delta),
            phase=JournalPhase.COMMITTED,
            related_event_id=event.for_,
        ),
    )


def _handle_unmount_path(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, UnmountPathEvent)
    state_delta: dict[str, object] = {
        "target_ref": event.target,
        "path": _chaos_resolved_path(state, event.target),
        "condition": _CHAOS_CONDITION_UNAVAILABLE,
    }
    ctx.pending_unmounts[event.id] = state_delta
    return (
        StartedJournalEntry(
            schema_version=1,
            event_id=event.id,
            scenario_id=ctx.scenario_id,
            run_id=ctx.run_id,
            logical_time_ns=resolved.at_ns,
            action=TimelineActionName.UNMOUNT_PATH,
            target_ids=_chaos_target_ids(state, event.target),
            location_ids=_location_ids_for_target(state, event.target),
            state_delta=state_delta,
            phase=JournalPhase.STARTED,
            temp_path=_chaos_window_temp_path(event.id),
        ),
    )


def _handle_remount_path(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, RemountPathEvent)
    state_delta = ctx.pending_unmounts.pop(event.for_)
    target_ref = state_delta.get("target_ref")
    return (
        CommittedJournalEntry(
            schema_version=1,
            event_id=event.id,
            scenario_id=ctx.scenario_id,
            run_id=ctx.run_id,
            logical_time_ns=resolved.at_ns,
            action=TimelineActionName.REMOUNT_PATH,
            target_ids=[target_ref] if isinstance(target_ref, str) else [],
            location_ids=_location_ids_for_target(state, target_ref),
            state_delta=dict(state_delta),
            phase=JournalPhase.COMMITTED,
            related_event_id=event.for_,
        ),
    )
