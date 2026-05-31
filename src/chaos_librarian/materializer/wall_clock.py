"""Wall-clock materialize/run orchestrator."""

from __future__ import annotations

import dataclasses
import hashlib
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from chaos_librarian.clock import parse_duration
from chaos_librarian.contract.content_sources import ContentSourceEvidence
from chaos_librarian.contract.journal import CommittedJournalEntry, JournalEntry
from chaos_librarian.contract.materialization import (
    FilesystemAction,
    MaterializationExecutionMode,
    NetworkFsChaosAction,
    NetworkLagAction,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode
from chaos_librarian.contract.run_sentinel import RunSentinelState
from chaos_librarian.contract.scenario import (
    NetworkLagEffect,
    Scenario,
    TimelineActionName,
)
from chaos_librarian.engine import PlanArtifacts, PlanExecutionRequest, run_materializer_plan
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.resolution import ResolvedEvent, resolve_timeline
from chaos_librarian.errors import ChaosLibrarianValueError
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
    ScenarioValidationError,
    TimelineUnsupportedError,
)
from chaos_librarian.materializer.network_fs_chaos import (
    CHAOS_CLOSE_ACTIONS,
    CHAOS_ENTRY_ACTIONS,
    NetworkFsChaosState,
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
    WallClockBaselineMetadata,
    cleanup_failed_phase_b_run,
    finalize_materialize_run,
    publish_wall_clock_baseline,
)
from chaos_librarian.materializer.phase_b import (
    PhaseBState,
    PhaseBStateInputs,
    augment_phase_b_outputs,
    dispatch_phase_b_entry,
    make_phase_b_state,
    phase_b_failure_outcome,
    phase_b_failure_record,
)
from chaos_librarian.materializer.phase_b.filesystem import promote_slow_copy
from chaos_librarian.materializer.preflight import (
    preflight_asset,
    preflight_timeline,
)
from chaos_librarian.materializer.scheduler import (
    SpeedMultiplier,
    due_event_count,
    logical_now_ns,
    parse_speed,
)
from chaos_librarian.materializer.synthesis import (
    PhaseAInputs,
    PhaseAResult,
    materialize_assets_phase_a,
    materialize_one_asset,
    stamp_phase_a_manifest,
)
from chaos_librarian.materializer.tooling.capabilities import (
    assert_capable_for_static_materialize,
    detect_capabilities,
)
from chaos_librarian.topology import iter_asset_contexts
from chaos_librarian.validation import run_validation
from chaos_librarian.validation.input import prepare_run_input

__all__ = [
    "WallClockSlowCopySession",
    "WallClockUsageError",
    "run_wall_clock_scenario",
]

# Cadence (1 second in ns) at which an in-flight slow copy grows toward its
# final size while waiting for the commit event.
_SLOW_COPY_POLL_INTERVAL_NS = 1_000_000_000


class WallClockUsageError(ChaosLibrarianValueError):
    """Raised for invalid wall-clock-only CLI parameters."""


@dataclass(slots=True)
class WallClockSlowCopySession:
    """Active wall-clock slow-copy state."""

    start_event_id: str
    asset_id: str
    source_bytes: bytes
    temp_path: str
    final_path: str
    start_logical_ns: int
    commit_logical_ns: int
    total_bytes: int


@dataclass(slots=True)
class WallClockNetworkLagSession:
    """Active wall-clock network-lag state."""

    start_event_id: str
    effect: NetworkLagEffect
    target_ref: str
    after_event_id: str
    logical_start_ns: int
    logical_commit_ns: int
    requested_duration_ns: int
    started_wall_ns: int
    from_path: str | None
    to_path: str | None


@dataclass(slots=True)
class _DispatchState(PhaseBState):
    slow_copies: dict[str, WallClockSlowCopySession] = field(default_factory=dict)
    slow_copy_initial_paths: dict[str, str] = field(default_factory=dict)
    network_lag_starts_by_after: dict[str, JournalEntry] = field(default_factory=dict)
    network_lags: dict[str, WallClockNetworkLagSession] = field(default_factory=dict)
    deferred_network_lag_entries: dict[str, JournalEntry] = field(default_factory=dict)
    network_lag_actions: list[NetworkLagAction] = field(default_factory=list)


def _monotonic_ns() -> int:
    return time.monotonic_ns()


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _sleep_until(deadline_ns: int) -> None:
    remaining_ns = deadline_ns - _monotonic_ns()
    if remaining_ns > 0:
        time.sleep(remaining_ns / 1_000_000_000)


def run_wall_clock_scenario(
    scenario_path: Path,
    out_dir: Path,
    *,
    duration: str,
    speed: str,
) -> MaterializeArtifacts:
    """Run a scenario against wall-clock time and emit materialized artifacts."""
    requested_duration_ns = _parse_positive_duration(duration)
    speed_multiplier = parse_speed(speed)
    started_at = _utc_now()
    run_input = prepare_run_input(scenario_path)
    validation_report = run_validation(run_input)
    if not validation_report.ok:
        raise ScenarioValidationError(
            "scenario failed semantic validation; refusing to run",
            payload={"validation_report": validation_report.model_dump(mode="json")},
            validation_report=validation_report,
        )
    scenario = run_input.scenario
    preflight_timeline(scenario, allow_network_lag=True, allow_network_fs_chaos=True)
    resolved_timeline = resolve_timeline(scenario)
    _preflight_wall_clock_slow_copies(resolved_timeline)
    caps = detect_capabilities()
    assert_capable_for_static_materialize(caps)
    assert_capable_for_matroska_muxing_profiles(scenario, caps)
    assert_capable_for_webm_video(scenario, caps)
    assert_capable_for_audio_recipes(scenario, caps)
    assert_capable_for_resolution_switch_video(scenario, caps)
    assert_capable_for_hdr_video(scenario, caps)
    run_id = uuid.uuid4()
    full_artifacts = run_materializer_plan(
        PlanExecutionRequest(
            run_input=run_input,
            validation_report=validation_report,
            run_id_override=run_id,
        )
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

    staging_dir = _create_staging_dir(out_dir)
    baseline_artifacts = run_materializer_plan(
        PlanExecutionRequest(
            run_input=run_input,
            validation_report=validation_report,
            run_id_override=run_id,
            applied_events_override=0,
        )
    )
    phase_a = materialize_assets_phase_a(
        PhaseAInputs(
            scenario=scenario,
            out_dir=staging_dir,
            artifacts=baseline_artifacts,
            caps=caps,
            stamp_manifest=True,
            materialize_asset=materialize_one_asset,
        )
    )
    _publish_baseline(
        staging_dir=staging_dir,
        out_dir=out_dir,
        run_input=run_input,
        artifacts=baseline_artifacts,
        caps=caps,
        run_id=run_id,
        started_at=started_at,
        content_sources=phase_a.content_sources,
    )
    return _run_timed_phase(
        run_context=RunContext(
            run_input=run_input,
            out_dir=out_dir,
            run_id=run_id,
            started_at=started_at,
            caps=caps,
            plan_artifacts=full_artifacts,
        ),
        scenario=scenario,
        phase_a=phase_a,
        requested_duration_ns=requested_duration_ns,
        speed=speed_multiplier,
    )


def _parse_positive_duration(raw: str) -> int:
    duration_ns = parse_duration(raw)
    if duration_ns <= 0:
        raise WallClockUsageError("duration must be greater than zero")
    return duration_ns


def _create_staging_dir(out_dir: Path) -> Path:
    if out_dir.exists():
        raise FileExistsError(f"refusing to write into existing directory: {out_dir}")
    staging_dir = out_dir.parent / f".{out_dir.name}.staging"
    staging_dir.mkdir(parents=True)
    (staging_dir / "library").mkdir()
    return staging_dir


def _preflight_wall_clock_slow_copies(resolved_timeline: list[ResolvedEvent]) -> None:
    for index, resolved in enumerate(resolved_timeline):
        action = resolved.event.action
        if action.value != "slow_copy_start":
            continue
        next_index = index + 1
        if next_index >= len(resolved_timeline):
            _raise_slow_copy_unsupported(resolved.event.id)
        next_event = resolved_timeline[next_index].event
        if next_event.action.value != "slow_copy_commit":
            _raise_slow_copy_unsupported(resolved.event.id)
        if getattr(next_event, "for_", None) != resolved.event.id:
            _raise_slow_copy_unsupported(resolved.event.id)
        if resolved_timeline[next_index].at_ns <= resolved.at_ns:
            _raise_slow_copy_unsupported(resolved.event.id)


def _raise_slow_copy_unsupported(start_event_id: str) -> None:
    raise TimelineUnsupportedError(
        "wall-clock slow_copy_start must be immediately followed by its commit",
        payload={"event_id": start_event_id},
    )


def _publish_baseline(
    *,
    staging_dir: Path,
    out_dir: Path,
    run_input,
    artifacts: PlanArtifacts,
    caps,
    run_id: uuid.UUID,
    started_at: datetime,
    content_sources: list[ContentSourceEvidence],
) -> None:
    replay_bundle = build_replay_bundle(
        run_id=run_id,
        scenario_yaml_bytes=run_input.raw_bytes,
        plan_artifacts=artifacts,
        caps=caps,
        created_at=started_at,
        content_sources=content_sources,
        execution_mode=ExecutionMode.RUN,
    )
    ctx = RunContext(
        run_input=run_input,
        out_dir=out_dir,
        run_id=run_id,
        started_at=started_at,
        caps=caps,
        plan_artifacts=artifacts,
    )
    publish_wall_clock_baseline(
        staging_dir,
        out_dir,
        WallClockBaselineMetadata(
            initial_manifest=artifacts.initial_manifest,
            current_manifest=artifacts.current_manifest,
            validation_report=artifacts.validation_report,
            replay_bundle=replay_bundle,
            scenario_yaml_bytes=run_input.raw_bytes,
            sentinel=build_sentinel(ctx, RunSentinelState.IN_PROGRESS),
        ),
    )


def _run_timed_phase(
    *,
    run_context: RunContext,
    scenario: Scenario,
    phase_a: PhaseAResult,
    requested_duration_ns: int,
    speed: SpeedMultiplier,
) -> MaterializeArtifacts:
    start_wall_ns = _monotonic_ns()
    deadline_ns = start_wall_ns + requested_duration_ns
    state = _make_dispatch_state(run_context, scenario, phase_a.invocations)
    executed_journal: list[JournalEntry] = []
    cursor = 0
    journal = run_context.plan_artifacts.journal
    _configure_network_lag_schedule(state, journal)
    logical_times_ns = [entry.logical_time_ns for entry in journal]
    commit_times = _slow_copy_commit_times(journal)
    overran_duration = False

    try:
        while cursor < len(journal):
            now_ns = _monotonic_ns()
            logical_ns = logical_now_ns(now_ns - start_wall_ns, speed)
            _grow_active_slow_copies(
                run_context.out_dir / "library",
                state.slow_copies,
                logical_ns=logical_ns,
            )
            if now_ns >= deadline_ns:
                break
            due_count = due_event_count(logical_times_ns, logical_ns=logical_ns, cursor=cursor)
            if due_count == 0:
                wake_ns = _next_wake_ns(start_wall_ns, deadline_ns, journal[cursor], speed)
                if state.slow_copies:
                    wake_ns = min(wake_ns, now_ns + _SLOW_COPY_POLL_INTERVAL_NS)
                _sleep_until(wake_ns)
                continue
            for _ in range(due_count):
                if _monotonic_ns() >= deadline_ns:
                    break
                cursor = _execute_and_record(
                    cursor=cursor,
                    journal=journal,
                    state=state,
                    commit_times=commit_times,
                    executed_journal=executed_journal,
                    out_dir=run_context.out_dir,
                )
        if state.slow_copies:
            cursor = _finish_active_slow_copies(
                cursor=cursor,
                journal=journal,
                state=state,
                start_wall_ns=start_wall_ns,
                speed=speed,
                executed_journal=executed_journal,
                out_dir=run_context.out_dir,
            )
            overran_duration = True
        if state.network_lags:
            cursor = _finish_active_network_lags(
                cursor=cursor,
                journal=journal,
                state=state,
                start_wall_ns=start_wall_ns,
                speed=speed,
                executed_journal=executed_journal,
                out_dir=run_context.out_dir,
            )
            overran_duration = True
    except (FilesystemActionError, MediaActionError, CorruptionActionError) as exc:
        actual_duration_ns = max(0, _monotonic_ns() - start_wall_ns)
        _finalize_wall_clock_phase_b_failure(
            run_context=run_context,
            scenario=scenario,
            phase_a=phase_a,
            state=state,
            executed_journal=executed_journal,
            requested_duration_ns=requested_duration_ns,
            actual_duration_ns=actual_duration_ns,
            speed=speed,
            overran_duration=actual_duration_ns > requested_duration_ns,
            exc=exc,
        )
        raise
    if cursor >= len(journal):
        _sleep_until(deadline_ns)
    actual_duration_ns = max(0, _monotonic_ns() - start_wall_ns)
    overran_duration = overran_duration or actual_duration_ns > requested_duration_ns
    return _finalize_wall_clock_run(
        run_context=run_context,
        scenario=scenario,
        phase_a=phase_a,
        state=state,
        executed_journal=executed_journal,
        requested_duration_ns=requested_duration_ns,
        actual_duration_ns=actual_duration_ns,
        speed=speed,
        overran_duration=overran_duration,
    )


def _make_dispatch_state(
    run_context: RunContext,
    scenario: Scenario,
    invocations: list[ToolInvocation],
) -> _DispatchState:
    state = make_phase_b_state(
        PhaseBStateInputs(
            library_root=run_context.out_dir / "library",
            scenario=scenario,
            resolved_seed=run_context.plan_artifacts.replay_bundle.resolved_seed,
            ffmpeg_version=run_context.caps.ffmpeg.version or "unknown",
            ffprobe_version=run_context.caps.ffprobe.version or "unknown",
            invocations=invocations,
            manifest=run_context.plan_artifacts.current_manifest,
            initial_manifest=run_context.plan_artifacts.initial_manifest,
        )
    )
    return _DispatchState(
        fs_ctx=state.fs_ctx,
        media_ctx=state.media_ctx,
        corruption_ctx=state.corruption_ctx,
        oracle_hash_ctx=state.oracle_hash_ctx,
        chaos=state.chaos,
    )


def _next_wake_ns(
    start_wall_ns: int,
    deadline_ns: int,
    next_entry: JournalEntry,
    speed: SpeedMultiplier,
) -> int:
    return min(deadline_ns, _entry_due_wall_ns(start_wall_ns, next_entry, speed))


def _entry_due_wall_ns(
    start_wall_ns: int,
    next_entry: JournalEntry,
    speed: SpeedMultiplier,
) -> int:
    logical_delta = max(0, next_entry.logical_time_ns)
    wall_offset = logical_delta * speed.denominator // speed.numerator
    if logical_delta * speed.denominator % speed.numerator:
        wall_offset += 1
    return start_wall_ns + wall_offset


def _execute_and_record(
    *,
    cursor: int,
    journal: tuple[JournalEntry, ...],
    state: _DispatchState,
    commit_times: Mapping[str, int],
    executed_journal: list[JournalEntry],
    out_dir: Path,
) -> int:
    entry = journal[cursor]
    _execute_entry(state, entry, commit_times)
    executed = entry.model_copy(update={"wall_clock_time": _utc_now()})
    _append_journal_entry(out_dir / "journal.jsonl", executed)
    executed_journal.append(executed)
    return cursor + 1


def _execute_entry(
    state: _DispatchState,
    entry: JournalEntry,
    commit_times: Mapping[str, int],
) -> None:
    lag_start = state.network_lag_starts_by_after.get(entry.event_id)
    if lag_start is not None:
        state.deferred_network_lag_entries[lag_start.event_id] = entry
        return
    action = TimelineActionName(entry.action)
    if action is TimelineActionName.SLOW_COPY_START:
        state.filesystem_actions.append(_wall_clock_slow_copy_start(state, entry, commit_times))
        return
    if action is TimelineActionName.SLOW_COPY_COMMIT:
        state.filesystem_actions.append(_wall_clock_slow_copy_commit(state, entry))
        return
    if action is TimelineActionName.NETWORK_LAG_START:
        _wall_clock_network_lag_start(state, entry)
        return
    if action is TimelineActionName.NETWORK_LAG_COMMIT:
        state.network_lag_actions.append(_wall_clock_network_lag_commit(state, entry))
        return
    if _dispatch_chaos_entry(state, entry, action):
        return
    dispatch_phase_b_entry(state, entry)


def _dispatch_chaos_entry(
    state: _DispatchState, entry: JournalEntry, action: TimelineActionName
) -> bool:
    """Route a network-fs-chaos entry; return whether it was handled."""
    if action in CHAOS_CLOSE_ACTIONS:
        realize_chaos_close(_chaos_state(state), entry)
        return True
    if action in CHAOS_ENTRY_ACTIONS:
        realize_chaos_entry(_chaos_state(state), entry)
        return True
    return False


def _chaos_state(state: _DispatchState) -> NetworkFsChaosState:
    if state.chaos is None:  # pragma: no cover - always set in _make_dispatch_state
        raise ChaosLibrarianValueError("network-fs-chaos state not initialized")
    return state.chaos


def _chaos_actions(state: _DispatchState) -> list[NetworkFsChaosAction]:
    return list(state.chaos.actions) if state.chaos is not None else []


def _restore_chaos(state: _DispatchState) -> None:
    if state.chaos is not None:
        restore_chaos_modes(state.chaos)


def _configure_network_lag_schedule(
    state: _DispatchState,
    journal: tuple[JournalEntry, ...],
) -> None:
    for entry in journal:
        if TimelineActionName(entry.action) is not TimelineActionName.NETWORK_LAG_START:
            continue
        effect = _network_lag_effect(entry)
        if effect is NetworkLagEffect.HELD_HANDLE:
            continue
        after_event_id = _network_lag_str(entry, "after_event_id")
        state.network_lag_starts_by_after[after_event_id] = entry


def _wall_clock_slow_copy_start(
    state: _DispatchState,
    entry: JournalEntry,
    commit_times: Mapping[str, int],
) -> FilesystemAction:
    asset_id = entry.target_ids[0]
    initial_path = str(entry.state_delta["initial_path_at_start"])
    temp_path = str(entry.state_delta["temp_path"])
    final_path = str(entry.state_delta["final_path"])
    src = state.fs_ctx.library_root / initial_path
    dst = state.fs_ctx.library_root / temp_path
    dst.parent.mkdir(parents=True, exist_ok=True)
    source_bytes = src.read_bytes()
    dst.write_bytes(b"")
    state.slow_copies[entry.event_id] = WallClockSlowCopySession(
        start_event_id=entry.event_id,
        asset_id=asset_id,
        source_bytes=source_bytes,
        temp_path=temp_path,
        final_path=final_path,
        start_logical_ns=entry.logical_time_ns,
        commit_logical_ns=commit_times[entry.event_id],
        total_bytes=len(source_bytes),
    )
    state.slow_copy_initial_paths[entry.event_id] = initial_path
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.SLOW_COPY_START,
        target_asset_id=asset_id,
        from_path=initial_path,
        to_path=final_path,
        temp_path=temp_path,
        duration_ns=0,
    )


def _wall_clock_slow_copy_commit(
    state: _DispatchState,
    entry: JournalEntry,
) -> FilesystemAction:
    if not isinstance(entry, CommittedJournalEntry):
        raise ChaosLibrarianValueError(f"{entry.event_id} is not a committed slow_copy entry")
    session = state.slow_copies.pop(entry.related_event_id)
    initial_path = state.slow_copy_initial_paths.pop(entry.related_event_id)
    temp = state.fs_ctx.library_root / session.temp_path
    temp.parent.mkdir(parents=True, exist_ok=True)
    temp.write_bytes(session.source_bytes)
    promote_slow_copy(
        library_root=state.fs_ctx.library_root,
        initial_path=initial_path,
        temp_path=session.temp_path,
        final_path=session.final_path,
    )
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.SLOW_COPY_COMMIT,
        target_asset_id=session.asset_id,
        from_path=session.temp_path,
        to_path=session.final_path,
        temp_path=None,
        duration_ns=0,
    )


def _wall_clock_network_lag_start(state: _DispatchState, entry: JournalEntry) -> None:
    effect = _network_lag_effect(entry)
    state.network_lags[entry.event_id] = WallClockNetworkLagSession(
        start_event_id=entry.event_id,
        effect=effect,
        target_ref=_network_lag_str(entry, "target_ref"),
        after_event_id=_network_lag_str(entry, "after_event_id"),
        logical_start_ns=_network_lag_int(entry, "logical_start_ns"),
        logical_commit_ns=_network_lag_int(entry, "logical_commit_ns"),
        requested_duration_ns=_network_lag_int(entry, "requested_duration_ns"),
        started_wall_ns=_monotonic_ns(),
        from_path=_network_lag_optional_str(entry, "from_path"),
        to_path=_network_lag_optional_str(entry, "to_path"),
    )


def _wall_clock_network_lag_commit(
    state: _DispatchState,
    entry: JournalEntry,
) -> NetworkLagAction:
    if not isinstance(entry, CommittedJournalEntry):
        raise ChaosLibrarianValueError(f"{entry.event_id} is not a committed network_lag entry")
    session = state.network_lags.pop(entry.related_event_id)
    deferred = state.deferred_network_lag_entries.pop(entry.related_event_id, None)
    if deferred is not None:
        dispatch_phase_b_entry(state, deferred)
    return NetworkLagAction(
        event_id=session.start_event_id,
        commit_event_id=entry.event_id,
        effect=session.effect,
        target_ref=session.target_ref,
        after_event_id=session.after_event_id,
        logical_start_ns=session.logical_start_ns,
        logical_commit_ns=session.logical_commit_ns,
        requested_duration_ns=session.requested_duration_ns,
        actual_duration_ns=max(0, _monotonic_ns() - session.started_wall_ns),
        from_path=session.from_path,
        to_path=session.to_path,
        provider="stdlib-local",
        enforced=session.effect is not NetworkLagEffect.HELD_HANDLE,
    )


def _network_lag_effect(entry: JournalEntry) -> NetworkLagEffect:
    return network_lag_effect(entry, error_type=ChaosLibrarianValueError)


def _network_lag_str(entry: JournalEntry, key: str) -> str:
    return network_lag_str(entry, key, error_type=ChaosLibrarianValueError)


def _network_lag_optional_str(entry: JournalEntry, key: str) -> str | None:
    return network_lag_optional_str(entry, key, error_type=ChaosLibrarianValueError)


def _network_lag_int(entry: JournalEntry, key: str) -> int:
    return network_lag_int(entry, key, error_type=ChaosLibrarianValueError)


def _finish_active_slow_copies(
    *,
    cursor: int,
    journal: tuple[JournalEntry, ...],
    state: _DispatchState,
    start_wall_ns: int,
    speed: SpeedMultiplier,
    executed_journal: list[JournalEntry],
    out_dir: Path,
) -> int:
    while cursor < len(journal):
        entry = journal[cursor]
        action = TimelineActionName(entry.action)
        if action is not TimelineActionName.SLOW_COPY_COMMIT:
            break
        if not isinstance(entry, CommittedJournalEntry):
            raise ChaosLibrarianValueError(f"{entry.event_id} is not a committed slow_copy entry")
        if entry.related_event_id not in state.slow_copies:
            break
        _sleep_until(_entry_due_wall_ns(start_wall_ns, entry, speed))
        logical_ns = logical_now_ns(_monotonic_ns() - start_wall_ns, speed)
        _grow_active_slow_copies(out_dir / "library", state.slow_copies, logical_ns=logical_ns)
        cursor = _execute_and_record(
            cursor=cursor,
            journal=journal,
            state=state,
            commit_times={},
            executed_journal=executed_journal,
            out_dir=out_dir,
        )
    return cursor


def _finish_active_network_lags(
    *,
    cursor: int,
    journal: tuple[JournalEntry, ...],
    state: _DispatchState,
    start_wall_ns: int,
    speed: SpeedMultiplier,
    executed_journal: list[JournalEntry],
    out_dir: Path,
) -> int:
    while cursor < len(journal) and state.network_lags:
        entry = journal[cursor]
        _sleep_until(_entry_due_wall_ns(start_wall_ns, entry, speed))
        cursor = _execute_and_record(
            cursor=cursor,
            journal=journal,
            state=state,
            commit_times={},
            executed_journal=executed_journal,
            out_dir=out_dir,
        )
    return cursor


def _append_journal_entry(path: Path, entry: JournalEntry) -> None:
    with path.open("ab") as handle:
        handle.write(serialize_journal_bytes((entry,)))


def _slow_copy_commit_times(journal: tuple[JournalEntry, ...]) -> dict[str, int]:
    times: dict[str, int] = {}
    for entry in journal:
        if TimelineActionName(entry.action) is not TimelineActionName.SLOW_COPY_COMMIT:
            continue
        if not isinstance(entry, CommittedJournalEntry):
            raise ChaosLibrarianValueError(f"{entry.event_id} is not a committed slow_copy entry")
        times[entry.related_event_id] = entry.logical_time_ns
    return times


def _slow_copy_visible_size(
    session: WallClockSlowCopySession,
    logical_now_ns: int,
) -> int:
    duration_ns = session.commit_logical_ns - session.start_logical_ns
    elapsed_ns = logical_now_ns - session.start_logical_ns
    clamped_ns = max(0, min(elapsed_ns, duration_ns))
    return session.total_bytes * clamped_ns // duration_ns


def _grow_active_slow_copies(
    library_root: Path,
    sessions: Mapping[str, WallClockSlowCopySession],
    *,
    logical_ns: int,
) -> None:
    for session in sessions.values():
        visible_size = _slow_copy_visible_size(session, logical_ns)
        temp = library_root / session.temp_path
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(session.source_bytes[:visible_size])


def _finalize_wall_clock_run(
    *,
    run_context: RunContext,
    scenario: Scenario,
    phase_a: PhaseAResult,
    state: _DispatchState,
    executed_journal: list[JournalEntry],
    requested_duration_ns: int,
    actual_duration_ns: int,
    speed: SpeedMultiplier,
    overran_duration: bool,
) -> MaterializeArtifacts:
    final_artifacts = _final_artifacts_for_executed_prefix(
        run_context=run_context,
        scenario=scenario,
        phase_a=phase_a,
        state=state,
        executed_journal=executed_journal,
    )
    finished_at = _utc_now()
    materialization_report = build_report(
        outcome=Outcome.SUCCESS,
        run_id=run_context.run_id,
        caps=run_context.caps,
        started_at=run_context.started_at,
        finished_at=finished_at,
        invocations=state.media_ctx.invocations,
        materialized=phase_a.materialized_assets,
        failures=[],
        filesystem_actions=state.filesystem_actions,
        media_actions=state.media_actions,
        corruption_actions=state.corruption_actions,
        oracle_hash_actions=state.oracle_hash_actions,
        network_lag_actions=state.network_lag_actions,
        network_fs_chaos_actions=_chaos_actions(state),
        requested_duration_ns=requested_duration_ns,
        actual_duration_ns=actual_duration_ns,
        speed_multiplier=speed.normalized,
        overran_duration=overran_duration,
        content_sources=phase_a.content_sources,
        execution_mode=MaterializationExecutionMode.RUN,
    )
    _restore_chaos(state)
    replay_bundle = _build_final_replay_bundle(
        run_context=run_context,
        artifacts=final_artifacts,
        executed_journal=executed_journal,
        created_at=finished_at,
        content_sources=phase_a.content_sources,
    )
    finalize_materialize_run(
        run_context.out_dir,
        build_metadata(
            plan_artifacts=final_artifacts,
            scenario_yaml_bytes=run_context.run_input.raw_bytes,
            materialization_report=materialization_report,
            replay_bundle=replay_bundle,
            sentinel=build_sentinel(run_context, RunSentinelState.COMPLETE),
        ),
        build_reports(final_artifacts),
    )
    return MaterializeArtifacts(
        current_manifest=final_artifacts.current_manifest,
        materialization_report=materialization_report,
        replay_bundle=replay_bundle,
    )


def _finalize_wall_clock_phase_b_failure(
    *,
    run_context: RunContext,
    scenario: Scenario,
    phase_a: PhaseAResult,
    state: _DispatchState,
    executed_journal: list[JournalEntry],
    requested_duration_ns: int,
    actual_duration_ns: int,
    speed: SpeedMultiplier,
    overran_duration: bool,
    exc: FilesystemActionError | MediaActionError | CorruptionActionError,
) -> None:
    final_artifacts = _final_artifacts_for_executed_prefix(
        run_context=run_context,
        scenario=scenario,
        phase_a=phase_a,
        state=state,
        executed_journal=executed_journal,
    )
    finished_at = _utc_now()
    outcome = phase_b_failure_outcome(exc)
    materialization_report = build_report(
        outcome=outcome,
        run_id=run_context.run_id,
        caps=run_context.caps,
        started_at=run_context.started_at,
        finished_at=finished_at,
        invocations=state.media_ctx.invocations,
        materialized=phase_a.materialized_assets,
        failures=[phase_b_failure_record(exc)],
        filesystem_actions=state.filesystem_actions,
        media_actions=state.media_actions,
        corruption_actions=state.corruption_actions,
        oracle_hash_actions=state.oracle_hash_actions,
        network_lag_actions=state.network_lag_actions,
        network_fs_chaos_actions=_chaos_actions(state),
        requested_duration_ns=requested_duration_ns,
        actual_duration_ns=actual_duration_ns,
        speed_multiplier=speed.normalized,
        overran_duration=overran_duration,
        content_sources=phase_a.content_sources,
        execution_mode=MaterializationExecutionMode.RUN,
    )
    _restore_chaos(state)
    replay_bundle = _build_final_replay_bundle(
        run_context=run_context,
        artifacts=final_artifacts,
        executed_journal=executed_journal,
        created_at=finished_at,
        content_sources=phase_a.content_sources,
    )
    cleanup_failed_phase_b_run(
        run_context.out_dir,
        build_metadata(
            plan_artifacts=final_artifacts,
            scenario_yaml_bytes=run_context.run_input.raw_bytes,
            materialization_report=materialization_report,
            replay_bundle=replay_bundle,
            sentinel=build_sentinel(run_context, RunSentinelState.COMPLETE),
        ),
    )


def _final_artifacts_for_executed_prefix(
    *,
    run_context: RunContext,
    scenario: Scenario,
    phase_a: PhaseAResult,
    state: _DispatchState,
    executed_journal: list[JournalEntry],
) -> PlanArtifacts:
    prefix_artifacts = run_materializer_plan(
        PlanExecutionRequest(
            run_input=run_context.run_input,
            validation_report=run_context.plan_artifacts.validation_report,
            resolved_seed_override=run_context.plan_artifacts.replay_bundle.resolved_seed,
            run_id_override=run_context.run_id,
            applied_events_override=len(executed_journal),
        )
    )
    stamp_phase_a_manifest(
        manifest=prefix_artifacts.current_manifest,
        scenario=scenario,
        phase_a=phase_a,
    )
    augment_phase_b_outputs(prefix_artifacts.current_manifest, state)
    return dataclasses.replace(prefix_artifacts, journal=tuple(executed_journal))


def _build_final_replay_bundle(
    *,
    run_context: RunContext,
    artifacts: PlanArtifacts,
    executed_journal: list[JournalEntry],
    created_at: datetime,
    content_sources: list[ContentSourceEvidence],
):
    digest_entries = [
        entry.model_copy(update={"wall_clock_time": None}) for entry in executed_journal
    ]
    journal_digest = hashlib.sha256(serialize_journal_bytes(digest_entries)).hexdigest()
    bundle = build_replay_bundle(
        run_id=run_context.run_id,
        scenario_yaml_bytes=run_context.run_input.raw_bytes,
        plan_artifacts=artifacts,
        caps=run_context.caps,
        created_at=created_at,
        content_sources=content_sources,
        execution_mode=ExecutionMode.RUN,
    )
    return bundle.model_copy(
        update={
            "applied_events": len(executed_journal),
            "journal_digest": journal_digest,
        }
    )
