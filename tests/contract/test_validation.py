"""Tests for the validation report schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import VALIDATION_SCHEMA_VERSION
from chaos_librarian.contract.validation import (
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)


def test_ok_report_roundtrip() -> None:
    r = ValidationReport(
        schema_version=VALIDATION_SCHEMA_VERSION,
        scenario_id="s1",
        ok=True,
        issues=[],
    )
    assert ValidationReport.model_validate_json(r.model_dump_json()) == r


def test_failing_report_with_issues() -> None:
    r = ValidationReport(
        schema_version=VALIDATION_SCHEMA_VERSION,
        scenario_id="s1",
        ok=False,
        issues=[
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="path.absolute",
                message="absolute scenario path",
                line=12,
                column=5,
                path="timeline[0].to",
            )
        ],
    )
    loaded = ValidationReport.model_validate_json(r.model_dump_json())
    assert loaded.issues[0].severity is ValidationSeverity.ERROR


def test_rejects_unknown_severity() -> None:
    bad = {
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "scenario_id": "s1",
        "ok": False,
        "issues": [
            {"severity": "panic", "code": "x", "message": "y"},
        ],
    }
    with pytest.raises(ValidationError):
        ValidationReport.model_validate(bad)
