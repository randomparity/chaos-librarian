"""Rule 9: E_PATH_CONTAINMENT on rendered initial asset paths."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.path_rendering import (
    clean_display_component,
    render_asset_path,
    render_declared_sidecar_path,
)
from chaos_librarian.validation.codes import E_PATH_CONTAINMENT
from chaos_librarian.validation.rules._common import (
    RawAssetContext,
    Reporter,
    _as_list,
    _as_mapping,
    _Loc,
    iter_asset_contexts,
    primary_root_path,
    renderable_context_for,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_asset_id_container_safe"]


def rule_asset_id_container_safe(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject values that make rendered initial paths escape containment."""
    reporter = Reporter(collector=collector, line_index=line_index)
    root_path = primary_root_path(raw)
    if root_path is None:
        return
    for context in iter_asset_contexts(raw):
        renderable = renderable_context_for(context, root_path)
        if renderable is None:
            continue
        if not _check_display_fields(context, reporter):
            continue
        try:
            media_path = render_asset_path(renderable)
        except ValueError as error:
            reporter.error(
                code=E_PATH_CONTAINMENT,
                message=f"rendered asset path is invalid: {error}",
                loc=_render_error_loc(context, str(error)),
            )
            continue
        _check_declared_sidecar_paths(context.asset, context.asset_loc, media_path, reporter)


def _check_display_fields(context: RawAssetContext, reporter: Reporter) -> bool:
    is_valid = True
    for value, loc in _iter_rendered_display_fields(context):
        try:
            clean_display_component(value)
        except ValueError as error:
            reporter.error(
                code=E_PATH_CONTAINMENT,
                message=f"rendered display field is invalid: {error}",
                loc=loc,
            )
            is_valid = False
    return is_valid


def _iter_rendered_display_fields(context: RawAssetContext):
    yield from _maybe_str_loc(context.movie, "title", context.movie_loc)
    yield from _maybe_str_loc(context.series, "title", context.series_loc)
    yield from _maybe_str_loc(context.episode, "title", context.episode_loc)
    yield from _maybe_str_loc(context.artist, "name", context.artist_loc)
    yield from _maybe_str_loc(context.album, "title", context.album_loc)
    yield from _maybe_str_loc(context.track, "title", context.track_loc)
    yield from _maybe_str_loc(context.variant, "label", context.variant_loc)
    if context.bundle_asset_count > 1:
        yield from _maybe_str_loc(context.asset, "role", context.asset_loc)


def _maybe_str_loc(
    mapping: Mapping[str, object] | None,
    field_name: str,
    loc: _Loc | None,
):
    if mapping is None or loc is None:
        return
    value = mapping.get(field_name)
    if isinstance(value, str):
        yield value, (*loc, field_name)


def _check_declared_sidecar_paths(
    asset: Mapping[str, object],
    asset_loc: _Loc,
    media_path: str,
    reporter: Reporter,
) -> None:
    subtitles = _as_list(asset.get("subtitles"))
    if subtitles is None:
        return
    for sub_idx, sub_obj in enumerate(subtitles):
        subtitle = _as_mapping(sub_obj)
        if subtitle is None or subtitle.get("mode") != "sidecar":
            continue
        language = subtitle.get("language")
        if not isinstance(language, str):
            continue
        try:
            render_declared_sidecar_path(media_path, language)
        except ValueError as error:
            reporter.error(
                code=E_PATH_CONTAINMENT,
                message=f"rendered declared sidecar path is invalid: {error}",
                loc=(*asset_loc, "subtitles", sub_idx, "language"),
            )


def _render_error_loc(context: RawAssetContext, message: str) -> _Loc:
    if "asset_container" in message:
        return (*context.asset_loc, "container")
    specific_loc = _specific_display_error_loc(context, message)
    if specific_loc is not None:
        return specific_loc
    return _default_display_error_loc(context)


def _specific_display_error_loc(context: RawAssetContext, message: str) -> _Loc | None:
    if context.parent_kind == "movie" and context.movie_loc is not None:
        return (*context.movie_loc, "title")
    display_locs: tuple[tuple[str, _Loc | None], ...] = (
        ("series_title", _title_loc(context.series_loc)),
        ("episode_title", _title_loc(context.episode_loc)),
        ("artist_name", _name_loc(context.artist_loc)),
        ("album_title", _title_loc(context.album_loc)),
        ("track_title", _title_loc(context.track_loc)),
    )
    for field_name, loc in display_locs:
        if field_name in message and loc is not None:
            return loc
    return None


def _default_display_error_loc(context: RawAssetContext) -> _Loc:
    if context.episode_loc is not None:
        return (*context.episode_loc, "title")
    if context.track_loc is not None:
        return (*context.track_loc, "title")
    return context.asset_loc


def _title_loc(loc: _Loc | None) -> _Loc | None:
    return (*loc, "title") if loc is not None else None


def _name_loc(loc: _Loc | None) -> _Loc | None:
    return (*loc, "name") if loc is not None else None
