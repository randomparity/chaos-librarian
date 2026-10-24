"""Shared subprocess boundary for materializer-owned tool invocations."""

from __future__ import annotations

import os
import selectors
import subprocess  # nosec B404 - this module is the audited argv-only tool boundary.
import time
from dataclasses import dataclass
from typing import Final, Literal

from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.materializer.tooling.constants import STDERR_TAIL_BYTES

_FAILURE_EXIT_CODE: Final = 1
StdoutMode = Literal["devnull", "pipe"]
FailureKind = Literal["timeout", "launch", "output_limit"]


@dataclass(frozen=True, slots=True)
class RecordedToolResult:
    """Result of one materializer tool subprocess and its audit record."""

    invocation: ToolInvocation
    stderr_tail: str
    stdout: str | bytes | None = None
    failure_kind: FailureKind | None = None

    def stdout_text(self) -> str:
        """Return stdout as lossy UTF-8 text for JSON/version probe parsers."""
        if isinstance(self.stdout, str):
            return self.stdout
        if isinstance(self.stdout, bytes):
            return self.stdout.decode("utf-8", errors="replace")
        return ""


def run_recorded_tool(
    argv: list[str],
    *,
    tool: str,
    version: str,
    timeout_s: float,
    stdout_mode: StdoutMode,
    text: bool,
    max_output_bytes: int | None = None,
) -> RecordedToolResult:
    """Run an argv-only materializer tool subprocess and return its audit data."""
    if max_output_bytes is not None:
        return _run_bounded_tool(
            argv,
            tool=tool,
            version=version,
            timeout_s=timeout_s,
            stdout_mode=stdout_mode,
            text=text,
            limit=max_output_bytes,
        )
    start = time.monotonic_ns()
    stdout_target = subprocess.PIPE if stdout_mode == "pipe" else subprocess.DEVNULL
    try:
        completed = subprocess.run(  # nosec B603 - argv-only, shell=False, bounded timeout.
            list(argv),
            stdout=stdout_target,
            stderr=subprocess.PIPE,
            timeout=timeout_s,
            check=False,
            stdin=subprocess.DEVNULL,
            text=text,
        )
    except subprocess.TimeoutExpired as exc:
        return _failed_result(
            argv=argv,
            tool=tool,
            version=version,
            start_ns=start,
            stderr_tail=_timeout_tail(tool, timeout_s=timeout_s, exc=exc),
            failure_kind="timeout",
        )
    except OSError as exc:
        return _failed_result(
            argv=argv,
            tool=tool,
            version=version,
            start_ns=start,
            stderr_tail=f"{tool} launch failed: {exc}",
            failure_kind="launch",
        )
    return RecordedToolResult(
        invocation=ToolInvocation(
            tool=tool,
            version=version,
            command=list(argv),
            exit_code=completed.returncode,
            duration_ns=time.monotonic_ns() - start,
        ),
        stderr_tail=_tail_text(completed.stderr),
        stdout=completed.stdout,
    )


def _failed_result(
    *,
    argv: list[str],
    tool: str,
    version: str,
    start_ns: int,
    stderr_tail: str,
    failure_kind: FailureKind,
) -> RecordedToolResult:
    return RecordedToolResult(
        invocation=ToolInvocation(
            tool=tool,
            version=version,
            command=list(argv),
            exit_code=_FAILURE_EXIT_CODE,
            duration_ns=time.monotonic_ns() - start_ns,
        ),
        stderr_tail=stderr_tail,
        failure_kind=failure_kind,
    )


def _timeout_tail(tool: str, *, timeout_s: float, exc: subprocess.TimeoutExpired) -> str:
    tail = f"{tool} timeout after {timeout_s}s"
    stderr_tail = _tail_text(exc.stderr)
    if stderr_tail:
        tail = f"{tail}: {stderr_tail}"
    return tail


def _tail_text(value: bytes | str | None) -> str:
    if not value:
        return ""
    if isinstance(value, bytes):
        return value[-STDERR_TAIL_BYTES:].decode("utf-8", errors="replace")
    return value[-STDERR_TAIL_BYTES:]


def _run_bounded_tool(
    argv: list[str],
    *,
    tool: str,
    version: str,
    timeout_s: float,
    stdout_mode: StdoutMode,
    text: bool,
    limit: int,
) -> RecordedToolResult:
    """Drain Unix tool pipes with a combined cap, preserving a bounded diagnostic tail."""
    if limit <= 0:
        raise ValueError("tool output limit must be positive")
    start = time.monotonic_ns()
    deadline = time.monotonic() + timeout_s
    stdout_target = subprocess.PIPE if stdout_mode == "pipe" else subprocess.DEVNULL
    try:
        with subprocess.Popen(  # nosec B603 - argv-only trusted tools; bounded pipes/time.
            list(argv),
            stdin=subprocess.DEVNULL,
            stdout=stdout_target,
            stderr=subprocess.PIPE,
        ) as process:
            try:
                output, stderr, failure = _capture_bounded(process, limit, deadline)
            finally:
                if process.poll() is None:
                    process.kill()
                process.wait()
            exit_code = process.returncode
    except OSError as exc:
        return _failed_result(
            argv=argv,
            tool=tool,
            version=version,
            start_ns=start,
            stderr_tail=f"{tool} launch/read failed: {exc}",
            failure_kind="launch",
        )
    if failure is not None:
        diagnostic = (
            f"{tool} output limit exceeded ({limit} bytes)"
            if failure == "output_limit"
            else f"{tool} timeout after {timeout_s}s"
        )
        return _failed_result(
            argv=argv,
            tool=tool,
            version=version,
            start_ns=start,
            stderr_tail=diagnostic + ": " + _tail_text(bytes(stderr)),
            failure_kind=failure,
        )
    return RecordedToolResult(
        invocation=ToolInvocation(
            tool=tool,
            version=version,
            command=list(argv),
            exit_code=exit_code,
            duration_ns=time.monotonic_ns() - start,
        ),
        stderr_tail=_tail_text(bytes(stderr)),
        stdout=bytes(output).decode("utf-8", errors="replace") if text else bytes(output),
    )


def _capture_bounded(
    process: subprocess.Popen[bytes], limit: int, deadline: float
) -> tuple[bytearray, bytearray, FailureKind | None]:
    output, stderr = bytearray(), bytearray()
    consumed = 0
    with selectors.DefaultSelector() as selector:
        for pipe in (process.stdout, process.stderr):
            if pipe is not None:
                selector.register(pipe, selectors.EVENT_READ)
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return output, stderr, "timeout"
            for key, _ in selector.select(remaining):
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                consumed += len(chunk)
                if key.fileobj is process.stderr:
                    stderr.extend(chunk)
                    del stderr[:-STDERR_TAIL_BYTES]
                if consumed > limit:
                    return output, stderr, "output_limit"
                if key.fileobj is process.stdout:
                    output.extend(chunk)
    try:
        process.wait(timeout=max(0.001, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        return output, stderr, "timeout"
    return output, stderr, None
