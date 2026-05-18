"""Tests for plan --steps flag (CLI level)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


class TestPlanSteps:
    """plan --steps caps the timeline; missing flag runs the full timeline.

    WHY: partial fixtures are the input surface for step mode and replay.
    """

    def test_steps_zero_empties_journal(self, tmp_path: Path) -> None:
        out = tmp_path / "run"
        result = runner.invoke(
            app,
            [
                "plan",
                str(FIXTURE_DIR / "identity-move-rename.yaml"),
                "--out",
                str(out),
                "--steps",
                "0",
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        assert (out / "journal.jsonl").read_text() == ""
        bundle = PlanOnlyReplayBundle.model_validate_json((out / "replay.json").read_text())
        assert bundle.applied_events == 0

    def test_steps_k_partial_journal(self, tmp_path: Path) -> None:
        # identity-move-rename is atomic-only: 1 step unit = 1 raw event.
        out = tmp_path / "run"
        result = runner.invoke(
            app,
            [
                "plan",
                str(FIXTURE_DIR / "identity-move-rename.yaml"),
                "--out",
                str(out),
                "--steps",
                "1",
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        bundle = PlanOnlyReplayBundle.model_validate_json((out / "replay.json").read_text())
        assert bundle.applied_events == 1
        assert sum(1 for _ in (out / "journal.jsonl").read_text().splitlines()) == 1

    def test_steps_one_on_slow_copy_applies_pair(self, tmp_path: Path) -> None:
        """--steps 1 on slow-copy.yaml advances BOTH halves of the pair.

        WHY: Codex round 3 finding 1 — one step unit covers
        slow_copy_start + slow_copy_commit; the journal must have both
        entries.
        """
        out = tmp_path / "run"
        result = runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "slow-copy.yaml"), "--out", str(out), "--steps", "1"],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        bundle = PlanOnlyReplayBundle.model_validate_json((out / "replay.json").read_text())
        assert bundle.applied_events == 2
        lines = (out / "journal.jsonl").read_text().splitlines()
        assert len(lines) == 2
        phases = [json.loads(line)["phase"] for line in lines]
        assert phases == ["started", "committed"]

    def test_steps_negative_is_usage_error(self, tmp_path: Path) -> None:
        out = tmp_path / "run"
        result = runner.invoke(
            app,
            [
                "plan",
                str(FIXTURE_DIR / "identity-move-rename.yaml"),
                "--out",
                str(out),
                "--steps",
                "-1",
            ],
        )
        assert result.exit_code == 2

    def test_steps_missing_is_full_run(self, tmp_path: Path) -> None:
        out = tmp_path / "run"
        result = runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        bundle = PlanOnlyReplayBundle.model_validate_json((out / "replay.json").read_text())
        assert bundle.applied_events == 2
