"""Shared support matrix for static media synthesis."""

from __future__ import annotations

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
