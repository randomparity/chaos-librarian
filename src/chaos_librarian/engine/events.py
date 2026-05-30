"""Event handlers — one function per ``TimelineActionName`` variant.

``apply_event`` is the single entry point. Each handler:

- mutates the in-memory ``WorldState`` in place
- returns one or more ``JournalEntry`` records describing the change
- never touches the filesystem (plan-only)

Per-action helpers are kept short (<30 lines) so adding a new variant in a
later sprint is a localized change.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from chaos_librarian.clock import parse_duration
from chaos_librarian.contract.journal import (
    AtomicJournalEntry,
    CommittedJournalEntry,
    JournalEntry,
    JournalPhase,
    StartedJournalEntry,
)
from chaos_librarian.contract.manifest import (
    ManifestLocation,
    ManifestSidecar,
    ManifestVersion,
)
from chaos_librarian.contract.profiles import CorruptionRecord, ProfileName
from chaos_librarian.contract.scenario import (
    AcquireLockEvent,
    AddFileEvent,
    ArchiveFileEvent,
    ChangePermissionsEvent,
    CorruptContainerHeaderEvent,
    CorruptPacketRangeEvent,
    CreateSidecarEvent,
    DeleteFileEvent,
    EditMetadataEvent,
    EmbedSubtitleEvent,
    ExtractSubtitleEvent,
    MoveAssetEvent,
    MoveBetweenRootsEvent,
    MoveEpisodeToSeasonEvent,
    MoveTrackToDiscEvent,
    NetworkLagCommitEvent,
    NetworkLagStartEvent,
    ReencodeAudioEvent,
    ReencodeVideoEvent,
    ReleaseLockEvent,
    RemountPathEvent,
    RemoveSidecarEvent,
    RemuxContainerEvent,
    RenameFileEvent,
    RenameSeasonEvent,
    RenumberDiscEvent,
    RenumberEpisodeEvent,
    SidecarKind,
    SimulateQuotaExceededEvent,
    SimulateStaleHandleEvent,
    SlowCopyCommitEvent,
    SlowCopyStartEvent,
    SwapDiscNumbersEvent,
    SwapEpisodeNumbersEvent,
    SwapTrackNumbersEvent,
    TimelineActionName,
    ToggleReadonlyEvent,
    TouchMtimeEvent,
    TruncateFileEvent,
    UnmountPathEvent,
    UpdateSidecarEvent,
    WriteInvalidDurationMetadataEvent,
    WrongOracleHashEvent,
)
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.engine.context import EngineEventContext
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState
from chaos_librarian.errors import ChaosLibrarianValueError
from chaos_librarian.path_rendering import render_declared_sidecar_path, replace_root_prefix

_STATE_DELTA_KEYS: Final[dict[TimelineActionName, frozenset[str]]] = {
    TimelineActionName.MOVE_ASSET: frozenset({"from_path", "to_path"}),
    TimelineActionName.RENAME_FILE: frozenset({"from_path", "to_path"}),
    TimelineActionName.DELETE_FILE: frozenset({"removed_path"}),
    TimelineActionName.ADD_FILE: frozenset({"added_path"}),
    TimelineActionName.CREATE_SIDECAR: frozenset(
        {
            "sidecar_path",
            "sidecar_id",
            "language",
            "kind",
            "codec",
            "source",
            "encoding",
            "body",
            "media_type",
        }
    ),
    TimelineActionName.SLOW_COPY_START: frozenset(
        {"final_path", "temp_path", "initial_path_at_start"}
    ),
    TimelineActionName.SLOW_COPY_COMMIT: frozenset({"final_path"}),
    TimelineActionName.ARCHIVE_FILE: frozenset({"from_path", "to_path"}),
    TimelineActionName.MOVE_BETWEEN_ROOTS: frozenset(
        {"from_path", "to_path", "from_root_id", "to_root_id"}
    ),
    TimelineActionName.REENCODE_VIDEO: frozenset(
        {"resolution", "codec", "input_path", "output_path"}
    ),
    TimelineActionName.REENCODE_AUDIO: frozenset(
        {"from_channels", "to_channels", "input_path", "output_path"}
    ),
    TimelineActionName.REMUX_CONTAINER: frozenset(
        {"from_container", "to_container", "from_path", "to_path", "input_path", "output_path"}
    ),
    TimelineActionName.EDIT_METADATA: frozenset({"fields", "input_path", "output_path"}),
    TimelineActionName.EMBED_SUBTITLE: frozenset(
        {
            "embedded_sidecar_id",
            "embedded_sidecar_path",
            "language",
            "kind",
            "input_path",
            "output_path",
        }
    ),
    TimelineActionName.EXTRACT_SUBTITLE: frozenset(
        {"sidecar_id", "sidecar_path", "language", "input_path"}
    ),
    TimelineActionName.REMOVE_SIDECAR: frozenset({"removed_sidecar_id", "removed_sidecar_path"}),
    TimelineActionName.UPDATE_SIDECAR: frozenset({"sidecar_id", "sidecar_path"}),
    TimelineActionName.CORRUPT_CONTAINER_HEADER: frozenset(
        {
            "input_path",
            "output_path",
            "profile",
            "corruptor",
            "byte_start",
            "byte_count",
            "seed_material",
        }
    ),
    TimelineActionName.TRUNCATE_FILE: frozenset(
        {
            "input_path",
            "output_path",
            "profile",
            "corruptor",
            "keep_bytes",
            "seed_material",
        }
    ),
    TimelineActionName.CORRUPT_PACKET_RANGE: frozenset(
        {
            "input_path",
            "output_path",
            "profile",
            "corruptor",
            "stream",
            "packet_start",
            "packet_count",
            "seed_material",
        }
    ),
    TimelineActionName.WRITE_INVALID_DURATION_METADATA: frozenset(
        {
            "input_path",
            "output_path",
            "profile",
            "corruptor",
            "value",
            "seed_material",
        }
    ),
    TimelineActionName.TOUCH_MTIME: frozenset({"path", "profile", "offset"}),
    TimelineActionName.WRONG_ORACLE_HASH: frozenset(
        {
            "input_path",
            "output_path",
            "profile",
            "algorithm",
            "seed_material",
        }
    ),
    TimelineActionName.NETWORK_LAG_START: frozenset(
        {
            "effect",
            "target_ref",
            "after_event_id",
            "logical_start_ns",
            "logical_commit_ns",
            "requested_duration_ns",
            "from_path",
            "to_path",
        }
    ),
    TimelineActionName.NETWORK_LAG_COMMIT: frozenset(
        {
            "effect",
            "target_ref",
            "after_event_id",
            "logical_start_ns",
            "logical_commit_ns",
            "requested_duration_ns",
            "from_path",
            "to_path",
        }
    ),
    TimelineActionName.RENUMBER_EPISODE: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
    TimelineActionName.MOVE_EPISODE_TO_SEASON: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
    TimelineActionName.RENAME_SEASON: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
    TimelineActionName.RENUMBER_DISC: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
    TimelineActionName.MOVE_TRACK_TO_DISC: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
    TimelineActionName.SWAP_EPISODE_NUMBERS: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
    TimelineActionName.SWAP_DISC_NUMBERS: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
    TimelineActionName.SWAP_TRACK_NUMBERS: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
}
"""Per-action contract for emitted ``state_delta`` keys.

Each handler MUST emit at least these keys; extras are allowed for forward
compatibility. ``create_sidecar`` includes ``language`` and
``slow_copy_start`` includes
``initial_path_at_start`` so Phase B and ``derive_path_history`` can drive
purely from the journal.

The parametrized test ``test_state_delta_keys_match_contract`` enforces this
contract by invoking each handler against a minimal scenario.
"""


def apply_event(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    """Dispatch one resolved event to its handler and return its journal entries."""
    handler = _HANDLERS[resolved.event.action]
    entries = handler(state, resolved, ids, ctx)
    for entry in entries:
        state.previous_event_delta = (entry.event_id, dict(entry.state_delta))
    return entries


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


def _seed_material(corruptor: str, ctx: EngineEventContext, event_id: str, target: str) -> str:
    return f"{corruptor}:{ctx.resolved_seed}:{event_id}:{target}"


def _bind_corruption_version(
    state: WorldState,
    ids: IdAllocator,
    *,
    target: str,
    record: CorruptionRecord,
) -> tuple[str, str]:
    prior_version_id = state.version_id_for_asset(target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    state.bind_version(
        target,
        ManifestVersion(
            id=new_version_id,
            asset_id=target,
            index=prior_version.index + 1,
            corruption=record,
        ),
    )
    return prior_version_id, new_version_id


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


def _handle_reencode_video(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = _checked_event(resolved, ReencodeVideoEvent)
    prior_version_id = state.version_id_for_asset(event.target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    state.bind_version(
        event.target,
        ManifestVersion(id=new_version_id, asset_id=event.target, index=prior_version.index + 1),
    )
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
        action=TimelineActionName.REENCODE_VIDEO,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={
            "resolution": event.resolution,
            "codec": event.codec,
            "input_path": previous.path,
            "output_path": previous.path,
        },
        input_version_ids=[prior_version_id],
        output_version_ids=[new_version_id],
    )
    return (entry,)


def _handle_reencode_audio(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = _checked_event(resolved, ReencodeAudioEvent)
    prior_version_id = state.version_id_for_asset(event.target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    state.bind_version(
        event.target,
        ManifestVersion(id=new_version_id, asset_id=event.target, index=prior_version.index + 1),
    )
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
        action=TimelineActionName.REENCODE_AUDIO,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={
            "from_channels": event.from_channels,
            "to_channels": event.to_channels,
            "input_path": previous.path,
            "output_path": previous.path,
        },
        input_version_ids=[prior_version_id],
        output_version_ids=[new_version_id],
    )
    return (entry,)


def _handle_create_sidecar(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    """Allocate a sidecar row; route on ``event.kind``.

    Subtitle sidecars carry a ``language`` and dedup any declared row
    seeded by ``build_initial_state`` that collides on
    ``(asset_id, language)`` — the timeline ``create_sidecar`` is the
    authoritative writer for that language (#39). Poster and NFO
    sidecars carry no language and never collide; they are inserted
    verbatim. No kind bumps the asset's version.
    """
    event = _checked_event(resolved, CreateSidecarEvent)
    if event.kind == SidecarKind.SUBTITLE:
        # Drop any declared subtitle row seeded by ``build_initial_state``
        # that collides on ``(asset_id, language)``. Validation's
        # projection overwrites declared entries with the timeline value;
        # mirror that here. The phase-A writer also skips the declared
        # file on disk via ``timeline_sidecar_languages``, so the
        # manifest must not carry a row for the orphaned declared write.
        collisions = [
            sid
            for sid, sidecar in state.sidecars.items()
            if sidecar.asset_id == event.target
            and sidecar.kind == SidecarKind.SUBTITLE.value
            and sidecar.language == event.language
        ]
        for sid in collisions:
            del state.sidecars[sid]
            state.discard_renderer_sidecar(sid)
    sidecar_id = ids.next_sidecar_id()
    state.sidecars[sidecar_id] = ManifestSidecar(
        id=sidecar_id,
        asset_id=event.target,
        kind=event.kind.value,
        path=event.to,
        language=event.language,
    )
    state_delta: dict[str, object] = {
        "sidecar_path": event.to,
        "sidecar_id": sidecar_id,
        "language": event.language,
        "kind": event.kind.value,
        "codec": event.codec.value if event.codec is not None else None,
        "source": event.source.value if event.source is not None else None,
        "encoding": event.encoding.value if event.encoding is not None else None,
        "body": event.body,
        "media_type": event.media_type.value if event.media_type is not None else None,
    }
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
        action=TimelineActionName.CREATE_SIDECAR,
        target_ids=[event.target],
        location_ids=[state.location_id_for_asset(event.target)],
        state_delta=state_delta,
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
    state.pending_slow_copies[event.id] = (loc_id, event.to)
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
    loc_id, final_path = state.pending_slow_copies.pop(event.for_)
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


def _extract_extension(path: str) -> str:
    """Return the basename extension without a dot, or ``""`` when absent."""
    basename = path.rsplit("/", 1)[-1]
    if "." not in basename:
        return ""
    return basename.rsplit(".", 1)[-1]


def _swap_extension(path: str, new_ext: str) -> str:
    """Replace the path's file extension with ``new_ext`` (no leading dot).

    Pure string surgery: ``"library/movies-hd/x.mkv"`` + ``"mp4"`` →
    ``"library/movies-hd/x.mp4"``. If the path has no extension, appends.
    """
    if _extract_extension(path):
        base = path.rsplit(".", 1)[0]
        return f"{base}.{new_ext}"
    return f"{path}.{new_ext}"


def _handle_remux_container(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    """Allocate a new version; rewrite the asset's location path extension.

    The byte payload doesn't actually change here (the materializer's
    ffmpeg -c copy preserves streams); the version bump signals to
    voom-v2 that the file moved to a new container, which is a
    reconciliation-relevant event.
    """
    event = _checked_event(resolved, RemuxContainerEvent)
    prior_version_id = state.version_id_for_asset(event.target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    state.bind_version(
        event.target,
        ManifestVersion(
            id=new_version_id,
            asset_id=event.target,
            index=prior_version.index + 1,
        ),
    )
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    prev_container = _extract_extension(previous.path)
    new_path = _swap_extension(previous.path, event.to_container)
    state.locations[loc_id] = previous.model_copy(update={"path": new_path})
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
        action=TimelineActionName.REMUX_CONTAINER,
        target_ids=[event.target],
        location_ids=[loc_id],
        input_version_ids=[prior_version_id],
        output_version_ids=[new_version_id],
        state_delta={
            "from_container": prev_container,
            "to_container": event.to_container,
            "from_path": previous.path,
            "to_path": new_path,
            "input_path": previous.path,
            "output_path": new_path,
        },
    )
    return (entry,)


def _handle_edit_metadata(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    """Allocate a new version; record the fields delta. Path unchanged."""
    event = _checked_event(resolved, EditMetadataEvent)
    prior_version_id = state.version_id_for_asset(event.target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    state.bind_version(
        event.target,
        ManifestVersion(
            id=new_version_id,
            asset_id=event.target,
            index=prior_version.index + 1,
        ),
    )
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
        action=TimelineActionName.EDIT_METADATA,
        target_ids=[event.target],
        location_ids=[loc_id],
        input_version_ids=[prior_version_id],
        output_version_ids=[new_version_id],
        state_delta={
            "fields": dict(event.fields),
            "input_path": previous.path,
            "output_path": previous.path,
        },
    )
    return (entry,)


def _handle_embed_subtitle(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    """Allocate a new version; remove the named sidecar from state.

    The materializer unlinks the sidecar file in phase B; here we mirror
    that with state.sidecars.pop. Validation guarantees the sidecar
    exists at scenario-construction time (rule_sidecar_target).
    """
    event = _checked_event(resolved, EmbedSubtitleEvent)
    sidecar_id = state.sidecar_id_for_path(event.target, event.sidecar_path)
    sidecar = state.sidecars[sidecar_id]
    prior_version_id = state.version_id_for_asset(event.target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    state.bind_version(
        event.target,
        ManifestVersion(
            id=new_version_id,
            asset_id=event.target,
            index=prior_version.index + 1,
        ),
    )
    del state.sidecars[sidecar_id]
    state.discard_renderer_sidecar(sidecar_id)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
        action=TimelineActionName.EMBED_SUBTITLE,
        target_ids=[event.target],
        location_ids=[loc_id],
        input_version_ids=[prior_version_id],
        output_version_ids=[new_version_id],
        state_delta={
            "embedded_sidecar_id": sidecar_id,
            "embedded_sidecar_path": sidecar.path,
            "language": sidecar.language,
            "kind": sidecar.kind,
            "input_path": previous.path,
            "output_path": previous.path,
        },
    )
    return (entry,)


def _handle_extract_subtitle(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    """Allocate a new sidecar row; asset's version is UNCHANGED.

    Asymmetric with embed_subtitle (which DOES bump version) because
    extraction is a read-only operation on the asset bytes.
    """
    event = _checked_event(resolved, ExtractSubtitleEvent)
    sidecar_id = ids.next_sidecar_id()
    state.sidecars[sidecar_id] = ManifestSidecar(
        id=sidecar_id,
        asset_id=event.target,
        kind=SidecarKind.SUBTITLE.value,
        path=event.to,
        language=event.language,
    )
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
        action=TimelineActionName.EXTRACT_SUBTITLE,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={
            "sidecar_id": sidecar_id,
            "sidecar_path": event.to,
            "language": event.language,
            "input_path": previous.path,
        },
    )
    return (entry,)


def _handle_remove_sidecar(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    """Drop the named sidecar from state. No version change."""
    event = _checked_event(resolved, RemoveSidecarEvent)
    sidecar_id = state.sidecar_id_for_path(event.target, event.sidecar_path)
    sidecar = state.sidecars[sidecar_id]
    del state.sidecars[sidecar_id]
    state.discard_renderer_sidecar(sidecar_id)
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
        action=TimelineActionName.REMOVE_SIDECAR,
        target_ids=[event.target],
        location_ids=[state.location_id_for_asset(event.target)],
        state_delta={
            "removed_sidecar_id": sidecar_id,
            "removed_sidecar_path": sidecar.path,
        },
    )
    return (entry,)


def _handle_update_sidecar(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    """Emit a journal entry; no state mutation. Phase B regenerates bytes."""
    event = _checked_event(resolved, UpdateSidecarEvent)
    sidecar_id = state.sidecar_id_for_path(event.target, event.sidecar_path)
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
        action=TimelineActionName.UPDATE_SIDECAR,
        target_ids=[event.target],
        location_ids=[state.location_id_for_asset(event.target)],
        state_delta={
            "sidecar_id": sidecar_id,
            "sidecar_path": event.sidecar_path,
        },
    )
    return (entry,)


def _handle_corrupt_container_header(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = _checked_event(resolved, CorruptContainerHeaderEvent)
    corruptor = "container_header_v1"
    seed_material = _seed_material(corruptor, ctx, event.id, event.target)
    record = CorruptionRecord(
        profile=ProfileName.MALFORMED_MEDIA,
        event_id=event.id,
        corruptor=corruptor,
        byte_start=0,
        byte_count=event.bytes,
        seed_material=seed_material,
    )
    prior_version_id, new_version_id = _bind_corruption_version(
        state, ids, target=event.target, record=record
    )
    loc_id = state.location_id_for_asset(event.target)
    location = state.locations[loc_id]
    return (
        _new_atomic_entry(
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
            target_ids=[event.target],
            location_ids=[loc_id],
            input_version_ids=[prior_version_id],
            output_version_ids=[new_version_id],
            state_delta={
                "input_path": location.path,
                "output_path": location.path,
                "profile": ProfileName.MALFORMED_MEDIA.value,
                "corruptor": corruptor,
                "byte_start": 0,
                "byte_count": event.bytes,
                "seed_material": seed_material,
            },
        ),
    )


def _handle_truncate_file(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = _checked_event(resolved, TruncateFileEvent)
    corruptor = "truncate_file_v1"
    seed_material = _seed_material(corruptor, ctx, event.id, event.target)
    record = CorruptionRecord(
        profile=ProfileName.MALFORMED_MEDIA,
        event_id=event.id,
        corruptor=corruptor,
        seed_material=seed_material,
        metadata={"keep_bytes": event.keep_bytes},
    )
    prior_version_id, new_version_id = _bind_corruption_version(
        state, ids, target=event.target, record=record
    )
    loc_id = state.location_id_for_asset(event.target)
    location = state.locations[loc_id]
    return (
        _new_atomic_entry(
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.TRUNCATE_FILE,
            target_ids=[event.target],
            location_ids=[loc_id],
            input_version_ids=[prior_version_id],
            output_version_ids=[new_version_id],
            state_delta={
                "input_path": location.path,
                "output_path": location.path,
                "profile": ProfileName.MALFORMED_MEDIA.value,
                "corruptor": corruptor,
                "keep_bytes": event.keep_bytes,
                "seed_material": seed_material,
            },
        ),
    )


def _handle_corrupt_packet_range(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = _checked_event(resolved, CorruptPacketRangeEvent)
    corruptor = "packet_range_v1"
    seed_material = _seed_material(corruptor, ctx, event.id, event.target)
    record = CorruptionRecord(
        profile=ProfileName.MALFORMED_MEDIA,
        event_id=event.id,
        corruptor=corruptor,
        seed_material=seed_material,
        stream=event.stream.value,
        packet_start=event.packet_start,
        packet_count=event.packet_count,
    )
    prior_version_id, new_version_id = _bind_corruption_version(
        state, ids, target=event.target, record=record
    )
    loc_id = state.location_id_for_asset(event.target)
    location = state.locations[loc_id]
    return (
        _new_atomic_entry(
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.CORRUPT_PACKET_RANGE,
            target_ids=[event.target],
            location_ids=[loc_id],
            input_version_ids=[prior_version_id],
            output_version_ids=[new_version_id],
            state_delta={
                "input_path": location.path,
                "output_path": location.path,
                "profile": ProfileName.MALFORMED_MEDIA.value,
                "corruptor": corruptor,
                "stream": event.stream.value,
                "packet_start": event.packet_start,
                "packet_count": event.packet_count,
                "seed_material": seed_material,
            },
        ),
    )


def _handle_write_invalid_duration_metadata(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = _checked_event(resolved, WriteInvalidDurationMetadataEvent)
    corruptor = "invalid_duration_metadata_v1"
    seed_material = _seed_material(corruptor, ctx, event.id, event.target)
    record = CorruptionRecord(
        profile=ProfileName.MALFORMED_MEDIA,
        event_id=event.id,
        corruptor=corruptor,
        seed_material=seed_material,
        metadata={"value": event.value},
    )
    prior_version_id, new_version_id = _bind_corruption_version(
        state, ids, target=event.target, record=record
    )
    loc_id = state.location_id_for_asset(event.target)
    location = state.locations[loc_id]
    return (
        _new_atomic_entry(
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.WRITE_INVALID_DURATION_METADATA,
            target_ids=[event.target],
            location_ids=[loc_id],
            input_version_ids=[prior_version_id],
            output_version_ids=[new_version_id],
            state_delta={
                "input_path": location.path,
                "output_path": location.path,
                "profile": ProfileName.MALFORMED_MEDIA.value,
                "corruptor": corruptor,
                "value": event.value,
                "seed_material": seed_material,
            },
        ),
    )


def _handle_touch_mtime(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, TouchMtimeEvent)
    loc_id = state.location_id_for_asset(event.target)
    location = state.locations[loc_id]
    return (
        _new_atomic_entry(
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.TOUCH_MTIME,
            target_ids=[event.target],
            location_ids=[loc_id],
            state_delta={
                "path": location.path,
                "profile": ProfileName.FILESYSTEM_ARTIFACTS.value,
                "offset": event.offset,
            },
        ),
    )


def _handle_wrong_oracle_hash(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = _checked_event(resolved, WrongOracleHashEvent)
    prior_version_id = state.version_id_for_asset(event.target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    state.bind_version(
        event.target,
        ManifestVersion(
            id=new_version_id,
            asset_id=event.target,
            index=prior_version.index + 1,
        ),
    )
    loc_id = state.location_id_for_asset(event.target)
    location = state.locations[loc_id]
    return (
        _new_atomic_entry(
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.WRONG_ORACLE_HASH,
            target_ids=[event.target],
            location_ids=[loc_id],
            input_version_ids=[prior_version_id],
            output_version_ids=[new_version_id],
            state_delta={
                "input_path": location.path,
                "output_path": location.path,
                "profile": ProfileName.NEGATIVE_ORACLE.value,
                "algorithm": "sha256",
                "seed_material": _seed_material(
                    "wrong_oracle_hash_v1", ctx, event.id, event.target
                ),
            },
        ),
    )


def _handle_network_lag_start(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, NetworkLagStartEvent)
    if state.previous_event_delta is None or state.previous_event_delta[0] != event.after:
        raise ChaosLibrarianValueError(
            f"network_lag_start must immediately follow after event {event.after!r}"
        )
    source_delta = state.previous_event_delta[1]
    duration_ns = parse_duration(event.duration)
    state_delta = _network_lag_delta(
        event=event,
        source_delta=source_delta,
        logical_start_ns=resolved.at_ns,
        requested_duration_ns=duration_ns,
    )
    state.pending_network_lags[event.id] = state_delta
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
    state_delta = state.pending_network_lags.pop(event.for_)
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


def _location_ids_for_target(state: WorldState, target: object) -> list[str]:
    if not isinstance(target, str) or not state.has_location(target):
        return []
    return [state.location_id_for_asset(target)]


def _network_lag_temp_path(event_id: str) -> str:
    return f".chaos-librarian/network-lag/{event_id}"


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
    state.pending_locks[event.id] = state_delta
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
    state_delta = state.pending_locks.pop(event.for_)
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
    state.pending_unmounts[event.id] = state_delta
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
    state_delta = state.pending_unmounts.pop(event.for_)
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


def _handle_renumber_episode(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, RenumberEpisodeEvent)
    asset_ids = state.asset_ids_for_episode(event.target)
    previous = state.episodes[event.target]
    before = _capture_rendered_paths(state, asset_ids)
    updates: dict[str, object] = {"episode_number": event.episode_number}
    if event.absolute_number is not None:
        updates["absolute_number"] = event.absolute_number
    state.episodes[event.target] = previous.model_copy(update=updates)
    metadata = _metadata_delta(previous, state.episodes[event.target], tuple(updates))
    return (
        _hierarchy_entry(
            state=state,
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.RENUMBER_EPISODE,
            hierarchy_target_id=event.target,
            asset_ids=asset_ids,
            before_paths=before,
            metadata=metadata,
        ),
    )


def _handle_move_episode_to_season(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, MoveEpisodeToSeasonEvent)
    asset_ids = state.asset_ids_for_episode(event.target)
    previous = state.episodes[event.target]
    before = _capture_rendered_paths(state, asset_ids)
    updates: dict[str, object] = {
        "season_id": event.to_season,
        "episode_number": event.episode_number,
    }
    if event.absolute_number is not None:
        updates["absolute_number"] = event.absolute_number
    state.episodes[event.target] = previous.model_copy(update=updates)
    metadata = _metadata_delta(previous, state.episodes[event.target], tuple(updates))
    return (
        _hierarchy_entry(
            state=state,
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.MOVE_EPISODE_TO_SEASON,
            hierarchy_target_id=event.target,
            asset_ids=asset_ids,
            before_paths=before,
            metadata=metadata,
        ),
    )


def _handle_rename_season(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, RenameSeasonEvent)
    asset_ids = state.asset_ids_for_season(event.target)
    previous = state.seasons[event.target]
    before = _capture_rendered_paths(state, asset_ids)
    state.seasons[event.target] = previous.model_copy(update={"title": event.title})
    metadata = _metadata_delta(previous, state.seasons[event.target], ("title",))
    return (
        _hierarchy_entry(
            state=state,
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.RENAME_SEASON,
            hierarchy_target_id=event.target,
            asset_ids=asset_ids,
            before_paths=before,
            metadata=metadata,
        ),
    )


def _handle_renumber_disc(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, RenumberDiscEvent)
    asset_ids = state.asset_ids_for_disc(event.target)
    previous = state.discs[event.target]
    before = _capture_rendered_paths(state, asset_ids)
    state.discs[event.target] = previous.model_copy(update={"disc_number": event.disc_number})
    metadata = _metadata_delta(previous, state.discs[event.target], ("disc_number",))
    return (
        _hierarchy_entry(
            state=state,
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.RENUMBER_DISC,
            hierarchy_target_id=event.target,
            asset_ids=asset_ids,
            before_paths=before,
            metadata=metadata,
        ),
    )


def _handle_move_track_to_disc(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, MoveTrackToDiscEvent)
    asset_ids = state.asset_ids_for_track(event.target)
    previous = state.tracks[event.target]
    before = _capture_rendered_paths(state, asset_ids)
    state.tracks[event.target] = previous.model_copy(
        update={"disc_id": event.to_disc, "track_number": event.track_number}
    )
    metadata = _metadata_delta(previous, state.tracks[event.target], ("disc_id", "track_number"))
    return (
        _hierarchy_entry(
            state=state,
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.MOVE_TRACK_TO_DISC,
            hierarchy_target_id=event.target,
            asset_ids=asset_ids,
            before_paths=before,
            metadata=metadata,
        ),
    )


def _handle_swap_episode_numbers(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, SwapEpisodeNumbersEvent)
    asset_ids = state.asset_ids_for_episode(event.target) + state.asset_ids_for_episode(
        event.with_episode
    )
    before = _capture_rendered_paths(state, asset_ids)
    a = state.episodes[event.target]
    b = state.episodes[event.with_episode]
    state.episodes[event.target] = a.model_copy(update={"episode_number": b.episode_number})
    state.episodes[event.with_episode] = b.model_copy(update={"episode_number": a.episode_number})
    metadata = _swap_metadata("episode_number", a.episode_number, b.episode_number)
    return (
        _hierarchy_entry(
            state=state,
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.SWAP_EPISODE_NUMBERS,
            hierarchy_target_id=event.target,
            extra_hierarchy_target_ids=(event.with_episode,),
            asset_ids=asset_ids,
            before_paths=before,
            metadata=metadata,
        ),
    )


def _handle_swap_disc_numbers(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, SwapDiscNumbersEvent)
    asset_ids = state.asset_ids_for_disc(event.target) + state.asset_ids_for_disc(event.with_disc)
    before = _capture_rendered_paths(state, asset_ids)
    a = state.discs[event.target]
    b = state.discs[event.with_disc]
    state.discs[event.target] = a.model_copy(update={"disc_number": b.disc_number})
    state.discs[event.with_disc] = b.model_copy(update={"disc_number": a.disc_number})
    metadata = _swap_metadata("disc_number", a.disc_number, b.disc_number)
    return (
        _hierarchy_entry(
            state=state,
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.SWAP_DISC_NUMBERS,
            hierarchy_target_id=event.target,
            extra_hierarchy_target_ids=(event.with_disc,),
            asset_ids=asset_ids,
            before_paths=before,
            metadata=metadata,
        ),
    )


def _handle_swap_track_numbers(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, SwapTrackNumbersEvent)
    asset_ids = state.asset_ids_for_track(event.target) + state.asset_ids_for_track(
        event.with_track
    )
    before = _capture_rendered_paths(state, asset_ids)
    a = state.tracks[event.target]
    b = state.tracks[event.with_track]
    state.tracks[event.target] = a.model_copy(update={"track_number": b.track_number})
    state.tracks[event.with_track] = b.model_copy(update={"track_number": a.track_number})
    metadata = _swap_metadata("track_number", a.track_number, b.track_number)
    return (
        _hierarchy_entry(
            state=state,
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.SWAP_TRACK_NUMBERS,
            hierarchy_target_id=event.target,
            extra_hierarchy_target_ids=(event.with_track,),
            asset_ids=asset_ids,
            before_paths=before,
            metadata=metadata,
        ),
    )


def _swap_metadata(field: str, a_value: int, b_value: int) -> dict[str, dict[str, object]]:
    """Per-entity before/after for the swapped number field, keyed by operand role."""
    return {
        "target": {field: {"before": a_value, "after": b_value}},
        "with": {field: {"before": b_value, "after": a_value}},
    }


def _capture_rendered_paths(
    state: WorldState,
    asset_ids: list[str],
) -> dict[str, tuple[str, str]]:
    paths: dict[str, tuple[str, str]] = {}
    for asset_id in asset_ids:
        if not state.has_location(asset_id) or not state.renderer_manages_asset(asset_id):
            continue
        location_id = state.location_id_for_asset(asset_id)
        paths[asset_id] = (location_id, state.locations[location_id].path)
    return paths


def _metadata_delta(
    before: object,
    after: object,
    fields: tuple[str, ...],
) -> dict[str, dict[str, object]]:
    return {
        field: {"before": getattr(before, field), "after": getattr(after, field)}
        for field in fields
        if getattr(before, field) != getattr(after, field)
    }


def _hierarchy_entry(
    *,
    state: WorldState,
    resolved: ResolvedEvent,
    ctx: EngineEventContext,
    action: TimelineActionName,
    hierarchy_target_id: str,
    asset_ids: list[str],
    before_paths: dict[str, tuple[str, str]],
    metadata: dict[str, dict[str, object]],
    extra_hierarchy_target_ids: tuple[str, ...] = (),
) -> AtomicJournalEntry:
    path_moves: list[dict[str, str]] = []
    sidecar_moves: list[dict[str, str]] = []
    skipped_deleted_asset_ids: list[str] = []
    sidecars_by_asset = state.renderer_derived_sidecars_by_asset(asset_ids)
    for asset_id in asset_ids:
        if not state.has_location(asset_id):
            skipped_deleted_asset_ids.append(asset_id)
            continue
        before = before_paths.get(asset_id)
        if before is None:
            continue
        location_id, from_path = before
        to_path = state.render_path_for_asset(asset_id)
        if from_path == to_path:
            continue
        state.locations[location_id] = state.locations[location_id].model_copy(
            update={"path": to_path}
        )
        path_moves.append(
            {
                "asset_id": asset_id,
                "location_id": location_id,
                "from_path": from_path,
                "to_path": to_path,
            }
        )
        for sidecar in sidecars_by_asset.get(asset_id, []):
            if sidecar.language is None:
                raise ChaosLibrarianValueError(
                    f"renderer-derived sidecar {sidecar.id!r} has no language"
                )
            sidecar_to_path = render_declared_sidecar_path(
                to_path,
                sidecar.language,
                codec=_sidecar_codec_from_path(sidecar),
            )
            if sidecar.path == sidecar_to_path:
                continue
            state.sidecars[sidecar.id] = sidecar.model_copy(update={"path": sidecar_to_path})
            sidecar_moves.append(
                {
                    "sidecar_id": sidecar.id,
                    "asset_id": asset_id,
                    "from_path": sidecar.path,
                    "to_path": sidecar_to_path,
                }
            )
    return _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
        action=action,
        target_ids=[hierarchy_target_id, *extra_hierarchy_target_ids, *asset_ids],
        location_ids=[move["location_id"] for move in path_moves],
        state_delta={
            "metadata": metadata,
            "path_moves": path_moves,
            "sidecar_moves": sidecar_moves,
            "skipped_deleted_asset_ids": skipped_deleted_asset_ids,
        },
    )


def _sidecar_codec_from_path(sidecar: ManifestSidecar) -> str:
    _prefix, separator, codec = sidecar.path.rpartition(".")
    if separator and codec:
        return codec
    return "srt"


_HANDLERS: dict[TimelineActionName, _Handler] = {
    TimelineActionName.MOVE_ASSET: _handle_move_asset,
    TimelineActionName.RENAME_FILE: _handle_rename_file,
    TimelineActionName.DELETE_FILE: _handle_delete_file,
    TimelineActionName.ADD_FILE: _handle_add_file,
    TimelineActionName.REENCODE_VIDEO: _handle_reencode_video,
    TimelineActionName.REENCODE_AUDIO: _handle_reencode_audio,
    TimelineActionName.CREATE_SIDECAR: _handle_create_sidecar,
    TimelineActionName.SLOW_COPY_START: _handle_slow_copy_start,
    TimelineActionName.SLOW_COPY_COMMIT: _handle_slow_copy_commit,
    TimelineActionName.ARCHIVE_FILE: _handle_archive_file,
    TimelineActionName.MOVE_BETWEEN_ROOTS: _handle_move_between_roots,
    TimelineActionName.REMUX_CONTAINER: _handle_remux_container,
    TimelineActionName.EDIT_METADATA: _handle_edit_metadata,
    TimelineActionName.EMBED_SUBTITLE: _handle_embed_subtitle,
    TimelineActionName.EXTRACT_SUBTITLE: _handle_extract_subtitle,
    TimelineActionName.REMOVE_SIDECAR: _handle_remove_sidecar,
    TimelineActionName.UPDATE_SIDECAR: _handle_update_sidecar,
    TimelineActionName.CORRUPT_CONTAINER_HEADER: _handle_corrupt_container_header,
    TimelineActionName.TRUNCATE_FILE: _handle_truncate_file,
    TimelineActionName.CORRUPT_PACKET_RANGE: _handle_corrupt_packet_range,
    TimelineActionName.WRITE_INVALID_DURATION_METADATA: _handle_write_invalid_duration_metadata,
    TimelineActionName.TOUCH_MTIME: _handle_touch_mtime,
    TimelineActionName.WRONG_ORACLE_HASH: _handle_wrong_oracle_hash,
    TimelineActionName.NETWORK_LAG_START: _handle_network_lag_start,
    TimelineActionName.NETWORK_LAG_COMMIT: _handle_network_lag_commit,
    TimelineActionName.CHANGE_PERMISSIONS: _handle_change_permissions,
    TimelineActionName.SIMULATE_QUOTA_EXCEEDED: _handle_simulate_quota_exceeded,
    TimelineActionName.TOGGLE_READONLY: _handle_toggle_readonly,
    TimelineActionName.SIMULATE_STALE_HANDLE: _handle_simulate_stale_handle,
    TimelineActionName.UNMOUNT_PATH: _handle_unmount_path,
    TimelineActionName.REMOUNT_PATH: _handle_remount_path,
    TimelineActionName.ACQUIRE_LOCK: _handle_acquire_lock,
    TimelineActionName.RELEASE_LOCK: _handle_release_lock,
    TimelineActionName.RENUMBER_EPISODE: _handle_renumber_episode,
    TimelineActionName.MOVE_EPISODE_TO_SEASON: _handle_move_episode_to_season,
    TimelineActionName.RENAME_SEASON: _handle_rename_season,
    TimelineActionName.RENUMBER_DISC: _handle_renumber_disc,
    TimelineActionName.MOVE_TRACK_TO_DISC: _handle_move_track_to_disc,
    TimelineActionName.SWAP_EPISODE_NUMBERS: _handle_swap_episode_numbers,
    TimelineActionName.SWAP_DISC_NUMBERS: _handle_swap_disc_numbers,
    TimelineActionName.SWAP_TRACK_NUMBERS: _handle_swap_track_numbers,
}
