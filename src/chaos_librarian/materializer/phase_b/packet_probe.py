"""Resolve media packet selections into byte ranges using ffprobe."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Final

from chaos_librarian.contract.materialization import ToolInvocation

_PROBE_TIMEOUT_S: Final[float] = 15.0
_STREAM_SELECTORS: Final[dict[str, str]] = {
    "video": "v:0",
    "audio": "a:0",
    "subtitle": "s:0",
}


class PacketProbeError(ValueError):
    """Packet-range resolution failed after an ffprobe invocation."""

    def __init__(self, message: str, *, tool_invocation_index: int | None = None) -> None:
        super().__init__(message)
        self.tool_invocation_index = tool_invocation_index


def _run_ffprobe_packets(argv: list[str]) -> subprocess.CompletedProcess[str]:
    """Run ffprobe packet query; split out for unit-test monkeypatching."""
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        timeout=_PROBE_TIMEOUT_S,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def resolve_packet_byte_range(
    path: Path,
    *,
    stream: str,
    packet_start: int,
    packet_count: int,
    ffprobe_version: str = "",
    invocations: list[ToolInvocation] | None = None,
) -> tuple[int, int]:
    """Return ``(byte_start, byte_count)`` for a stream packet range."""
    selector = _stream_selector(stream)
    argv = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        selector,
        "-show_packets",
        "-show_entries",
        "packet=pos,size",
        "-of",
        "json",
        str(path),
    ]
    started = time.monotonic_ns()
    try:
        completed = _run_ffprobe_packets(argv)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PacketProbeError(f"ffprobe packet probe failed for {path}: {exc}") from exc
    duration_ns = time.monotonic_ns() - started
    invocation_index = _append_invocation(
        invocations,
        argv=argv,
        ffprobe_version=ffprobe_version,
        exit_code=completed.returncode,
        duration_ns=duration_ns,
    )
    try:
        if completed.returncode != 0:
            stderr_tail = (completed.stderr or "")[-2048:]
            raise ValueError(f"ffprobe packet probe failed for {path}: {stderr_tail}")
        packets = _packet_entries(completed.stdout)
        packet_end = packet_start + packet_count
        if packet_end > len(packets):
            raise ValueError(
                "requested packet range is past available packets: "
                f"{packet_start}:{packet_end} > {len(packets)}"
            )
        selected = _usable_packet_range(packets[packet_start:packet_end], stream=stream, path=path)
        first_pos = selected[0][0]
        last_pos, last_size = selected[-1]
        return first_pos, (last_pos + last_size) - first_pos
    except ValueError as exc:
        raise PacketProbeError(str(exc), tool_invocation_index=invocation_index) from exc


def _append_invocation(
    invocations: list[ToolInvocation] | None,
    *,
    argv: list[str],
    ffprobe_version: str,
    exit_code: int,
    duration_ns: int,
) -> int | None:
    if invocations is None:
        return None
    invocation_index = len(invocations)
    invocations.append(
        ToolInvocation(
            tool="ffprobe",
            version=ffprobe_version,
            command=list(argv),
            exit_code=exit_code,
            duration_ns=duration_ns,
        )
    )
    return invocation_index


def _stream_selector(stream: str) -> str:
    selector = _STREAM_SELECTORS.get(stream)
    if selector is None:
        raise ValueError(
            f"unsupported packet stream {stream!r}; supported: {sorted(_STREAM_SELECTORS)}"
        )
    return selector


def _packet_entries(stdout: str) -> list[object]:
    try:
        raw = json.loads(stdout or "")
    except json.JSONDecodeError as exc:
        raise ValueError("ffprobe packet output was not valid JSON") from exc
    if not isinstance(raw, dict):
        raise ValueError("ffprobe packet JSON root was not an object")
    packets_raw = raw.get("packets")
    if not isinstance(packets_raw, list):
        return []
    return packets_raw


def _usable_packet_range(
    packets_raw: list[object],
    *,
    stream: str,
    path: Path,
) -> list[tuple[int, int]]:
    packets: list[tuple[int, int]] = []
    for packet_raw in packets_raw:
        packet = _packet_pos_size(packet_raw)
        if packet is None:
            raise ValueError(
                f"ffprobe found no usable packet positions for {stream} stream in {path}"
            )
        packets.append(packet)
    return packets


def _packet_pos_size(packet_raw: object) -> tuple[int, int] | None:
    if not isinstance(packet_raw, dict):
        return None
    packet: dict[str, object] = {}
    for key, value in packet_raw.items():
        if not isinstance(key, str):
            return None
        packet[key] = value
    pos = _decimal_str(packet.get("pos"))
    size = _decimal_str(packet.get("size"))
    if pos is None or size is None:
        return None
    return int(pos), int(size)


def _decimal_str(value: object) -> str | None:
    if isinstance(value, str) and value.isdecimal():
        return value
    return None
