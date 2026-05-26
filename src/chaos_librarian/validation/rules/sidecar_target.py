"""Rule: validate sidecar references — 3 codes share one (asset_id, path) projection.

Tracks a per-timeline-step ``(asset_id, path) -> kind`` projection
seeded with each asset's declared subtitles (mode=sidecar) and updated
by create_sidecar / extract_subtitle (insert) and remove_sidecar /
embed_subtitle (delete).

Emits:
- E_SIDECAR_TARGET_UNKNOWN: remove/update/embed reference a sidecar that
  isn't in the projection at that point in the timeline.
- E_SIDECAR_KIND_MISMATCH: embed_subtitle references a non-subtitle.
- E_SIDECAR_PATH_COLLISION: extract_subtitle.to lands on a live sidecar
  path (declared or runtime-created).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import SidecarKind, TimelineActionName
from chaos_librarian.validation.codes import (
    E_SIDECAR_KIND_MISMATCH,
    E_SIDECAR_PATH_COLLISION,
    E_SIDECAR_TARGET_UNKNOWN,
)
from chaos_librarian.validation.rules._common import (
    Reporter,
    _iter_timeline_events,
    iter_declared_sidecars,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_sidecar_target"]

_Projection = dict[tuple[str, str], tuple[str, str | None]]
"""``(asset_id, path) -> (kind, language)``.

``language`` is ``None`` for poster/NFO rows. Subtitle rows carry it so
``_handle_create_sidecar`` can mirror the engine's ``(asset, language)``
dedup (#63 finding #2): the engine drops any prior subtitle row matching
the new event's ``(asset, language)`` regardless of path, so a scenario
that declares a rendered sidecar path and then ``create_sidecar`` writes
a different subtitle path must invalidate the declared row in the
projection too. Without this, embed/remove referencing the declared path
validates clean but crashes the engine.
"""


def rule_sidecar_target(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Walk timeline; maintain ``(asset_id, path) -> kind``; emit 3 codes.

    See module docstring for the precise contract.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    projection = _seed_projection_from_declared(raw)
    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        target = event.get("target")
        if not isinstance(action, str) or not isinstance(target, str):
            continue
        if action == TimelineActionName.CREATE_SIDECAR:
            _handle_create_sidecar(event, target=target, projection=projection)
        elif action == TimelineActionName.EXTRACT_SUBTITLE:
            _handle_extract_subtitle(
                event,
                idx=idx,
                target=target,
                projection=projection,
                reporter=reporter,
            )
        elif action == TimelineActionName.EMBED_SUBTITLE:
            _handle_embed_subtitle(
                event,
                idx=idx,
                target=target,
                projection=projection,
                reporter=reporter,
            )
        elif action == TimelineActionName.REMOVE_SIDECAR:
            _handle_remove_sidecar(
                event,
                idx=idx,
                target=target,
                projection=projection,
                reporter=reporter,
            )
        elif action == TimelineActionName.UPDATE_SIDECAR:
            _handle_update_sidecar(
                event,
                idx=idx,
                target=target,
                projection=projection,
                reporter=reporter,
            )


def _handle_create_sidecar(
    event: Mapping[str, object],
    *,
    target: str,
    projection: _Projection,
) -> None:
    """Insert ``(target, to) -> (kind, language)`` for a well-shaped event.

    Subtitle creates additionally drop any existing subtitle entry on
    ``target`` that matches the new event's ``language`` regardless of
    path. The engine does the same in ``_handle_create_sidecar`` (removes
    every ``ManifestSidecar`` row keyed on ``(asset, "subtitle",
    language)``); validating without that dedup let a scenario like
    "declared rendered sidecar + create_sidecar to movies/a0/en.srt +
    embed declared sidecar" pass shape validation only to fail at runtime
    with a bare ``KeyError`` from the engine.
    """
    to = event.get("to")
    kind = event.get("kind", SidecarKind.SUBTITLE.value)
    if not isinstance(to, str) or not isinstance(kind, str):
        return
    raw_language = event.get("language")
    language = raw_language if isinstance(raw_language, str) else None
    if kind == SidecarKind.SUBTITLE.value and language is not None:
        for existing_key in [
            key
            for key, value in projection.items()
            if key[0] == target and value[0] == SidecarKind.SUBTITLE.value and value[1] == language
        ]:
            del projection[existing_key]
    projection[(target, to)] = (kind, language)


def _handle_extract_subtitle(
    event: Mapping[str, object],
    *,
    idx: int,
    target: str,
    projection: _Projection,
    reporter: Reporter,
) -> None:
    """Emit E_SIDECAR_PATH_COLLISION or insert (target, to) -> subtitle."""
    to = event.get("to")
    if not isinstance(to, str):
        return
    if (target, to) in projection:
        reporter.error(
            code=E_SIDECAR_PATH_COLLISION,
            message=(
                f"extract_subtitle.to {to!r} collides with an existing sidecar on asset {target!r}"
            ),
            loc=("timeline", idx, "to"),
        )
    else:
        raw_language = event.get("language")
        language = raw_language if isinstance(raw_language, str) else None
        projection[(target, to)] = (SidecarKind.SUBTITLE.value, language)


def _handle_embed_subtitle(
    event: Mapping[str, object],
    *,
    idx: int,
    target: str,
    projection: _Projection,
    reporter: Reporter,
) -> None:
    """Emit _TARGET_UNKNOWN, _KIND_MISMATCH, or consume the sidecar."""
    sidecar_path = event.get("sidecar_path")
    if not isinstance(sidecar_path, str):
        return
    entry = projection.get((target, sidecar_path))
    if entry is None:
        reporter.error(
            code=E_SIDECAR_TARGET_UNKNOWN,
            message=(
                f"embed_subtitle references unknown sidecar {sidecar_path!r} on asset {target!r}"
            ),
            loc=("timeline", idx, "sidecar_path"),
        )
        return
    kind, _language = entry
    if kind != SidecarKind.SUBTITLE.value:
        reporter.error(
            code=E_SIDECAR_KIND_MISMATCH,
            message=(
                f"embed_subtitle references {kind!r} sidecar {sidecar_path!r}; subtitle expected"
            ),
            loc=("timeline", idx, "sidecar_path"),
        )
    else:
        # embed consumes the sidecar — remove from projection.
        del projection[(target, sidecar_path)]


def _handle_remove_sidecar(
    event: Mapping[str, object],
    *,
    idx: int,
    target: str,
    projection: _Projection,
    reporter: Reporter,
) -> None:
    """Emit E_SIDECAR_TARGET_UNKNOWN or delete (target, sidecar_path)."""
    sidecar_path = event.get("sidecar_path")
    if not isinstance(sidecar_path, str):
        return
    if (target, sidecar_path) not in projection:
        reporter.error(
            code=E_SIDECAR_TARGET_UNKNOWN,
            message=(
                f"remove_sidecar references unknown sidecar {sidecar_path!r} on asset {target!r}"
            ),
            loc=("timeline", idx, "sidecar_path"),
        )
    else:
        del projection[(target, sidecar_path)]


def _handle_update_sidecar(
    event: Mapping[str, object],
    *,
    idx: int,
    target: str,
    projection: _Projection,
    reporter: Reporter,
) -> None:
    """Emit E_SIDECAR_TARGET_UNKNOWN; update_sidecar does not change projection."""
    sidecar_path = event.get("sidecar_path")
    if isinstance(sidecar_path, str) and (target, sidecar_path) not in projection:
        reporter.error(
            code=E_SIDECAR_TARGET_UNKNOWN,
            message=(
                f"update_sidecar references unknown sidecar {sidecar_path!r} on asset {target!r}"
            ),
            loc=("timeline", idx, "sidecar_path"),
        )


def _seed_projection_from_declared(raw: Mapping[str, object]) -> _Projection:
    """Seed (asset_id, rendered_path) -> kind for every declared subtitle."""
    projection: _Projection = {}
    for sidecar in iter_declared_sidecars(raw):
        projection[(sidecar.asset_id, sidecar.path)] = (sidecar.kind, sidecar.language)
    return projection
