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

from chaos_librarian.contract.materialization import (
    FilesystemAction,
    MaterializedAsset,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.run_sentinel import RunSentinelState
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.engine import run_plan
from chaos_librarian.materializer._context import MaterializeArtifacts, RunContext
from chaos_librarian.materializer.capabilities import (
    assert_capable_for_static_materialize,
    detect_capabilities,
)
from chaos_librarian.materializer.errors import (
    FilesystemActionError,
    ProbeParseError,
    ScenarioValidationError,
    ToolFailedError,
)
from chaos_librarian.materializer.filesystem import apply_phase_b
from chaos_librarian.materializer.finalize import (
    build_sentinel,
    finalize_failure,
    finalize_failure_filesystem,
    finalize_success,
)
from chaos_librarian.materializer.manifest_build import (
    augment_manifest,
    augment_timeline_sidecars,
)
from chaos_librarian.materializer.preflight import (
    iter_assets,
    preflight_asset,
    preflight_timeline,
)
from chaos_librarian.materializer.synthesis import materialize_one_asset
from chaos_librarian.materializer.writer import begin_materialize_run
from chaos_librarian.validation import run_validation
from chaos_librarian.validation.input import prepare_run_input

__all__ = ["MaterializeArtifacts", "RunContext", "materialize_scenario"]


def materialize_scenario(scenario_path: Path, out_dir: Path) -> MaterializeArtifacts:
    """Run the 8-step pipeline. Raises on any failure (caught by the CLI).

    Raises:
        ScenarioLoadError: ``scenario_path`` cannot be read or parsed.
        ScenarioValidationError: scenario fails semantic validation.
        TimelineUnsupportedError: a timeline event names an action outside
            ``SUPPORTED_S6_ACTIONS`` (e.g. ``reencode_video``,
            ``reencode_audio``, ``add_file``).
        UnsupportedMaterializationError: scenario declares a codec,
            container, or subtitle mode outside the Sprint 5 matrix.
        CapabilityGateError: ffmpeg / ffprobe / mkvtoolnix missing or
            below the minimum version.
        ContainmentViolationError: a path escapes ``<out_dir>/library/``.
        ToolFailedError: ffmpeg or mkvtoolnix exited non-zero during
            synthesis.
        ProbeParseError: ffprobe output is malformed or missing required
            fields.
        FilesystemActionError: a phase-B helper raised ``OSError``.
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
    # materialize executes the whole timeline; pass ``steps_limit=None`` so
    # ``run_plan`` applies every resolved event. Sprint 5 capped this at 0
    # because phase B did not yet exist and the materializer reused the
    # plan-only manifest as-is.
    plan_artifacts = run_plan(
        run_input=run_input,
        validation_report=validation_report,
        steps_limit=None,
    )
    for asset in iter_assets(scenario):
        preflight_asset(asset.video, asset.audio, asset.subtitles, asset.container)
    ctx = RunContext(
        run_input=run_input,
        out_dir=out_dir,
        run_id=uuid.uuid4(),
        started_at=started_at,
        caps=caps,
        plan_artifacts=plan_artifacts,
    )
    begin_materialize_run(ctx.out_dir, build_sentinel(ctx, RunSentinelState.IN_PROGRESS))
    return _run_synthesis(ctx, scenario)


def _run_synthesis(ctx: RunContext, scenario: Scenario) -> MaterializeArtifacts:
    """Steps 7-8: per-asset synthesis loop, phase-B mutations, finalize/cleanup."""
    invocations: list[ToolInvocation] = []
    materialized: list[MaterializedAsset] = []
    filesystem_actions: list[FilesystemAction] = []
    # Engine's ``build_initial_state`` lays every asset under the primary
    # root (scenario.library.roots[0]); synthesis must mirror that layout
    # so the on-disk file lives where phase B's ``state_delta['from_path']``
    # expects to find it.
    primary_root_path = scenario.library.roots[0].path
    try:
        # Phase A — per-asset synthesis (unchanged from Sprint 5 except for
        # the explicit ``root_path`` so the on-disk layout follows
        # ``INITIAL_PATH_TEMPLATE``).
        for invocation_index, asset in enumerate(iter_assets(scenario)):
            invocation, materialized_asset, probed, sidecar_hashes = materialize_one_asset(
                asset,
                ctx.plan_artifacts.replay_bundle.resolved_seed,
                ctx.out_dir,
                ctx.caps,
                invocation_index,
                root_path=primary_root_path,
            )
            invocations.append(invocation)
            materialized.append(materialized_asset)
            augment_manifest(
                ctx.plan_artifacts.current_manifest,
                asset,
                materialized_asset,
                probed,
                sidecar_hashes,
            )
        # Phase B — timeline application (new in Sprint 6).
        filesystem_actions, phase_b_sidecar_hashes = apply_phase_b(
            library_root=ctx.out_dir / "library",
            journal=ctx.plan_artifacts.journal,
            scenario=scenario,
            resolved_seed=ctx.plan_artifacts.replay_bundle.resolved_seed,
        )
        augment_timeline_sidecars(ctx.plan_artifacts.current_manifest, phase_b_sidecar_hashes)
    except (ToolFailedError, ProbeParseError) as exc:
        if isinstance(exc, ToolFailedError):
            invocations.append(exc.invocation)
        finalize_failure(ctx, exc, Outcome.TOOL_FAILED, invocations, materialized)
        raise
    except FilesystemActionError as exc:
        finalize_failure_filesystem(ctx, exc, invocations, materialized, filesystem_actions)
        raise
    return finalize_success(ctx, invocations, materialized, filesystem_actions)
