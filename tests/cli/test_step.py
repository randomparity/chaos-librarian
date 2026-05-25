"""End-to-end tests for the step CLI command."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.materialization import ToolchainInfo
from chaos_librarian.contract.replay_bundle import (
    ExecutionMode,
    MaterializeReplayBundle,
    PlanOnlyReplayBundle,
)
from chaos_librarian.contract.run_sentinel import RunSentinel, RunSentinelState

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _make_paused(tmp_path: Path) -> Path:
    out = tmp_path / "run"
    result = runner.invoke(
        app,
        ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out), "--steps", "0"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    return out


def _replace_replay_with_materialize_bundle(run_dir: Path) -> None:
    plan = PlanOnlyReplayBundle.model_validate_json((run_dir / "replay.json").read_text())
    payload = plan.model_dump()
    payload.pop("execution_mode")
    bundle = MaterializeReplayBundle(
        **payload,
        execution_mode=ExecutionMode.MATERIALIZE,
        created_at=datetime(2026, 5, 25, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="8.1.1", ffprobe="8.1.1", mkvtoolnix="98.0"),
        content_sources=[],
    )
    (run_dir / "replay.json").write_text(bundle.model_dump_json(indent=2) + "\n")


class TestStepHappyPath:
    """step --next advances the fixture and updates replay.json.

    WHY: this is the headline step-mode behavior — partial fixtures are
    rewritable.
    """

    def test_next_one(self, tmp_path: Path) -> None:
        paused = _make_paused(tmp_path)
        result = runner.invoke(app, ["step", str(paused), "--next", "1"])
        assert result.exit_code == 0, result.stdout + result.stderr
        bundle = PlanOnlyReplayBundle.model_validate_json((paused / "replay.json").read_text())
        assert bundle.applied_events == 1

    def test_batch_advance(self, tmp_path: Path) -> None:
        paused = _make_paused(tmp_path)
        result = runner.invoke(app, ["step", str(paused), "--next", "5"])
        assert result.exit_code == 0, result.stdout + result.stderr
        bundle = PlanOnlyReplayBundle.model_validate_json((paused / "replay.json").read_text())
        assert bundle.applied_events == 2  # identity-move-rename has only two events
        assert "applied 2" in result.stdout

    def test_done_on_completed(self, tmp_path: Path) -> None:
        full = tmp_path / "run"
        runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(full)],
        )
        result = runner.invoke(app, ["step", str(full), "--next", "1", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["done"] is True
        assert payload["steps_applied"] == 0

    def test_json_summary(self, tmp_path: Path) -> None:
        paused = _make_paused(tmp_path)
        result = runner.invoke(app, ["step", str(paused), "--next", "1", "--json"])
        payload = json.loads(result.stdout)
        assert payload["steps_applied"] == 1
        assert payload["done"] is False
        assert "run_id" in payload


class TestStepErrors:
    """step maps engine errors to exit codes.

    WHY: agents key on the exit-code matrix in the design.
    """

    def test_negative_next(self, tmp_path: Path) -> None:
        paused = _make_paused(tmp_path)
        result = runner.invoke(app, ["step", str(paused), "--next", "-1"])
        assert result.exit_code == 2

    def test_missing_sentinel(self, tmp_path: Path) -> None:
        paused = _make_paused(tmp_path)
        (paused / ".chaos-librarian-run").unlink()
        result = runner.invoke(app, ["step", str(paused), "--next", "1"])
        assert result.exit_code == 7

    def test_tampered_scenario(self, tmp_path: Path) -> None:
        paused = _make_paused(tmp_path)
        sp = paused / "scenario.yaml"
        sp.write_text(sp.read_text() + "\n# tamper\n")
        result = runner.invoke(app, ["step", str(paused), "--next", "1"])
        assert result.exit_code == 7

    def test_corrupt_journal(self, tmp_path: Path) -> None:
        # Need a journal with entries to corrupt — use --steps 1
        out = tmp_path / "run"
        runner.invoke(
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
        (out / "journal.jsonl").write_text("{not json\n")
        result = runner.invoke(app, ["step", str(out), "--next", "1"])
        assert result.exit_code == 1

    def test_step_refuses_in_progress_sentinel(self, tmp_path: Path) -> None:
        """WHY: a partial materialize run-dir must not be advanced by step;
        step exits 7 with E_SENTINEL_IN_PROGRESS so an agent surfaces it."""
        out = tmp_path / "run"
        plan_result = runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out)],
        )
        assert plan_result.exit_code == 0
        sentinel_path = out / ".chaos-librarian-run"
        sentinel = RunSentinel.model_validate_json(sentinel_path.read_text())
        in_progress = sentinel.model_copy(update={"state": RunSentinelState.IN_PROGRESS})
        sentinel_path.write_text(in_progress.model_dump_json(indent=2, exclude_none=True) + "\n")

        result = runner.invoke(app, ["step", str(out), "--json"])
        assert result.exit_code == 7
        payload = json.loads(result.stderr)
        assert payload["error_code"] == "E_SENTINEL_IN_PROGRESS"

    def test_step_refuses_materialized_run_dir_with_structured_json(self, tmp_path: Path) -> None:
        out = _make_paused(tmp_path)
        _replace_replay_with_materialize_bundle(out)

        result = runner.invoke(app, ["step", str(out), "--next", "1", "--json"])

        assert result.exit_code == 1
        assert "Traceback" not in result.stderr
        payload = json.loads(result.stderr)
        assert payload["error_code"] == "E_STEP_UNSUPPORTED_MODE"
        assert payload["details"]["execution_mode"] == "materialize"
        assert payload["details"]["supported_execution_mode"] == "plan_only"

    def test_step_reports_invalid_replay_bundle_json(self, tmp_path: Path) -> None:
        paused = _make_paused(tmp_path)
        (paused / "replay.json").write_text("{not json\n")

        result = runner.invoke(app, ["step", str(paused), "--json"])

        assert result.exit_code == 1
        assert "Traceback" not in result.stderr
        payload = json.loads(result.stderr)
        assert payload["error_code"] == "E_REPLAY_BUNDLE_INVALID"
        assert payload["bundle_path"].endswith("replay.json")
