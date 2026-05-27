"""Tests for slow_copy_start / slow_copy_commit handlers."""

from __future__ import annotations

import uuid

import pytest

from chaos_librarian.contract.journal import (
    CommittedJournalEntry,
    JournalPhase,
    StartedJournalEntry,
)
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state
from tests.engine.conftest import _engine_event_context

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _scenario() -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 18,
            "scenario_id": "sc",
            "seed": 7,
            "duration_scale": "short",
            "library": {
                "roots": [
                    {"id": "staging", "path": "staging"},
                    {"id": "movies_hd", "path": "movies-hd"},
                ]
            },
            "movies": [
                {
                    "id": "movie_0",
                    "title": "T",
                    "layout": "movie_flat",
                    "variants": [
                        {
                            "id": "v0",
                            "label": "hd",
                            "bundle": {
                                "id": "b0",
                                "assets": [
                                    {
                                        "id": "a0",
                                        "role": "primary_video",
                                        "container": "mkv",
                                        "duration_seconds": 1,
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
            "series": [],
            "artists": [],
            "timeline": [
                {
                    "id": "copy_start_001",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a0",
                    "to": "movies-hd/Nova.mkv",
                    "temp_path": "movies-hd/Nova.mkv.part",
                    "duration": "3s",
                },
                {
                    "id": "copy_commit_001",
                    "at": "4s",
                    "action": "slow_copy_commit",
                    "for": "copy_start_001",
                },
            ],
        }
    )


class TestSlowCopyStart:
    """slow_copy_start stages a temp_path on the asset's location.

    WHY: watchers must be able to observe partial files in-flight; the
    journal records the temp path so the test harness knows what to look
    for.
    """

    def test_started_entry_carries_temp_path(self) -> None:
        scenario = _scenario()
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        start_event, _ = resolve_timeline(scenario)
        (entry,) = apply_event(state, start_event, ids, _engine_event_context("sc", run_id=_RUN_ID))
        assert isinstance(entry, StartedJournalEntry)
        assert entry.phase == JournalPhase.STARTED
        assert entry.temp_path == "movies-hd/Nova.mkv.part"
        assert entry.state_delta == {
            "final_path": "movies-hd/Nova.mkv",
            "temp_path": "movies-hd/Nova.mkv.part",
            "initial_path_at_start": "staging/T - hd.mkv",
        }
        loc = state.locations[state.location_id_for_asset("a0")]
        assert loc.temp_path == "movies-hd/Nova.mkv.part"


class TestSlowCopyCommit:
    """slow_copy_commit promotes temp_path to final path.

    WHY: the commit is what makes the file observable as fully copied; the
    journal's CommittedJournalEntry is the oracle anchor for that moment.
    """

    def test_commit_clears_temp_and_sets_final_path(self) -> None:
        scenario = _scenario()
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        resolved = resolve_timeline(scenario)
        entries: tuple[object, ...] = ()
        for r in resolved:
            entries = apply_event(state, r, ids, _engine_event_context("sc", run_id=_RUN_ID))
        (commit_entry,) = entries
        assert isinstance(commit_entry, CommittedJournalEntry)
        assert commit_entry.phase == JournalPhase.COMMITTED
        assert commit_entry.related_event_id == "copy_start_001"
        loc = state.locations[state.location_id_for_asset("a0")]
        assert loc.temp_path is None
        assert loc.path == "movies-hd/Nova.mkv"
        assert state.pending_slow_copies == {}


class TestSlowCopyCommitAfterDeleteCrashes:
    """Engine crashes if slow_copy_commit runs after the asset was deleted.

    WHY: encodes the necessity of the E_LIFECYCLE_INVALID rule that flags
    ``delete_file`` on an asset with a pending slow_copy. ``slow_copy_commit``
    looks up the staged location id in ``state.locations``; if ``delete_file``
    has popped it, the commit handler raises ``KeyError``. If this test
    stops raising, the engine has gained a defensive branch and the rule's
    necessity needs to be re-evaluated.
    """

    def test_commit_after_delete_raises_keyerror(self) -> None:
        scenario = _scenario()
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        start_event, commit_event = resolve_timeline(scenario)

        apply_event(state, start_event, ids, _engine_event_context("sc", run_id=_RUN_ID))
        assert "copy_start_001" in state.pending_slow_copies

        # Hand-build a delete: scenario.Scenario.model_validate would reject
        # the mixed timeline if we tried to put delete + commit in one
        # scenario, so we manually mutate state to mirror what a missing
        # lifecycle rule would let the engine reach.
        state.unbind_location("a0")

        with pytest.raises(KeyError):
            apply_event(state, commit_event, ids, _engine_event_context("sc", run_id=_RUN_ID))
