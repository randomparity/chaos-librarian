"""Rule 10: E_SIDECAR_LANGUAGE_INVALID — keep manifest sidecar keys unique.

The manifest v3 keys ``ManifestSidecar`` lookups on ``(asset_id, language)``.
Duplicate ``(target, language)`` across ``create_sidecar`` events in the
same scenario would produce two sidecar rows with the same composite key,
leaving the key ambiguous; this rule rejects that.

The rule deliberately does NOT require the timeline's ``language`` to
appear in ``asset.subtitles[*].language``. A timeline-only sidecar (no
declared subtitle) is legal; so is overriding a declared subtitle with a
timeline ``create_sidecar`` (phase A defers to phase B by skipping
languages the timeline will write).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_SIDECAR_LANGUAGE_INVALID
from chaos_librarian.validation.rules.raw_helpers import (
    Reporter,
    _iter_timeline_events,
    first_or_duplicate,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.reporting import IssueCollector

__all__ = ["rule_sidecar_language_consistent"]


def rule_sidecar_language_consistent(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject duplicate ``(target, language)`` ``create_sidecar`` events.

    See module docstring for the rationale and the deliberately-allowed
    cases (timeline-only sidecars, overrides of declared subtitles).
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    seen: dict[tuple[str, str], int] = {}
    for index, event in _iter_timeline_events(raw):
        if event.get("action") != TimelineActionName.CREATE_SIDECAR:
            continue
        target = event.get("target")
        language = event.get("language")
        if not isinstance(target, str) or not isinstance(language, str):
            continue  # Pydantic owns the type checks
        key = (target, language)
        first_index = first_or_duplicate(seen, key, index)
        if first_index is not None:
            reporter.error(
                code=E_SIDECAR_LANGUAGE_INVALID,
                message=(
                    f"duplicate create_sidecar for ({target!r}, {language!r}); "
                    f"first event was at index {first_index}"
                ),
                loc=("timeline", index, "language"),
            )
