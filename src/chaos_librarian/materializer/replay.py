"""Replay helpers for wall-clock run bundles."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from chaos_librarian.contract.content_sources import ContentSourceEvidence
from chaos_librarian.contract.manifest import Manifest, ProbedMedia
from chaos_librarian.contract.materialization import (
    MaterializationExecutionMode,
    MaterializedAsset,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinelState
from chaos_librarian.contract.scenario import (
    Asset,
    Scenario,
)
from chaos_librarian.contract.validation import ValidationReport, ValidationSeverity
from chaos_librarian.engine import PlanArtifacts, ReplayIntegrityError, run_materializer_plan
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.resolution import resolve_timeline, step_boundaries
from chaos_librarian.materializer.errors import (
    CorruptionActionError,
    FilesystemActionError,
    MediaActionError,
)
from chaos_librarian.materializer.manifest_build import (
    augment_manifest,
)
from chaos_librarian.materializer.persistence._context import MaterializeArtifacts, RunContext
from chaos_librarian.materializer.persistence.finalize import build_sentinel
from chaos_librarian.materializer.persistence.reports import (
    build_metadata,
    build_replay_bundle,
    build_report,
    build_reports,
)
from chaos_librarian.materializer.persistence.writer import (
    cleanup_failed_phase_b_run,
    finalize_materialize_run,
)
from chaos_librarian.materializer.phase_b import (
    PhaseBState,
    augment_phase_b_outputs,
    dispatch_phase_b_entry,
    make_phase_b_state,
    phase_b_failure_outcome,
    phase_b_failure_record,
)
from chaos_librarian.materializer.phase_b.sidecar_languages import timeline_sidecar_languages
from chaos_librarian.materializer.preflight import iter_assets, preflight_asset, preflight_timeline
from chaos_librarian.materializer.synthesis import materialize_one_asset
from chaos_librarian.materializer.tooling.capabilities import (
    assert_capable_for_static_materialize,
    detect_capabilities,
)
from chaos_librarian.validation import RunInput, prepare_run_input_from_bytes, run_validation

__all__ = ["replay_run_bundle"]


@dataclass(frozen=True, slots=True)
class _PhaseAResult:
    invocations: list[ToolInvocation]
    materialized_assets: list[MaterializedAsset]
    content_sources: list[ContentSourceEvidence]


def replay_run_bundle(bundle: MaterializeReplayBundle, out_dir: Path) -> MaterializeArtifacts:
    """Replay a verified wall-clock run bundle as fast as possible."""
    if bundle.execution_mode is not ExecutionMode.RUN:
        raise ReplayIntegrityError("only execution_mode='run' bundles are supported")
    run_input, validation_report, prefix_artifacts = _verified_run_prefix(bundle)
    return _materialize_verified_run_prefix(
        run_input=run_input,
        validation_report=validation_report,
        prefix_artifacts=prefix_artifacts,
        source_bundle=bundle,
        out_dir=out_dir,
    )


def _verified_run_prefix(
    bundle: MaterializeReplayBundle,
) -> tuple[RunInput, ValidationReport, PlanArtifacts]:
    yaml_bytes = bundle.scenario.encode("utf-8")
    run_input = prepare_run_input_from_bytes(
        raw_bytes=yaml_bytes,
        source_label=f"run-replay:{bundle.run_id}",
    )
    report = run_validation(run_input)
    if not report.ok:
        errors = [
            issue.code for issue in report.issues if issue.severity == ValidationSeverity.ERROR
        ]
        raise ReplayIntegrityError(f"run replay scenario re-validation failed: {errors}")

    resolved_timeline = resolve_timeline(run_input.scenario)
    valid_boundaries = {0, *step_boundaries(resolved_timeline)}
    if bundle.applied_events not in valid_boundaries:
        raise ReplayIntegrityError(f"applied_events {bundle.applied_events} is not replayable")

    artifacts = run_materializer_plan(
        run_input=run_input,
        validation_report=report,
        resolved_seed_override=bundle.resolved_seed,
        run_id_override=bundle.run_id,
        applied_events_override=bundle.applied_events,
    )
    digest_entries = [
        entry.model_copy(update={"wall_clock_time": None}) for entry in artifacts.journal
    ]
    digest = hashlib.sha256(serialize_journal_bytes(digest_entries)).hexdigest()
    if digest != bundle.journal_digest:
        raise ReplayIntegrityError(
            f"journal_digest mismatch: recorded {bundle.journal_digest}, recomputed {digest}"
        )
    return run_input, report, artifacts


def _materialize_verified_run_prefix(
    *,
    run_input: RunInput,
    validation_report: ValidationReport,
    prefix_artifacts: PlanArtifacts,
    source_bundle: MaterializeReplayBundle,
    out_dir: Path,
) -> MaterializeArtifacts:
    scenario = run_input.scenario
    preflight_timeline(scenario)
    caps = detect_capabilities()
    assert_capable_for_static_materialize(caps)
    for asset in iter_assets(scenario):
        preflight_asset(asset.video, asset.audio, asset.subtitles, asset.container)
    out_dir.mkdir(parents=True)
    (out_dir / "library").mkdir()
    started_at = datetime.now(UTC)
    phase_a = _synthesize_phase_a(
        scenario=scenario,
        out_dir=out_dir,
        artifacts=prefix_artifacts,
        caps=caps,
    )
    state = _make_run_replay_phase_b_state(
        scenario=scenario,
        out_dir=out_dir,
        artifacts=prefix_artifacts,
        invocations=phase_a.invocations,
    )
    try:
        _apply_prefix_phase_b(state, prefix_artifacts)
    except (FilesystemActionError, MediaActionError, CorruptionActionError) as exc:
        _finalize_run_replay_phase_b_failure(
            run_input=run_input,
            prefix_artifacts=prefix_artifacts,
            source_bundle=source_bundle,
            out_dir=out_dir,
            caps=caps,
            started_at=started_at,
            phase_a=phase_a,
            state=state,
            exc=exc,
        )
        raise
    finished_at = datetime.now(UTC)
    report = build_report(
        outcome=Outcome.SUCCESS,
        run_id=source_bundle.run_id,
        caps=caps,
        started_at=started_at,
        finished_at=finished_at,
        invocations=phase_a.invocations,
        materialized=phase_a.materialized_assets,
        failures=[],
        filesystem_actions=state.filesystem_actions,
        media_actions=state.media_actions,
        corruption_actions=state.corruption_actions,
        content_sources=phase_a.content_sources,
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay_bundle = _build_run_replay_bundle(
        run_input=run_input,
        prefix_artifacts=prefix_artifacts,
        source_bundle=source_bundle,
        caps=caps,
        created_at=finished_at,
        content_sources=phase_a.content_sources,
    )
    ctx = RunContext(
        run_input=run_input,
        out_dir=out_dir,
        run_id=source_bundle.run_id,
        started_at=started_at,
        caps=caps,
        plan_artifacts=prefix_artifacts,
    )
    finalize_materialize_run(
        out_dir,
        build_metadata(
            plan_artifacts=prefix_artifacts,
            scenario_yaml_bytes=run_input.raw_bytes,
            materialization_report=report,
            replay_bundle=replay_bundle,
            sentinel=build_sentinel(ctx, RunSentinelState.COMPLETE),
        ),
        build_reports(prefix_artifacts),
    )
    return MaterializeArtifacts(
        current_manifest=prefix_artifacts.current_manifest,
        materialization_report=report,
        replay_bundle=replay_bundle,
    )


def _build_run_replay_bundle(
    *,
    run_input: RunInput,
    prefix_artifacts: PlanArtifacts,
    source_bundle: MaterializeReplayBundle,
    caps,
    created_at: datetime,
    content_sources: list[ContentSourceEvidence],
) -> MaterializeReplayBundle:
    return build_replay_bundle(
        run_id=source_bundle.run_id,
        scenario_yaml_bytes=run_input.raw_bytes,
        plan_artifacts=prefix_artifacts,
        caps=caps,
        created_at=created_at,
        content_sources=content_sources,
        execution_mode=ExecutionMode.RUN,
    ).model_copy(
        update={
            "applied_events": source_bundle.applied_events,
            "journal_digest": source_bundle.journal_digest,
        }
    )


def _finalize_run_replay_phase_b_failure(
    *,
    run_input: RunInput,
    prefix_artifacts: PlanArtifacts,
    source_bundle: MaterializeReplayBundle,
    out_dir: Path,
    caps,
    started_at: datetime,
    phase_a: _PhaseAResult,
    state: PhaseBState,
    exc: FilesystemActionError | MediaActionError | CorruptionActionError,
) -> None:
    augment_phase_b_outputs(prefix_artifacts.current_manifest, state)
    finished_at = datetime.now(UTC)
    report = build_report(
        outcome=phase_b_failure_outcome(exc),
        run_id=source_bundle.run_id,
        caps=caps,
        started_at=started_at,
        finished_at=finished_at,
        invocations=phase_a.invocations,
        materialized=phase_a.materialized_assets,
        failures=[phase_b_failure_record(exc)],
        filesystem_actions=state.filesystem_actions,
        media_actions=state.media_actions,
        corruption_actions=state.corruption_actions,
        content_sources=phase_a.content_sources,
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay_bundle = _build_run_replay_bundle(
        run_input=run_input,
        prefix_artifacts=prefix_artifacts,
        source_bundle=source_bundle,
        caps=caps,
        created_at=finished_at,
        content_sources=phase_a.content_sources,
    )
    ctx = RunContext(
        run_input=run_input,
        out_dir=out_dir,
        run_id=source_bundle.run_id,
        started_at=started_at,
        caps=caps,
        plan_artifacts=prefix_artifacts,
    )
    cleanup_failed_phase_b_run(
        out_dir,
        build_metadata(
            plan_artifacts=prefix_artifacts,
            scenario_yaml_bytes=run_input.raw_bytes,
            materialization_report=report,
            replay_bundle=replay_bundle,
            sentinel=build_sentinel(ctx, RunSentinelState.COMPLETE),
        ),
    )


def _synthesize_phase_a(
    *,
    scenario: Scenario,
    out_dir: Path,
    artifacts: PlanArtifacts,
    caps,
) -> _PhaseAResult:
    invocations: list[ToolInvocation] = []
    materialized_assets: list[MaterializedAsset] = []
    content_sources: list[ContentSourceEvidence] = []
    primary_root_path = scenario.library.roots[0].path
    skip_by_asset = timeline_sidecar_languages(scenario)
    for invocation_index, asset in enumerate(iter_assets(scenario)):
        result = materialize_one_asset(
            asset,
            artifacts.replay_bundle.resolved_seed,
            out_dir,
            caps,
            invocation_index,
            root_path=primary_root_path,
            skip_languages=skip_by_asset.get(asset.id, frozenset()),
        )
        invocations.append(result.invocation)
        materialized_assets.append(result.materialized_asset)
        content_sources.extend(result.content_sources)
        _stamp_phase_a_asset(
            artifacts.current_manifest,
            asset,
            result.materialized_asset,
            result.probed,
            result.sidecar_hashes,
        )
    return _PhaseAResult(
        invocations=invocations,
        materialized_assets=materialized_assets,
        content_sources=content_sources,
    )


def _stamp_phase_a_asset(
    manifest: Manifest,
    asset: Asset,
    materialized: MaterializedAsset,
    probed: ProbedMedia,
    sidecar_hashes: dict[tuple[str, str], str],
) -> None:
    augment_manifest(manifest, asset, materialized, probed, sidecar_hashes)


def _make_run_replay_phase_b_state(
    *,
    scenario: Scenario,
    out_dir: Path,
    artifacts: PlanArtifacts,
    invocations: list[ToolInvocation],
) -> PhaseBState:
    return make_phase_b_state(
        library_root=out_dir / "library",
        scenario=scenario,
        resolved_seed=artifacts.replay_bundle.resolved_seed,
        ffmpeg_version="unknown",
        ffprobe_version="unknown",
        invocations=invocations,
        manifest=artifacts.current_manifest,
    )


def _apply_prefix_phase_b(
    state: PhaseBState,
    artifacts: PlanArtifacts,
) -> None:
    for entry in artifacts.journal:
        dispatch_phase_b_entry(state, entry)
    augment_phase_b_outputs(artifacts.current_manifest, state)
