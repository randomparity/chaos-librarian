"""Success and failure finalize paths: sentinel + writer dispatch."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

from chaos_librarian import __version__ as _chaos_librarian_version
from chaos_librarian.contract import RUN_SENTINEL_SCHEMA_VERSION
from chaos_librarian.contract.materialization import (
    CorruptionAction,
    FailureStage,
    FilesystemAction,
    MaterializationFailure,
    MaterializedAsset,
    MediaAction,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.run_sentinel import RunSentinel, RunSentinelState
from chaos_librarian.materializer.errors import (
    MaterializationError,
    ProbeParseError,
)
from chaos_librarian.materializer.persistence._context import MaterializeArtifacts, RunContext
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
from chaos_librarian.materializer.phase_b import PhaseBError, phase_b_failure_record

__all__ = [
    "build_sentinel",
    "finalize_failure",
    "finalize_failure_phase_b",
    "finalize_success",
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
    filesystem_actions: list[FilesystemAction],
    media_actions: list[MediaAction],
    corruption_actions: list[CorruptionAction],
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
        filesystem_actions=filesystem_actions,
        media_actions=media_actions,
        corruption_actions=corruption_actions,
    )
    replay_bundle = build_replay_bundle(
        run_id=ctx.run_id,
        scenario_yaml_bytes=ctx.run_input.raw_bytes,
        plan_artifacts=ctx.plan_artifacts,
        caps=ctx.caps,
        created_at=finished_at,
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
    filesystem_actions: list[FilesystemAction] | None = None,
    media_actions: list[MediaAction] | None = None,
    corruption_actions: list[CorruptionAction] | None = None,
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
        filesystem_actions=filesystem_actions or [],
        media_actions=media_actions or [],
        corruption_actions=corruption_actions or [],
    )
    replay_bundle = build_replay_bundle(
        run_id=ctx.run_id,
        scenario_yaml_bytes=ctx.run_input.raw_bytes,
        plan_artifacts=ctx.plan_artifacts,
        caps=ctx.caps,
        created_at=finished_at,
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
    filesystem_actions: list[FilesystemAction],
    media_actions: list[MediaAction],
    corruption_actions: list[CorruptionAction],
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
        filesystem_actions=filesystem_actions,
        media_actions=media_actions,
        corruption_actions=corruption_actions,
    )
    replay_bundle = build_replay_bundle(
        run_id=ctx.run_id,
        scenario_yaml_bytes=ctx.run_input.raw_bytes,
        plan_artifacts=ctx.plan_artifacts,
        caps=ctx.caps,
        created_at=finished_at,
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
