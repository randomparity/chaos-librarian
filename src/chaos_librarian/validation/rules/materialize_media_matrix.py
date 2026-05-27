"""Rule: static media fields must be values materialize can synthesize."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.media_matrix import (
    HEVC_VIDEO_CODECS,
    SUPPORTED_AUDIO_CODECS,
    SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER,
    SUPPORTED_RESOLUTIONS,
    SUPPORTED_VIDEO_CODECS,
    SUPPORTED_VIDEO_CONTAINERS,
    SUPPORTED_VIDEO_SOURCES,
)
from chaos_librarian.validation.codes import E_MATERIALIZE_UNSUPPORTED
from chaos_librarian.validation.rules._common import (
    RawAssetContext,
    Reporter,
    _as_list,
    _as_mapping,
    _Loc,
    iter_asset_contexts,
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
    for context in iter_asset_contexts(raw):
        _check_asset_context(context, reporter)


def _check_asset_context(context: RawAssetContext, reporter: Reporter) -> None:
    if context.parent_kind == ParentKind.TRACK.value:
        _check_track_asset(context, reporter)
        return
    if context.parent_kind in {ParentKind.MOVIE.value, ParentKind.EPISODE.value}:
        _check_video_asset(context, reporter)


def _check_video_asset(context: RawAssetContext, reporter: Reporter) -> None:
    asset = context.asset
    asset_loc = context.asset_loc
    _check_string_field(
        asset,
        field_name="container",
        supported=SUPPORTED_VIDEO_CONTAINERS,
        loc=(*asset_loc, "container"),
        reporter=reporter,
    )
    video = _as_mapping(asset.get("video"))
    if video is None:
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message=f"{context.parent_kind} assets must declare a video stream",
            loc=(*asset_loc, "video"),
        )
    else:
        _check_video(
            video=video,
            video_loc=(*asset_loc, "video"),
            reporter=reporter,
        )
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


def _check_track_asset(context: RawAssetContext, reporter: Reporter) -> None:
    asset = context.asset
    asset_loc = context.asset_loc
    if _as_mapping(asset.get("video")) is not None:
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="track assets must not declare a video stream",
            loc=(*asset_loc, "video"),
        )
    if _as_list(asset.get("subtitles")):
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="track assets must not declare subtitle tracks",
            loc=(*asset_loc, "subtitles"),
        )
    audio_streams = _as_list(asset.get("audio"))
    if audio_streams is None or len(audio_streams) != 1:
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="track assets must declare exactly one audio stream",
            loc=(*asset_loc, "audio"),
        )
        return
    audio = _as_mapping(audio_streams[0])
    if audio is None:
        return
    _check_track_container_and_codec(
        asset=asset, audio=audio, asset_loc=asset_loc, reporter=reporter
    )


def _check_track_container_and_codec(
    *,
    asset: Mapping[str, object],
    audio: Mapping[str, object],
    asset_loc: _Loc,
    reporter: Reporter,
) -> None:
    container = asset.get("container")
    if isinstance(container, str) and container not in SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER:
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message=f"track container {container!r} is not supported by materialize synthesis",
            loc=(*asset_loc, "container"),
        )
    codec = audio.get("codec")
    if not isinstance(container, str) or not isinstance(codec, str):
        return
    supported_codecs = SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER.get(container)
    if supported_codecs is None or codec in supported_codecs:
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message=(
            f"track audio codec {codec!r} is not supported for audio-only container {container!r}"
        ),
        loc=(*asset_loc, "audio", 0, "codec"),
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
    _check_interlaced_video(
        video=video,
        video_loc=video_loc,
        reporter=reporter,
    )
    _check_hdr_video(
        video=video,
        video_loc=video_loc,
        reporter=reporter,
    )


def _check_interlaced_video(
    *,
    video: Mapping[str, object],
    video_loc: _Loc,
    reporter: Reporter,
) -> None:
    field_order = video.get("field_order")
    if not isinstance(field_order, str):
        return
    if "vfr_cadence" in video and video.get("vfr_cadence") is not None:
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="field_order cannot be combined with vfr_cadence",
            loc=(*video_loc, "field_order"),
        )


def _check_hdr_video(
    *,
    video: Mapping[str, object],
    video_loc: _Loc,
    reporter: Reporter,
) -> None:
    hdr_mode = video.get("hdr_mode")
    if not isinstance(hdr_mode, str):
        return
    codec = video.get("codec")
    if isinstance(codec, str) and codec not in HEVC_VIDEO_CODECS:
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="HDR signaling requires HEVC/H.265 video materialization",
            loc=(*video_loc, "hdr_mode"),
        )
    color_space = video.get("color_space")
    if isinstance(color_space, str) and color_space != "bt2020":
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="HDR signaling requires color_space 'bt2020' when color_space is set",
            loc=(*video_loc, "color_space"),
        )
    color_range = video.get("color_range")
    if isinstance(color_range, str) and color_range != "limited":
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="HDR signaling requires color_range 'limited' when color_range is set",
            loc=(*video_loc, "color_range"),
        )
    if "vfr_cadence" in video and video.get("vfr_cadence") is not None:
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="HDR signaling cannot be combined with vfr_cadence",
            loc=(*video_loc, "hdr_mode"),
        )
    if "field_order" in video and video.get("field_order") is not None:
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="HDR signaling cannot be combined with field_order",
            loc=(*video_loc, "hdr_mode"),
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
