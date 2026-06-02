"""CLI handling for materializer exception envelopes."""

from __future__ import annotations

from pathlib import Path
from typing import NoReturn

import typer

from chaos_librarian.cli._envelope import emit_materialize_error
from chaos_librarian.materializer.errors import (
    CapabilityGateError,
    ContainmentViolationError,
    CorruptionActionError,
    FilesystemActionError,
    MaterializationError,
    MediaActionError,
    ProbeParseError,
    ScenarioValidationError,
    TimelineUnsupportedError,
    ToolFailedError,
    UnsupportedMaterializationError,
)

_REPORT_BACKED_ERRORS = (
    ToolFailedError,
    ProbeParseError,
    FilesystemActionError,
    MediaActionError,
    CorruptionActionError,
)
_REPLAY_REPORT_BACKED_ERRORS = (
    TimelineUnsupportedError,
    UnsupportedMaterializationError,
    *_REPORT_BACKED_ERRORS,
)


def exit_materialization_error(
    exc: MaterializationError,
    *,
    json_output: bool,
    run_dir: Path | None,
) -> NoReturn:
    """Emit the shared materialization envelope and exit with the mapped code."""
    emit_materialize_error(exc, json_output=json_output, run_dir=run_dir)
    raise typer.Exit(code=_exit_code(exc)) from exc


def materialize_command_report_dir(exc: MaterializationError, out: Path) -> Path | None:
    """Return the report directory for materialize/run errors that write one."""
    if isinstance(exc, _REPORT_BACKED_ERRORS):
        return out
    return None


def replay_command_report_dir(exc: MaterializationError, out: Path) -> Path | None:
    """Return the report directory for replay errors that write one."""
    if isinstance(exc, _REPLAY_REPORT_BACKED_ERRORS):
        return out
    return None


def _exit_code(exc: MaterializationError) -> int:
    if isinstance(exc, CapabilityGateError):
        return 4
    if isinstance(exc, ScenarioValidationError):
        return 3
    if isinstance(exc, ContainmentViolationError):
        return 7
    return 5
