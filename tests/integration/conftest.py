"""Shared helpers for Layer 4 integration tests.

The materialize pipeline writes a structured run-dir to disk; tests that
exercise the real ffmpeg toolchain need to read back into typed Pydantic
models for assertions. Centralizing the loaders here keeps each test
focused on behavior, not JSON-shape massaging.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import TypeAdapter

from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.materialization import MaterializationReport
from chaos_librarian.contract.replay_bundle import ReplayBundle
from chaos_librarian.contract.reports import AssetReport

_REPLAY_BUNDLE_ADAPTER: TypeAdapter[ReplayBundle] = TypeAdapter(ReplayBundle)


def sha256_of(path: Path) -> str:
    """Return ``sha256:<hex>`` over the file's bytes (matches manifest format)."""
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _load_current_manifest(out_dir: Path) -> Manifest:
    """Re-hydrate ``<out_dir>/manifest.current.json`` into a ``Manifest``."""
    return Manifest.model_validate_json((out_dir / "manifest.current.json").read_text())


def _load_asset_report(out_dir: Path, asset_id: str) -> AssetReport:
    """Re-hydrate ``<out_dir>/reports/assets/<asset_id>.json``."""
    return AssetReport.model_validate_json(
        (out_dir / "reports" / "assets" / f"{asset_id}.json").read_text()
    )


def _load_materialization_report(out_dir: Path) -> MaterializationReport:
    """Re-hydrate ``materialization.json``."""
    return MaterializationReport.model_validate_json((out_dir / "materialization.json").read_text())


def _load_replay_bundle(out_dir: Path) -> ReplayBundle:
    """Re-hydrate ``replay.json`` through the discriminated-union adapter.

    ``ReplayBundle`` is ``Annotated[... , Field(discriminator="execution_mode")]``
    so the loader picks ``MaterializeReplayBundle`` or ``PlanOnlyReplayBundle``
    based on the on-disk discriminator.
    """
    payload = json.loads((out_dir / "replay.json").read_text())
    return _REPLAY_BUNDLE_ADAPTER.validate_python(payload)


def _initial_sha256_for(asset_id: str, out_dir: Path) -> str:
    """Look up ``asset_id``'s phase-A content_hash from ``materialization.json``.

    Filesystem-mutation actions in Sprint 6 preserve bytes (move/rename
    are renames, slow-copy preserves content), so the post-phase-B file
    must hash to the same value the materializer recorded after phase A.
    Tests use this to assert "the file at the final path is the same
    file the materializer produced, just relocated".
    """
    report = _load_materialization_report(out_dir)
    for materialized in report.materialized:
        if materialized.asset_id == asset_id:
            return materialized.content_hash
    raise AssertionError(
        f"no MaterializedAsset for {asset_id!r} in materialization.json "
        f"(materialized: {[m.asset_id for m in report.materialized]!r})"
    )
