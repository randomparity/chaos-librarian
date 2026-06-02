"""``inspect`` command: emit a run-directory summary (D10 shape)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, cast

import typer
from pydantic import ValidationError

from chaos_librarian.cli._envelope import (
    E_FIXTURE_INCONSISTENT,
    E_REPLAY_BUNDLE_INVALID,
    E_SENTINEL_INVALID,
    emit_cli_error,
)
from chaos_librarian.cli._replay_io import REPLAY_BUNDLE_ADAPTER
from chaos_librarian.cli.app import app
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import ExecutionMode, ReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinelState
from chaos_librarian.engine import (
    SentinelInvalidError,
    resolve_timeline,
    step_boundaries,
    verify_sentinel,
)
from chaos_librarian.validation import RunInput, prepare_run_input_from_bytes
from chaos_librarian.validation.scenario_io import ScenarioLoadError


@dataclass(frozen=True)
class _InspectArtifactError(Exception):
    error_code: str
    message: str
    exit_code: int
    path_key: str
    path: Path


@app.command()
def inspect(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect a run directory."""
    try:
        summary = _build_inspect_summary(run_dir)
    except SentinelInvalidError as exc:
        emit_cli_error(error_code=E_SENTINEL_INVALID, message=str(exc), json_output=json_output)
        raise typer.Exit(code=7) from exc
    except _InspectArtifactError as exc:
        emit_cli_error(
            error_code=exc.error_code,
            message=exc.message,
            json_output=json_output,
            extra_top_level={exc.path_key: str(exc.path)},
        )
        raise typer.Exit(code=exc.exit_code) from exc

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
        _InspectArtifactError: persisted artifact read/parse failures after
            sentinel verification.
    """
    sentinel = verify_sentinel(run_dir)

    bundle = _load_replay_bundle(run_dir / "replay.json")
    manifest_current = _load_manifest(run_dir / "manifest.current.json")
    journal_entries = _count_journal_entries(run_dir / "journal.jsonl")
    run_input = _load_scenario_input(run_dir / "scenario.yaml")
    scenario = run_input.scenario
    resolved_timeline = resolve_timeline(scenario)
    boundaries = step_boundaries(resolved_timeline)
    applied_events = bundle.applied_events
    if (
        sentinel.state is RunSentinelState.IN_PROGRESS
        and bundle.execution_mode is ExecutionMode.RUN
    ):
        applied_events = journal_entries
    if applied_events == 0:
        applied_steps = 0
    elif applied_events in boundaries:
        applied_steps = boundaries.index(applied_events) + 1
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
        "applied_events": applied_events,
        "applied_steps": applied_steps,
        "steps_remaining": steps_remaining,
        "counts": {
            "movies": len(manifest_current.movies),
            "series": len(manifest_current.series),
            "seasons": len(manifest_current.seasons),
            "episodes": len(manifest_current.episodes),
            "artists": len(manifest_current.artists),
            "albums": len(manifest_current.albums),
            "discs": len(manifest_current.discs),
            "tracks": len(manifest_current.tracks),
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


def _load_replay_bundle(path: Path) -> ReplayBundle:
    try:
        return REPLAY_BUNDLE_ADAPTER.validate_json(path.read_bytes())
    except (OSError, ValidationError) as exc:
        raise _InspectArtifactError(
            error_code=E_REPLAY_BUNDLE_INVALID,
            message=f"replay bundle is not parseable: {exc}",
            exit_code=1,
            path_key="bundle_path",
            path=path,
        ) from exc


def _load_manifest(path: Path) -> Manifest:
    try:
        return Manifest.model_validate_json(path.read_text())
    except (OSError, ValidationError) as exc:
        raise _InspectArtifactError(
            error_code=E_FIXTURE_INCONSISTENT,
            message=f"manifest.current.json is not parseable: {exc}",
            exit_code=7,
            path_key="manifest_path",
            path=path,
        ) from exc


def _count_journal_entries(path: Path) -> int:
    try:
        journal_text = path.read_text()
    except (FileNotFoundError, OSError) as exc:
        raise _InspectArtifactError(
            error_code=E_FIXTURE_INCONSISTENT,
            message=f"journal.jsonl is not readable: {exc}",
            exit_code=7,
            path_key="journal_path",
            path=path,
        ) from exc
    return sum(1 for line in journal_text.splitlines() if line.strip())


def _load_scenario_input(path: Path) -> RunInput:
    try:
        scenario_bytes = path.read_bytes()
        run_input = prepare_run_input_from_bytes(
            raw_bytes=scenario_bytes,
            source_label=f"inspect:{path.parent}",
        )
        _ = run_input.scenario
        return run_input
    except (OSError, ScenarioLoadError, ValidationError) as exc:
        raise _InspectArtifactError(
            error_code=E_FIXTURE_INCONSISTENT,
            message=f"scenario.yaml is not parseable: {exc}",
            exit_code=7,
            path_key="scenario_path",
            path=path,
        ) from exc


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
        f"counts:           movies={counts['movies']} series={counts['series']} "
        f"seasons={counts['seasons']} episodes={counts['episodes']}"
    )
    typer.echo(
        f"                  artists={counts['artists']} albums={counts['albums']} "
        f"discs={counts['discs']} tracks={counts['tracks']} variants={counts['variants']} "
        f"bundles={counts['bundles']} assets={counts['assets']} sidecars={counts['sidecars']}"
    )
    sentinel = cast("dict[str, object]", summary["sentinel"])
    typer.echo(f"sentinel:         state={sentinel['state']} run_id={sentinel['run_id']}")
