"""Typer app exposing the chaos-librarian CLI surface.

Sprint 0 freezes the command surface. Every command prints a not-implemented
notice and exits with code 1. Later sprints replace these stubs with real
implementations. See docs/specs/chaos-librarian-design.md "CLI Contract".
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

app = typer.Typer(
    name="chaos-librarian",
    help="Scenario-driven synthetic media library simulator.",
    no_args_is_help=True,
)


def _stub(command: str) -> None:
    typer.echo(f"chaos-librarian {command}: not yet implemented (Sprint 0 stub).", err=True)
    raise typer.Exit(code=1)


def _validate_new_out_path(value: Path) -> Path:
    """Reject --out paths whose parent is missing or that already exist.

    The CLI never overwrites an existing output directory and requires
    the caller to have prepared a writable parent. This runs as a Typer
    callback so failures surface as exit-code 2 BadParameter errors
    before any command body executes.
    """
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
    _stub("validate")


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
    scenario: Annotated[Path, typer.Argument(exists=False, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out")],
    duration: Annotated[str, typer.Option("--duration")],
    speed: Annotated[str, typer.Option("--speed")] = "1x",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run a scenario in wall-clock mode."""
    _stub("run")


@app.command()
def step(
    run_dir: Annotated[Path, typer.Argument(exists=False)],
    next_: Annotated[bool, typer.Option("--next")] = False,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Advance a step-mode run."""
    _stub("step")


@app.command()
def replay(
    bundle: Annotated[Path, typer.Argument(exists=False, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out")],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Replay a recorded run."""
    _stub("replay")


@app.command()
def inspect(
    run_dir: Annotated[Path, typer.Argument(exists=False)],
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
    run_dir: Annotated[Path, typer.Argument(exists=False)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Remove a run directory (sentinel-protected)."""
    _stub("clean")
