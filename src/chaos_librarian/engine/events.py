"""Event handlers — one function per ``TimelineActionName`` variant.

``apply_event`` is the single entry point. Each handler:

- mutates the in-memory ``WorldState`` in place
- returns one or more ``JournalEntry`` records describing the change
- never touches the filesystem (plan-only)

Per-action helpers are kept short (<30 lines) so adding a new variant in a
later sprint is a localized change.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from chaos_librarian.contract.journal import (
    AtomicJournalEntry,
    JournalEntry,
    JournalPhase,
)
from chaos_librarian.contract.manifest import ManifestLocation
from chaos_librarian.contract.scenario import (
    AddFileEvent,
    DeleteFileEvent,
    MoveAssetEvent,
    RenameFileEvent,
    TimelineActionName,
)
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState


def apply_event(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Dispatch one resolved event to its handler and return its journal entries."""
    handler = _HANDLERS[resolved.event.action]
    return handler(state, resolved, ids, run_id, scenario_id)


_Handler = Callable[
    [WorldState, ResolvedEvent, IdAllocator, uuid.UUID, str],
    tuple[JournalEntry, ...],
]


def _new_atomic_entry(
    *,
    resolved: ResolvedEvent,
    run_id: uuid.UUID,
    scenario_id: str,
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
        scenario_id=scenario_id,
        run_id=run_id,
        logical_time_ns=resolved.at_ns,
        action=action,
        target_ids=target_ids,
        input_version_ids=input_version_ids or [],
        output_version_ids=output_version_ids or [],
        location_ids=location_ids,
        state_delta=state_delta,
        phase=JournalPhase.ATOMIC,
    )


def _handle_move_asset(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, MoveAssetEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    state.locations[loc_id] = previous.model_copy(update={"path": event.to})
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.MOVE_ASSET,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={"from_path": previous.path, "to_path": event.to},
    )
    return (entry,)


def _handle_rename_file(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, RenameFileEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    state.locations[loc_id] = previous.model_copy(update={"path": event.to})
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.RENAME_FILE,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={"from_path": previous.path, "to_path": event.to},
    )
    return (entry,)


def _handle_delete_file(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, DeleteFileEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    state.unbind_location(event.target)
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.DELETE_FILE,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={"removed_path": previous.path},
    )
    return (entry,)


def _handle_add_file(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, AddFileEvent)
    # The Sprint 3 lifecycle rule (_rule_timeline_lifecycle) pre-empts this
    # case for CLI-driven runs, but the assertion stays as defense in depth
    # for library-level callers that bypass validation.
    if state.has_location(event.target):
        raise ValueError(
            f"add_file: asset {event.target!r} already has a location; "
            f"use move_asset or rename_file to relocate"
        )
    location_id = ids.next_location_id()
    location = ManifestLocation(id=location_id, asset_id=event.target, path=event.to)
    state.bind_location(event.target, location)
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.ADD_FILE,
        target_ids=[event.target],
        location_ids=[location_id],
        state_delta={"added_path": event.to},
    )
    return (entry,)


# Tasks 6 and 7 add the remaining five action variants to this table.
_HANDLERS: dict[TimelineActionName, _Handler] = {
    TimelineActionName.MOVE_ASSET: _handle_move_asset,
    TimelineActionName.RENAME_FILE: _handle_rename_file,
    TimelineActionName.DELETE_FILE: _handle_delete_file,
    TimelineActionName.ADD_FILE: _handle_add_file,
}
