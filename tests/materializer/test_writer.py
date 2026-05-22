"""Layer 3 — materializer writer atomicity + sentinel flip."""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

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
from chaos_librarian.contract.run_sentinel import RunSentinel, RunSentinelState
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.materializer.writer import (
    SENTINEL_FILENAME,
    MaterializeMetadata,
    WallClockBaselineMetadata,
    begin_materialize_run,
    cleanup_failed_phase_b_run,
    cleanup_failed_run,
    publish_wall_clock_baseline,
)


def _sentinel(state: RunSentinelState) -> RunSentinel:
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
    sentinel = _sentinel(RunSentinelState.IN_PROGRESS)
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
    sentinel = _sentinel(RunSentinelState.IN_PROGRESS)
    try:
        begin_materialize_run(out_dir, sentinel)
    except FileExistsError:
        return
    raise AssertionError("begin_materialize_run should refuse existing dirs")


def test_publish_wall_clock_baseline_renames_staging(tmp_path: Path) -> None:
    """WHY: wall-clock run publishes a replay-valid baseline before
    executing timed events. Interrupted runs must still expose coherent
    baseline metadata without materialization.json."""
    out_dir = tmp_path / "run"
    staging = tmp_path / ".staging"
    staging.mkdir()
    (staging / "library").mkdir()
    empty_journal_digest = hashlib.sha256(serialize_journal_bytes(())).hexdigest()
    metadata = WallClockBaselineMetadata(
        initial_manifest=Manifest(
            schema_version=4,
            works=[],
            variants=[],
            bundles=[],
            assets=[],
            versions=[],
            locations=[],
            sidecars=[],
        ),
        current_manifest=Manifest(
            schema_version=4,
            works=[],
            variants=[],
            bundles=[],
            assets=[],
            versions=[],
            locations=[],
            sidecars=[],
        ),
        validation_report=ValidationReport(schema_version=1, ok=True, scenario_id="x"),
        replay_bundle=MaterializeReplayBundle(
            schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
            chaos_librarian_version="0.1.0",
            scenario="schema_version: 6\nscenario_id: x\n",
            run_id=uuid.UUID("11111111-1111-4111-8111-111111111111"),
            resolved_seed=1,
            applied_events=0,
            journal_digest=empty_journal_digest,
            execution_mode=ExecutionMode.RUN,
            created_at=datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC),
            toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
        ),
        scenario_yaml_bytes=b"schema_version: 6\nscenario_id: x\n",
        sentinel=_sentinel(RunSentinelState.IN_PROGRESS),
    )
    publish_wall_clock_baseline(staging, out_dir, metadata)
    assert out_dir.exists()
    assert not staging.exists()
    assert (out_dir / "journal.jsonl").read_bytes() == b""
    assert not (out_dir / "materialization.json").exists()
    replay_payload = json.loads((out_dir / "replay.json").read_text(encoding="utf-8"))
    assert replay_payload["execution_mode"] == "run"
    assert replay_payload["applied_events"] == 0
    assert replay_payload["journal_digest"] == empty_journal_digest


def test_cleanup_failed_run_writes_full_metadata(tmp_path: Path) -> None:
    """WHY: Finding 4 — ``clean`` requires ``replay.json`` and ``inspect``
    requires both ``replay.json`` and ``manifest.current.json``. A failure
    run-dir missing those files crashes the tooling. ``cleanup_failed_run``
    must emit every metadata file ``finalize_materialize_run`` does so the
    two run-dir shapes are uniform for downstream consumers."""
    out_dir = tmp_path / "failed_run"
    in_progress = _sentinel(RunSentinelState.IN_PROGRESS)
    begin_materialize_run(out_dir, in_progress)
    # Drop a synthetic byte under library/ so the wipe is observable.
    (out_dir / "library" / "stale.bin").write_bytes(b"x")

    run_id = uuid.uuid4()
    manifest = Manifest(
        schema_version=4,
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
        scenario="schema_version: 6\nscenario_id: static\n",
        run_id=run_id,
        resolved_seed=1,
        applied_events=0,
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
            scenario_yaml_bytes=b"schema_version: 6\nscenario_id: static\n",
            sentinel=_sentinel(RunSentinelState.COMPLETE),
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


def test_cleanup_failed_phase_b_run_propagates_rmtree_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY: the asymmetric ``ignore_errors=True`` on the fs_failed wipe
    silently swallowed ``rmtree`` failures and still flipped the sentinel
    to ``complete``, even though ``library/`` was still partially
    populated. Downstream tooling reads ``outcome=fs_failed`` + a
    consistent sentinel and assumes the tree was wiped. Fail loud
    instead: surface the OSError so library/'s forensic state is
    preserved for investigation.

    Spy on ``shutil.rmtree``: assert ``ignore_errors=True`` is NOT
    passed (so a real ``shutil.rmtree`` would raise on a real error)
    AND that the simulated raise reaches the caller (so the sentinel
    is not flipped to ``complete``)."""
    out_dir = tmp_path / "fs_failed_run"
    in_progress = _sentinel(RunSentinelState.IN_PROGRESS)
    begin_materialize_run(out_dir, in_progress)
    (out_dir / "library" / "stale.bin").write_bytes(b"x")

    boom = OSError(13, "Permission denied")
    captured: dict[str, object] = {}

    def _spy_rmtree(path: object, *args: object, **kwargs: object) -> None:
        captured["path"] = path
        captured["args"] = args
        captured["kwargs"] = kwargs
        raise boom

    monkeypatch.setattr(shutil, "rmtree", _spy_rmtree)

    run_id = uuid.uuid4()
    manifest = Manifest(
        schema_version=4,
        works=[],
        variants=[],
        bundles=[],
        assets=[],
        versions=[],
        locations=[],
        sidecars=[],
    )
    validation_report = ValidationReport(schema_version=1, ok=True, scenario_id="static", issues=[])
    materialization_report = MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        run_id=run_id,
        outcome=Outcome.FS_FAILED,
        platform="test",
        started_at=datetime(2026, 5, 18, 0, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 18, 0, 0, 1, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
    )
    replay_bundle = MaterializeReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.1.0",
        scenario="schema_version: 6\nscenario_id: static\n",
        run_id=run_id,
        resolved_seed=1,
        applied_events=0,
        journal_digest="0" * 64,
        execution_mode=ExecutionMode.MATERIALIZE,
        created_at=datetime(2026, 5, 18, 0, 0, 1, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
    )
    metadata = MaterializeMetadata(
        initial_manifest=manifest,
        current_manifest=manifest,
        journal_entries=(),
        validation_report=validation_report,
        materialization_report=materialization_report,
        replay_bundle=replay_bundle,
        scenario_yaml_bytes=b"schema_version: 6\nscenario_id: static\n",
        sentinel=_sentinel(RunSentinelState.COMPLETE),
    )
    with pytest.raises(OSError, match="Permission denied") as exc_info:
        cleanup_failed_phase_b_run(out_dir, metadata)
    assert exc_info.value is boom
    # The fix is "drop ignore_errors=True"; with it passed, real rmtree
    # would silently swallow the OSError and the test would not surface
    # any failure.
    captured_kwargs = captured["kwargs"]
    assert isinstance(captured_kwargs, dict)
    assert "ignore_errors" not in captured_kwargs
    # Sentinel is still in_progress because the cleanup raised before flipping.
    sentinel_payload = json.loads((out_dir / SENTINEL_FILENAME).read_text())
    assert sentinel_payload["state"] == "in_progress"


def test_cleanup_failed_phase_b_run_handles_missing_library(tmp_path: Path) -> None:
    """WHY: an upstream failure may wipe ``library/`` before phase-B cleanup runs.

    Without a ``library.exists()`` guard, ``cleanup_failed_phase_b_run``
    crashes mid-cleanup with ``FileNotFoundError``, leaving the sentinel
    stuck at ``in_progress`` and the metadata unwritten. Mirror the
    sibling ``cleanup_failed_run`` shape: skip the rmtree silently when
    the library is already gone, still write metadata, flip the sentinel
    (PR #63 adversarial review, finding #5).
    """
    out_dir = tmp_path / "fs_failed_run"
    in_progress = _sentinel(RunSentinelState.IN_PROGRESS)
    begin_materialize_run(out_dir, in_progress)
    # Pre-remove library/ so the cleanup runs against a missing tree.
    shutil.rmtree(out_dir / "library")
    run_id = uuid.uuid4()
    manifest = Manifest(
        schema_version=4,
        works=[],
        variants=[],
        bundles=[],
        assets=[],
        versions=[],
        locations=[],
        sidecars=[],
    )
    validation_report = ValidationReport(schema_version=1, ok=True, scenario_id="static", issues=[])
    materialization_report = MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        run_id=run_id,
        outcome=Outcome.MEDIA_FAILED,
        platform="test",
        started_at=datetime(2026, 5, 18, 0, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 18, 0, 0, 1, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
    )
    replay_bundle = MaterializeReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.1.0",
        scenario="schema_version: 6\nscenario_id: static\n",
        run_id=run_id,
        resolved_seed=1,
        applied_events=0,
        journal_digest="0" * 64,
        execution_mode=ExecutionMode.MATERIALIZE,
        created_at=datetime(2026, 5, 18, 0, 0, 1, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
    )
    metadata = MaterializeMetadata(
        initial_manifest=manifest,
        current_manifest=manifest,
        journal_entries=(),
        validation_report=validation_report,
        materialization_report=materialization_report,
        replay_bundle=replay_bundle,
        scenario_yaml_bytes=b"schema_version: 6\nscenario_id: static\n",
        sentinel=_sentinel(RunSentinelState.COMPLETE),
    )
    cleanup_failed_phase_b_run(out_dir, metadata)
    # Metadata + sentinel were written even though library/ was already gone.
    sentinel_payload = json.loads((out_dir / SENTINEL_FILENAME).read_text())
    assert sentinel_payload["state"] == "complete"
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
