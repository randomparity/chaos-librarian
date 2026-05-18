"""Typer app exposing the chaos-librarian CLI surface.

Sprint 0 freezes the command surface. Every command prints a not-implemented
notice and exits with code 1. Later sprints replace these stubs with real
implementations. See docs/specs/chaos-librarian-design.md "CLI Contract".
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated, cast

import typer
from pydantic import ValidationError

from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.contract.validation import ValidationIssue
from chaos_librarian.engine import (
    JournalCorruptError,
    PlanArtifacts,
    ScenarioTamperedError,
    SentinelInvalidError,
    StepResult,
    run_plan,
    step_fixture,
)
from chaos_librarian.engine.resolution import resolve_timeline, step_boundaries
from chaos_librarian.engine.writer import append_step, write_fixture
from chaos_librarian.scenario_io import ScenarioLoadError
from chaos_librarian.validation import (
    ValidationReport,
    ValidationSeverity,
    prepare_run_input,
    prepare_run_input_from_bytes,
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
    steps: Annotated[int | None, typer.Option("--steps", min=0)] = None,
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

    artifacts = run_plan(run_input=run_input, validation_report=report, steps_limit=steps)
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
    next_count: Annotated[int, typer.Option("--next", min=1)] = 1,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Advance a step-mode run by ``--next`` resolved events (default 1)."""
    try:
        result = step_fixture(run_dir, n_events=next_count)
    except SentinelInvalidError as exc:
        _emit_step_error("sentinel_invalid", str(exc), json_output=json_output)
        raise typer.Exit(code=7) from exc
    except ScenarioTamperedError as exc:
        _emit_step_error(
            "scenario_tampered",
            str(exc),
            json_output=json_output,
            extra={"recorded_run_id": exc.recorded, "recomputed_run_id": exc.recomputed},
        )
        raise typer.Exit(code=7) from exc
    except JournalCorruptError as exc:
        _emit_step_error(
            "journal_corrupt",
            str(exc),
            json_output=json_output,
            extra={"kind": exc.kind, "line": exc.line, "detail": exc.detail},
        )
        raise typer.Exit(code=1) from exc

    append_step(
        run_dir,
        new_entries=result.new_entries,
        new_current_manifest=result.new_current_manifest,
        new_report_set=result.new_report_set,
        new_replay_bundle=result.new_replay_bundle,
    )

    if json_output:
        typer.echo(_step_summary_json(result))
    else:
        typer.echo(f"step: applied {result.steps_applied}, remaining {result.steps_remaining}")


def _step_summary_json(result: StepResult) -> str:
    payload = {
        "run_id": str(result.new_replay_bundle.run_id),
        "steps_applied": result.steps_applied,
        "steps_remaining": result.steps_remaining,
        "applied_events": result.new_replay_bundle.applied_events,
        "done": result.done,
    }
    return json.dumps(payload, sort_keys=True)


def _emit_step_error(
    error_code: str,
    message: str,
    *,
    json_output: bool,
    extra: dict[str, object] | None = None,
) -> None:
    if json_output:
        payload: dict[str, object] = {"error": error_code, "message": message}
        if extra:
            payload.update(extra)
        typer.echo(json.dumps(payload, sort_keys=True), err=True)
    else:
        typer.echo(f"{error_code}: {message}", err=True)


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
    try:
        summary = _build_inspect_summary(run_dir)
    except SentinelInvalidError as exc:
        _emit_step_error("sentinel_invalid", str(exc), json_output=json_output)
        raise typer.Exit(code=7) from exc

    if json_output:
        typer.echo(json.dumps(summary, sort_keys=True))
    else:
        _render_inspect_human(summary)


def _build_inspect_summary(run_dir: Path) -> dict[str, object]:
    """Read a run directory's persisted artifacts and return a summary dict.

    Verifies the sentinel first; missing or unparseable sentinels raise
    ``SentinelInvalidError`` so the CLI can map them to exit 7. After the
    sentinel passes, reads ``replay.json``, ``manifest.current.json``, the
    journal, and the embedded ``scenario.yaml`` to compute step-unit
    counted ``applied_steps`` / ``steps_remaining`` via ``step_boundaries``.

    Args:
        run_dir: Path to a chaos-librarian run directory.

    Returns:
        A dict matching the design D10 inspect summary shape.

    Raises:
        SentinelInvalidError: sentinel missing or unparseable.
    """
    _verify_sentinel(run_dir)

    bundle = PlanOnlyReplayBundle.model_validate_json((run_dir / "replay.json").read_text())
    manifest_current = Manifest.model_validate_json((run_dir / "manifest.current.json").read_text())
    journal_path = run_dir / "journal.jsonl"
    journal_entries = (
        sum(1 for line in journal_path.read_text().splitlines() if line.strip())
        if journal_path.exists()
        else 0
    )

    scenario_bytes = (run_dir / "scenario.yaml").read_bytes()
    run_input = prepare_run_input_from_bytes(
        raw_bytes=scenario_bytes,
        source_label=f"inspect:{run_dir}",
    )
    scenario = Scenario.model_validate(run_input.raw_data)
    resolved_timeline = resolve_timeline(scenario)
    boundaries = step_boundaries(resolved_timeline)
    if bundle.applied_events == 0:
        applied_steps = 0
    elif bundle.applied_events in boundaries:
        applied_steps = boundaries.index(bundle.applied_events) + 1
    else:
        # Off-boundary detection here is informational; the integrity
        # error fires at replay/step time, not inspect time.
        applied_steps = 0
    steps_remaining = len(boundaries) - applied_steps
    return {
        "run_id": str(bundle.run_id),
        "scenario_id": scenario.scenario_id,
        "schema_version": bundle.schema_version,
        "execution_mode": bundle.execution_mode.value,
        "journal_entries": journal_entries,
        "applied_events": bundle.applied_events,
        "applied_steps": applied_steps,
        "steps_remaining": steps_remaining,
        "counts": {
            "works": len(manifest_current.works),
            "variants": len(manifest_current.variants),
            "bundles": len(manifest_current.bundles),
            "assets": len(manifest_current.assets),
            "sidecars": len(manifest_current.sidecars),
        },
        "created_at": None,
    }


def _verify_sentinel(run_dir: Path) -> None:
    """Raise ``SentinelInvalidError`` if the run sentinel is missing or unparseable."""
    sentinel_path = run_dir / ".chaos-librarian-run"
    if not sentinel_path.exists():
        raise SentinelInvalidError(f"sentinel missing: {sentinel_path}")
    try:
        RunSentinel.model_validate_json(sentinel_path.read_text())
    except (ValidationError, ValueError) as exc:
        raise SentinelInvalidError(f"sentinel unparseable: {exc}") from exc


def _render_inspect_human(summary: dict[str, object]) -> None:
    """Echo the inspect summary as a plain key:value block to stdout."""
    typer.echo(f"run_id:           {summary['run_id']}")
    typer.echo(f"scenario_id:      {summary['scenario_id']}")
    typer.echo(f"execution_mode:   {summary['execution_mode']}")
    typer.echo(f"journal_entries:  {summary['journal_entries']}")
    typer.echo(f"applied_events:   {summary['applied_events']}")
    typer.echo(f"applied_steps:    {summary['applied_steps']}")
    typer.echo(f"steps_remaining:  {summary['steps_remaining']}")
    counts = cast("dict[str, int]", summary["counts"])
    typer.echo(
        f"counts:           works={counts['works']} variants={counts['variants']} "
        f"bundles={counts['bundles']} assets={counts['assets']} sidecars={counts['sidecars']}"
    )


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
    sentinel_path = run_dir / ".chaos-librarian-run"
    if not sentinel_path.exists():
        _emit_step_error(
            "sentinel_invalid",
            f"sentinel missing: {sentinel_path}",
            json_output=json_output,
        )
        raise typer.Exit(code=7)
    try:
        sentinel = RunSentinel.model_validate_json(sentinel_path.read_text())
    except (ValidationError, ValueError) as exc:
        _emit_step_error(
            "sentinel_invalid",
            f"sentinel unparseable: {exc}",
            json_output=json_output,
        )
        raise typer.Exit(code=7) from exc

    resolved = run_dir.resolve()
    shutil.rmtree(run_dir)

    if json_output:
        typer.echo(
            json.dumps({"removed": str(resolved), "run_id": str(sentinel.run_id)}, sort_keys=True)
        )
    else:
        typer.echo(f"clean: removed {resolved} (run_id {sentinel.run_id})")


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
