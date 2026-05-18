"""Typer app exposing the chaos-librarian CLI surface.

Sprint 0 freezes the command surface. Every command prints a not-implemented
notice and exits with code 1. Later sprints replace these stubs with real
implementations. See docs/specs/chaos-librarian-design.md "CLI Contract".
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.validation import (
    ValidationReport,
    ValidationSeverity,
    run_validation,
)

app = typer.Typer(
    name="chaos-librarian",
    help="Scenario-driven synthetic media library simulator.",
    no_args_is_help=True,
)


def _stub(command: str) -> None:
    typer.echo(f"chaos-librarian {command}: not yet implemented.", err=True)
    raise typer.Exit(code=1)


def _validate_new_out_path(value: Path) -> Path:
    """Reject --out paths that already exist or whose parent is not a writable directory."""
    if value.exists():
        raise typer.BadParameter(f"--out path already exists: {value}")
    parent = value.parent
    if not parent.exists():
        raise typer.BadParameter(f"--out parent directory does not exist: {parent}")
    if not parent.is_dir():
        raise typer.BadParameter(f"--out parent is not a directory: {parent}")
    return value


@app.command()
def validate(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate a scenario file."""
    report = run_validation(scenario)
    if json_output:
        typer.echo(report.model_dump_json(by_alias=True, exclude_none=True))
    else:
        _render_human(report)
    if not report.ok:
        raise typer.Exit(code=3)


@app.command()
def plan(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=_validate_new_out_path)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Plan a scenario without creating media."""
    _stub("plan")


@app.command()
def materialize(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=_validate_new_out_path)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Materialize a scenario (creates real media files)."""
    _stub("materialize")


@app.command()
def run(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=_validate_new_out_path)],
    duration: Annotated[str, typer.Option("--duration")],
    speed: Annotated[str, typer.Option("--speed")] = "1x",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run a scenario in wall-clock mode."""
    _stub("run")


@app.command()
def step(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    next_: Annotated[bool, typer.Option("--next")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Advance a step-mode run."""
    _stub("step")


@app.command()
def replay(
    bundle: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=_validate_new_out_path)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Replay a recorded run."""
    _stub("replay")


@app.command()
def inspect(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect a run directory."""
    _stub("inspect")


@app.command()
def capabilities(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Detect available media tools (ffmpeg, ffprobe, mkvtoolnix)."""
    _stub("capabilities")


@app.command()
def clean(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Remove a run directory (sentinel-protected)."""
    _stub("clean")


_SEVERITY_LABEL = {
    ValidationSeverity.ERROR: "ERROR",
    ValidationSeverity.WARNING: "WARN ",
    ValidationSeverity.INFO: "INFO ",
}


def _render_human(report: ValidationReport) -> None:
    status = "OK" if report.ok else f"FAIL ({len(report.issues)} issues)"
    typer.echo(f"scenario: {report.scenario_id}")
    typer.echo(f"status: {status}")
    if not report.issues:
        return
    typer.echo("")
    for issue in report.issues:
        label = _SEVERITY_LABEL[issue.severity]
        location = (
            f"line {issue.line}:{issue.column}"
            if issue.line is not None and issue.column is not None
            else ""
        )
        path = issue.path or ""
        typer.echo(f"{label}  {issue.code:<25} {path:<35} {location:<14} {issue.message}")
