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
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from chaos_librarian.contract.manifest import Manifest, ManifestSidecar
from chaos_librarian.contract.materialization import (
    FilesystemAction,
    MaterializedAsset,
    MediaAction,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.run_sentinel import RunSentinelState
from chaos_librarian.contract.scenario import (
    CreateSidecarEvent,
    Scenario,
    SidecarKind,
    TimelineActionName,
)
from chaos_librarian.engine import run_plan
from chaos_librarian.materializer._context import MaterializeArtifacts, RunContext
from chaos_librarian.materializer.capabilities import (
    assert_capable_for_static_materialize,
    detect_capabilities,
)
from chaos_librarian.materializer.errors import (
    FilesystemActionError,
    MediaActionError,
    ProbeParseError,
    ScenarioValidationError,
    ToolFailedError,
)

# _PhaseBContext and _dispatch_one are underscore-private in filesystem.py
# but the orchestrator needs them to dispatch one journal entry at a
# time alongside media.apply_media_action. Keep the underscore prefix
# rather than widening the public API surface — both modules are
# materializer-internal.
from chaos_librarian.materializer.filesystem import _dispatch_one, _PhaseBContext
from chaos_librarian.materializer.finalize import (
    build_sentinel,
    finalize_failure,
    finalize_failure_phase_b,
    finalize_success,
)
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
            ``SUPPORTED_S7_ACTIONS`` (currently only ``add_file``).
        UnsupportedMaterializationError: scenario declares a codec,
            container, or subtitle mode outside the Sprint 5 matrix.
        CapabilityGateError: ffmpeg / ffprobe / mkvtoolnix missing or
            below the minimum version.
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
    """Steps 7-8: per-asset synthesis loop, unified phase-B walk, finalize/cleanup."""
    invocations: list[ToolInvocation] = []
    materialized: list[MaterializedAsset] = []
    filesystem_actions: list[FilesystemAction] = []
    media_actions: list[MediaAction] = []
    # Engine's ``build_initial_state`` lays every asset under the primary
    # root (scenario.library.roots[0]); synthesis must mirror that layout
    # so the on-disk file lives where phase B's ``state_delta['from_path']``
    # expects to find it.
    primary_root_path = scenario.library.roots[0].path
    timeline_sidecar_languages = _timeline_sidecar_languages(scenario)
    try:
        # Phase A — per-asset synthesis. ``skip_languages`` defers the
        # write to phase B for any (asset, language) the timeline will
        # produce; otherwise phase A would write an orphan SRT that the
        # manifest cannot reference (manifest v3 uniqueness collapses
        # the row onto the timeline-allocated id).
        for invocation_index, asset in enumerate(iter_assets(scenario)):
            skip_languages = timeline_sidecar_languages.get(asset.id, frozenset())
            invocation, materialized_asset, probed, sidecar_hashes = materialize_one_asset(
                asset,
                ctx.plan_artifacts.replay_bundle.resolved_seed,
                ctx.out_dir,
                ctx.caps,
                invocation_index,
                root_path=primary_root_path,
                skip_languages=skip_languages,
            )
            invocations.append(invocation)
            materialized.append(materialized_asset)
            augment_manifest(
                ctx.plan_artifacts.current_manifest,
                asset,
                materialized_asset,
                probed,
                sidecar_hashes,
                skip_languages=skip_languages,
            )
        # Phase B — unified journal walk. Each entry routes to stdlib
        # (filesystem._dispatch_one) or media (media.apply_media_action).
        scenario_assets = {asset.id: asset for asset in iter_assets(scenario)}
        library_root = ctx.out_dir / "library"
        resolved_seed = ctx.plan_artifacts.replay_bundle.resolved_seed
        fs_ctx = _PhaseBContext(
            library_root=library_root,
            scenario_assets=scenario_assets,
            resolved_seed=resolved_seed,
        )
        media_ctx = _MediaContext(
            library_root=library_root,
            scenario_assets=scenario_assets,
            resolved_seed=resolved_seed,
            ffmpeg_version=ctx.caps.ffmpeg.version or "unknown",
            ffprobe_version=ctx.caps.ffprobe.version or "unknown",
            invocations=invocations,
            sidecar_lookup=_sidecar_lookup_from(ctx.plan_artifacts.current_manifest),
        )
        for entry in ctx.plan_artifacts.journal:
            action = TimelineActionName(entry.action)
            if action in _STDLIB_ACTIONS:
                result = _dispatch_one(fs_ctx, entry)
                if result is not None:
                    filesystem_actions.append(result)
            elif action in _MEDIA_ACTIONS:
                media_actions.append(apply_media_action(media_ctx, entry))
            else:
                # Defense in depth — preflight should have rejected this.
                raise MediaActionError(
                    f"unsupported phase-B action {action.value!r}",
                    event_id=entry.event_id,
                    action=action,
                    cause=RuntimeError("not in _STDLIB_ACTIONS or _MEDIA_ACTIONS"),
                )
        # Drain phase-B sidecar hashes from BOTH dispatchers, plus the
        # post-phase-B version map (reencode_* / remux / edit_metadata /
        # embed_subtitle) and the post-phase-B sidecar map
        # (update_sidecar / extract_subtitle).
        augment_timeline_sidecars(
            ctx.plan_artifacts.current_manifest, fs_ctx.phase_b_sidecar_hashes
        )
        augment_versions(ctx.plan_artifacts.current_manifest, media_ctx.post_phase_b_versions)
        augment_updated_sidecars(
            ctx.plan_artifacts.current_manifest, media_ctx.post_phase_b_sidecars
        )
    except (ToolFailedError, ProbeParseError) as exc:
        if isinstance(exc, ToolFailedError):
            invocations.append(exc.invocation)
        finalize_failure(ctx, exc, Outcome.TOOL_FAILED, invocations, materialized)
        raise
    except FilesystemActionError as exc:
        finalize_failure_phase_b(
            ctx,
            exc,
            Outcome.FS_FAILED,
            invocations,
            materialized,
            filesystem_actions,
            media_actions,
        )
        raise
    except MediaActionError as exc:
        finalize_failure_phase_b(
            ctx,
            exc,
            Outcome.MEDIA_FAILED,
            invocations,
            materialized,
            filesystem_actions,
            media_actions,
        )
        raise
    return finalize_success(ctx, invocations, materialized, filesystem_actions, media_actions)


def _sidecar_lookup_from(manifest: Manifest) -> Callable[[str], ManifestSidecar | None]:
    """Build a ``sidecar_id -> ManifestSidecar`` lookup callable.

    Used by ``update_sidecar`` handlers to recover the kind/language
    recorded on the existing manifest row. The lookup is a closure over
    a dict snapshot taken before the phase-B walk, so concurrent
    mutations during the walk (handlers may append new rows) don't
    affect lookups for ids that already existed.
    """
    by_id = {sidecar.id: sidecar for sidecar in manifest.sidecars}

    def lookup(sidecar_id: str) -> ManifestSidecar | None:
        return by_id.get(sidecar_id)

    return lookup


def _timeline_sidecar_languages(scenario: Scenario) -> dict[str, frozenset[str]]:
    """Map each asset_id to the set of languages a timeline ``create_sidecar`` will write.

    Phase A consults this set to skip declared subtitles whose language
    the timeline overrides; otherwise both phases would emit a file for
    the same ``(asset_id, language)`` and the manifest v3 uniqueness
    collapse would orphan the phase-A file (#39).
    """
    per_asset: dict[str, set[str]] = {}
    for event in scenario.timeline:
        if not isinstance(event, CreateSidecarEvent):
            continue
        # Sprint 7 widens CreateSidecarEvent.language to ``str | None`` for
        # poster/NFO kinds; only subtitle kinds participate in declared-
        # subtitle override tracking, and the model_validator guarantees
        # subtitle => language is not None.
        if event.kind is not SidecarKind.SUBTITLE:
            continue
        assert event.language is not None
        per_asset.setdefault(event.target, set()).add(event.language)
    return {asset_id: frozenset(langs) for asset_id, langs in per_asset.items()}
