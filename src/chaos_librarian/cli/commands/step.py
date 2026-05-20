"""``step`` command: advance a step-mode run by ``--next`` resolved events."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.cli._envelope import (
    E_JOURNAL_CORRUPT,
    E_SCENARIO_TAMPERED,
    E_SENTINEL_IN_PROGRESS,
    E_SENTINEL_INVALID,
    emit_cli_error,
)
from chaos_librarian.cli.app import app
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

    try:
        result = step_fixture(run_dir, n_steps=next_count)
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
