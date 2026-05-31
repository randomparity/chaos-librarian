"""Rule: extract_subtitle on an asset with no declared subtitle track.

The materializer's extract handler does ``ffmpeg -map 0:s:m:language``
(falling back to ``-map 0:s:0``); if the asset has no subtitle stream
at all, ffmpeg fails at runtime. This rule rejects scenarios where the
asset has no declared subtitle track of EITHER mode (embedded or
sidecar). A sidecar declaration counts because a prior embed_subtitle
in the timeline may have folded it into the asset.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation.codes import E_EXTRACT_TRACK_UNKNOWN
from chaos_librarian.validation.rules.hierarchy_walkers import iter_assets_with_loc
from chaos_librarian.validation.rules.raw_helpers import (
    Reporter,
    _as_list,
    _iter_timeline_events,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_extract_track_unknown"]


def rule_extract_track_unknown(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Emit E_EXTRACT_TRACK_UNKNOWN for extract_subtitle on a subtitle-less asset."""
    reporter = Reporter(collector=collector, line_index=line_index)
    assets_with_subtitle_tracks = _assets_with_subtitle_tracks(raw)
    for idx, event in _iter_timeline_events(raw):
        if event.get("action") != TimelineActionName.EXTRACT_SUBTITLE:
            continue
        target = event.get("target")
        if not isinstance(target, str):
            continue
        if target not in assets_with_subtitle_tracks:
            # Unknown asset is rule_target_unknown's job; only emit when
            # the asset exists but has no subtitle tracks.
            continue
        if not assets_with_subtitle_tracks[target]:
            reporter.error(
                code=E_EXTRACT_TRACK_UNKNOWN,
                message=(
                    f"extract_subtitle on asset {target!r} which declares no "
                    "subtitle tracks (embedded or sidecar)"
                ),
                loc=("timeline", idx, "target"),
            )


def _assets_with_subtitle_tracks(raw: Mapping[str, object]) -> dict[str, bool]:
    """asset_id -> True iff the asset declares at least one subtitle track."""
    out: dict[str, bool] = {}
    for asset, _ in iter_assets_with_loc(raw):
        asset_id = asset.get("id")
        if not isinstance(asset_id, str):
            continue
        subs = _as_list(asset.get("subtitles")) or []
        out[asset_id] = bool(subs)
    return out
