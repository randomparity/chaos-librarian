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
from chaos_librarian.contract.journal import CommittedJournalEntry, JournalEntry
from chaos_librarian.contract.manifest import Manifest, ProbedMedia
from chaos_librarian.contract.materialization import (
    FilesystemAction,
    MaterializationExecutionMode,
    MaterializedAsset,
    Outcome,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import ExecutionMode
from chaos_librarian.contract.run_sentinel import RunSentinelState
from chaos_librarian.contract.scenario import (
    CreateSidecarEvent,
    Scenario,
    SidecarKind,
    TimelineActionName,
)
from chaos_librarian.engine import PlanArtifacts, run_plan
from chaos_librarian.engine.journal_io import serialize_journal_bytes
from chaos_librarian.engine.resolution import ResolvedEvent, resolve_timeline
from chaos_librarian.errors import ChaosLibrarianValueError
from chaos_librarian.materializer._context import MaterializeArtifacts, RunContext
from chaos_librarian.materializer.capabilities import (
    assert_capable_for_static_materialize,
    detect_capabilities,
)
from chaos_librarian.materializer.errors import (
    CorruptionActionError,
    FilesystemActionError,
    MediaActionError,
    ScenarioValidationError,
    TimelineUnsupportedError,
)
from chaos_librarian.materializer.finalize import build_sentinel
from chaos_librarian.materializer.manifest_build import (
    augment_manifest,
)
from chaos_librarian.materializer.phase_b import (
    PhaseBState,
    augment_phase_b_outputs,
    dispatch_phase_b_entry,
    make_phase_b_state,
    phase_b_failure_outcome,
    phase_b_failure_record,
)
from chaos_librarian.materializer.preflight import (
    iter_assets,
    preflight_asset,
    preflight_timeline,
)
from chaos_librarian.materializer.reports import (
    build_metadata,
    build_replay_bundle,
    build_report,
    build_reports,
)
from chaos_librarian.materializer.scheduler import (
    SpeedMultiplier,
    due_event_count,
    logical_now_ns,
    parse_speed,
)
from chaos_librarian.materializer.synthesis import materialize_one_asset
from chaos_librarian.materializer.writer import (
    WallClockBaselineMetadata,
    cleanup_failed_phase_b_run,
    finalize_materialize_run,
    publish_wall_clock_baseline,
)
from chaos_librarian.validation import run_validation
from chaos_librarian.validation.input import prepare_run_input

__all__ = [
    "WallClockSlowCopySession",
    "WallClockUsageError",
    "run_wall_clock_scenario",
]


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
class _PhaseAResult:
    invocations: list[ToolInvocation] = field(default_factory=list)
    materialized: list[MaterializedAsset] = field(default_factory=list)
    probed_by_asset: dict[str, ProbedMedia] = field(default_factory=dict)
    sidecar_hashes_by_asset: dict[str, dict[tuple[str, str], str]] = field(default_factory=dict)


@dataclass(slots=True)
class _DispatchState(PhaseBState):
    slow_copies: dict[str, WallClockSlowCopySession] = field(default_factory=dict)
    slow_copy_initial_paths: dict[str, str] = field(default_factory=dict)


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
    preflight_timeline(scenario)
    resolved_timeline = resolve_timeline(scenario)
    _preflight_wall_clock_slow_copies(resolved_timeline)
    caps = detect_capabilities()
    assert_capable_for_static_materialize(caps)
    run_id = uuid.uuid4()
    full_artifacts = run_plan(
        run_input=run_input,
        validation_report=validation_report,
        run_id_override=run_id,
    )
    for asset in iter_assets(scenario):
        preflight_asset(asset.video, asset.audio, asset.subtitles, asset.container)

    staging_dir = _create_staging_dir(out_dir)
    baseline_artifacts = run_plan(
        run_input=run_input,
        validation_report=validation_report,
        run_id_override=run_id,
        applied_events_override=0,
    )
    phase_a = _synthesize_phase_a(
        scenario=scenario,
        out_dir=staging_dir,
        artifacts=baseline_artifacts,
        caps=caps,
    )
    _publish_baseline(
        staging_dir=staging_dir,
        out_dir=out_dir,
        run_input=run_input,
        artifacts=baseline_artifacts,
        caps=caps,
        run_id=run_id,
        started_at=started_at,
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


def _synthesize_phase_a(
    *,
    scenario: Scenario,
    out_dir: Path,
    artifacts: PlanArtifacts,
    caps,
) -> _PhaseAResult:
    result = _PhaseAResult()
    primary_root_path = scenario.library.roots[0].path
    skip_by_asset = _timeline_sidecar_languages(scenario)
    for invocation_index, asset in enumerate(iter_assets(scenario)):
        skip_languages = skip_by_asset.get(asset.id, frozenset())
        invocation, materialized, probed, sidecar_hashes = materialize_one_asset(
            asset,
            artifacts.replay_bundle.resolved_seed,
            out_dir,
            caps,
            invocation_index,
            root_path=primary_root_path,
            skip_languages=skip_languages,
        )
        result.invocations.append(invocation)
        result.materialized.append(materialized)
        result.probed_by_asset[asset.id] = probed
        result.sidecar_hashes_by_asset[asset.id] = sidecar_hashes
    _stamp_phase_a_metadata(artifacts.current_manifest, scenario, result)
    return result


def _stamp_phase_a_metadata(
    manifest: Manifest,
    scenario: Scenario,
    phase_a: _PhaseAResult,
) -> None:
    by_asset = {record.asset_id: record for record in phase_a.materialized}
    skip_by_asset = _timeline_sidecar_languages(scenario)
    for asset in iter_assets(scenario):
        materialized = by_asset.get(asset.id)
        probed = phase_a.probed_by_asset.get(asset.id)
        if materialized is None or probed is None:
            continue
        augment_manifest(
            manifest,
            asset,
            materialized,
            probed,
            phase_a.sidecar_hashes_by_asset.get(asset.id, {}),
            skip_languages=skip_by_asset.get(asset.id, frozenset()),
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
) -> None:
    replay_bundle = build_replay_bundle(
        run_id=run_id,
        scenario_yaml_bytes=run_input.raw_bytes,
        plan_artifacts=artifacts,
        caps=caps,
        created_at=started_at,
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
    phase_a: _PhaseAResult,
    requested_duration_ns: int,
    speed: SpeedMultiplier,
) -> MaterializeArtifacts:
    start_wall_ns = _monotonic_ns()
    deadline_ns = start_wall_ns + requested_duration_ns
    state = _make_dispatch_state(run_context, scenario, phase_a.invocations)
    executed_journal: list[JournalEntry] = []
    cursor = 0
    journal = run_context.plan_artifacts.journal
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
                _sleep_until(_next_wake_ns(start_wall_ns, deadline_ns, journal[cursor], speed))
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
        library_root=run_context.out_dir / "library",
        scenario=scenario,
        resolved_seed=run_context.plan_artifacts.replay_bundle.resolved_seed,
        ffmpeg_version=run_context.caps.ffmpeg.version or "unknown",
        ffprobe_version=run_context.caps.ffprobe.version or "unknown",
        invocations=invocations,
        manifest=run_context.plan_artifacts.current_manifest,
    )
    return _DispatchState(
        fs_ctx=state.fs_ctx,
        media_ctx=state.media_ctx,
        corruption_ctx=state.corruption_ctx,
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
    action = TimelineActionName(entry.action)
    if action is TimelineActionName.SLOW_COPY_START:
        state.filesystem_actions.append(_wall_clock_slow_copy_start(state, entry, commit_times))
        return
    if action is TimelineActionName.SLOW_COPY_COMMIT:
        state.filesystem_actions.append(_wall_clock_slow_copy_commit(state, entry))
        return
    dispatch_phase_b_entry(state, entry)


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
    assert isinstance(entry, CommittedJournalEntry)
    session = state.slow_copies.pop(entry.related_event_id)
    initial_path = state.slow_copy_initial_paths.pop(entry.related_event_id)
    temp = state.fs_ctx.library_root / session.temp_path
    temp.parent.mkdir(parents=True, exist_ok=True)
    temp.write_bytes(session.source_bytes)
    if initial_path != session.final_path:
        (state.fs_ctx.library_root / initial_path).unlink(missing_ok=True)
    final = state.fs_ctx.library_root / session.final_path
    final.parent.mkdir(parents=True, exist_ok=True)
    temp.replace(final)
    return FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.SLOW_COPY_COMMIT,
        target_asset_id=session.asset_id,
        from_path=session.temp_path,
        to_path=session.final_path,
        temp_path=None,
        duration_ns=0,
    )


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
        assert isinstance(entry, CommittedJournalEntry)
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


def _append_journal_entry(path: Path, entry: JournalEntry) -> None:
    with path.open("ab") as handle:
        handle.write(serialize_journal_bytes((entry,)))


def _slow_copy_commit_times(journal: tuple[JournalEntry, ...]) -> dict[str, int]:
    times: dict[str, int] = {}
    for entry in journal:
        if TimelineActionName(entry.action) is not TimelineActionName.SLOW_COPY_COMMIT:
            continue
        assert isinstance(entry, CommittedJournalEntry)
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
    phase_a: _PhaseAResult,
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
        materialized=phase_a.materialized,
        failures=[],
        filesystem_actions=state.filesystem_actions,
        media_actions=state.media_actions,
        corruption_actions=state.corruption_actions,
        requested_duration_ns=requested_duration_ns,
        actual_duration_ns=actual_duration_ns,
        speed_multiplier=speed.normalized,
        overran_duration=overran_duration,
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay_bundle = _build_final_replay_bundle(
        run_context=run_context,
        artifacts=final_artifacts,
        executed_journal=executed_journal,
        created_at=finished_at,
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
    phase_a: _PhaseAResult,
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
        materialized=phase_a.materialized,
        failures=[phase_b_failure_record(exc)],
        filesystem_actions=state.filesystem_actions,
        media_actions=state.media_actions,
        corruption_actions=state.corruption_actions,
        requested_duration_ns=requested_duration_ns,
        actual_duration_ns=actual_duration_ns,
        speed_multiplier=speed.normalized,
        overran_duration=overran_duration,
        execution_mode=MaterializationExecutionMode.RUN,
    )
    replay_bundle = _build_final_replay_bundle(
        run_context=run_context,
        artifacts=final_artifacts,
        executed_journal=executed_journal,
        created_at=finished_at,
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
    phase_a: _PhaseAResult,
    state: _DispatchState,
    executed_journal: list[JournalEntry],
) -> PlanArtifacts:
    prefix_artifacts = run_plan(
        run_input=run_context.run_input,
        validation_report=run_context.plan_artifacts.validation_report,
        resolved_seed_override=run_context.plan_artifacts.replay_bundle.resolved_seed,
        run_id_override=run_context.run_id,
        applied_events_override=len(executed_journal),
    )
    _stamp_phase_a_metadata(prefix_artifacts.current_manifest, scenario, phase_a)
    augment_phase_b_outputs(prefix_artifacts.current_manifest, state)
    return dataclasses.replace(prefix_artifacts, journal=tuple(executed_journal))


def _build_final_replay_bundle(
    *,
    run_context: RunContext,
    artifacts: PlanArtifacts,
    executed_journal: list[JournalEntry],
    created_at: datetime,
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
        execution_mode=ExecutionMode.RUN,
    )
    return bundle.model_copy(
        update={
            "applied_events": len(executed_journal),
            "journal_digest": journal_digest,
        }
    )


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
