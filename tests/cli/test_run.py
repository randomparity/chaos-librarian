"""Layer 5 — run CLI with wall-clock orchestrator mocked."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli import commands as commands_pkg
from chaos_librarian.cli.app import app
from chaos_librarian.contract import (
    MANIFEST_SCHEMA_VERSION,
    MATERIALIZATION_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
)
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.materialization import (
    MaterializationExecutionMode,
    MaterializationReport,
    Outcome,
    ToolchainInfo,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.materializer import MaterializeArtifacts
from chaos_librarian.materializer.errors import (
    CapabilityGateError,
    ContainmentViolationError,
    CorruptionActionError,
    ScenarioValidationError,
    TimelineUnsupportedError,
    UnsupportedMaterializationError,
)

app_mod = commands_pkg.run

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
RUN_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _success(out: Path) -> MaterializeArtifacts:
    report = MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        run_id=RUN_ID,
        outcome=Outcome.SUCCESS,
        platform="test",
        started_at=datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 21, 0, 0, 1, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
        requested_duration_ns=1_000_000_000,
        actual_duration_ns=1_000_000_000,
        speed_multiplier="10",
        overran_duration=False,
        content_sources=[],
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay = MaterializeReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.1.0",
        scenario=(FIXTURE_DIR / "identity-move-rename.yaml").read_text(encoding="utf-8"),
        run_id=RUN_ID,
        resolved_seed=1,
        applied_events=2,
        journal_digest="0" * 64,
        execution_mode=ExecutionMode.RUN,
        created_at=datetime(2026, 5, 21, 0, 0, 1, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
        content_sources=[],
    )
    out.mkdir()
    (out / "materialization.json").write_text("{}", encoding="utf-8")
    (out / "replay.json").write_text("{}", encoding="utf-8")
    return MaterializeArtifacts(
        current_manifest=Manifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            movies=[],
            series=[],
            seasons=[],
            episodes=[],
            artists=[],
            albums=[],
            discs=[],
            tracks=[],
            variants=[],
            bundles=[],
            assets=[],
            versions=[],
            locations=[],
            sidecars=[],
        ),
        materialization_report=report,
        replay_bundle=replay,
    )


def _raise(exc: Exception):
    def _inner(*_args, **_kwargs):
        raise exc

    return _inner


def test_run_exit_zero_on_success(monkeypatch, tmp_path: Path) -> None:
    out = tmp_path / "run"
    monkeypatch.setattr(app_mod, "run_wall_clock_scenario", lambda *_a, **_k: _success(out))
    result = runner.invoke(
        app,
        [
            "run",
            str(FIXTURE_DIR / "identity-move-rename.yaml"),
            "--out",
            str(out),
            "--duration",
            "1s",
            "--speed",
            "10x",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["execution_mode"] == "run"
    assert payload["run_id"] == str(RUN_ID)
    assert payload["requested_duration_ns"] == 1_000_000_000
    assert payload["actual_duration_ns"] == 1_000_000_000
    assert payload["speed_multiplier"] == "10"
    assert payload["applied_events"] == 2
    assert payload["overran_duration"] is False
    assert payload["materialization_report_path"] == str((out / "materialization.json").resolve())
    assert payload["replay_bundle_path"] == str((out / "replay.json").resolve())


def test_run_rejects_zero_duration(tmp_path: Path) -> None:
    result = runner.invoke(
        app,
        [
            "run",
            str(FIXTURE_DIR / "identity-move-rename.yaml"),
            "--out",
            str(tmp_path / "run"),
            "--duration",
            "0",
            "--json",
        ],
    )
    assert result.exit_code == 2


def test_run_validation_error_exit_three(monkeypatch, tmp_path: Path) -> None:
    report = ValidationReport(schema_version=1, ok=False, scenario_id="x", issues=[])
    exc = ScenarioValidationError("bad scenario", validation_report=report)
    monkeypatch.setattr(app_mod, "run_wall_clock_scenario", _raise(exc))
    result = runner.invoke(
        app,
        [
            "run",
            str(FIXTURE_DIR / "identity-move-rename.yaml"),
            "--out",
            str(tmp_path / "run"),
            "--duration",
            "1s",
            "--json",
        ],
    )
    assert result.exit_code == 3


def test_run_capability_error_exit_four(monkeypatch, tmp_path: Path) -> None:
    exc = CapabilityGateError("missing ffmpeg")
    monkeypatch.setattr(app_mod, "run_wall_clock_scenario", _raise(exc))
    result = runner.invoke(
        app,
        [
            "run",
            str(FIXTURE_DIR / "identity-move-rename.yaml"),
            "--out",
            str(tmp_path / "run"),
            "--duration",
            "1s",
            "--json",
        ],
    )
    assert result.exit_code == 4


def test_run_unsupported_timeline_exit_five(monkeypatch, tmp_path: Path) -> None:
    exc = TimelineUnsupportedError("unsupported timeline")
    monkeypatch.setattr(app_mod, "run_wall_clock_scenario", _raise(exc))
    out = tmp_path / "run"
    result = runner.invoke(
        app,
        [
            "run",
            str(FIXTURE_DIR / "identity-move-rename.yaml"),
            "--out",
            str(out),
            "--duration",
            "1s",
            "--json",
        ],
    )
    assert result.exit_code == 5
    payload = json.loads(result.stderr)
    assert payload["error_code"] == "E_MATERIALIZE_TIMELINE_UNSUPPORTED"
    assert "materialization_report_path" not in payload
    assert not out.exists()


def test_run_materialization_error_exit_five(monkeypatch, tmp_path: Path) -> None:
    exc = UnsupportedMaterializationError("unsupported codec")
    monkeypatch.setattr(app_mod, "run_wall_clock_scenario", _raise(exc))
    out = tmp_path / "run"
    result = runner.invoke(
        app,
        [
            "run",
            str(FIXTURE_DIR / "identity-move-rename.yaml"),
            "--out",
            str(out),
            "--duration",
            "1s",
            "--json",
        ],
    )
    assert result.exit_code == 5
    payload = json.loads(result.stderr)
    assert payload["error_code"] == "E_MATERIALIZE_UNSUPPORTED"
    assert "materialization_report_path" not in payload
    assert not out.exists()


def test_cli_run_corruption_failure_exits_5_with_materialization_report_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    exc = CorruptionActionError(
        "corrupt_container_header failed for event corrupt_header_001: short file",
        event_id="corrupt_header_001",
        action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
        cause=RuntimeError("short file"),
        asset_id="asset_main",
    )
    monkeypatch.setattr(app_mod, "run_wall_clock_scenario", _raise(exc))
    out = tmp_path / "run"

    result = runner.invoke(
        app,
        [
            "run",
            str(FIXTURE_DIR / "identity-move-rename.yaml"),
            "--out",
            str(out),
            "--duration",
            "1s",
            "--json",
        ],
    )

    assert result.exit_code == 5
    payload = json.loads(result.stderr)
    assert payload["error_code"] == "E_MATERIALIZE_CORRUPTION_FAILED"
    assert payload["asset_id"] == "asset_main"
    assert payload["materialization_report_path"] == str(out / "materialization.json")
    assert payload["details"]["event_id"] == "corrupt_header_001"
    assert payload["details"]["action"] == "corrupt_container_header"


def test_run_filesystem_safety_error_exit_seven(monkeypatch, tmp_path: Path) -> None:
    exc = ContainmentViolationError("unsafe path")
    monkeypatch.setattr(app_mod, "run_wall_clock_scenario", _raise(exc))
    result = runner.invoke(
        app,
        [
            "run",
            str(FIXTURE_DIR / "identity-move-rename.yaml"),
            "--out",
            str(tmp_path / "run"),
            "--duration",
            "1s",
            "--json",
        ],
    )
    assert result.exit_code == 7
