"""Materialize orchestrator — the 8-step pipeline.

Steps 1-5 (validation, preflight, plan execution, sentinel write) run
entirely in memory before any ffmpeg invocation. Steps 6-8 (per-asset
synthesis, manifest augmentation, finalize) delegate to ``synthesis``,
``manifest_build``, and ``finalize`` respectively. The materializer
raises the spec's error hierarchy on any failure; the CLI handler
converts them to exit codes.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.materialization import Outcome
from chaos_librarian.contract.run_sentinel import RunSentinelState
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.engine import run_materializer_plan
from chaos_librarian.materializer.capability_gates import (
    assert_capable_for_audio_recipes,
    assert_capable_for_hdr_video,
    assert_capable_for_resolution_switch_video,
)
from chaos_librarian.materializer.errors import (
    CapabilityGateError,
    CorruptionActionError,
    FilesystemActionError,
    MediaActionError,
    ProbeParseError,
    ScenarioValidationError,
    ToolFailedError,
)
from chaos_librarian.materializer.persistence._context import MaterializeArtifacts, RunContext
from chaos_librarian.materializer.persistence.finalize import (
    build_sentinel,
    finalize_failure,
    finalize_failure_phase_b,
    finalize_success,
)
from chaos_librarian.materializer.persistence.writer import begin_materialize_run
from chaos_librarian.materializer.phase_b import (
    PhaseBState,
    augment_phase_b_outputs,
    dispatch_phase_b_entry,
    make_phase_b_state,
    phase_b_failure_outcome,
)
from chaos_librarian.materializer.preflight import (
    iter_assets,
    preflight_asset,
    preflight_timeline,
)
from chaos_librarian.materializer.synthesis import PhaseAResult, materialize_assets_phase_a
from chaos_librarian.materializer.tooling.capabilities import (
    assert_capable_for_static_materialize,
    detect_capabilities,
)
from chaos_librarian.media_matrix import HEVC_VIDEO_CODECS
from chaos_librarian.topology import iter_asset_contexts
from chaos_librarian.validation import run_validation
from chaos_librarian.validation.input import prepare_run_input

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
    run_input = prepare_run_input(scenario_path)
    # Run semantic validation BEFORE the timeline scope check so
    # containment/lifecycle errors surface as ScenarioValidationError
    # (exit 3) instead of being shadowed by TimelineUnsupportedError when an
    # invalid scenario happens to also declare timeline events.
    validation_report = run_validation(run_input)
    if not validation_report.ok:
        raise ScenarioValidationError(
            "scenario failed semantic validation; refusing to materialize",
            payload={
                "validation_report": validation_report.model_dump(mode="json", exclude_none=True),
            },
            validation_report=validation_report,
        )
    # Validation succeeded → ``RunInput.scenario`` cache is primed by the
    # shape pass; access the cached parse instead of re-validating.
    scenario = run_input.scenario
    # Pre-flight the timeline before any other gate. Matrix-rejection
    # contract: TimelineUnsupportedError must surface before run-dir
    # allocation, so callers see exit 5 without a stale half-allocated
    # directory on disk.
    preflight_timeline(scenario)
    caps = detect_capabilities()
    assert_capable_for_static_materialize(caps)
    assert_capable_for_audio_recipes(scenario, caps)
    assert_capable_for_resolution_switch_video(scenario, caps)
    _assert_capable_for_hevc_video(scenario, caps)
    assert_capable_for_hdr_video(scenario, caps)
    run_id = uuid.uuid4()
    # materialize executes the whole timeline; pass ``steps_limit=None`` so
    # ``run_materializer_plan`` applies every resolved event. Sprint 5 capped this at 0
    # because phase B did not yet exist and the materializer reused the
    # plan-only manifest as-is.
    plan_artifacts = run_materializer_plan(
        run_input=run_input,
        validation_report=validation_report,
        run_id_override=run_id,
        steps_limit=None,
    )
    for context in iter_asset_contexts(scenario):
        asset = context.asset
        preflight_asset(
            parent_kind=context.parent_kind,
            video=asset.video,
            audios=asset.audio,
            subtitles=asset.subtitles,
            container=asset.container,
        )
    ctx = RunContext(
        run_input=run_input,
        out_dir=out_dir,
        run_id=run_id,
        started_at=started_at,
        caps=caps,
        plan_artifacts=plan_artifacts,
    )
    begin_materialize_run(ctx.out_dir, build_sentinel(ctx, RunSentinelState.IN_PROGRESS))
    return _run_synthesis(ctx, scenario)


def _assert_capable_for_hevc_video(scenario: Scenario, caps: Capabilities) -> None:
    """Raise before run-dir allocation when scenario needs HEVC and libx265 is absent."""
    for asset in iter_assets(scenario):
        if asset.video is None or asset.video.codec not in HEVC_VIDEO_CODECS:
            continue
        if caps.ready_for.materialize_hevc_video:
            return
        raise CapabilityGateError(
            "HEVC/H.265 video materialization requires FFmpeg with the libx265 encoder",
            asset_id=asset.id,
            field="ready_for.materialize_hevc_video",
            payload={
                "capability": "ready_for.materialize_hevc_video",
                "required_encoder": "libx265",
                "video_codec": asset.video.codec,
            },
        )


def _run_synthesis(ctx: RunContext, scenario: Scenario) -> MaterializeArtifacts:
    """Steps 7-8: per-asset synthesis loop, unified phase-B walk, finalize/cleanup."""
    phase_a = PhaseAResult()
    phase_b_state: PhaseBState | None = None
    try:
        materialize_assets_phase_a(
            scenario=scenario,
            out_dir=ctx.out_dir,
            artifacts=ctx.plan_artifacts,
            caps=ctx.caps,
            result=phase_a,
            stamp_manifest=True,
        )
        phase_b_state = make_phase_b_state(
            library_root=ctx.out_dir / "library",
            scenario=scenario,
            resolved_seed=ctx.plan_artifacts.replay_bundle.resolved_seed,
            ffmpeg_version=ctx.caps.ffmpeg.version or "unknown",
            ffprobe_version=ctx.caps.ffprobe.version or "unknown",
            invocations=phase_a.invocations,
            manifest=ctx.plan_artifacts.current_manifest,
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
            filesystem_actions=phase_b_state.filesystem_actions,
            media_actions=phase_b_state.media_actions,
            corruption_actions=phase_b_state.corruption_actions,
            oracle_hash_actions=phase_b_state.oracle_hash_actions,
            content_sources=phase_a.content_sources,
        )
        raise
    assert phase_b_state is not None
    return finalize_success(
        ctx,
        phase_a.invocations,
        phase_a.materialized_assets,
        filesystem_actions=phase_b_state.filesystem_actions,
        media_actions=phase_b_state.media_actions,
        corruption_actions=phase_b_state.corruption_actions,
        oracle_hash_actions=phase_b_state.oracle_hash_actions,
        content_sources=phase_a.content_sources,
    )
