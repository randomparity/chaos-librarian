"""Rule: profile-specific actions require their matching profile labels."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.profile_policy import REQUIRED_PROFILES_BY_ACTION
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_PROFILE_REQUIRED
from chaos_librarian.validation.rules.core.raw_helpers import (
    Reporter,
    _iter_timeline_events,
)

if TYPE_CHECKING:
    from chaos_librarian.validation.reporting import IssueCollector
    from chaos_librarian.validation.scenario_io import LineIndex


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
        try:
            action_name = TimelineActionName(action)
        except ValueError:
            continue
        required_profile = REQUIRED_PROFILES_BY_ACTION.get(action_name)
        if required_profile is not None and required_profile.value not in profiles:
            _emit_required_profile(
                action=action,
                profile=required_profile.value,
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
