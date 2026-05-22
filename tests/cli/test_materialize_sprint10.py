"""Layer 5 — Sprint 10 materialize CLI corruption dispatch."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli import commands as commands_pkg
from chaos_librarian.cli.app import app
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer import MaterializeArtifacts
from chaos_librarian.materializer.errors import CorruptionActionError

app_mod = commands_pkg.materialize

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def test_cli_corruption_failure_exits_5_with_materialization_report_path(
    monkeypatch,
    tmp_path: Path,
) -> None:
    def boom(*_a: object, **_k: object) -> MaterializeArtifacts:
        raise CorruptionActionError(
            "corrupt_container_header failed for event corrupt_header_001: short file",
            event_id="corrupt_header_001",
            action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
            cause=RuntimeError("short file"),
            asset_id="asset_main",
        )

    monkeypatch.setattr(app_mod, "materialize_scenario", boom)
    out = tmp_path / "run-001"
    result = runner.invoke(
        app,
        [
            "materialize",
            str(FIXTURE_DIR / "invalid" / "corrupt-container-header-missing-profile.yaml"),
            "--out",
            str(out),
            "--json",
        ],
    )
    assert result.exit_code == 5, result.stdout + result.stderr
    payload = json.loads(result.stderr)
    assert payload["error_code"] == "E_MATERIALIZE_CORRUPTION_FAILED"
    assert payload["asset_id"] == "asset_main"
    assert payload["materialization_report_path"] == str(out / "materialization.json")
    assert payload["details"]["event_id"] == "corrupt_header_001"
    assert payload["details"]["action"] == "corrupt_container_header"


def test_cli_missing_profile_exits_3_and_creates_no_run_dir(tmp_path: Path) -> None:
    out = tmp_path / "must-not-exist"

    result = runner.invoke(
        app,
        [
            "materialize",
            str(FIXTURE_DIR / "invalid" / "corrupt-container-header-missing-profile.yaml"),
            "--out",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 3, result.stdout + result.stderr
    payload = json.loads(result.stderr)
    assert payload["error_code"] == "E_MATERIALIZE_VALIDATION_FAILED"
    assert "materialization_report_path" not in payload
    assert not out.exists()
