"""Fixture-directory writer for plan-only runs.

Stages the plan-only artifacts under a sibling temp directory and
atomically renames it onto ``<out_dir>``:

1. ``scenario.yaml`` (verbatim source bytes)
2. ``replay.json``
3. ``manifest.initial.json``
4. ``manifest.current.json``
5. ``journal.jsonl``
6. ``validation.json``
7. ``reports/{assets,works,variants,bundles}/<id>.json`` (Sprint 4)
8. ``.chaos-librarian-run`` (sentinel, written LAST inside staging)

The single ``Path.replace`` makes publication atomic on POSIX and macOS:
observers see either nothing or every file. Any failure during staging
triggers ``shutil.rmtree`` so a partial fixture cannot persist.

JSON canonicalization is centralized in ``_emit_json`` /  ``_emit_jsonl``
so every Sprint 3 artifact serializes the same way: ``indent=2``,
``by_alias=True``, ``exclude_none=True``, trailing ``"\n"``. This is what
makes plan-only output bit-identical.

``append_step`` (Sprint 4) updates an existing fixture in place when the
engine advances by one step: it rewrites ``manifest.current.json``,
``replay.json`` and every report file via sibling-tempfile + rename
(per-file atomic), and appends the new entries to ``journal.jsonl``.
Not atomic across files — recovery is by re-running the step.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.plan import PlanArtifacts
from chaos_librarian.engine.reports import ReportSet


def write_fixture(
    out_dir: Path,
    artifacts: PlanArtifacts,
    scenario_yaml_bytes: bytes,
) -> None:
    """Persist a PlanArtifacts result to disk atomically.

    Args:
        out_dir: Target directory. MUST NOT already exist; the function
            creates it (via atomic rename from staging) and refuses to
            overwrite.
        artifacts: The result of ``run_plan``.
        scenario_yaml_bytes: Verbatim source YAML bytes, written to
            ``scenario.yaml`` without modification.

    Raises:
        FileExistsError: If ``out_dir`` already exists.
    """
    if out_dir.exists():
        raise FileExistsError(f"refusing to write into existing directory: {out_dir}")

    staging = Path(tempfile.mkdtemp(prefix=".chaos-librarian-staging-", dir=out_dir.parent))
    try:
        (staging / "scenario.yaml").write_bytes(scenario_yaml_bytes)
        _emit_json(artifacts.replay_bundle, staging / "replay.json")
        _emit_json(artifacts.initial_manifest, staging / "manifest.initial.json")
        _emit_json(artifacts.current_manifest, staging / "manifest.current.json")
        _emit_jsonl(artifacts.journal, staging / "journal.jsonl")
        _emit_json(artifacts.validation_report, staging / "validation.json")
        _stage_reports(staging, artifacts.reports)
        _emit_sentinel(staging, artifacts.sentinel)
        staging.replace(out_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _emit_sentinel(out_dir: Path, sentinel: RunSentinel) -> None:
    """Write the sentinel into the staging directory last."""
    target = out_dir / ".chaos-librarian-run"
    payload = sentinel.model_dump_json(indent=2, by_alias=True, exclude_none=True) + "\n"
    target.write_text(payload)


def _emit_json(model: BaseModel, target: Path) -> None:
    """Write one Pydantic model as canonical JSON with trailing newline."""
    payload = model.model_dump_json(indent=2, by_alias=True, exclude_none=True) + "\n"
    target.write_text(payload)


def _emit_jsonl(entries: Iterable[JournalEntry], target: Path) -> None:
    """Write each entry as one canonical-JSON line; empty iter writes an empty file."""
    target.write_bytes(serialize_journal_bytes(entries))


def _stage_reports(staging: Path, reports: ReportSet) -> None:
    """Stage every per-entity report under ``staging/reports/<kind>/<id>.json``."""
    reports_root = staging / "reports"
    (reports_root / "assets").mkdir(parents=True)
    (reports_root / "works").mkdir()
    (reports_root / "variants").mkdir()
    (reports_root / "bundles").mkdir()
    for asset_report in reports.assets:
        _emit_json(asset_report, reports_root / "assets" / f"{asset_report.asset_id}.json")
    for work_report in reports.works:
        _emit_json(work_report, reports_root / "works" / f"{work_report.work_id}.json")
    for variant_report in reports.variants:
        _emit_json(variant_report, reports_root / "variants" / f"{variant_report.variant_id}.json")
    for bundle_report in reports.bundles:
        _emit_json(bundle_report, reports_root / "bundles" / f"{bundle_report.bundle_id}.json")


def append_step(
    run_dir: Path,
    *,
    new_entries: Iterable[JournalEntry],
    new_current_manifest: Manifest,
    new_report_set: ReportSet,
    new_replay_bundle: PlanOnlyReplayBundle,
) -> None:
    """Update an existing plan-only fixture with a step's new journal entries.

    Rewrites the four mutable files atomically per-file (sibling tempfile +
    ``Path.replace``) and appends the new journal lines. Not atomic *across*
    files; the documented recovery rule is that the next ``step --next``
    re-derives state from the journal — see
    docs/superpowers/specs/2026-05-18-sprint-4-design.md "Edge case 12".

    Args:
        run_dir: An existing fixture directory created by ``write_fixture``.
        new_entries: Journal entries to append to ``journal.jsonl``.
        new_current_manifest: Manifest after the step's events.
        new_report_set: Report set after the step's events.
        new_replay_bundle: Replay bundle with updated applied_events and
            recomputed run_id.
    """
    _replace_atomic(run_dir / "manifest.current.json", _emit_to_str(new_current_manifest))
    _replace_atomic(run_dir / "replay.json", _emit_to_str(new_replay_bundle))
    _replace_atomic_reports(run_dir / "reports", new_report_set)
    _append_journal_lines(run_dir / "journal.jsonl", new_entries)


def _emit_to_str(model: BaseModel) -> str:
    """Same canonical JSON form as ``_emit_json`` but returned as text."""
    return model.model_dump_json(indent=2, by_alias=True, exclude_none=True) + "\n"


def _replace_atomic(target: Path, content: str) -> None:
    """Write ``content`` to a sibling tempfile and rename onto ``target``."""
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(target)


def _replace_atomic_reports(reports_root: Path, reports: ReportSet) -> None:
    """Per-file atomic rewrite of every report under ``reports_root``."""
    for asset_report in reports.assets:
        _replace_atomic(
            reports_root / "assets" / f"{asset_report.asset_id}.json",
            _emit_to_str(asset_report),
        )
    for work_report in reports.works:
        _replace_atomic(
            reports_root / "works" / f"{work_report.work_id}.json",
            _emit_to_str(work_report),
        )
    for variant_report in reports.variants:
        _replace_atomic(
            reports_root / "variants" / f"{variant_report.variant_id}.json",
            _emit_to_str(variant_report),
        )
    for bundle_report in reports.bundles:
        _replace_atomic(
            reports_root / "bundles" / f"{bundle_report.bundle_id}.json",
            _emit_to_str(bundle_report),
        )


def _append_journal_lines(target: Path, entries: Iterable[JournalEntry]) -> None:
    """Append serialised journal lines to ``target`` (no rewrite of existing bytes)."""
    suffix = serialize_journal_bytes(entries)
    if not suffix:
        return
    with target.open("ab") as fh:
        fh.write(suffix)
