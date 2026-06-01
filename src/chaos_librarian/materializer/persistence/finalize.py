"""Success and failure finalize paths: sentinel + writer dispatch."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Final

from chaos_librarian import __version__ as _chaos_librarian_version
from chaos_librarian.contract import RUN_SENTINEL_SCHEMA_VERSION
from chaos_librarian.contract.content_sources import ContentSourceEvidence
from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.materialization import (
    FailureStage,
    MaterializationExecutionMode,
    MaterializationFailure,
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
    ProbeParseError,
)
from chaos_librarian.materializer.persistence._context import (
    MaterializeArtifacts,
    ReportActions,
    RunContext,
)
from chaos_librarian.materializer.persistence.reports import (
    build_metadata,
    build_replay_bundle,
    build_report,
    build_reports,
)
from chaos_librarian.materializer.persistence.writer import (
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
    "finalize_run_replay_phase_b_failure",
    "finalize_run_replay_success",
    "finalize_success",
    "finalize_wall_clock_phase_b_failure",
    "finalize_wall_clock_success",
]


CREATED_BY: Final = f"chaos-librarian/{_chaos_librarian_version}"


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
    finished_at = datetime.now(UTC)
    materialization_report = build_report(
        outcome=Outcome.SUCCESS,
        run_id=ctx.run_id,
        caps=ctx.caps,
        started_at=ctx.started_at,
        finished_at=finished_at,
        invocations=invocations,
        materialized=materialized,
        failures=[],
        actions=actions,
        content_sources=content_sources,
    )
    replay_bundle = build_replay_bundle(
        run_id=ctx.run_id,
        scenario_yaml_bytes=ctx.run_input.raw_bytes,
        plan_artifacts=ctx.plan_artifacts,
        caps=ctx.caps,
        created_at=finished_at,
        content_sources=content_sources,
    )
    finalize_materialize_run(
        ctx.out_dir,
        build_metadata(
            plan_artifacts=ctx.plan_artifacts,
            scenario_yaml_bytes=ctx.run_input.raw_bytes,
            materialization_report=materialization_report,
            replay_bundle=replay_bundle,
            sentinel=build_sentinel(ctx, RunSentinelState.COMPLETE),
        ),
        build_reports(ctx.plan_artifacts),
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
    finished_at = datetime.now(UTC)
    invocation = getattr(exc, "invocation", None)
    exit_code = invocation.exit_code if invocation is not None else None
    failure = MaterializationFailure(
        asset_id=getattr(exc, "asset_id", None),
        stage=FailureStage.FFPROBE if isinstance(exc, ProbeParseError) else FailureStage.FFMPEG,
        exit_code=exit_code,
        stderr_tail=str(exc.payload.get("stderr_tail", "")),
        invocation_index=(len(invocations) - 1) if invocations else None,
    )
    report = build_report(
        outcome=outcome,
        run_id=ctx.run_id,
        caps=ctx.caps,
        started_at=ctx.started_at,
        finished_at=finished_at,
        invocations=invocations,
        materialized=materialized,
        failures=[failure],
        actions=actions,
        content_sources=content_sources,
    )
    replay_bundle = build_replay_bundle(
        run_id=ctx.run_id,
        scenario_yaml_bytes=ctx.run_input.raw_bytes,
        plan_artifacts=ctx.plan_artifacts,
        caps=ctx.caps,
        created_at=finished_at,
        content_sources=content_sources,
    )
    cleanup_failed_run(
        ctx.out_dir,
        build_metadata(
            plan_artifacts=ctx.plan_artifacts,
            scenario_yaml_bytes=ctx.run_input.raw_bytes,
            materialization_report=report,
            replay_bundle=replay_bundle,
            sentinel=build_sentinel(ctx, RunSentinelState.COMPLETE),
        ),
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
    finished_at = datetime.now(UTC)
    failure = phase_b_failure_record(exc)
    report = build_report(
        outcome=outcome,
        run_id=ctx.run_id,
        caps=ctx.caps,
        started_at=ctx.started_at,
        finished_at=finished_at,
        invocations=invocations,
        materialized=materialized,
        failures=[failure],
        actions=actions,
        content_sources=content_sources,
    )
    replay_bundle = build_replay_bundle(
        run_id=ctx.run_id,
        scenario_yaml_bytes=ctx.run_input.raw_bytes,
        plan_artifacts=ctx.plan_artifacts,
        caps=ctx.caps,
        created_at=finished_at,
        content_sources=content_sources,
    )
    cleanup_failed_phase_b_run(
        ctx.out_dir,
        build_metadata(
            plan_artifacts=ctx.plan_artifacts,
            scenario_yaml_bytes=ctx.run_input.raw_bytes,
            materialization_report=report,
            replay_bundle=replay_bundle,
            sentinel=build_sentinel(ctx, RunSentinelState.COMPLETE),
        ),
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
    finished_at = datetime.now(UTC)
    report = build_report(
        outcome=Outcome.SUCCESS,
        run_id=ctx.run_id,
        caps=ctx.caps,
        started_at=ctx.started_at,
        finished_at=finished_at,
        invocations=invocations,
        materialized=materialized,
        failures=[],
        actions=actions,
        content_sources=content_sources,
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay_bundle = _build_run_replay_bundle(
        ctx,
        source_bundle,
        finished_at,
        content_sources,
    )
    finalize_materialize_run(
        ctx.out_dir,
        build_metadata(
            plan_artifacts=ctx.plan_artifacts,
            scenario_yaml_bytes=ctx.run_input.raw_bytes,
            materialization_report=report,
            replay_bundle=replay_bundle,
            sentinel=build_sentinel(ctx, RunSentinelState.COMPLETE),
        ),
        build_reports(ctx.plan_artifacts),
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
    finished_at = datetime.now(UTC)
    report = build_report(
        outcome=phase_b_failure_outcome(exc),
        run_id=ctx.run_id,
        caps=ctx.caps,
        started_at=ctx.started_at,
        finished_at=finished_at,
        invocations=invocations,
        materialized=materialized,
        failures=[phase_b_failure_record(exc)],
        actions=actions,
        content_sources=content_sources,
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay_bundle = _build_run_replay_bundle(
        ctx,
        source_bundle,
        finished_at,
        content_sources,
    )
    cleanup_failed_phase_b_run(
        ctx.out_dir,
        build_metadata(
            plan_artifacts=ctx.plan_artifacts,
            scenario_yaml_bytes=ctx.run_input.raw_bytes,
            materialization_report=report,
            replay_bundle=replay_bundle,
            sentinel=build_sentinel(ctx, RunSentinelState.COMPLETE),
        ),
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
    finished_at = datetime.now(UTC)
    report = build_report(
        outcome=Outcome.SUCCESS,
        run_id=ctx.run_id,
        caps=ctx.caps,
        started_at=ctx.started_at,
        finished_at=finished_at,
        invocations=invocations,
        materialized=materialized,
        failures=[],
        actions=actions,
        requested_duration_ns=requested_duration_ns,
        actual_duration_ns=actual_duration_ns,
        speed_multiplier=speed_multiplier,
        overran_duration=overran_duration,
        content_sources=content_sources,
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay_bundle = _build_wall_clock_replay_bundle(
        ctx,
        final_artifacts,
        executed_journal,
        finished_at,
        content_sources,
    )
    finalize_materialize_run(
        ctx.out_dir,
        build_metadata(
            plan_artifacts=final_artifacts,
            scenario_yaml_bytes=ctx.run_input.raw_bytes,
            materialization_report=report,
            replay_bundle=replay_bundle,
            sentinel=build_sentinel(ctx, RunSentinelState.COMPLETE),
        ),
        build_reports(final_artifacts),
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
    finished_at = datetime.now(UTC)
    report = build_report(
        outcome=phase_b_failure_outcome(exc),
        run_id=ctx.run_id,
        caps=ctx.caps,
        started_at=ctx.started_at,
        finished_at=finished_at,
        invocations=invocations,
        materialized=materialized,
        failures=[phase_b_failure_record(exc)],
        actions=actions,
        requested_duration_ns=requested_duration_ns,
        actual_duration_ns=actual_duration_ns,
        speed_multiplier=speed_multiplier,
        overran_duration=overran_duration,
        content_sources=content_sources,
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay_bundle = _build_wall_clock_replay_bundle(
        ctx,
        final_artifacts,
        executed_journal,
        finished_at,
        content_sources,
    )
    cleanup_failed_phase_b_run(
        ctx.out_dir,
        build_metadata(
            plan_artifacts=final_artifacts,
            scenario_yaml_bytes=ctx.run_input.raw_bytes,
            materialization_report=report,
            replay_bundle=replay_bundle,
            sentinel=build_sentinel(ctx, RunSentinelState.COMPLETE),
        ),
    )


def _build_run_replay_bundle(
    ctx: RunContext,
    source_bundle: MaterializeReplayBundle,
    created_at: datetime,
    content_sources: list[ContentSourceEvidence],
) -> MaterializeReplayBundle:
    replay_bundle = build_replay_bundle(
        run_id=ctx.run_id,
        scenario_yaml_bytes=ctx.run_input.raw_bytes,
        plan_artifacts=ctx.plan_artifacts,
        caps=ctx.caps,
        created_at=created_at,
        content_sources=content_sources,
        execution_mode=ExecutionMode.RUN,
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
    created_at: datetime,
    content_sources: list[ContentSourceEvidence],
) -> MaterializeReplayBundle:
    digest_entries = [
        entry.model_copy(update={"wall_clock_time": None}) for entry in executed_journal
    ]
    journal_digest = hashlib.sha256(serialize_journal_bytes(digest_entries)).hexdigest()
    replay_bundle = build_replay_bundle(
        run_id=ctx.run_id,
        scenario_yaml_bytes=ctx.run_input.raw_bytes,
        plan_artifacts=final_artifacts,
        caps=ctx.caps,
        created_at=created_at,
        content_sources=content_sources,
        execution_mode=ExecutionMode.RUN,
    )
    return replay_bundle.model_copy(
        update={
            "applied_events": len(executed_journal),
            "journal_digest": journal_digest,
        }
    )
