"""``clean`` command: remove a sentinel-protected run directory."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from chaos_librarian.cli._envelope import E_FIXTURE_INCONSISTENT, E_SENTINEL_INVALID, emit_cli_error
from chaos_librarian.cli._replay_io import REPLAY_BUNDLE_ADAPTER
from chaos_librarian.cli.app import app
from chaos_librarian.engine import SentinelInvalidError, verify_sentinel


@app.command()
def clean(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Remove a run directory (sentinel-protected)."""
    try:
        sentinel = verify_sentinel(run_dir)
    except SentinelInvalidError as exc:
        emit_cli_error(error_code=E_SENTINEL_INVALID, message=str(exc), json_output=json_output)
        raise typer.Exit(code=7) from exc

    replay_path = run_dir / "replay.json"
    if not replay_path.exists():
        emit_cli_error(
            error_code=E_FIXTURE_INCONSISTENT,
            message=f"replay.json missing: {replay_path}",
            json_output=json_output,
        )
        raise typer.Exit(code=7)
    try:
        bundle = REPLAY_BUNDLE_ADAPTER.validate_json(replay_path.read_bytes())
    except ValidationError as exc:
        emit_cli_error(
            error_code=E_FIXTURE_INCONSISTENT,
            message=f"replay.json unparseable: {exc}",
            json_output=json_output,
        )
        raise typer.Exit(code=7) from exc
    if bundle.run_id != sentinel.run_id:
        emit_cli_error(
            error_code=E_FIXTURE_INCONSISTENT,
            message=f"sentinel.run_id {sentinel.run_id} != replay.json run_id {bundle.run_id}",
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
