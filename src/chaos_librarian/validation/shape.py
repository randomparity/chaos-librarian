"""Pydantic shape-validation pass. Implemented in Task 5."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector


def run_shape_pass(
    raw_data: dict[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Stub - Task 5 fills this in."""
    return None
