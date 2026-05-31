"""``materialize`` command: synthesize real media from a static scenario."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.cli._envelope import emit_cli_error
from chaos_librarian.cli._materialization_errors import (
    exit_materialization_error,
    materialize_command_report_dir,
)
from chaos_librarian.cli._render import validate_new_out_path
from chaos_librarian.cli.app import app
from chaos_librarian.materializer import (
    MaterializationError,
    materialize_scenario,
)
from chaos_librarian.scenario_io import ScenarioLoadError
from chaos_librarian.validation.codes import E_YAML_PARSE


@app.command()
def materialize(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=validate_new_out_path)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Materialize a scenario (creates real media files)."""
    try:
        artifacts = materialize_scenario(scenario, out)
    except ScenarioLoadError as exc:
        # Mirror ``validate`` / ``plan``: unparseable or unreadable YAML
        # fails fast with E_YAML_PARSE and exit 3, routed through the
        # unified envelope.
        emit_cli_error(
            error_code=E_YAML_PARSE,
            message=str(exc),
            json_output=json_output,
            extra_top_level={"scenario_path": str(scenario)},
        )
        raise typer.Exit(code=3) from exc
    except MaterializationError as exc:
        exit_materialization_error(
            exc,
            json_output=json_output,
            run_dir=materialize_command_report_dir(exc, out),
        )

    if json_output:
        typer.echo(artifacts.materialization_report.model_dump_json(indent=2, exclude_none=True))
    else:
        typer.echo(f"materialize: wrote {out}")
