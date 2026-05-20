"""Contract round-trip tests for MaterializationReport v3."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import MATERIALIZATION_SCHEMA_VERSION
from chaos_librarian.contract.materialization import (
    FailureStage,
    FilesystemAction,
    MaterializationFailure,
    MaterializationReport,
    MaterializedAsset,
    Outcome,
    ToolchainInfo,
    ToolInvocation,
)
from chaos_librarian.contract.scenario import TimelineActionName


def _minimal_report(**overrides: object) -> MaterializationReport:
    defaults: dict[str, object] = {
        "schema_version": MATERIALIZATION_SCHEMA_VERSION,
        "run_id": uuid.uuid4(),
        "outcome": Outcome.SUCCESS,
        "platform": "darwin-arm64",
        "started_at": datetime(2026, 5, 18, 0, 0, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 5, 18, 0, 0, 1, tzinfo=UTC),
        "toolchain": ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
    }
    defaults.update(overrides)
    return MaterializationReport.model_validate(defaults)


def test_minimal_success_report_round_trips():
    """WHY: success-path materialize writes invocations + materialized; the
    minimal report (no failures) must round-trip cleanly."""
    report = _minimal_report(
        materialized=[
            MaterializedAsset(
                asset_id="a0",
                location_path="library/movie/main.mkv",
                content_hash="sha256:" + "0" * 64,
                size_bytes=1234,
                duration_seconds=2.0,
                invocation_index=0,
            ),
        ],
        invocations=[
            ToolInvocation(
                tool="ffmpeg",
                version="7.1.1",
                command=["ffmpeg", "-version"],
                exit_code=0,
                duration_ns=1_000_000,
            ),
        ],
    )
    blob = report.model_dump_json(exclude_none=True)
    assert MaterializationReport.model_validate_json(blob) == report


def test_failure_report_records_per_asset_failure():
    """WHY: spec failure model records asset_id, stage, exit_code,
    stderr_tail, invocation_index — every materialize tool failure surfaces
    these via materialization.json so an agent can debug without grep."""
    report = _minimal_report(
        outcome=Outcome.TOOL_FAILED,
        failures=[
            MaterializationFailure(
                asset_id="a0",
                stage=FailureStage.FFMPEG,
                exit_code=1,
                stderr_tail="x264 [error]: bad input",
                invocation_index=0,
            ),
        ],
    )
    blob = report.model_dump_json(exclude_none=True)
    loaded = MaterializationReport.model_validate_json(blob)
    assert loaded.failures[0].stage == "ffmpeg"


def test_outcome_enum_accepts_all_documented_values():
    for value in (
        Outcome.SUCCESS,
        Outcome.UNSUPPORTED,
        Outcome.TOOL_FAILED,
        Outcome.TOOL_MISSING,
        Outcome.CONTAINMENT_VIOLATION,
    ):
        assert _minimal_report(outcome=value).outcome is value


def test_unknown_outcome_value_rejected():
    payload = {
        "schema_version": MATERIALIZATION_SCHEMA_VERSION,
        "run_id": str(uuid.uuid4()),
        "outcome": "broken",
        "platform": "darwin-arm64",
        "started_at": "2026-05-18T00:00:00Z",
        "finished_at": "2026-05-18T00:00:01Z",
        "toolchain": {"ffmpeg": "7.1.1"},
    }
    with pytest.raises(ValidationError):
        MaterializationReport.model_validate(payload)


def test_materialization_schema_version_is_three() -> None:
    assert MATERIALIZATION_SCHEMA_VERSION == 3


def test_filesystem_action_round_trip() -> None:
    payload = {
        "event_id": "ev_move_001",
        "action": "move_asset",
        "target_asset_id": "asset_hd_main",
        "from_path": "movies-hd/old.mkv",
        "to_path": "movies-hd/new.mkv",
        "temp_path": None,
        "duration_ns": 1_500_000,
    }
    action = FilesystemAction.model_validate(payload)
    assert action.action == TimelineActionName.MOVE_ASSET
    assert action.duration_ns == 1_500_000


def test_outcome_fs_failed_present() -> None:
    assert Outcome("fs_failed") is Outcome.FS_FAILED


def test_failure_stage_filesystem_present() -> None:
    assert FailureStage("filesystem") is FailureStage.FILESYSTEM


def test_materialization_report_filesystem_actions_defaults_to_empty() -> None:
    payload = {
        "schema_version": 3,
        "run_id": "1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01",
        "outcome": "success",
        "platform": "darwin",
        "started_at": "2026-05-19T00:00:00Z",
        "finished_at": "2026-05-19T00:00:01Z",
        "toolchain": {},
        "invocations": [],
        "materialized": [],
        "failures": [],
    }
    report = MaterializationReport.model_validate(payload)
    assert report.filesystem_actions == []
