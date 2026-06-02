"""Filesystem and root-placement event handlers."""

from __future__ import annotations

from chaos_librarian.contract.journal import (
    CommittedJournalEntry,
    JournalEntry,
    JournalPhase,
    StartedJournalEntry,
)
from chaos_librarian.contract.manifest import ManifestLocation
from chaos_librarian.contract.scenario import (
    AddFileEvent,
    ArchiveFileEvent,
    DeleteFileEvent,
    MoveAssetEvent,
    MoveBetweenRootsEvent,
    RenameFileEvent,
    SlowCopyCommitEvent,
    SlowCopyStartEvent,
    TimelineActionName,
)
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.engine.context import EngineEventContext
from chaos_librarian.engine.event_handlers.common import _checked_event, _new_atomic_entry
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState
from chaos_librarian.errors import ChaosLibrarianValueError
from chaos_librarian.path_rendering import replace_root_prefix


def _handle_move_asset(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = _checked_event(resolved, MoveAssetEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    state.locations[loc_id] = previous.model_copy(update={"path": event.to})
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
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
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = _checked_event(resolved, RenameFileEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    state.locations[loc_id] = previous.model_copy(update={"path": event.to})
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
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
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = _checked_event(resolved, DeleteFileEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    state.unbind_location(event.target)
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
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
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = _checked_event(resolved, AddFileEvent)
    # The Sprint 3 lifecycle rule (_rule_timeline_lifecycle) pre-empts this
    # case for CLI-driven runs, but the explicit check stays as defense in
    # depth for library-level callers that bypass validation.
    if state.has_location(event.target):
        raise ChaosLibrarianValueError(
            f"add_file: asset {event.target!r} already has a location; "
            f"use move_asset or rename_file to relocate"
        )
    location_id = ids.next_location_id()
    location = ManifestLocation(id=location_id, asset_id=event.target, path=event.to)
    state.bind_location(event.target, location)
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
        action=TimelineActionName.ADD_FILE,
        target_ids=[event.target],
        location_ids=[location_id],
        state_delta={"added_path": event.to},
    )
    return (entry,)


def _handle_slow_copy_start(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = _checked_event(resolved, SlowCopyStartEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    state.locations[loc_id] = previous.model_copy(update={"temp_path": event.temp_path})
    ctx.pending_slow_copies[event.id] = (loc_id, event.to)
    entry = StartedJournalEntry(
        schema_version=1,
        event_id=event.id,
        scenario_id=ctx.scenario_id,
        run_id=ctx.run_id,
        logical_time_ns=resolved.at_ns,
        action=TimelineActionName.SLOW_COPY_START,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={
            "final_path": event.to,
            "temp_path": event.temp_path,
            "initial_path_at_start": previous.path,
        },
        phase=JournalPhase.STARTED,
        temp_path=event.temp_path,
    )
    return (entry,)


def _handle_slow_copy_commit(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = _checked_event(resolved, SlowCopyCommitEvent)
    loc_id, final_path = ctx.pending_slow_copies.pop(event.for_)
    previous = state.locations[loc_id]
    state.locations[loc_id] = previous.model_copy(update={"path": final_path, "temp_path": None})
    entry = CommittedJournalEntry(
        schema_version=1,
        event_id=event.id,
        scenario_id=ctx.scenario_id,
        run_id=ctx.run_id,
        logical_time_ns=resolved.at_ns,
        action=TimelineActionName.SLOW_COPY_COMMIT,
        target_ids=[previous.asset_id],
        location_ids=[loc_id],
        state_delta={"final_path": final_path},
        phase=JournalPhase.COMMITTED,
        related_event_id=event.for_,
    )
    return (entry,)


def _handle_archive_file(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    """Move ``target`` to its archive destination.

    The destination is ``state.archive_path_for(target)``; validation has
    already proven the archive root exists. ``location.path`` updates;
    the asset stays placed.
    """
    event = _checked_event(resolved, ArchiveFileEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    archive_path = state.archive_path_for(event.target)
    state.locations[loc_id] = previous.model_copy(update={"path": archive_path})
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
        action=TimelineActionName.ARCHIVE_FILE,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={"from_path": previous.path, "to_path": archive_path},
    )
    return (entry,)


def _handle_move_between_roots(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    """Move ``target`` from ``from_root_id`` to ``to_root_id``.

    The destination preserves the current rendered path suffix and replaces
    only the declared library root prefix. Validation has already proven
    both root ids exist.
    """
    event = _checked_event(resolved, MoveBetweenRootsEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    from_root_path = state.root_path_for(event.from_root_id)
    to_root_path = state.root_path_for(event.to_root_id)
    destination = replace_root_prefix(previous.path, from_root=from_root_path, to_root=to_root_path)
    state.locations[loc_id] = previous.model_copy(update={"path": destination})
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
        action=TimelineActionName.MOVE_BETWEEN_ROOTS,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={
            "from_path": previous.path,
            "to_path": destination,
            "from_root_id": event.from_root_id,
            "to_root_id": event.to_root_id,
        },
    )
    return (entry,)
