"""``compare`` command: compare an oracle fixture to observed consumer state."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.adapter import (
    AdapterInputError,
    CompareMode,
    compare_fixture_to_observed,
    load_fixture,
    load_observed_state,
)
from chaos_librarian.cli._envelope import E_SENTINEL_INVALID, emit_cli_error
from chaos_librarian.cli.app import app
from chaos_librarian.engine import SentinelInvalidError


@app.command()
def compare(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    observed: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    mode: Annotated[CompareMode, typer.Option("--mode")] = CompareMode.FINAL_STATE,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Compare a run directory against consumer observed-state JSON."""
    try:
        fixture = load_fixture(run_dir)
        observed_state = load_observed_state(observed)
        report = compare_fixture_to_observed(fixture, observed_state, mode=mode)
    except SentinelInvalidError as exc:
        emit_cli_error(error_code=E_SENTINEL_INVALID, message=str(exc), json_output=json_output)
        raise typer.Exit(code=7) from exc
    except AdapterInputError as exc:
        emit_cli_error(
            error_code=exc.error_code,
            message=exc.message,
            json_output=json_output,
            details=exc.details,
        )
        raise typer.Exit(code=1) from exc

    if json_output:
        typer.echo(report.model_dump_json(indent=2, exclude_none=True))
    else:
        _render_human(
            report.ok,
            len(report.findings),
            [finding.message for finding in report.findings],
        )
    if not report.ok:
        raise typer.Exit(code=6)


def _render_human(ok: bool, finding_count: int, messages: list[str]) -> None:
    status = "ok" if ok else "divergence"
    typer.echo(f"compare: {status} ({finding_count} findings)")
    for message in messages:
        typer.echo(f"- {message}")
