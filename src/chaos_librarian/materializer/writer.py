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
from collections.abc import Iterable
from pathlib import Path
from typing import Final

from chaos_librarian.contract.journal import JournalEntry
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
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.writer import (
    canonical_json,
    replace_atomic_bytes,
    replace_atomic_text,
)

SENTINEL_FILENAME: Final = ".chaos-librarian-run"


def begin_materialize_run(out_dir: Path, sentinel: RunSentinel) -> None:
    """Create ``out_dir`` with an in-progress sentinel.

    Library subdir is created here too because ffmpeg requires its parent.
    Raises ``FileExistsError`` if ``out_dir`` exists.
    """
    out_dir.mkdir(parents=True)
    (out_dir / "library").mkdir()
    replace_atomic_text(out_dir / SENTINEL_FILENAME, canonical_json(sentinel))


def finalize_materialize_run(
    out_dir: Path,
    *,
    initial_manifest: Manifest,
    current_manifest: Manifest,
    journal_entries: Iterable[JournalEntry],
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
    replace_atomic_bytes(out_dir / "scenario.yaml", scenario_yaml_bytes)
    replace_atomic_text(out_dir / "manifest.initial.json", canonical_json(initial_manifest))
    replace_atomic_text(out_dir / "manifest.current.json", canonical_json(current_manifest))
    replace_atomic_bytes(out_dir / "journal.jsonl", serialize_journal_bytes(journal_entries))
    replace_atomic_text(out_dir / "validation.json", canonical_json(validation_report))
    replace_atomic_text(out_dir / "materialization.json", canonical_json(materialization_report))
    replace_atomic_text(out_dir / "replay.json", canonical_json(replay_bundle))
    _write_reports(out_dir, asset_reports, work_reports, variant_reports, bundle_reports)
    # Sentinel last — the moment readers can trust the dir.
    replace_atomic_text(out_dir / SENTINEL_FILENAME, canonical_json(sentinel))


def cleanup_failed_run(
    out_dir: Path,
    *,
    initial_manifest: Manifest,
    current_manifest: Manifest,
    journal_entries: Iterable[JournalEntry],
    validation_report: ValidationReport,
    materialization_report: MaterializationReport,
    replay_bundle: MaterializeReplayBundle,
    scenario_yaml_bytes: bytes,
    sentinel: RunSentinel,
) -> None:
    """Wipe ``library/``, write every metadata file, and flip the sentinel
    to ``complete``.

    The failure run-dir must be readable by ``inspect`` and removable by
    ``clean``. Both commands hard-require ``replay.json`` and
    ``manifest.current.json``; emitting them on caught failure keeps the
    failure run-dir uniform with the success run-dir from a tooling
    perspective — ``inspect <failed-run>`` shows the same shape, just with
    ``outcome != "success"``. ``current_manifest`` is the un-augmented
    plan-only manifest (no ``content_hash`` / ``probed`` fields populated).

    Reports under ``reports/`` are deliberately NOT written here: emitting
    them on a failed run is correctness-neutral and adds complexity. Skip
    them — the spec's failure-outcome rule only requires the metadata
    files that ``inspect`` and ``clean`` consume.
    """
    library = out_dir / "library"
    if library.exists():
        shutil.rmtree(library)
    library.mkdir()  # empty placeholder so the run-dir shape stays stable
    replace_atomic_bytes(out_dir / "scenario.yaml", scenario_yaml_bytes)
    replace_atomic_text(out_dir / "manifest.initial.json", canonical_json(initial_manifest))
    replace_atomic_text(out_dir / "manifest.current.json", canonical_json(current_manifest))
    replace_atomic_bytes(out_dir / "journal.jsonl", serialize_journal_bytes(journal_entries))
    replace_atomic_text(out_dir / "validation.json", canonical_json(validation_report))
    replace_atomic_text(out_dir / "materialization.json", canonical_json(materialization_report))
    replace_atomic_text(out_dir / "replay.json", canonical_json(replay_bundle))
    # Sentinel last — the moment readers can trust the dir.
    replace_atomic_text(out_dir / SENTINEL_FILENAME, canonical_json(sentinel))


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
        replace_atomic_text(reports_dir / "assets" / f"{asset_id}.json", canonical_json(report))
    for work_id, report in works.items():
        replace_atomic_text(reports_dir / "works" / f"{work_id}.json", canonical_json(report))
    for variant_id, report in variants.items():
        replace_atomic_text(reports_dir / "variants" / f"{variant_id}.json", canonical_json(report))
    for bundle_id, report in bundles.items():
        replace_atomic_text(reports_dir / "bundles" / f"{bundle_id}.json", canonical_json(report))
