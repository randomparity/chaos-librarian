"""Shared support matrix for static media synthesis."""

from __future__ import annotations

from typing import Final

SUPPORTED_VIDEO_CONTAINERS: Final[frozenset[str]] = frozenset({"mkv", "mp4"})
SUPPORTED_AUDIO_ONLY_CONTAINERS: Final[frozenset[str]] = frozenset({"flac", "mp3", "m4a"})
SUPPORTED_AUDIO_ONLY_CODECS_BY_CONTAINER: Final[dict[str, frozenset[str]]] = {
    "flac": frozenset({"flac"}),
    "mp3": frozenset({"mp3"}),
    "m4a": frozenset({"aac"}),
}
SUPPORTED_CONTAINERS: Final[frozenset[str]] = (
    SUPPORTED_VIDEO_CONTAINERS | SUPPORTED_AUDIO_ONLY_CONTAINERS
)
SUPPORTED_RESOLUTIONS: Final[frozenset[str]] = frozenset({"sd", "hd", "1080p"})
SUPPORTED_VIDEO_SOURCES: Final[frozenset[str]] = frozenset(
    {"color_bars", "mandelbrot", "solid_color"}
)
SUPPORTED_VIDEO_CODECS: Final[frozenset[str]] = frozenset({"h264", "h265", "hevc"})
SUPPORTED_AUDIO_CODECS: Final[frozenset[str]] = frozenset({"aac"})
VIDEO_ENCODER_BY_CODEC: Final[dict[str, str]] = {
    "h264": "libx264",
    "h265": "libx265",
    "hevc": "libx265",
}
AUDIO_ENCODER_BY_CODEC: Final[dict[str, str]] = {
    "aac": "aac",
    "flac": "flac",
    "mp3": "libmp3lame",
}
HEVC_VIDEO_CODECS: Final[frozenset[str]] = frozenset({"h265", "hevc"})
