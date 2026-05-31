"""Validation issue collection shared by shape and semantic passes."""

from __future__ import annotations

from dataclasses import dataclass, field

from chaos_librarian.contract.validation import ValidationIssue, ValidationSeverity
from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation.codes import format_jsonpath


@dataclass
class IssueCollector:
    """Accumulator passed to every validation pass; resolves loc to line/column."""

    issues: list[ValidationIssue] = field(default_factory=list)

    def add(
        self,
        *,
        code: str,
        severity: ValidationSeverity,
        message: str,
        loc: tuple[str | int, ...],
        line_index: LineIndex,
    ) -> None:
        position = _resolve_position(loc, line_index)
        self.issues.append(
            ValidationIssue(
                severity=severity,
                code=code,
                message=message,
                line=position[0],
                column=position[1],
                path=format_jsonpath(loc) if loc else None,
            )
        )


def _resolve_position(
    loc: tuple[str | int, ...],
    line_index: LineIndex,
) -> tuple[int | None, int | None]:
    """Look up ``loc`` in the line index, walking up if the exact path misses.

    Whole-file fallback is ``(1, 0)`` so issues without precise location
    still anchor to *something* — never (None, None) once a line index
    exists.
    """
    current = loc
    while current:
        hit = line_index.lookup(current)
        if hit is not None:
            return hit
        current = current[:-1]
    top = line_index.lookup(())
    if top is not None:
        return top
    return 1, 0
