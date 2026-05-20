"""Materializer error hierarchy — every subclass carries an error_code."""

from __future__ import annotations

from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.contract.validation import (
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from chaos_librarian.materializer.errors import (
    CapabilityGateError,
    ContainmentViolationError,
    FilesystemActionError,
    MaterializationError,
    MediaActionError,
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
        FilesystemActionError,
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


def test_filesystem_action_error_carries_event_id_action_errno() -> None:
    """WHY: phase-B helpers raise OSError mid-mutation; the orchestrator wraps
    it with the originating event_id, the TimelineActionName, and the errno so
    the CLI can emit a structured JSON payload at exit 4 without
    introspecting __cause__ — and so reviewers see exactly which mutation
    failed when library/ has been wiped."""
    cause = OSError(2, "No such file or directory")
    err = FilesystemActionError(
        "move_asset failed for event move_001: no such file",
        event_id="move_001",
        cause=cause,
        action=TimelineActionName.MOVE_ASSET,
        asset_id="asset_hd_main",
    )
    assert err.error_code == "E_MATERIALIZE_FS_FAILED"
    assert err.event_id == "move_001"
    assert err.cause is cause
    assert err.action is TimelineActionName.MOVE_ASSET
    assert err.payload["event_id"] == "move_001"
    assert err.payload["action"] == "move_asset"
    assert err.payload["errno"] == 2


def test_filesystem_action_error_accepts_non_oserror_cause() -> None:
    """WHY: the dispatcher widened its trap from ``OSError`` to ``Exception``
    so contract-drift bugs (KeyError from scenario_assets lookup, AssertionError
    from a malformed journal entry) still route through cleanup + exit 5
    instead of escaping unwrapped. Non-OSError causes carry ``errno=None``."""
    cause = KeyError("asset_does_not_exist")
    err = FilesystemActionError(
        "create_sidecar failed for event cs_unknown",
        event_id="cs_unknown",
        cause=cause,
        action=TimelineActionName.CREATE_SIDECAR,
        asset_id="asset_does_not_exist",
    )
    assert err.cause is cause
    assert err.payload["errno"] is None
    assert err.payload["action"] == "create_sidecar"


def test_media_action_error_payload_carries_event_action_invocation():
    cause = RuntimeError("ffmpeg exit 1")
    err = MediaActionError(
        "reencode_video failed for event ev_rv_001",
        event_id="ev_rv_001",
        action=TimelineActionName.REENCODE_VIDEO,
        cause=cause,
        asset_id="asset_main",
        tool_invocation_index=3,
    )
    assert err.error_code == "E_MATERIALIZE_MEDIA_FAILED"
    assert err.event_id == "ev_rv_001"
    assert err.action == TimelineActionName.REENCODE_VIDEO
    assert err.cause is cause
    assert err.tool_invocation_index == 3
    assert err.payload["event_id"] == "ev_rv_001"
    assert err.payload["action"] == "reencode_video"
    assert err.payload["tool_invocation_index"] == 3
    assert err.asset_id == "asset_main"


def test_media_action_error_subclass_of_materialization_error():
    err = MediaActionError(
        "x",
        event_id="e0",
        action=TimelineActionName.REENCODE_VIDEO,
        cause=RuntimeError("y"),
    )
    assert isinstance(err, MaterializationError)
