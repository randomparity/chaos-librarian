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
from chaos_librarian.validation.pipeline import run_validation

__all__ = [
    "ValidationReport",
    "ValidationSeverity",
    "run_validation",
]
