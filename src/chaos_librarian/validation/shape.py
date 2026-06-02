"""Pydantic shape-validation pass.

Parses ``RunInput.raw_data`` via ``Scenario.model_validate`` and maps each
``ValidationError`` entry to a ``ValidationIssue`` with a stable error
code, a JSONPath, and a line/column resolved via the ``LineIndex``.

The shape pass is authoritative for ``RunInput.scenario``: on success it
primes the cache from a fresh parse; on failure it invalidates any prior
entry. Reading the cached property directly would let a caller that
pre-populated the cache and then mutated ``raw_data`` bypass validation
entirely.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.validation.codes import E_FIELD_SHAPE, PYDANTIC_TO_CODE

if TYPE_CHECKING:
    from chaos_librarian.validation.input import RunInput
    from chaos_librarian.validation.reporting import IssueCollector

__all__ = ["run_shape_pass"]


def run_shape_pass(run_input: RunInput, collector: IssueCollector) -> None:
    """Parse ``run_input.raw_data`` fresh; prime the cache on success.

    Parses directly rather than reading ``run_input.scenario`` so the
    shape pass sees the *current* ``raw_data`` even if a caller warmed
    the cache before validation ran.

    On success: ``prime_scenario_cache`` writes the fresh parse.
    On failure: ``invalidate_scenario_cache`` drops any prior entry so
    subsequent ``run_input.scenario`` access re-parses (and re-raises).
    """
    try:
        parsed = Scenario.model_validate(run_input.raw_data)
    except ValidationError as e:
        run_input.invalidate_scenario_cache()
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
        return
    run_input.prime_scenario_cache(parsed)
