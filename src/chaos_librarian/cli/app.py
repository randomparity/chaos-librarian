"""Typer app exposing the chaos-librarian CLI surface.

See docs/specs/chaos-librarian-design.md "CLI Contract".
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated, Final, cast

import typer
from pydantic import TypeAdapter, ValidationError

from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import (
    MaterializeReplayBundle,
    PlanOnlyReplayBundle,
    ReplayBundle,
)
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.contract.validation import ValidationIssue
from chaos_librarian.engine import (
    JournalCorruptError,
    PlanArtifacts,
    ReplayIntegrityError,
    ScenarioTamperedError,
    SentinelInvalidError,
    StepResult,
    compare_fixtures,
    replay_plan_bundle,
    run_plan,
    step_fixture,
)
from chaos_librarian.engine.resolution import resolve_timeline, step_boundaries
from chaos_librarian.engine.writer import append_step, write_fixture
from chaos_librarian.materializer import (
    CapabilityGateError,
    ContainmentViolationError,
    MaterializationError,
    ProbeParseError,
    ScenarioValidationError,
    TimelineUnsupportedError,
    ToolFailedError,
    UnsupportedMaterializationError,
    detect_capabilities,
    materialize_scenario,
)
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

_REPLAY_BUNDLE_ADAPTER: Final = TypeAdapter(ReplayBundle)


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
    """Wrap a ScenarioLoadError as the E_YAML_PARSE validation report.

    The byte-binding factory raises now; the CLI maps the exception to
    the structured report shape promised for unparseable input.
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
    try:
        artifacts = materialize_scenario(scenario, out)
    except CapabilityGateError as exc:
        _emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=4) from exc
    except ScenarioValidationError as exc:
        # Mirror ``plan``'s exit code (3) for semantic-validation failures so
        # downstream agents key off the same convention.
        _emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=3) from exc
    except TimelineUnsupportedError as exc:
        _emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=5) from exc
    except UnsupportedMaterializationError as exc:
        _emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=5) from exc
    except ToolFailedError as exc:
        _emit_materialize_error(exc, json_output=json_output, run_dir=out)
        raise typer.Exit(code=5) from exc
    except ProbeParseError as exc:
        _emit_materialize_error(exc, json_output=json_output, run_dir=out)
        raise typer.Exit(code=5) from exc
    except ContainmentViolationError as exc:
        _emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=7) from exc

    if json_output:
        typer.echo(artifacts.materialization_report.model_dump_json(indent=2, exclude_none=True))
    else:
        typer.echo(f"materialize: wrote {out}")


def _emit_materialize_error(
    exc: MaterializationError,
    *,
    json_output: bool,
    run_dir: Path | None,
) -> None:
    payload: dict[str, object] = {
        "error_code": exc.error_code,
        "message": exc.message,
    }
    if exc.asset_id is not None:
        payload["asset_id"] = exc.asset_id
    if exc.field is not None:
        payload["field"] = exc.field
    payload.update(exc.payload)
    if run_dir is not None:
        payload["materialization_report_path"] = str(run_dir / "materialization.json")
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True))
    else:
        typer.echo(f"chaos-librarian: materialize failed ({exc.error_code})", err=True)
        typer.echo(f"  message: {exc.message}", err=True)
        if exc.asset_id is not None:
            typer.echo(f"  asset:   {exc.asset_id}", err=True)
        if exc.field is not None:
            typer.echo(f"  field:   {exc.field}", err=True)
        if run_dir is not None:
            typer.echo(f"  report:  {run_dir / 'materialization.json'}", err=True)


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
        sentinel = _verify_sentinel(run_dir)
    except SentinelInvalidError as exc:
        _emit_step_error("sentinel_invalid", str(exc), json_output=json_output)
        raise typer.Exit(code=7) from exc
    if sentinel.state == "in_progress":
        _emit_step_error(
            "E_SENTINEL_IN_PROGRESS",
            f"sentinel state is in_progress; clean the run-dir before stepping: {run_dir}",
            json_output=json_output,
        )
        raise typer.Exit(code=7)

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
    against: Annotated[Path | None, typer.Option("--against", exists=True, file_okay=False)] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Replay a recorded run from its replay.json bundle."""
    parsed_any = _REPLAY_BUNDLE_ADAPTER.validate_json(bundle.read_bytes())
    if isinstance(parsed_any, MaterializeReplayBundle):
        _emit_step_error(
            "materialize_replay_not_implemented",
            "materialize replay is not implemented in this CLI build",
            json_output=json_output,
            extra={"execution_mode": parsed_any.execution_mode.value},
        )
        raise typer.Exit(code=1)
    parsed_bundle = parsed_any
    try:
        artifacts = replay_plan_bundle(parsed_bundle)
    except ReplayIntegrityError as exc:
        payload = {
            "error": "replay_divergence",
            "kind": "integrity",
            "recorded_run_id": str(parsed_bundle.run_id),
            "message": str(exc),
        }
        if json_output:
            typer.echo(json.dumps(payload, sort_keys=True), err=True)
        else:
            typer.echo(f"replay_divergence: {exc}", err=True)
        raise typer.Exit(code=6) from exc

    write_fixture(out, artifacts, parsed_bundle.scenario.encode("utf-8"))

    target = against or _infer_original(bundle, parsed_bundle.run_id, parsed_bundle.applied_events)
    if target is not None:
        diff = compare_fixtures(target, out)
        if not diff.is_clean():
            payload = {
                "error": "replay_divergence",
                "kind": "artifact_diff",
                "run_id": str(parsed_bundle.run_id),
                "left_dir": str(target.resolve()),
                "right_dir": str(out.resolve()),
                "files": [
                    {
                        "path": f.path,
                        "kind": f.kind,
                        "left_bytes": f.left_bytes,
                        "right_bytes": f.right_bytes,
                        "first_diff_line": f.first_diff_line,
                        "preview_left": f.preview_left,
                        "preview_right": f.preview_right,
                    }
                    for f in diff.files
                ],
            }
            if json_output:
                typer.echo(json.dumps(payload, sort_keys=True), err=True)
            else:
                typer.echo(f"replay_divergence: {len(diff.files)} files differ", err=True)
                for f in diff.files:
                    typer.echo(f"  - {f.path} [{f.kind}]", err=True)
            raise typer.Exit(code=6)

    if json_output:
        typer.echo(
            json.dumps(
                {
                    "out": str(out.resolve()),
                    "run_id": str(parsed_bundle.run_id),
                    "compared_against": str(target) if target else None,
                },
                sort_keys=True,
            )
        )
    else:
        suffix = f" (matches {target})" if target else ""
        typer.echo(f"replay: wrote {out}{suffix}")


def _infer_original(bundle_path: Path, run_id: object, applied_events: int) -> Path | None:
    """Return ``bundle_path.parent`` when it is the bundle's original fixture.

    Two bundles of the same scenario+seed at different truncation points share
    a ``run_id``; the cross-check on ``applied_events`` ensures auto-discover
    does not match a different-length sibling fixture. Returns ``None`` when
    the sentinel is missing, the sentinel is unparseable, the sibling
    ``replay.json`` is missing or unparseable, or either field disagrees.
    """
    parent = bundle_path.parent
    sentinel = _load_sentinel(parent / ".chaos-librarian-run")
    if sentinel is None or sentinel.run_id != run_id:
        return None
    parent_bundle = _load_replay_bundle(parent / "replay.json")
    if parent_bundle is None or parent_bundle.applied_events != applied_events:
        return None
    return parent


def _load_sentinel(path: Path) -> RunSentinel | None:
    """Parse a sentinel file, returning ``None`` when absent or malformed."""
    if not path.exists():
        return None
    try:
        return RunSentinel.model_validate_json(path.read_text())
    except (ValidationError, ValueError):
        return None


def _load_replay_bundle(path: Path) -> PlanOnlyReplayBundle | None:
    """Parse a plan-only replay bundle, returning ``None`` when absent or malformed."""
    if not path.exists():
        return None
    try:
        return PlanOnlyReplayBundle.model_validate_json(path.read_text())
    except (ValidationError, ValueError):
        return None


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
    sentinel = _verify_sentinel(run_dir)

    bundle = _REPLAY_BUNDLE_ADAPTER.validate_json((run_dir / "replay.json").read_bytes())
    manifest_current = Manifest.model_validate_json((run_dir / "manifest.current.json").read_text())
    try:
        journal_text = (run_dir / "journal.jsonl").read_text()
    except FileNotFoundError:
        journal_entries = 0
    else:
        journal_entries = sum(1 for line in journal_text.splitlines() if line.strip())

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
        "sentinel": {
            "state": sentinel.state,
            "created_at": sentinel.created_at.isoformat() if sentinel.created_at else None,
            "run_id": str(sentinel.run_id),
        },
    }


def _verify_sentinel(run_dir: Path) -> RunSentinel:
    """Return the parsed sentinel; raise ``SentinelInvalidError`` if missing or unparseable."""
    sentinel_path = run_dir / ".chaos-librarian-run"
    if not sentinel_path.exists():
        raise SentinelInvalidError(f"sentinel missing: {sentinel_path}")
    try:
        return RunSentinel.model_validate_json(sentinel_path.read_text())
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
    sentinel = cast("dict[str, object]", summary["sentinel"])
    typer.echo(f"sentinel:         state={sentinel['state']} run_id={sentinel['run_id']}")


@app.command()
def capabilities(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Detect available media tools (ffmpeg, ffprobe, mkvtoolnix)."""
    caps = detect_capabilities()
    if json_output:
        typer.echo(caps.model_dump_json(indent=2, exclude_none=True))
    else:
        _render_capabilities_human(caps)
    exit_code = 0 if (caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum) else 4
    raise typer.Exit(code=exit_code)


def _render_capabilities_human(caps: Capabilities) -> None:
    """Echo the capabilities payload as a plain key:value block to stdout."""
    typer.echo(f"platform:   {caps.platform}")
    for name, tool in (
        ("ffmpeg", caps.ffmpeg),
        ("ffprobe", caps.ffprobe),
        ("mkvtoolnix", caps.mkvtoolnix),
    ):
        if not tool.found:
            typer.echo(f"  {name:<11} missing")
            continue
        status = "OK" if tool.meets_minimum else "BELOW MINIMUM"
        typer.echo(f"  {name:<11} {tool.version} ({tool.path}) [{status}]")
    typer.echo("ready_for:")
    typer.echo(f"  materialize_static:               {caps.ready_for.materialize_static}")
    typer.echo(
        f"  materialize_filesystem_mutations: {caps.ready_for.materialize_filesystem_mutations}"
    )
    typer.echo(f"  materialize_media_mutations:      {caps.ready_for.materialize_media_mutations}")


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

    replay_path = run_dir / "replay.json"
    if not replay_path.exists():
        _emit_step_error(
            "fixture_inconsistent",
            f"replay.json missing: {replay_path}",
            json_output=json_output,
        )
        raise typer.Exit(code=7)
    try:
        bundle = _REPLAY_BUNDLE_ADAPTER.validate_json(replay_path.read_bytes())
    except (ValidationError, ValueError) as exc:
        _emit_step_error(
            "fixture_inconsistent",
            f"replay.json unparseable: {exc}",
            json_output=json_output,
        )
        raise typer.Exit(code=7) from exc
    if bundle.run_id != sentinel.run_id:
        _emit_step_error(
            "fixture_inconsistent",
            f"sentinel.run_id {sentinel.run_id} != replay.json run_id {bundle.run_id}",
            json_output=json_output,
        )
        raise typer.Exit(code=7)

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
