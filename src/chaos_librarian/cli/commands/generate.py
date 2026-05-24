"""``generate`` command: write deterministic fuzz scenario YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.cli._render import validate_new_out_path
from chaos_librarian.cli.app import app
from chaos_librarian.contract.profiles import FuzzProfileName
from chaos_librarian.generation import (
    generate_scenario_yaml,
    generated_scenario_summary,
    write_generated_scenario,
)


@app.command()
def generate(
    profile: Annotated[FuzzProfileName, typer.Option("--profile")],
    seed: Annotated[int, typer.Option("--seed", min=0)],
    out: Annotated[Path, typer.Option("--out", callback=validate_new_out_path)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Generate a deterministic fuzz scenario YAML file."""
    data = generate_scenario_yaml(profile=profile, seed=seed)
    write_generated_scenario(out, data)
    if json_output:
        typer.echo(generated_scenario_summary(out, data))
    else:
        typer.echo(f"generate: wrote {out}")
