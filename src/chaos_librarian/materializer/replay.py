"""Replay helpers for wall-clock run bundles."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from chaos_librarian.contract.content_sources import ContentSourceEvidence
from chaos_librarian.contract.journal import CommittedJournalEntry, JournalEntry
from chaos_librarian.contract.materialization import (
    MaterializationExecutionMode,
    NetworkFsChaosAction,
    NetworkLagAction,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinelState
from chaos_librarian.contract.scenario import (
    NetworkLagEffect,
    Scenario,
    TimelineActionName,
)
from chaos_librarian.contract.validation import ValidationReport, ValidationSeverity
from chaos_librarian.engine import (
    PlanArtifacts,
    PlanExecutionRequest,
    ReplayIntegrityError,
    run_materializer_plan,
)
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.resolution import resolve_timeline, step_boundaries
from chaos_librarian.materializer.capability_gates import (
    assert_capable_for_audio_recipes,
    assert_capable_for_hdr_video,
    assert_capable_for_matroska_muxing_profiles,
    assert_capable_for_resolution_switch_video,
    assert_capable_for_webm_video,
)
from chaos_librarian.materializer.errors import (
    CorruptionActionError,
    FilesystemActionError,
    MediaActionError,
)
from chaos_librarian.materializer.network_fs_chaos import (
    CHAOS_CLOSE_ACTIONS,
    CHAOS_ENTRY_ACTIONS,
    realize_chaos_close,
    realize_chaos_entry,
    restore_chaos_modes,
)
from chaos_librarian.materializer.network_lag_fields import (
    network_lag_effect,
    network_lag_int,
    network_lag_optional_str,
    network_lag_str,
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
from chaos_librarian.materializer.phase_b.dispatch import (
    PhaseBState,
    PhaseBStateInputs,
    augment_phase_b_outputs,
    dispatch_phase_b_entry,
    make_phase_b_state,
    phase_b_failure_outcome,
    phase_b_failure_record,
)
from chaos_librarian.materializer.preflight import preflight_asset, preflight_timeline
from chaos_librarian.materializer.synthesis import (
    PhaseAInputs,
    PhaseAResult,
    materialize_assets_phase_a,
    materialize_one_asset,
)
from chaos_librarian.materializer.tooling.capabilities import (
    assert_capable_for_static_materialize,
    detect_capabilities,
)
from chaos_librarian.topology import iter_asset_contexts
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

    artifacts = run_materializer_plan(
        PlanExecutionRequest(
            run_input=run_input,
            validation_report=report,
            resolved_seed_override=bundle.resolved_seed,
            run_id_override=bundle.run_id,
            applied_events_override=bundle.applied_events,
        )
    )
    digest_entries = [
        entry.model_copy(update={"wall_clock_time": None}) for entry in artifacts.journal
    ]
    digest = hashlib.sha256(serialize_journal_bytes(digest_entries)).hexdigest()
    if digest != bundle.journal_digest:
        raise ReplayIntegrityError(
            f"journal_digest mismatch: recorded {bundle.journal_digest}, recomputed {digest}"
        )
    _preflight_run_replay_pairing(artifacts.journal)
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
    preflight_timeline(scenario, allow_network_lag=True, allow_network_fs_chaos=True)
    caps = detect_capabilities()
    assert_capable_for_static_materialize(caps)
    assert_capable_for_matroska_muxing_profiles(scenario, caps)
    assert_capable_for_webm_video(scenario, caps)
    assert_capable_for_audio_recipes(scenario, caps)
    assert_capable_for_resolution_switch_video(scenario, caps)
    assert_capable_for_hdr_video(scenario, caps)
    for context in iter_asset_contexts(scenario):
        asset = context.asset
        preflight_asset(
            parent_kind=context.parent_kind,
            video=asset.video,
            audios=asset.audio,
            subtitles=asset.subtitles,
            container=asset.container,
        )
    out_dir.mkdir(parents=True)
    (out_dir / "library").mkdir()
    started_at = datetime.now(UTC)
    phase_a = materialize_assets_phase_a(
        PhaseAInputs(
            scenario=scenario,
            out_dir=out_dir,
            artifacts=prefix_artifacts,
            caps=caps,
            stamp_manifest=True,
            materialize_asset=materialize_one_asset,
        )
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
    chaos_actions = _replay_chaos_actions(state)
    _restore_replay_chaos(state)
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
        oracle_hash_actions=state.oracle_hash_actions,
        network_lag_actions=state.network_lag_actions,
        network_fs_chaos_actions=chaos_actions,
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
    phase_a: PhaseAResult,
    state: PhaseBState,
    exc: FilesystemActionError | MediaActionError | CorruptionActionError,
) -> None:
    augment_phase_b_outputs(prefix_artifacts.current_manifest, state)
    finished_at = datetime.now(UTC)
    chaos_actions = _replay_chaos_actions(state)
    _restore_replay_chaos(state)
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
        oracle_hash_actions=state.oracle_hash_actions,
        network_lag_actions=state.network_lag_actions,
        network_fs_chaos_actions=chaos_actions,
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


def _make_run_replay_phase_b_state(
    *,
    scenario: Scenario,
    out_dir: Path,
    artifacts: PlanArtifacts,
    invocations: list[ToolInvocation],
) -> PhaseBState:
    return make_phase_b_state(
        PhaseBStateInputs(
            library_root=out_dir / "library",
            scenario=scenario,
            resolved_seed=artifacts.replay_bundle.resolved_seed,
            ffmpeg_version="unknown",
            ffprobe_version="unknown",
            invocations=invocations,
            manifest=artifacts.current_manifest,
            initial_manifest=artifacts.initial_manifest,
        )
    )


def _apply_prefix_phase_b(
    state: PhaseBState,
    artifacts: PlanArtifacts,
) -> None:
    network_lag_starts: dict[str, JournalEntry] = {}
    for entry in artifacts.journal:
        action = TimelineActionName(entry.action)
        if action is TimelineActionName.NETWORK_LAG_START:
            network_lag_starts[entry.event_id] = entry
            continue
        if action is TimelineActionName.NETWORK_LAG_COMMIT:
            state.network_lag_actions.append(
                _run_replay_network_lag_action(network_lag_starts, entry)
            )
            continue
        if _apply_replay_chaos_entry(state, entry, action):
            continue
        dispatch_phase_b_entry(state, entry)
    augment_phase_b_outputs(artifacts.current_manifest, state)
    if network_lag_starts:
        pending = sorted(network_lag_starts)
        raise ReplayIntegrityError(f"uncommitted network_lag_start entries: {pending}")
    if state.chaos is not None and (state.chaos.open_locks or state.chaos.open_unmounts):
        pending = sorted({*state.chaos.open_locks, *state.chaos.open_unmounts})
        raise ReplayIntegrityError(f"unclosed network-fs-chaos open windows: {pending}")


def _preflight_run_replay_pairing(journal: Iterable[JournalEntry]) -> None:
    network_lag_starts: dict[str, JournalEntry] = {}
    open_locks: dict[str, JournalEntry] = {}
    open_unmounts: dict[str, JournalEntry] = {}
    for entry in journal:
        action = TimelineActionName(entry.action)
        if action is TimelineActionName.NETWORK_LAG_START:
            network_lag_starts[entry.event_id] = entry
        elif action is TimelineActionName.NETWORK_LAG_COMMIT:
            _run_replay_network_lag_action(network_lag_starts, entry)
        elif action is TimelineActionName.ACQUIRE_LOCK:
            open_locks[entry.event_id] = entry
        elif action is TimelineActionName.RELEASE_LOCK:
            _preflight_chaos_close(
                entry,
                open_entries=open_locks,
                close_action="release_lock",
                open_action="acquire_lock",
            )
        elif action is TimelineActionName.UNMOUNT_PATH:
            open_unmounts[entry.event_id] = entry
        elif action is TimelineActionName.REMOUNT_PATH:
            _preflight_chaos_close(
                entry,
                open_entries=open_unmounts,
                close_action="remount_path",
                open_action="unmount_path",
            )
    if network_lag_starts:
        pending = sorted(network_lag_starts)
        raise ReplayIntegrityError(f"uncommitted network_lag_start entries: {pending}")
    if open_locks or open_unmounts:
        pending = sorted({*open_locks, *open_unmounts})
        raise ReplayIntegrityError(f"unclosed network-fs-chaos open windows: {pending}")


def _preflight_chaos_close(
    entry: JournalEntry,
    *,
    open_entries: dict[str, JournalEntry],
    close_action: str,
    open_action: str,
) -> None:
    related_id = getattr(entry, "related_event_id", None)
    if not isinstance(related_id, str):
        raise ReplayIntegrityError(f"{entry.event_id}: {close_action} missing related_event_id")
    if open_entries.pop(related_id, None) is None:
        raise ReplayIntegrityError(
            f"{entry.event_id}: {close_action} references missing {open_action} {related_id}"
        )


def _apply_replay_chaos_entry(
    state: PhaseBState, entry: JournalEntry, action: TimelineActionName
) -> bool:
    """Route a network-fs-chaos entry during replay; return whether handled."""
    if state.chaos is None:  # pragma: no cover - always set in make_phase_b_state
        return False
    if action in CHAOS_CLOSE_ACTIONS:
        realize_chaos_close(state.chaos, entry)
        return True
    if action in CHAOS_ENTRY_ACTIONS:
        realize_chaos_entry(state.chaos, entry)
        return True
    return False


def _replay_chaos_actions(state: PhaseBState) -> list[NetworkFsChaosAction]:
    return list(state.chaos.actions) if state.chaos is not None else []


def _restore_replay_chaos(state: PhaseBState) -> None:
    if state.chaos is not None:
        restore_chaos_modes(state.chaos)


def _run_replay_network_lag_action(
    starts: dict[str, JournalEntry],
    commit: JournalEntry,
) -> NetworkLagAction:
    if not isinstance(commit, CommittedJournalEntry):
        raise ReplayIntegrityError(f"{commit.event_id} is not a committed network lag entry")
    start = starts.pop(commit.related_event_id, None)
    if start is None:
        raise ReplayIntegrityError(
            f"network_lag_commit {commit.event_id} references missing start "
            f"{commit.related_event_id}"
        )
    effect = _network_lag_effect(start)
    return NetworkLagAction(
        event_id=start.event_id,
        commit_event_id=commit.event_id,
        effect=effect,
        target_ref=_network_lag_str(start, "target_ref"),
        after_event_id=_network_lag_str(start, "after_event_id"),
        logical_start_ns=_network_lag_int(start, "logical_start_ns"),
        logical_commit_ns=_network_lag_int(start, "logical_commit_ns"),
        requested_duration_ns=_network_lag_int(start, "requested_duration_ns"),
        actual_duration_ns=None,
        from_path=_network_lag_optional_str(start, "from_path"),
        to_path=_network_lag_optional_str(start, "to_path"),
        provider="stdlib-local",
        enforced=effect is not NetworkLagEffect.HELD_HANDLE,
    )


def _network_lag_effect(entry: JournalEntry) -> NetworkLagEffect:
    return network_lag_effect(entry, error_type=ReplayIntegrityError)


def _network_lag_str(entry: JournalEntry, key: str) -> str:
    return network_lag_str(entry, key, error_type=ReplayIntegrityError)


def _network_lag_optional_str(entry: JournalEntry, key: str) -> str | None:
    return network_lag_optional_str(entry, key, error_type=ReplayIntegrityError)


def _network_lag_int(entry: JournalEntry, key: str) -> int:
    return network_lag_int(entry, key, error_type=ReplayIntegrityError)
