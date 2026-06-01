"""``generate`` command: write deterministic fuzz scenario YAML."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.cli._envelope import (
    E_GENERATE_FAILED,
    emit_cli_error,
    emit_cli_operation_error,
)
from chaos_librarian.cli._render import validate_new_out_path
from chaos_librarian.cli.app import app
from chaos_librarian.contract.profiles import FUZZ_LANES_BY_PROFILE, FuzzLaneName, FuzzProfileName
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.generation import (
    GenerationBatchItem,
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
    planned_items = plan_generation_batch(
        profile=profile,
        seed=seed,
        count=count,
        lane=resolved_lane,
    )
    if count == 1:
        _write_single(profile=profile, planned=planned_items[0], out=out, json_output=json_output)
        return
    _write_batch(
        profile=profile,
        planned_items=planned_items,
        out_dir=out,
        json_output=json_output,
    )


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


def _write_single(
    profile: FuzzProfileName,
    planned: GenerationBatchItem,
    out: Path,
    json_output: bool,
) -> None:
    validate_new_out_path(out)
    try:
        generated = generate_scenario(profile=profile, lane=planned.lane, seed=planned.seed)
    except Exception as exc:
        _emit_single_generate_failure(
            profile=profile,
            planned=planned,
            out=out,
            operation="generate_scenario",
            exc=exc,
            json_output=json_output,
        )
        raise typer.Exit(code=1) from exc
    try:
        write_generated_scenario(out, generated.yaml_bytes)
    except OSError as exc:
        _emit_single_generate_failure(
            profile=profile,
            planned=planned,
            out=out,
            operation="write_generated_scenario",
            exc=exc,
            json_output=json_output,
        )
        raise typer.Exit(code=1) from exc
    if json_output:
        typer.echo(
            generated_scenario_summary(
                out,
                generated.yaml_bytes,
                scenario=generated.scenario,
            )
        )
    else:
        typer.echo(f"generate: wrote {out}")


def _write_batch(
    profile: FuzzProfileName,
    planned_items: tuple[GenerationBatchItem, ...],
    out_dir: Path,
    json_output: bool,
) -> None:
    _validate_out_dir(out_dir)
    targets = _batch_targets(profile=profile, planned_items=planned_items, out_dir=out_dir)
    written: list[Path] = []
    records: list[tuple[Path, bytes, Scenario]] = []
    for planned, path in targets:
        try:
            generated = generate_scenario(profile=profile, lane=planned.lane, seed=planned.seed)
            _assert_scenario_id(
                profile=profile,
                planned=planned,
                generated_id=generated.scenario.scenario_id,
            )
            write_generated_scenario(path, generated.yaml_bytes)
        except Exception as exc:  # rollback then re-report any generation/write failure
            removed, unremoved = _rollback(written)
            emit_cli_error(
                error_code=E_GENERATE_FAILED,
                message=_batch_failure_message(
                    profile=profile,
                    planned=planned,
                    exc=exc,
                    removed=removed,
                    unremoved=unremoved,
                ),
                json_output=json_output,
                details=_batch_failure_details(
                    profile=profile,
                    planned=planned,
                    path=path,
                    exc=exc,
                    removed=removed,
                    unremoved=unremoved,
                ),
            )
            raise typer.Exit(code=1) from exc
        written.append(path)
        records.append((path, generated.yaml_bytes, generated.scenario))
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
    profile: FuzzProfileName,
    planned_items: tuple[GenerationBatchItem, ...],
    out_dir: Path,
) -> list[tuple[GenerationBatchItem, Path]]:
    targets: list[tuple[GenerationBatchItem, Path]] = []
    names: set[str] = set()
    for planned in planned_items:
        name = f"{scenario_id_for(profile, planned.seed, planned.lane)}.yaml"
        if name in names:
            raise RuntimeError(f"batch produced a duplicate file name: {name}")
        names.add(name)
        path = out_dir / name
        if path.exists():
            raise typer.BadParameter(f"--out already contains target file: {path}")
        targets.append((planned, path))
    return targets


def _assert_scenario_id(
    profile: FuzzProfileName,
    planned: GenerationBatchItem,
    generated_id: str,
) -> None:
    expected = scenario_id_for(profile, planned.seed, planned.lane)
    if generated_id != expected:
        raise RuntimeError(
            f"generated scenario_id {generated_id!r} does not match planned {expected!r}"
        )


def _emit_single_generate_failure(
    *,
    profile: FuzzProfileName,
    planned: GenerationBatchItem,
    out: Path,
    operation: str,
    exc: Exception,
    json_output: bool,
) -> None:
    emit_cli_operation_error(
        error_code=E_GENERATE_FAILED,
        message=_single_failure_message(profile=profile, planned=planned, exc=exc),
        json_output=json_output,
        operation=operation,
        path=out,
        exc=exc,
        extra_details={
            "profile": profile.value,
            "lane": planned.lane.value,
            "seed": planned.seed,
        },
    )


def _single_failure_message(
    *,
    profile: FuzzProfileName,
    planned: GenerationBatchItem,
    exc: Exception,
) -> str:
    return (
        f"generate failed at profile={profile.value} lane={planned.lane.value} "
        f"seed={planned.seed}: {exc}"
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
    planned: GenerationBatchItem,
    exc: Exception,
    removed: list[Path],
    unremoved: list[Path],
) -> str:
    message = (
        f"generate failed at profile={profile.value} lane={planned.lane.value} "
        f"seed={planned.seed}: {exc}"
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
    planned: GenerationBatchItem,
    path: Path,
    exc: Exception,
    removed: list[Path],
    unremoved: list[Path],
) -> dict[str, object]:
    return {
        "profile": profile.value,
        "lane": planned.lane.value,
        "seed": planned.seed,
        "target_path": str(path),
        "exception_type": type(exc).__name__,
        "removed_paths": [str(path) for path in removed],
        "unremoved_paths": [str(path) for path in unremoved],
    }


def _batch_summary_json(out_dir: Path, records: list[tuple[Path, bytes, Scenario]]) -> str:
    scenarios = [
        json.loads(generated_scenario_summary(path, yaml_bytes, scenario=scenario))
        for path, yaml_bytes, scenario in records
    ]
    scenarios.sort(key=lambda summary: summary["scenario_path"])
    payload: dict[str, object] = {
        "ok": True,
        "count": len(scenarios),
        "out_dir": str(out_dir.resolve()),
        "scenarios": scenarios,
    }
    return json.dumps(payload, sort_keys=True)
