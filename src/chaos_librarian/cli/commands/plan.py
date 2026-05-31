"""``plan`` command: write the plan-only replay fixture for a scenario."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.cli._envelope import emit_failure, synthesize_yaml_parse_report
from chaos_librarian.cli._render import validate_new_out_path
from chaos_librarian.cli.app import app
from chaos_librarian.engine import PlanArtifacts, run_plan, write_fixture
from chaos_librarian.validation import prepare_run_input, run_validation
from chaos_librarian.validation.scenario_io import ScenarioLoadError


@app.command()
def plan(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=validate_new_out_path)],
    steps: Annotated[int | None, typer.Option("--steps", min=0)] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Plan a scenario without creating media."""
    try:
        run_input = prepare_run_input(scenario)
    except ScenarioLoadError as exc:
        report = synthesize_yaml_parse_report(scenario, exc)
        emit_failure(report, json_output=json_output)
        raise typer.Exit(code=3) from exc

    report = run_validation(run_input)
    if not report.ok:
        emit_failure(report, json_output=json_output)
        raise typer.Exit(code=3)

    artifacts = run_plan(run_input=run_input, validation_report=report, steps_limit=steps)
    write_fixture(out, artifacts, run_input.raw_bytes)

    if json_output:
        typer.echo(_plan_summary_json(artifacts, out))
    else:
        typer.echo(f"plan: wrote {out}")


def _plan_summary_json(artifacts: PlanArtifacts, out: Path) -> str:
    summary = {
        "run_id": str(artifacts.replay_bundle.run_id),
        "scenario_id": artifacts.validation_report.scenario_id,
        "schema_version": 1,
        "out": str(out.resolve()),
        "journal_entries": len(artifacts.journal),
        "ok": artifacts.validation_report.ok,
    }
    return json.dumps(summary, sort_keys=True)
