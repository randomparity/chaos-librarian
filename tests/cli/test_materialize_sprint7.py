"""Layer 5 — Sprint 7 materialize CLI dispatch with the orchestrator mocked.

WHY: when a phase-B media handler fails the orchestrator has already wiped
``library/`` and written ``materialization.json`` with outcome=media_failed.
The CLI dispatch branch added in Task 37 must surface that failure as
exit code 5 carrying ``E_MATERIALIZE_MEDIA_FAILED`` and the per-action
context (event_id, action, tool_invocation_index) so downstream adapters
can correlate the JSON envelope with the on-disk report and the
invocations array within it.
"""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli import commands as commands_pkg
from chaos_librarian.cli.app import app
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer import MaterializeArtifacts
from chaos_librarian.materializer.errors import MediaActionError

app_mod = commands_pkg.materialize

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def test_materialize_media_failed_exit_5_with_json_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    """End-to-end CLI test: mocked orchestrator raises MediaActionError."""

    def boom(*_a: object, **_k: object) -> MaterializeArtifacts:
        raise MediaActionError(
            "reencode_video failed for event ev_rv_001: ffmpeg exited 1",
            event_id="ev_rv_001",
            action=TimelineActionName.REENCODE_VIDEO,
            cause=RuntimeError("ffmpeg exited 1"),
            tool_invocation_index=2,
        )

    monkeypatch.setattr(app_mod, "materialize_scenario", boom)
    out = tmp_path / "run-001"
    result = runner.invoke(
        app,
        [
            "materialize",
            str(FIXTURE_DIR / "reencode-video.yaml"),
            "--out",
            str(out),
            "--json",
        ],
    )
    assert result.exit_code == 5, result.stdout + result.stderr
    payload = json.loads(result.stderr)
    assert payload["error_code"] == "E_MATERIALIZE_MEDIA_FAILED"
    assert payload["materialization_report_path"] == str(out / "materialization.json")
    details = payload["details"]
    assert details["event_id"] == "ev_rv_001"
    assert details["action"] == "reencode_video"
    assert details["tool_invocation_index"] == 2
