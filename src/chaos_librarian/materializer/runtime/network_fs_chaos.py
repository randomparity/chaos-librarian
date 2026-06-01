"""Wall-clock realization of the network-fs-chaos timeline actions.

``change_permissions`` and ``toggle_readonly`` apply a real ``os.chmod`` to the
resolved target under ``<run-dir>/library/`` and capture the original mode so it
can be restored at teardown. The four kernel-level conditions
(``simulate_quota_exceeded``/ENOSPC, ``simulate_stale_handle``/ESTALE,
``acquire_lock``+``release_lock``/EAGAIN, ``unmount_path``+``remount_path``/
unavailable) perform no filesystem op and are recorded with ``enforced=False``.

Every action appends a neutral ``NetworkFsChaosAction`` to the materialization
report. Captured modes are restored by ``restore_chaos_modes`` at run finalize and
on the Phase-B failure path so the run tree is always cleanable.
"""

from __future__ import annotations

import stat
from dataclasses import dataclass, field
from pathlib import Path

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.materialization import (
    NetworkFsChaosAction,
    NetworkFsChaosCondition,
)
from chaos_librarian.contract.paths import resolve_under_library
from chaos_librarian.contract.scenario import LockType, ReadonlyState, TimelineActionName
from chaos_librarian.errors import ChaosLibrarianValueError

__all__ = [
    "CHAOS_CLOSE_ACTIONS",
    "CHAOS_ENTRY_ACTIONS",
    "NetworkFsChaosState",
    "realize_chaos_close",
    "realize_chaos_entry",
    "restore_chaos_modes",
]

# Single-shot + paired-open actions routed to ``realize_chaos_entry``; paired-close
# actions routed to ``realize_chaos_close``. Shared by the wall-clock runner and replay.
CHAOS_CLOSE_ACTIONS = frozenset({TimelineActionName.RELEASE_LOCK, TimelineActionName.REMOUNT_PATH})
CHAOS_ENTRY_ACTIONS = frozenset(
    {
        TimelineActionName.CHANGE_PERMISSIONS,
        TimelineActionName.TOGGLE_READONLY,
        TimelineActionName.SIMULATE_QUOTA_EXCEEDED,
        TimelineActionName.SIMULATE_STALE_HANDLE,
        TimelineActionName.ACQUIRE_LOCK,
        TimelineActionName.UNMOUNT_PATH,
    }
)

# Owner/group/other write bits cleared by toggle_readonly.
_WRITE_BITS = stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH


@dataclass(slots=True)
class NetworkFsChaosState:
    """Wall-clock network-fs-chaos accumulator threaded on the dispatch state."""

    library_root: Path
    actions: list[NetworkFsChaosAction] = field(default_factory=list)
    # Original mode per real-chmod path, captured the FIRST time the path is
    # touched. Keyed by path so stacked chmods (e.g. change_permissions then
    # toggle_readonly on the same asset) restore to the true pre-chaos mode, not
    # an intermediate one.
    captured_modes: dict[Path, int] = field(default_factory=dict)
    # Open windows keyed by the open event's id, holding the open's recorded facts.
    open_locks: dict[str, dict[str, object]] = field(default_factory=dict)
    open_unmounts: dict[str, dict[str, object]] = field(default_factory=dict)


def realize_chaos_entry(state: NetworkFsChaosState, entry: JournalEntry) -> None:
    """Realize one single-shot or paired-open chaos journal entry."""
    action = TimelineActionName(entry.action)
    if action is TimelineActionName.CHANGE_PERMISSIONS:
        _realize_change_permissions(state, entry)
    elif action is TimelineActionName.TOGGLE_READONLY:
        _realize_toggle_readonly(state, entry)
    elif action is TimelineActionName.SIMULATE_QUOTA_EXCEEDED:
        _record_simulated(state, entry, NetworkFsChaosCondition.ENOSPC)
    elif action is TimelineActionName.SIMULATE_STALE_HANDLE:
        _record_simulated(state, entry, NetworkFsChaosCondition.ESTALE)
    elif action is TimelineActionName.ACQUIRE_LOCK:
        state.open_locks[entry.event_id] = dict(entry.state_delta)
    elif action is TimelineActionName.UNMOUNT_PATH:
        state.open_unmounts[entry.event_id] = dict(entry.state_delta)
    else:  # pragma: no cover - dispatch only routes the actions above here
        raise ChaosLibrarianValueError(f"{entry.event_id}: not a chaos open entry {entry.action!r}")


def realize_chaos_close(state: NetworkFsChaosState, entry: JournalEntry) -> None:
    """Realize one paired-close chaos journal entry (release_lock / remount_path)."""
    action = TimelineActionName(entry.action)
    related_id = getattr(entry, "related_event_id", None)
    if not isinstance(related_id, str):
        raise ChaosLibrarianValueError(f"{entry.event_id}: chaos close missing related_event_id")
    if action is TimelineActionName.RELEASE_LOCK:
        open_delta = state.open_locks.pop(related_id)
        condition = NetworkFsChaosCondition.EAGAIN
        lock_type = _lock_type(open_delta)
        readonly_state: ReadonlyState | None = None
    elif action is TimelineActionName.REMOUNT_PATH:
        open_delta = state.open_unmounts.pop(related_id)
        condition = NetworkFsChaosCondition.UNAVAILABLE
        lock_type = None
        readonly_state = None
    else:  # pragma: no cover - dispatch only routes the actions above here
        raise ChaosLibrarianValueError(f"{entry.event_id}: not a chaos close {entry.action!r}")
    open_target = open_delta.get("target_ref")
    state.actions.append(
        NetworkFsChaosAction(
            event_id=related_id,
            action=action,
            target_ref=_target_ref(entry),
            condition=condition,
            enforced=False,
            lock_type=lock_type,
            readonly_state=readonly_state,
            related_event_id=entry.event_id,
            related_target_ref=open_target if isinstance(open_target, str) else None,
        )
    )


def restore_chaos_modes(state: NetworkFsChaosState) -> None:
    """Restore every captured original mode (run finalize and failure path).

    Idempotent: each restore clears the captured list, so a finalize after a
    failure-path restore is a no-op.
    """
    for path, original_mode in state.captured_modes.items():
        if path.exists():
            path.chmod(original_mode)
    state.captured_modes.clear()


def _realize_change_permissions(state: NetworkFsChaosState, entry: JournalEntry) -> None:
    target_ref = _target_ref(entry)
    mode_str = entry.state_delta.get("mode")
    if not isinstance(mode_str, str):
        raise ChaosLibrarianValueError(f"{entry.event_id}: change_permissions missing mode")
    new_mode = int(mode_str, 8)
    enforced = _apply_chmod(state, _resolve_entry_path(state, entry), new_mode)
    state.actions.append(
        NetworkFsChaosAction(
            event_id=entry.event_id,
            action=TimelineActionName.CHANGE_PERMISSIONS,
            target_ref=target_ref,
            condition=NetworkFsChaosCondition.EACCES,
            enforced=enforced,
            mode=mode_str,
        )
    )


def _realize_toggle_readonly(state: NetworkFsChaosState, entry: JournalEntry) -> None:
    target_ref = _target_ref(entry)
    readonly_state = _readonly_state(entry.state_delta)
    resolved = _resolve_entry_path(state, entry)
    enforced = False
    if resolved is not None and resolved.exists():
        current = stat.S_IMODE(resolved.stat().st_mode)
        _capture_mode(state, resolved, current)
        new_mode = (
            current & ~_WRITE_BITS
            if readonly_state is ReadonlyState.READONLY
            else (current | _WRITE_BITS)
        )
        resolved.chmod(new_mode)
        enforced = True
    state.actions.append(
        NetworkFsChaosAction(
            event_id=entry.event_id,
            action=TimelineActionName.TOGGLE_READONLY,
            target_ref=target_ref,
            condition=NetworkFsChaosCondition.EACCES,
            enforced=enforced,
            readonly_state=readonly_state,
        )
    )


def _record_simulated(
    state: NetworkFsChaosState, entry: JournalEntry, condition: NetworkFsChaosCondition
) -> None:
    state.actions.append(
        NetworkFsChaosAction(
            event_id=entry.event_id,
            action=TimelineActionName(entry.action),
            target_ref=_target_ref(entry),
            condition=condition,
            enforced=False,
        )
    )


def _apply_chmod(state: NetworkFsChaosState, resolved: Path | None, new_mode: int) -> bool:
    """Chmod the resolved target; return whether a real op was applied."""
    if resolved is None or not resolved.exists():
        return False
    _capture_mode(state, resolved, stat.S_IMODE(resolved.stat().st_mode))
    resolved.chmod(new_mode)
    return True


def _capture_mode(state: NetworkFsChaosState, path: Path, original_mode: int) -> None:
    # First touch wins: a later chmod on the same path must not overwrite the
    # true pre-chaos mode with an intermediate (e.g. 000) one.
    state.captured_modes.setdefault(path, original_mode)


def _resolve_entry_path(state: NetworkFsChaosState, entry: JournalEntry) -> Path | None:
    """Resolve a chaos entry's library-relative ``path`` under ``library/``.

    The engine records the asset's rendered path (or the subtree path) under the
    ``path`` key. Validation has already rejected escaping paths; resolve under
    the library root and return None if it cannot be contained (defensive — never
    raises into the runner).
    """
    path_value = entry.state_delta.get("path")
    if not isinstance(path_value, str):
        return None
    try:
        return resolve_under_library(Path(path_value), state.library_root)
    except (ChaosLibrarianValueError, ValueError, OSError):
        return None


def _target_ref(entry: JournalEntry) -> str:
    value = entry.state_delta.get("target_ref")
    if isinstance(value, str):
        return value
    if entry.target_ids:
        return entry.target_ids[0]
    raise ChaosLibrarianValueError(f"{entry.event_id}: chaos entry missing target_ref")


def _readonly_state(state_delta: dict[str, object]) -> ReadonlyState:
    value = state_delta.get("readonly_state")
    if isinstance(value, str):
        return ReadonlyState(value)
    raise ChaosLibrarianValueError("toggle_readonly missing readonly_state")


def _lock_type(open_delta: dict[str, object]) -> LockType | None:
    value = open_delta.get("lock_type")
    return LockType(value) if isinstance(value, str) else None
