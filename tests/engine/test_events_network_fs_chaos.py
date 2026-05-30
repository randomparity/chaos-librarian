"""Tests for the network-fs-chaos engine handlers."""

from __future__ import annotations

from chaos_librarian.contract.journal import (
    AtomicJournalEntry,
    CommittedJournalEntry,
    StartedJournalEntry,
)
from chaos_librarian.contract.scenario import (
    AcquireLockEvent,
    ChangePermissionsEvent,
    LockType,
    ReadonlyState,
    ReleaseLockEvent,
    RemountPathEvent,
    SimulateQuotaExceededEvent,
    SimulateStaleHandleEvent,
    TimelineActionName,
    ToggleReadonlyEvent,
    UnmountPathEvent,
)
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import build_initial_state
from tests.engine.conftest import _build_minimal_scenario, _engine_event_context


def _scenario_state():
    scenario = _build_minimal_scenario(
        roots=[("movies-hd", "library/movies-hd")],
        movies=[("movie_001", "asset_hd_main", "mkv")],
    )
    return scenario, build_initial_state(scenario, IdAllocator(TraceRecorder()))


def _apply(state, event, at_ns: int, declared_index: int):
    return apply_event(
        state=state,
        resolved=ResolvedEvent(at_ns=at_ns, declared_index=declared_index, event=event),
        ids=IdAllocator(TraceRecorder()),
        ctx=_engine_event_context(),
    )


def test_change_permissions_emits_atomic_entry() -> None:
    _scenario, state = _scenario_state()
    event = ChangePermissionsEvent(id="chmod_1", at="1s", target="asset_hd_main", mode="000")

    (entry,) = _apply(state, event, 1_000_000_000, 0)

    assert isinstance(entry, AtomicJournalEntry)
    assert entry.action == TimelineActionName.CHANGE_PERMISSIONS
    assert entry.target_ids == ["asset_hd_main"]
    assert entry.state_delta == {
        "target_ref": "asset_hd_main",
        "condition": "eacces",
        "mode": "000",
    }


def test_simulate_quota_exceeded_records_enospc() -> None:
    _scenario, state = _scenario_state()
    event = SimulateQuotaExceededEvent(id="quota_1", at="1s", target="asset_hd_main")

    (entry,) = _apply(state, event, 1_000_000_000, 0)

    assert isinstance(entry, AtomicJournalEntry)
    assert entry.state_delta["condition"] == "enospc"


def test_toggle_readonly_records_readonly_state() -> None:
    _scenario, state = _scenario_state()
    event = ToggleReadonlyEvent(
        id="ro_1", at="1s", target="asset_hd_main", mode=ReadonlyState.READONLY
    )

    (entry,) = _apply(state, event, 1_000_000_000, 0)

    assert entry.state_delta["condition"] == "eacces"
    assert entry.state_delta["readonly_state"] == "readonly"


def test_simulate_stale_handle_records_estale() -> None:
    _scenario, state = _scenario_state()
    event = SimulateStaleHandleEvent(id="stale_1", at="1s", target="asset_hd_main")

    (entry,) = _apply(state, event, 1_000_000_000, 0)

    assert entry.state_delta["condition"] == "estale"


def test_change_permissions_subtree_path_target_has_no_asset_id() -> None:
    _scenario, state = _scenario_state()
    event = ChangePermissionsEvent(id="chmod_1", at="1s", target="movies-hd/sub", mode="444")

    (entry,) = _apply(state, event, 1_000_000_000, 0)

    assert entry.target_ids == []
    assert entry.state_delta["target_ref"] == "movies-hd/sub"


def test_acquire_release_lock_lifecycle() -> None:
    _scenario, state = _scenario_state()
    acquire = AcquireLockEvent(
        id="acq_1", at="1s", target="asset_hd_main", lock_type=LockType.EXCLUSIVE
    )

    (open_entry,) = _apply(state, acquire, 1_000_000_000, 0)

    assert isinstance(open_entry, StartedJournalEntry)
    assert open_entry.action == TimelineActionName.ACQUIRE_LOCK
    assert open_entry.state_delta["lock_type"] == "exclusive"
    assert "acq_1" in state.pending_locks

    release = ReleaseLockEvent.model_validate(
        {"id": "rel_1", "at": "2s", "action": "release_lock", "for": "acq_1"}
    )
    (close_entry,) = _apply(state, release, 2_000_000_000, 1)

    assert isinstance(close_entry, CommittedJournalEntry)
    assert close_entry.action == TimelineActionName.RELEASE_LOCK
    assert close_entry.related_event_id == "acq_1"
    assert close_entry.target_ids == ["asset_hd_main"]
    assert "acq_1" not in state.pending_locks


def test_unmount_remount_lifecycle() -> None:
    _scenario, state = _scenario_state()
    unmount = UnmountPathEvent(id="um_1", at="1s", target="asset_hd_main")

    (open_entry,) = _apply(state, unmount, 1_000_000_000, 0)

    assert isinstance(open_entry, StartedJournalEntry)
    assert open_entry.state_delta["condition"] == "unavailable"
    assert "um_1" in state.pending_unmounts

    remount = RemountPathEvent.model_validate(
        {"id": "rm_1", "at": "2s", "action": "remount_path", "for": "um_1"}
    )
    (close_entry,) = _apply(state, remount, 2_000_000_000, 1)

    assert isinstance(close_entry, CommittedJournalEntry)
    assert close_entry.related_event_id == "um_1"
    assert "um_1" not in state.pending_unmounts
