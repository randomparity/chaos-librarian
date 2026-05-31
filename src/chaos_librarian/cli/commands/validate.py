"""``validate`` command: shape + semantic validation of a scenario file."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.cli._envelope import synthesize_yaml_parse_report
from chaos_librarian.cli._render import render_human
from chaos_librarian.cli.app import app
from chaos_librarian.validation import prepare_run_input, run_validation
from chaos_librarian.validation.scenario_io import ScenarioLoadError


@app.command()
def validate(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate a scenario file."""
    try:
        run_input = prepare_run_input(scenario)
    except ScenarioLoadError as exc:
        report = synthesize_yaml_parse_report(scenario, exc)
    else:
        report = run_validation(run_input)
    if json_output:
        typer.echo(report.model_dump_json(by_alias=True, exclude_none=True))
    else:
        render_human(report)
    if not report.ok:
        raise typer.Exit(code=3)
