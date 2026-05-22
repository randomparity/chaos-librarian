"""Replay helpers for wall-clock run bundles."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from chaos_librarian.contract.manifest import Manifest, ManifestSidecar, ProbedMedia
from chaos_librarian.contract.materialization import (
    FilesystemAction,
    MaterializationExecutionMode,
    MaterializedAsset,
    MediaAction,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinelState
from chaos_librarian.contract.scenario import (
    Asset,
    CreateSidecarEvent,
    Scenario,
    SidecarKind,
    TimelineActionName,
)
from chaos_librarian.contract.validation import ValidationReport, ValidationSeverity
from chaos_librarian.engine import PlanArtifacts, ReplayIntegrityError, run_plan
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.resolution import resolve_timeline, step_boundaries
from chaos_librarian.materializer._context import MaterializeArtifacts, RunContext
from chaos_librarian.materializer.capabilities import (
    assert_capable_for_static_materialize,
    detect_capabilities,
)
from chaos_librarian.materializer.filesystem import _dispatch_one, _PhaseBContext
from chaos_librarian.materializer.finalize import build_sentinel
from chaos_librarian.materializer.manifest_build import (
    augment_manifest,
    augment_timeline_sidecars,
    augment_updated_sidecars,
    augment_versions,
)
from chaos_librarian.materializer.media import (
    _MEDIA_ACTIONS,
    _STDLIB_ACTIONS,
    _MediaContext,
    apply_media_action,
)
from chaos_librarian.materializer.preflight import iter_assets, preflight_asset, preflight_timeline
from chaos_librarian.materializer.reports import (
    build_metadata,
    build_replay_bundle,
    build_report,
    build_reports,
)
from chaos_librarian.materializer.synthesis import materialize_one_asset
from chaos_librarian.materializer.writer import finalize_materialize_run
from chaos_librarian.validation import RunInput, prepare_run_input_from_bytes, run_validation

__all__ = ["replay_run_bundle"]


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

    artifacts = run_plan(
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
    invocations, materialized = _synthesize_phase_a(
        scenario=scenario,
        out_dir=out_dir,
        artifacts=prefix_artifacts,
        caps=caps,
    )
    filesystem_actions, media_actions = _apply_prefix_phase_b(
        scenario=scenario,
        out_dir=out_dir,
        artifacts=prefix_artifacts,
        invocations=invocations,
    )
    finished_at = datetime.now(UTC)
    report = build_report(
        outcome=Outcome.SUCCESS,
        run_id=source_bundle.run_id,
        caps=caps,
        started_at=started_at,
        finished_at=finished_at,
        invocations=invocations,
        materialized=materialized,
        failures=[],
        filesystem_actions=filesystem_actions,
        media_actions=media_actions,
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay_bundle = build_replay_bundle(
        run_id=source_bundle.run_id,
        scenario_yaml_bytes=run_input.raw_bytes,
        plan_artifacts=prefix_artifacts,
        caps=caps,
        created_at=finished_at,
        execution_mode=ExecutionMode.RUN,
    ).model_copy(
        update={
            "applied_events": source_bundle.applied_events,
            "journal_digest": source_bundle.journal_digest,
        }
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


def _synthesize_phase_a(
    *,
    scenario: Scenario,
    out_dir: Path,
    artifacts: PlanArtifacts,
    caps,
) -> tuple[list[ToolInvocation], list[MaterializedAsset]]:
    invocations: list[ToolInvocation] = []
    materialized_assets: list[MaterializedAsset] = []
    primary_root_path = scenario.library.roots[0].path
    skip_by_asset = _timeline_sidecar_languages(scenario)
    for invocation_index, asset in enumerate(iter_assets(scenario)):
        invocation, materialized, probed, sidecar_hashes = materialize_one_asset(
            asset,
            artifacts.replay_bundle.resolved_seed,
            out_dir,
            caps,
            invocation_index,
            root_path=primary_root_path,
            skip_languages=skip_by_asset.get(asset.id, frozenset()),
        )
        invocations.append(invocation)
        materialized_assets.append(materialized)
        _stamp_phase_a_asset(
            artifacts.current_manifest,
            asset,
            materialized,
            probed,
            sidecar_hashes,
        )
    return invocations, materialized_assets


def _stamp_phase_a_asset(
    manifest: Manifest,
    asset: Asset,
    materialized: MaterializedAsset,
    probed: ProbedMedia,
    sidecar_hashes: dict[tuple[str, str], str],
) -> None:
    augment_manifest(manifest, asset, materialized, probed, sidecar_hashes)


def _apply_prefix_phase_b(
    *,
    scenario: Scenario,
    out_dir: Path,
    artifacts: PlanArtifacts,
    invocations: list[ToolInvocation],
) -> tuple[list[FilesystemAction], list[MediaAction]]:
    scenario_assets = {asset.id: asset for asset in iter_assets(scenario)}
    fs_ctx = _PhaseBContext(
        library_root=out_dir / "library",
        scenario_assets=scenario_assets,
        resolved_seed=artifacts.replay_bundle.resolved_seed,
    )
    media_ctx = _MediaContext(
        library_root=out_dir / "library",
        scenario_assets=scenario_assets,
        resolved_seed=artifacts.replay_bundle.resolved_seed,
        ffmpeg_version="unknown",
        ffprobe_version="unknown",
        invocations=invocations,
        sidecar_lookup=_sidecar_lookup_from(artifacts.current_manifest),
    )
    filesystem_actions: list[FilesystemAction] = []
    media_actions: list[MediaAction] = []
    for entry in artifacts.journal:
        action = TimelineActionName(entry.action)
        if action in _STDLIB_ACTIONS:
            fs_action = _dispatch_one(fs_ctx, entry)
            if fs_action is not None:
                filesystem_actions.append(fs_action)
        elif action in _MEDIA_ACTIONS:
            media_actions.append(apply_media_action(media_ctx, entry))
    augment_timeline_sidecars(artifacts.current_manifest, fs_ctx.phase_b_sidecar_hashes)
    augment_versions(artifacts.current_manifest, media_ctx.post_phase_b_versions)
    augment_updated_sidecars(artifacts.current_manifest, media_ctx.post_phase_b_sidecars)
    return filesystem_actions, media_actions


def _timeline_sidecar_languages(scenario: Scenario) -> dict[str, frozenset[str]]:
    per_asset: dict[str, set[str]] = {}
    for event in scenario.timeline:
        if not isinstance(event, CreateSidecarEvent):
            continue
        if event.kind is not SidecarKind.SUBTITLE:
            continue
        assert event.language is not None
        per_asset.setdefault(event.target, set()).add(event.language)
    return {asset_id: frozenset(langs) for asset_id, langs in per_asset.items()}


def _sidecar_lookup_from(manifest: Manifest) -> Callable[[str], ManifestSidecar | None]:
    by_id = {sidecar.id: sidecar for sidecar in manifest.sidecars}

    def lookup(sidecar_id: str) -> ManifestSidecar | None:
        return by_id.get(sidecar_id)

    return lookup
