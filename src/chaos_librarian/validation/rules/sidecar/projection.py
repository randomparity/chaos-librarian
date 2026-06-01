"""Sidecar projection helpers shared by validation rules."""

from __future__ import annotations

from dataclasses import dataclass

from chaos_librarian.contract.scenario import SidecarKind
from chaos_librarian.path_rendering import render_declared_sidecar_path
from chaos_librarian.validation.rules.core.raw_helpers import _RawMapping
from chaos_librarian.validation.rules.hierarchy.projection import HierarchyMutation
from chaos_librarian.validation.rules.hierarchy.walkers import iter_declared_sidecars


@dataclass(frozen=True, slots=True)
class SidecarProjectionRow:
    """One row of the ``(asset_id, path) -> sidecar`` projection.

    Shared by ``rule_sidecar_target`` (target-existence checks) and
    ``rule_timeline_lifecycle`` (lifecycle checks) so the declared seed,
    create dedup, and hierarchy move stay consistent across both. The two
    rules layer their own emissions on top of this common state.
    """

    kind: str
    language: str | None
    renderer_derived: bool
    codec: str = "srt"
    source: str = "generated_srt"
    encoding: str = "utf8"
    timing_profile: str = "normal"

    @property
    def uses_default_subtitle_recipe(self) -> bool:
        return (
            self.kind == SidecarKind.SUBTITLE.value
            and self.codec == "srt"
            and self.source == "generated_srt"
            and self.encoding == "utf8"
            and self.timing_profile == "normal"
        )


SidecarProjection = dict[tuple[str, str], SidecarProjectionRow]
"""``(asset_id, path) -> SidecarProjectionRow``, evolved as the timeline walks."""


def seed_sidecar_projection(raw: _RawMapping) -> SidecarProjection:
    """Seed ``(asset_id, rendered_path) -> row`` for every declared subtitle."""
    return {
        (sidecar.asset_id, sidecar.path): SidecarProjectionRow(
            kind=sidecar.kind,
            language=sidecar.language,
            renderer_derived=True,
            codec=sidecar.codec,
            source=sidecar.source,
            encoding=sidecar.encoding,
            timing_profile=sidecar.timing_profile,
        )
        for sidecar in iter_declared_sidecars(raw)
    }


def drop_subtitle_rows_for_language(
    projection: SidecarProjection, *, target: str, language: str
) -> None:
    """Drop every subtitle row on ``target`` matching ``language``.

    Mirrors the engine's ``(asset, language)`` dedup: a create that names a
    language drops any prior subtitle row for that language regardless of path.
    """
    for key in [
        key
        for key, value in projection.items()
        if key[0] == target
        and value.kind == SidecarKind.SUBTITLE.value
        and value.language == language
    ]:
        del projection[key]


def project_sidecars_for_hierarchy_mutation(
    mutation: HierarchyMutation, projection: SidecarProjection
) -> None:
    """Move renderer-derived declared subtitle rows alongside their media path."""
    for asset_id, (old_media_path, new_media_path) in mutation.path_changes.items():
        if old_media_path is None or new_media_path is None:
            continue
        for key, value in list(projection.items()):
            key_asset_id, sidecar_path = key
            if key_asset_id != asset_id:
                continue
            if value.kind != SidecarKind.SUBTITLE.value or not value.renderer_derived:
                continue
            if value.language is None:
                continue
            try:
                old_sidecar_path = render_declared_sidecar_path(
                    old_media_path, value.language, codec=value.codec
                )
                new_sidecar_path = render_declared_sidecar_path(
                    new_media_path, value.language, codec=value.codec
                )
            except ValueError:
                continue
            if sidecar_path == old_sidecar_path:
                del projection[key]
                projection[(asset_id, new_sidecar_path)] = value
