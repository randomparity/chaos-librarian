"""Phase-B materializer public surface."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chaos_librarian.materializer.phase_b.dispatch import (
        PhaseBError,
        PhaseBState,
        PhaseBStateInputs,
        augment_phase_b_outputs,
        dispatch_phase_b_entry,
        make_phase_b_state,
        phase_b_failure_outcome,
        phase_b_failure_record,
    )

__all__ = [
    "PhaseBError",
    "PhaseBState",
    "PhaseBStateInputs",
    "augment_phase_b_outputs",
    "dispatch_phase_b_entry",
    "make_phase_b_state",
    "phase_b_failure_outcome",
    "phase_b_failure_record",
]


def __getattr__(name: str) -> object:
    """Load dispatch re-exports only when callers ask for them."""
    if name not in __all__:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    dispatch = import_module("chaos_librarian.materializer.phase_b.dispatch")
    value = getattr(dispatch, name)
    globals()[name] = value
    return value
