"""Capability detection — ffmpeg, ffprobe, mkvtoolnix.

Used by ``chaos-librarian capabilities`` and by ``chaos-librarian
materialize`` (which re-runs the gate at startup and refuses on regression).
"""

from __future__ import annotations

import platform
import re
import shutil
from typing import Final

from packaging.version import InvalidVersion, Version

from chaos_librarian.contract import CAPABILITIES_SCHEMA_VERSION
from chaos_librarian.contract.capabilities import (
    Capabilities,
    ReadyFor,
    ToolStatus,
)
from chaos_librarian.materializer.content.source_capabilities import (
    collect_content_source_capabilities,
)
from chaos_librarian.materializer.errors import CapabilityGateError
from chaos_librarian.materializer.tooling._subprocess import run_recorded_tool

MIN_VERSIONS: Final[dict[str, Version]] = {
    "ffmpeg": Version("7.0"),
    "ffprobe": Version("7.0"),
    "mkvtoolnix": Version("80"),
}

_VERSION_RE: Final[dict[str, re.Pattern[str]]] = {
    "ffmpeg": re.compile(r"^ffmpeg version (\S+)"),
    "ffprobe": re.compile(r"^ffprobe version (\S+)"),
    "mkvmerge": re.compile(r"^mkvmerge v(\S+)"),
}

_REGEX_TO_MIN_KEY: Final[dict[str, str]] = {
    "ffmpeg": "ffmpeg",
    "ffprobe": "ffprobe",
    "mkvmerge": "mkvtoolnix",
}
_VERSION_ARGS: Final[dict[str, tuple[str, ...]]] = {
    "ffmpeg": ("-version",),
    "ffprobe": ("-version",),
    "mkvmerge": ("--version",),
}

# Indirection so tests can monkeypatch shutil.which at the module boundary.
shutil_which = shutil.which


def _canonical_version_from_tool_output(raw: str) -> Version | None:
    """Normalize a tool's reported version into a comparable ``Version``.

    Handles distro-tagged strings like ``n7.1-0ubuntu1`` and
    ``7.0.2-3ubuntu1`` by extracting the upstream MAJOR[.MINOR[.PATCH]]
    triplet. Git-snapshot builds (``N-118412-g0ce1c8f7c5``) and
    unparseable strings return ``None`` (caller treats as
    ``meets_minimum=False``).
    """
    match = re.match(r"^[nN]?(\d+(?:\.\d+){0,2})", raw)
    if not match:
        return None
    try:
        return Version(match.group(1))
    except InvalidVersion:
        return None


def _probe_one(name: str, *, regex_key: str) -> ToolStatus:
    path = shutil_which(name)
    if path is None:
        return ToolStatus(found=False, version=None, path=None, meets_minimum=False)
    stdout = _capability_stdout([path, *_VERSION_ARGS[regex_key]], tool=name)
    if stdout is None:
        return ToolStatus(found=True, version=None, path=path, meets_minimum=False)
    first_line = stdout.splitlines()[0] if stdout else ""
    pattern = _VERSION_RE[regex_key]
    match = pattern.match(first_line)
    if not match:
        return ToolStatus(found=True, version=None, path=path, meets_minimum=False)
    raw = match.group(1)
    parsed = _canonical_version_from_tool_output(raw)
    if parsed is None:
        return ToolStatus(found=True, version=None, path=path, meets_minimum=False)
    minimum_key = _REGEX_TO_MIN_KEY[regex_key]
    return ToolStatus(
        found=True,
        version=str(parsed),
        path=path,
        meets_minimum=parsed >= MIN_VERSIONS[minimum_key],
    )


def _ffmpeg_encoder_available(ffmpeg: ToolStatus, encoder: str) -> bool:
    """Return whether the minimum-passing FFmpeg binary advertises ``encoder``."""
    if not ffmpeg.meets_minimum or ffmpeg.path is None:
        return False
    stdout = _capability_stdout(
        [ffmpeg.path, "-hide_banner", "-encoders"],
        tool="ffmpeg",
        version=ffmpeg.version or "",
    )
    if stdout is None:
        return False
    pattern = re.compile(rf"(^|\s){re.escape(encoder)}(\s|$)")
    return pattern.search(stdout) is not None


def _ffmpeg_filter_available(ffmpeg: ToolStatus, filter_name: str) -> bool:
    """Return whether the minimum-passing FFmpeg binary advertises ``filter_name``."""
    if not ffmpeg.meets_minimum or ffmpeg.path is None:
        return False
    stdout = _capability_stdout(
        [ffmpeg.path, "-hide_banner", "-filters"],
        tool="ffmpeg",
        version=ffmpeg.version or "",
    )
    if stdout is None:
        return False
    pattern = re.compile(rf"(^|\s){re.escape(filter_name)}(\s|$)")
    return pattern.search(stdout) is not None


def _ffmpeg_encoder_supports_pixel_format(
    ffmpeg: ToolStatus,
    *,
    encoder: str,
    pixel_format: str,
) -> bool:
    """Return whether FFmpeg encoder help advertises ``pixel_format``."""
    if not ffmpeg.meets_minimum or ffmpeg.path is None:
        return False
    stdout = _capability_stdout(
        [ffmpeg.path, "-hide_banner", "-h", f"encoder={encoder}"],
        tool="ffmpeg",
        version=ffmpeg.version or "",
    )
    if stdout is None:
        return False
    pattern = re.compile(rf"(^|\s){re.escape(pixel_format)}(\s|$)")
    return pattern.search(stdout) is not None


def _capability_stdout(argv: list[str], *, tool: str, version: str = "") -> str | None:
    result = run_recorded_tool(
        argv,
        tool=tool,
        version=version,
        timeout_s=5.0,
        stdout_mode="pipe",
        text=True,
    )
    if result.failure_kind is not None or result.invocation.exit_code != 0:
        return None
    return result.stdout_text()


def _ffmpeg_hdr_signaling_available(
    ffmpeg: ToolStatus, ffprobe: ToolStatus, *, libx265_available: bool
) -> bool:
    """Return whether this host can synthesize probe-visible HEVC HDR signaling."""
    return (
        ffmpeg.meets_minimum
        and ffprobe.meets_minimum
        and libx265_available
        and _ffmpeg_filter_available(ffmpeg, "setparams")
        and _ffmpeg_encoder_supports_pixel_format(
            ffmpeg,
            encoder="libx265",
            pixel_format="yuv420p10le",
        )
    )


def detect_capabilities() -> Capabilities:
    """Probe ffmpeg, ffprobe, mkvmerge and return a Capabilities report."""
    ffmpeg = _probe_one("ffmpeg", regex_key="ffmpeg")
    ffprobe = _probe_one("ffprobe", regex_key="ffprobe")
    mkv = _probe_one("mkvmerge", regex_key="mkvmerge")
    ffmpeg_ok = ffmpeg.meets_minimum
    ffprobe_ok = ffprobe.meets_minimum
    mkv_ok = mkv.meets_minimum
    libx264_available = _ffmpeg_encoder_available(ffmpeg, "libx264")
    libx265_available = _ffmpeg_encoder_available(ffmpeg, "libx265")
    libvpx_vp9_available = _ffmpeg_encoder_available(ffmpeg, "libvpx-vp9")
    hdr_video_available = _ffmpeg_hdr_signaling_available(
        ffmpeg,
        ffprobe,
        libx265_available=libx265_available,
    )
    resolution_switch_available = ffmpeg_ok and ffprobe_ok and libx264_available
    audio_recipes_available = (
        ffmpeg_ok and ffprobe_ok and _ffmpeg_filter_available(ffmpeg, "anoisesrc")
    )
    return Capabilities(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        mkvtoolnix=mkv,
        platform=f"{platform.system().lower()}-{platform.machine().lower()}",
        content_sources=collect_content_source_capabilities(
            ffmpeg_available=ffmpeg_ok,
            hdr_available=hdr_video_available,
            resolution_sequence_available=resolution_switch_available,
            audio_recipes_available=audio_recipes_available,
        ),
        ready_for=ReadyFor(
            materialize_static=ffmpeg_ok and ffprobe_ok,
            materialize_filesystem_mutations=ffmpeg_ok and ffprobe_ok,
            materialize_media_mutations=ffmpeg_ok and ffprobe_ok and mkv_ok,
            materialize_hevc_video=ffmpeg_ok and ffprobe_ok and libx265_available,
            materialize_hdr_video=hdr_video_available,
            materialize_resolution_switch_video=resolution_switch_available,
            materialize_audio_recipes=audio_recipes_available,
            materialize_matroska_muxing_profiles=ffmpeg_ok and ffprobe_ok and mkv_ok,
            materialize_webm_video=ffmpeg_ok and ffprobe_ok and libvpx_vp9_available,
        ),
    )


def assert_capable_for_static_materialize(caps: Capabilities) -> None:
    """Raise ``CapabilityGateError`` (exit 4) if ffmpeg or ffprobe failed."""
    if caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum:
        return
    missing: list[str] = []
    if not caps.ffmpeg.meets_minimum:
        missing.append("ffmpeg")
    if not caps.ffprobe.meets_minimum:
        missing.append("ffprobe")
    raise CapabilityGateError(
        f"required tool(s) missing or below minimum: {', '.join(missing)}",
        payload={"capabilities": caps.model_dump(mode="json", exclude_none=True)},
    )
