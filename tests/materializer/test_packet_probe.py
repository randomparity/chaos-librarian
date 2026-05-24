"""Tests for packet byte range resolution."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.materializer.phase_b import packet_probe
from chaos_librarian.materializer.phase_b.packet_probe import (
    PacketProbeError,
    resolve_packet_byte_range,
)


def _completed(stdout: str) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=["ffprobe"],
        returncode=0,
        stdout=stdout,
        stderr="",
    )


def test_video_packets_with_pos_and_size_resolve_byte_range(monkeypatch) -> None:
    def fake_run(argv, **_kwargs):
        assert "-select_streams" in argv
        assert argv[argv.index("-select_streams") + 1] == "v:0"
        return _completed(
            '{"packets": ['
            '{"pos": "100", "size": "10"},'
            '{"pos": "120", "size": "15"},'
            '{"pos": "150", "size": "20"}'
            "]}"
        )

    monkeypatch.setattr(packet_probe, "_run_ffprobe_packets", fake_run)

    assert resolve_packet_byte_range(
        Path("asset.mkv"), stream="video", packet_start=1, packet_count=2
    ) == (120, 50)


def test_audio_stream_selection_uses_a_zero(monkeypatch) -> None:
    def fake_run(argv, **_kwargs):
        assert argv[argv.index("-select_streams") + 1] == "a:0"
        return _completed('{"packets": [{"pos": "7", "size": "5"}]}')

    monkeypatch.setattr(packet_probe, "_run_ffprobe_packets", fake_run)

    assert resolve_packet_byte_range(
        Path("asset.mkv"), stream="audio", packet_start=0, packet_count=1
    ) == (7, 5)


def test_missing_packet_pos_raises_value_error(monkeypatch) -> None:
    def fake_run(_argv, **_kwargs):
        return _completed('{"packets": [{"size": "5"}]}')

    monkeypatch.setattr(packet_probe, "_run_ffprobe_packets", fake_run)

    with pytest.raises(ValueError, match="usable packet positions"):
        resolve_packet_byte_range(Path("asset.mkv"), stream="video", packet_start=0, packet_count=1)


def test_requested_packet_range_past_available_packets_raises_value_error(monkeypatch) -> None:
    def fake_run(_argv, **_kwargs):
        return _completed('{"packets": [{"pos": "7", "size": "5"}]}')

    monkeypatch.setattr(packet_probe, "_run_ffprobe_packets", fake_run)

    with pytest.raises(ValueError, match="past available packets"):
        resolve_packet_byte_range(Path("asset.mkv"), stream="video", packet_start=1, packet_count=1)


def test_packet_probe_records_tool_invocation(monkeypatch) -> None:
    def fake_run(argv, **_kwargs):
        return _completed('{"packets": [{"pos": "7", "size": "5"}]}')

    monkeypatch.setattr(packet_probe, "_run_ffprobe_packets", fake_run)
    invocations: list[ToolInvocation] = []

    assert resolve_packet_byte_range(
        Path("asset.mkv"),
        stream="video",
        packet_start=0,
        packet_count=1,
        ffprobe_version="ffprobe test",
        invocations=invocations,
    ) == (7, 5)

    assert len(invocations) == 1
    assert invocations[0].tool == "ffprobe"
    assert invocations[0].version == "ffprobe test"
    assert invocations[0].command[:4] == ["ffprobe", "-v", "error", "-select_streams"]
    assert invocations[0].exit_code == 0


def test_packet_probe_error_carries_invocation_index(monkeypatch) -> None:
    def fake_run(_argv, **_kwargs):
        return subprocess.CompletedProcess(
            args=["ffprobe"],
            returncode=1,
            stdout="",
            stderr="no packets",
        )

    monkeypatch.setattr(packet_probe, "_run_ffprobe_packets", fake_run)
    invocations: list[ToolInvocation] = []

    with pytest.raises(PacketProbeError) as exc_info:
        resolve_packet_byte_range(
            Path("asset.mkv"),
            stream="video",
            packet_start=0,
            packet_count=1,
            ffprobe_version="ffprobe test",
            invocations=invocations,
        )

    assert exc_info.value.tool_invocation_index == 0
    assert invocations[0].exit_code == 1
