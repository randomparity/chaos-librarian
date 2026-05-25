"""Shared support matrix for static media synthesis."""

from __future__ import annotations

from typing import Final

SUPPORTED_CONTAINERS: Final[frozenset[str]] = frozenset({"mkv", "mp4"})
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
HEVC_VIDEO_CODECS: Final[frozenset[str]] = frozenset({"h265", "hevc"})
