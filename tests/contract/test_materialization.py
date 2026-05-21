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
    MediaAction,
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


def test_materialization_schema_version_is_four() -> None:
    assert MATERIALIZATION_SCHEMA_VERSION == 4


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


def test_materialization_failure_round_trips_with_none_optional_fields() -> None:
    """WHY: filesystem-stage failures populate stage + stderr_tail but leave
    asset_id, exit_code, and invocation_index None. ``canonical_json`` is
    serialized with ``exclude_none=True``; the resulting JSON must re-validate
    without callers having to backfill defaults. Issue #36."""
    failure = MaterializationFailure(
        asset_id=None,
        stage=FailureStage.FILESYSTEM,
        exit_code=None,
        stderr_tail="rmtree failed: [Errno 13] Permission denied",
        invocation_index=None,
    )
    blob = failure.model_dump_json(exclude_none=True)
    parsed = MaterializationFailure.model_validate_json(blob)
    assert parsed == failure


def test_materialization_report_filesystem_actions_defaults_to_empty() -> None:
    payload = {
        "schema_version": 4,
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


def test_media_action_round_trip():
    action = MediaAction(
        event_id="ev_rv_001",
        action=TimelineActionName.REENCODE_VIDEO,
        target_asset_id="asset_main",
        input_path="library/movies/asset_main.mkv",
        output_path="library/movies/asset_main.mkv",
        input_version_id="version_0001",
        output_version_id="version_0002",
        output_sidecar_id=None,
        input_content_hash="sha256:" + "0" * 64,
        output_content_hash="sha256:" + "1" * 64,
        tool_invocation_index=2,
        duration_ns=1_234_567,
    )
    assert action.event_id == "ev_rv_001"
    assert action.action == TimelineActionName.REENCODE_VIDEO


def test_media_action_extract_subtitle_no_input_version():
    action = MediaAction(
        event_id="ev_xs_001",
        action=TimelineActionName.EXTRACT_SUBTITLE,
        target_asset_id="asset_main",
        input_path="library/asset_main.mkv",
        output_path="library/asset_main.fra.srt",
        input_version_id=None,
        output_version_id=None,
        output_sidecar_id="sidecar_0002",
        input_content_hash=None,
        output_content_hash="sha256:" + "2" * 64,
        tool_invocation_index=4,
        duration_ns=100,
    )
    assert action.output_sidecar_id == "sidecar_0002"
    assert action.input_version_id is None
    assert action.output_version_id is None


def test_outcome_includes_media_failed():
    assert Outcome.MEDIA_FAILED.value == "media_failed"


def test_failure_stage_includes_media():
    assert FailureStage.MEDIA.value == "media"


def test_materialization_report_carries_media_actions():
    report = MaterializationReport(
        schema_version=4,
        run_id=uuid.uuid4(),
        outcome=Outcome.SUCCESS,
        platform="darwin",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        toolchain=ToolchainInfo(),
    )
    assert report.media_actions == []
    assert report.schema_version == 4
