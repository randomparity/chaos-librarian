"""Project the journal to one asset's filesystem-affecting subset.

Sprint 6: ``AssetReport.path_history`` carries a typed projection of the
journal's filesystem events for the asset under report. The function is
mode-agnostic — both plan-only and materialize call it.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Final, cast

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.reports import PathHistoryEntry
from chaos_librarian.contract.scenario import TimelineActionName

__all__ = ["derive_path_history"]


_FILESYSTEM_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.MOVE_ASSET,
        TimelineActionName.RENAME_FILE,
        TimelineActionName.DELETE_FILE,
        TimelineActionName.ADD_FILE,
        TimelineActionName.CREATE_SIDECAR,
        TimelineActionName.SLOW_COPY_START,
        TimelineActionName.SLOW_COPY_COMMIT,
        TimelineActionName.ARCHIVE_FILE,
        TimelineActionName.MOVE_BETWEEN_ROOTS,
        TimelineActionName.RENUMBER_EPISODE,
        TimelineActionName.MOVE_EPISODE_TO_SEASON,
        TimelineActionName.RENAME_SEASON,
        TimelineActionName.RENUMBER_DISC,
        TimelineActionName.MOVE_TRACK_TO_DISC,
    }
)
"""Actions whose journal entries describe an on-disk change.

ADD_FILE stays in the set because delete-then-add represents a file
disappearing and reappearing at a new path. path_history is a logical
projection, not a materialize-only audit.
"""


def derive_path_history(asset_id: str, journal: Iterable[JournalEntry]) -> list[PathHistoryEntry]:
    """Filter ``journal`` to filesystem entries targeting ``asset_id``.

    Returns entries in journal order (callers should pass a journal that
    is already sorted by ``logical_time_ns`` — same convention as Sprint
    4's ``AssetHistoryEntry`` derivation).
    """
    history: list[PathHistoryEntry] = []
    for entry in journal:
        action = TimelineActionName(entry.action)
        if action not in _FILESYSTEM_ACTIONS:
            continue
        if asset_id not in entry.target_ids:
            continue
        delta = entry.state_delta
        if action in _HIERARCHY_ACTIONS:
            history.extend(_hierarchy_path_entries(asset_id, entry))
            continue
        history.append(
            PathHistoryEntry(
                event_id=entry.event_id,
                action=action,
                logical_time_ns=entry.logical_time_ns,
                from_path=(
                    _maybe_str(delta.get("from_path"))
                    or _maybe_str(delta.get("removed_path"))
                    or _maybe_str(delta.get("initial_path_at_start"))
                ),
                to_path=(
                    _maybe_str(delta.get("to_path"))
                    or _maybe_str(delta.get("added_path"))
                    or _maybe_str(delta.get("final_path"))
                    or _maybe_str(delta.get("sidecar_path"))
                ),
                temp_path=_maybe_str(delta.get("temp_path")),
            )
        )
    return history


_HIERARCHY_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.RENUMBER_EPISODE,
        TimelineActionName.MOVE_EPISODE_TO_SEASON,
        TimelineActionName.RENAME_SEASON,
        TimelineActionName.RENUMBER_DISC,
        TimelineActionName.MOVE_TRACK_TO_DISC,
    }
)


def _hierarchy_path_entries(
    asset_id: str,
    entry: JournalEntry,
) -> list[PathHistoryEntry]:
    path_moves = entry.state_delta.get("path_moves")
    if not isinstance(path_moves, list):
        return []
    history: list[PathHistoryEntry] = []
    for move in path_moves:
        if not isinstance(move, Mapping):
            continue
        move = cast(Mapping[str, object], move)
        if move.get("asset_id") != asset_id:
            continue
        history.append(
            PathHistoryEntry(
                event_id=entry.event_id,
                action=TimelineActionName(entry.action),
                logical_time_ns=entry.logical_time_ns,
                from_path=_maybe_str(move.get("from_path")),
                to_path=_maybe_str(move.get("to_path")),
                temp_path=None,
            )
        )
    return history


def _maybe_str(value: object) -> str | None:
    """Return ``value`` if it is a str, else None.

    state_delta values are typed ``object`` at the schema level (the field
    is ``dict[str, object]``). Defensive cast keeps the PathHistoryEntry's
    typed fields honest even if a future handler emits a non-string value
    in one of the path keys.
    """
    return value if isinstance(value, str) else None
