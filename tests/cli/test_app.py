"""Tests for the CLI stub. All commands exist and exit 1 in Sprint 0."""

from __future__ import annotations

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


@pytest.mark.parametrize(
    "command_args",
    [
        ["validate", "scenario.yaml"],
        ["plan", "scenario.yaml", "--out", "fixtures/run-001"],
        ["materialize", "scenario.yaml", "--out", "fixtures/run-001"],
        ["run", "scenario.yaml", "--out", "fixtures/run-001", "--duration", "10s"],
        ["step", "fixtures/run-001", "--next"],
        ["replay", "fixtures/run-001/replay.json", "--out", "fixtures/replay-001"],
        ["inspect", "fixtures/run-001"],
        ["capabilities"],
        ["clean", "fixtures/run-001"],
    ],
)
def test_stub_command_exits_one(command_args: list[str]) -> None:
    result = runner.invoke(app, command_args)
    assert result.exit_code == 1, f"Stub {command_args[0]} should exit 1"


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
