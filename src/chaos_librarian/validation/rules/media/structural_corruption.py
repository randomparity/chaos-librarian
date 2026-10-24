"""Preflight the deliberately small generated structural-corruption matrix."""

import math
from collections.abc import Mapping
from typing import Final

from chaos_librarian.validation.codes import E_MATERIALIZE_UNSUPPORTED
from chaos_librarian.validation.reporting import IssueCollector
from chaos_librarian.validation.rules.core.raw_helpers import (
    Reporter,
    _as_list,
    _as_mapping,
    _iter_timeline_events,
)
from chaos_librarian.validation.rules.hierarchy.walkers import iter_asset_contexts
from chaos_librarian.validation.scenario_io import LineIndex

_MAX_DURATION: Final = 30
_MP3_RATE: Final = 44100

_CONTAINERS: Final = {"mp4_moov": "mp4", "mkv_cues": "mkv", "mp3_after_16_frames": "mp3"}
_PATH_ACTIONS: Final = frozenset(
    {"add_asset", "delete_asset", "move_asset", "rename_file", "move_between_roots", "touch_mtime"}
)


def rule_structural_corruption(
    raw: Mapping[str, object], line_index: LineIndex, collector: IssueCollector
) -> None:
    reporter = Reporter(collector=collector, line_index=line_index)
    assets = {
        c.asset["id"]: c.asset
        for c in iter_asset_contexts(raw)
        if isinstance(c.asset.get("id"), str)
    }
    events = list(_iter_timeline_events(raw))
    for index, event in events:
        selector = (
            event.get("region")
            if event.get("action") == "corrupt_container_header"
            else (event.get("boundary") if event.get("action") == "truncate_file" else None)
        )
        if not isinstance(selector, str) or selector not in _CONTAINERS:
            continue
        target = event.get("target")
        asset = assets.get(target) if isinstance(target, str) else None
        if asset is None:
            continue
        errors = _asset_errors(asset, _CONTAINERS[selector])
        if any(
            other_index != index
            and other.get("target") == target
            and (
                not isinstance(other.get("action"), str) or other.get("action") not in _PATH_ACTIONS
            )
            for other_index, other in events
        ):
            errors.append("structural corruption allows only one byte mutation per target asset")
        for message in errors:
            reporter.error(code=E_MATERIALIZE_UNSUPPORTED, message=message, loc=("timeline", index))


def _asset_errors(asset: Mapping[str, object], container: str) -> list[str]:
    errors: list[str] = []
    if asset.get("container") != container:
        errors.append(f"structural selector requires container={container}")
    duration = asset.get("duration_seconds")
    if (
        not isinstance(duration, int | float)
        or not math.isfinite(duration)
        or not 0 < duration <= _MAX_DURATION
    ):
        errors.append("structural corruption requires finite duration in (0, 30] seconds")
    for field in (
        "import_source",
        "same_content_as",
        "hardlinked_to",
        "symlink",
        "embedded_chapters",
        "embedded_cover_art",
        "matroska_muxing_profile",
    ):
        if asset.get(field) is not None:
            errors.append(f"structural corruption does not support {field}")
    if asset.get("subtitles"):
        errors.append("structural corruption does not support subtitle tracks")
    video = _as_mapping(asset.get("video"))
    if container == "mp3":
        if video is not None:
            errors.append("structural MP3 requires audio-only media")
    else:
        errors.extend(_video_errors(video))
    errors.extend(_audio_errors(asset, container))
    return errors


def _video_errors(video: Mapping[str, object] | None) -> list[str]:
    if video is None or video.get("codec") != "h264" or video.get("resolution") != "sd":
        return ["structural video requires H.264 at sd resolution"]
    return [
        f"structural video does not support {field}"
        for field in (
            "vfr_cadence",
            "field_order",
            "color_space",
            "color_range",
            "hdr_mode",
            "resolution_sequence",
        )
        if video.get(field) is not None
    ]


def _audio_errors(asset: Mapping[str, object], container: str) -> list[str]:
    tracks = _as_list(asset.get("audio")) or []
    if len(tracks) > 1 or (container == "mp3" and len(tracks) != 1):
        return ["structural corruption permits one audio track (required for MP3)"]
    errors: list[str] = []
    for raw_track in tracks:
        track = _as_mapping(raw_track)
        if track is None:
            continue
        codec = "mp3" if container == "mp3" else "aac"
        if track.get("codec") != codec or track.get("channels") not in ("mono", "stereo"):
            errors.append(f"structural corruption requires mono/stereo {codec} audio")
        if container == "mp3" and track.get("sample_rate", 48000) != _MP3_RATE:
            errors.append("structural MP3 requires sample_rate=44100")
        if any(track.get(f) is not None for f in ("default", "forced", "sample_format")):
            errors.append("structural corruption does not support track flags or sample_format")
    return errors
