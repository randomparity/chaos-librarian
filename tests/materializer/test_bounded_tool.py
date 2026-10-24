"""Feature tool output must be bounded without losing actionable failures."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from chaos_librarian.materializer.tooling._subprocess import run_recorded_tool


@pytest.mark.parametrize("fd", [1, 2])
def test_output_limit_terminates_noisy_tool(fd: int) -> None:
    result = run_recorded_tool(
        [sys.executable, "-c", f"import os; os.write({fd}, b'x' * 1000000)"],
        tool="fixture",
        version="test",
        timeout_s=5,
        stdout_mode="pipe",
        text=False,
        max_output_bytes=4096,
    )
    assert result.invocation.exit_code != 0
    assert result.failure_kind == "output_limit"
    assert "output limit" in result.stderr_tail
    assert len(result.stdout or b"") <= 4096


def test_bounded_tool_preserves_output_and_timeout() -> None:
    result = run_recorded_tool(
        [sys.executable, "-c", "import sys; print('ok'); print('diagnostic', file=sys.stderr)"],
        tool="fixture",
        version="test",
        timeout_s=5,
        stdout_mode="pipe",
        text=True,
        max_output_bytes=4096,
    )
    assert result.invocation.exit_code == 0
    assert result.stdout == "ok\n"
    assert result.stderr_tail == "diagnostic\n"
    timeout = run_recorded_tool(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        tool="fixture",
        version="test",
        timeout_s=0.1,
        stdout_mode="pipe",
        text=False,
        max_output_bytes=4096,
    )
    assert timeout.failure_kind == "timeout"
    assert "timeout" in timeout.stderr_tail


@pytest.mark.parametrize("mode", ["timeout", "output_limit"])
def test_failed_bounded_child_is_reaped(tmp_path: Path, mode: str) -> None:
    pid_path = tmp_path / "pid"
    work = "time.sleep(10)" if mode == "timeout" else "os.write(1, b'x' * 1000000)"
    program = (
        "import os, time; from pathlib import Path; "
        f"Path({str(pid_path)!r}).write_text(str(os.getpid())); {work}"
    )
    result = run_recorded_tool(
        [sys.executable, "-c", program],
        tool="fixture",
        version="test",
        timeout_s=1,
        stdout_mode="pipe",
        text=False,
        max_output_bytes=4096,
    )
    assert result.failure_kind == mode
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_path.read_text()), 0)


def test_bounded_tool_drains_simultaneous_streams_and_reports_launch_error() -> None:
    result = run_recorded_tool(
        [sys.executable, "-c", "import os; os.write(1, b'o' * 2048); os.write(2, b'e' * 2048)"],
        tool="fixture",
        version="test",
        timeout_s=5,
        stdout_mode="pipe",
        text=False,
        max_output_bytes=4096,
    )
    assert result.invocation.exit_code == 0
    assert result.stdout == b"o" * 2048
    assert result.stderr_tail == "e" * 2048
    missing = run_recorded_tool(
        ["/nonexistent/chaos-librarian-test-tool"],
        tool="fixture",
        version="test",
        timeout_s=5,
        stdout_mode="devnull",
        text=False,
        max_output_bytes=4096,
    )
    assert missing.failure_kind == "launch"
    assert missing.invocation.exit_code != 0
    assert "launch/read failed" in missing.stderr_tail
