"""ffprobe wrapper.

Runs ``ffprobe -show_format -show_streams -of json`` and maps the result
into ``ProbedMedia``. Unparseable output raises ``ProbeParseError``.
Sprint 5 deliberately drops subtitle streams (sidecars are separate
files; embedded subtitles arrive in Sprint 7).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Final

from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream
from chaos_librarian.materializer.errors import ProbeParseError

_PROBE_TIMEOUT_S: Final[float] = 15.0


def _coerce_blob(value: object) -> dict[str, object] | None:
    """Return ``value`` as ``dict[str, object]`` if it is a string-keyed dict."""
    if not isinstance(value, dict):
        return None
    blob: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            return None
        blob[key] = item
    return blob


def _fps_from_rate(rate: str | None) -> float | None:
    """Parse an ffprobe ``r_frame_rate`` (``"24/1"`` or ``"24"``) into float."""
    if rate is None:
        return None
    if "/" in rate:
        num_str, den_str = rate.split("/", 1)
        try:
            num = float(num_str)
            den = float(den_str)
        except ValueError:
            return None
        if den == 0.0:
            return None
        return num / den
    try:
        return float(rate)
    except ValueError:
        return None


def _opt_int(blob: dict[str, object], key: str) -> int | None:
    """Return ``int(blob[key])`` if present and coercible, else ``None``."""
    value = blob.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _opt_str(blob: dict[str, object], key: str) -> str | None:
    """Return ``str(blob[key])`` if present, else ``None``."""
    value = blob.get(key)
    if value is None:
        return None
    return str(value)


def _language_tag(blob: dict[str, object]) -> str | None:
    """Pull ``tags.language`` out of an ffprobe stream blob if present."""
    tags = _coerce_blob(blob.get("tags"))
    if tags is None:
        return None
    raw = tags.get("language")
    if raw is None:
        return None
    return str(raw)


def _stream_from_json(blob: dict[str, object]) -> ProbedStream | None:
    """Map one ffprobe stream blob into a ``ProbedStream``.

    Returns ``None`` for subtitle streams (dropped in Sprint 5) and for
    streams whose ``codec_type`` is unknown.
    """
    codec_type = blob.get("codec_type")
    codec = str(blob.get("codec_name") or "")
    if codec_type == "video":
        return ProbedStream(
            kind="video",
            codec=codec,
            width=_opt_int(blob, "width"),
            height=_opt_int(blob, "height"),
            fps=_fps_from_rate(_opt_str(blob, "r_frame_rate")),
            language=_language_tag(blob),
        )
    if codec_type == "audio":
        return ProbedStream(
            kind="audio",
            codec=codec,
            channels=_opt_int(blob, "channels"),
            sample_rate=_opt_int(blob, "sample_rate"),
            language=_language_tag(blob),
        )
    # subtitle (and any unknown codec_type) streams are dropped — see module docstring.
    return None


def _parse_streams(streams_raw: object) -> list[ProbedStream]:
    """Iterate the ffprobe ``streams`` array and collect mapped entries."""
    if not isinstance(streams_raw, list):
        return []
    parsed: list[ProbedStream] = []
    for entry in streams_raw:
        blob = _coerce_blob(entry)
        if blob is None:
            continue
        stream = _stream_from_json(blob)
        if stream is not None:
            parsed.append(stream)
    return parsed


def _build_probed_media(
    fmt: dict[str, object], streams: list[ProbedStream], path: Path
) -> ProbedMedia:
    """Construct ``ProbedMedia`` from the parsed ``format`` blob."""
    try:
        return ProbedMedia(
            container=str(fmt.get("format_name") or ""),
            duration_seconds=float(_opt_str(fmt, "duration") or 0.0),
            size_bytes=int(_opt_str(fmt, "size") or 0),
            streams=streams,
        )
    except (ValueError, TypeError) as exc:
        raise ProbeParseError(
            f"failed to map ffprobe JSON into ProbedMedia for {path}",
            payload={"path": str(path)},
        ) from exc


def probe_file(path: Path) -> ProbedMedia:
    """Run ``ffprobe`` against ``path`` and return the parsed ``ProbedMedia``.

    Raises:
        ProbeParseError: ffprobe exited non-zero, timed out, produced
            unparseable JSON, or returned a payload that could not be
            mapped into ``ProbedMedia``.
    """
    argv = [
        "ffprobe",
        "-hide_banner",
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(path),
    ]
    try:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeParseError(
            f"ffprobe timeout on {path}",
            payload={"path": str(path), "timeout_s": _PROBE_TIMEOUT_S},
        ) from exc
    if completed.returncode != 0:
        raise ProbeParseError(
            f"ffprobe exit {completed.returncode} on {path}",
            payload={"path": str(path), "stderr": (completed.stderr or "")[-2048:]},
        )
    try:
        raw = json.loads(completed.stdout or "")
    except json.JSONDecodeError as exc:
        raise ProbeParseError(
            f"ffprobe stdout was not valid JSON for {path}",
            payload={"path": str(path), "stdout_head": (completed.stdout or "")[:512]},
        ) from exc
    blob = _coerce_blob(raw)
    if blob is None:
        raise ProbeParseError(
            f"ffprobe JSON root was not an object for {path}",
            payload={"path": str(path)},
        )
    fmt = _coerce_blob(blob.get("format")) or {}
    streams = _parse_streams(blob.get("streams"))
    return _build_probed_media(fmt, streams, path)
