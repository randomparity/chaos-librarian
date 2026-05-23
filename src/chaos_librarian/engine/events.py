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
    AddFileEvent,
    ArchiveFileEvent,
    CorruptContainerHeaderEvent,
    CreateSidecarEvent,
    DeleteFileEvent,
    EditMetadataEvent,
    EmbedSubtitleEvent,
    ExtractSubtitleEvent,
    MoveAssetEvent,
    MoveBetweenRootsEvent,
    NetworkLagCommitEvent,
    NetworkLagStartEvent,
    ReencodeAudioEvent,
    ReencodeVideoEvent,
    RemoveSidecarEvent,
    RemuxContainerEvent,
    RenameFileEvent,
    SidecarKind,
    SlowCopyCommitEvent,
    SlowCopyStartEvent,
    TimelineActionName,
    UpdateSidecarEvent,
)
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.engine.context import EngineEventContext
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState
from chaos_librarian.errors import ChaosLibrarianValueError

_STATE_DELTA_KEYS: Final[dict[TimelineActionName, frozenset[str]]] = {
    TimelineActionName.MOVE_ASSET: frozenset({"from_path", "to_path"}),
    TimelineActionName.RENAME_FILE: frozenset({"from_path", "to_path"}),
    TimelineActionName.DELETE_FILE: frozenset({"removed_path"}),
    TimelineActionName.ADD_FILE: frozenset({"added_path"}),
    TimelineActionName.CREATE_SIDECAR: frozenset(
        {"sidecar_path", "sidecar_id", "language", "kind"}
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

    The destination is ``<to_root.path>/<asset_id>.<container>``. Validation
    has already proven both root ids exist.
    """
    event = _checked_event(resolved, MoveBetweenRootsEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    asset = state.assets[event.target]
    to_root_path = state.root_path_for(event.to_root_id)
    destination = f"{to_root_path}/{event.target}.{asset.container}"
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
    prior_version_id = state.version_id_for_asset(event.target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    corruptor = "container_header_v1"
    seed_material = f"{corruptor}:{ctx.resolved_seed}:{event.id}:{event.target}"
    record = CorruptionRecord(
        profile=ProfileName.MALFORMED_MEDIA,
        event_id=event.id,
        corruptor=corruptor,
        byte_start=0,
        byte_count=event.bytes,
        seed_material=seed_material,
    )
    state.bind_version(
        event.target,
        ManifestVersion(
            id=new_version_id,
            asset_id=event.target,
            index=prior_version.index + 1,
            corruption=record,
        ),
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
    TimelineActionName.NETWORK_LAG_START: _handle_network_lag_start,
    TimelineActionName.NETWORK_LAG_COMMIT: _handle_network_lag_commit,
}
