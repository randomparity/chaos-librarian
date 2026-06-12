"""Rule: create_sidecar authored content must be synthesizable.

Subtitle ``create_sidecar`` events use the shared subtitle recipe matrix; an
out-of-set codec/source/encoding raises E_MATERIALIZE_UNSUPPORTED — the same
code the declared-subtitle path (``materialize_media_matrix``) raises for the
analogous combo. NFO ``body`` (any non-empty UTF-8 string) and poster
``media_type`` (a closed enum) are always synthesizable, so they need no
materialize check here.

A poster ``image_format`` (#118) selects the synthesized image format; the ``to:``
extension must agree with it (png→.png, jpeg→.jpg/.jpeg, webp→.webp) so the
recorded sidecar path stays honest about the bytes — a mismatch raises the same
E_MATERIALIZE_UNSUPPORTED.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from chaos_librarian.contract.scenario import (
    SidecarKind,
    SubtitleCodec,
    SubtitleEncoding,
    SubtitleSource,
    TimelineActionName,
)
from chaos_librarian.validation.codes import E_MATERIALIZE_UNSUPPORTED
from chaos_librarian.validation.rules.core.raw_helpers import (
    Reporter,
    _enum,
    _iter_timeline_events,
)
from chaos_librarian.validation.rules.media._subtitle_recipe import CREATE_SIDECAR_SUBTITLE_MATRIX

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
        codec = _enum(SubtitleCodec, event.get("codec") or SubtitleCodec.SRT.value)
        source = _enum(SubtitleSource, event.get("source") or SubtitleSource.GENERATED_SRT.value)
        encoding = _enum(SubtitleEncoding, event.get("encoding") or SubtitleEncoding.UTF8.value)
        if codec is None or source is None:
            continue  # Pydantic owns the type checks
        allowed = CREATE_SIDECAR_SUBTITLE_MATRIX.get((codec, source))
        if allowed is None:
            reporter.error(
                code=E_MATERIALIZE_UNSUPPORTED,
                message=(
                    f"create_sidecar subtitle codec/source ({codec.value!r}, {source.value!r}) "
                    "is not synthesizable by the timeline event"
                ),
                loc=("timeline", index, "codec"),
            )
            continue
        if encoding is not None and encoding not in allowed:
            reporter.error(
                code=E_MATERIALIZE_UNSUPPORTED,
                message=f"create_sidecar subtitle encoding {encoding.value!r} is not supported",
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
