"""Tests for slow_copy_start / slow_copy_commit handlers."""

from __future__ import annotations

import uuid

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

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _scenario() -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 1,
            "scenario_id": "sc",
            "seed": 7,
            "duration_scale": "short",
            "library": {
                "roots": [
                    {"id": "staging", "path": "staging"},
                    {"id": "movies_hd", "path": "movies-hd"},
                ]
            },
            "works": [
                {
                    "id": "w0",
                    "title": "T",
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
        (entry,) = apply_event(state, start_event, ids, _RUN_ID, "sc")
        assert isinstance(entry, StartedJournalEntry)
        assert entry.phase == JournalPhase.STARTED
        assert entry.temp_path == "movies-hd/Nova.mkv.part"
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
            entries = apply_event(state, r, ids, _RUN_ID, "sc")
        (commit_entry,) = entries
        assert isinstance(commit_entry, CommittedJournalEntry)
        assert commit_entry.phase == JournalPhase.COMMITTED
        assert commit_entry.related_event_id == "copy_start_001"
        loc = state.locations[state.location_id_for_asset("a0")]
        assert loc.temp_path is None
        assert loc.path == "movies-hd/Nova.mkv"
        assert state.pending_slow_copies == {}
