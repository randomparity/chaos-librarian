"""End-to-end tests for the plan CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


class TestPlanExitCodes:
    """Valid scenarios exit 0; invalid ones exit 3 without creating --out.

    WHY: exit codes drive CI gates and agentic scripts. The "no --out on
    failure" rule keeps tooling from cleaning up half-written fixtures.
    """

    def test_valid_scenario_exits_zero(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        result = runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        assert (out / ".chaos-librarian-run").exists()

    def test_invalid_scenario_exits_three_without_out(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("42\n")  # E_TOP_LEVEL_NOT_MAPPING
        out = tmp_path / "run-001"
        result = runner.invoke(app, ["plan", str(bad), "--out", str(out)])
        assert result.exit_code == 3
        assert not out.exists()


class TestPlanJSONSummary:
    """``--json`` emits a small summary object.

    WHY: agents consume this; the small shape is the contract surface.
    """

    def test_json_summary_fields(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        result = runner.invoke(
            app,
            [
                "plan",
                str(FIXTURE_DIR / "identity-move-rename.yaml"),
                "--out",
                str(out),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["scenario_id"] == "identity-move-rename"
        assert payload["out"] == str(out.resolve())
        assert payload["journal_entries"] == 2
        assert payload["ok"] is True
        assert "run_id" in payload


class TestPlanWritesEveryFile:
    """plan writes the seven plan-only artifacts.

    WHY: locks the public fixture layout for plan-only mode.
    """

    def test_seven_files(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out)],
        )
        names = sorted(p.name for p in out.iterdir())
        assert names == [
            ".chaos-librarian-run",
            "journal.jsonl",
            "manifest.current.json",
            "manifest.initial.json",
            "replay.json",
            "scenario.yaml",
            "validation.json",
        ]
