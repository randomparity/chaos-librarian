from __future__ import annotations

from chaos_librarian.cli._render import render_human
from chaos_librarian.contract.validation import (
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)


def test_render_human_prints_issue_rows(capsys) -> None:
    report = ValidationReport(
        schema_version=1,
        scenario_id="scenario-a",
        ok=False,
        issues=[
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="E_FIELD_MISSING",
                message="required field missing",
                path="$.timeline[0].target",
                line=12,
                column=4,
            )
        ],
    )

    render_human(report)

    output = capsys.readouterr().out
    assert "scenario: scenario-a" in output
    assert "status: FAIL (1 issues)" in output
    assert "ERROR" in output
    assert "E_FIELD_MISSING" in output
    assert "$.timeline[0].target" in output
    assert "line 12:4" in output
