"""``step`` command: advance a step-mode run by ``--next`` resolved events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from chaos_librarian.cli._envelope import (
    E_JOURNAL_CORRUPT,
    E_REPLAY_BUNDLE_INVALID,
    E_SCENARIO_TAMPERED,
    E_SENTINEL_IN_PROGRESS,
    E_SENTINEL_INVALID,
    E_STEP_UNSUPPORTED_MODE,
    E_STEP_WRITE_FAILED,
    emit_cli_error,
    emit_cli_operation_error,
)
from chaos_librarian.cli._replay_io import REPLAY_BUNDLE_ADAPTER
from chaos_librarian.cli.app import app
from chaos_librarian.contract.replay_bundle import ExecutionMode, PlanOnlyReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinelState
from chaos_librarian.engine import (
    JournalCorruptError,
    ScenarioTamperedError,
    SentinelInvalidError,
    StepResult,
    append_step,
    step_fixture,
    verify_sentinel,
)
from chaos_librarian.validation import prepare_replay_input_from_bytes


@app.command()
def step(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    next_count: Annotated[int, typer.Option("--next", min=1)] = 1,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Advance a step-mode run by ``--next`` resolved events (default 1)."""
    try:
        sentinel = verify_sentinel(run_dir)
    except SentinelInvalidError as exc:
        emit_cli_error(error_code=E_SENTINEL_INVALID, message=str(exc), json_output=json_output)
        raise typer.Exit(code=7) from exc
    if sentinel.state is RunSentinelState.IN_PROGRESS:
        emit_cli_error(
            error_code=E_SENTINEL_IN_PROGRESS,
            message=f"sentinel state is in_progress; clean the run-dir before stepping: {run_dir}",
            json_output=json_output,
        )
        raise typer.Exit(code=7)
    _preflight_step_replay_bundle(run_dir, json_output=json_output)

    try:
        prepared_input = prepare_replay_input_from_bytes(
            scenario_bytes=(run_dir / "scenario.yaml").read_bytes(),
            source_label=f"step:{run_dir}",
        )
        result = step_fixture(run_dir, n_steps=next_count, prepared_input=prepared_input)
    except SentinelInvalidError as exc:
        emit_cli_error(error_code=E_SENTINEL_INVALID, message=str(exc), json_output=json_output)
        raise typer.Exit(code=7) from exc
    except ScenarioTamperedError as exc:
        emit_cli_error(
            error_code=E_SCENARIO_TAMPERED,
            message=str(exc),
            json_output=json_output,
            details={"recorded_run_id": exc.recorded, "recomputed_run_id": exc.recomputed},
        )
        raise typer.Exit(code=7) from exc
    except JournalCorruptError as exc:
        emit_cli_error(
            error_code=E_JOURNAL_CORRUPT,
            message=str(exc),
            json_output=json_output,
            details={"kind": exc.kind, "line": exc.line, "detail": exc.detail},
        )
        raise typer.Exit(code=1) from exc

    try:
        append_step(
            run_dir,
            new_entries=result.new_entries,
            new_current_manifest=result.new_current_manifest,
            new_report_set=result.new_report_set,
            new_replay_bundle=result.new_replay_bundle,
        )
    except OSError as exc:
        emit_cli_operation_error(
            error_code=E_STEP_WRITE_FAILED,
            message=f"step failed to publish fixture updates in {run_dir}: {exc}",
            json_output=json_output,
            operation="append_step",
            path=run_dir,
            exc=exc,
        )
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(_step_summary_json(result))
    else:
        typer.echo(f"step: applied {result.steps_applied}, remaining {result.steps_remaining}")


def _preflight_step_replay_bundle(run_dir: Path, *, json_output: bool) -> None:
    """Reject invalid or non-plan replay bundles before entering the plan-only engine."""
    bundle_path = run_dir / "replay.json"
    try:
        bundle = REPLAY_BUNDLE_ADAPTER.validate_json(bundle_path.read_bytes())
    except (OSError, ValidationError) as exc:
        emit_cli_error(
            error_code=E_REPLAY_BUNDLE_INVALID,
            message=f"replay bundle is not parseable: {exc}",
            json_output=json_output,
            extra_top_level={"bundle_path": str(bundle_path)},
        )
        raise typer.Exit(code=1) from exc
    if isinstance(bundle, PlanOnlyReplayBundle):
        return
    mode = bundle.execution_mode.value
    emit_cli_error(
        error_code=E_STEP_UNSUPPORTED_MODE,
        message=f"step supports plan_only replay bundles only; got {mode}",
        json_output=json_output,
        details={
            "execution_mode": mode,
            "supported_execution_mode": ExecutionMode.PLAN_ONLY.value,
        },
    )
    raise typer.Exit(code=1)


def _step_summary_json(result: StepResult) -> str:
    payload = {
        "run_id": str(result.new_replay_bundle.run_id),
        "steps_applied": result.steps_applied,
        "steps_remaining": result.steps_remaining,
        "applied_events": result.new_replay_bundle.applied_events,
        "done": result.done,
    }
    return json.dumps(payload, sort_keys=True)
