"""Pydantic shape-validation pass.

Calls ``Scenario.model_validate`` and maps each ``ValidationError`` entry
to a ``ValidationIssue`` with a stable error code, a JSONPath, and a
line/column resolved via the ``LineIndex``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.validation import codes

if TYPE_CHECKING:
    from collections.abc import Mapping

    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector


def run_shape_pass(
    raw_data: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> Scenario | None:
    """Validate ``raw_data`` against the Scenario model; collect any issues.

    Returns the parsed ``Scenario`` on success, ``None`` on any error.
    """
    try:
        return Scenario.model_validate(raw_data)
    except ValidationError as e:
        for entry in e.errors(include_url=False, include_context=True):
            pydantic_type = entry["type"]
            code = codes.PYDANTIC_TO_CODE.get(pydantic_type, codes.E_FIELD_SHAPE)
            if code == codes.E_FIELD_SHAPE:
                message = f"{entry['msg']} (pydantic type: {pydantic_type})"
            else:
                message = entry["msg"]
            loc = tuple(entry["loc"])
            collector.add(
                code=code,
                severity=ValidationSeverity.ERROR,
                message=message,
                loc=loc,
                line_index=line_index,
            )
        return None
