"""Layer 5 — materialize CLI with materialize_scenario mocked."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

import chaos_librarian.cli.app as app_mod
from chaos_librarian.cli.app import app
from chaos_librarian.contract import (
    MATERIALIZATION_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
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
from chaos_librarian.contract.validation import (
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from chaos_librarian.materializer import MaterializeArtifacts
from chaos_librarian.materializer.errors import (
    CapabilityGateError,
    ScenarioValidationError,
    TimelineUnsupportedError,
    UnsupportedMaterializationError,
)

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _success() -> MaterializeArtifacts:
    return MaterializeArtifacts(
        current_manifest=Manifest(
            schema_version=2,
            works=[],
            variants=[],
            bundles=[],
            assets=[],
            versions=[],
            locations=[],
            sidecars=[],
        ),
        materialization_report=MaterializationReport(
            schema_version=MATERIALIZATION_SCHEMA_VERSION,
            run_id=uuid.uuid4(),
            outcome=Outcome.SUCCESS,
            platform="test",
            started_at=datetime.now(UTC),
            finished_at=datetime.now(UTC),
            toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
        ),
        replay_bundle=MaterializeReplayBundle(
            schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
            chaos_librarian_version="0.1.0",
            scenario="schema_version: 2\nscenario_id: x\n",
            run_id=uuid.uuid4(),
            resolved_seed=1,
            journal_digest="0" * 64,
            execution_mode=ExecutionMode.MATERIALIZE,
            created_at=datetime.now(UTC),
            toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
        ),
    )


def test_materialize_exit_zero_on_success(monkeypatch, tmp_path: Path) -> None:
    out = tmp_path / "run"
    out.mkdir()  # mocked orchestrator does not allocate
    monkeypatch.setattr(app_mod, "materialize_scenario", lambda *_a, **_k: _success())
    target = out / "x"
    result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(target), "--json"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "success"


def test_materialize_exit_four_on_capability_gate(monkeypatch, tmp_path: Path) -> None:
    def raise_gate(*_a: object, **_k: object) -> MaterializeArtifacts:
        raise CapabilityGateError(
            "ffmpeg missing",
            payload={"capabilities": {"ffmpeg": {"found": False}}},
        )

    monkeypatch.setattr(app_mod, "materialize_scenario", raise_gate)
    out = tmp_path / "no_caps"
    result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out), "--json"],
    )
    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "E_MATERIALIZE_CAPABILITY_GATE"


def test_materialize_exit_five_on_unsupported_lazy_allocation(monkeypatch, tmp_path: Path) -> None:
    """WHY: lazy allocation guarantee (Finding 3) — pre-synthesis failures
    leave NO on-disk artifact and the stdout JSON omits
    materialization_report_path."""

    def raise_unsupported(*_a: object, **_k: object) -> MaterializeArtifacts:
        raise UnsupportedMaterializationError(
            "opus not supported",
            asset_id="a0",
            field="audio[0].codec",
            payload={"supported": ["aac"]},
        )

    monkeypatch.setattr(app_mod, "materialize_scenario", raise_unsupported)
    out = tmp_path / "absent"
    result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out), "--json"],
    )
    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "E_MATERIALIZE_UNSUPPORTED"
    assert "materialization_report_path" not in payload
    assert not out.exists()


def test_materialize_exit_five_on_timeline(monkeypatch, tmp_path: Path) -> None:
    def raise_timeline(*_a: object, **_k: object) -> MaterializeArtifacts:
        raise TimelineUnsupportedError(
            "no timeline allowed", field="timeline", payload={"event_count": 1}
        )

    monkeypatch.setattr(app_mod, "materialize_scenario", raise_timeline)
    out = tmp_path / "absent"
    result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "slow-copy.yaml"), "--out", str(out), "--json"],
    )
    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "E_MATERIALIZE_TIMELINE_UNSUPPORTED"


def test_materialize_exit_three_on_validation_failure(monkeypatch, tmp_path: Path) -> None:
    """WHY: Finding 1 — the materialize entry must mirror ``plan``'s
    exit-3 convention for semantic-validation failures so agents can
    disambiguate "scenario rejected" from "tool failed". The stdout JSON
    carries E_MATERIALIZE_VALIDATION_FAILED and omits
    materialization_report_path (no run-dir allocated)."""
    bad_report = ValidationReport(
        schema_version=1,
        ok=False,
        scenario_id="bad",
        issues=[
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="E_PATH_CONTAINMENT",
                message="asset path escapes library/",
                line=None,
                column=None,
                path=None,
            )
        ],
    )

    def raise_validation(*_a: object, **_k: object) -> MaterializeArtifacts:
        raise ScenarioValidationError(
            "scenario failed semantic validation; refusing to materialize",
            payload={
                "validation_report": bad_report.model_dump(mode="json", exclude_none=True),
            },
            validation_report=bad_report,
        )

    monkeypatch.setattr(app_mod, "materialize_scenario", raise_validation)
    out = tmp_path / "absent"
    result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out), "--json"],
    )
    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "E_MATERIALIZE_VALIDATION_FAILED"
    assert "materialization_report_path" not in payload
    assert not out.exists()
