"""Hierarchy and podcast metadata event handlers."""

from __future__ import annotations

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalEntry
from chaos_librarian.contract.manifest import ManifestSidecar
from chaos_librarian.contract.scenario import (
    MarkEpisodeStaleEvent,
    MoveEpisodeToSeasonEvent,
    MoveTrackToDiscEvent,
    RenameSeasonEvent,
    RenumberDiscEvent,
    RenumberEpisodeEvent,
    RepublishEpisodeEvent,
    SwapDiscNumbersEvent,
    SwapEpisodeNumbersEvent,
    SwapTrackNumbersEvent,
    TimelineActionName,
)
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.engine.context import EngineEventContext
from chaos_librarian.engine.event_handlers.common import _checked_event, _new_atomic_entry
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState
from chaos_librarian.errors import ChaosLibrarianValueError
from chaos_librarian.path_rendering import render_declared_sidecar_path


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


def _handle_republish_episode(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, RepublishEpisodeEvent)
    asset_ids = state.asset_ids_for_podcast_episode(event.target)
    previous = state.podcast_episodes[event.target]
    before = _capture_rendered_paths(state, asset_ids)
    updates: dict[str, object] = {"published_at": event.published_at, "stale": False}
    if event.slug is not None:
        updates["slug"] = event.slug
    state.podcast_episodes[event.target] = previous.model_copy(update=updates)
    metadata = _metadata_delta(previous, state.podcast_episodes[event.target], tuple(updates))
    return (
        _hierarchy_entry(
            state=state,
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.REPUBLISH_EPISODE,
            hierarchy_target_id=event.target,
            asset_ids=asset_ids,
            before_paths=before,
            metadata=metadata,
        ),
    )


def _handle_mark_episode_stale(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    """Flip the episode's recorded stale fact; the file lingers unchanged.

    Records a neutral ``state_delta`` (stale + current paths) — no policy. The
    lifecycle rule has already proven the episode still has a live location.
    """
    del ids
    event = _checked_event(resolved, MarkEpisodeStaleEvent)
    asset_ids = state.asset_ids_for_podcast_episode(event.target)
    previous = state.podcast_episodes[event.target]
    state.podcast_episodes[event.target] = previous.model_copy(update={"stale": True})
    location_ids = [state.location_id_for_asset(asset_id) for asset_id in asset_ids]
    paths = [state.locations[location_id].path for location_id in location_ids]
    entry = _new_atomic_entry(
        resolved=resolved,
        ctx=ctx,
        action=TimelineActionName.MARK_EPISODE_STALE,
        target_ids=[event.target, *asset_ids],
        location_ids=location_ids,
        state_delta={"stale": True, "paths": paths},
    )
    return (entry,)


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
