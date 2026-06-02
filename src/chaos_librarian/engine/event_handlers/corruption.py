"""Corruption, filesystem-artifact, and negative-oracle event handlers."""

from __future__ import annotations

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import ManifestVersion
from chaos_librarian.contract.profiles import CorruptionRecord, ProfileName
from chaos_librarian.contract.scenario import (
    CorruptContainerHeaderEvent,
    CorruptPacketRangeEvent,
    CorruptTagsEvent,
    TimelineActionName,
    TouchMtimeEvent,
    TruncateFileEvent,
    WriteInvalidDurationMetadataEvent,
    WrongOracleHashEvent,
)
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.engine.context import EngineEventContext
from chaos_librarian.engine.event_handlers.common import _checked_event, _new_atomic_entry
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState


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


def _handle_corrupt_tags(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    event = _checked_event(resolved, CorruptTagsEvent)
    corruptor = "tag_corruption_v1"
    seed_material = _seed_material(corruptor, ctx, event.id, event.target)
    record = CorruptionRecord(
        profile=ProfileName.MALFORMED_MEDIA,
        event_id=event.id,
        corruptor=corruptor,
        byte_start=0,
        byte_count=event.bytes,
        seed_material=seed_material,
        metadata={"flavor": event.flavor.value},
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
            action=TimelineActionName.CORRUPT_TAGS,
            target_ids=[event.target],
            location_ids=[loc_id],
            input_version_ids=[prior_version_id],
            output_version_ids=[new_version_id],
            state_delta={
                "input_path": location.path,
                "output_path": location.path,
                "profile": ProfileName.MALFORMED_MEDIA.value,
                "corruptor": corruptor,
                "flavor": event.flavor.value,
                "byte_count": event.bytes,
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
