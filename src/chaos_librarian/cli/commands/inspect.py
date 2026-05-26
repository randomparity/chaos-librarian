"""``inspect`` command: emit a run-directory summary (D10 shape)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, cast

import typer

from chaos_librarian.cli._envelope import E_SENTINEL_INVALID, emit_cli_error
from chaos_librarian.cli._replay_io import REPLAY_BUNDLE_ADAPTER
from chaos_librarian.cli.app import app
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import ExecutionMode
from chaos_librarian.contract.run_sentinel import RunSentinelState
from chaos_librarian.engine import (
    SentinelInvalidError,
    resolve_timeline,
    step_boundaries,
    verify_sentinel,
)
from chaos_librarian.validation import prepare_run_input_from_bytes


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
    sentinel = verify_sentinel(run_dir)

    bundle = REPLAY_BUNDLE_ADAPTER.validate_json((run_dir / "replay.json").read_bytes())
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
