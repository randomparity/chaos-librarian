"""Plan-engine event dispatcher.

``apply_event`` is the single entry point. Handler implementations live
under ``chaos_librarian.engine.event_handlers`` by action family; this
module owns the public dispatch table and state-delta contract.
"""

from __future__ import annotations

from typing import Final

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.engine.context import EngineEventContext
from chaos_librarian.engine.event_handlers.common import _Handler
from chaos_librarian.engine.event_handlers.corruption import (
    _handle_corrupt_container_header,
    _handle_corrupt_packet_range,
    _handle_corrupt_tags,
    _handle_touch_mtime,
    _handle_truncate_file,
    _handle_write_invalid_duration_metadata,
    _handle_wrong_oracle_hash,
)
from chaos_librarian.engine.event_handlers.filesystem import (
    _handle_add_file,
    _handle_archive_file,
    _handle_delete_file,
    _handle_move_asset,
    _handle_move_between_roots,
    _handle_rename_file,
    _handle_slow_copy_commit,
    _handle_slow_copy_start,
)
from chaos_librarian.engine.event_handlers.hierarchy import (
    _handle_mark_episode_stale,
    _handle_move_episode_to_season,
    _handle_move_track_to_disc,
    _handle_rename_season,
    _handle_renumber_disc,
    _handle_renumber_episode,
    _handle_republish_episode,
    _handle_swap_disc_numbers,
    _handle_swap_episode_numbers,
    _handle_swap_track_numbers,
)
from chaos_librarian.engine.event_handlers.media import (
    _handle_create_sidecar,
    _handle_edit_metadata,
    _handle_embed_subtitle,
    _handle_extract_subtitle,
    _handle_reencode_audio,
    _handle_reencode_video,
    _handle_remove_sidecar,
    _handle_remux_container,
    _handle_update_sidecar,
)
from chaos_librarian.engine.event_handlers.network_fs_chaos import (
    _handle_acquire_lock,
    _handle_change_permissions,
    _handle_release_lock,
    _handle_remount_path,
    _handle_simulate_quota_exceeded,
    _handle_simulate_stale_handle,
    _handle_toggle_readonly,
    _handle_unmount_path,
)
from chaos_librarian.engine.event_handlers.network_lag import (
    _handle_network_lag_commit,
    _handle_network_lag_start,
)
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState

__all__ = ["_STATE_DELTA_KEYS", "apply_event"]

_STATE_DELTA_KEYS: Final[dict[TimelineActionName, frozenset[str]]] = {
    TimelineActionName.MOVE_ASSET: frozenset({"from_path", "to_path"}),
    TimelineActionName.RENAME_FILE: frozenset({"from_path", "to_path"}),
    TimelineActionName.DELETE_FILE: frozenset({"removed_path"}),
    TimelineActionName.ADD_FILE: frozenset({"added_path"}),
    TimelineActionName.CREATE_SIDECAR: frozenset(
        {
            "sidecar_path",
            "sidecar_id",
            "language",
            "kind",
            "codec",
            "source",
            "encoding",
            "body",
            "media_type",
            "image_format",
        }
    ),
    TimelineActionName.SLOW_COPY_START: frozenset(
        {"final_path", "temp_path", "initial_path_at_start"}
    ),
    TimelineActionName.SLOW_COPY_COMMIT: frozenset({"final_path"}),
    TimelineActionName.ARCHIVE_FILE: frozenset({"from_path", "to_path"}),
    TimelineActionName.MOVE_BETWEEN_ROOTS: frozenset(
        {"from_path", "to_path", "from_root_id", "to_root_id"}
    ),
    TimelineActionName.REENCODE_VIDEO: frozenset(
        {"resolution", "codec", "input_path", "output_path"}
    ),
    TimelineActionName.REENCODE_AUDIO: frozenset(
        {"from_channels", "to_channels", "input_path", "output_path"}
    ),
    TimelineActionName.REMUX_CONTAINER: frozenset(
        {"from_container", "to_container", "from_path", "to_path", "input_path", "output_path"}
    ),
    TimelineActionName.EDIT_METADATA: frozenset({"fields", "input_path", "output_path"}),
    TimelineActionName.EMBED_SUBTITLE: frozenset(
        {
            "embedded_sidecar_id",
            "embedded_sidecar_path",
            "language",
            "kind",
            "input_path",
            "output_path",
        }
    ),
    TimelineActionName.EXTRACT_SUBTITLE: frozenset(
        {"sidecar_id", "sidecar_path", "language", "input_path"}
    ),
    TimelineActionName.REMOVE_SIDECAR: frozenset({"removed_sidecar_id", "removed_sidecar_path"}),
    TimelineActionName.UPDATE_SIDECAR: frozenset({"sidecar_id", "sidecar_path"}),
    TimelineActionName.CORRUPT_CONTAINER_HEADER: frozenset(
        {
            "input_path",
            "output_path",
            "profile",
            "corruptor",
            "byte_start",
            "byte_count",
            "seed_material",
        }
    ),
    TimelineActionName.TRUNCATE_FILE: frozenset(
        {
            "input_path",
            "output_path",
            "profile",
            "corruptor",
            "keep_bytes",
            "seed_material",
        }
    ),
    TimelineActionName.CORRUPT_PACKET_RANGE: frozenset(
        {
            "input_path",
            "output_path",
            "profile",
            "corruptor",
            "stream",
            "packet_start",
            "packet_count",
            "seed_material",
        }
    ),
    TimelineActionName.WRITE_INVALID_DURATION_METADATA: frozenset(
        {
            "input_path",
            "output_path",
            "profile",
            "corruptor",
            "value",
            "seed_material",
        }
    ),
    TimelineActionName.CORRUPT_TAGS: frozenset(
        {
            "input_path",
            "output_path",
            "profile",
            "corruptor",
            "flavor",
            "byte_count",
            "seed_material",
        }
    ),
    TimelineActionName.TOUCH_MTIME: frozenset({"path", "profile", "offset"}),
    TimelineActionName.WRONG_ORACLE_HASH: frozenset(
        {
            "input_path",
            "output_path",
            "profile",
            "algorithm",
            "seed_material",
        }
    ),
    TimelineActionName.NETWORK_LAG_START: frozenset(
        {
            "effect",
            "target_ref",
            "after_event_id",
            "logical_start_ns",
            "logical_commit_ns",
            "requested_duration_ns",
            "from_path",
            "to_path",
        }
    ),
    TimelineActionName.NETWORK_LAG_COMMIT: frozenset(
        {
            "effect",
            "target_ref",
            "after_event_id",
            "logical_start_ns",
            "logical_commit_ns",
            "requested_duration_ns",
            "from_path",
            "to_path",
        }
    ),
    TimelineActionName.RENUMBER_EPISODE: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
    TimelineActionName.MOVE_EPISODE_TO_SEASON: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
    TimelineActionName.RENAME_SEASON: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
    TimelineActionName.RENUMBER_DISC: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
    TimelineActionName.MOVE_TRACK_TO_DISC: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
    TimelineActionName.SWAP_EPISODE_NUMBERS: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
    TimelineActionName.SWAP_DISC_NUMBERS: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
    TimelineActionName.SWAP_TRACK_NUMBERS: frozenset(
        {"metadata", "path_moves", "sidecar_moves", "skipped_deleted_asset_ids"}
    ),
}
"""Per-action contract for emitted ``state_delta`` keys.

Each handler MUST emit at least these keys; extras are allowed for forward
compatibility. ``create_sidecar`` includes ``language`` and
``slow_copy_start`` includes
``initial_path_at_start`` so Phase B and ``derive_path_history`` can drive
purely from the journal.

The parametrized test ``test_state_delta_keys_match_contract`` enforces this
contract by invoking each handler against a minimal scenario.
"""


def apply_event(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    """Dispatch one resolved event to its handler and return its journal entries."""
    handler = _HANDLERS[resolved.event.action]
    entries = handler(state, resolved, ids, ctx)
    for entry in entries:
        ctx.previous_event_delta = (entry.event_id, dict(entry.state_delta))
    return entries


_HANDLERS: dict[TimelineActionName, _Handler] = {
    TimelineActionName.MOVE_ASSET: _handle_move_asset,
    TimelineActionName.RENAME_FILE: _handle_rename_file,
    TimelineActionName.DELETE_FILE: _handle_delete_file,
    TimelineActionName.ADD_FILE: _handle_add_file,
    TimelineActionName.REENCODE_VIDEO: _handle_reencode_video,
    TimelineActionName.REENCODE_AUDIO: _handle_reencode_audio,
    TimelineActionName.CREATE_SIDECAR: _handle_create_sidecar,
    TimelineActionName.SLOW_COPY_START: _handle_slow_copy_start,
    TimelineActionName.SLOW_COPY_COMMIT: _handle_slow_copy_commit,
    TimelineActionName.ARCHIVE_FILE: _handle_archive_file,
    TimelineActionName.MOVE_BETWEEN_ROOTS: _handle_move_between_roots,
    TimelineActionName.REMUX_CONTAINER: _handle_remux_container,
    TimelineActionName.EDIT_METADATA: _handle_edit_metadata,
    TimelineActionName.EMBED_SUBTITLE: _handle_embed_subtitle,
    TimelineActionName.EXTRACT_SUBTITLE: _handle_extract_subtitle,
    TimelineActionName.REMOVE_SIDECAR: _handle_remove_sidecar,
    TimelineActionName.UPDATE_SIDECAR: _handle_update_sidecar,
    TimelineActionName.CORRUPT_CONTAINER_HEADER: _handle_corrupt_container_header,
    TimelineActionName.TRUNCATE_FILE: _handle_truncate_file,
    TimelineActionName.CORRUPT_PACKET_RANGE: _handle_corrupt_packet_range,
    TimelineActionName.WRITE_INVALID_DURATION_METADATA: _handle_write_invalid_duration_metadata,
    TimelineActionName.CORRUPT_TAGS: _handle_corrupt_tags,
    TimelineActionName.TOUCH_MTIME: _handle_touch_mtime,
    TimelineActionName.WRONG_ORACLE_HASH: _handle_wrong_oracle_hash,
    TimelineActionName.NETWORK_LAG_START: _handle_network_lag_start,
    TimelineActionName.NETWORK_LAG_COMMIT: _handle_network_lag_commit,
    TimelineActionName.CHANGE_PERMISSIONS: _handle_change_permissions,
    TimelineActionName.SIMULATE_QUOTA_EXCEEDED: _handle_simulate_quota_exceeded,
    TimelineActionName.TOGGLE_READONLY: _handle_toggle_readonly,
    TimelineActionName.SIMULATE_STALE_HANDLE: _handle_simulate_stale_handle,
    TimelineActionName.UNMOUNT_PATH: _handle_unmount_path,
    TimelineActionName.REMOUNT_PATH: _handle_remount_path,
    TimelineActionName.ACQUIRE_LOCK: _handle_acquire_lock,
    TimelineActionName.RELEASE_LOCK: _handle_release_lock,
    TimelineActionName.RENUMBER_EPISODE: _handle_renumber_episode,
    TimelineActionName.MOVE_EPISODE_TO_SEASON: _handle_move_episode_to_season,
    TimelineActionName.RENAME_SEASON: _handle_rename_season,
    TimelineActionName.RENUMBER_DISC: _handle_renumber_disc,
    TimelineActionName.MOVE_TRACK_TO_DISC: _handle_move_track_to_disc,
    TimelineActionName.SWAP_EPISODE_NUMBERS: _handle_swap_episode_numbers,
    TimelineActionName.SWAP_DISC_NUMBERS: _handle_swap_disc_numbers,
    TimelineActionName.SWAP_TRACK_NUMBERS: _handle_swap_track_numbers,
    TimelineActionName.REPUBLISH_EPISODE: _handle_republish_episode,
    TimelineActionName.MARK_EPISODE_STALE: _handle_mark_episode_stale,
}
