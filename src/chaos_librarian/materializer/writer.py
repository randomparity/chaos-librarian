"""Materialize-mode atomic write helpers.

Unlike ``engine.writer`` (plan-only, single staging-rename), materialize
writes the library tree in-place during synthesis. This module brackets
that: ``begin_materialize_run`` creates the run-dir and writes an
in-progress sentinel; ``finalize_materialize_run`` writes the rest of
the metadata atomically and flips the sentinel to ``complete``;
``cleanup_failed_run`` wipes ``library/`` on caught failure and writes
the failure-decorated metadata.

The two write entry points consume ``MaterializeMetadata`` (file-by-file
contents shared by both paths) and, for the success path,
``MaterializeReports`` (per-entity report dicts). Bundling these into
dataclasses cuts the previous 12-kwarg sprawl down to a positional
arg + dataclass at each call site (issue #12).
"""

from __future__ import annotations

import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

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
from chaos_librarian.contract.run_sentinel import SENTINEL_FILENAME, RunSentinel
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.writer import (
    canonical_json,
    replace_atomic_bytes,
    replace_atomic_text,
)

__all__ = [
    "SENTINEL_FILENAME",
    "MaterializeMetadata",
    "MaterializeReports",
    "begin_materialize_run",
    "cleanup_failed_phase_b_run",
    "cleanup_failed_run",
    "finalize_materialize_run",
]


@dataclass(frozen=True, slots=True)
class MaterializeMetadata:
    """The file-by-file contents the writer persists.

    Shared between the success path (``finalize_materialize_run``) and
    the caught-failure path (``cleanup_failed_run``); the only success-only
    artifacts are the per-entity reports, which travel in
    ``MaterializeReports``.
    """

    initial_manifest: Manifest
    current_manifest: Manifest
    journal_entries: Iterable[JournalEntry]
    validation_report: ValidationReport
    materialization_report: MaterializationReport
    replay_bundle: MaterializeReplayBundle
    scenario_yaml_bytes: bytes
    sentinel: RunSentinel


@dataclass(frozen=True, slots=True)
class MaterializeReports:
    """Per-entity report dicts written only on the success path."""

    assets: dict[str, AssetReport]
    works: dict[str, WorkReport]
    variants: dict[str, VariantReport]
    bundles: dict[str, BundleReport]


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
    metadata: MaterializeMetadata,
    reports: MaterializeReports,
) -> None:
    """Write metadata atomically and replace the sentinel with state='complete'."""
    _write_shared_metadata(out_dir, metadata)
    _write_reports(out_dir, reports)
    # Sentinel last — the moment readers can trust the dir.
    replace_atomic_text(out_dir / SENTINEL_FILENAME, canonical_json(metadata.sentinel))


def cleanup_failed_run(out_dir: Path, metadata: MaterializeMetadata) -> None:
    """Wipe ``library/``, write every metadata file, and flip the sentinel
    to ``complete``.

    The failure run-dir must be readable by ``inspect`` and removable by
    ``clean``. Both commands hard-require ``replay.json`` and
    ``manifest.current.json``; emitting them on caught failure keeps the
    failure run-dir uniform with the success run-dir from a tooling
    perspective — ``inspect <failed-run>`` shows the same shape, just with
    ``outcome != "success"``. The metadata's ``current_manifest`` is the
    un-augmented plan-only manifest (no ``content_hash`` / ``probed``).

    Reports under ``reports/`` are deliberately NOT written here: emitting
    them on a failed run is correctness-neutral and adds complexity. Skip
    them — the spec's failure-outcome rule only requires the metadata
    files that ``inspect`` and ``clean`` consume.
    """
    library = out_dir / "library"
    if library.exists():
        shutil.rmtree(library)
    library.mkdir()  # empty placeholder so the run-dir shape stays stable
    _write_shared_metadata(out_dir, metadata)
    # Sentinel last — the moment readers can trust the dir.
    replace_atomic_text(out_dir / SENTINEL_FILENAME, canonical_json(metadata.sentinel))


def cleanup_failed_phase_b_run(out_dir: Path, metadata: MaterializeMetadata) -> None:
    """Wipe ``library/`` entirely (no placeholder), write metadata, flip sentinel.

    Used by the phase-B failure path (filesystem OR media). Unlike
    ``cleanup_failed_run``, no empty ``library/`` directory is recreated:
    a phase-B crash leaves the run-dir in a state where the
    partially-mutated tree is gone, and the rest of the metadata
    describes the failure (``outcome=fs_failed`` or ``media_failed``)
    for ``inspect`` and ``clean`` consumers.

    On ``rmtree`` failure the OSError surfaces to the caller; the
    partially-wiped library is visible for forensic inspection. The
    sentinel stays at ``in_progress`` so downstream tooling cannot
    mistake the half-cleaned run-dir for a completed failure record.
    """
    library = out_dir / "library"
    shutil.rmtree(library)
    _write_shared_metadata(out_dir, metadata)
    # Sentinel last — the moment readers can trust the dir.
    replace_atomic_text(out_dir / SENTINEL_FILENAME, canonical_json(metadata.sentinel))


def _write_shared_metadata(out_dir: Path, metadata: MaterializeMetadata) -> None:
    """Persist every file shared between the success and failure paths."""
    replace_atomic_bytes(out_dir / "scenario.yaml", metadata.scenario_yaml_bytes)
    replace_atomic_text(
        out_dir / "manifest.initial.json", canonical_json(metadata.initial_manifest)
    )
    replace_atomic_text(
        out_dir / "manifest.current.json", canonical_json(metadata.current_manifest)
    )
    replace_atomic_bytes(
        out_dir / "journal.jsonl", serialize_journal_bytes(metadata.journal_entries)
    )
    replace_atomic_text(out_dir / "validation.json", canonical_json(metadata.validation_report))
    replace_atomic_text(
        out_dir / "materialization.json", canonical_json(metadata.materialization_report)
    )
    replace_atomic_text(out_dir / "replay.json", canonical_json(metadata.replay_bundle))


def _write_reports(out_dir: Path, reports: MaterializeReports) -> None:
    reports_dir = out_dir / "reports"
    for sub in ("assets", "works", "variants", "bundles"):
        (reports_dir / sub).mkdir(parents=True, exist_ok=True)
    for asset_id, report in reports.assets.items():
        replace_atomic_text(reports_dir / "assets" / f"{asset_id}.json", canonical_json(report))
    for work_id, report in reports.works.items():
        replace_atomic_text(reports_dir / "works" / f"{work_id}.json", canonical_json(report))
    for variant_id, report in reports.variants.items():
        replace_atomic_text(reports_dir / "variants" / f"{variant_id}.json", canonical_json(report))
    for bundle_id, report in reports.bundles.items():
        replace_atomic_text(reports_dir / "bundles" / f"{bundle_id}.json", canonical_json(report))
