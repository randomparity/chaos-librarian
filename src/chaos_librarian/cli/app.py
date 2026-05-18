"""Typer app exposing the chaos-librarian CLI surface.

Sprint 0 freezes the command surface. Every command prints a not-implemented
notice and exits with code 1. Later sprints replace these stubs with real
implementations. See docs/specs/chaos-librarian-design.md "CLI Contract".
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.contract.validation import ValidationIssue
from chaos_librarian.engine import PlanArtifacts, run_plan
from chaos_librarian.engine.writer import write_fixture
from chaos_librarian.scenario_io import ScenarioLoadError
from chaos_librarian.validation import (
    ValidationReport,
    ValidationSeverity,
    prepare_run_input,
    run_validation,
)
from chaos_librarian.validation.codes import E_YAML_PARSE

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
    try:
        run_input = prepare_run_input(scenario)
    except ScenarioLoadError as exc:
        report = _synthesize_yaml_parse_report(scenario, exc)
    else:
        report = run_validation(run_input)
    if json_output:
        typer.echo(report.model_dump_json(by_alias=True, exclude_none=True))
    else:
        _render_human(report)
    if not report.ok:
        raise typer.Exit(code=3)


def _synthesize_yaml_parse_report(scenario_path: Path, exc: ScenarioLoadError) -> ValidationReport:
    """Wrap a ScenarioLoadError as the Sprint 1 E_YAML_PARSE report.

    The byte-binding factory raises now; the CLI maps the exception to the
    structured report shape Sprint 1 promised for unparseable input.
    """
    return ValidationReport(
        schema_version=1,
        scenario_id="<unknown>",
        ok=False,
        issues=[
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code=E_YAML_PARSE,
                message=str(exc),
                line=exc.line,
                column=exc.column,
                path=None,
            )
        ],
    )


@app.command()
def plan(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=_validate_new_out_path)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Plan a scenario without creating media."""
    try:
        run_input = prepare_run_input(scenario)
    except ScenarioLoadError as exc:
        report = _synthesize_yaml_parse_report(scenario, exc)
        _emit_failure(report, json_output=json_output)
        raise typer.Exit(code=3) from exc

    report = run_validation(run_input)
    if not report.ok:
        _emit_failure(report, json_output=json_output)
        raise typer.Exit(code=3)

    artifacts = run_plan(run_input=run_input, validation_report=report)
    write_fixture(out, artifacts, run_input.raw_bytes)

    if json_output:
        typer.echo(_plan_summary_json(artifacts, out))
    else:
        typer.echo(f"plan: wrote {out}")


def _emit_failure(report: ValidationReport, *, json_output: bool) -> None:
    if json_output:
        typer.echo(report.model_dump_json(by_alias=True, exclude_none=True))
    else:
        _render_human(report)


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
