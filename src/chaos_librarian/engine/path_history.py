"""Project the journal to one asset's filesystem-affecting subset.

Sprint 6: ``AssetReport.path_history`` carries a typed projection of the
journal's filesystem events for the asset under report. The function is
mode-agnostic — both plan-only and materialize call it.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

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
    }
)
"""Actions whose journal entries describe an on-disk change.

ADD_FILE stays in the set even though Sprint 6's materializer rejects it
at preflight — plan-only journals are still allowed to contain add_file
events, and path_history is a logical projection (not a materialize-only
audit). Sprint 7 removes the materialize gate without touching this set.
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


def _maybe_str(value: object) -> str | None:
    """Return ``value`` if it is a str, else None.

    state_delta values are typed ``object`` at the schema level (the field
    is ``dict[str, object]``). Defensive cast keeps the PathHistoryEntry's
    typed fields honest even if a future handler emits a non-string value
    in one of the path keys.
    """
    return value if isinstance(value, str) else None
