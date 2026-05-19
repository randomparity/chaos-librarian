"""Rule 8: E_LIFECYCLE_INVALID — reject timelines that can't execute.

Simulates the asset lifecycle: every declared asset starts "placed" (per
``docs/contract/manifest-initial-state.md``). The simulation rejects
operations that would otherwise crash the engine's per-handler state
lookups (``state._asset_to_location``, etc).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.validation.codes import E_LIFECYCLE_INVALID
from chaos_librarian.validation.rules._common import _iter_timeline_events, _Loc
from chaos_librarian.validation.rules.id_duplicate import iter_asset_ids

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
    state = _LifecycleState(
        placed=set(iter_asset_ids(raw)),
        pending_slow_copies={},
        assets_with_pending_copy=set(),
    )

    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        if not isinstance(action, str):
            continue  # Pydantic owns shape on missing/non-string action
        target = event.get("target")
        loc: _Loc = ("timeline", idx, "action")
        kwargs = {
            "state": state,
            "collector": collector,
            "line_index": line_index,
            "loc": loc,
        }

        if action == TimelineActionName.ADD_FILE and isinstance(target, str):
            _lifecycle_check_add_file(target=target, **kwargs)
        elif action in _MUTATION_ACTIONS and isinstance(target, str):
            _lifecycle_check_mutation(action=action, target=target, **kwargs)
        elif action in _LOCATION_DEPENDENT_PASSTHROUGH and isinstance(target, str):
            _lifecycle_check_passthrough(action=action, target=target, **kwargs)
        elif action == TimelineActionName.SLOW_COPY_START and isinstance(target, str):
            _lifecycle_check_slow_copy_start(target=target, ev_id=event.get("id"), **kwargs)
        elif action == TimelineActionName.SLOW_COPY_COMMIT:
            _lifecycle_apply_commit(ref=event.get("for"), state=state)


def _lifecycle_emit(
    *,
    collector: IssueCollector,
    line_index: LineIndex,
    loc: _Loc,
    message: str,
) -> None:
    """Add one E_LIFECYCLE_INVALID error to the collector."""
    collector.add(
        code=E_LIFECYCLE_INVALID,
        severity=ValidationSeverity.ERROR,
        message=message,
        loc=loc,
        line_index=line_index,
    )


def _lifecycle_check_add_file(
    *,
    target: str,
    state: _LifecycleState,
    collector: IssueCollector,
    line_index: LineIndex,
    loc: _Loc,
) -> None:
    if target in state.placed:
        _lifecycle_emit(
            collector=collector,
            line_index=line_index,
            loc=loc,
            message=f"add_file on already-placed asset {target!r}",
        )
    state.placed.add(target)


def _lifecycle_check_mutation(
    *,
    action: str,
    target: str,
    state: _LifecycleState,
    collector: IssueCollector,
    line_index: LineIndex,
    loc: _Loc,
) -> None:
    if target not in state.placed:
        _lifecycle_emit(
            collector=collector,
            line_index=line_index,
            loc=loc,
            message=f"{action} on unplaced asset {target!r}",
        )
    if target in state.assets_with_pending_copy:
        _lifecycle_emit(
            collector=collector,
            line_index=line_index,
            loc=loc,
            message=f"{action} on asset {target!r} with a pending slow_copy",
        )
    if action == TimelineActionName.DELETE_FILE:
        state.placed.discard(target)


def _lifecycle_check_passthrough(
    *,
    action: str,
    target: str,
    state: _LifecycleState,
    collector: IssueCollector,
    line_index: LineIndex,
    loc: _Loc,
) -> None:
    if target not in state.placed:
        _lifecycle_emit(
            collector=collector,
            line_index=line_index,
            loc=loc,
            message=f"{action} on unplaced asset {target!r}",
        )


def _lifecycle_check_slow_copy_start(
    *,
    target: str,
    ev_id: object,
    state: _LifecycleState,
    collector: IssueCollector,
    line_index: LineIndex,
    loc: _Loc,
) -> None:
    if target not in state.placed:
        _lifecycle_emit(
            collector=collector,
            line_index=line_index,
            loc=loc,
            message=f"slow_copy_start on unplaced asset {target!r}",
        )
    if not isinstance(ev_id, str):
        return  # Pydantic owns shape; nothing to track
    if target in state.assets_with_pending_copy:
        _lifecycle_emit(
            collector=collector,
            line_index=line_index,
            loc=loc,
            message=f"slow_copy_start on asset {target!r} that already has a pending copy",
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
