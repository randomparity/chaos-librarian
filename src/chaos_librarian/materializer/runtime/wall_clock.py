"""Wall-clock materialize/run orchestrator."""

from __future__ import annotations

import dataclasses
import errno
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from chaos_librarian.clock import parse_duration
from chaos_librarian.contract.content_sources import ContentSourceEvidence
from chaos_librarian.contract.journal import CommittedJournalEntry, JournalEntry
from chaos_librarian.contract.materialization import (
    FilesystemAction,
    NetworkFsChaosAction,
    NetworkLagAction,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode
from chaos_librarian.contract.run_sentinel import RunSentinelState
from chaos_librarian.contract.scenario import (
    NetworkLagEffect,
    Scenario,
    TimelineActionName,
)
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.plan import PlanArtifacts, PlanExecutionRequest, run_materializer_plan
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.errors import ChaosLibrarianValueError
from chaos_librarian.materializer.content.synthesis import (
    PhaseAInputs,
    PhaseAResult,
    materialize_assets_phase_a,
    materialize_one_asset,
    stamp_phase_a_manifest,
)
from chaos_librarian.materializer.errors import (
    CorruptionActionError,
    FilesystemActionError,
    MaterializationWriteError,
    MediaActionError,
    TimelineUnsupportedError,
)
from chaos_librarian.materializer.persistence._context import (
    MaterializeArtifacts,
    RunContext,
)
from chaos_librarian.materializer.persistence.finalize import (
    build_sentinel,
    finalize_wall_clock_phase_b_failure,
    finalize_wall_clock_success,
)
from chaos_librarian.materializer.persistence.reports import (
    ReplayBundleAssemblyRequest,
    build_replay_bundle,
)
from chaos_librarian.materializer.persistence.writer import (
    WallClockBaselineMetadata,
    publish_wall_clock_baseline,
)
from chaos_librarian.materializer.phase_b.dispatch import (
    PhaseBState,
    PhaseBStateInputs,
    augment_phase_b_outputs,
    dispatch_phase_b_entry,
    make_phase_b_state,
)
from chaos_librarian.materializer.phase_b.filesystem import promote_slow_copy
from chaos_librarian.materializer.phase_b.report_actions import report_actions_from_phase_b
from chaos_librarian.materializer.preparation.run_setup import (
    MaterializerPreparationMode,
    prepare_materializer_run,
)
from chaos_librarian.materializer.runtime.network_fs_chaos import (
    CHAOS_CLOSE_ACTIONS,
    CHAOS_ENTRY_ACTIONS,
    NetworkFsChaosState,
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
from chaos_librarian.materializer.runtime.scheduler import (
    SpeedMultiplier,
    due_event_count,
    logical_now_ns,
    parse_speed,
)

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
class _DispatchState:
    phase_b: PhaseBState
    chaos: NetworkFsChaosState | None = None
    slow_copies: dict[str, WallClockSlowCopySession] = field(default_factory=dict)
    slow_copy_initial_paths: dict[str, str] = field(default_factory=dict)
    network_lag_starts_by_after: dict[str, JournalEntry] = field(default_factory=dict)
    network_lags: dict[str, WallClockNetworkLagSession] = field(default_factory=dict)
    deferred_network_lag_entries: dict[str, JournalEntry] = field(default_factory=dict)


@dataclass(slots=True)
class _WallClockExecutionResult:
    cursor: int
    state: _DispatchState
    executed_journal: list[JournalEntry]
    overran_duration: bool


@dataclass(slots=True)
class _WallClockExecutionContext:
    journal: tuple[JournalEntry, ...]
    logical_times_ns: tuple[int, ...]
    out_dir: Path
    start_wall_ns: int
    requested_duration_ns: int
    deadline_ns: int
    speed: SpeedMultiplier
    state: _DispatchState
    executed_journal: list[JournalEntry]
    commit_times: Mapping[str, int]


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
    """Run a scenario against wall-clock time and emit materialized artifacts.

    Raises:
        DurationParseError: ``duration`` is not valid duration syntax.
        SpeedParseError: ``speed`` is not valid speed multiplier syntax.
        WallClockUsageError: ``duration`` parses but is not greater than zero.
        ScenarioLoadError: ``scenario_path`` cannot be read or parsed.
        ScenarioValidationError: scenario fails semantic validation.
        TimelineUnsupportedError: a timeline event names an unsupported
            action or wall-clock slow-copy shape.
        UnsupportedMaterializationError: scenario declares media outside
            the materialization support matrix.
        CapabilityGateError: required materialization tooling or codec
            support is missing.
        ContainmentViolationError: a path escapes ``<out_dir>/library/``.
        ToolFailedError: ffmpeg or mkvtoolnix exited non-zero during
            synthesis.
        ProbeParseError: ffprobe output is malformed or missing required
            fields.
        MaterializationWriteError: run directory lifecycle metadata,
            report, publish, or cleanup writes failed.
        FilesystemActionError: a phase-B filesystem helper raised.
        MediaActionError: a phase-B media handler raised.
        CorruptionActionError: a phase-B corruption handler raised.
    """
    requested_duration_ns = _parse_positive_duration(duration)
    speed_multiplier = parse_speed(speed)
    started_at = _utc_now()
    prepared = prepare_materializer_run(
        scenario_path,
        mode=MaterializerPreparationMode.WALL_CLOCK,
        resolved_timeline_check=_preflight_wall_clock_slow_copies,
    )
    scenario = prepared.scenario

    staging_dir = _create_staging_dir(out_dir)
    baseline_artifacts = run_materializer_plan(
        PlanExecutionRequest(
            run_input=prepared.run_input,
            validation_report=prepared.validation_report,
            run_id_override=prepared.run_id,
            applied_events_override=0,
        )
    )
    phase_a = materialize_assets_phase_a(
        PhaseAInputs(
            scenario=scenario,
            out_dir=staging_dir,
            artifacts=baseline_artifacts,
            caps=prepared.caps,
            stamp_manifest=True,
            materialize_asset=materialize_one_asset,
        )
    )
    _publish_baseline(
        staging_dir=staging_dir,
        out_dir=out_dir,
        run_input=prepared.run_input,
        artifacts=baseline_artifacts,
        caps=prepared.caps,
        run_id=prepared.run_id,
        started_at=started_at,
        content_sources=phase_a.content_sources,
    )
    return _run_timed_phase(
        run_context=RunContext(
            run_input=prepared.run_input,
            out_dir=out_dir,
            run_id=prepared.run_id,
            started_at=started_at,
            caps=prepared.caps,
            plan_artifacts=prepared.plan_artifacts,
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
        cause = FileExistsError(
            errno.EEXIST,
            "refusing to write into existing directory",
            str(out_dir),
        )
        raise MaterializationWriteError(
            operation="begin_wall_clock_run",
            path=out_dir,
            cause=cause,
        ) from cause
    staging_dir = out_dir.parent / f".{out_dir.name}.staging"
    try:
        staging_dir.mkdir(parents=True)
        (staging_dir / "library").mkdir()
    except OSError as exc:
        raise MaterializationWriteError(
            operation="begin_wall_clock_run",
            path=staging_dir,
            cause=exc,
        ) from exc
    return staging_dir


def _preflight_wall_clock_slow_copies(resolved_timeline: list[ResolvedEvent]) -> None:
    for index, resolved in enumerate(resolved_timeline):
        action = resolved.event.action
        if action is not TimelineActionName.SLOW_COPY_START:
            continue
        next_index = index + 1
        if next_index >= len(resolved_timeline):
            _raise_slow_copy_unsupported(resolved.event.id)
        next_event = resolved_timeline[next_index].event
        if next_event.action is not TimelineActionName.SLOW_COPY_COMMIT:
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
    ctx = RunContext(
        run_input=run_input,
        out_dir=out_dir,
        run_id=run_id,
        started_at=started_at,
        caps=caps,
        plan_artifacts=artifacts,
    )
    replay_bundle = build_replay_bundle(
        ReplayBundleAssemblyRequest(
            run_context=ctx,
            plan_artifacts=artifacts,
            created_at=started_at,
            content_sources=content_sources,
            execution_mode=ExecutionMode.RUN,
        )
    )
    try:
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
    except OSError as exc:
        raise MaterializationWriteError(
            operation="publish_wall_clock_baseline",
            path=out_dir,
            cause=exc,
        ) from exc


def _run_timed_phase(
    *,
    run_context: RunContext,
    scenario: Scenario,
    phase_a: PhaseAResult,
    requested_duration_ns: int,
    speed: SpeedMultiplier,
) -> MaterializeArtifacts:
    start_wall_ns = _monotonic_ns()
    state = _make_dispatch_state(run_context, scenario, phase_a.invocations)
    executed_journal: list[JournalEntry] = []

    try:
        execution_context = _wall_clock_execution_context(
            run_context=run_context,
            start_wall_ns=start_wall_ns,
            requested_duration_ns=requested_duration_ns,
            speed=speed,
            state=state,
            executed_journal=executed_journal,
        )
        execution = _execute_wall_clock_journal(execution_context)
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
    actual_duration_ns = max(0, _monotonic_ns() - start_wall_ns)
    overran_duration = execution.overran_duration or actual_duration_ns > requested_duration_ns
    try:
        return _finalize_wall_clock_run(
            run_context=run_context,
            scenario=scenario,
            phase_a=phase_a,
            state=execution.state,
            executed_journal=execution.executed_journal,
            requested_duration_ns=requested_duration_ns,
            actual_duration_ns=actual_duration_ns,
            speed=speed,
            overran_duration=overran_duration,
        )
    except (FilesystemActionError, MediaActionError, CorruptionActionError) as exc:
        _finalize_wall_clock_phase_b_failure(
            run_context=run_context,
            scenario=scenario,
            phase_a=phase_a,
            state=execution.state,
            executed_journal=execution.executed_journal,
            requested_duration_ns=requested_duration_ns,
            actual_duration_ns=actual_duration_ns,
            speed=speed,
            overran_duration=overran_duration,
            exc=exc,
        )
        raise


def _wall_clock_execution_context(
    *,
    run_context: RunContext,
    start_wall_ns: int,
    requested_duration_ns: int,
    speed: SpeedMultiplier,
    state: _DispatchState,
    executed_journal: list[JournalEntry],
) -> _WallClockExecutionContext:
    journal = run_context.plan_artifacts.journal
    _configure_network_lag_schedule(state, journal)
    return _WallClockExecutionContext(
        journal=journal,
        logical_times_ns=tuple(entry.logical_time_ns for entry in journal),
        out_dir=run_context.out_dir,
        start_wall_ns=start_wall_ns,
        requested_duration_ns=requested_duration_ns,
        deadline_ns=start_wall_ns + requested_duration_ns,
        speed=speed,
        state=state,
        executed_journal=executed_journal,
        commit_times=_slow_copy_commit_times(journal),
    )


def _execute_wall_clock_journal(
    context: _WallClockExecutionContext,
) -> _WallClockExecutionResult:
    cursor = 0
    overran_duration = False

    while cursor < len(context.journal):
        now_ns = _monotonic_ns()
        logical_ns = logical_now_ns(now_ns - context.start_wall_ns, context.speed)
        _grow_active_slow_copies(
            context.out_dir / "library",
            context.state.slow_copies,
            logical_ns=logical_ns,
        )
        if now_ns >= context.deadline_ns:
            break
        due_count = due_event_count(
            context.logical_times_ns,
            logical_ns=logical_ns,
            cursor=cursor,
        )
        if due_count == 0:
            wake_ns = _next_wake_ns(context, context.journal[cursor])
            if context.state.slow_copies:
                wake_ns = min(wake_ns, now_ns + _SLOW_COPY_POLL_INTERVAL_NS)
            _sleep_until(wake_ns)
            continue
        for _ in range(due_count):
            if _monotonic_ns() >= context.deadline_ns:
                break
            cursor = _execute_and_record(
                context=context,
                cursor=cursor,
            )
    if context.state.slow_copies:
        cursor = _finish_active_slow_copies(
            context=context,
            cursor=cursor,
        )
        overran_duration = True
    if context.state.network_lags:
        cursor = _finish_active_network_lags(
            context=context,
            cursor=cursor,
        )
        overran_duration = True
    if cursor >= len(context.journal):
        _sleep_until(context.deadline_ns)
    return _WallClockExecutionResult(
        cursor=cursor,
        state=context.state,
        executed_journal=context.executed_journal,
        overran_duration=overran_duration,
    )


def _make_dispatch_state(
    run_context: RunContext,
    scenario: Scenario,
    invocations: list[ToolInvocation],
) -> _DispatchState:
    library_root = run_context.out_dir / "library"
    return _DispatchState(
        phase_b=make_phase_b_state(
            PhaseBStateInputs(
                library_root=library_root,
                scenario=scenario,
                resolved_seed=run_context.plan_artifacts.replay_bundle.resolved_seed,
                ffmpeg_version=run_context.caps.ffmpeg.version or "unknown",
                ffprobe_version=run_context.caps.ffprobe.version or "unknown",
                invocations=invocations,
                manifest=run_context.plan_artifacts.current_manifest,
                initial_manifest=run_context.plan_artifacts.initial_manifest,
            )
        ),
        chaos=NetworkFsChaosState(library_root=library_root),
    )


def _next_wake_ns(context: _WallClockExecutionContext, next_entry: JournalEntry) -> int:
    return min(context.deadline_ns, _entry_due_wall_ns(context, next_entry))


def _entry_due_wall_ns(
    context: _WallClockExecutionContext,
    next_entry: JournalEntry,
) -> int:
    logical_delta = max(0, next_entry.logical_time_ns)
    wall_offset = logical_delta * context.speed.denominator // context.speed.numerator
    if logical_delta * context.speed.denominator % context.speed.numerator:
        wall_offset += 1
    return context.start_wall_ns + wall_offset


def _execute_and_record(
    *,
    context: _WallClockExecutionContext,
    cursor: int,
) -> int:
    entry = context.journal[cursor]
    _execute_entry(context.state, entry, context.commit_times)
    executed = entry.model_copy(update={"wall_clock_time": _utc_now()})
    _append_journal_entry(context.out_dir / "journal.jsonl", executed)
    context.executed_journal.append(executed)
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
        state.phase_b.filesystem_actions.append(
            _wall_clock_slow_copy_start(state, entry, commit_times)
        )
        return
    if action is TimelineActionName.SLOW_COPY_COMMIT:
        state.phase_b.filesystem_actions.append(_wall_clock_slow_copy_commit(state, entry))
        return
    if action is TimelineActionName.NETWORK_LAG_START:
        _wall_clock_network_lag_start(state, entry)
        return
    if action is TimelineActionName.NETWORK_LAG_COMMIT:
        state.phase_b.network_lag_actions.append(_wall_clock_network_lag_commit(state, entry))
        return
    if _dispatch_chaos_entry(state, entry, action):
        return
    dispatch_phase_b_entry(state.phase_b, entry)


def _dispatch_chaos_entry(
    state: _DispatchState, entry: JournalEntry, action: TimelineActionName
) -> bool:
    """Route a network-fs-chaos entry; return whether it was handled."""
    if action in CHAOS_CLOSE_ACTIONS:
        with _wall_clock_filesystem_effect(
            operation="network_fs_chaos",
            event_id=entry.event_id,
            action=action,
            asset_id=_entry_asset_id(entry),
        ):
            realize_chaos_close(_chaos_state(state), entry)
        return True
    if action in CHAOS_ENTRY_ACTIONS:
        with _wall_clock_filesystem_effect(
            operation="network_fs_chaos",
            event_id=entry.event_id,
            action=action,
            asset_id=_entry_asset_id(entry),
        ):
            realize_chaos_entry(_chaos_state(state), entry)
        return True
    return False


def _chaos_state(state: _DispatchState) -> NetworkFsChaosState:
    if state.chaos is None:  # pragma: no cover - always set in _make_dispatch_state
        raise ChaosLibrarianValueError("network-fs-chaos state not initialized")
    return state.chaos


def _chaos_actions(state: _DispatchState) -> list[NetworkFsChaosAction]:
    return list(state.chaos.actions) if state.chaos is not None else []


def _restore_chaos_action(state: _DispatchState) -> NetworkFsChaosAction:
    if state.chaos is not None:
        for action in reversed(state.chaos.actions):
            if action.enforced:
                return action
    raise ChaosLibrarianValueError("network-fs-chaos restore has no enforced action")


def _chaos_target_asset_id(state: _DispatchState, target_ref: str) -> str | None:
    return target_ref if target_ref in state.phase_b.fs_ctx.scenario_assets else None


def _restore_chaos(state: _DispatchState) -> None:
    chaos = state.chaos
    if chaos is None or not chaos.captured_modes:
        return
    action = _restore_chaos_action(state)
    try:
        with _wall_clock_filesystem_effect(
            operation="network_fs_chaos_restore",
            event_id=action.event_id,
            action=action.action,
            asset_id=_chaos_target_asset_id(state, action.target_ref),
        ):
            restore_chaos_modes(chaos)
    except FilesystemActionError:
        chaos.captured_modes.clear()
        raise


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
    with _wall_clock_filesystem_effect(
        operation="slow_copy_start",
        event_id=entry.event_id,
        action=TimelineActionName.SLOW_COPY_START,
        asset_id=_entry_asset_id(entry),
    ):
        asset_id = _required_entry_asset_id(entry)
        initial_path = str(entry.state_delta["initial_path_at_start"])
        temp_path = str(entry.state_delta["temp_path"])
        final_path = str(entry.state_delta["final_path"])
        src = state.phase_b.fs_ctx.library_root / initial_path
        dst = state.phase_b.fs_ctx.library_root / temp_path
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
    with _wall_clock_filesystem_effect(
        operation="slow_copy_commit",
        event_id=entry.event_id,
        action=TimelineActionName.SLOW_COPY_COMMIT,
        asset_id=_entry_asset_id(entry),
    ):
        session = state.slow_copies.pop(entry.related_event_id)
        initial_path = state.slow_copy_initial_paths.pop(entry.related_event_id)
        temp = state.phase_b.fs_ctx.library_root / session.temp_path
        temp.parent.mkdir(parents=True, exist_ok=True)
        temp.write_bytes(session.source_bytes)
        promote_slow_copy(
            library_root=state.phase_b.fs_ctx.library_root,
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
        dispatch_phase_b_entry(state.phase_b, deferred)
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


@contextmanager
def _wall_clock_filesystem_effect(
    *,
    operation: str,
    event_id: str,
    action: TimelineActionName,
    asset_id: str | None,
) -> Iterator[None]:
    try:
        yield
    except FilesystemActionError:
        raise
    except Exception as exc:
        raise FilesystemActionError(
            f"{operation} failed for event {event_id}: {exc}",
            event_id=event_id,
            action=action,
            asset_id=asset_id,
            cause=exc,
            payload={"operation": operation},
        ) from exc


def _entry_asset_id(entry: JournalEntry) -> str | None:
    return entry.target_ids[0] if entry.target_ids else None


def _required_entry_asset_id(entry: JournalEntry) -> str:
    asset_id = _entry_asset_id(entry)
    if asset_id is None:
        raise ChaosLibrarianValueError(f"{entry.event_id}: filesystem event has no target asset")
    return asset_id


def _finish_active_slow_copies(
    *,
    context: _WallClockExecutionContext,
    cursor: int,
) -> int:
    while cursor < len(context.journal):
        entry = context.journal[cursor]
        action = TimelineActionName(entry.action)
        if action is not TimelineActionName.SLOW_COPY_COMMIT:
            break
        if not isinstance(entry, CommittedJournalEntry):
            raise ChaosLibrarianValueError(f"{entry.event_id} is not a committed slow_copy entry")
        if entry.related_event_id not in context.state.slow_copies:
            break
        _sleep_until(_entry_due_wall_ns(context, entry))
        logical_ns = logical_now_ns(
            _monotonic_ns() - context.start_wall_ns,
            context.speed,
        )
        _grow_active_slow_copies(
            context.out_dir / "library",
            context.state.slow_copies,
            logical_ns=logical_ns,
        )
        cursor = _execute_and_record(
            context=context,
            cursor=cursor,
        )
    return cursor


def _finish_active_network_lags(
    *,
    context: _WallClockExecutionContext,
    cursor: int,
) -> int:
    while cursor < len(context.journal) and context.state.network_lags:
        entry = context.journal[cursor]
        _sleep_until(_entry_due_wall_ns(context, entry))
        cursor = _execute_and_record(
            context=context,
            cursor=cursor,
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
        with _wall_clock_filesystem_effect(
            operation="slow_copy_growth",
            event_id=session.start_event_id,
            action=TimelineActionName.SLOW_COPY_START,
            asset_id=session.asset_id,
        ):
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
    network_fs_chaos_actions = _chaos_actions(state)
    _restore_chaos(state)
    return finalize_wall_clock_success(
        run_context,
        final_artifacts,
        executed_journal=executed_journal,
        invocations=state.phase_b.media_ctx.invocations,
        materialized=phase_a.materialized_assets,
        actions=report_actions_from_phase_b(
            state.phase_b,
            network_fs_chaos_actions=network_fs_chaos_actions,
        ),
        requested_duration_ns=requested_duration_ns,
        actual_duration_ns=actual_duration_ns,
        speed_multiplier=speed.normalized,
        overran_duration=overran_duration,
        content_sources=phase_a.content_sources,
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
    network_fs_chaos_actions = _chaos_actions(state)
    _restore_chaos(state)
    finalize_wall_clock_phase_b_failure(
        run_context,
        final_artifacts,
        exc,
        executed_journal=executed_journal,
        invocations=state.phase_b.media_ctx.invocations,
        materialized=phase_a.materialized_assets,
        actions=report_actions_from_phase_b(
            state.phase_b,
            network_fs_chaos_actions=network_fs_chaos_actions,
        ),
        requested_duration_ns=requested_duration_ns,
        actual_duration_ns=actual_duration_ns,
        speed_multiplier=speed.normalized,
        overran_duration=overran_duration,
        content_sources=phase_a.content_sources,
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
    augment_phase_b_outputs(prefix_artifacts.current_manifest, state.phase_b)
    return dataclasses.replace(prefix_artifacts, journal=tuple(executed_journal))
