"""End-to-end tests for the inspect CLI command."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli._replay_io import REPLAY_BUNDLE_ADAPTER
from chaos_librarian.cli.app import app
from chaos_librarian.contract.materialization import ToolchainInfo
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinel, RunSentinelState
from chaos_librarian.engine import run_materializer_plan
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.writer import canonical_json
from chaos_librarian.validation import prepare_run_input, run_validation

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _make_fixture(tmp_path: Path, steps: int | None) -> Path:
    out = tmp_path / "run"
    args = ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out)]
    if steps is not None:
        args += ["--steps", str(steps)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stdout + result.stderr
    return out


class TestInspect:
    """inspect emits a JSON summary or a human block.

    WHY: agents pipe --json output through jq; humans want a clean block.
    """

    def test_full_fixture_json(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, steps=None)
        result = runner.invoke(app, ["inspect", str(fixture), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["scenario_id"] == "identity-move-rename"
        assert payload["execution_mode"] == "plan_only"
        assert payload["journal_entries"] == 2
        assert payload["steps_remaining"] == 0
        assert payload["counts"]["assets"] == 1

    def test_partial_fixture_steps_remaining(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, steps=1)
        result = runner.invoke(app, ["inspect", str(fixture), "--json"])
        payload = json.loads(result.stdout)
        assert payload["steps_remaining"] == 1
        assert payload["journal_entries"] == 1

    def test_missing_sentinel(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, steps=None)
        (fixture / ".chaos-librarian-run").unlink()
        result = runner.invoke(app, ["inspect", str(fixture)])
        assert result.exit_code == 7

    def test_inspect_reports_complete_state(self, tmp_path: Path) -> None:
        """WHY: every plan-only run-dir reports state=complete; agents read
        the field to distinguish completed runs from interrupted materialize."""
        out = tmp_path / "run"
        plan_result = runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out)],
        )
        assert plan_result.exit_code == 0, plan_result.stdout + plan_result.stderr

        result = runner.invoke(app, ["inspect", str(out), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["sentinel"]["state"] == "complete"

    def test_inspect_reports_in_progress_state(self, tmp_path: Path) -> None:
        """WHY: an interrupted materialize run leaves the sentinel at
        state=in_progress; inspect must surface that so an agent can clean it."""
        out = tmp_path / "interrupted"
        plan_result = runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out)],
        )
        assert plan_result.exit_code == 0
        sentinel_path = out / ".chaos-librarian-run"
        sentinel = RunSentinel.model_validate_json(sentinel_path.read_text())
        sentinel_in_progress = sentinel.model_copy(update={"state": RunSentinelState.IN_PROGRESS})
        sentinel_path.write_text(
            sentinel_in_progress.model_dump_json(indent=2, exclude_none=True) + "\n"
        )

        result = runner.invoke(app, ["inspect", str(out), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["sentinel"]["state"] == "in_progress"

    def test_inspect_slow_copy_partial(self, tmp_path: Path) -> None:
        """inspect reports step-unit counts, not raw event counts.

        WHY: Codex round 3 finding 1 — --next is step-unit-counted; the
        inspect summary must use the same unit so adapters see a
        consistent story.
        """
        out = tmp_path / "run"
        runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "slow-copy.yaml"), "--out", str(out), "--steps", "0"],
        )
        result = runner.invoke(app, ["inspect", str(out), "--json"])
        payload = json.loads(result.stdout)
        assert payload["applied_steps"] == 0
        assert payload["steps_remaining"] == 1  # one step unit covers the whole pair
        assert payload["applied_events"] == 0
        assert payload["journal_entries"] == 0

    def test_in_progress_run_reports_live_journal_events(self, tmp_path: Path) -> None:
        """Interrupted wall-clock runs keep baseline replay metadata; inspect
        must still report the live appended journal count as progress."""
        out = tmp_path / "run"
        runner.invoke(
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
        bundle = REPLAY_BUNDLE_ADAPTER.validate_json((out / "replay.json").read_bytes())
        run_input = prepare_run_input(FIXTURE_DIR / "identity-move-rename.yaml")
        report = run_validation(run_input)
        live_artifacts = run_materializer_plan(
            run_input=run_input,
            validation_report=report,
            run_id_override=bundle.run_id,
            applied_events_override=2,
        )
        run_bundle = MaterializeReplayBundle(
            schema_version=bundle.schema_version,
            chaos_librarian_version=bundle.chaos_librarian_version,
            scenario=bundle.scenario,
            run_id=bundle.run_id,
            resolved_seed=bundle.resolved_seed,
            applied_events=0,
            journal_digest=bundle.journal_digest,
            execution_trace=bundle.execution_trace,
            execution_mode=ExecutionMode.RUN,
            created_at=datetime(2026, 5, 21, 0, 0, 0, tzinfo=UTC),
            toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
            content_sources=[],
        )
        (out / "replay.json").write_text(canonical_json(run_bundle), encoding="utf-8")
        (out / "journal.jsonl").write_bytes(serialize_journal_bytes(live_artifacts.journal))
        sentinel_path = out / ".chaos-librarian-run"
        sentinel = RunSentinel.model_validate_json(sentinel_path.read_text())
        sentinel_path.write_text(
            canonical_json(sentinel.model_copy(update={"state": RunSentinelState.IN_PROGRESS})),
            encoding="utf-8",
        )

        result = runner.invoke(app, ["inspect", str(out), "--json"])
        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["sentinel"]["state"] == "in_progress"
        assert payload["journal_entries"] == 2
        assert payload["applied_events"] == 2
        assert payload["applied_steps"] == 2
        assert payload["steps_remaining"] == 0
