"""Rule 8: E_LIFECYCLE_INVALID — reject timelines that can't execute.

Simulates the asset lifecycle: every declared asset starts "placed" (per
``docs/contract/manifest-initial-state.md``). The simulation rejects
operations that would otherwise crash the engine's per-handler state
lookups (``state._asset_to_location``, etc).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import SidecarKind, TimelineActionName
from chaos_librarian.validation.codes import E_LIFECYCLE_INVALID
from chaos_librarian.validation.rules.core.raw_helpers import (
    Reporter,
    _iter_timeline_events,
    _Loc,
)
from chaos_librarian.validation.rules.hierarchy.projection import (
    HierarchyProjection,
    build_hierarchy_projection,
    is_hierarchy_action,
)
from chaos_librarian.validation.rules.hierarchy.walkers import iter_asset_ids
from chaos_librarian.validation.rules.sidecar.projection import (
    SidecarProjection,
    create_sidecar_projection_row,
    drop_subtitle_rows_for_language,
    extracted_subtitle_projection_row,
    project_sidecars_for_hierarchy_mutation,
    seed_sidecar_projection,
)

if TYPE_CHECKING:
    from chaos_librarian.validation.reporting import IssueCollector
    from chaos_librarian.validation.scenario_io import LineIndex

__all__ = ["rule_timeline_lifecycle"]


_MUTATION_ACTIONS: frozenset[str] = frozenset(
    {
        TimelineActionName.MOVE_ASSET,
        TimelineActionName.RENAME_FILE,
        TimelineActionName.DELETE_FILE,
    }
)
_LOCATION_DEPENDENT_PASSTHROUGH: frozenset[str] = frozenset(
    {
        TimelineActionName.REENCODE_VIDEO,
        TimelineActionName.REENCODE_AUDIO,
        TimelineActionName.CREATE_SIDECAR,
        TimelineActionName.ARCHIVE_FILE,
        TimelineActionName.MOVE_BETWEEN_ROOTS,
        TimelineActionName.REMUX_CONTAINER,
        TimelineActionName.EDIT_METADATA,
        TimelineActionName.EMBED_SUBTITLE,
        TimelineActionName.EXTRACT_SUBTITLE,
        TimelineActionName.REMOVE_SIDECAR,
        TimelineActionName.UPDATE_SIDECAR,
        TimelineActionName.CORRUPT_CONTAINER_HEADER,
        TimelineActionName.TRUNCATE_FILE,
        TimelineActionName.CORRUPT_PACKET_RANGE,
        TimelineActionName.WRITE_INVALID_DURATION_METADATA,
        TimelineActionName.CORRUPT_TAGS,
        TimelineActionName.TOUCH_MTIME,
        TimelineActionName.WRONG_ORACLE_HASH,
    }
)
# Operations that are incompatible with a pending slow_copy: they relocate,
# mutate, or read the asset's bytes, so they must reject while a slow_copy is in
# flight — the same guard the mutation set already applies to
# move/rename/delete. UPDATE_SIDECAR and REMOVE_SIDECAR are intentionally
# excluded — they touch a sidecar file, not the asset.
_SLOW_COPY_INCOMPATIBLE_OPS: frozenset[str] = frozenset(
    {
        TimelineActionName.ARCHIVE_FILE,
        TimelineActionName.MOVE_BETWEEN_ROOTS,
        TimelineActionName.REENCODE_VIDEO,
        TimelineActionName.REENCODE_AUDIO,
        TimelineActionName.REMUX_CONTAINER,
        TimelineActionName.EDIT_METADATA,
        TimelineActionName.EMBED_SUBTITLE,
        TimelineActionName.EXTRACT_SUBTITLE,
        TimelineActionName.CORRUPT_CONTAINER_HEADER,
        TimelineActionName.TRUNCATE_FILE,
        TimelineActionName.CORRUPT_PACKET_RANGE,
        TimelineActionName.WRITE_INVALID_DURATION_METADATA,
        TimelineActionName.CORRUPT_TAGS,
        TimelineActionName.TOUCH_MTIME,
        TimelineActionName.WRONG_ORACLE_HASH,
    }
)
_SIDECAR_ACTIONS: frozenset[str] = frozenset(
    {
        TimelineActionName.CREATE_SIDECAR,
        TimelineActionName.EXTRACT_SUBTITLE,
        TimelineActionName.EMBED_SUBTITLE,
        TimelineActionName.REMOVE_SIDECAR,
        TimelineActionName.UPDATE_SIDECAR,
    }
)


@dataclass
class _LifecycleState:
    """Mutable per-asset state for the lifecycle simulation.

    Tracking it in a dataclass keeps ``rule_timeline_lifecycle`` flat
    (one branch per action variant) and lets each per-action helper
    receive a single state handle instead of three positional dicts.
    """

    placed: set[str]
    pending_slow_copies: dict[str, str]  # start_event_id -> asset_id
    assets_with_pending_copy: set[str]
    sidecars_by_path: SidecarProjection = field(default_factory=dict)
    """(asset_id, path) -> projection row. Seeded from declared subtitles; updated
    by create_sidecar / extract_subtitle (insert) and
    remove_sidecar / embed_subtitle (delete)."""
    stale_episodes: set[str] = field(default_factory=set)
    """Podcast episode ids already flipped stale by mark_episode_stale; a second
    mark on the same episode is a redundant lifecycle transition."""


def rule_timeline_lifecycle(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject timelines that cannot execute against the asset lifecycle.

    Simulates: every declared asset starts "placed" (per the initial-state
    convention in docs/contract/manifest-initial-state.md). Rejects:

    - ``add_file`` on a placed asset
    - any location-dependent mutation (move/rename/delete, reencode_video/
      reencode_audio/create_sidecar) on an unplaced asset — the engine
      reads ``state._asset_to_location`` / ``_asset_to_version`` in each
      handler and would raise ``KeyError`` otherwise
    - overlapping ``slow_copy_start`` on the same asset
    - ``delete_file``, ``move_asset``, or ``rename_file`` on an asset that
      has a pending ``slow_copy_start`` — the engine's commit handler
      would otherwise look up a location id the delete/move/rename has
      already popped or relocated
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    # Bind ``code=E_LIFECYCLE_INVALID`` once — every emission in this rule uses
    # the same code, so threading it through five helpers is pure noise.
    emit: _Emit = partial(reporter.error, code=E_LIFECYCLE_INVALID)
    hierarchy_projection = build_hierarchy_projection(raw)
    hierarchy_pending_slow_copies: dict[str, tuple[str, str]] = {}
    state = _LifecycleState(
        placed=set(iter_asset_ids(raw)),
        pending_slow_copies={},
        assets_with_pending_copy=set(),
        sidecars_by_path=seed_sidecar_projection(raw),
    )

    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        if not isinstance(action, str):
            continue  # Pydantic owns shape on missing/non-string action
        target = event.get("target")
        loc: _Loc = ("timeline", idx, "action")

        if action == TimelineActionName.ADD_FILE and isinstance(target, str):
            _lifecycle_check_add_file(target=target, state=state, emit=emit, loc=loc)
        elif is_hierarchy_action(action):
            _lifecycle_check_hierarchy_action(
                event=event,
                state=state,
                hierarchy_projection=hierarchy_projection,
                emit=emit,
                loc=loc,
            )
        elif action in _MUTATION_ACTIONS and isinstance(target, str):
            _lifecycle_check_mutation(
                action=action,
                target=target,
                state=state,
                emit=emit,
                loc=loc,
            )
        elif action in _SIDECAR_ACTIONS and isinstance(target, str):
            _lifecycle_check_sidecar_action(
                event=event,
                action=action,
                target=target,
                state=state,
                emit=emit,
                loc=loc,
            )
        elif action in _LOCATION_DEPENDENT_PASSTHROUGH and isinstance(target, str):
            _lifecycle_check_passthrough(
                action=action, target=target, state=state, emit=emit, loc=loc
            )
        elif action == TimelineActionName.SLOW_COPY_START and isinstance(target, str):
            _lifecycle_check_slow_copy_start(
                target=target,
                ev_id=event.get("id"),
                state=state,
                emit=emit,
                loc=loc,
            )
        elif action == TimelineActionName.SLOW_COPY_COMMIT:
            _lifecycle_apply_commit(ref=event.get("for"), state=state)
        elif action == TimelineActionName.MARK_EPISODE_STALE and isinstance(target, str):
            _lifecycle_check_mark_episode_stale(
                target=target,
                state=state,
                hierarchy_projection=hierarchy_projection,
                emit=emit,
                loc=loc,
            )

        if not is_hierarchy_action(action):
            hierarchy_projection.project_non_hierarchy_event(
                event,
                hierarchy_pending_slow_copies,
            )


# Pre-bound ``reporter.error(code=E_LIFECYCLE_INVALID, …)`` callable; the
# remaining kwargs (message, loc) are passed at each emission site.
_Emit = Callable[..., None]


def _lifecycle_check_add_file(
    *,
    target: str,
    state: _LifecycleState,
    emit: _Emit,
    loc: _Loc,
) -> None:
    if target in state.placed:
        emit(message=f"add_file on already-placed asset {target!r}", loc=loc)
    state.placed.add(target)


def _lifecycle_check_mark_episode_stale(
    *,
    target: str,
    state: _LifecycleState,
    hierarchy_projection: HierarchyProjection,
    emit: _Emit,
    loc: _Loc,
) -> None:
    """Reject staling an episode with no live location, or a double stale.

    ``mark_episode_stale`` records the episode's current rendered path, so it
    needs at least one placed asset; flipping an already-stale episode is a
    redundant transition. A target that does not resolve to a podcast episode is
    owned by ``rule_target_unknown`` (E_TARGET_UNKNOWN) and skipped here.
    """
    episode = hierarchy_projection.podcast_episodes.get(target)
    if episode is None:
        return
    if target in state.stale_episodes:
        emit(message=f"mark_episode_stale on already-stale episode {target!r}", loc=loc)
    if not any(asset_id in state.placed for asset_id in episode.asset_ids):
        emit(
            message=f"mark_episode_stale on episode {target!r} with no live location",
            loc=loc,
        )
    state.stale_episodes.add(target)


def _lifecycle_check_mutation(
    *,
    action: str,
    target: str,
    state: _LifecycleState,
    emit: _Emit,
    loc: _Loc,
) -> None:
    if target not in state.placed:
        emit(message=f"{action} on unplaced asset {target!r}", loc=loc)
    if target in state.assets_with_pending_copy:
        emit(message=f"{action} on asset {target!r} with a pending slow_copy", loc=loc)
    if action == TimelineActionName.DELETE_FILE:
        state.placed.discard(target)


def _lifecycle_check_passthrough(
    *,
    action: str,
    target: str,
    state: _LifecycleState,
    emit: _Emit,
    loc: _Loc,
) -> None:
    if target not in state.placed:
        emit(message=f"{action} on unplaced asset {target!r}", loc=loc)
    if action in _SLOW_COPY_INCOMPATIBLE_OPS and target in state.assets_with_pending_copy:
        emit(message=f"{action} on asset {target!r} with a pending slow_copy", loc=loc)


def _lifecycle_check_sidecar_action(
    *,
    event: Mapping[str, object],
    action: str,
    target: str,
    state: _LifecycleState,
    emit: _Emit,
    loc: _Loc,
) -> None:
    _lifecycle_check_passthrough(action=action, target=target, state=state, emit=emit, loc=loc)
    if action == TimelineActionName.CREATE_SIDECAR:
        _apply_create_sidecar(event=event, target=target, state=state)
    elif action == TimelineActionName.EXTRACT_SUBTITLE:
        _apply_extract_subtitle(event=event, target=target, state=state)
    elif action == TimelineActionName.EMBED_SUBTITLE:
        _apply_embed_subtitle(event=event, target=target, state=state, emit=emit, loc=loc)
    elif action == TimelineActionName.REMOVE_SIDECAR:
        _apply_remove_sidecar(event=event, target=target, state=state, emit=emit, loc=loc)
    elif action == TimelineActionName.UPDATE_SIDECAR:
        _apply_update_sidecar(event=event, target=target, state=state, emit=emit, loc=loc)


def _lifecycle_check_slow_copy_start(
    *,
    target: str,
    ev_id: object,
    state: _LifecycleState,
    emit: _Emit,
    loc: _Loc,
) -> None:
    if target not in state.placed:
        emit(message=f"slow_copy_start on unplaced asset {target!r}", loc=loc)
    if not isinstance(ev_id, str):
        return  # Pydantic owns shape; nothing to track
    if target in state.assets_with_pending_copy:
        emit(
            message=f"slow_copy_start on asset {target!r} that already has a pending copy",
            loc=loc,
        )
    state.pending_slow_copies[ev_id] = target
    state.assets_with_pending_copy.add(target)


def _lifecycle_apply_commit(*, ref: object, state: _LifecycleState) -> None:
    """Drop the matched start from pending state. Rule 5a owns orphan reporting."""
    if not isinstance(ref, str):
        return
    if ref not in state.pending_slow_copies:
        return
    committed_asset = state.pending_slow_copies.pop(ref)
    state.assets_with_pending_copy.discard(committed_asset)


def _lifecycle_check_hierarchy_action(
    *,
    event: Mapping[str, object],
    state: _LifecycleState,
    hierarchy_projection: HierarchyProjection,
    emit: _Emit,
    loc: _Loc,
) -> None:
    action = event.get("action")
    affected_asset_ids = hierarchy_projection.affected_asset_ids(event)
    for asset_id in affected_asset_ids:
        if asset_id in state.assets_with_pending_copy:
            emit(message=f"{action} on asset {asset_id!r} with a pending slow_copy", loc=loc)
    mutation = hierarchy_projection.apply(event)
    project_sidecars_for_hierarchy_mutation(mutation, state.sidecars_by_path)


def _apply_create_sidecar(
    *,
    event: Mapping[str, object],
    target: str,
    state: _LifecycleState,
) -> None:
    """Insert (target, to) -> kind into the sidecar projection."""
    to = event.get("to")
    if not isinstance(to, str):
        return
    row = create_sidecar_projection_row(event)
    if row is None:
        return
    if row.kind is SidecarKind.SUBTITLE and row.language is not None:
        drop_subtitle_rows_for_language(
            state.sidecars_by_path, target=target, language=row.language
        )
    state.sidecars_by_path[(target, to)] = row


def _apply_extract_subtitle(
    *,
    event: Mapping[str, object],
    target: str,
    state: _LifecycleState,
) -> None:
    """Insert (target, to) -> subtitle into the sidecar projection."""
    to = event.get("to")
    if isinstance(to, str):
        state.sidecars_by_path[(target, to)] = extracted_subtitle_projection_row(event)


def _apply_embed_subtitle(
    *,
    event: Mapping[str, object],
    target: str,
    state: _LifecycleState,
    emit: _Emit,
    loc: _Loc,
) -> None:
    """Emit E_LIFECYCLE_INVALID if sidecar is missing; else consume it."""
    sidecar_path = event.get("sidecar_path")
    if not isinstance(sidecar_path, str):
        return
    if (target, sidecar_path) not in state.sidecars_by_path:
        emit(
            message=(f"embed_subtitle on missing sidecar {sidecar_path!r} (asset {target!r})"),
            loc=loc,
        )
    else:
        del state.sidecars_by_path[(target, sidecar_path)]


def _apply_remove_sidecar(
    *,
    event: Mapping[str, object],
    target: str,
    state: _LifecycleState,
    emit: _Emit,
    loc: _Loc,
) -> None:
    """Emit E_LIFECYCLE_INVALID if sidecar is missing; else delete it."""
    sidecar_path = event.get("sidecar_path")
    if not isinstance(sidecar_path, str):
        return
    if (target, sidecar_path) not in state.sidecars_by_path:
        emit(
            message=(f"remove_sidecar on missing sidecar {sidecar_path!r} (asset {target!r})"),
            loc=loc,
        )
    else:
        del state.sidecars_by_path[(target, sidecar_path)]


def _apply_update_sidecar(
    *,
    event: Mapping[str, object],
    target: str,
    state: _LifecycleState,
    emit: _Emit,
    loc: _Loc,
) -> None:
    """Emit E_LIFECYCLE_INVALID if sidecar is missing; do not mutate projection."""
    sidecar_path = event.get("sidecar_path")
    if not isinstance(sidecar_path, str):
        return
    if (target, sidecar_path) not in state.sidecars_by_path:
        emit(
            message=(f"update_sidecar on missing sidecar {sidecar_path!r} (asset {target!r})"),
            loc=loc,
        )
