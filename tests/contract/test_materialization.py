"""Contract round-trip tests for MaterializationReport."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel, ValidationError

from chaos_librarian.contract import MATERIALIZATION_SCHEMA_VERSION
from chaos_librarian.contract import materialization as materialization_contract
from chaos_librarian.contract import scenario as scenario_contract
from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceEvidence,
    ContentTrackKind,
)
from chaos_librarian.contract.materialization import (
    CorruptionAction,
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
from chaos_librarian.contract.profiles import CorruptionProbeOutcome
from chaos_librarian.contract.scenario import NetworkLagEffect, TimelineActionName


def _source_evidence() -> ContentSourceEvidence:
    return ContentSourceEvidence(
        asset_id="asset_main",
        track_kind=ContentTrackKind.VIDEO,
        track_index=None,
        source="color_bars",
        provider="builtin-lavfi",
        recipe_digest="sha256:" + "0" * 64,
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
        cache_key=None,
        content_hash=None,
        origin_uri=None,
        license=None,
    )


def _minimal_report(**overrides: object) -> MaterializationReport:
    defaults: dict[str, object] = {
        "schema_version": MATERIALIZATION_SCHEMA_VERSION,
        "run_id": uuid.uuid4(),
        "outcome": Outcome.SUCCESS,
        "platform": "darwin-arm64",
        "started_at": datetime(2026, 5, 18, 0, 0, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 5, 18, 0, 0, 1, tzinfo=UTC),
        "toolchain": ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
        "content_sources": [_source_evidence()],
    }
    defaults.update(overrides)
    return MaterializationReport.model_validate(defaults)


def _timeline_action(member_name: str) -> TimelineActionName:
    action = getattr(TimelineActionName, member_name, None)
    assert isinstance(action, TimelineActionName)
    return action


WRONG_ORACLE_HASH_ACTION = _timeline_action("WRONG_ORACLE_HASH")


def _oracle_hash_action_model() -> type[BaseModel]:
    model = getattr(materialization_contract, "OracleHashAction", None)
    assert isinstance(model, type)
    assert issubclass(model, BaseModel)
    return model


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
        Outcome.CORRUPTION_FAILED,
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


def test_materialization_schema_version_is_sixteen() -> None:
    assert MATERIALIZATION_SCHEMA_VERSION == 17


def test_materialized_asset_records_mp4_moov_placement() -> None:
    asset = MaterializedAsset(
        asset_id="asset_mp4",
        location_path="library/movie/main.mp4",
        content_hash="sha256:" + "0" * 64,
        size_bytes=100,
        duration_seconds=1.0,
        invocation_index=0,
        mp4_moov_placement=scenario_contract.Mp4MoovPlacement.MOOV_AT_START,
    )

    assert asset.model_dump(mode="json")["mp4_moov_placement"] == "moov_at_start"


def test_materialization_report_run_timing_defaults() -> None:
    report = _minimal_report()
    assert report.requested_duration_ns is None
    assert report.actual_duration_ns is None
    assert report.speed_multiplier is None
    assert report.overran_duration is False
    assert (
        report.execution_mode is materialization_contract.MaterializationExecutionMode.MATERIALIZE
    )


def test_materialization_report_accepts_run_timing() -> None:
    report = _minimal_report(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        requested_duration_ns=90_000_000_000,
        actual_duration_ns=90_123_456_789,
        speed_multiplier="10",
        overran_duration=True,
        execution_mode="run",
    )
    assert report.execution_mode is materialization_contract.MaterializationExecutionMode.RUN


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


def test_filesystem_action_touch_mtime_round_trip() -> None:
    action = FilesystemAction(
        event_id="mtime_001",
        action=_timeline_action("TOUCH_MTIME"),
        target_asset_id="asset_main",
        from_path="movies-hd/asset_main.mkv",
        to_path="movies-hd/asset_main.mkv",
        temp_path=None,
        content_hash="sha256:" + "0" * 64,
        mtime_before_ns=1_000_000_000,
        mtime_after_ns=3_000_000_000,
        duration_ns=10,
    )

    loaded = FilesystemAction.model_validate_json(action.model_dump_json())

    assert loaded == action
    assert loaded.content_hash == "sha256:" + "0" * 64
    assert loaded.mtime_after_ns == 3_000_000_000


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
        "schema_version": MATERIALIZATION_SCHEMA_VERSION,
        "run_id": "1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01",
        "outcome": "success",
        "platform": "darwin",
        "started_at": "2026-05-19T00:00:00Z",
        "finished_at": "2026-05-19T00:00:01Z",
        "toolchain": {},
        "content_sources": [
            {
                "asset_id": "asset_main",
                "track_kind": "video",
                "track_index": None,
                "source": "color_bars",
                "provider": "builtin-lavfi",
                "recipe_digest": "sha256:" + "0" * 64,
                "cache_disposition": "not_cacheable",
                "cache_key": None,
                "content_hash": None,
                "origin_uri": None,
                "license": None,
            }
        ],
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


def test_failure_stage_includes_corruption():
    assert FailureStage.CORRUPTION.value == "corruption"


def test_materialization_report_carries_media_actions():
    report = MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        run_id=uuid.uuid4(),
        outcome=Outcome.SUCCESS,
        platform="darwin",
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        toolchain=ToolchainInfo(),
        content_sources=[],
    )
    assert report.media_actions == []
    assert report.schema_version == MATERIALIZATION_SCHEMA_VERSION


def test_network_lag_action_round_trip() -> None:
    action = materialization_contract.NetworkLagAction(
        event_id="lag_start_001",
        commit_event_id="lag_commit_001",
        effect=NetworkLagEffect.DELAYED_RENAME,
        target_ref="asset_main",
        after_event_id="rename_001",
        logical_start_ns=10_000_000_000,
        logical_commit_ns=12_000_000_000,
        requested_duration_ns=2_000_000_000,
        actual_duration_ns=200_000_000,
        from_path="library/movies-hd/asset_main.mkv",
        to_path="movies-hd/renamed.mkv",
        provider="stdlib-local",
        enforced=True,
    )

    loaded = materialization_contract.NetworkLagAction.model_validate_json(action.model_dump_json())

    assert loaded == action
    assert loaded.effect.value == "delayed_rename"


def test_materialization_report_carries_network_lag_actions() -> None:
    report = _minimal_report(
        network_lag_actions=[
            {
                "event_id": "lag_start_001",
                "commit_event_id": "lag_commit_001",
                "effect": "held_handle",
                "target_ref": "asset_main",
                "after_event_id": "metadata_001",
                "logical_start_ns": 1,
                "logical_commit_ns": 2,
                "requested_duration_ns": 1,
                "actual_duration_ns": None,
                "from_path": "library/movies-hd/asset_main.mkv",
                "to_path": None,
                "provider": "stdlib-local",
                "enforced": False,
            }
        ]
    )

    assert len(report.network_lag_actions) == 1
    assert report.network_lag_actions[0].effect.value == "held_handle"


def test_materialization_report_carries_content_source_evidence() -> None:
    report = _minimal_report()

    assert report.content_sources[0].provider == "builtin-lavfi"


def test_materialization_content_source_carries_muxing_profile() -> None:
    evidence = ContentSourceEvidence(
        asset_id="asset_main",
        track_kind=ContentTrackKind.MUXING,
        source="short_clusters",
        provider="builtin-mkvmerge",
        recipe_digest="sha256:" + "1" * 64,
        matroska_muxing_profile=scenario_contract.MatroskaMuxingProfile.SHORT_CLUSTERS,
        container="mkv",
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
    )

    loaded = ContentSourceEvidence.model_validate(evidence.model_dump(mode="json"))

    assert loaded.track_kind is ContentTrackKind.MUXING
    assert loaded.matroska_muxing_profile is scenario_contract.MatroskaMuxingProfile.SHORT_CLUSTERS
    assert loaded.container == "mkv"


def test_corruption_probe_outcome_accepts_declared_values_only() -> None:
    assert CorruptionProbeOutcome("failed_expected") is CorruptionProbeOutcome.FAILED_EXPECTED
    assert CorruptionProbeOutcome("still_probeable") is CorruptionProbeOutcome.STILL_PROBEABLE

    with pytest.raises(ValueError, match="unexpected"):
        CorruptionProbeOutcome("unexpected")


def test_corruption_action_round_trips_hashes_and_probe_outcome() -> None:
    action = CorruptionAction(
        event_id="corrupt_header_001",
        action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
        target_asset_id="asset_main",
        input_path="movies-hd/asset_main.mkv",
        output_path="movies-hd/asset_main.mkv",
        input_version_id="version_0001",
        output_version_id="version_0002",
        input_content_hash="sha256:" + "0" * 64,
        output_content_hash="sha256:" + "1" * 64,
        corruptor="container_header_v1",
        input_size_bytes=8192,
        output_size_bytes=8192,
        byte_start=0,
        byte_count=64,
        seed_material="container_header_v1:42:corrupt_header_001:asset_main",
        probe_outcome=CorruptionProbeOutcome.FAILED_EXPECTED,
        probe_error_tail="Invalid data found",
        duration_ns=1_234_567,
    )

    loaded = CorruptionAction.model_validate_json(action.model_dump_json())

    assert loaded == action
    assert loaded.input_content_hash == "sha256:" + "0" * 64
    assert loaded.probe_outcome is CorruptionProbeOutcome.FAILED_EXPECTED


def test_truncate_file_corruption_action_round_trip() -> None:
    action = CorruptionAction(
        event_id="truncate_001",
        action=TimelineActionName.TRUNCATE_FILE,
        target_asset_id="asset_main",
        input_path="movies-hd/asset_main.mkv",
        output_path="movies-hd/asset_main.mkv",
        input_version_id="version_0001",
        output_version_id="version_0002",
        input_content_hash="sha256:" + "0" * 64,
        output_content_hash="sha256:" + "1" * 64,
        corruptor="truncate_file_v1",
        input_size_bytes=128,
        output_size_bytes=64,
        byte_start=64,
        byte_count=64,
        seed_material="truncate_file_v1:42:truncate_001:asset_main",
        probe_outcome=CorruptionProbeOutcome.FAILED_EXPECTED,
        duration_ns=10,
    )

    loaded = CorruptionAction.model_validate_json(action.model_dump_json())

    assert loaded == action
    assert loaded.input_size_bytes == 128
    assert loaded.output_size_bytes == 64


def test_packet_range_corruption_action_round_trip() -> None:
    action = CorruptionAction(
        event_id="packet_corrupt_001",
        action=TimelineActionName.CORRUPT_PACKET_RANGE,
        target_asset_id="asset_main",
        input_path="movies-hd/asset_main.mkv",
        output_path="movies-hd/asset_main.mkv",
        input_version_id="version_0001",
        output_version_id="version_0002",
        input_content_hash="sha256:" + "0" * 64,
        output_content_hash="sha256:" + "1" * 64,
        corruptor="packet_range_v1",
        input_size_bytes=8192,
        output_size_bytes=8192,
        stream="video",
        packet_start=0,
        packet_count=2,
        byte_start=4096,
        byte_count=2048,
        seed_material="packet_range_v1:42:packet_corrupt_001:asset_main",
        probe_outcome=CorruptionProbeOutcome.STILL_PROBEABLE,
        duration_ns=10,
    )

    loaded = CorruptionAction.model_validate_json(action.model_dump_json())

    assert loaded == action
    assert loaded.stream == "video"
    assert loaded.packet_count == 2


def test_oracle_hash_action_round_trip() -> None:
    action_model = _oracle_hash_action_model()
    action = action_model(
        event_id="wrong_hash_001",
        action=WRONG_ORACLE_HASH_ACTION,
        target_asset_id="asset_main",
        input_path="movies-hd/asset_main.mkv",
        output_path="movies-hd/asset_main.mkv",
        input_version_id="version_0001",
        output_version_id="version_0002",
        actual_content_hash="sha256:" + "1" * 64,
        reported_content_hash="sha256:" + "2" * 64,
        seed_material="wrong_oracle_hash_v1:42:wrong_hash_001:asset_main",
        duration_ns=10,
    )

    loaded = action_model.model_validate_json(action.model_dump_json())

    assert loaded == action


def test_materialization_report_carries_oracle_hash_actions() -> None:
    action_model = _oracle_hash_action_model()
    action = action_model(
        event_id="wrong_hash_001",
        action=WRONG_ORACLE_HASH_ACTION,
        target_asset_id="asset_main",
        input_path="movies-hd/asset_main.mkv",
        output_path="movies-hd/asset_main.mkv",
        input_version_id="version_0001",
        output_version_id="version_0002",
        actual_content_hash="sha256:" + "1" * 64,
        reported_content_hash="sha256:" + "2" * 64,
        seed_material="wrong_oracle_hash_v1:42:wrong_hash_001:asset_main",
        duration_ns=10,
    )

    report = _minimal_report(oracle_hash_actions=[action])

    assert report.oracle_hash_actions == [action]


def test_corruption_action_rejects_bad_input_content_hash() -> None:
    payload = {
        "event_id": "corrupt_header_001",
        "action": "corrupt_container_header",
        "target_asset_id": "asset_main",
        "input_path": "movies-hd/asset_main.mkv",
        "output_path": "movies-hd/asset_main.mkv",
        "input_version_id": "version_0001",
        "output_version_id": "version_0002",
        "input_content_hash": "sha256:not-a-hash",
        "output_content_hash": "sha256:" + "1" * 64,
        "corruptor": "container_header_v1",
        "input_size_bytes": 8192,
        "output_size_bytes": 8192,
        "byte_start": 0,
        "byte_count": 64,
        "seed_material": "container_header_v1:42:corrupt_header_001:asset_main",
        "probe_outcome": "failed_expected",
        "duration_ns": 1_234_567,
    }

    with pytest.raises(ValidationError):
        CorruptionAction.model_validate(payload)


def test_corruption_action_rejects_bad_output_content_hash() -> None:
    payload = {
        "event_id": "corrupt_header_001",
        "action": "corrupt_container_header",
        "target_asset_id": "asset_main",
        "input_path": "movies-hd/asset_main.mkv",
        "output_path": "movies-hd/asset_main.mkv",
        "input_version_id": "version_0001",
        "output_version_id": "version_0002",
        "input_content_hash": "sha256:" + "0" * 64,
        "output_content_hash": "sha256:not-a-hash",
        "corruptor": "container_header_v1",
        "input_size_bytes": 8192,
        "output_size_bytes": 8192,
        "byte_start": 0,
        "byte_count": 64,
        "seed_material": "container_header_v1:42:corrupt_header_001:asset_main",
        "probe_outcome": "failed_expected",
        "duration_ns": 1_234_567,
    }

    with pytest.raises(ValidationError):
        CorruptionAction.model_validate(payload)
