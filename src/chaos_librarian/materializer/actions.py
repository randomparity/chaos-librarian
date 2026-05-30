"""Timeline action sets supported by the materializer."""

from __future__ import annotations

from typing import Final

from chaos_librarian.contract.scenario import HIERARCHY_TIMELINE_ACTIONS, TimelineActionName

SUPPORTED_S6_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
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

_MEDIA_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
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

# create_sidecar moved to _MEDIA_ACTIONS in Sprint 7: the per-kind byte
# generators (subtitle / NFO / poster) belong alongside the media handlers,
# so Sprint 6's stdlib set is filtered here to keep routing single-dispatch.
_STDLIB_ACTIONS: Final[frozenset[TimelineActionName]] = (
    SUPPORTED_S6_ACTIONS - {TimelineActionName.CREATE_SIDECAR}
) | frozenset({TimelineActionName.REMOVE_SIDECAR})

SUPPORTED_S7_ACTIONS: Final[frozenset[TimelineActionName]] = _STDLIB_ACTIONS | _MEDIA_ACTIONS

_CORRUPTION_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.CORRUPT_CONTAINER_HEADER,
        TimelineActionName.TRUNCATE_FILE,
        TimelineActionName.CORRUPT_PACKET_RANGE,
        TimelineActionName.WRITE_INVALID_DURATION_METADATA,
        TimelineActionName.CORRUPT_TAGS,
    }
)

_ORACLE_HASH_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.WRONG_ORACLE_HASH,
    }
)

_FILESYSTEM_ARTIFACT_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset(
    {
        TimelineActionName.TOUCH_MTIME,
    }
)

_HIERARCHY_ACTIONS: Final[frozenset[TimelineActionName]] = HIERARCHY_TIMELINE_ACTIONS

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

SUPPORTED_S10_ACTIONS: Final[frozenset[TimelineActionName]] = (
    _STDLIB_ACTIONS
    | _MEDIA_ACTIONS
    | _CORRUPTION_ACTIONS
    | _ORACLE_HASH_ACTIONS
    | _FILESYSTEM_ARTIFACT_ACTIONS
    | _HIERARCHY_ACTIONS
    | PODCAST_ACTIONS
)
