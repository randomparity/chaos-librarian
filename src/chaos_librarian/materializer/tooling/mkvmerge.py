"""mkvmerge argv builder and subprocess wrapper."""

from __future__ import annotations

import subprocess
import time
from pathlib import Path

from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.scenario import MatroskaMuxingProfile
from chaos_librarian.materializer.tooling.constants import STDERR_TAIL_BYTES


def build_mkvmerge_command(
    *,
    input_path: Path,
    output_path: Path,
    container: str,
    profile: MatroskaMuxingProfile,
    deterministic_seed: int,
) -> list[str]:
    """Build a deterministic mkvmerge remux command.

    Args:
        input_path: Temporary FFmpeg output to remux.
        output_path: Final Matroska/WebM output path.
        container: Scenario container name.
        profile: Requested cue or cluster muxing profile.
        deterministic_seed: mkvmerge deterministic mode seed.

    Returns:
        The argv list for mkvmerge.
    """
    argv = [
        "mkvmerge",
        "--quiet",
        "--deterministic",
        str(deterministic_seed),
        "--no-date",
        "--disable-track-statistics-tags",
    ]
    if container == "webm":
        argv.append("--webm")
    if profile is MatroskaMuxingProfile.NO_CUES:
        argv.append("--no-cues")
    elif profile is MatroskaMuxingProfile.DENSE_CUES:
        argv.extend(["--cues", "0:all"])
    elif profile is MatroskaMuxingProfile.SHORT_CLUSTERS:
        argv.extend(["--cluster-length", "250ms"])
    argv.extend(["-o", str(output_path), str(input_path)])
    return argv


def run_mkvmerge(
    argv: list[str],
    *,
    mkvmerge_version: str,
    timeout_s: float = 60.0,
) -> tuple[ToolInvocation, str]:
    """Invoke mkvmerge and return its invocation record plus stderr tail.

    Args:
        argv: mkvmerge argv to execute.
        mkvmerge_version: Version recorded in the materialization report.
        timeout_s: Subprocess timeout in seconds.

    Returns:
        A `(ToolInvocation, stderr_tail)` tuple regardless of exit code.
    """
    start = time.monotonic_ns()
    completed = subprocess.run(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=timeout_s,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    duration_ns = time.monotonic_ns() - start
    stderr_bytes = completed.stderr or b""
    stderr_tail = stderr_bytes[-STDERR_TAIL_BYTES:].decode("utf-8", errors="replace")
    invocation = ToolInvocation(
        tool="mkvmerge",
        version=mkvmerge_version,
        command=list(argv),
        exit_code=completed.returncode,
        duration_ns=duration_ns,
    )
    return invocation, stderr_tail
