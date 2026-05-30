"""Replay coverage for generated fuzz lane scenarios."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.generation import generate_scenario_yaml

runner = CliRunner()


def test_generated_regression_lane_plans_and_replays(tmp_path: Path) -> None:
    scenario = tmp_path / "fuzz-regression-core-fs.yaml"
    run_dir = tmp_path / "run"
    replay_dir = tmp_path / "replay"
    scenario.write_bytes(
        generate_scenario_yaml(
            profile=FuzzProfileName.FUZZ_REGRESSION,
            lane=FuzzLaneName.CORE_FS,
            seed=456,
        )
    )

    plan_result = runner.invoke(app, ["plan", str(scenario), "--out", str(run_dir), "--json"])
    assert plan_result.exit_code == 0, plan_result.stdout + plan_result.stderr

    replay_result = runner.invoke(
        app,
        ["replay", str(run_dir / "replay.json"), "--out", str(replay_dir), "--json"],
    )
    assert replay_result.exit_code == 0, replay_result.stdout + replay_result.stderr


def test_batch_generated_scenario_plans(tmp_path: Path) -> None:
    out = tmp_path / "gen"
    out.mkdir()
    run_dir = tmp_path / "run"

    gen = runner.invoke(
        app,
        ["generate", "--profile", "fuzz-smoke", "--count", "2", "--seed", "70", "--out", str(out)],
    )
    assert gen.exit_code == 0, gen.stdout + gen.stderr

    scenario = out / "fuzz-smoke-smoke-seed-70.yaml"
    assert scenario.exists()
    plan_result = runner.invoke(app, ["plan", str(scenario), "--out", str(run_dir), "--json"])
    assert plan_result.exit_code == 0, plan_result.stdout + plan_result.stderr
