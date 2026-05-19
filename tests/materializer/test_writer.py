"""Layer 3 — materializer writer atomicity + sentinel flip."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from chaos_librarian.contract import (
    MATERIALIZATION_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
    RUN_SENTINEL_SCHEMA_VERSION,
)
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.materialization import (
    MaterializationReport,
    Outcome,
    ToolchainInfo,
)
from chaos_librarian.contract.replay_bundle import (
    ExecutionMode,
    MaterializeReplayBundle,
)
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.materializer.writer import (
    SENTINEL_FILENAME,
    MaterializeMetadata,
    begin_materialize_run,
    cleanup_failed_run,
)


def _sentinel(state: Literal["in_progress", "complete"]) -> RunSentinel:
    return RunSentinel(
        run_id=uuid.uuid4(),
        schema_version=RUN_SENTINEL_SCHEMA_VERSION,
        created_by="chaos-librarian-test",
        created_at=datetime(2026, 5, 18, 0, 0, 0, tzinfo=UTC),
        state=state,
    )


def test_begin_creates_run_dir_with_in_progress_sentinel(tmp_path: Path) -> None:
    """WHY: the in_progress sentinel is the marker that future tooling
    uses to detect interrupted materialize runs (Finding 2). It must be
    on disk before any ffmpeg subprocess starts."""
    out_dir = tmp_path / "run"
    sentinel = _sentinel("in_progress")
    begin_materialize_run(out_dir, sentinel)
    assert out_dir.exists()
    assert (out_dir / "library").is_dir()
    sentinel_path = out_dir / SENTINEL_FILENAME
    assert sentinel_path.exists()
    payload = json.loads(sentinel_path.read_text())
    assert payload["state"] == "in_progress"


def test_begin_refuses_existing_out_dir(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    sentinel = _sentinel("in_progress")
    try:
        begin_materialize_run(out_dir, sentinel)
    except FileExistsError:
        return
    raise AssertionError("begin_materialize_run should refuse existing dirs")


def test_cleanup_failed_run_writes_full_metadata(tmp_path: Path) -> None:
    """WHY: Finding 4 — ``clean`` requires ``replay.json`` and ``inspect``
    requires both ``replay.json`` and ``manifest.current.json``. A failure
    run-dir missing those files crashes the tooling. ``cleanup_failed_run``
    must emit every metadata file ``finalize_materialize_run`` does so the
    two run-dir shapes are uniform for downstream consumers."""
    out_dir = tmp_path / "failed_run"
    in_progress = _sentinel("in_progress")
    begin_materialize_run(out_dir, in_progress)
    # Drop a synthetic byte under library/ so the wipe is observable.
    (out_dir / "library" / "stale.bin").write_bytes(b"x")

    run_id = uuid.uuid4()
    manifest = Manifest(
        schema_version=2,
        works=[],
        variants=[],
        bundles=[],
        assets=[],
        versions=[],
        locations=[],
        sidecars=[],
    )
    validation_report = ValidationReport(
        schema_version=1,
        ok=True,
        scenario_id="static",
        issues=[],
    )
    materialization_report = MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        run_id=run_id,
        outcome=Outcome.TOOL_FAILED,
        platform="test",
        started_at=datetime(2026, 5, 18, 0, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 18, 0, 0, 1, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
        invocations=[],
        materialized=[],
        failures=[],
    )
    replay_bundle = MaterializeReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.1.0",
        scenario="schema_version: 2\nscenario_id: static\n",
        run_id=run_id,
        resolved_seed=1,
        journal_digest="0" * 64,
        execution_mode=ExecutionMode.MATERIALIZE,
        created_at=datetime(2026, 5, 18, 0, 0, 1, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
    )
    cleanup_failed_run(
        out_dir,
        MaterializeMetadata(
            initial_manifest=manifest,
            current_manifest=manifest,
            journal_entries=(),
            validation_report=validation_report,
            materialization_report=materialization_report,
            replay_bundle=replay_bundle,
            scenario_yaml_bytes=b"schema_version: 2\nscenario_id: static\n",
            sentinel=_sentinel("complete"),
        ),
    )
    # library/ wiped to empty, sentinel flipped.
    assert list((out_dir / "library").iterdir()) == []
    sentinel_payload = json.loads((out_dir / SENTINEL_FILENAME).read_text())
    assert sentinel_payload["state"] == "complete"
    # Every metadata file inspect/clean read exists.
    for name in (
        "scenario.yaml",
        "manifest.initial.json",
        "manifest.current.json",
        "journal.jsonl",
        "validation.json",
        "materialization.json",
        "replay.json",
    ):
        assert (out_dir / name).exists(), name
