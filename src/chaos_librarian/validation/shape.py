"""Pydantic shape-validation pass.

Accesses ``RunInput.scenario`` (which lazily parses via
``Scenario.model_validate``) and maps each ``ValidationError`` entry
to a ``ValidationIssue`` with a stable error code, a JSONPath, and a
line/column resolved via the ``LineIndex``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.validation.codes import E_FIELD_SHAPE, PYDANTIC_TO_CODE

if TYPE_CHECKING:
    from chaos_librarian.validation.input import RunInput
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["run_shape_pass"]


def run_shape_pass(run_input: RunInput, collector: IssueCollector) -> None:
    """Validate the scenario shape via ``RunInput.scenario``; collect issues.

    On success, accessing the ``scenario`` cached_property populates the
    RunInput cache so downstream consumers (``run_plan``,
    ``materialize_scenario``) reuse the same parse rather than re-validating.
    On failure, the cache remains empty and the ValidationError is decomposed
    into structured ``ValidationIssue`` entries on ``collector``.
    """
    try:
        _ = run_input.scenario
    except ValidationError as e:
        for entry in e.errors(include_url=False, include_context=True):
            pydantic_type = entry["type"]
            code = PYDANTIC_TO_CODE.get(pydantic_type, E_FIELD_SHAPE)
            if code == E_FIELD_SHAPE:
                message = f"{entry['msg']} (pydantic type: {pydantic_type})"
            else:
                message = entry["msg"]
            loc = tuple(entry["loc"])
            collector.add(
                code=code,
                severity=ValidationSeverity.ERROR,
                message=message,
                loc=loc,
                line_index=run_input.line_index,
            )
