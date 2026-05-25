"""Rule: static media fields must be values materialize can synthesize."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.media_matrix import (
    SUPPORTED_AUDIO_CODECS,
    SUPPORTED_CONTAINERS,
    SUPPORTED_RESOLUTIONS,
    SUPPORTED_VIDEO_CODECS,
    SUPPORTED_VIDEO_SOURCES,
)
from chaos_librarian.validation.codes import E_MATERIALIZE_UNSUPPORTED
from chaos_librarian.validation.rules._common import (
    Reporter,
    _as_list,
    _as_mapping,
    _Loc,
    iter_assets_with_loc,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_materialize_media_matrix"]


def rule_materialize_media_matrix(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject shape-valid static media declarations unsupported by materialize."""
    reporter = Reporter(collector=collector, line_index=line_index)
    for asset, asset_loc in iter_assets_with_loc(raw):
        _check_string_field(
            asset,
            field_name="container",
            supported=SUPPORTED_CONTAINERS,
            loc=(*asset_loc, "container"),
            reporter=reporter,
        )
        video = _as_mapping(asset.get("video"))
        if video is not None:
            _check_video(video=video, video_loc=(*asset_loc, "video"), reporter=reporter)
        for index, audio_obj in enumerate(_as_list(asset.get("audio")) or []):
            audio = _as_mapping(audio_obj)
            if audio is None:
                continue
            _check_string_field(
                audio,
                field_name="codec",
                supported=SUPPORTED_AUDIO_CODECS,
                loc=(*asset_loc, "audio", index, "codec"),
                reporter=reporter,
            )


def _check_video(
    *,
    video: Mapping[str, object],
    video_loc: _Loc,
    reporter: Reporter,
) -> None:
    for field_name, supported in (
        ("source", SUPPORTED_VIDEO_SOURCES),
        ("codec", SUPPORTED_VIDEO_CODECS),
        ("resolution", SUPPORTED_RESOLUTIONS),
    ):
        _check_string_field(
            video,
            field_name=field_name,
            supported=supported,
            loc=(*video_loc, field_name),
            reporter=reporter,
        )


def _check_string_field(
    data: Mapping[str, object],
    *,
    field_name: str,
    supported: frozenset[str],
    loc: _Loc,
    reporter: Reporter,
) -> None:
    value = data.get(field_name)
    if not isinstance(value, str):
        return
    if value in supported:
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message=f"{field_name} {value!r} is not supported by materialize synthesis",
        loc=loc,
    )
