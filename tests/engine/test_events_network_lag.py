"""Tests for network_lag_start / network_lag_commit handlers."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.journal import (
    CommittedJournalEntry,
    JournalPhase,
    StartedJournalEntry,
)
from chaos_librarian.contract.scenario import (
    NetworkLagCommitEvent,
    NetworkLagEffect,
    NetworkLagStartEvent,
    RenameFileEvent,
    TimelineActionName,
)
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import build_initial_state
from chaos_librarian.errors import ChaosLibrarianValueError
from tests.engine.conftest import _build_minimal_scenario, _engine_event_context


def _scenario_state():
    scenario = _build_minimal_scenario(
        roots=[("movies-hd", "library/movies-hd")],
        works=[("work_001", "asset_hd_main", "mkv")],
    )
    return scenario, build_initial_state(scenario, IdAllocator(TraceRecorder()))


def _apply_rename_source(state) -> None:
    event = RenameFileEvent(
        id="rename_001",
        at="10s",
        target="asset_hd_main",
        to="movies-hd/renamed.mkv",
    )
    apply_event(
        state=state,
        resolved=ResolvedEvent(at_ns=10_000_000_000, declared_index=0, event=event),
        ids=IdAllocator(TraceRecorder()),
        ctx=_engine_event_context(),
    )


def _lag_start() -> NetworkLagStartEvent:
    return NetworkLagStartEvent(
        id="lag_start_001",
        at="10s",
        effect=NetworkLagEffect.DELAYED_RENAME,
        target="asset_hd_main",
        after="rename_001",
        duration="2s",
    )


def test_network_lag_start_emits_started_entry_with_path_timing_evidence() -> None:
    _scenario, state = _scenario_state()
    _apply_rename_source(state)

    entries = apply_event(
        state=state,
        resolved=ResolvedEvent(at_ns=10_000_000_000, declared_index=1, event=_lag_start()),
        ids=IdAllocator(TraceRecorder()),
        ctx=_engine_event_context(),
    )

    assert len(entries) == 1
    entry = entries[0]
    assert isinstance(entry, StartedJournalEntry)
    assert entry.phase == JournalPhase.STARTED
    assert entry.action == TimelineActionName.NETWORK_LAG_START
    assert entry.target_ids == ["asset_hd_main"]
    assert entry.temp_path == ".chaos-librarian/network-lag/lag_start_001"
    assert entry.state_delta == {
        "effect": "delayed_rename",
        "target_ref": "asset_hd_main",
        "after_event_id": "rename_001",
        "logical_start_ns": 10_000_000_000,
        "logical_commit_ns": 12_000_000_000,
        "requested_duration_ns": 2_000_000_000,
        "from_path": "library/movies-hd/asset_hd_main.mkv",
        "to_path": "movies-hd/renamed.mkv",
    }


def test_network_lag_commit_emits_committed_entry_with_matching_evidence() -> None:
    _scenario, state = _scenario_state()
    _apply_rename_source(state)
    apply_event(
        state=state,
        resolved=ResolvedEvent(at_ns=10_000_000_000, declared_index=1, event=_lag_start()),
        ids=IdAllocator(TraceRecorder()),
        ctx=_engine_event_context(),
    )
    commit = NetworkLagCommitEvent(
        id="lag_commit_001",
        at="12s",
        for_="lag_start_001",
    )

    entries = apply_event(
        state=state,
        resolved=ResolvedEvent(at_ns=12_000_000_000, declared_index=2, event=commit),
        ids=IdAllocator(TraceRecorder()),
        ctx=_engine_event_context(),
    )

    assert len(entries) == 1
    entry = entries[0]
    assert isinstance(entry, CommittedJournalEntry)
    assert entry.phase == JournalPhase.COMMITTED
    assert entry.action == TimelineActionName.NETWORK_LAG_COMMIT
    assert entry.related_event_id == "lag_start_001"
    assert entry.state_delta["effect"] == "delayed_rename"
    assert entry.state_delta["after_event_id"] == "rename_001"
    assert entry.state_delta["from_path"] == "library/movies-hd/asset_hd_main.mkv"
    assert entry.state_delta["to_path"] == "movies-hd/renamed.mkv"


def test_network_lag_start_requires_after_event_to_be_previous_event() -> None:
    _scenario, state = _scenario_state()
    _apply_rename_source(state)
    apply_event(
        state=state,
        resolved=ResolvedEvent(
            at_ns=11_000_000_000,
            declared_index=1,
            event=RenameFileEvent(
                id="rename_002",
                at="11s",
                target="asset_hd_main",
                to="movies-hd/second.mkv",
            ),
        ),
        ids=IdAllocator(TraceRecorder()),
        ctx=_engine_event_context(),
    )

    with pytest.raises(ChaosLibrarianValueError, match="must immediately follow"):
        apply_event(
            state=state,
            resolved=ResolvedEvent(at_ns=12_000_000_000, declared_index=2, event=_lag_start()),
            ids=IdAllocator(TraceRecorder()),
            ctx=_engine_event_context(),
        )
