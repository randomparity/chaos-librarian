"""Rule 10: E_SIDECAR_LANGUAGE_INVALID — keep manifest sidecar keys unique.

The manifest v3 keys ``ManifestSidecar`` lookups on ``(asset_id, language)``.
Two failure modes break that invariant:

1. Duplicate ``(target, language)`` across ``create_sidecar`` events in the
   same scenario would produce two sidecar rows with the same composite
   key, leaving the key ambiguous.
2. ``language`` that doesn't appear in the target asset's declared
   ``subtitles[*].language`` is a typo or oversight — the materializer
   hashes subtitles from ``asset.subtitles`` by declared language, so a
   mismatched event-language would either leave the plan-created row
   hashless or append a second row for the same on-disk file.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.validation.codes import E_SIDECAR_LANGUAGE_INVALID
from chaos_librarian.validation.rules._common import (
    _as_list,
    _as_mapping,
    _iter_timeline_events,
)
from chaos_librarian.validation.rules.asset_path_safety import iter_assets_with_loc

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_sidecar_language_consistent"]


def rule_sidecar_language_consistent(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject ``create_sidecar`` events that break the manifest v3 key invariant.

    See module docstring for the two failure modes flagged.
    """
    declared_by_asset = _index_declared_languages(raw)

    seen: dict[tuple[str, str], int] = {}
    for index, event in _iter_timeline_events(raw):
        if event.get("action") != TimelineActionName.CREATE_SIDECAR:
            continue
        target = event.get("target")
        language = event.get("language")
        if not isinstance(target, str) or not isinstance(language, str):
            continue  # Pydantic owns the type checks
        key = (target, language)
        if key in seen:
            collector.add(
                code=E_SIDECAR_LANGUAGE_INVALID,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"duplicate create_sidecar for ({target!r}, {language!r}); "
                    f"first event was at index {seen[key]}"
                ),
                loc=("timeline", index, "language"),
                line_index=line_index,
            )
        else:
            seen[key] = index
        declared = declared_by_asset.get(target)
        if declared is not None and language not in declared:
            collector.add(
                code=E_SIDECAR_LANGUAGE_INVALID,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"create_sidecar language {language!r} not declared on "
                    f"target asset {target!r} (declared: {sorted(declared)!r})"
                ),
                loc=("timeline", index, "language"),
                line_index=line_index,
            )


def _index_declared_languages(raw: Mapping[str, object]) -> dict[str, set[str]]:
    """Build a lookup of declared subtitle languages per asset id."""
    declared_by_asset: dict[str, set[str]] = {}
    for asset, _loc in iter_assets_with_loc(raw):
        asset_id = asset.get("id")
        if not isinstance(asset_id, str):
            continue
        subs = _as_list(asset.get("subtitles")) or []
        languages: set[str] = set()
        for sub_obj in subs:
            sub = _as_mapping(sub_obj)
            if sub is None:
                continue
            lang = sub.get("language")
            if isinstance(lang, str):
                languages.add(lang)
        declared_by_asset[asset_id] = languages
    return declared_by_asset
