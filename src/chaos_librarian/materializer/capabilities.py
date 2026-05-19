"""Capability detection — ffmpeg, ffprobe, mkvtoolnix.

Used by ``chaos-librarian capabilities`` and by ``chaos-librarian
materialize`` (which re-runs the gate at startup and refuses on regression).
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from typing import Final

from packaging.version import InvalidVersion, Version

from chaos_librarian.contract import CAPABILITIES_SCHEMA_VERSION
from chaos_librarian.contract.capabilities import (
    Capabilities,
    ReadyFor,
    ToolStatus,
)
from chaos_librarian.materializer.errors import CapabilityGateError

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
    try:
        result = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ToolStatus(found=True, version=None, path=path, meets_minimum=False)
    first_line = (result.stdout or "").splitlines()[0] if result.stdout else ""
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


def detect_capabilities() -> Capabilities:
    """Probe ffmpeg, ffprobe, mkvmerge and return a Capabilities report."""
    ffmpeg = _probe_one("ffmpeg", regex_key="ffmpeg")
    ffprobe = _probe_one("ffprobe", regex_key="ffprobe")
    mkv = _probe_one("mkvmerge", regex_key="mkvmerge")
    ffmpeg_ok = ffmpeg.meets_minimum
    ffprobe_ok = ffprobe.meets_minimum
    mkv_ok = mkv.meets_minimum
    return Capabilities(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        mkvtoolnix=mkv,
        platform=f"{platform.system().lower()}-{platform.machine().lower()}",
        ready_for=ReadyFor(
            materialize_static=ffmpeg_ok and ffprobe_ok,
            materialize_filesystem_mutations=ffmpeg_ok and ffprobe_ok,
            materialize_media_mutations=ffmpeg_ok and ffprobe_ok and mkv_ok,
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
