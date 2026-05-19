"""Pydantic shape-validation pass.

Parses ``RunInput.raw_data`` via ``Scenario.model_validate`` and maps each
``ValidationError`` entry to a ``ValidationIssue`` with a stable error
code, a JSONPath, and a line/column resolved via the ``LineIndex``.

The shape pass is authoritative for ``RunInput.scenario``: on success it
writes the freshly parsed Scenario into the RunInput cache slot; on
failure it invalidates any prior cache entry. Reading the cached
property directly here would let a caller that pre-populated the cache
and then mutated ``raw_data`` bypass validation entirely (Codex round 3
finding).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.validation.codes import E_FIELD_SHAPE, PYDANTIC_TO_CODE

if TYPE_CHECKING:
    from chaos_librarian.validation.input import RunInput
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["run_shape_pass"]


def run_shape_pass(run_input: RunInput, collector: IssueCollector) -> None:
    """Parse ``run_input.raw_data`` fresh; populate the cache on success.

    Parses ``Scenario.model_validate(run_input.raw_data)`` directly rather
    than reading ``run_input.scenario``. This guarantees the shape pass
    sees the *current* ``raw_data`` even if a caller pre-populated the
    cache by accessing ``run_input.scenario`` before validation ran.

    On success: the cache slot in ``run_input.__dict__["scenario"]`` is
    overwritten with the fresh parse so downstream consumers reuse it.
    On failure: the cache slot is removed (if any) so subsequent
    ``run_input.scenario`` access re-parses (and re-raises) rather than
    returning a stale value.
    """
    try:
        parsed = Scenario.model_validate(run_input.raw_data)
    except ValidationError as e:
        # Invalidate any stale cache from prior access. cached_property
        # stores results in __dict__ keyed by the attribute name.
        run_input.__dict__.pop("scenario", None)
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
    # Authoritative cache write: overwrites any pre-existing value.
    run_input.__dict__["scenario"] = parsed
