"""Rule: create_sidecar authored content must be synthesizable.

Subtitle ``create_sidecar`` events are SRT-only in v1; an ass/ssa codec or an
out-of-set encoding raises E_MATERIALIZE_UNSUPPORTED — the same code the
declared-subtitle path (``materialize_media_matrix``) raises for the analogous
combo. NFO ``body`` (any non-empty UTF-8 string) and poster ``media_type`` (a
closed enum) are always synthesizable, so they need no materialize check here.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import SidecarKind, TimelineActionName
from chaos_librarian.validation.codes import E_MATERIALIZE_UNSUPPORTED
from chaos_librarian.validation.rules._common import Reporter, _iter_timeline_events
from chaos_librarian.validation.rules._subtitle_recipe import CREATE_SIDECAR_SUBTITLE_MATRIX

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_create_sidecar_content"]


def rule_create_sidecar_content(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject create_sidecar subtitle combos the materializer cannot synthesize."""
    reporter = Reporter(collector=collector, line_index=line_index)
    for index, event in _iter_timeline_events(raw):
        if event.get("action") != TimelineActionName.CREATE_SIDECAR:
            continue
        if event.get("kind", SidecarKind.SUBTITLE.value) != SidecarKind.SUBTITLE.value:
            continue
        codec = event.get("codec") or "srt"
        source = event.get("source") or "generated_srt"
        encoding = event.get("encoding") or "utf8"
        if not isinstance(codec, str) or not isinstance(source, str):
            continue  # Pydantic owns the type checks
        allowed = CREATE_SIDECAR_SUBTITLE_MATRIX.get((codec, source))
        if allowed is None:
            reporter.error(
                code=E_MATERIALIZE_UNSUPPORTED,
                message=(
                    f"create_sidecar subtitle codec/source ({codec!r}, {source!r}) "
                    "is not synthesizable by the timeline event (SRT only)"
                ),
                loc=("timeline", index, "codec"),
            )
            continue
        if isinstance(encoding, str) and encoding not in allowed:
            reporter.error(
                code=E_MATERIALIZE_UNSUPPORTED,
                message=f"create_sidecar subtitle encoding {encoding!r} is not supported",
                loc=("timeline", index, "encoding"),
            )
