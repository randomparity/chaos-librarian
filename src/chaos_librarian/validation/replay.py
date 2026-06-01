"""Validation-owned preparation for replayed scenario bytes."""

from __future__ import annotations

from dataclasses import dataclass

from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.validation.input import RunInput, prepare_run_input_from_bytes
from chaos_librarian.validation.pipeline import run_validation


@dataclass(frozen=True)
class PreparedReplayInput:
    """Scenario bytes and validation report prepared for replay consumers.

    Attributes:
        run_input: The byte-bound scenario input created from the bundle's
            embedded scenario text.
        validation_report: The validation result for ``run_input``. Replay
            consumers decide whether a failed report is an integrity error for
            their mode.
    """

    run_input: RunInput
    validation_report: ValidationReport


def prepare_replay_input_from_bytes(
    *,
    scenario_bytes: bytes,
    source_label: str,
) -> PreparedReplayInput:
    """Prepare embedded replay scenario bytes and run validation once.

    Args:
        scenario_bytes: The exact scenario bytes embedded in a replay bundle.
        source_label: Diagnostic source label for parse and validation errors.

    Returns:
        The byte-bound ``RunInput`` plus its validation report.
    """
    run_input = prepare_run_input_from_bytes(
        raw_bytes=scenario_bytes,
        source_label=source_label,
    )
    return PreparedReplayInput(
        run_input=run_input,
        validation_report=run_validation(run_input),
    )
