"""Validation pipeline orchestrator.

Flow (matches the Sprint 1 design spec):

1. Caller invokes ``prepare_run_input(path)`` to byte-bind the read; on
   ``ScenarioLoadError`` the caller is responsible for synthesizing an
   ``E_YAML_PARSE`` report (the CLI helper ``_synthesize_yaml_parse_report``
   does this). ``run_validation`` itself receives an already-parsed
   ``RunInput`` so validation, planning, and the replay bundle all
   describe the same byte sequence.
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

from chaos_librarian.contract.validation import ValidationReport, ValidationSeverity
from chaos_librarian.validation.codes import E_TOP_LEVEL_NOT_MAPPING
from chaos_librarian.validation.input import RunInput
from chaos_librarian.validation.reporting import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass
from chaos_librarian.validation.shape import run_shape_pass


def run_validation(run_input: RunInput) -> ValidationReport:
    """Run the full validation pipeline against a pre-read scenario.

    The ``ScenarioLoadError`` branch lives in ``prepare_run_input`` now;
    callers that may face a malformed YAML file must catch it there and
    synthesize an ``E_YAML_PARSE`` report themselves.

    Returns a ``ValidationReport`` regardless of outcome. ``report.ok``
    is ``True`` iff zero ERROR-severity issues accumulated.
    """
    collector = IssueCollector()
    raw_data = run_input.raw_data
    line_index = run_input.line_index

    # Step 1.5: top-level shape guard. A non-mapping top level would crash
    # the shape pass; emit a structured issue and stop here.
    if not isinstance(raw_data, dict):
        collector.add(
            code=E_TOP_LEVEL_NOT_MAPPING,
            severity=ValidationSeverity.ERROR,
            message=(f"top-level YAML is {type(raw_data).__name__}, expected mapping"),
            loc=(),
            line_index=line_index,
        )
        return _assemble_report(scenario_id="<unknown>", collector=collector)

    # Step 2: shape pass (also primes ``RunInput.scenario`` cache on success).
    run_shape_pass(run_input, collector)

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
