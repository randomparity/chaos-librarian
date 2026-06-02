"""ffprobe wrapper.

Runs ``ffprobe -show_format -show_streams -show_chapters -of json`` and maps
the result into ``ProbedMedia``. Unparseable output raises ``ProbeParseError``.
Sidecar subtitles are tracked separately, but embedded subtitle streams are
reported in ``ProbedMedia.streams``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from chaos_librarian.contract.manifest import (
    ProbedChapter,
    ProbedMedia,
    ProbedStream,
    StreamKind,
)
from chaos_librarian.materializer.errors import ProbeParseError
from chaos_librarian.materializer.tooling._subprocess import run_recorded_tool

_PROBE_TIMEOUT_S: Final[float] = 15.0


def _coerce_str_keyed_dict(value: object) -> dict[str, object] | None:
    """Return ``value`` as ``dict[str, object]`` if it is a string-keyed dict."""
    if not isinstance(value, dict):
        return None
    payload: dict[str, object] = {}
    for key, item in value.items():
        if not isinstance(key, str):
            return None
        payload[key] = item
    return payload


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


def _opt_int(payload: dict[str, object], key: str) -> int | None:
    """Return ``int(payload[key])`` if present and coercible, else ``None``."""
    value = payload.get(key)
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


def _opt_str(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    return str(value)


def _opt_bool(payload: dict[str, object], key: str) -> bool | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value != 0
    if isinstance(value, str):
        if value == "1" or value.casefold() == "true":
            return True
        if value == "0" or value.casefold() == "false":
            return False
    return None


def _language_tag(payload: dict[str, object]) -> str | None:
    return _tag_value(payload, "language")


def _tag_value(payload: dict[str, object], key: str) -> str | None:
    tags = _coerce_str_keyed_dict(payload.get("tags"))
    if tags is None:
        return None
    key = key.casefold()
    for tag_key, tag_value in tags.items():
        if tag_key.casefold() == key:
            return str(tag_value)
    return None


def _attached_pic(stream_json: dict[str, object]) -> bool | None:
    disposition = _coerce_str_keyed_dict(stream_json.get("disposition"))
    if disposition is None:
        return None
    return True if _opt_bool(disposition, "attached_pic") is True else None


def _disposition_bool(stream_json: dict[str, object], key: str) -> bool | None:
    disposition = _coerce_str_keyed_dict(stream_json.get("disposition"))
    if disposition is None:
        return None
    return _opt_bool(disposition, key)


def _stream_from_json(stream_json: dict[str, object]) -> ProbedStream | None:
    """Map one ffprobe stream object into a ``ProbedStream``.

    Returns ``None`` for streams whose ``codec_type`` is unknown.
    """
    codec_type = stream_json.get("codec_type")
    codec = str(stream_json.get("codec_name") or "")
    if codec_type == "video":
        return ProbedStream(
            kind=StreamKind.VIDEO,
            codec=codec,
            width=_opt_int(stream_json, "width"),
            height=_opt_int(stream_json, "height"),
            fps=_fps_from_rate(_opt_str(stream_json, "r_frame_rate")),
            language=_language_tag(stream_json),
            title=_tag_value(stream_json, "title"),
            attached_pic=_attached_pic(stream_json),
        )
    if codec_type == "audio":
        return ProbedStream(
            kind=StreamKind.AUDIO,
            codec=codec,
            channels=_opt_int(stream_json, "channels"),
            channel_layout=_opt_str(stream_json, "channel_layout"),
            sample_rate=_opt_int(stream_json, "sample_rate"),
            language=_language_tag(stream_json),
            title=_tag_value(stream_json, "title") or _tag_value(stream_json, "handler_name"),
            role=_tag_value(stream_json, "role"),
        )
    if codec_type == "subtitle":
        return ProbedStream(
            kind=StreamKind.SUBTITLE,
            codec=codec,
            language=_language_tag(stream_json),
            title=_tag_value(stream_json, "title"),
            default=_disposition_bool(stream_json, "default"),
            forced=_disposition_bool(stream_json, "forced"),
        )
    return None


def _parse_streams(streams_raw: object) -> list[ProbedStream]:
    if not isinstance(streams_raw, list):
        return []
    parsed: list[ProbedStream] = []
    for entry in streams_raw:
        stream_json = _coerce_str_keyed_dict(entry)
        if stream_json is None:
            continue
        stream = _stream_from_json(stream_json)
        if stream is not None:
            parsed.append(stream)
    return parsed


def _milliseconds_from_chapter_time(chapter_json: dict[str, object], prefix: str) -> int | None:
    integer_value = _opt_int(chapter_json, prefix)
    if integer_value is not None and _opt_str(chapter_json, "time_base") == "1/1000":
        return integer_value
    seconds = _opt_str(chapter_json, f"{prefix}_time")
    if seconds is None:
        return None
    try:
        return round(float(seconds) * 1000)
    except ValueError:
        return None


def _chapter_from_json(index: int, chapter_json: dict[str, object]) -> ProbedChapter | None:
    start_ms = _milliseconds_from_chapter_time(chapter_json, "start")
    end_ms = _milliseconds_from_chapter_time(chapter_json, "end")
    if start_ms is None or end_ms is None:
        return None
    chapter_id = _opt_int(chapter_json, "id")
    return ProbedChapter(
        index=index if chapter_id is None else chapter_id,
        start_ms=start_ms,
        end_ms=end_ms,
        title=_tag_value(chapter_json, "title"),
    )


def _parse_chapters(chapters_raw: object) -> list[ProbedChapter]:
    if not isinstance(chapters_raw, list):
        return []
    parsed: list[ProbedChapter] = []
    for index, entry in enumerate(chapters_raw):
        chapter_json = _coerce_str_keyed_dict(entry)
        if chapter_json is None:
            continue
        chapter = _chapter_from_json(index, chapter_json)
        if chapter is not None:
            parsed.append(chapter)
    return parsed


def _build_probed_media(
    fmt: dict[str, object],
    streams: list[ProbedStream],
    chapters: list[ProbedChapter],
    path: Path,
) -> ProbedMedia:
    try:
        return ProbedMedia(
            container=str(fmt.get("format_name") or ""),
            duration_seconds=float(_opt_str(fmt, "duration") or 0.0),
            size_bytes=int(_opt_str(fmt, "size") or 0),
            streams=streams,
            chapters=chapters,
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
        "-show_chapters",
        "-of",
        "json",
        str(path),
    ]
    result = run_recorded_tool(
        argv,
        tool="ffprobe",
        version="",
        timeout_s=_PROBE_TIMEOUT_S,
        stdout_mode="pipe",
        text=True,
    )
    if result.failure_kind == "timeout":
        raise ProbeParseError(
            f"ffprobe timeout on {path}",
            payload={"path": str(path), "timeout_s": _PROBE_TIMEOUT_S},
        )
    if result.failure_kind == "launch":
        raise ProbeParseError(
            f"ffprobe launch failed on {path}",
            payload={"path": str(path), "stderr": result.stderr_tail},
        )
    if result.invocation.exit_code != 0:
        raise ProbeParseError(
            f"ffprobe exit {result.invocation.exit_code} on {path}",
            payload={"path": str(path), "stderr": result.stderr_tail},
        )
    try:
        raw = json.loads(result.stdout_text())
    except json.JSONDecodeError as exc:
        raise ProbeParseError(
            f"ffprobe stdout was not valid JSON for {path}",
            payload={"path": str(path), "stdout_head": result.stdout_text()[:512]},
        ) from exc
    payload = _coerce_str_keyed_dict(raw)
    if payload is None:
        raise ProbeParseError(
            f"ffprobe JSON root was not an object for {path}",
            payload={"path": str(path)},
        )
    fmt = _coerce_str_keyed_dict(payload.get("format")) or {}
    streams = _parse_streams(payload.get("streams"))
    chapters = _parse_chapters(payload.get("chapters"))
    return _build_probed_media(fmt, streams, chapters, path)
