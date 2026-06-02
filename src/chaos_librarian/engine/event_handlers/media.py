"""Media-version and sidecar event handlers."""

from __future__ import annotations

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import ManifestSidecar, ManifestVersion
from chaos_librarian.contract.scenario import (
    CreateSidecarEvent,
    EditMetadataEvent,
    EmbedSubtitleEvent,
    ExtractSubtitleEvent,
    ReencodeAudioEvent,
    ReencodeVideoEvent,
    RemoveSidecarEvent,
    RemuxContainerEvent,
    SidecarKind,
    TimelineActionName,
    UpdateSidecarEvent,
)
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.engine.context import EngineEventContext
from chaos_librarian.engine.event_handlers.common import _checked_event, _new_atomic_entry
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState


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
        "image_format": event.image_format.value if event.image_format is not None else None,
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
