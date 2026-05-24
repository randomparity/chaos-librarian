"""derive_version_history — project version-affecting journal events for one asset.

Pure function over the journal. Mirrors ``engine/path_history.py``'s
shape for the version-allocating subset of actions (reencode_*,
remux_container, edit_metadata, embed_subtitle).

``extract_subtitle`` is intentionally NOT version-affecting (spec design
decision #9): extraction is read-only on the asset bytes.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.reports import VersionHistoryEntry
from chaos_librarian.contract.scenario import TimelineActionName

__all__ = ["derive_version_history"]


_VERSION_AFFECTING_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.REENCODE_VIDEO,
        TimelineActionName.REENCODE_AUDIO,
        TimelineActionName.REMUX_CONTAINER,
        TimelineActionName.EDIT_METADATA,
        TimelineActionName.EMBED_SUBTITLE,
        TimelineActionName.CORRUPT_CONTAINER_HEADER,
        TimelineActionName.TRUNCATE_FILE,
        TimelineActionName.CORRUPT_PACKET_RANGE,
        TimelineActionName.WRITE_INVALID_DURATION_METADATA,
        TimelineActionName.WRONG_ORACLE_HASH,
    }
)


_PRESERVED_DELTA_KEYS: Final[dict[TimelineActionName, frozenset[str]]] = {
    TimelineActionName.REENCODE_VIDEO: frozenset({"resolution", "codec"}),
    TimelineActionName.REENCODE_AUDIO: frozenset({"from_channels", "to_channels"}),
    TimelineActionName.REMUX_CONTAINER: frozenset({"from_container", "to_container"}),
    TimelineActionName.EDIT_METADATA: frozenset({"fields"}),
    TimelineActionName.EMBED_SUBTITLE: frozenset({"language", "kind"}),
    TimelineActionName.CORRUPT_CONTAINER_HEADER: frozenset(
        {"profile", "corruptor", "byte_start", "byte_count", "seed_material"}
    ),
    TimelineActionName.TRUNCATE_FILE: frozenset(
        {"profile", "corruptor", "keep_bytes", "seed_material"}
    ),
    TimelineActionName.CORRUPT_PACKET_RANGE: frozenset(
        {
            "profile",
            "corruptor",
            "stream",
            "packet_start",
            "packet_count",
            "seed_material",
        }
    ),
    TimelineActionName.WRITE_INVALID_DURATION_METADATA: frozenset(
        {"profile", "corruptor", "value", "seed_material"}
    ),
    TimelineActionName.WRONG_ORACLE_HASH: frozenset({"profile", "algorithm", "seed_material"}),
}


def derive_version_history(
    asset_id: str, journal: Iterable[JournalEntry]
) -> list[VersionHistoryEntry]:
    """Project the version-affecting subset of ``journal`` for ``asset_id``.

    Reads each entry's ``action``, filters to the version-affecting set,
    further filters to entries that target ``asset_id``, and projects
    the contract-locked subset of ``state_delta`` keys per action.
    """
    history: list[VersionHistoryEntry] = []
    for entry in journal:
        try:
            action = TimelineActionName(entry.action)
        except ValueError:
            continue  # unknown actions never carry version semantics
        if action not in _VERSION_AFFECTING_ACTIONS:
            continue
        if asset_id not in entry.target_ids:
            continue
        preserved_keys = _PRESERVED_DELTA_KEYS[action]
        summary = {k: entry.state_delta[k] for k in preserved_keys if k in entry.state_delta}
        history.append(
            VersionHistoryEntry(
                event_id=entry.event_id,
                action=action,
                logical_time_ns=entry.logical_time_ns,
                input_version_id=(entry.input_version_ids[0] if entry.input_version_ids else None),
                output_version_id=(
                    entry.output_version_ids[0] if entry.output_version_ids else None
                ),
                state_delta_summary=summary,
            )
        )
    return history
