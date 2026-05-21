"""``run`` command: wall-clock-mode runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.cli._envelope import emit_cli_error, emit_materialize_error
from chaos_librarian.cli._render import validate_new_out_path
from chaos_librarian.cli.app import app
from chaos_librarian.clock import DurationParseError
from chaos_librarian.materializer import (
    CapabilityGateError,
    ContainmentViolationError,
    FilesystemActionError,
    MediaActionError,
    ProbeParseError,
    ScenarioValidationError,
    TimelineUnsupportedError,
    ToolFailedError,
    UnsupportedMaterializationError,
    WallClockUsageError,
    run_wall_clock_scenario,
)
from chaos_librarian.materializer.scheduler import SpeedParseError
from chaos_librarian.scenario_io import ScenarioLoadError
from chaos_librarian.validation.codes import E_YAML_PARSE
from chaos_librarian.validation.input import prepare_run_input_from_bytes


@app.command()
def run(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=validate_new_out_path)],
    duration: Annotated[str, typer.Option("--duration")],
    speed: Annotated[str, typer.Option("--speed")] = "1x",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Run a scenario in wall-clock mode."""
    try:
        artifacts = run_wall_clock_scenario(
            scenario,
            out,
            duration=duration,
            speed=speed,
        )
    except (DurationParseError, SpeedParseError, WallClockUsageError) as exc:
        raise typer.BadParameter(str(exc)) from exc
    except ScenarioLoadError as exc:
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
        emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=3) from exc
    except (
        TimelineUnsupportedError,
        UnsupportedMaterializationError,
        ToolFailedError,
        ProbeParseError,
        FilesystemActionError,
        MediaActionError,
    ) as exc:
        emit_materialize_error(exc, json_output=json_output, run_dir=out)
        raise typer.Exit(code=5) from exc
    except ContainmentViolationError as exc:
        emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=7) from exc

    if json_output:
        typer.echo(json.dumps(_success_payload(artifacts, out), sort_keys=True))
    else:
        typer.echo(f"run: wrote {out}")


def _success_payload(artifacts, out: Path) -> dict[str, object]:
    report = artifacts.materialization_report
    replay = artifacts.replay_bundle
    run_input = prepare_run_input_from_bytes(
        raw_bytes=replay.scenario.encode("utf-8"),
        source_label=f"run-summary:{replay.run_id}",
    )
    return {
        "ok": True,
        "run_id": str(report.run_id),
        "scenario_id": run_input.scenario.scenario_id,
        "out": str(out.resolve()),
        "execution_mode": report.execution_mode.value,
        "requested_duration_ns": report.requested_duration_ns,
        "actual_duration_ns": report.actual_duration_ns,
        "speed_multiplier": report.speed_multiplier,
        "applied_events": replay.applied_events,
        "overran_duration": report.overran_duration,
        "materialization_report_path": str((out / "materialization.json").resolve()),
        "replay_bundle_path": str((out / "replay.json").resolve()),
    }
