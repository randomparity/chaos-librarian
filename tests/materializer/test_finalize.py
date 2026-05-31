from __future__ import annotations

import inspect
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceCapabilities,
    ContentSourceEvidence,
    ContentTrackKind,
)
from chaos_librarian.contract.materialization import (
    FailureStage,
    FilesystemAction,
    MaterializationExecutionMode,
    MaterializedAsset,
    NetworkFsChaosAction,
    NetworkFsChaosCondition,
    NetworkLagAction,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode
from chaos_librarian.contract.run_sentinel import RunSentinelState
from chaos_librarian.contract.scenario import NetworkLagEffect, TimelineActionName
from chaos_librarian.engine import run_plan
from chaos_librarian.materializer.errors import FilesystemActionError
from chaos_librarian.materializer.persistence import finalize as finalize_mod
from chaos_librarian.materializer.persistence import reports as reports_mod
from chaos_librarian.materializer.persistence._context import RunContext
from chaos_librarian.materializer.persistence.writer import MaterializeMetadata, MaterializeReports
from chaos_librarian.validation import prepare_run_input, run_validation

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
RUN_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")


def _source_evidence() -> ContentSourceEvidence:
    return ContentSourceEvidence(
        asset_id="asset_main",
        track_kind=ContentTrackKind.VIDEO,
        source="color_bars",
        provider="builtin-lavfi",
        recipe_digest="sha256:" + "0" * 64,
        cache_disposition=CacheDisposition.NOT_CACHEABLE,
    )


def test_report_and_finalize_builders_require_explicit_content_sources() -> None:
    for func in (
        reports_mod.build_report,
        reports_mod.build_replay_bundle,
        finalize_mod.finalize_success,
        finalize_mod.finalize_failure,
        finalize_mod.finalize_failure_phase_b,
    ):
        parameter = inspect.signature(func).parameters["content_sources"]
        assert parameter.default is inspect.Signature.empty
    for func in (finalize_mod.finalize_success, finalize_mod.finalize_failure_phase_b):
        for name in (
            "filesystem_actions",
            "media_actions",
            "corruption_actions",
            "oracle_hash_actions",
        ):
            assert inspect.signature(func).parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


def _caps() -> Capabilities:
    return Capabilities(
        schema_version=7,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=True,
            materialize_hevc_video=True,
            materialize_hdr_video=True,
            materialize_resolution_switch_video=True,
            materialize_audio_recipes=True,
            materialize_matroska_muxing_profiles=True,
            materialize_webm_video=True,
        ),
    )


def _run_context(tmp_path: Path) -> RunContext:
    run_input = prepare_run_input(FIXTURE_DIR / "static-library.yaml")
    validation_report = run_validation(run_input)
    assert validation_report.ok
    return RunContext(
        run_input=run_input,
        out_dir=tmp_path / "run",
        run_id=RUN_ID,
        started_at=datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC),
        caps=_caps(),
        plan_artifacts=run_plan(run_input=run_input, validation_report=validation_report),
    )


def test_finalize_success_writes_complete_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: list[tuple[Path, MaterializeMetadata, MaterializeReports]] = []

    def fake_finalize(
        out_dir: Path,
        metadata: MaterializeMetadata,
        reports: MaterializeReports,
    ) -> None:
        captured.append((out_dir, metadata, reports))

    monkeypatch.setattr(finalize_mod, "finalize_materialize_run", fake_finalize)
    ctx = _run_context(tmp_path)
    invocation = ToolInvocation(
        tool="ffmpeg",
        version="7.1.1",
        command=["ffmpeg", "-i", "input", "output"],
        exit_code=0,
        duration_ns=10,
    )
    materialized = [
        MaterializedAsset(
            asset_id="asset_main",
            location_path="library/movies-hd/asset_main.mkv",
            content_hash="sha256:" + "a" * 64,
            size_bytes=10,
            duration_seconds=1.0,
            invocation_index=0,
        )
    ]
    content_sources = [_source_evidence()]

    artifacts = finalize_mod.finalize_success(
        ctx,
        [invocation],
        materialized,
        filesystem_actions=[],
        media_actions=[],
        corruption_actions=[],
        oracle_hash_actions=[],
        content_sources=content_sources,
    )

    assert len(captured) == 1
    out_dir, metadata, reports = captured[0]
    assert out_dir == ctx.out_dir
    assert metadata.sentinel.state is RunSentinelState.COMPLETE
    assert metadata.materialization_report.outcome is Outcome.SUCCESS
    assert metadata.materialization_report.invocations == [invocation]
    assert metadata.materialization_report.materialized == materialized
    assert metadata.materialization_report.content_sources == content_sources
    assert metadata.replay_bundle.content_sources == content_sources
    assert artifacts.replay_bundle.content_sources == content_sources
    assert artifacts.materialization_report == metadata.materialization_report
    assert artifacts.current_manifest == ctx.plan_artifacts.current_manifest
    assert reports.assets


def test_finalize_run_replay_success_writes_run_mode_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: list[tuple[Path, MaterializeMetadata, MaterializeReports]] = []

    def fake_finalize(
        out_dir: Path,
        metadata: MaterializeMetadata,
        reports: MaterializeReports,
    ) -> None:
        captured.append((out_dir, metadata, reports))

    helper = getattr(finalize_mod, "finalize_run_replay_success", None)
    assert helper is not None
    monkeypatch.setattr(finalize_mod, "finalize_materialize_run", fake_finalize)
    ctx = _run_context(tmp_path)
    source_bundle = reports_mod.build_replay_bundle(
        run_id=ctx.run_id,
        scenario_yaml_bytes=ctx.run_input.raw_bytes,
        plan_artifacts=ctx.plan_artifacts,
        caps=ctx.caps,
        created_at=ctx.started_at,
        content_sources=[],
        execution_mode=ExecutionMode.RUN,
    ).model_copy(
        update={
            "applied_events": 2,
            "journal_digest": "f" * 64,
        }
    )
    network_lag_action = NetworkLagAction(
        event_id="lag-start",
        commit_event_id="lag-commit",
        effect=NetworkLagEffect.DELAYED_VISIBILITY,
        target_ref="asset_main",
        after_event_id="copy-1",
        logical_start_ns=10,
        logical_commit_ns=20,
        requested_duration_ns=10,
        provider="stdlib-local",
        enforced=True,
    )
    chaos_action = NetworkFsChaosAction(
        event_id="readonly-1",
        action=TimelineActionName.TOGGLE_READONLY,
        target_ref="asset_main",
        condition=NetworkFsChaosCondition.EACCES,
        enforced=True,
    )

    artifacts = helper(
        ctx,
        source_bundle,
        [],
        [],
        filesystem_actions=[],
        media_actions=[],
        corruption_actions=[],
        oracle_hash_actions=[],
        network_lag_actions=[network_lag_action],
        network_fs_chaos_actions=[chaos_action],
        content_sources=[],
    )

    assert len(captured) == 1
    _, metadata, reports = captured[0]
    report = metadata.materialization_report
    assert report.execution_mode is MaterializationExecutionMode.RUN
    assert report.network_lag_actions == [network_lag_action]
    assert report.network_fs_chaos_actions == [chaos_action]
    assert metadata.replay_bundle.execution_mode is ExecutionMode.RUN
    assert metadata.replay_bundle.applied_events == source_bundle.applied_events
    assert metadata.replay_bundle.journal_digest == source_bundle.journal_digest
    assert metadata.sentinel.state is RunSentinelState.COMPLETE
    assert artifacts.materialization_report == report
    assert artifacts.replay_bundle == metadata.replay_bundle
    assert reports.assets


def test_finalize_failure_phase_b_records_failure_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: list[tuple[Path, MaterializeMetadata]] = []

    def fake_cleanup(out_dir: Path, metadata: MaterializeMetadata) -> None:
        captured.append((out_dir, metadata))

    monkeypatch.setattr(finalize_mod, "cleanup_failed_phase_b_run", fake_cleanup)
    ctx = _run_context(tmp_path)
    action = FilesystemAction(
        event_id="move-1",
        action=TimelineActionName.MOVE_ASSET,
        target_asset_id="asset_main",
        from_path="library/old.mkv",
        to_path="library/new.mkv",
        duration_ns=12,
    )
    exc = FilesystemActionError(
        "move failed",
        event_id="move-1",
        action=TimelineActionName.MOVE_ASSET,
        cause=OSError(2, "missing"),
        asset_id="asset_main",
    )

    finalize_mod.finalize_failure_phase_b(
        ctx,
        exc,
        Outcome.FS_FAILED,
        [],
        [],
        filesystem_actions=[action],
        media_actions=[],
        corruption_actions=[],
        oracle_hash_actions=[],
        content_sources=[],
    )

    assert len(captured) == 1
    out_dir, metadata = captured[0]
    report = metadata.materialization_report
    assert out_dir == ctx.out_dir
    assert metadata.sentinel.state is RunSentinelState.COMPLETE
    assert report.outcome is Outcome.FS_FAILED
    assert report.filesystem_actions == [action]
    assert report.failures[0].stage is FailureStage.FILESYSTEM
    assert report.failures[0].asset_id == "asset_main"
    assert report.failures[0].stderr_tail == "[Errno 2] missing"
