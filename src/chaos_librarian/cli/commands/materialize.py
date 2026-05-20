"""``materialize`` command: synthesize real media from a static scenario."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.cli._envelope import emit_cli_error, emit_materialize_error
from chaos_librarian.cli._render import validate_new_out_path
from chaos_librarian.cli.app import app
from chaos_librarian.materializer import (
    CapabilityGateError,
    ContainmentViolationError,
    FilesystemActionError,
    ProbeParseError,
    ScenarioValidationError,
    TimelineUnsupportedError,
    ToolFailedError,
    UnsupportedMaterializationError,
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
    except CapabilityGateError as exc:
        emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=4) from exc
    except ScenarioValidationError as exc:
        # Mirror ``plan``'s exit code (3) for semantic-validation failures so
        # downstream agents key off the same convention.
        emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=3) from exc
    except TimelineUnsupportedError as exc:
        emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=5) from exc
    except UnsupportedMaterializationError as exc:
        emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=5) from exc
    except ToolFailedError as exc:
        emit_materialize_error(exc, json_output=json_output, run_dir=out)
        raise typer.Exit(code=5) from exc
    except ProbeParseError as exc:
        emit_materialize_error(exc, json_output=json_output, run_dir=out)
        raise typer.Exit(code=5) from exc
    except FilesystemActionError as exc:
        # Phase B has already wiped library/ and written the failure
        # report; surface E_MATERIALIZE_FS_FAILED with run_dir=out so the
        # envelope advertises materialization_report_path.
        emit_materialize_error(exc, json_output=json_output, run_dir=out)
        raise typer.Exit(code=5) from exc
    except ContainmentViolationError as exc:
        emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=7) from exc

    if json_output:
        typer.echo(artifacts.materialization_report.model_dump_json(indent=2, exclude_none=True))
    else:
        typer.echo(f"materialize: wrote {out}")
