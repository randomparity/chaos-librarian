"""Contract-owned profile-gating policy for timeline actions."""

from __future__ import annotations

from typing import Final

from chaos_librarian.contract.profiles import ProfileName
from chaos_librarian.contract.scenario import TimelineActionName

REQUIRED_PROFILES_BY_ACTION: Final[dict[TimelineActionName, ProfileName]] = {
    TimelineActionName.CORRUPT_CONTAINER_HEADER: ProfileName.MALFORMED_MEDIA,
    TimelineActionName.TRUNCATE_FILE: ProfileName.MALFORMED_MEDIA,
    TimelineActionName.CORRUPT_PACKET_RANGE: ProfileName.MALFORMED_MEDIA,
    TimelineActionName.WRITE_INVALID_DURATION_METADATA: ProfileName.MALFORMED_MEDIA,
    TimelineActionName.CORRUPT_TAGS: ProfileName.MALFORMED_MEDIA,
    TimelineActionName.TOUCH_MTIME: ProfileName.FILESYSTEM_ARTIFACTS,
    TimelineActionName.WRONG_ORACLE_HASH: ProfileName.NEGATIVE_ORACLE,
    TimelineActionName.NETWORK_LAG_START: ProfileName.NETWORK_FS_LAG,
    TimelineActionName.NETWORK_LAG_COMMIT: ProfileName.NETWORK_FS_LAG,
    TimelineActionName.CHANGE_PERMISSIONS: ProfileName.NETWORK_FS_CHAOS,
    TimelineActionName.SIMULATE_QUOTA_EXCEEDED: ProfileName.NETWORK_FS_CHAOS,
    TimelineActionName.TOGGLE_READONLY: ProfileName.NETWORK_FS_CHAOS,
    TimelineActionName.SIMULATE_STALE_HANDLE: ProfileName.NETWORK_FS_CHAOS,
    TimelineActionName.UNMOUNT_PATH: ProfileName.NETWORK_FS_CHAOS,
    TimelineActionName.REMOUNT_PATH: ProfileName.NETWORK_FS_CHAOS,
    TimelineActionName.ACQUIRE_LOCK: ProfileName.NETWORK_FS_CHAOS,
    TimelineActionName.RELEASE_LOCK: ProfileName.NETWORK_FS_CHAOS,
}
"""Timeline action -> profile label required to authorize it."""
