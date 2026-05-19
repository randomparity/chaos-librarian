"""Materializer error hierarchy — every subclass carries an error_code."""

from __future__ import annotations

from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.validation import (
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from chaos_librarian.materializer.errors import (
    CapabilityGateError,
    ContainmentViolationError,
    MaterializationError,
    ProbeParseError,
    ScenarioValidationError,
    TimelineUnsupportedError,
    ToolFailedError,
    UnsupportedMaterializationError,
)


def test_every_subclass_carries_an_error_code():
    """WHY: the CLI handler dispatches on the subclass and reads error_code
    into the stdout JSON payload; if any subclass forgets to set it, the
    agent sees a payload missing the field."""
    for cls in (
        TimelineUnsupportedError,
        UnsupportedMaterializationError,
        ToolFailedError,
        ProbeParseError,
        ContainmentViolationError,
        CapabilityGateError,
        ScenarioValidationError,
    ):
        assert issubclass(cls, MaterializationError)
        assert hasattr(cls, "error_code")
        assert cls.error_code.startswith("E_MATERIALIZE_") or cls.error_code in {
            "E_PATH_CONTAINMENT",
            "E_MATERIALIZE_CAPABILITY_GATE",
        }


def test_base_error_holds_payload():
    """WHY: every error carries the structured payload the CLI emits as
    --json stdout; missing fields default to None so the payload shape is
    consistent across error types."""
    err = UnsupportedMaterializationError(
        message="x",
        asset_id="a0",
        field="audio[0].codec",
        payload={"supported": ["aac"]},
    )
    assert err.error_code == "E_MATERIALIZE_UNSUPPORTED"
    assert err.payload["supported"] == ["aac"]


def test_tool_failed_carries_invocation():
    """WHY: the ToolFailedError uniquely carries the failing ToolInvocation
    so the CLI can record it in materialization.json — failing the assertion
    would mean we lose subprocess stderr at the exit boundary."""
    invocation = ToolInvocation(
        tool="ffmpeg",
        version="7.1.1",
        command=["ffmpeg", "-i", "..."],
        exit_code=1,
        duration_ns=1_000_000,
    )
    err = ToolFailedError(
        message="ffmpeg failed",
        asset_id="a0",
        field=None,
        payload={"stderr_tail": "x264 error"},
        invocation=invocation,
    )
    assert err.invocation.exit_code == 1


def test_scenario_validation_error_carries_report():
    """WHY: the materialize entry validates the scenario explicitly before
    any run-dir allocation (Finding 1). When semantic validation fails, the
    orchestrator raises ScenarioValidationError carrying the full
    ValidationReport so the CLI can serialize it into the stdout JSON
    payload at exit 3 — the same shape as `plan`'s reference behavior."""
    report = ValidationReport(
        schema_version=1,
        ok=False,
        scenario_id="bad",
        issues=[
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="E_PATH_CONTAINMENT",
                message="asset path escapes library/",
                line=None,
                column=None,
                path=None,
            )
        ],
    )
    err = ScenarioValidationError(
        "scenario failed semantic validation",
        payload={"validation_report": report.model_dump(mode="json", exclude_none=True)},
        validation_report=report,
    )
    assert err.error_code == "E_MATERIALIZE_VALIDATION_FAILED"
    assert err.validation_report.ok is False
    assert err.validation_report.issues[0].code == "E_PATH_CONTAINMENT"
