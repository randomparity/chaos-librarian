"""Tests for the CLI stub. All commands exist and exit 1 in Sprint 0."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app

# Click 8.2+ removed mix_stderr from CliRunner.__init__; stdout and stderr are
# now separate by default, which matches the intent of the original spec.
runner = CliRunner()


@pytest.mark.parametrize(
    "command",
    [
        "validate",
        "plan",
        "materialize",
        "run",
        "step",
        "replay",
        "inspect",
        "capabilities",
        "clean",
    ],
)
def test_command_exists_and_exits_one(command: str) -> None:
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0, f"--help should always succeed for {command}"


def test_capabilities_stub_exits_one() -> None:
    result = runner.invoke(app, ["capabilities"])
    assert result.exit_code == 1


class TestValidatePathValidation:
    def test_rejects_missing_scenario(self, tmp_path: Path) -> None:
        missing = tmp_path / "does-not-exist.yaml"
        result = runner.invoke(app, ["validate", str(missing)])
        assert result.exit_code == 2, (
            f"missing scenario should exit 2 (BadParameter), got {result.exit_code}"
        )

    def test_rejects_directory_as_scenario(self, tmp_path: Path) -> None:
        a_dir = tmp_path / "a-dir"
        a_dir.mkdir()
        result = runner.invoke(app, ["validate", str(a_dir)])
        assert result.exit_code == 2, (
            f"directory passed as scenario should exit 2, got {result.exit_code}"
        )


def test_validate_stub_with_valid_scenario_exits_one(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("")
    result = runner.invoke(app, ["validate", str(scenario)])
    assert result.exit_code == 1, (
        f"validate stub with valid path should exit 1, got {result.exit_code}"
    )


class TestPlanPathValidation:
    def test_rejects_missing_scenario(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.yaml"
        out = tmp_path / "run-001"
        result = runner.invoke(app, ["plan", str(missing), "--out", str(out)])
        assert result.exit_code == 2, (
            f"missing scenario should exit 2 (BadParameter), got {result.exit_code}"
        )

    def test_rejects_directory_as_scenario(self, tmp_path: Path) -> None:
        a_dir = tmp_path / "a-dir"
        a_dir.mkdir()
        out = tmp_path / "run-001"
        result = runner.invoke(app, ["plan", str(a_dir), "--out", str(out)])
        assert result.exit_code == 2, (
            f"directory passed as scenario should exit 2, got {result.exit_code}"
        )

    def test_rejects_out_when_parent_missing(self, tmp_path: Path) -> None:
        scenario = tmp_path / "scenario.yaml"
        scenario.write_text("")
        out = tmp_path / "nonexistent-parent" / "run-001"
        result = runner.invoke(app, ["plan", str(scenario), "--out", str(out)])
        assert result.exit_code == 2, (
            f"--out with missing parent should exit 2, got {result.exit_code}"
        )

    def test_rejects_out_when_path_already_exists(self, tmp_path: Path) -> None:
        scenario = tmp_path / "scenario.yaml"
        scenario.write_text("")
        out = tmp_path / "run-001"
        out.mkdir()
        result = runner.invoke(app, ["plan", str(scenario), "--out", str(out)])
        assert result.exit_code == 2, (
            f"--out path that already exists should exit 2, got {result.exit_code}"
        )


def test_plan_stub_with_valid_paths_exits_one(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("")
    out = tmp_path / "run-001"
    result = runner.invoke(app, ["plan", str(scenario), "--out", str(out)])
    assert result.exit_code == 1


class TestMaterializePathValidation:
    def test_rejects_missing_scenario(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.yaml"
        out = tmp_path / "run-001"
        result = runner.invoke(app, ["materialize", str(missing), "--out", str(out)])
        assert result.exit_code == 2, (
            f"missing scenario should exit 2 (BadParameter), got {result.exit_code}"
        )

    def test_rejects_directory_as_scenario(self, tmp_path: Path) -> None:
        a_dir = tmp_path / "a-dir"
        a_dir.mkdir()
        out = tmp_path / "run-001"
        result = runner.invoke(app, ["materialize", str(a_dir), "--out", str(out)])
        assert result.exit_code == 2, (
            f"directory passed as scenario should exit 2, got {result.exit_code}"
        )

    def test_rejects_out_when_parent_missing(self, tmp_path: Path) -> None:
        scenario = tmp_path / "scenario.yaml"
        scenario.write_text("")
        out = tmp_path / "nonexistent-parent" / "run-001"
        result = runner.invoke(app, ["materialize", str(scenario), "--out", str(out)])
        assert result.exit_code == 2, (
            f"--out with missing parent should exit 2, got {result.exit_code}"
        )

    def test_rejects_out_when_parent_is_file(self, tmp_path: Path) -> None:
        scenario = tmp_path / "scenario.yaml"
        scenario.write_text("")
        parent_as_file = tmp_path / "a-file"
        parent_as_file.write_text("")
        out = parent_as_file / "run-001"
        result = runner.invoke(app, ["materialize", str(scenario), "--out", str(out)])
        assert result.exit_code == 2, (
            f"--out whose parent is a regular file should exit 2, got {result.exit_code}"
        )

    def test_rejects_out_when_path_already_exists(self, tmp_path: Path) -> None:
        scenario = tmp_path / "scenario.yaml"
        scenario.write_text("")
        out = tmp_path / "run-001"
        out.mkdir()
        result = runner.invoke(app, ["materialize", str(scenario), "--out", str(out)])
        assert result.exit_code == 2, (
            f"--out path that already exists should exit 2, got {result.exit_code}"
        )


def test_materialize_stub_with_valid_paths_exits_one(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("")
    out = tmp_path / "run-001"
    result = runner.invoke(app, ["materialize", str(scenario), "--out", str(out)])
    assert result.exit_code == 1


class TestRunPathValidation:
    def test_rejects_missing_scenario(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.yaml"
        out = tmp_path / "run-001"
        result = runner.invoke(
            app,
            ["run", str(missing), "--out", str(out), "--duration", "10s"],
        )
        assert result.exit_code == 2, (
            f"missing scenario should exit 2 (BadParameter), got {result.exit_code}"
        )

    def test_rejects_directory_as_scenario(self, tmp_path: Path) -> None:
        a_dir = tmp_path / "a-dir"
        a_dir.mkdir()
        out = tmp_path / "run-001"
        result = runner.invoke(
            app,
            ["run", str(a_dir), "--out", str(out), "--duration", "10s"],
        )
        assert result.exit_code == 2, (
            f"directory passed as scenario should exit 2, got {result.exit_code}"
        )

    def test_rejects_out_when_parent_missing(self, tmp_path: Path) -> None:
        scenario = tmp_path / "scenario.yaml"
        scenario.write_text("")
        out = tmp_path / "nonexistent-parent" / "run-001"
        result = runner.invoke(
            app,
            ["run", str(scenario), "--out", str(out), "--duration", "10s"],
        )
        assert result.exit_code == 2, (
            f"--out with missing parent should exit 2, got {result.exit_code}"
        )

    def test_rejects_out_when_parent_is_file(self, tmp_path: Path) -> None:
        scenario = tmp_path / "scenario.yaml"
        scenario.write_text("")
        parent_as_file = tmp_path / "a-file"
        parent_as_file.write_text("")
        out = parent_as_file / "run-001"
        result = runner.invoke(
            app,
            ["run", str(scenario), "--out", str(out), "--duration", "10s"],
        )
        assert result.exit_code == 2, (
            f"--out whose parent is a regular file should exit 2, got {result.exit_code}"
        )

    def test_rejects_out_when_path_already_exists(self, tmp_path: Path) -> None:
        scenario = tmp_path / "scenario.yaml"
        scenario.write_text("")
        out = tmp_path / "run-001"
        out.mkdir()
        result = runner.invoke(
            app,
            ["run", str(scenario), "--out", str(out), "--duration", "10s"],
        )
        assert result.exit_code == 2, (
            f"--out path that already exists should exit 2, got {result.exit_code}"
        )


def test_run_stub_with_valid_paths_exits_one(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("")
    out = tmp_path / "run-001"
    result = runner.invoke(
        app,
        ["run", str(scenario), "--out", str(out), "--duration", "10s"],
    )
    assert result.exit_code == 1


class TestStepPathValidation:
    def test_rejects_missing_run_dir(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing-run"
        result = runner.invoke(app, ["step", str(missing), "--next"])
        assert result.exit_code == 2, (
            f"missing run_dir should exit 2 (BadParameter), got {result.exit_code}"
        )

    def test_rejects_file_as_run_dir(self, tmp_path: Path) -> None:
        a_file = tmp_path / "not-a-dir"
        a_file.write_text("")
        result = runner.invoke(app, ["step", str(a_file), "--next"])
        assert result.exit_code == 2, (
            f"file passed as run_dir should exit 2, got {result.exit_code}"
        )


def test_step_stub_with_valid_run_dir_exits_one(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-001"
    run_dir.mkdir()
    result = runner.invoke(app, ["step", str(run_dir), "--next"])
    assert result.exit_code == 1


class TestInspectPathValidation:
    def test_rejects_missing_run_dir(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing-run"
        result = runner.invoke(app, ["inspect", str(missing)])
        assert result.exit_code == 2, (
            f"missing run_dir should exit 2 (BadParameter), got {result.exit_code}"
        )

    def test_rejects_file_as_run_dir(self, tmp_path: Path) -> None:
        a_file = tmp_path / "not-a-dir"
        a_file.write_text("")
        result = runner.invoke(app, ["inspect", str(a_file)])
        assert result.exit_code == 2, (
            f"file passed as run_dir should exit 2, got {result.exit_code}"
        )


def test_inspect_stub_with_valid_run_dir_exits_one(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-001"
    run_dir.mkdir()
    result = runner.invoke(app, ["inspect", str(run_dir)])
    assert result.exit_code == 1


class TestCleanPathValidation:
    def test_rejects_missing_run_dir(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing-run"
        result = runner.invoke(app, ["clean", str(missing)])
        assert result.exit_code == 2, (
            f"missing run_dir should exit 2 (BadParameter), got {result.exit_code}"
        )

    def test_rejects_file_as_run_dir(self, tmp_path: Path) -> None:
        a_file = tmp_path / "not-a-dir"
        a_file.write_text("")
        result = runner.invoke(app, ["clean", str(a_file)])
        assert result.exit_code == 2, (
            f"file passed as run_dir should exit 2, got {result.exit_code}"
        )


def test_clean_stub_with_valid_run_dir_exits_one(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-001"
    run_dir.mkdir()
    result = runner.invoke(app, ["clean", str(run_dir)])
    assert result.exit_code == 1


class TestReplayPathValidation:
    def test_rejects_missing_bundle(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing-replay.json"
        out = tmp_path / "replay-out"
        result = runner.invoke(app, ["replay", str(missing), "--out", str(out)])
        assert result.exit_code == 2, (
            f"missing bundle should exit 2 (BadParameter), got {result.exit_code}"
        )

    def test_rejects_directory_as_bundle(self, tmp_path: Path) -> None:
        a_dir = tmp_path / "a-dir"
        a_dir.mkdir()
        out = tmp_path / "replay-out"
        result = runner.invoke(app, ["replay", str(a_dir), "--out", str(out)])
        assert result.exit_code == 2, (
            f"directory passed as bundle should exit 2, got {result.exit_code}"
        )

    def test_rejects_out_when_parent_missing(self, tmp_path: Path) -> None:
        bundle = tmp_path / "replay.json"
        bundle.write_text("")
        out = tmp_path / "nonexistent-parent" / "replay-out"
        result = runner.invoke(app, ["replay", str(bundle), "--out", str(out)])
        assert result.exit_code == 2, (
            f"--out with missing parent should exit 2, got {result.exit_code}"
        )

    def test_rejects_out_when_parent_is_file(self, tmp_path: Path) -> None:
        bundle = tmp_path / "replay.json"
        bundle.write_text("")
        parent_as_file = tmp_path / "a-file"
        parent_as_file.write_text("")
        out = parent_as_file / "replay-out"
        result = runner.invoke(app, ["replay", str(bundle), "--out", str(out)])
        assert result.exit_code == 2, (
            f"--out whose parent is a regular file should exit 2, got {result.exit_code}"
        )

    def test_rejects_out_when_path_already_exists(self, tmp_path: Path) -> None:
        bundle = tmp_path / "replay.json"
        bundle.write_text("")
        out = tmp_path / "replay-out"
        out.mkdir()
        result = runner.invoke(app, ["replay", str(bundle), "--out", str(out)])
        assert result.exit_code == 2, (
            f"--out path that already exists should exit 2, got {result.exit_code}"
        )


def test_replay_stub_with_valid_paths_exits_one(tmp_path: Path) -> None:
    bundle = tmp_path / "replay.json"
    bundle.write_text("")
    out = tmp_path / "replay-out"
    result = runner.invoke(app, ["replay", str(bundle), "--out", str(out)])
    assert result.exit_code == 1


def test_top_level_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in [
        "validate",
        "plan",
        "materialize",
        "run",
        "step",
        "replay",
        "inspect",
        "capabilities",
        "clean",
    ]:
        assert command in result.stdout
