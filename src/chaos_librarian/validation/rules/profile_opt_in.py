"""Rule: profile-specific actions require their matching profile labels."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from chaos_librarian.contract.profiles import ProfileName
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_PROFILE_REQUIRED
from chaos_librarian.validation.rules.raw_helpers import (
    Reporter,
    _iter_timeline_events,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.reporting import IssueCollector


REQUIRED_PROFILES_BY_ACTION: Final[dict[str, str]] = {
    TimelineActionName.CORRUPT_CONTAINER_HEADER.value: ProfileName.MALFORMED_MEDIA.value,
    TimelineActionName.TRUNCATE_FILE.value: ProfileName.MALFORMED_MEDIA.value,
    TimelineActionName.CORRUPT_PACKET_RANGE.value: ProfileName.MALFORMED_MEDIA.value,
    TimelineActionName.WRITE_INVALID_DURATION_METADATA.value: ProfileName.MALFORMED_MEDIA.value,
    TimelineActionName.CORRUPT_TAGS.value: ProfileName.MALFORMED_MEDIA.value,
    TimelineActionName.TOUCH_MTIME.value: ProfileName.FILESYSTEM_ARTIFACTS.value,
    TimelineActionName.WRONG_ORACLE_HASH.value: ProfileName.NEGATIVE_ORACLE.value,
    TimelineActionName.NETWORK_LAG_START.value: ProfileName.NETWORK_FS_LAG.value,
    TimelineActionName.NETWORK_LAG_COMMIT.value: ProfileName.NETWORK_FS_LAG.value,
    TimelineActionName.CHANGE_PERMISSIONS.value: ProfileName.NETWORK_FS_CHAOS.value,
    TimelineActionName.SIMULATE_QUOTA_EXCEEDED.value: ProfileName.NETWORK_FS_CHAOS.value,
    TimelineActionName.TOGGLE_READONLY.value: ProfileName.NETWORK_FS_CHAOS.value,
    TimelineActionName.SIMULATE_STALE_HANDLE.value: ProfileName.NETWORK_FS_CHAOS.value,
    TimelineActionName.UNMOUNT_PATH.value: ProfileName.NETWORK_FS_CHAOS.value,
    TimelineActionName.REMOUNT_PATH.value: ProfileName.NETWORK_FS_CHAOS.value,
    TimelineActionName.ACQUIRE_LOCK.value: ProfileName.NETWORK_FS_CHAOS.value,
    TimelineActionName.RELEASE_LOCK.value: ProfileName.NETWORK_FS_CHAOS.value,
}
"""Action value -> profile label required to authorize it.

Single source of truth for which timeline actions are profile-gated. Fuzz
lane generation derives the gated profile labels it must declare from this
map, so generated scenarios cannot drift out of sync with the validation
rule that would otherwise reject them.
"""


def rule_profile_opt_in(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    reporter = Reporter(collector=collector, line_index=line_index)
    profiles_raw = raw.get("profiles", [])
    profiles = set(profiles_raw) if isinstance(profiles_raw, list) else set()
    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        if not isinstance(action, str):
            continue
        required_profile = REQUIRED_PROFILES_BY_ACTION.get(action)
        if required_profile is not None and required_profile not in profiles:
            _emit_required_profile(
                action=action,
                profile=required_profile,
                event=event,
                idx=idx,
                reporter=reporter,
            )


def _emit_required_profile(
    *,
    action: str,
    profile: str,
    event: Mapping[str, object],
    idx: int,
    reporter: Reporter,
) -> None:
    event_id = event.get("id")
    suffix = f" for event {event_id!r}" if isinstance(event_id, str) else ""
    reporter.error(
        code=E_PROFILE_REQUIRED,
        message=f"{action} requires profile {profile!r}{suffix}",
        loc=("timeline", idx, "action"),
    )
