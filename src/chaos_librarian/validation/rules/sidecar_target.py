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
    _as_list,
    _as_mapping,
    _iter_timeline_events,
    _list_at_path,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_sidecar_target"]

_Projection = dict[tuple[str, str], str]


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
    """Insert (target, to) -> kind for a well-shaped create_sidecar event."""
    to = event.get("to")
    kind = event.get("kind", SidecarKind.SUBTITLE.value)
    if isinstance(to, str) and isinstance(kind, str):
        projection[(target, to)] = kind


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
        projection[(target, to)] = SidecarKind.SUBTITLE.value


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
    kind = projection.get((target, sidecar_path))
    if kind is None:
        reporter.error(
            code=E_SIDECAR_TARGET_UNKNOWN,
            message=(
                f"embed_subtitle references unknown sidecar {sidecar_path!r} on asset {target!r}"
            ),
            loc=("timeline", idx, "sidecar_path"),
        )
    elif kind != SidecarKind.SUBTITLE.value:
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
    """Seed (asset_id, path) -> kind for every declared subtitle.

    Declared subtitles use the path convention <asset_id>.<language>.srt
    (per scenario v5 §"Declared-sidecar path convention").
    """
    projection: _Projection = {}
    for work_obj in _list_at_path(raw, ("works",)) or []:
        work = _as_mapping(work_obj)
        if work is None:
            continue
        for variant_obj in _as_list(work.get("variants")) or []:
            variant = _as_mapping(variant_obj)
            if variant is None:
                continue
            bundle = _as_mapping(variant.get("bundle"))
            if bundle is None:
                continue
            for asset_obj in _as_list(bundle.get("assets")) or []:
                _seed_from_asset(asset_obj, projection=projection)
    return projection


def _seed_from_asset(
    asset_obj: object,
    *,
    projection: _Projection,
) -> None:
    """Insert one entry per declared sidecar-mode subtitle on one asset."""
    asset = _as_mapping(asset_obj)
    if asset is None:
        return
    asset_id = asset.get("id")
    if not isinstance(asset_id, str):
        return
    for sub_obj in _as_list(asset.get("subtitles")) or []:
        sub = _as_mapping(sub_obj)
        if sub is None:
            continue
        if sub.get("mode") != "sidecar":
            continue
        language = sub.get("language")
        if not isinstance(language, str):
            continue
        projection[(asset_id, f"{asset_id}.{language}.srt")] = SidecarKind.SUBTITLE.value
