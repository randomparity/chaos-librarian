"""Rule: profile-specific actions require their matching profile labels."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.profiles import ProfileName
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_PROFILE_REQUIRED
from chaos_librarian.validation.rules._common import Reporter, _iter_timeline_events

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector


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
        if (
            action == TimelineActionName.CORRUPT_CONTAINER_HEADER.value
            and ProfileName.MALFORMED_MEDIA.value not in profiles
        ):
            _emit_required_profile(
                action=TimelineActionName.CORRUPT_CONTAINER_HEADER.value,
                profile=ProfileName.MALFORMED_MEDIA.value,
                event=event,
                idx=idx,
                reporter=reporter,
            )
        elif (
            action
            in {
                TimelineActionName.NETWORK_LAG_START.value,
                TimelineActionName.NETWORK_LAG_COMMIT.value,
            }
            and ProfileName.NETWORK_FS_LAG.value not in profiles
        ):
            _emit_required_profile(
                action=str(action),
                profile=ProfileName.NETWORK_FS_LAG.value,
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
