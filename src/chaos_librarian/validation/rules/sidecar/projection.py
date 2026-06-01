"""Sidecar projection helpers shared by validation rules."""

from __future__ import annotations

from dataclasses import dataclass

from chaos_librarian.contract.scenario import (
    SidecarKind,
    SubtitleCodec,
    SubtitleEncoding,
    SubtitleSource,
    SubtitleTimingProfile,
)
from chaos_librarian.path_rendering import render_declared_sidecar_path
from chaos_librarian.validation.rules.core.raw_helpers import _enum, _RawMapping
from chaos_librarian.validation.rules.hierarchy.projection import HierarchyMutation
from chaos_librarian.validation.rules.hierarchy.rendering_projection import iter_declared_sidecars


@dataclass(frozen=True, slots=True)
class SidecarProjectionRow:
    """One row of the ``(asset_id, path) -> sidecar`` projection.

    Shared by ``rule_sidecar_target`` (target-existence checks) and
    ``rule_timeline_lifecycle`` (lifecycle checks) so the declared seed,
    create dedup, and hierarchy move stay consistent across both. The two
    rules layer their own emissions on top of this common state.
    """

    kind: SidecarKind
    language: str | None
    renderer_derived: bool
    codec: SubtitleCodec = SubtitleCodec.SRT
    source: SubtitleSource = SubtitleSource.GENERATED_SRT
    encoding: SubtitleEncoding = SubtitleEncoding.UTF8
    timing_profile: SubtitleTimingProfile = SubtitleTimingProfile.NORMAL

    @property
    def uses_default_subtitle_recipe(self) -> bool:
        return (
            self.kind is SidecarKind.SUBTITLE
            and self.codec is SubtitleCodec.SRT
            and self.source is SubtitleSource.GENERATED_SRT
            and self.encoding is SubtitleEncoding.UTF8
            and self.timing_profile is SubtitleTimingProfile.NORMAL
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


def create_sidecar_projection_row(event: _RawMapping) -> SidecarProjectionRow | None:
    kind = _enum(SidecarKind, event.get("kind", SidecarKind.SUBTITLE.value))
    if kind is None:
        return None
    language = _language_from_event(event)
    if kind is not SidecarKind.SUBTITLE:
        return SidecarProjectionRow(
            kind=kind,
            language=language,
            renderer_derived=False,
        )
    codec = _subtitle_codec_from_event(event)
    source = _subtitle_source_from_event(event)
    encoding = _subtitle_encoding_from_event(event)
    if codec is None or source is None or encoding is None:
        return None
    return SidecarProjectionRow(
        kind=kind,
        language=language,
        renderer_derived=False,
        codec=codec,
        source=source,
        encoding=encoding,
    )


def extracted_subtitle_projection_row(event: _RawMapping) -> SidecarProjectionRow:
    return SidecarProjectionRow(
        kind=SidecarKind.SUBTITLE,
        language=_language_from_event(event),
        renderer_derived=False,
    )


def _language_from_event(event: _RawMapping) -> str | None:
    language = event.get("language")
    return language if isinstance(language, str) else None


def _subtitle_codec_from_event(event: _RawMapping) -> SubtitleCodec | None:
    value = event.get("codec")
    if value is None:
        return SubtitleCodec.SRT
    return _enum(SubtitleCodec, value)


def _subtitle_source_from_event(event: _RawMapping) -> SubtitleSource | None:
    value = event.get("source")
    if value is None:
        return SubtitleSource.GENERATED_SRT
    return _enum(SubtitleSource, value)


def _subtitle_encoding_from_event(event: _RawMapping) -> SubtitleEncoding | None:
    value = event.get("encoding")
    if value is None:
        return SubtitleEncoding.UTF8
    return _enum(SubtitleEncoding, value)


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
        if key[0] == target and value.kind is SidecarKind.SUBTITLE and value.language == language
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
            if value.kind is not SidecarKind.SUBTITLE or not value.renderer_derived:
                continue
            if value.language is None:
                continue
            try:
                old_sidecar_path = render_declared_sidecar_path(
                    old_media_path, value.language, codec=value.codec.value
                )
                new_sidecar_path = render_declared_sidecar_path(
                    new_media_path, value.language, codec=value.codec.value
                )
            except ValueError:
                continue
            if sidecar_path == old_sidecar_path:
                del projection[key]
                projection[(asset_id, new_sidecar_path)] = value
