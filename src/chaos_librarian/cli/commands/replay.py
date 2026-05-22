"""``replay`` command: rebuild a fixture from a recorded replay.json bundle."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, cast

import typer
from pydantic import TypeAdapter, ValidationError

from chaos_librarian.cli._envelope import (
    E_MATERIALIZE_REPLAY_NOT_IMPLEMENTED,
    E_REPLAY_BUNDLE_INVALID,
    E_REPLAY_DIVERGENCE,
    emit_cli_error,
)
from chaos_librarian.cli._render import validate_new_out_path
from chaos_librarian.cli._replay_io import REPLAY_BUNDLE_ADAPTER, infer_original
from chaos_librarian.cli.app import app
from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.engine import (
    FixtureDiff,
    FixtureFileDiff,
    ReplayIntegrityError,
    compare_fixtures,
    replay_plan_bundle,
    write_fixture,
)
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.materializer.replay import replay_run_bundle

_JOURNAL_ADAPTER = TypeAdapter(JournalEntry)
_RUN_REPLAY_COMPARE_KEYS = frozenset(
    {
        "scenario",
        "run_id",
        "resolved_seed",
        "applied_events",
        "journal_digest",
        "execution_mode",
    }
)
_CORRUPTION_COMPARE_FIELDS = (
    "event_id",
    "action",
    "target_asset_id",
    "input_path",
    "output_path",
    "input_version_id",
    "output_version_id",
    "input_content_hash",
    "output_content_hash",
    "corruptor",
    "byte_start",
    "byte_count",
    "seed_material",
    "probe_outcome",
    "probe_error_tail",
)


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

    write_fixture(out, artifacts, parsed_bundle.scenario.encode("utf-8"))

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


def compare_run_replay(left_dir: Path, right_dir: Path) -> FixtureDiff:
    """Compare run replay outputs while ignoring wall-clock-only volatility."""
    diffs: list[FixtureFileDiff] = []
    _compare_json(
        diffs,
        left_dir,
        right_dir,
        "manifest.current.json",
        normalizer=lambda data: data,
    )
    _compare_json(
        diffs,
        left_dir,
        right_dir,
        "replay.json",
        normalizer=lambda data: {key: data.get(key) for key in _RUN_REPLAY_COMPARE_KEYS},
    )
    _compare_journal(diffs, left_dir, right_dir)
    _compare_json(
        diffs,
        left_dir,
        right_dir,
        "materialization.json",
        normalizer=_normalize_materialization_for_run_replay,
    )
    _compare_tree_bytes(diffs, left_dir, right_dir, "library")
    return FixtureDiff(left_dir=left_dir, right_dir=right_dir, files=tuple(diffs))


def _normalize_materialization_for_run_replay(data: dict[str, object]) -> dict[str, object]:
    actions = data.get("corruption_actions", [])
    if not isinstance(actions, list):
        actions = []
    normalized_actions: list[dict[str, object]] = []
    for action in actions:
        normalized = _normalize_corruption_action(action)
        if normalized is not None:
            normalized_actions.append(normalized)
    return {
        "outcome": data.get("outcome"),
        "execution_mode": data.get("execution_mode"),
        "corruption_actions": normalized_actions,
    }


def _normalize_corruption_action(action: object) -> dict[str, object] | None:
    if not isinstance(action, dict):
        return None
    action_data = cast("dict[str, object]", action)
    return {field: action_data.get(field) for field in _CORRUPTION_COMPARE_FIELDS}


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


def _compare_json(
    diffs: list[FixtureFileDiff],
    left_dir: Path,
    right_dir: Path,
    rel: str,
    *,
    normalizer,
) -> None:
    left = left_dir / rel
    right = right_dir / rel
    if not _record_missing(diffs, left, right, rel):
        return
    left_blob = _canonical_compare_json(normalizer(json.loads(left.read_text(encoding="utf-8"))))
    right_blob = _canonical_compare_json(normalizer(json.loads(right.read_text(encoding="utf-8"))))
    if left_blob != right_blob:
        diffs.append(_diff(rel, left_blob, right_blob))


def _compare_journal(diffs: list[FixtureFileDiff], left_dir: Path, right_dir: Path) -> None:
    rel = "journal.jsonl"
    left = left_dir / rel
    right = right_dir / rel
    if not _record_missing(diffs, left, right, rel):
        return
    left_blob = _normalized_journal_bytes(left)
    right_blob = _normalized_journal_bytes(right)
    if left_blob != right_blob:
        diffs.append(_diff(rel, left_blob, right_blob))


def _compare_tree_bytes(
    diffs: list[FixtureFileDiff],
    left_dir: Path,
    right_dir: Path,
    rel_root: str,
) -> None:
    left_files = _collect_files(left_dir / rel_root)
    right_files = _collect_files(right_dir / rel_root)
    for rel in sorted(left_files | right_files):
        fixture_rel = f"{rel_root}/{rel}"
        left = left_dir / fixture_rel
        right = right_dir / fixture_rel
        if not _record_missing(diffs, left, right, fixture_rel):
            continue
        left_blob = left.read_bytes()
        right_blob = right.read_bytes()
        if left_blob != right_blob:
            diffs.append(_diff(fixture_rel, left_blob, right_blob))


def _collect_files(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()}


def _normalized_journal_bytes(path: Path) -> bytes:
    entries = [
        _JOURNAL_ADAPTER.validate_json(line).model_copy(update={"wall_clock_time": None})
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return serialize_journal_bytes(entries)


def _canonical_compare_json(data: object) -> bytes:
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _record_missing(
    diffs: list[FixtureFileDiff],
    left: Path,
    right: Path,
    rel: str,
) -> bool:
    if left.exists() and right.exists():
        return True
    if not left.exists():
        diffs.append(
            FixtureFileDiff(
                path=rel,
                kind="missing_in_left",
                left_bytes=None,
                right_bytes=right.stat().st_size if right.exists() else None,
                first_diff_line=None,
                preview_left=None,
                preview_right=None,
            )
        )
        return False
    diffs.append(
        FixtureFileDiff(
            path=rel,
            kind="missing_in_right",
            left_bytes=left.stat().st_size,
            right_bytes=None,
            first_diff_line=None,
            preview_left=None,
            preview_right=None,
        )
    )
    return False


def _diff(rel: str, left: bytes, right: bytes) -> FixtureFileDiff:
    return FixtureFileDiff(
        path=rel,
        kind="byte_diff",
        left_bytes=len(left),
        right_bytes=len(right),
        first_diff_line=None,
        preview_left=None,
        preview_right=None,
    )
