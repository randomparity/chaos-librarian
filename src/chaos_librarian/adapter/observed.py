"""Observed-state JSON loader for adapter consumers."""

from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError

from chaos_librarian.adapter.errors import E_ADAPTER_OBSERVED_INVALID, AdapterInputError
from chaos_librarian.contract.observed_state import ObservedState


def load_observed_state(path: Path) -> ObservedState:
    """Load and validate a consumer-exported observed-state JSON file."""
    try:
        data = path.read_text()
        return ObservedState.model_validate_json(data)
    except (OSError, ValueError, ValidationError) as exc:
        raise AdapterInputError(
            error_code=E_ADAPTER_OBSERVED_INVALID,
            message=f"observed-state input is invalid: {exc}",
            details={"path": str(path)},
        ) from exc
