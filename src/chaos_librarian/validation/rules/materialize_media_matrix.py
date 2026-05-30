"""Rule: static media fields must be values materialize can synthesize."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Final

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.media_matrix import (
    AUDIO_SAMPLE_FORMATS_BY_CODEC,
    HEVC_VIDEO_CODECS,
    MP3_SAMPLE_RATES,
    RESOLUTION_SWITCH_VIDEO_CODEC,
    RESOLUTION_SWITCH_VIDEO_CONTAINER,
    RESOLUTION_SWITCH_VIDEO_RESOLUTION,
    RESOLUTION_SWITCH_VIDEO_SEQUENCE,
    RESOLUTION_SWITCH_VIDEO_SOURCE,
    SUPPORTED_AUDIO_CODECS,
    SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER,
    SUPPORTED_AUDIO_SAMPLE_RATES,
    SUPPORTED_RESOLUTIONS,
    SUPPORTED_VIDEO_CODECS,
    SUPPORTED_VIDEO_CODECS_BY_CONTAINER,
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
from chaos_librarian.validation.rules._subtitle_recipe import (
    SUBTITLE_RECIPE_MATRIX as _SUBTITLE_RECIPE_MATRIX,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_materialize_media_matrix"]

_MATROSKA_MUXING_PROFILE_CONTAINERS: Final[frozenset[str]] = frozenset({"mkv", "webm"})
_WEBM_VIDEO_CODEC: Final = "vp9"
_WEBM_REJECTED_VIDEO_FIELDS: Final[tuple[str, ...]] = (
    "vfr_cadence",
    "field_order",
    "color_space",
    "color_range",
    "hdr_mode",
    "resolution_sequence",
)
_SUBTITLE_TIMING_PROFILES: Final[frozenset[str]] = frozenset({"normal", "overlap", "out_of_range"})


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
    _check_mp4_moov_placement(asset=asset, asset_loc=asset_loc, reporter=reporter)
    video = _as_mapping(asset.get("video"))
    if video is None:
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message=f"{context.parent_kind} assets must declare a video stream",
            loc=(*asset_loc, "video"),
        )
    else:
        if asset.get("container") == "webm":
            _check_webm_video_asset(
                asset=asset,
                video=video,
                asset_loc=asset_loc,
                video_loc=(*asset_loc, "video"),
                reporter=reporter,
            )
            return
        if isinstance(video.get("resolution_sequence"), str):
            _check_resolution_switch_video(
                asset=asset,
                video=video,
                asset_loc=asset_loc,
                video_loc=(*asset_loc, "video"),
                reporter=reporter,
            )
            return
        _check_matroska_muxing_profile(
            asset=asset,
            asset_loc=asset_loc,
            reporter=reporter,
        )
        _check_video_embedded_metadata(asset=asset, asset_loc=asset_loc, reporter=reporter)
        _check_string_field(
            asset,
            field_name="container",
            supported=SUPPORTED_VIDEO_CONTAINERS,
            loc=(*asset_loc, "container"),
            reporter=reporter,
        )
        _check_video(
            container=asset.get("container"),
            video=video,
            video_loc=(*asset_loc, "video"),
            reporter=reporter,
        )
    _check_subtitles(asset=asset, asset_loc=asset_loc, reporter=reporter)
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
        _check_audio_sample_rate(
            audio=audio,
            loc=(*asset_loc, "audio", index, "sample_rate"),
            reporter=reporter,
        )
        _check_audio_sample_format(
            audio=audio,
            loc=(*asset_loc, "audio", index, "sample_format"),
            reporter=reporter,
        )


def _check_mp4_moov_placement(
    *,
    asset: Mapping[str, object],
    asset_loc: _Loc,
    reporter: Reporter,
) -> None:
    placement = asset.get("mp4_moov_placement")
    if not isinstance(placement, str):
        return
    if asset.get("container") == "mp4":
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message="mp4_moov_placement is only supported for mp4 assets",
        loc=(*asset_loc, "mp4_moov_placement"),
    )


def _check_resolution_switch_video(
    *,
    asset: Mapping[str, object],
    video: Mapping[str, object],
    asset_loc: _Loc,
    video_loc: _Loc,
    reporter: Reporter,
) -> None:
    _reject_matroska_muxing_profile_for_asset(
        asset=asset,
        asset_loc=asset_loc,
        reporter=reporter,
        reason="cannot be combined with resolution-switch video materialization",
    )
    _check_expected_string_field(
        asset,
        field_name="container",
        expected=RESOLUTION_SWITCH_VIDEO_CONTAINER,
        loc=(*asset_loc, "container"),
        reporter=reporter,
    )
    for field_name, expected in (
        ("source", RESOLUTION_SWITCH_VIDEO_SOURCE),
        ("codec", RESOLUTION_SWITCH_VIDEO_CODEC),
        ("resolution", RESOLUTION_SWITCH_VIDEO_RESOLUTION),
        ("resolution_sequence", RESOLUTION_SWITCH_VIDEO_SEQUENCE),
    ):
        _check_expected_string_field(
            video,
            field_name=field_name,
            expected=expected,
            loc=(*video_loc, field_name),
            reporter=reporter,
        )
    if _as_list(asset.get("audio")):
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="resolution-switch video materialization does not support audio streams",
            loc=(*asset_loc, "audio"),
        )
    if _as_list(asset.get("subtitles")):
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="resolution-switch video materialization does not support subtitle tracks",
            loc=(*asset_loc, "subtitles"),
        )
    _reject_embedded_metadata_for_asset(
        asset=asset,
        asset_loc=asset_loc,
        reporter=reporter,
        reason="cannot be combined with resolution-switch video materialization",
    )
    for field_name in (
        "vfr_cadence",
        "field_order",
        "color_space",
        "color_range",
        "hdr_mode",
    ):
        if field_name not in video or video.get(field_name) is None:
            continue
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message=f"resolution-switch video materialization cannot combine {field_name}",
            loc=(*video_loc, field_name),
        )


def _check_track_asset(context: RawAssetContext, reporter: Reporter) -> None:
    asset = context.asset
    asset_loc = context.asset_loc
    _check_mp4_moov_placement(asset=asset, asset_loc=asset_loc, reporter=reporter)
    _reject_embedded_metadata_for_asset(
        asset=asset,
        asset_loc=asset_loc,
        reporter=reporter,
        reason="is only supported for video assets",
    )
    _reject_matroska_muxing_profile_for_asset(
        asset=asset,
        asset_loc=asset_loc,
        reporter=reporter,
        reason="is only supported for mkv and webm video assets",
    )
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


def _check_video_embedded_metadata(
    *,
    asset: Mapping[str, object],
    asset_loc: _Loc,
    reporter: Reporter,
) -> None:
    container = asset.get("container")
    chapters = _as_mapping(asset.get("embedded_chapters"))
    cover_art = _as_mapping(asset.get("embedded_cover_art"))
    if chapters is not None:
        if container not in {"mp4", "mkv"}:
            reporter.error(
                code=E_MATERIALIZE_UNSUPPORTED,
                message="embedded_chapters is only supported for mp4 and mkv video assets",
                loc=(*asset_loc, "embedded_chapters"),
            )
        _check_chapter_duration(
            asset=asset,
            chapters=chapters,
            asset_loc=asset_loc,
            reporter=reporter,
        )
    if cover_art is not None and container != "mp4":
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="embedded_cover_art is only supported for mp4 video assets",
            loc=(*asset_loc, "embedded_cover_art"),
        )


def _check_matroska_muxing_profile(
    *,
    asset: Mapping[str, object],
    asset_loc: _Loc,
    reporter: Reporter,
) -> None:
    profile = asset.get("matroska_muxing_profile")
    if not isinstance(profile, str):
        return
    if asset.get("container") in _MATROSKA_MUXING_PROFILE_CONTAINERS:
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message="matroska_muxing_profile is only supported for mkv and webm video assets",
        loc=(*asset_loc, "matroska_muxing_profile"),
    )


def _check_webm_video_asset(
    *,
    asset: Mapping[str, object],
    video: Mapping[str, object],
    asset_loc: _Loc,
    video_loc: _Loc,
    reporter: Reporter,
) -> None:
    if not isinstance(asset.get("matroska_muxing_profile"), str):
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="webm video materialization requires matroska_muxing_profile",
            loc=(*asset_loc, "matroska_muxing_profile"),
        )
    for field_name, supported in (
        ("source", SUPPORTED_VIDEO_SOURCES),
        ("resolution", SUPPORTED_RESOLUTIONS),
    ):
        _check_string_field(
            video,
            field_name=field_name,
            supported=supported,
            loc=(*video_loc, field_name),
            reporter=reporter,
        )
    codec = video.get("codec")
    if isinstance(codec, str) and codec != _WEBM_VIDEO_CODEC:
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="webm video materialization only supports VP9 video",
            loc=(*video_loc, "codec"),
        )
    if _as_list(asset.get("audio")):
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="webm muxing profile materialization does not support audio streams",
            loc=(*asset_loc, "audio"),
        )
    if _as_list(asset.get("subtitles")):
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="webm muxing profile materialization does not support subtitle tracks",
            loc=(*asset_loc, "subtitles"),
        )
    _reject_embedded_metadata_for_asset(
        asset=asset,
        asset_loc=asset_loc,
        reporter=reporter,
        reason="cannot be combined with webm muxing profile materialization",
    )
    for field_name in _WEBM_REJECTED_VIDEO_FIELDS:
        if field_name not in video or video.get(field_name) is None:
            continue
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message=f"webm muxing profile materialization cannot combine {field_name}",
            loc=(*video_loc, field_name),
        )


def _check_chapter_duration(
    *,
    asset: Mapping[str, object],
    chapters: Mapping[str, object],
    asset_loc: _Loc,
    reporter: Reporter,
) -> None:
    count = chapters.get("count")
    duration = asset.get("duration_seconds")
    if not isinstance(count, int) or isinstance(count, bool):
        return
    if not isinstance(duration, int | float) or isinstance(duration, bool):
        return
    if count <= round(float(duration) * 1000):
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message="embedded_chapters.count requires at least one millisecond per chapter",
        loc=(*asset_loc, "embedded_chapters", "count"),
    )


def _reject_embedded_metadata_for_asset(
    *,
    asset: Mapping[str, object],
    asset_loc: _Loc,
    reporter: Reporter,
    reason: str,
) -> None:
    for field_name in ("embedded_chapters", "embedded_cover_art"):
        if _as_mapping(asset.get(field_name)) is None:
            continue
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message=f"{field_name} {reason}",
            loc=(*asset_loc, field_name),
        )


def _reject_matroska_muxing_profile_for_asset(
    *,
    asset: Mapping[str, object],
    asset_loc: _Loc,
    reporter: Reporter,
    reason: str,
) -> None:
    if not isinstance(asset.get("matroska_muxing_profile"), str):
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message=f"matroska_muxing_profile {reason}",
        loc=(*asset_loc, "matroska_muxing_profile"),
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
        _check_audio_sample_rate(
            audio=audio,
            loc=(*asset_loc, "audio", 0, "sample_rate"),
            reporter=reporter,
        )
        _check_audio_sample_format(
            audio=audio,
            loc=(*asset_loc, "audio", 0, "sample_format"),
            reporter=reporter,
        )
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message=(
            f"track audio codec {codec!r} is not supported for audio-only container {container!r}"
        ),
        loc=(*asset_loc, "audio", 0, "codec"),
    )


def _check_audio_sample_rate(
    *,
    audio: Mapping[str, object],
    loc: _Loc,
    reporter: Reporter,
) -> None:
    sample_rate = audio.get("sample_rate")
    if not isinstance(sample_rate, int) or isinstance(sample_rate, bool):
        return
    codec = audio.get("codec")
    supported_rates = MP3_SAMPLE_RATES if codec == "mp3" else SUPPORTED_AUDIO_SAMPLE_RATES
    if sample_rate in supported_rates:
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message=f"sample_rate {sample_rate!r} is not supported for audio codec {codec!r}",
        loc=loc,
    )


def _check_audio_sample_format(
    *,
    audio: Mapping[str, object],
    loc: _Loc,
    reporter: Reporter,
) -> None:
    sample_format = audio.get("sample_format")
    if not isinstance(sample_format, str):
        return
    codec = audio.get("codec")
    if not isinstance(codec, str):
        return
    supported_formats = AUDIO_SAMPLE_FORMATS_BY_CODEC.get(codec)
    if supported_formats is not None and sample_format in supported_formats:
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message=f"sample_format {sample_format!r} is not supported for audio codec {codec!r}",
        loc=loc,
    )


def _check_video(
    *,
    container: object,
    video: Mapping[str, object],
    video_loc: _Loc,
    reporter: Reporter,
) -> None:
    supported_codecs = SUPPORTED_VIDEO_CODECS
    if isinstance(container, str):
        supported_codecs = SUPPORTED_VIDEO_CODECS_BY_CONTAINER.get(
            container,
            SUPPORTED_VIDEO_CODECS,
        )
    for field_name, supported in (
        ("source", SUPPORTED_VIDEO_SOURCES),
        ("codec", supported_codecs),
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


def _check_subtitles(
    *,
    asset: Mapping[str, object],
    asset_loc: _Loc,
    reporter: Reporter,
) -> None:
    for index, sub_obj in enumerate(_as_list(asset.get("subtitles")) or []):
        subtitle = _as_mapping(sub_obj)
        if subtitle is None:
            continue
        loc = (*asset_loc, "subtitles", index)
        _check_subtitle_mode(subtitle=subtitle, loc=loc, reporter=reporter)
        _check_subtitle_timing(subtitle=subtitle, loc=loc, reporter=reporter)
        _check_subtitle_recipe(subtitle=subtitle, loc=loc, reporter=reporter)


def _check_subtitle_mode(
    *,
    subtitle: Mapping[str, object],
    loc: _Loc,
    reporter: Reporter,
) -> None:
    mode = subtitle.get("mode")
    if not isinstance(mode, str) or mode == "sidecar":
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message="static materialization supports only sidecar subtitle tracks",
        loc=(*loc, "mode"),
    )


def _check_subtitle_timing(
    *,
    subtitle: Mapping[str, object],
    loc: _Loc,
    reporter: Reporter,
) -> None:
    timing = subtitle.get("timing_profile", "normal")
    if not isinstance(timing, str) or timing in _SUBTITLE_TIMING_PROFILES:
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message="subtitle timing_profile is not supported by materialize synthesis",
        loc=(*loc, "timing_profile"),
    )


def _check_subtitle_recipe(
    *,
    subtitle: Mapping[str, object],
    loc: _Loc,
    reporter: Reporter,
) -> None:
    codec = subtitle.get("codec")
    source = subtitle.get("source", "generated_srt")
    encoding = subtitle.get("encoding", "utf8")
    if not isinstance(codec, str) or not isinstance(source, str):
        return
    supported_encodings = _SUBTITLE_RECIPE_MATRIX.get((codec, source))
    if supported_encodings is None:
        reporter.error(
            code=E_MATERIALIZE_UNSUPPORTED,
            message="subtitle codec/source recipe combination is not supported",
            loc=(*loc, "source"),
        )
        return
    if not isinstance(encoding, str) or encoding in supported_encodings:
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message="subtitle encoding is not supported for this codec/source recipe",
        loc=(*loc, "encoding"),
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


def _check_expected_string_field(
    data: Mapping[str, object],
    *,
    field_name: str,
    expected: str,
    loc: _Loc,
    reporter: Reporter,
) -> None:
    value = data.get(field_name)
    if not isinstance(value, str) or value == expected:
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message=(f"resolution-switch video materialization requires {field_name} {expected!r}"),
        loc=loc,
    )
