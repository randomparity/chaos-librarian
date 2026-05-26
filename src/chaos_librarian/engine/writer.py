"""Fixture-directory writer for plan-only runs.

Stages the plan-only artifacts under a sibling temp directory and
atomically renames it onto ``<out_dir>``:

1. ``scenario.yaml`` (verbatim source bytes)
2. ``replay.json``
3. ``manifest.initial.json``
4. ``manifest.current.json``
5. ``journal.jsonl``
6. ``validation.json``
7. ``reports/{assets,movies,series,seasons,episodes,artists,albums,discs,tracks,
   variants,bundles}/<id>.json``
8. ``.chaos-librarian-run`` (sentinel, written LAST inside staging)

The single ``Path.replace`` makes publication atomic on POSIX and macOS:
observers see either nothing or every file. Any failure during staging
triggers ``shutil.rmtree`` so a partial fixture cannot persist.

JSON canonicalization is centralized in ``_emit_json`` /  ``_emit_jsonl``
so every Sprint 3 artifact serializes the same way: ``indent=2``,
``by_alias=True``, optional ``None`` values omitted, required nullable
fields preserved, trailing ``"\n"``. This is what makes plan-only output
bit-identical.

``append_step`` (Sprint 4) updates an existing fixture in place when the
engine advances by one step: it rewrites ``manifest.current.json``,
``replay.json`` and every report file via sibling-tempfile + rename
(per-file atomic), and appends the new entries to ``journal.jsonl``.
Not atomic across files — recovery is by re-running the step.
"""

from __future__ import annotations

import json
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

REPORT_DIRS = (
    "assets",
    "movies",
    "series",
    "seasons",
    "episodes",
    "artists",
    "albums",
    "discs",
    "tracks",
    "variants",
    "bundles",
)


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


def canonical_json(model: BaseModel) -> str:
    """Canonical text form of a Pydantic model: indent=2, by_alias, trailing newline."""
    payload = _dump_preserving_required_nulls(model)
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _dump_preserving_required_nulls(model: BaseModel) -> dict[str, object]:
    raw = model.model_dump(mode="json", by_alias=True, exclude_none=False)
    if not isinstance(raw, dict):
        raise TypeError(f"expected object dump for {type(model).__name__}")
    return dict(_iter_serialized_fields(model, raw))


def _iter_serialized_fields(
    model: BaseModel,
    raw: dict[str, object],
) -> Iterable[tuple[str, object]]:
    fields = type(model).model_fields.items()
    for (field_name, field), (key, raw_value) in zip(fields, raw.items(), strict=True):
        value = getattr(model, field_name)
        if value is None:
            if field.is_required():
                yield key, None
            continue
        yield key, _dump_value_preserving_required_nulls(value, raw_value)


def _dump_value_preserving_required_nulls(value: object, raw_value: object) -> object:
    if isinstance(value, BaseModel):
        return _dump_preserving_required_nulls(value)
    if isinstance(value, list | tuple):
        if not isinstance(raw_value, list):
            return raw_value
        return [
            _dump_value_preserving_required_nulls(item, raw_item)
            for item, raw_item in zip(value, raw_value, strict=True)
        ]
    return raw_value


def replace_atomic_text(target: Path, content: str) -> None:
    """Write ``content`` to a sibling tempfile and rename onto ``target`` (per-file atomic)."""
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(target)


def replace_atomic_bytes(target: Path, content: bytes) -> None:
    """Write ``content`` bytes to a sibling tempfile and rename onto ``target``."""
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(target)


def _emit_sentinel(out_dir: Path, sentinel: RunSentinel) -> None:
    (out_dir / ".chaos-librarian-run").write_text(canonical_json(sentinel))


def _emit_json(model: BaseModel, target: Path) -> None:
    target.write_text(canonical_json(model))


def _emit_jsonl(entries: Iterable[JournalEntry], target: Path) -> None:
    target.write_bytes(serialize_journal_bytes(entries))


def _stage_reports(staging: Path, reports: ReportSet) -> None:
    """Stage every per-entity report under ``staging/reports/<kind>/<id>.json``."""
    reports_root = staging / "reports"
    for name in REPORT_DIRS:
        (reports_root / name).mkdir(parents=True, exist_ok=True)
    for directory, report_id, report in _iter_report_files(reports):
        _emit_json(report, reports_root / directory / f"{report_id}.json")


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
    replace_atomic_text(run_dir / "manifest.current.json", canonical_json(new_current_manifest))
    replace_atomic_text(run_dir / "replay.json", canonical_json(new_replay_bundle))
    _replace_atomic_reports(run_dir / "reports", new_report_set)
    _append_journal_lines(run_dir / "journal.jsonl", new_entries)


def _replace_atomic_reports(reports_root: Path, reports: ReportSet) -> None:
    for directory, report_id, report in _iter_report_files(reports):
        replace_atomic_text(
            reports_root / directory / f"{report_id}.json",
            canonical_json(report),
        )


def _iter_report_files(reports: ReportSet) -> Iterable[tuple[str, str, BaseModel]]:
    for report in reports.assets:
        yield "assets", report.asset_id, report
    for report in reports.movies:
        yield "movies", report.movie_id, report
    for report in reports.series:
        yield "series", report.series_id, report
    for report in reports.seasons:
        yield "seasons", report.season_id, report
    for report in reports.episodes:
        yield "episodes", report.episode_id, report
    for report in reports.artists:
        yield "artists", report.artist_id, report
    for report in reports.albums:
        yield "albums", report.album_id, report
    for report in reports.discs:
        yield "discs", report.disc_id, report
    for report in reports.tracks:
        yield "tracks", report.track_id, report
    for report in reports.variants:
        yield "variants", report.variant_id, report
    for report in reports.bundles:
        yield "bundles", report.bundle_id, report


def _append_journal_lines(target: Path, entries: Iterable[JournalEntry]) -> None:
    """Append serialised journal lines to ``target`` (no rewrite of existing bytes)."""
    suffix = serialize_journal_bytes(entries)
    if not suffix:
        return
    with target.open("ab") as fh:
        fh.write(suffix)
