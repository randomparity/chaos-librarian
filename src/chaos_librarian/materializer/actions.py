"""Timeline action sets supported by the materializer."""

from __future__ import annotations

from typing import Final

from chaos_librarian.contract.materialization import CORRUPTION_TIMELINE_ACTIONS
from chaos_librarian.contract.scenario import HIERARCHY_TIMELINE_ACTIONS, TimelineActionName

BASE_FILESYSTEM_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
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

MEDIA_PHASE_B_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.REENCODE_VIDEO,
        TimelineActionName.REENCODE_AUDIO,
        TimelineActionName.REMUX_CONTAINER,
        TimelineActionName.EDIT_METADATA,
        TimelineActionName.EMBED_SUBTITLE,
        TimelineActionName.EXTRACT_SUBTITLE,
        TimelineActionName.UPDATE_SIDECAR,
        TimelineActionName.CREATE_SIDECAR,
    }
)

# create_sidecar is routed with media handlers because the per-kind byte
# generators (subtitle / NFO / poster) live there; filter it out of the
# stdlib set to keep phase-B routing single-dispatch.
STDLIB_PHASE_B_ACTIONS: Final[frozenset[TimelineActionName]] = (
    BASE_FILESYSTEM_ACTIONS - {TimelineActionName.CREATE_SIDECAR}
) | frozenset({TimelineActionName.REMOVE_SIDECAR})

ORACLE_HASH_PHASE_B_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.WRONG_ORACLE_HASH,
    }
)

FILESYSTEM_ARTIFACT_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.TOUCH_MTIME,
    }
)

HIERARCHY_PHASE_B_ACTIONS: Final[frozenset[TimelineActionName]] = HIERARCHY_TIMELINE_ACTIONS

# Podcast staleness records a neutral oracle fact; the file lingers untouched on
# disk, so this has no filesystem effect (like wrong_oracle_hash) — supported but
# not dispatched to a filesystem handler.
PODCAST_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.MARK_EPISODE_STALE,
    }
)

NETWORK_LAG_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.NETWORK_LAG_START,
        TimelineActionName.NETWORK_LAG_COMMIT,
    }
)

NETWORK_FS_CHAOS_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.CHANGE_PERMISSIONS,
        TimelineActionName.SIMULATE_QUOTA_EXCEEDED,
        TimelineActionName.TOGGLE_READONLY,
        TimelineActionName.SIMULATE_STALE_HANDLE,
        TimelineActionName.UNMOUNT_PATH,
        TimelineActionName.REMOUNT_PATH,
        TimelineActionName.ACQUIRE_LOCK,
        TimelineActionName.RELEASE_LOCK,
    }
)

MATERIALIZE_SUPPORTED_ACTIONS: Final[frozenset[TimelineActionName]] = (
    STDLIB_PHASE_B_ACTIONS
    | MEDIA_PHASE_B_ACTIONS
    | CORRUPTION_TIMELINE_ACTIONS
    | ORACLE_HASH_PHASE_B_ACTIONS
    | FILESYSTEM_ARTIFACT_ACTIONS
    | HIERARCHY_PHASE_B_ACTIONS
    | PODCAST_ACTIONS
)
