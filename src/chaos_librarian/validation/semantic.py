"""Semantic-validation pass. Rules are registered in Tasks 6-12."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector


def run_semantic_pass(
    raw_data: dict[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Stub - Task 6 starts the rule registry; Tasks 7-12 add rules."""
    return None
