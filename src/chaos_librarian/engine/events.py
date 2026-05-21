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
from typing import Final

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
from chaos_librarian.contract.scenario import (
    AddFileEvent,
    ArchiveFileEvent,
    CreateSidecarEvent,
    DeleteFileEvent,
    EditMetadataEvent,
    EmbedSubtitleEvent,
    ExtractSubtitleEvent,
    MoveAssetEvent,
    MoveBetweenRootsEvent,
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
        raise ChaosLibrarianValueError(
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


def _handle_reencode_video(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, ReencodeVideoEvent)
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
        run_id=run_id,
        scenario_id=scenario_id,
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
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, ReencodeAudioEvent)
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
        run_id=run_id,
        scenario_id=scenario_id,
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
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Allocate a sidecar row; route on ``event.kind``.

    Subtitle sidecars carry a ``language`` and dedup any declared row
    seeded by ``build_initial_state`` that collides on
    ``(asset_id, language)`` — the timeline ``create_sidecar`` is the
    authoritative writer for that language (#39). Poster and NFO
    sidecars carry no language and never collide; they are inserted
    verbatim. No kind bumps the asset's version.
    """
    event = resolved.event
    assert isinstance(event, CreateSidecarEvent)
    if event.kind == SidecarKind.SUBTITLE:
        # Drop any declared subtitle row seeded by ``build_initial_state``
        # that collides on ``(asset_id, language)``. Validation's
        # projection overwrites declared entries with the timeline value;
        # mirror that here. The phase-A writer also skips the declared
        # file on disk via ``_timeline_sidecar_languages``, so the
        # manifest must not carry a row for the orphaned declared write.
        collisions = [
            sid
            for sid, sidecar in state.sidecars.items()
            if sidecar.asset_id == event.target
            and sidecar.kind == "subtitle"
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
        run_id=run_id,
        scenario_id=scenario_id,
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
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, SlowCopyStartEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    state.locations[loc_id] = previous.model_copy(update={"temp_path": event.temp_path})
    state.pending_slow_copies[event.id] = (loc_id, event.to)
    entry = StartedJournalEntry(
        schema_version=1,
        event_id=event.id,
        scenario_id=scenario_id,
        run_id=run_id,
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
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, SlowCopyCommitEvent)
    loc_id, final_path = state.pending_slow_copies.pop(event.for_)
    previous = state.locations[loc_id]
    state.locations[loc_id] = previous.model_copy(update={"path": final_path, "temp_path": None})
    entry = CommittedJournalEntry(
        schema_version=1,
        event_id=event.id,
        scenario_id=scenario_id,
        run_id=run_id,
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
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Move ``target`` to its archive destination.

    The destination is ``state.archive_path_for(target)``; validation has
    already proven the archive root exists. ``location.path`` updates;
    the asset stays placed.
    """
    event = resolved.event
    assert isinstance(event, ArchiveFileEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    archive_path = state.archive_path_for(event.target)
    state.locations[loc_id] = previous.model_copy(update={"path": archive_path})
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
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
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Move ``target`` from ``from_root_id`` to ``to_root_id``.

    The destination is ``<to_root.path>/<asset_id>.<container>``. Validation
    has already proven both root ids exist.
    """
    event = resolved.event
    assert isinstance(event, MoveBetweenRootsEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    asset = state.assets[event.target]
    to_root_path = state.root_path_for(event.to_root_id)
    destination = f"{to_root_path}/{event.target}.{asset.container}"
    state.locations[loc_id] = previous.model_copy(update={"path": destination})
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
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


def _swap_extension(path: str, new_ext: str) -> str:
    """Replace the path's file extension with ``new_ext`` (no leading dot).

    Pure string surgery: ``"library/movies-hd/x.mkv"`` + ``"mp4"`` →
    ``"library/movies-hd/x.mp4"``. If the path has no extension, appends.
    """
    if "." in path.rsplit("/", 1)[-1]:
        base = path.rsplit(".", 1)[0]
        return f"{base}.{new_ext}"
    return f"{path}.{new_ext}"


def _handle_remux_container(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Allocate a new version; rewrite the asset's location path extension.

    The byte payload doesn't actually change here (the materializer's
    ffmpeg -c copy preserves streams); the version bump signals to
    voom-v2 that the file moved to a new container, which is a
    reconciliation-relevant event.
    """
    event = resolved.event
    assert isinstance(event, RemuxContainerEvent)
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
    prev_container = previous.path.rsplit(".", 1)[-1] if "." in previous.path else ""
    new_path = _swap_extension(previous.path, event.to_container)
    state.locations[loc_id] = previous.model_copy(update={"path": new_path})
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
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
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Allocate a new version; record the fields delta. Path unchanged."""
    event = resolved.event
    assert isinstance(event, EditMetadataEvent)
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
        run_id=run_id,
        scenario_id=scenario_id,
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
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Allocate a new version; remove the named sidecar from state.

    The materializer unlinks the sidecar file in phase B; here we mirror
    that with state.sidecars.pop. Validation guarantees the sidecar
    exists at scenario-construction time (rule_sidecar_target).
    """
    event = resolved.event
    assert isinstance(event, EmbedSubtitleEvent)
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
        run_id=run_id,
        scenario_id=scenario_id,
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
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Allocate a new sidecar row; asset's version is UNCHANGED.

    Asymmetric with embed_subtitle (which DOES bump version) because
    extraction is a read-only operation on the asset bytes.
    """
    event = resolved.event
    assert isinstance(event, ExtractSubtitleEvent)
    sidecar_id = ids.next_sidecar_id()
    state.sidecars[sidecar_id] = ManifestSidecar(
        id=sidecar_id,
        asset_id=event.target,
        kind="subtitle",
        path=event.to,
        language=event.language,
    )
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
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
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Drop the named sidecar from state. No version change."""
    event = resolved.event
    assert isinstance(event, RemoveSidecarEvent)
    sidecar_id = state.sidecar_id_for_path(event.target, event.sidecar_path)
    sidecar = state.sidecars[sidecar_id]
    del state.sidecars[sidecar_id]
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
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
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Emit a journal entry; no state mutation. Phase B regenerates bytes."""
    event = resolved.event
    assert isinstance(event, UpdateSidecarEvent)
    sidecar_id = state.sidecar_id_for_path(event.target, event.sidecar_path)
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.UPDATE_SIDECAR,
        target_ids=[event.target],
        location_ids=[state.location_id_for_asset(event.target)],
        state_delta={
            "sidecar_id": sidecar_id,
            "sidecar_path": event.sidecar_path,
        },
    )
    return (entry,)


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
}
