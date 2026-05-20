"""Layer 5 — Sprint 6 materialize CLI dispatch with the orchestrator mocked.

WHY: when phase B fails the orchestrator has already wiped ``library/`` and
written ``materialization.json`` with outcome=fs_failed. The CLI dispatch
branch added in Task 20 must surface that failure as exit code 5 carrying
``E_MATERIALIZE_FS_FAILED`` and the per-action context (event_id, action,
asset_id, errno) so downstream adapters can correlate the JSON envelope
with the on-disk report.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli import commands as commands_pkg
from chaos_librarian.cli.app import app
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer import MaterializeArtifacts
from chaos_librarian.materializer.errors import FilesystemActionError

app_mod = commands_pkg.materialize

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def test_cli_materialize_fs_failed_exits_5_with_event_id_in_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """End-to-end CLI test: mocked orchestrator raises FilesystemActionError."""

    def boom(*_a: object, **_k: object) -> MaterializeArtifacts:
        raise FilesystemActionError(
            "move_asset failed for event move_001: no such file",
            event_id="move_001",
            cause=OSError(2, "No such file or directory"),
            action=TimelineActionName.MOVE_ASSET,
            asset_id="asset_hd_main",
        )

    monkeypatch.setattr(app_mod, "materialize_scenario", boom)
    out = tmp_path / "run-001"
    result = runner.invoke(
        app,
        [
            "materialize",
            str(FIXTURE_DIR / "identity-move-rename.yaml"),
            "--out",
            str(out),
            "--json",
        ],
    )
    assert result.exit_code == 5, result.stdout + result.stderr
    payload = json.loads(result.stderr)
    assert payload["error_code"] == "E_MATERIALIZE_FS_FAILED"
    assert payload["materialization_report_path"] == str(out / "materialization.json")
    details = payload["details"]
    assert details["event_id"] == "move_001"
    assert details["action"] == "move_asset"
    assert details["errno"] == 2
    assert payload["asset_id"] == "asset_hd_main"
