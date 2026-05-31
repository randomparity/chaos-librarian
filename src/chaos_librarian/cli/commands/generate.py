"""``generate`` command: write deterministic fuzz scenario YAML."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.cli._envelope import E_GENERATE_FAILED, emit_cli_error
from chaos_librarian.cli._render import validate_new_out_path
from chaos_librarian.cli.app import app
from chaos_librarian.contract.profiles import FUZZ_LANES_BY_PROFILE, FuzzLaneName, FuzzProfileName
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.generation import (
    BatchItem,
    generate_scenario,
    generated_scenario_summary,
    plan_generation_batch,
    scenario_id_for,
    write_generated_scenario,
)


@app.command()
def generate(
    profile: Annotated[FuzzProfileName, typer.Option("--profile")],
    seed: Annotated[int, typer.Option("--seed", min=0)],
    out: Annotated[Path, typer.Option("--out")],
    lane: Annotated[FuzzLaneName | None, typer.Option("--lane")] = None,
    count: Annotated[int, typer.Option("--count", min=1, max=1000)] = 1,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Generate one or more deterministic fuzz scenario YAML files.

    With ``--count 1`` (default) ``--out`` is a new file. With ``--count > 1``
    ``--out`` is an existing directory and each scenario is written as
    ``<scenario_id>.yaml``.
    """
    resolved_lane = _resolve_lane_for_batch(profile=profile, lane=lane, count=count)
    items = plan_generation_batch(profile=profile, lane=resolved_lane, seed=seed, count=count)
    if count == 1:
        _write_single(profile=profile, item=items[0], out=out, json_output=json_output)
        return
    _write_batch(profile=profile, items=items, out_dir=out, json_output=json_output)


def _resolve_lane_for_batch(
    profile: FuzzProfileName, lane: FuzzLaneName | None, count: int
) -> FuzzLaneName | None:
    """Validate and resolve ``--lane``; return ``None`` to cycle the lane order."""
    if lane is not None:
        if lane not in FUZZ_LANES_BY_PROFILE[profile]:
            raise typer.BadParameter(f"lane {lane.value} is not valid for {profile.value}")
        return lane
    if profile is FuzzProfileName.FUZZ_SMOKE:
        return FuzzLaneName.SMOKE
    if count == 1:
        raise typer.BadParameter("--lane is required for fuzz-regression")
    return None


def _write_single(profile: FuzzProfileName, item: BatchItem, out: Path, json_output: bool) -> None:
    validate_new_out_path(out)
    generated = generate_scenario(profile=profile, lane=item.lane, seed=item.seed)
    write_generated_scenario(out, generated.data)
    if json_output:
        typer.echo(generated_scenario_summary(out, generated.data, scenario=generated.scenario))
    else:
        typer.echo(f"generate: wrote {out}")


def _write_batch(
    profile: FuzzProfileName,
    items: tuple[BatchItem, ...],
    out_dir: Path,
    json_output: bool,
) -> None:
    _validate_out_dir(out_dir)
    targets = _batch_targets(profile=profile, items=items, out_dir=out_dir)
    written: list[Path] = []
    records: list[tuple[Path, bytes, Scenario]] = []
    for item, path in targets:
        try:
            generated = generate_scenario(profile=profile, lane=item.lane, seed=item.seed)
            _assert_scenario_id(
                profile=profile, item=item, generated_id=generated.scenario.scenario_id
            )
            write_generated_scenario(path, generated.data)
        except Exception as exc:  # rollback then re-report any generation/write failure
            removed, unremoved = _rollback(written)
            emit_cli_error(
                error_code=E_GENERATE_FAILED,
                message=_batch_failure_message(
                    profile=profile,
                    item=item,
                    exc=exc,
                    removed=removed,
                    unremoved=unremoved,
                ),
                json_output=json_output,
                details=_batch_failure_details(
                    profile=profile,
                    item=item,
                    path=path,
                    exc=exc,
                    removed=removed,
                    unremoved=unremoved,
                ),
            )
            raise typer.Exit(code=1) from exc
        written.append(path)
        records.append((path, generated.data, generated.scenario))
        if not json_output:
            typer.echo(f"generate: wrote {path}")
    if json_output:
        typer.echo(_batch_summary_json(out_dir, records))
    else:
        typer.echo(f"generate: wrote {len(records)} scenarios to {out_dir}")


def _validate_out_dir(out_dir: Path) -> None:
    if not out_dir.exists():
        raise typer.BadParameter(f"--out directory does not exist: {out_dir}")
    if not out_dir.is_dir():
        raise typer.BadParameter(f"--out is not a directory: {out_dir}")


def _batch_targets(
    profile: FuzzProfileName, items: tuple[BatchItem, ...], out_dir: Path
) -> list[tuple[BatchItem, Path]]:
    targets: list[tuple[BatchItem, Path]] = []
    names: set[str] = set()
    for item in items:
        name = f"{scenario_id_for(profile, item.lane, item.seed)}.yaml"
        if name in names:
            raise RuntimeError(f"batch produced a duplicate file name: {name}")
        names.add(name)
        path = out_dir / name
        if path.exists():
            raise typer.BadParameter(f"--out already contains target file: {path}")
        targets.append((item, path))
    return targets


def _assert_scenario_id(profile: FuzzProfileName, item: BatchItem, generated_id: str) -> None:
    expected = scenario_id_for(profile, item.lane, item.seed)
    if generated_id != expected:
        raise RuntimeError(
            f"generated scenario_id {generated_id!r} does not match planned {expected!r}"
        )


def _rollback(written: list[Path]) -> tuple[list[Path], list[Path]]:
    """Best-effort remove this batch's files; return ``(removed, unremoved)``.

    Unlink failures are reported via ``unremoved`` rather than swallowed, so the
    caller can warn that the directory was not left fully clean.
    """
    removed: list[Path] = []
    unremoved: list[Path] = []
    for path in written:
        try:
            path.unlink(missing_ok=True)
            removed.append(path)
        except OSError:
            unremoved.append(path)
    return removed, unremoved


def _batch_failure_message(
    *,
    profile: FuzzProfileName,
    item: BatchItem,
    exc: Exception,
    removed: list[Path],
    unremoved: list[Path],
) -> str:
    message = (
        f"generate failed at profile={profile.value} lane={item.lane.value} seed={item.seed}: {exc}"
    )
    if removed:
        message += f"; rolled back {len(removed)} partially written files"
    if unremoved:
        message += (
            f"; could not remove {len(unremoved)} files during rollback "
            "(remove them before re-running)"
        )
    return message


def _batch_failure_details(
    *,
    profile: FuzzProfileName,
    item: BatchItem,
    path: Path,
    exc: Exception,
    removed: list[Path],
    unremoved: list[Path],
) -> dict[str, object]:
    return {
        "profile": profile.value,
        "lane": item.lane.value,
        "seed": item.seed,
        "target_path": str(path),
        "exception_type": type(exc).__name__,
        "removed_paths": [str(path) for path in removed],
        "unremoved_paths": [str(path) for path in unremoved],
    }


def _batch_summary_json(out_dir: Path, records: list[tuple[Path, bytes, Scenario]]) -> str:
    scenarios = [
        json.loads(generated_scenario_summary(path, data, scenario=scenario))
        for path, data, scenario in records
    ]
    scenarios.sort(key=lambda summary: summary["scenario_path"])
    payload: dict[str, object] = {
        "ok": True,
        "count": len(scenarios),
        "out_dir": str(out_dir.resolve()),
        "scenarios": scenarios,
    }
    return json.dumps(payload, sort_keys=True)
