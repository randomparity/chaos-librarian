"""Rule: create_sidecar authored content must be synthesizable.

Subtitle ``create_sidecar`` events are SRT-only in v1; an ass/ssa codec or an
out-of-set encoding raises E_MATERIALIZE_UNSUPPORTED — the same code the
declared-subtitle path (``materialize_media_matrix``) raises for the analogous
combo. NFO ``body`` (any non-empty UTF-8 string) and poster ``media_type`` (a
closed enum) are always synthesizable, so they need no materialize check here.

A poster ``image_format`` (#118) selects the synthesized image format; the ``to:``
extension must agree with it (png→.png, jpeg→.jpg/.jpeg, webp→.webp) so the
recorded sidecar path stays honest about the bytes — a mismatch raises the same
E_MATERIALIZE_UNSUPPORTED.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from chaos_librarian.contract.scenario import SidecarKind, TimelineActionName
from chaos_librarian.validation.codes import E_MATERIALIZE_UNSUPPORTED
from chaos_librarian.validation.rules._subtitle_recipe import CREATE_SIDECAR_SUBTITLE_MATRIX
from chaos_librarian.validation.rules.raw_helpers import (
    Reporter,
    _iter_timeline_events,
)

if TYPE_CHECKING:
    from chaos_librarian.validation.reporting import IssueCollector
    from chaos_librarian.validation.scenario_io import LineIndex

__all__ = ["rule_create_sidecar_content"]

_POSTER_EXTENSIONS_BY_FORMAT: Final[dict[str, frozenset[str]]] = {
    "png": frozenset({"png"}),
    "jpeg": frozenset({"jpg", "jpeg"}),
    "webp": frozenset({"webp"}),
}


def rule_create_sidecar_content(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject create_sidecar combos the materializer cannot synthesize."""
    reporter = Reporter(collector=collector, line_index=line_index)
    for index, event in _iter_timeline_events(raw):
        if event.get("action") != TimelineActionName.CREATE_SIDECAR:
            continue
        kind = event.get("kind", SidecarKind.SUBTITLE.value)
        if kind == SidecarKind.POSTER.value:
            _check_poster_image_format(event, index, reporter)
            continue
        if kind != SidecarKind.SUBTITLE.value:
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


def _check_poster_image_format(
    event: Mapping[str, object],
    index: int,
    reporter: Reporter,
) -> None:
    """Reject a poster whose ``to:`` extension disagrees with ``image_format``."""
    image_format = event.get("image_format")
    if not isinstance(image_format, str):
        return  # None ⇒ today's behavior; Pydantic owns enum validity
    allowed = _POSTER_EXTENSIONS_BY_FORMAT.get(image_format)
    if allowed is None:
        return  # Pydantic owns enum validity
    to = event.get("to")
    if not isinstance(to, str):
        return  # Pydantic owns the type check
    extension = to.rsplit(".", 1)[-1].lower() if "." in to else ""
    if extension in allowed:
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message=(
            f"poster image_format {image_format!r} requires a matching {to!r} extension "
            f"({'/'.join(sorted(allowed))})"
        ),
        loc=("timeline", index, "image_format"),
    )
