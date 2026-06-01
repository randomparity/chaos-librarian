"""Materialize orchestrator — the 8-step pipeline.

Steps 1-5 (validation, preflight, plan execution, sentinel write) run
entirely in memory before any ffmpeg invocation. Steps 6-8 (per-asset
synthesis, manifest augmentation, finalize) delegate to ``synthesis``,
``manifest_build``, and ``finalize`` respectively. The materializer
raises the spec's error hierarchy on any failure; the CLI handler
converts them to exit codes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from chaos_librarian.contract.materialization import Outcome
from chaos_librarian.contract.run_sentinel import RunSentinelState
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.materializer.content.synthesis import (
    PhaseAInputs,
    PhaseAResult,
    materialize_assets_phase_a,
)
from chaos_librarian.materializer.errors import (
    CorruptionActionError,
    FilesystemActionError,
    MediaActionError,
    ProbeParseError,
    ToolFailedError,
)
from chaos_librarian.materializer.persistence._context import (
    MaterializeArtifacts,
    ReportActions,
    RunContext,
)
from chaos_librarian.materializer.persistence.finalize import (
    build_sentinel,
    finalize_failure,
    finalize_failure_phase_b,
    finalize_success,
)
from chaos_librarian.materializer.persistence.writer import begin_materialize_run
from chaos_librarian.materializer.phase_b.dispatch import (
    PhaseBState,
    PhaseBStateInputs,
    augment_phase_b_outputs,
    dispatch_phase_b_entry,
    make_phase_b_state,
    phase_b_failure_outcome,
)
from chaos_librarian.materializer.preparation import prepare_materializer_run

__all__ = ["MaterializeArtifacts", "RunContext", "materialize_scenario"]


def materialize_scenario(scenario_path: Path, out_dir: Path) -> MaterializeArtifacts:
    """Run the 8-step pipeline. Raises on any failure (caught by the CLI).

    Raises:
        ScenarioLoadError: ``scenario_path`` cannot be read or parsed.
        ScenarioValidationError: scenario fails semantic validation.
        TimelineUnsupportedError: a timeline event names an action outside
            current materialize support.
        UnsupportedMaterializationError: scenario declares a codec,
            container, or subtitle mode outside the Sprint 5 matrix.
        CapabilityGateError: ffmpeg / ffprobe / mkvtoolnix missing or
            below the minimum version, or libx265 missing for HEVC video.
        ContainmentViolationError: a path escapes ``<out_dir>/library/``.
        ToolFailedError: ffmpeg or mkvtoolnix exited non-zero during
            synthesis.
        ProbeParseError: ffprobe output is malformed or missing required
            fields.
        FilesystemActionError: a phase-B stdlib helper raised.
        MediaActionError: a phase-B media handler (ffmpeg-backed or
            sidecar regeneration) raised.
    """
    started_at = datetime.now(UTC)
    prepared = prepare_materializer_run(
        scenario_path,
        validation_failure_message="scenario failed semantic validation; refusing to materialize",
        validation_payload_exclude_none=True,
        check_hevc_video=True,
    )
    scenario = prepared.scenario
    ctx = RunContext(
        run_input=prepared.run_input,
        out_dir=out_dir,
        run_id=prepared.run_id,
        started_at=started_at,
        caps=prepared.caps,
        plan_artifacts=prepared.plan_artifacts,
    )
    begin_materialize_run(ctx.out_dir, build_sentinel(ctx, RunSentinelState.IN_PROGRESS))
    return _run_synthesis(ctx, scenario)


def _run_synthesis(ctx: RunContext, scenario: Scenario) -> MaterializeArtifacts:
    """Steps 7-8: per-asset synthesis loop, unified phase-B walk, finalize/cleanup."""
    phase_a = PhaseAResult()
    phase_b_state: PhaseBState | None = None
    try:
        materialize_assets_phase_a(
            PhaseAInputs(
                scenario=scenario,
                out_dir=ctx.out_dir,
                artifacts=ctx.plan_artifacts,
                caps=ctx.caps,
                phase_a_accumulator=phase_a,
                stamp_manifest=True,
            )
        )
        phase_b_state = make_phase_b_state(
            PhaseBStateInputs(
                library_root=ctx.out_dir / "library",
                scenario=scenario,
                resolved_seed=ctx.plan_artifacts.replay_bundle.resolved_seed,
                ffmpeg_version=ctx.caps.ffmpeg.version or "unknown",
                ffprobe_version=ctx.caps.ffprobe.version or "unknown",
                invocations=phase_a.invocations,
                manifest=ctx.plan_artifacts.current_manifest,
                initial_manifest=ctx.plan_artifacts.initial_manifest,
            )
        )
        for entry in ctx.plan_artifacts.journal:
            dispatch_phase_b_entry(phase_b_state, entry)
        augment_phase_b_outputs(ctx.plan_artifacts.current_manifest, phase_b_state)
    except (ToolFailedError, ProbeParseError) as exc:
        if isinstance(exc, ToolFailedError):
            phase_a.invocations.append(exc.invocation)
        phase_a.content_sources.extend(exc.content_sources)
        finalize_failure(
            ctx,
            exc,
            Outcome.TOOL_FAILED,
            phase_a.invocations,
            phase_a.materialized_assets,
            content_sources=phase_a.content_sources,
        )
        raise
    except (FilesystemActionError, MediaActionError, CorruptionActionError) as exc:
        assert phase_b_state is not None
        finalize_failure_phase_b(
            ctx,
            exc,
            phase_b_failure_outcome(exc),
            phase_a.invocations,
            phase_a.materialized_assets,
            actions=_report_actions_from_state(phase_b_state),
            content_sources=phase_a.content_sources,
        )
        raise
    assert phase_b_state is not None
    return finalize_success(
        ctx,
        phase_a.invocations,
        phase_a.materialized_assets,
        actions=_report_actions_from_state(phase_b_state),
        content_sources=phase_a.content_sources,
    )


def _report_actions_from_state(state: PhaseBState) -> ReportActions:
    return ReportActions(
        filesystem=state.filesystem_actions,
        media=state.media_actions,
        corruption=state.corruption_actions,
        oracle_hash=state.oracle_hash_actions,
    )
