"""Shared support matrix for static media synthesis."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Final

SUPPORTED_VIDEO_CODECS_BY_CONTAINER: Final[dict[str, frozenset[str]]] = {
    "mkv": frozenset({"h264", "h265", "hevc"}),
    "mp4": frozenset({"h264", "h265", "hevc"}),
    "webm": frozenset({"vp9"}),
}
SUPPORTED_VIDEO_CONTAINERS: Final[frozenset[str]] = frozenset(SUPPORTED_VIDEO_CODECS_BY_CONTAINER)
SUPPORTED_AUDIO_ONLY_CONTAINERS: Final[frozenset[str]] = frozenset({"flac", "mp3", "m4a", "wav"})
SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER: Final[dict[str, frozenset[str]]] = {
    "flac": frozenset({"flac"}),
    "mp3": frozenset({"mp3"}),
    "m4a": frozenset({"aac"}),
    "wav": frozenset({"pcm_s16le", "pcm_s24le", "pcm_f32le"}),
}
SUPPORTED_CONTAINERS: Final[frozenset[str]] = (
    SUPPORTED_VIDEO_CONTAINERS | SUPPORTED_AUDIO_ONLY_CONTAINERS
)
SUPPORTED_RESOLUTIONS: Final[frozenset[str]] = frozenset({"sd", "hd", "1080p"})
SUPPORTED_VIDEO_SOURCES: Final[frozenset[str]] = frozenset(
    {"color_bars", "mandelbrot", "solid_color"}
)
SUPPORTED_AUDIO_SOURCES: Final[frozenset[str]] = frozenset(
    {"sine", "silence", "channel_tones", "noise"}
)
SUPPORTED_AUDIO_SAMPLE_RATES: Final[frozenset[int]] = frozenset(
    {8000, 22050, 44100, 48000, 88200, 96000}
)
MP3_SAMPLE_RATES: Final[frozenset[int]] = frozenset({8000, 22050, 44100, 48000})
AUDIO_SAMPLE_FORMATS_BY_CODEC: Final[dict[str, frozenset[str]]] = {
    "flac": frozenset({"s16", "s24"}),
    "pcm_s16le": frozenset({"s16"}),
    "pcm_s24le": frozenset({"s24"}),
    "pcm_f32le": frozenset({"flt"}),
}
SUPPORTED_VIDEO_CODECS: Final[frozenset[str]] = frozenset(
    codec for codecs in SUPPORTED_VIDEO_CODECS_BY_CONTAINER.values() for codec in codecs
)
SUPPORTED_AUDIO_CODECS: Final[frozenset[str]] = frozenset({"aac"})
VIDEO_ENCODER_BY_CODEC: Final[dict[str, str]] = {
    "h264": "libx264",
    "h265": "libx265",
    "hevc": "libx265",
    "vp9": "libvpx-vp9",
}
AUDIO_ENCODER_BY_CODEC: Final[dict[str, str]] = {
    "aac": "aac",
    "flac": "flac",
    "mp3": "libmp3lame",
    "pcm_s16le": "pcm_s16le",
    "pcm_s24le": "pcm_s24le",
    "pcm_f32le": "pcm_f32le",
}
HEVC_VIDEO_CODECS: Final[frozenset[str]] = frozenset({"h265", "hevc"})
RESOLUTION_SWITCH_VIDEO_CONTAINER: Final = "ts"
RESOLUTION_SWITCH_VIDEO_CODEC: Final = "h264"
RESOLUTION_SWITCH_VIDEO_SOURCE: Final = "color_bars"
RESOLUTION_SWITCH_VIDEO_RESOLUTION: Final = "sd"
RESOLUTION_SWITCH_VIDEO_SEQUENCE: Final = "sd_to_hd"

# Real-library container vocabulary for the importer (issue #105 / ADR 0012).
# Deliberately wider than SUPPORTED_VIDEO_CONTAINERS: imported assets
# materialize as byte copies, so no synthesis matrix applies. Bare
# extension tokens; they feed Asset.container values directly.
IMPORT_VIDEO_CONTAINERS: Final[frozenset[str]] = frozenset(
    {"mkv", "mp4", "webm", "avi", "mov", "ts", "m4v", "wmv", "mpg", "mpeg"}
)


DISPOSITION_UNSUPPORTED_ACTIONS: Final = frozenset(
    {
        "reencode_video",
        "reencode_audio",
        "remux_container",
        "embed_subtitle",
        "extract_subtitle",
        "edit_metadata",
        "write_invalid_duration_metadata",
    }
)
DISPOSITION_MAX_TRACKS: Final = 8
DISPOSITION_MAX_LANGUAGE_BYTES: Final = 64
DISPOSITION_MAX_DURATION: Final = 30
DISPOSITION_MAX_BYTES: Final = 64 * 1024 * 1024
DISPOSITION_MAX_OUTPUT_BYTES: Final = 1024 * 1024


def has_track_dispositions(asset: Mapping[str, object]) -> bool:
    """Whether an asset requires the bounded embedded/disposition path."""
    return any(
        track.get("mode") == "embedded"
        or any(track.get(flag) is not None for flag in ("default", "forced"))
        for kind in ("audio", "subtitles")
        for track in _track_mappings(asset.get(kind))
    )


def _track_mappings(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, list | tuple):
        return []
    return [{str(k): v for k, v in track.items()} for track in value if isinstance(track, dict)]


def track_disposition_errors(asset: Mapping[str, object]) -> list[tuple[str, str]]:
    """Shared raw/typed/direct synthesis matrix; shape validation owns missing types."""
    if not has_track_dispositions(asset):
        return []
    errors: list[tuple[str, str]] = []
    video_raw = asset.get("video")
    video = {str(k): v for k, v in video_raw.items()} if isinstance(video_raw, dict) else None
    if asset.get("container") != "mkv" or video is None:
        errors.append(("container", "track dispositions require MKV video"))
    else:
        for name, expected in (("codec", "h264"), ("resolution", "sd")):
            if video.get(name) != expected:
                errors.append((f"video.{name}", f"track dispositions require {name}={expected}"))
        for name in (
            "vfr_cadence",
            "field_order",
            "color_space",
            "color_range",
            "hdr_mode",
            "resolution_sequence",
        ):
            if video.get(name) is not None:
                errors.append((f"video.{name}", f"track dispositions do not support {name}"))
    duration = asset.get("duration_seconds")
    if (
        not isinstance(duration, int | float)
        or not math.isfinite(duration)
        or not 0 < duration <= DISPOSITION_MAX_DURATION
    ):
        errors.append(
            ("duration_seconds", "track dispositions require finite duration in (0, 30] seconds")
        )
    for name in (
        "matroska_muxing_profile",
        "embedded_chapters",
        "embedded_cover_art",
        "mp4_moov_placement",
        "same_content_as",
        "hardlinked_to",
        "symlink",
        "import_source",
    ):
        if asset.get(name) is not None:
            errors.append((name, f"track dispositions do not support {name}"))
    errors.extend(_disposition_track_errors(asset))
    return errors


def _disposition_track_errors(asset: Mapping[str, object]) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    for kind in ("audio", "subtitles"):
        tracks = _track_mappings(asset.get(kind))
        embedded = [t for t in tracks if kind == "audio" or t.get("mode") == "embedded"]
        if len(embedded) > DISPOSITION_MAX_TRACKS:
            errors.append((kind, "track dispositions allow at most 8 tracks per kind"))
        for index, track in enumerate(tracks):
            errors.extend(_track_disposition_errors(kind, index, track))
    return errors


def _track_disposition_errors(
    kind: str, index: int, track: Mapping[str, object]
) -> list[tuple[str, str]]:
    prefix = f"{kind}.{index}"
    if kind == "subtitles" and track.get("mode") != "embedded":
        return [
            (f"{prefix}.{flag}", "only embedded subtitles support dispositions")
            for flag in ("default", "forced")
            if track.get(flag) is not None
        ]
    errors: list[tuple[str, str]] = [
        (
            f"{prefix}.{flag}",
            f"explicit {flag} boolean required on every audio/embedded subtitle track",
        )
        for flag in ("default", "forced")
        if not isinstance(track.get(flag), bool)
    ]
    language = track.get("language")
    if isinstance(language, str) and len(language.encode("utf-8")) > DISPOSITION_MAX_LANGUAGE_BYTES:
        errors.append((f"{prefix}.language", "track disposition language must fit 64 UTF-8 bytes"))
    if kind == "audio":
        if track.get("sample_format") is not None:
            errors.append(
                (f"{prefix}.sample_format", "track dispositions do not support sample_format")
            )
        return errors
    for name, expected in (
        ("codec", "srt"),
        ("source", "generated_srt"),
        ("encoding", "utf8"),
        ("timing_profile", "normal"),
    ):
        if track.get(name, expected) != expected:
            errors.append(
                (f"{prefix}.{name}", f"embedded disposition subtitles require {name}={expected}")
            )
    return errors
