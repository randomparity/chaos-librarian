"""``run`` command: wall-clock-mode runner (Sprint 6+, stub today)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.cli._render import stub, validate_new_out_path
from chaos_librarian.cli.app import app


@app.command()
def run(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=validate_new_out_path)],
    duration: Annotated[str, typer.Option("--duration")],
    speed: Annotated[str, typer.Option("--speed")] = "1x",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run a scenario in wall-clock mode."""
    stub("run")
