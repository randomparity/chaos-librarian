"""Tests for the CLI stub. All commands exist; only ``validate`` is real.

The path-validation tests are parameterized over the table of commands
that take a file-or-directory positional argument. Adding a new command
to ``_FILE_ARG_COMMANDS`` or ``_DIR_ARG_COMMANDS`` extends the suite
automatically — earlier sprints had seven near-identical test classes
that had to be edited in lockstep.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app

# Click 8.2+ removed mix_stderr from CliRunner.__init__; stdout and stderr are
# now separate by default, which matches the intent of the original spec.
runner = CliRunner()

ALL_COMMANDS = [
    "validate",
    "plan",
    "materialize",
    "run",
    "step",
    "replay",
    "inspect",
    "capabilities",
    "clean",
]


def test_registered_commands_match_expected_order() -> None:
    """The CLI contract pins the order ``--help`` lists commands.

    WHY (per CLAUDE.md Rule 9): Typer renders ``--help`` in the order
    ``@app.command()`` decorators run. Each command lives in its own
    module under ``cli/commands/``; ``cli/commands/__init__.py`` imports
    them in the contract order. A forgotten ``import`` line silently
    drops a command from ``--help`` and the rest shift up — this test
    catches both regressions.
    """
    # cmd.name is None when the command name was inferred from the
    # callback's function name. Fall back to a getattr lookup so ``ty``
    # doesn't have to prove that callback is a function (per ty's
    # callable-vs-function rules).
    registered = [
        cmd.name or getattr(cmd.callback, "__name__", "<anonymous>")
        for cmd in app.registered_commands
    ]
    assert registered == ALL_COMMANDS


# Commands whose positional argument is a regular file (``exists=True,
# dir_okay=False``). Tuple entries are ``(name, extra_args, takes_out)``
# where ``extra_args`` is appended after the positional and ``takes_out``
# means the command also accepts ``--out <path>``.
_FILE_ARG_COMMANDS: list[tuple[str, list[str], bool]] = [
    ("validate", [], False),
    ("plan", [], True),
    ("materialize", [], True),
    ("run", ["--duration", "10s"], True),
    ("replay", [], True),
]

# Subset that accepts ``--out``; tests targeting --out paramaterize over
# ``(name, extra_args)`` only.
_FILE_ARG_WITH_OUT: list[tuple[str, list[str]]] = [
    (name, extra) for (name, extra, takes_out) in _FILE_ARG_COMMANDS if takes_out
]

# Commands whose positional argument is a directory (``exists=True,
# file_okay=False``).
_DIR_ARG_COMMANDS: list[tuple[str, list[str]]] = [
    ("step", ["--next", "1"]),
    ("inspect", []),
    ("clean", []),
]


def _invoke_with_file_arg(
    name: str,
    extra_args: list[str],
    takes_out: bool,
    file_path: Path,
    out: Path,
) -> int:
    args = [name, str(file_path)]
    if takes_out:
        args += ["--out", str(out)]
    args += extra_args
    return runner.invoke(app, args).exit_code


def _invoke_with_dir_arg(name: str, extra_args: list[str], dir_path: Path) -> int:
    return runner.invoke(app, [name, str(dir_path), *extra_args]).exit_code


# ---- top-level surface -----------------------------------------------------


@pytest.mark.parametrize("command", ALL_COMMANDS)
def test_command_exists_and_help_succeeds(command: str) -> None:
    """Every command in the public CLI surface must accept --help.

    WHY: the surface is frozen contract; a renamed/removed command breaks
    downstream tooling.
    """
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0, f"--help should always succeed for {command}"


def test_top_level_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ALL_COMMANDS:
        assert command in result.stdout


# ---- file-argument commands: positional rejections -------------------------


@pytest.mark.parametrize(("name", "extra_args", "takes_out"), _FILE_ARG_COMMANDS)
def test_file_arg_rejects_missing_path(
    name: str,
    extra_args: list[str],
    takes_out: bool,
    tmp_path: Path,
) -> None:
    """A nonexistent positional argument exits 2 (Typer BadParameter)."""
    missing = tmp_path / "missing.yaml"
    out = tmp_path / "run-001"
    assert _invoke_with_file_arg(name, extra_args, takes_out, missing, out) == 2


@pytest.mark.parametrize(("name", "extra_args", "takes_out"), _FILE_ARG_COMMANDS)
def test_file_arg_rejects_directory(
    name: str,
    extra_args: list[str],
    takes_out: bool,
    tmp_path: Path,
) -> None:
    """Passing a directory to a file-only positional argument exits 2."""
    a_dir = tmp_path / "a-dir"
    a_dir.mkdir()
    out = tmp_path / "run-001"
    assert _invoke_with_file_arg(name, extra_args, takes_out, a_dir, out) == 2


# ---- --out rejections (only the commands that accept --out) ----------------


@pytest.mark.parametrize(("name", "extra_args"), _FILE_ARG_WITH_OUT)
def test_out_rejects_parent_missing(
    name: str,
    extra_args: list[str],
    tmp_path: Path,
) -> None:
    """``--out`` whose parent directory does not exist exits 2."""
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("")
    out = tmp_path / "nonexistent-parent" / "run-001"
    assert _invoke_with_file_arg(name, extra_args, True, scenario, out) == 2


@pytest.mark.parametrize(("name", "extra_args"), _FILE_ARG_WITH_OUT)
def test_out_rejects_parent_is_file(
    name: str,
    extra_args: list[str],
    tmp_path: Path,
) -> None:
    """``--out`` whose parent is a regular file exits 2."""
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("")
    parent_as_file = tmp_path / "a-file"
    parent_as_file.write_text("")
    out = parent_as_file / "run-001"
    assert _invoke_with_file_arg(name, extra_args, True, scenario, out) == 2


@pytest.mark.parametrize(("name", "extra_args"), _FILE_ARG_WITH_OUT)
def test_out_rejects_already_existing_path(
    name: str,
    extra_args: list[str],
    tmp_path: Path,
) -> None:
    """``--out`` pointing at an existing path exits 2."""
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("")
    out = tmp_path / "run-001"
    out.mkdir()
    assert _invoke_with_file_arg(name, extra_args, True, scenario, out) == 2


# ---- directory-argument commands -------------------------------------------


@pytest.mark.parametrize(("name", "extra_args"), _DIR_ARG_COMMANDS)
def test_dir_arg_rejects_missing(
    name: str,
    extra_args: list[str],
    tmp_path: Path,
) -> None:
    """A nonexistent run_dir exits 2."""
    missing = tmp_path / "missing-run"
    assert _invoke_with_dir_arg(name, extra_args, missing) == 2


@pytest.mark.parametrize(("name", "extra_args"), _DIR_ARG_COMMANDS)
def test_dir_arg_rejects_file(
    name: str,
    extra_args: list[str],
    tmp_path: Path,
) -> None:
    """Passing a regular file to a dir-only positional argument exits 2."""
    a_file = tmp_path / "not-a-dir"
    a_file.write_text("")
    assert _invoke_with_dir_arg(name, extra_args, a_file) == 2


# ---- stubs return 1 once the args are valid --------------------------------
#
# These guard against the failure mode where path-validation passes but the
# stub regresses (e.g. accidentally raises an unexpected exception). They are
# parameterized over the file-argument and directory-argument tables.


@pytest.mark.parametrize(("name", "extra_args", "takes_out"), _FILE_ARG_COMMANDS)
def test_file_arg_stub_with_valid_paths_exits_one(
    name: str,
    extra_args: list[str],
    takes_out: bool,
    tmp_path: Path,
) -> None:
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("")
    out = tmp_path / "run-001"
    code = _invoke_with_file_arg(name, extra_args, takes_out, scenario, out)
    # ``validate`` (Sprint 1), ``plan`` (Sprint 3), and ``materialize`` (Sprint 5)
    # are real commands — an empty file fails shape validation with
    # E_TOP_LEVEL_NOT_MAPPING and the command exits 3. The remaining stub
    # commands exit 1.
    if name in {"validate", "plan", "materialize"}:
        assert code == 3
    else:
        assert code == 1


@pytest.mark.parametrize(("name", "extra_args"), _DIR_ARG_COMMANDS)
def test_dir_arg_stub_with_valid_dir_exits_one(
    name: str,
    extra_args: list[str],
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run-001"
    run_dir.mkdir()
    code = _invoke_with_dir_arg(name, extra_args, run_dir)
    # ``step``, ``inspect``, and ``clean`` (Sprint 4) are real commands —
    # an empty run_dir has no sentinel, so they exit 7 (sentinel_invalid).
    # Other dir-arg commands are still stubs and exit 1.
    if name in {"step", "inspect", "clean"}:
        assert code == 7
    else:
        assert code == 1
