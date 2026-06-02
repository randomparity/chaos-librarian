"""mkvmerge argv builder and subprocess wrapper."""

from __future__ import annotations

from pathlib import Path

from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.scenario import MatroskaMuxingProfile
from chaos_librarian.materializer.tooling._subprocess import run_recorded_tool


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
    result = run_recorded_tool(
        argv,
        tool="mkvmerge",
        version=mkvmerge_version,
        timeout_s=timeout_s,
        stdout_mode="devnull",
        text=False,
    )
    return result.invocation, result.stderr_tail
