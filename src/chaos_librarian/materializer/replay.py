"""Replay helpers for wall-clock run bundles."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from chaos_librarian.contract.journal import CommittedJournalEntry, JournalEntry
from chaos_librarian.contract.materialization import (
    NetworkFsChaosAction,
    NetworkLagAction,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode, MaterializeReplayBundle
from chaos_librarian.contract.scenario import (
    NetworkLagEffect,
    Scenario,
    TimelineActionName,
)
from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.plan import (
    PlanArtifacts,
    ReplayIntegrityError,
)
from chaos_librarian.engine.resolution import resolve_timeline, step_boundaries
from chaos_librarian.materializer.content.synthesis import (
    PhaseAInputs,
    materialize_assets_phase_a,
    materialize_one_asset,
)
from chaos_librarian.materializer.errors import (
    CorruptionActionError,
    FilesystemActionError,
    MediaActionError,
    ScenarioValidationError,
)
from chaos_librarian.materializer.persistence._context import (
    MaterializeArtifacts,
    ReportActions,
    RunContext,
)
from chaos_librarian.materializer.persistence.finalize import (
    finalize_run_replay_phase_b_failure,
    finalize_run_replay_success,
)
from chaos_librarian.materializer.phase_b.dispatch import (
    PhaseBState,
    PhaseBStateInputs,
    augment_phase_b_outputs,
    dispatch_phase_b_entry,
    make_phase_b_state,
)
from chaos_librarian.materializer.preparation import (
    PreparedMaterializerRun,
    prepare_materializer_run_input,
)
from chaos_librarian.materializer.runtime.network_fs_chaos import (
    CHAOS_CLOSE_ACTIONS,
    CHAOS_ENTRY_ACTIONS,
    realize_chaos_close,
    realize_chaos_entry,
    restore_chaos_modes,
)
from chaos_librarian.materializer.runtime.network_lag_fields import (
    network_lag_effect,
    network_lag_int,
    network_lag_optional_str,
    network_lag_str,
)
from chaos_librarian.validation import RunInput, prepare_run_input_from_bytes

__all__ = ["replay_run_bundle"]


def replay_run_bundle(bundle: MaterializeReplayBundle, out_dir: Path) -> MaterializeArtifacts:
    """Replay a verified wall-clock run bundle as fast as possible."""
    if bundle.execution_mode is not ExecutionMode.RUN:
        raise ReplayIntegrityError("only execution_mode='run' bundles are supported")
    prepared = _verified_run_prefix(bundle)
    return _materialize_verified_run_prefix(
        prepared=prepared,
        source_bundle=bundle,
        out_dir=out_dir,
    )


def _verified_run_prefix(
    bundle: MaterializeReplayBundle,
) -> PreparedMaterializerRun:
    yaml_bytes = bundle.scenario.encode("utf-8")
    run_input = prepare_run_input_from_bytes(
        raw_bytes=yaml_bytes,
        source_label=f"run-replay:{bundle.run_id}",
    )
    _assert_replay_boundary(run_input, applied_events=bundle.applied_events)
    try:
        prepared = prepare_materializer_run_input(
            run_input=run_input,
            validation_failure_message="run replay scenario re-validation failed",
            validation_payload_exclude_none=True,
            allow_network_lag=True,
            allow_network_fs_chaos=True,
            resolved_seed_override=bundle.resolved_seed,
            run_id_override=bundle.run_id,
            applied_events_override=bundle.applied_events,
        )
    except ScenarioValidationError as exc:
        errors = [
            issue.code
            for issue in exc.validation_report.issues
            if issue.severity is ValidationSeverity.ERROR
        ]
        raise ReplayIntegrityError(f"run replay scenario re-validation failed: {errors}") from exc
    artifacts = prepared.plan_artifacts
    digest_entries = [
        entry.model_copy(update={"wall_clock_time": None}) for entry in artifacts.journal
    ]
    digest = hashlib.sha256(serialize_journal_bytes(digest_entries)).hexdigest()
    if digest != bundle.journal_digest:
        raise ReplayIntegrityError(
            f"journal_digest mismatch: recorded {bundle.journal_digest}, recomputed {digest}"
        )
    _preflight_run_replay_pairing(artifacts.journal)
    return prepared


def _assert_replay_boundary(run_input: RunInput, *, applied_events: int) -> None:
    resolved_timeline = resolve_timeline(run_input.scenario)
    valid_boundaries = {0, *step_boundaries(resolved_timeline)}
    if applied_events not in valid_boundaries:
        raise ReplayIntegrityError(f"applied_events {applied_events} is not replayable")


def _materialize_verified_run_prefix(
    *,
    prepared: PreparedMaterializerRun,
    source_bundle: MaterializeReplayBundle,
    out_dir: Path,
) -> MaterializeArtifacts:
    scenario = prepared.scenario
    prefix_artifacts = prepared.plan_artifacts
    out_dir.mkdir(parents=True)
    (out_dir / "library").mkdir()
    started_at = datetime.now(UTC)
    ctx = RunContext(
        run_input=prepared.run_input,
        out_dir=out_dir,
        run_id=source_bundle.run_id,
        started_at=started_at,
        caps=prepared.caps,
        plan_artifacts=prefix_artifacts,
    )
    phase_a = materialize_assets_phase_a(
        PhaseAInputs(
            scenario=scenario,
            out_dir=out_dir,
            artifacts=prefix_artifacts,
            caps=prepared.caps,
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
        augment_phase_b_outputs(prefix_artifacts.current_manifest, state)
        chaos_actions = _replay_chaos_actions(state)
        _restore_replay_chaos(state)
        finalize_run_replay_phase_b_failure(
            ctx,
            source_bundle,
            exc,
            phase_a.invocations,
            phase_a.materialized_assets,
            actions=_report_actions_from_state(state, network_fs_chaos_actions=chaos_actions),
            content_sources=phase_a.content_sources,
        )
        raise
    chaos_actions = _replay_chaos_actions(state)
    _restore_replay_chaos(state)
    return finalize_run_replay_success(
        ctx,
        source_bundle,
        phase_a.invocations,
        phase_a.materialized_assets,
        actions=_report_actions_from_state(state, network_fs_chaos_actions=chaos_actions),
        content_sources=phase_a.content_sources,
    )


def _report_actions_from_state(
    state: PhaseBState,
    *,
    network_fs_chaos_actions: list[NetworkFsChaosAction],
) -> ReportActions:
    return ReportActions(
        filesystem=state.filesystem_actions,
        media=state.media_actions,
        corruption=state.corruption_actions,
        oracle_hash=state.oracle_hash_actions,
        network_lag=state.network_lag_actions,
        network_fs_chaos=network_fs_chaos_actions,
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
