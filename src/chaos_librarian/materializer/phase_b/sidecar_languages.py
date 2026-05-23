"""Timeline sidecar-language helpers for materializer entry points."""

from __future__ import annotations

from chaos_librarian.contract.scenario import CreateSidecarEvent, Scenario, SidecarKind
from chaos_librarian.errors import ChaosLibrarianValueError


def timeline_sidecar_languages(scenario: Scenario) -> dict[str, frozenset[str]]:
    """Map each asset id to subtitle languages created by the timeline.

    Materializer phase A uses this to skip declared subtitles that a timeline
    ``create_sidecar`` will overwrite, avoiding orphaned declared-sidecar
    files when the manifest collapses duplicate ``(asset_id, language)`` rows.
    """
    per_asset: dict[str, set[str]] = {}
    for event in scenario.timeline:
        if not isinstance(event, CreateSidecarEvent):
            continue
        if event.kind is not SidecarKind.SUBTITLE:
            continue
        if event.language is None:
            raise ChaosLibrarianValueError(
                f"subtitle sidecar event {event.id!r} for asset {event.target!r} "
                "is missing language"
            )
        per_asset.setdefault(event.target, set()).add(event.language)
    return {asset_id: frozenset(langs) for asset_id, langs in per_asset.items()}
