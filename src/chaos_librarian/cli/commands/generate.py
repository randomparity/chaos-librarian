"""``generate`` command: write deterministic fuzz scenario YAML."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.cli._render import validate_new_out_path
from chaos_librarian.cli.app import app
from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.contract.scenario import FUZZ_LANES_BY_PROFILE
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
    lane: Annotated[FuzzLaneName | None, typer.Option("--lane")] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Generate a deterministic fuzz scenario YAML file."""
    resolved_lane = _resolve_lane(profile=profile, lane=lane)
    data = generate_scenario_yaml(profile=profile, lane=resolved_lane, seed=seed)
    write_generated_scenario(out, data)
    if json_output:
        typer.echo(generated_scenario_summary(out, data))
    else:
        typer.echo(f"generate: wrote {out}")


def _resolve_lane(profile: FuzzProfileName, lane: FuzzLaneName | None) -> FuzzLaneName:
    if profile is FuzzProfileName.FUZZ_SMOKE and lane is None:
        return FuzzLaneName.SMOKE
    if lane is None:
        raise typer.BadParameter("--lane is required for fuzz-regression")
    if lane not in FUZZ_LANES_BY_PROFILE[profile]:
        raise typer.BadParameter(f"lane {lane.value} is not valid for {profile.value}")
    return lane
