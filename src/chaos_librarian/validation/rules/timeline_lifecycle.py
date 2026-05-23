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
from chaos_librarian.validation.rules._common import (
    Reporter,
    _iter_timeline_events,
    _Loc,
    iter_asset_ids,
    iter_declared_sidecars,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

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
    }
)
# Subset of the passthrough set that mutates the on-disk path OR reads asset
# bytes. These keep the asset placed but relocate / mutate / read bytes, so
# they also reject while a slow_copy is pending — same guard the mutation set
# already applies to move/rename/delete. UPDATE_SIDECAR and REMOVE_SIDECAR are
# intentionally excluded — they touch a sidecar file, not the asset.
# See follow-up issue #48 for the rename to slow_copy_forbidden_set.
_PATH_MUTATING_PASSTHROUGH: frozenset[str] = frozenset(
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
    sidecars_by_path: dict[tuple[str, str], str] = field(default_factory=dict)
    """(asset_id, path) -> kind. Seeded from declared subtitles; updated
    by create_sidecar / extract_subtitle (insert) and
    remove_sidecar / embed_subtitle (delete)."""


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
    state = _LifecycleState(
        placed=set(iter_asset_ids(raw)),
        pending_slow_copies={},
        assets_with_pending_copy=set(),
        sidecars_by_path=_seed_sidecars_by_path(raw),
    )

    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        if not isinstance(action, str):
            continue  # Pydantic owns shape on missing/non-string action
        target = event.get("target")
        loc: _Loc = ("timeline", idx, "action")

        if action == TimelineActionName.ADD_FILE and isinstance(target, str):
            _lifecycle_check_add_file(target=target, state=state, emit=emit, loc=loc)
        elif action in _MUTATION_ACTIONS and isinstance(target, str):
            _lifecycle_check_mutation(
                action=action,
                target=target,
                state=state,
                emit=emit,
                loc=loc,
            )
        elif action == TimelineActionName.CREATE_SIDECAR and isinstance(target, str):
            _lifecycle_check_passthrough(
                action=action, target=target, state=state, emit=emit, loc=loc
            )
            _apply_create_sidecar(event=event, target=target, state=state)
        elif action == TimelineActionName.EXTRACT_SUBTITLE and isinstance(target, str):
            _lifecycle_check_passthrough(
                action=action, target=target, state=state, emit=emit, loc=loc
            )
            _apply_extract_subtitle(event=event, target=target, state=state)
        elif action == TimelineActionName.EMBED_SUBTITLE and isinstance(target, str):
            _lifecycle_check_passthrough(
                action=action, target=target, state=state, emit=emit, loc=loc
            )
            _apply_embed_subtitle(event=event, target=target, state=state, emit=emit, loc=loc)
        elif action == TimelineActionName.REMOVE_SIDECAR and isinstance(target, str):
            _lifecycle_check_passthrough(
                action=action, target=target, state=state, emit=emit, loc=loc
            )
            _apply_remove_sidecar(event=event, target=target, state=state, emit=emit, loc=loc)
        elif action == TimelineActionName.UPDATE_SIDECAR and isinstance(target, str):
            _lifecycle_check_passthrough(
                action=action, target=target, state=state, emit=emit, loc=loc
            )
            _apply_update_sidecar(event=event, target=target, state=state, emit=emit, loc=loc)
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
    if action in _PATH_MUTATING_PASSTHROUGH and target in state.assets_with_pending_copy:
        emit(message=f"{action} on asset {target!r} with a pending slow_copy", loc=loc)


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


def _apply_create_sidecar(
    *,
    event: Mapping[str, object],
    target: str,
    state: _LifecycleState,
) -> None:
    """Insert (target, to) -> kind into the sidecar projection."""
    to = event.get("to")
    kind = event.get("kind", SidecarKind.SUBTITLE.value)
    if isinstance(to, str) and isinstance(kind, str):
        state.sidecars_by_path[(target, to)] = kind


def _apply_extract_subtitle(
    *,
    event: Mapping[str, object],
    target: str,
    state: _LifecycleState,
) -> None:
    """Insert (target, to) -> subtitle into the sidecar projection."""
    to = event.get("to")
    if isinstance(to, str):
        state.sidecars_by_path[(target, to)] = SidecarKind.SUBTITLE.value


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


def _seed_sidecars_by_path(raw: Mapping[str, object]) -> dict[tuple[str, str], str]:
    """Seed (asset_id, path) -> kind for declared subtitle sidecars.

    Declared subtitles use the path convention <asset_id>.<language>.srt
    (per scenario v5 §"Declared-sidecar path convention").
    """
    return {
        (sidecar.asset_id, sidecar.path): sidecar.kind for sidecar in iter_declared_sidecars(raw)
    }
