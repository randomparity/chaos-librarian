"""Validation pipeline: orchestrator and IssueCollector.

Flow (matches the Sprint 1 design spec):

1. ``load_scenario(path)`` → if it raises ``ScenarioLoadError``, emit one
   ``E_YAML_PARSE`` issue and return early.
1.5. **Top-level shape guard.** If ``raw_data`` is not a ``dict``, emit
   ``E_TOP_LEVEL_NOT_MAPPING`` and return early. Subsequent passes assume
   a mapping and would crash on a list or scalar.
2. ``run_shape_pass`` (Pydantic ``Scenario.model_validate``) → emits zero
   or more issues; returns ``Scenario | None``.
3. ``run_semantic_pass`` → runs unconditionally, even if step 2 produced
   issues. Each rule guards its own preconditions.
4. Assemble ``ValidationReport`` with ``scenario_id`` from raw_data (else
   ``"<unknown>"``), ``ok = (no ERROR issues)``, and issues sorted by
   (line, column, code) for stable output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from chaos_librarian.contract.validation import (
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from chaos_librarian.scenario_io import (
    LineIndex,
    ScenarioLoadError,
    load_scenario,
)
from chaos_librarian.validation import codes
from chaos_librarian.validation.semantic import run_semantic_pass
from chaos_librarian.validation.shape import run_shape_pass


@dataclass
class IssueCollector:
    """Accumulator passed to every pass; resolves loc → (line, column)."""

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
                path=codes.format_jsonpath(loc) if loc else None,
            )
        )


def run_validation(scenario_path: Path) -> ValidationReport:
    """Run the full validation pipeline against a scenario file.

    Returns a ``ValidationReport`` regardless of outcome. ``report.ok``
    is ``True`` iff zero ERROR-severity issues accumulated.
    """
    collector = IssueCollector()

    # Step 1: load.
    try:
        raw_data, line_index = load_scenario(scenario_path)
    except ScenarioLoadError as e:
        collector.add(
            code=codes.E_YAML_PARSE,
            severity=ValidationSeverity.ERROR,
            message=str(e),
            loc=(),
            line_index=LineIndex(),
        )
        return _assemble_report(scenario_id="<unknown>", collector=collector)

    # Step 1.5: top-level shape guard. A non-mapping top level would crash
    # the shape pass; emit a structured issue and stop here.
    if not isinstance(raw_data, dict):
        collector.add(
            code=codes.E_TOP_LEVEL_NOT_MAPPING,
            severity=ValidationSeverity.ERROR,
            message=(f"top-level YAML is {type(raw_data).__name__}, expected mapping"),
            loc=(),
            line_index=LineIndex(),
        )
        return _assemble_report(scenario_id="<unknown>", collector=collector)

    # Step 2: shape pass.
    run_shape_pass(raw_data, line_index, collector)

    # Step 3: semantic pass (runs even if shape produced issues; rules guard).
    run_semantic_pass(raw_data, line_index, collector)

    # Step 4: assemble.
    scenario_id_raw = raw_data.get("scenario_id")
    scenario_id = scenario_id_raw if isinstance(scenario_id_raw, str) else "<unknown>"
    return _assemble_report(scenario_id=scenario_id, collector=collector)


def _assemble_report(scenario_id: str, collector: IssueCollector) -> ValidationReport:
    # ``line`` / ``column`` are ``None`` for un-located issues (E_YAML_PARSE,
    # E_TOP_LEVEL_NOT_MAPPING) — coercing to 0 sorts them ahead of every
    # located issue, so file-wide problems appear at the top of the report.
    issues_sorted = sorted(
        collector.issues,
        key=lambda i: (i.line or 0, i.column or 0, i.code),
    )
    ok = not any(i.severity == ValidationSeverity.ERROR for i in issues_sorted)
    return ValidationReport(
        schema_version=1,
        scenario_id=scenario_id,
        ok=ok,
        issues=issues_sorted,
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
    # Top-level fallback.
    top = line_index.lookup(())
    if top is not None:
        return top
    return 1, 0
