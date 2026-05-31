"""``replay`` command: rebuild a fixture from a recorded replay.json bundle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from chaos_librarian.cli._envelope import (
    E_MATERIALIZE_REPLAY_NOT_IMPLEMENTED,
    E_REPLAY_BUNDLE_INVALID,
    E_REPLAY_DIVERGENCE,
    E_REPLAY_WRITE_FAILED,
    emit_cli_error,
    emit_cli_operation_error,
)
from chaos_librarian.cli._materialization_errors import (
    exit_materialization_error,
    replay_command_report_dir,
)
from chaos_librarian.cli._render import validate_new_out_path
from chaos_librarian.cli._replay_io import REPLAY_BUNDLE_ADAPTER, infer_original
from chaos_librarian.cli.app import app
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.engine import (
    FixtureDiff,
    ReplayIntegrityError,
    compare_fixtures,
    compare_run_replay,
    replay_plan_bundle,
    write_fixture,
)
from chaos_librarian.materializer.errors import (
    MaterializationError,
)
from chaos_librarian.materializer.replay import replay_run_bundle


@app.command()
def replay(
    bundle: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=validate_new_out_path)],
    against: Annotated[Path | None, typer.Option("--against", exists=True, file_okay=False)] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Replay a recorded run from its replay.json bundle."""
    try:
        bundle_bytes = bundle.read_bytes()
    except OSError as exc:
        # Typer's ``exists=True`` is pre-checked, but the file can become
        # unreadable (race, permission drop) between that check and here.
        emit_cli_error(
            error_code=E_REPLAY_BUNDLE_INVALID,
            message=f"replay bundle is not readable: {exc}",
            json_output=json_output,
            extra_top_level={"bundle_path": str(bundle)},
        )
        raise typer.Exit(code=1) from exc
    try:
        parsed_any = REPLAY_BUNDLE_ADAPTER.validate_json(bundle_bytes)
    except ValidationError as exc:
        emit_cli_error(
            error_code=E_REPLAY_BUNDLE_INVALID,
            message=f"replay bundle is not parseable: {exc}",
            json_output=json_output,
            extra_top_level={"bundle_path": str(bundle)},
        )
        raise typer.Exit(code=1) from exc
    if isinstance(parsed_any, MaterializeReplayBundle):
        _replay_materialize_bundle(parsed_any, out, against, json_output)
        return
    parsed_bundle = parsed_any
    try:
        artifacts = replay_plan_bundle(parsed_bundle)
    except ReplayIntegrityError as exc:
        emit_cli_error(
            error_code=E_REPLAY_DIVERGENCE,
            message=str(exc),
            json_output=json_output,
            details={"kind": "integrity", "recorded_run_id": str(parsed_bundle.run_id)},
        )
        raise typer.Exit(code=6) from exc

    try:
        write_fixture(out, artifacts, parsed_bundle.scenario.encode("utf-8"))
    except OSError as exc:
        emit_cli_operation_error(
            error_code=E_REPLAY_WRITE_FAILED,
            message=f"replay failed to write fixture {out}: {exc}",
            json_output=json_output,
            operation="write_fixture",
            path=out,
            exc=exc,
        )
        raise typer.Exit(code=1) from exc

    target = against or infer_original(bundle, parsed_bundle.run_id, parsed_bundle.applied_events)
    if target is not None:
        diff = compare_fixtures(target, out)
        if not diff.is_clean():
            _emit_replay_diff(diff, run_id=str(parsed_bundle.run_id), json_output=json_output)
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


def _replay_materialize_bundle(
    bundle: MaterializeReplayBundle,
    out: Path,
    against: Path | None,
    json_output: bool,
) -> None:
    if bundle.execution_mode is not ExecutionMode.RUN:
        emit_cli_error(
            error_code=E_MATERIALIZE_REPLAY_NOT_IMPLEMENTED,
            message="materialize replay is not implemented in this CLI build",
            json_output=json_output,
            details={"execution_mode": bundle.execution_mode.value},
        )
        raise typer.Exit(code=1)
    try:
        replay_run_bundle(bundle, out)
    except ReplayIntegrityError as exc:
        emit_cli_error(
            error_code=E_REPLAY_DIVERGENCE,
            message=str(exc),
            json_output=json_output,
            details={"kind": "integrity", "recorded_run_id": str(bundle.run_id)},
        )
        raise typer.Exit(code=6) from exc
    except MaterializationError as exc:
        exit_materialization_error(
            exc,
            json_output=json_output,
            run_dir=replay_command_report_dir(exc, out),
        )
    if against is not None:
        diff = compare_run_replay(against, out)
        if not diff.is_clean():
            _emit_replay_diff(diff, run_id=str(bundle.run_id), json_output=json_output)
            raise typer.Exit(code=6)
    if json_output:
        typer.echo(
            json.dumps(
                {
                    "out": str(out.resolve()),
                    "run_id": str(bundle.run_id),
                    "compared_against": str(against) if against else None,
                },
                sort_keys=True,
            )
        )
    else:
        typer.echo(f"replay: wrote {out}")


def _emit_replay_diff(diff: FixtureDiff, *, run_id: str, json_output: bool) -> None:
    file_summaries: list[dict[str, object]] = [
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
    ]
    emit_cli_error(
        error_code=E_REPLAY_DIVERGENCE,
        message=f"{len(diff.files)} files differ",
        json_output=json_output,
        details={
            "kind": "artifact_diff",
            "run_id": run_id,
            "left_dir": str(diff.left_dir.resolve()),
            "right_dir": str(diff.right_dir.resolve()),
            "files": file_summaries,
        },
    )
