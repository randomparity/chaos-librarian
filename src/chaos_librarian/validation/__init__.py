"""Public surface for the validation pipeline.

Re-exports the two contract DTOs that ``run_validation`` returns
(``ValidationReport``, ``ValidationSeverity``) so callers can import
everything they need from this one module instead of distinguishing
the contract package from the pipeline package at the CLI seam.
"""

from __future__ import annotations

from chaos_librarian.contract.validation import (
    ValidationReport,
    ValidationSeverity,
)
from chaos_librarian.validation.input import (
    RunInput,
    prepare_run_input,
    prepare_run_input_from_bytes,
)
from chaos_librarian.validation.pipeline import run_validation
from chaos_librarian.validation.replay import (
    PreparedReplayInput,
    prepare_replay_input_from_bytes,
)

__all__ = [
    "PreparedReplayInput",
    "RunInput",
    "ValidationReport",
    "ValidationSeverity",
    "prepare_replay_input_from_bytes",
    "prepare_run_input",
    "prepare_run_input_from_bytes",
    "run_validation",
]
