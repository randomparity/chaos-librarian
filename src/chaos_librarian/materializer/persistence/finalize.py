"""Success and failure finalize paths: sentinel + writer dispatch."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from chaos_librarian import __version__ as _chaos_librarian_version
from chaos_librarian.contract import RUN_SENTINEL_SCHEMA_VERSION
from chaos_librarian.contract.content_sources import ContentSourceEvidence
from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.materialization import (
    FailureStage,
    MaterializationExecutionMode,
    MaterializationFailure,
    MaterializationReport,
    MaterializedAsset,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinel, RunSentinelState
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.plan import PlanArtifacts
from chaos_librarian.materializer.errors import (
    MaterializationError,
    MaterializationWriteError,
    ProbeParseError,
    ToolFailedError,
)
from chaos_librarian.materializer.persistence._context import (
    MaterializeArtifacts,
    ReportActions,
    RunContext,
)
from chaos_librarian.materializer.persistence.reports import (
    MaterializationReportRequest,
    ReplayBundleAssemblyRequest,
    ReportInputs,
    build_metadata,
    build_replay_bundle,
    build_report,
    build_reports,
)
from chaos_librarian.materializer.persistence.writer import (
    MaterializeMetadata,
    MaterializeReports,
    cleanup_failed_phase_b_run,
    cleanup_failed_run,
    finalize_materialize_run,
)
from chaos_librarian.materializer.phase_b.dispatch import (
    PhaseBError,
    phase_b_failure_outcome,
    phase_b_failure_record,
)

__all__ = [
    "build_sentinel",
    "finalize_failure",
    "finalize_failure_phase_b",
    "finalize_run_replay_phase_a_failure",
    "finalize_run_replay_phase_b_failure",
    "finalize_run_replay_success",
    "finalize_success",
    "finalize_wall_clock_phase_b_failure",
    "finalize_wall_clock_success",
]


CREATED_BY: Final = f"chaos-librarian/{_chaos_librarian_version}"
type _FinalizeWriter = Callable[
    [Path, MaterializeMetadata, MaterializeReports | None],
    None,
]


def build_sentinel(ctx: RunContext, state: RunSentinelState) -> RunSentinel:
    """Construct a RunSentinel from the per-run invariants in ``ctx``.

    The fields shared by every sentinel (``run_id``, ``schema_version``,
    ``created_by``, ``created_at``) live on the context; ``state`` is the
    only per-call variable.
    """
    return RunSentinel(
        run_id=ctx.run_id,
        schema_version=RUN_SENTINEL_SCHEMA_VERSION,
        created_by=CREATED_BY,
        created_at=ctx.started_at,
        state=state,
    )


def finalize_success(
    ctx: RunContext,
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
    *,
    actions: ReportActions,
    content_sources: list[ContentSourceEvidence],
) -> MaterializeArtifacts:
    """Step 8 (success path) — atomic metadata write, sentinel flips to complete."""
    report_inputs = _base_report_inputs(
        invocations,
        materialized,
        actions=actions,
        content_sources=content_sources,
    )
    materialization_report = _build_materialization_report(
        ctx,
        report_inputs,
        outcome=Outcome.SUCCESS,
        failures=[],
    )
    replay_bundle = _build_materialize_replay_bundle(
        ctx,
        report_inputs,
    )
    _finalize_outputs(
        ctx,
        plan_artifacts=ctx.plan_artifacts,
        materialization_report=materialization_report,
        replay_bundle=replay_bundle,
        writer=_write_success_outputs,
        writer_operation="finalize_materialize_run",
        include_reports=True,
    )
    return MaterializeArtifacts(
        current_manifest=ctx.plan_artifacts.current_manifest,
        materialization_report=materialization_report,
        replay_bundle=replay_bundle,
    )


def finalize_failure(
    ctx: RunContext,
    exc: MaterializationError,
    outcome: Outcome,
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
    *,
    content_sources: list[ContentSourceEvidence],
    actions: ReportActions | None = None,
) -> None:
    """Assemble every metadata file ``cleanup_failed_run`` requires.

    The failed run-dir must remain readable by ``inspect`` and removable
    by ``clean``. Both commands hard-require ``replay.json``; ``inspect``
    additionally hard-requires ``manifest.current.json``. The un-augmented
    plan-only manifest from ``ctx.plan_artifacts`` is correct here —
    synthesis aborted, so no version has ``content_hash``/``probed``.
    """
    report_inputs = _base_report_inputs(
        invocations,
        materialized,
        actions=actions,
        content_sources=content_sources,
    )
    invocation = getattr(exc, "invocation", None)
    exit_code = invocation.exit_code if invocation is not None else None
    failure = MaterializationFailure(
        asset_id=getattr(exc, "asset_id", None),
        stage=FailureStage.FFPROBE if isinstance(exc, ProbeParseError) else FailureStage.FFMPEG,
        exit_code=exit_code,
        stderr_tail=str(exc.payload.get("stderr_tail", "")),
        invocation_index=(len(report_inputs.invocations) - 1)
        if report_inputs.invocations
        else None,
    )
    report = _build_materialization_report(
        ctx,
        report_inputs,
        outcome=outcome,
        failures=[failure],
    )
    replay_bundle = _build_materialize_replay_bundle(
        ctx,
        report_inputs,
    )
    _finalize_outputs(
        ctx,
        plan_artifacts=ctx.plan_artifacts,
        materialization_report=report,
        replay_bundle=replay_bundle,
        writer=_write_failure_outputs,
        writer_operation="cleanup_failed_run",
        include_reports=False,
    )


def finalize_failure_phase_b(
    ctx: RunContext,
    exc: PhaseBError,
    outcome: Outcome,
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
    *,
    actions: ReportActions,
    content_sources: list[ContentSourceEvidence],
) -> None:
    """Caught phase-B failure path: phase-B outcome set by caller; library/ wiped.

    Shared by filesystem, media, and intentional-corruption handlers. The
    fields on ``MaterializationFailure`` are derived from the exception
    subclass plus the caller-selected outcome. Action records captured before
    the crash are recorded so the report shows the audit trail up to the
    failing event.
    """
    report_inputs = _base_report_inputs(
        invocations,
        materialized,
        actions=actions,
        content_sources=content_sources,
    )
    failure = phase_b_failure_record(exc)
    report = _build_materialization_report(
        ctx,
        report_inputs,
        outcome=outcome,
        failures=[failure],
    )
    replay_bundle = _build_materialize_replay_bundle(
        ctx,
        report_inputs,
    )
    _finalize_outputs(
        ctx,
        plan_artifacts=ctx.plan_artifacts,
        materialization_report=report,
        replay_bundle=replay_bundle,
        writer=_write_phase_b_failure_outputs,
        writer_operation="cleanup_failed_phase_b_run",
        include_reports=False,
    )


def finalize_run_replay_success(
    ctx: RunContext,
    source_bundle: MaterializeReplayBundle,
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
    *,
    actions: ReportActions,
    content_sources: list[ContentSourceEvidence],
) -> MaterializeArtifacts:
    """Run-replay success path: write run-mode metadata via the shared seam."""
    report_inputs = _base_report_inputs(
        invocations,
        materialized,
        actions=actions,
        content_sources=content_sources,
    )
    report = _build_materialization_report(
        ctx,
        report_inputs,
        outcome=Outcome.SUCCESS,
        failures=[],
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay_bundle = _build_run_replay_bundle(
        ctx,
        source_bundle,
        report_inputs,
    )
    _finalize_outputs(
        ctx,
        plan_artifacts=ctx.plan_artifacts,
        materialization_report=report,
        replay_bundle=replay_bundle,
        writer=_write_success_outputs,
        writer_operation="finalize_materialize_run",
        include_reports=True,
    )
    return MaterializeArtifacts(
        current_manifest=ctx.plan_artifacts.current_manifest,
        materialization_report=report,
        replay_bundle=replay_bundle,
    )


def finalize_run_replay_phase_b_failure(
    ctx: RunContext,
    source_bundle: MaterializeReplayBundle,
    exc: PhaseBError,
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
    *,
    actions: ReportActions,
    content_sources: list[ContentSourceEvidence],
) -> None:
    """Run-replay phase-B failure path: preserve replay metadata before cleanup."""
    report_inputs = _base_report_inputs(
        invocations,
        materialized,
        actions=actions,
        content_sources=content_sources,
    )
    report = _build_materialization_report(
        ctx,
        report_inputs,
        outcome=phase_b_failure_outcome(exc),
        failures=[phase_b_failure_record(exc)],
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay_bundle = _build_run_replay_bundle(
        ctx,
        source_bundle,
        report_inputs,
    )
    _finalize_outputs(
        ctx,
        plan_artifacts=ctx.plan_artifacts,
        materialization_report=report,
        replay_bundle=replay_bundle,
        writer=_write_phase_b_failure_outputs,
        writer_operation="cleanup_failed_phase_b_run",
        include_reports=False,
    )


def finalize_run_replay_phase_a_failure(
    ctx: RunContext,
    source_bundle: MaterializeReplayBundle,
    exc: ToolFailedError | ProbeParseError,
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
    *,
    content_sources: list[ContentSourceEvidence],
) -> None:
    """Run-replay phase-A failure path: preserve run-mode metadata before cleanup."""
    report_inputs = _base_report_inputs(
        invocations,
        materialized,
        actions=None,
        content_sources=content_sources,
    )
    invocation = getattr(exc, "invocation", None)
    failure = MaterializationFailure(
        asset_id=getattr(exc, "asset_id", None),
        stage=FailureStage.FFPROBE if isinstance(exc, ProbeParseError) else FailureStage.FFMPEG,
        exit_code=invocation.exit_code if invocation is not None else None,
        stderr_tail=str(exc.payload.get("stderr_tail", "")),
        invocation_index=(len(report_inputs.invocations) - 1)
        if report_inputs.invocations
        else None,
    )
    report = _build_materialization_report(
        ctx,
        report_inputs,
        outcome=Outcome.TOOL_FAILED,
        failures=[failure],
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay_bundle = _build_run_replay_bundle(ctx, source_bundle, report_inputs)
    _finalize_outputs(
        ctx,
        plan_artifacts=ctx.plan_artifacts,
        materialization_report=report,
        replay_bundle=replay_bundle,
        writer=_write_failure_outputs,
        writer_operation="cleanup_failed_run_replay_phase_a",
        include_reports=False,
    )


def finalize_wall_clock_success(
    ctx: RunContext,
    final_artifacts: PlanArtifacts,
    *,
    executed_journal: list[JournalEntry],
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
    actions: ReportActions,
    requested_duration_ns: int,
    actual_duration_ns: int,
    speed_multiplier: str,
    overran_duration: bool,
    content_sources: list[ContentSourceEvidence],
) -> MaterializeArtifacts:
    """Wall-clock success path: write run-mode metadata via the shared seam."""
    report_inputs = _base_report_inputs(
        invocations,
        materialized,
        actions=actions,
        content_sources=content_sources,
    )
    report = _build_materialization_report(
        ctx,
        report_inputs,
        outcome=Outcome.SUCCESS,
        failures=[],
        requested_duration_ns=requested_duration_ns,
        actual_duration_ns=actual_duration_ns,
        speed_multiplier=speed_multiplier,
        overran_duration=overran_duration,
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay_bundle = _build_wall_clock_replay_bundle(
        ctx,
        final_artifacts,
        executed_journal,
        report_inputs,
    )
    _finalize_outputs(
        ctx,
        plan_artifacts=final_artifacts,
        materialization_report=report,
        replay_bundle=replay_bundle,
        writer=_write_success_outputs,
        writer_operation="finalize_materialize_run",
        include_reports=True,
    )
    return MaterializeArtifacts(
        current_manifest=final_artifacts.current_manifest,
        materialization_report=report,
        replay_bundle=replay_bundle,
    )


def finalize_wall_clock_phase_b_failure(
    ctx: RunContext,
    final_artifacts: PlanArtifacts,
    exc: PhaseBError,
    *,
    executed_journal: list[JournalEntry],
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
    actions: ReportActions,
    requested_duration_ns: int,
    actual_duration_ns: int,
    speed_multiplier: str,
    overran_duration: bool,
    content_sources: list[ContentSourceEvidence],
) -> None:
    """Wall-clock phase-B failure path: preserve run-mode metadata before cleanup."""
    report_inputs = _base_report_inputs(
        invocations,
        materialized,
        actions=actions,
        content_sources=content_sources,
    )
    report = _build_materialization_report(
        ctx,
        report_inputs,
        outcome=phase_b_failure_outcome(exc),
        failures=[phase_b_failure_record(exc)],
        requested_duration_ns=requested_duration_ns,
        actual_duration_ns=actual_duration_ns,
        speed_multiplier=speed_multiplier,
        overran_duration=overran_duration,
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay_bundle = _build_wall_clock_replay_bundle(
        ctx,
        final_artifacts,
        executed_journal,
        report_inputs,
    )
    _finalize_outputs(
        ctx,
        plan_artifacts=final_artifacts,
        materialization_report=report,
        replay_bundle=replay_bundle,
        writer=_write_phase_b_failure_outputs,
        writer_operation="cleanup_failed_phase_b_run",
        include_reports=False,
    )


def _base_report_inputs(
    invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset],
    *,
    actions: ReportActions | None,
    content_sources: list[ContentSourceEvidence],
) -> ReportInputs:
    return ReportInputs(
        finished_at=datetime.now(UTC),
        invocations=invocations,
        materialized=materialized,
        actions=actions,
        content_sources=content_sources,
    )


def _build_materialization_report(
    ctx: RunContext,
    report_inputs: ReportInputs,
    *,
    outcome: Outcome,
    failures: list[MaterializationFailure],
    requested_duration_ns: int | None = None,
    actual_duration_ns: int | None = None,
    speed_multiplier: str | None = None,
    overran_duration: bool = False,
    execution_mode: MaterializationExecutionMode = MaterializationExecutionMode.MATERIALIZE,
) -> MaterializationReport:
    return build_report(
        MaterializationReportRequest(
            run_context=ctx,
            report_inputs=report_inputs,
            outcome=outcome,
            failures=failures,
            requested_duration_ns=requested_duration_ns,
            actual_duration_ns=actual_duration_ns,
            speed_multiplier=speed_multiplier,
            overran_duration=overran_duration,
            execution_mode=execution_mode,
        )
    )


def _build_materialize_replay_bundle(
    ctx: RunContext,
    report_inputs: ReportInputs,
) -> MaterializeReplayBundle:
    return build_replay_bundle(
        ReplayBundleAssemblyRequest(
            run_context=ctx,
            plan_artifacts=ctx.plan_artifacts,
            created_at=report_inputs.finished_at,
            content_sources=report_inputs.content_sources,
        )
    )


def _build_run_replay_bundle(
    ctx: RunContext,
    source_bundle: MaterializeReplayBundle,
    report_inputs: ReportInputs,
) -> MaterializeReplayBundle:
    replay_bundle = build_replay_bundle(
        ReplayBundleAssemblyRequest(
            run_context=ctx,
            plan_artifacts=ctx.plan_artifacts,
            created_at=report_inputs.finished_at,
            content_sources=report_inputs.content_sources,
            execution_mode=ExecutionMode.RUN,
        )
    )
    return replay_bundle.model_copy(
        update={
            "applied_events": source_bundle.applied_events,
            "journal_digest": source_bundle.journal_digest,
        }
    )


def _build_wall_clock_replay_bundle(
    ctx: RunContext,
    final_artifacts: PlanArtifacts,
    executed_journal: list[JournalEntry],
    report_inputs: ReportInputs,
) -> MaterializeReplayBundle:
    digest_entries = [
        entry.model_copy(update={"wall_clock_time": None}) for entry in executed_journal
    ]
    journal_digest = hashlib.sha256(serialize_journal_bytes(digest_entries)).hexdigest()
    replay_bundle = build_replay_bundle(
        ReplayBundleAssemblyRequest(
            run_context=ctx,
            plan_artifacts=final_artifacts,
            created_at=report_inputs.finished_at,
            content_sources=report_inputs.content_sources,
            execution_mode=ExecutionMode.RUN,
        )
    )
    return replay_bundle.model_copy(
        update={
            "applied_events": len(executed_journal),
            "journal_digest": journal_digest,
        }
    )


def _finalize_outputs(
    ctx: RunContext,
    *,
    plan_artifacts: PlanArtifacts,
    materialization_report: MaterializationReport,
    replay_bundle: MaterializeReplayBundle,
    writer: _FinalizeWriter,
    writer_operation: str,
    include_reports: bool,
) -> None:
    metadata = build_metadata(
        plan_artifacts=plan_artifacts,
        scenario_yaml_bytes=ctx.run_input.raw_bytes,
        materialization_report=materialization_report,
        replay_bundle=replay_bundle,
        sentinel=build_sentinel(ctx, RunSentinelState.COMPLETE),
    )
    reports = build_reports(plan_artifacts) if include_reports else None
    try:
        writer(ctx.out_dir, metadata, reports)
    except OSError as write_exc:
        raise _write_error(writer_operation, ctx.out_dir, write_exc) from write_exc


def _write_success_outputs(
    out_dir: Path,
    metadata: MaterializeMetadata,
    reports: MaterializeReports | None,
) -> None:
    if reports is None:
        raise ValueError("finalize_materialize_run requires reports")
    finalize_materialize_run(out_dir, metadata, reports)


def _write_failure_outputs(
    out_dir: Path,
    metadata: MaterializeMetadata,
    _reports: MaterializeReports | None,
) -> None:
    cleanup_failed_run(out_dir, metadata)


def _write_phase_b_failure_outputs(
    out_dir: Path,
    metadata: MaterializeMetadata,
    _reports: MaterializeReports | None,
) -> None:
    cleanup_failed_phase_b_run(out_dir, metadata)


def _write_error(operation: str, path: Path, cause: OSError) -> MaterializationWriteError:
    return MaterializationWriteError(operation=operation, path=path, cause=cause)
