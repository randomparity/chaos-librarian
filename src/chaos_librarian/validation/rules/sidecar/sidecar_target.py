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
    E_MATERIALIZE_UNSUPPORTED,
    E_SIDECAR_KIND_MISMATCH,
    E_SIDECAR_PATH_COLLISION,
    E_SIDECAR_TARGET_UNKNOWN,
)
from chaos_librarian.validation.rules.core.raw_helpers import (
    Reporter,
    _iter_timeline_events,
)
from chaos_librarian.validation.rules.hierarchy.projection import (
    build_hierarchy_projection,
    is_hierarchy_action,
)
from chaos_librarian.validation.rules.sidecar.projection import (
    SidecarProjection,
    SidecarProjectionRow,
    drop_subtitle_rows_for_language,
    project_sidecars_for_hierarchy_mutation,
    seed_sidecar_projection,
)

if TYPE_CHECKING:
    from chaos_librarian.validation.reporting import IssueCollector
    from chaos_librarian.validation.scenario_io import LineIndex

__all__ = ["rule_sidecar_target"]


def rule_sidecar_target(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Walk timeline; maintain ``(asset_id, path) -> kind``; emit 3 codes.

    See module docstring for the precise contract.
    """
    reporter = Reporter(collector=collector, line_index=line_index)
    projection = seed_sidecar_projection(raw)
    hierarchy_projection = build_hierarchy_projection(raw)
    pending_slow_copies: dict[str, tuple[str, str]] = {}
    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        target = event.get("target")
        if not isinstance(action, str):
            continue
        if is_hierarchy_action(action):
            mutation = hierarchy_projection.apply(event)
            project_sidecars_for_hierarchy_mutation(mutation, projection)
            continue
        hierarchy_projection.project_non_hierarchy_event(event, pending_slow_copies)
        if not isinstance(target, str):
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
    projection: SidecarProjection,
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
        drop_subtitle_rows_for_language(projection, target=target, language=language)
    projection[(target, to)] = SidecarProjectionRow(
        kind=kind,
        language=language,
        renderer_derived=False,
    )


def _handle_extract_subtitle(
    event: Mapping[str, object],
    *,
    idx: int,
    target: str,
    projection: SidecarProjection,
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
        projection[(target, to)] = SidecarProjectionRow(
            kind=SidecarKind.SUBTITLE.value,
            language=language,
            renderer_derived=False,
        )


def _lookup_sidecar_or_error(
    event: Mapping[str, object],
    *,
    action: str,
    idx: int,
    target: str,
    projection: SidecarProjection,
    reporter: Reporter,
) -> tuple[str, SidecarProjectionRow] | None:
    """Resolve ``(sidecar_path, row)`` or emit E_SIDECAR_TARGET_UNKNOWN.

    Returns None when ``sidecar_path`` is missing/non-str (the shape pass owns
    that) or when ``(target, sidecar_path)`` is absent from the projection.
    """
    sidecar_path = event.get("sidecar_path")
    if not isinstance(sidecar_path, str):
        return None
    entry = projection.get((target, sidecar_path))
    if entry is None:
        reporter.error(
            code=E_SIDECAR_TARGET_UNKNOWN,
            message=f"{action} references unknown sidecar {sidecar_path!r} on asset {target!r}",
            loc=("timeline", idx, "sidecar_path"),
        )
        return None
    return sidecar_path, entry


def _handle_embed_subtitle(
    event: Mapping[str, object],
    *,
    idx: int,
    target: str,
    projection: SidecarProjection,
    reporter: Reporter,
) -> None:
    """Emit _TARGET_UNKNOWN, _KIND_MISMATCH, or consume the sidecar."""
    resolved = _lookup_sidecar_or_error(
        event,
        action="embed_subtitle",
        idx=idx,
        target=target,
        projection=projection,
        reporter=reporter,
    )
    if resolved is None:
        return
    sidecar_path, entry = resolved
    if entry.kind != SidecarKind.SUBTITLE.value:
        reporter.error(
            code=E_SIDECAR_KIND_MISMATCH,
            message=(
                f"embed_subtitle references {entry.kind!r} sidecar "
                f"{sidecar_path!r}; subtitle expected"
            ),
            loc=("timeline", idx, "sidecar_path"),
        )
    elif not entry.uses_default_subtitle_recipe:
        _report_unsupported_subtitle_recipe(
            action="embed_subtitle",
            sidecar_path=sidecar_path,
            loc=("timeline", idx, "sidecar_path"),
            reporter=reporter,
        )
    else:
        # embed consumes the sidecar — remove from projection.
        del projection[(target, sidecar_path)]


def _handle_remove_sidecar(
    event: Mapping[str, object],
    *,
    idx: int,
    target: str,
    projection: SidecarProjection,
    reporter: Reporter,
) -> None:
    """Emit E_SIDECAR_TARGET_UNKNOWN or delete (target, sidecar_path)."""
    resolved = _lookup_sidecar_or_error(
        event,
        action="remove_sidecar",
        idx=idx,
        target=target,
        projection=projection,
        reporter=reporter,
    )
    if resolved is None:
        return
    sidecar_path, _ = resolved
    del projection[(target, sidecar_path)]


def _handle_update_sidecar(
    event: Mapping[str, object],
    *,
    idx: int,
    target: str,
    projection: SidecarProjection,
    reporter: Reporter,
) -> None:
    """Emit E_SIDECAR_TARGET_UNKNOWN; update_sidecar does not change projection."""
    resolved = _lookup_sidecar_or_error(
        event,
        action="update_sidecar",
        idx=idx,
        target=target,
        projection=projection,
        reporter=reporter,
    )
    if resolved is None:
        return
    sidecar_path, entry = resolved
    if entry.kind == SidecarKind.SUBTITLE.value and not entry.uses_default_subtitle_recipe:
        _report_unsupported_subtitle_recipe(
            action="update_sidecar",
            sidecar_path=sidecar_path,
            loc=("timeline", idx, "sidecar_path"),
            reporter=reporter,
        )


def _report_unsupported_subtitle_recipe(
    *,
    action: str,
    sidecar_path: str,
    loc: tuple[str | int, ...],
    reporter: Reporter,
) -> None:
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message=f"{action} does not support non-default subtitle recipe {sidecar_path!r}",
        loc=loc,
    )
