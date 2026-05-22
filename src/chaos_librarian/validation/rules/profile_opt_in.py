"""Rule: corruption actions require the malformed-media profile."""

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
    if ProfileName.MALFORMED_MEDIA.value in profiles:
        return
    for idx, event in _iter_timeline_events(raw):
        if event.get("action") != TimelineActionName.CORRUPT_CONTAINER_HEADER.value:
            continue
        event_id = event.get("id")
        suffix = f" for event {event_id!r}" if isinstance(event_id, str) else ""
        reporter.error(
            code=E_PROFILE_REQUIRED,
            message=(
                "corrupt_container_header requires profile "
                f"{ProfileName.MALFORMED_MEDIA.value!r}{suffix}"
            ),
            loc=("timeline", idx, "action"),
        )
