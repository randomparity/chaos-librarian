"""Materialize-mode atomic write helpers.

Unlike ``engine.writer`` (plan-only, single staging-rename), materialize
writes the library tree in-place during synthesis. This module brackets
that: ``begin_materialize_run`` creates the run-dir and writes an
in-progress sentinel; ``finalize_materialize_run`` writes the rest of
the metadata atomically and flips the sentinel to ``complete``;
``cleanup_failed_run`` wipes ``library/`` on caught failure and writes
the failure-decorated metadata.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.materialization import MaterializationReport
from chaos_librarian.contract.replay_bundle import MaterializeReplayBundle
from chaos_librarian.contract.reports import (
    AssetReport,
    BundleReport,
    VariantReport,
    WorkReport,
)
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.validation import ValidationReport

SENTINEL_FILENAME: Final = ".chaos-librarian-run"


def _canonical(model: BaseModel) -> str:
    return model.model_dump_json(indent=2, by_alias=True, exclude_none=True) + "\n"


def _atomic_write_text(target: Path, content: str) -> None:
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(target)


def _atomic_write_bytes(target: Path, content: bytes) -> None:
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(target)


def begin_materialize_run(out_dir: Path, sentinel: RunSentinel) -> None:
    """Create ``out_dir`` with an in-progress sentinel.

    Library subdir is created here too because ffmpeg requires its parent.
    Raises ``FileExistsError`` if ``out_dir`` exists.
    """
    out_dir.mkdir(parents=True)
    (out_dir / "library").mkdir()
    _atomic_write_text(out_dir / SENTINEL_FILENAME, _canonical(sentinel))


def finalize_materialize_run(
    out_dir: Path,
    *,
    initial_manifest: Manifest,
    current_manifest: Manifest,
    journal_lines: list[str],
    validation_report: ValidationReport,
    materialization_report: MaterializationReport,
    replay_bundle: MaterializeReplayBundle,
    scenario_yaml_bytes: bytes,
    sentinel: RunSentinel,
    asset_reports: dict[str, AssetReport],
    work_reports: dict[str, WorkReport],
    variant_reports: dict[str, VariantReport],
    bundle_reports: dict[str, BundleReport],
) -> None:
    """Write metadata atomically and replace the sentinel with state='complete'."""
    _atomic_write_bytes(out_dir / "scenario.yaml", scenario_yaml_bytes)
    _atomic_write_text(out_dir / "manifest.initial.json", _canonical(initial_manifest))
    _atomic_write_text(out_dir / "manifest.current.json", _canonical(current_manifest))
    _atomic_write_text(out_dir / "journal.jsonl", "".join(journal_lines))
    _atomic_write_text(out_dir / "validation.json", _canonical(validation_report))
    _atomic_write_text(out_dir / "materialization.json", _canonical(materialization_report))
    _atomic_write_text(out_dir / "replay.json", _canonical(replay_bundle))
    _write_reports(out_dir, asset_reports, work_reports, variant_reports, bundle_reports)
    # Sentinel last — the moment readers can trust the dir.
    _atomic_write_text(out_dir / SENTINEL_FILENAME, _canonical(sentinel))


def cleanup_failed_run(
    out_dir: Path,
    *,
    initial_manifest: Manifest,
    current_manifest: Manifest,
    journal_lines: list[str],
    validation_report: ValidationReport,
    materialization_report: MaterializationReport,
    replay_bundle: MaterializeReplayBundle,
    scenario_yaml_bytes: bytes,
    sentinel: RunSentinel,
) -> None:
    """Wipe ``library/``, write every metadata file, and flip the sentinel
    to ``complete``.

    The failure run-dir must be readable by ``inspect`` and removable by
    ``clean`` (Finding 4). Both commands hard-require ``replay.json`` and
    ``manifest.current.json``; emitting them on caught failure keeps the
    failure run-dir uniform with the success run-dir from a tooling
    perspective — ``inspect <failed-run>`` shows the same shape, just with
    ``outcome != "success"``. ``current_manifest`` is the un-augmented
    plan-only manifest (no ``content_hash`` / ``probed`` fields populated).

    Reports under ``reports/`` are deliberately NOT written here: Sprint
    4's ``build_report_set`` runs over the un-augmented manifest cleanly,
    but emitting them on a failed run is correctness-neutral and adds
    complexity. Skip them — the spec's failure-outcome rule only requires
    the metadata files that ``inspect`` and ``clean`` consume.
    """
    library = out_dir / "library"
    if library.exists():
        shutil.rmtree(library)
    library.mkdir()  # empty placeholder so the run-dir shape stays stable
    _atomic_write_bytes(out_dir / "scenario.yaml", scenario_yaml_bytes)
    _atomic_write_text(out_dir / "manifest.initial.json", _canonical(initial_manifest))
    _atomic_write_text(out_dir / "manifest.current.json", _canonical(current_manifest))
    _atomic_write_text(out_dir / "journal.jsonl", "".join(journal_lines))
    _atomic_write_text(out_dir / "validation.json", _canonical(validation_report))
    _atomic_write_text(out_dir / "materialization.json", _canonical(materialization_report))
    _atomic_write_text(out_dir / "replay.json", _canonical(replay_bundle))
    # Sentinel last — the moment readers can trust the dir.
    _atomic_write_text(out_dir / SENTINEL_FILENAME, _canonical(sentinel))


def _write_reports(
    out_dir: Path,
    assets: dict[str, AssetReport],
    works: dict[str, WorkReport],
    variants: dict[str, VariantReport],
    bundles: dict[str, BundleReport],
) -> None:
    reports_dir = out_dir / "reports"
    for sub in ("assets", "works", "variants", "bundles"):
        (reports_dir / sub).mkdir(parents=True, exist_ok=True)
    for asset_id, report in assets.items():
        _atomic_write_text(reports_dir / "assets" / f"{asset_id}.json", _canonical(report))
    for work_id, report in works.items():
        _atomic_write_text(reports_dir / "works" / f"{work_id}.json", _canonical(report))
    for variant_id, report in variants.items():
        _atomic_write_text(reports_dir / "variants" / f"{variant_id}.json", _canonical(report))
    for bundle_id, report in bundles.items():
        _atomic_write_text(reports_dir / "bundles" / f"{bundle_id}.json", _canonical(report))
