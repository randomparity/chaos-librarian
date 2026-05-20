"""Tests for atomic filesystem event handlers in chaos_librarian.engine.events."""

from __future__ import annotations

import uuid

import pytest

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.scenario import Scenario, TimelineActionName
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state
from tests.engine.conftest import _build_minimal_scenario, _resolve_archive_file

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _scenario(timeline: list[dict[str, object]]) -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 4,
            "scenario_id": "fs",
            "seed": 1,
            "duration_scale": "short",
            "library": {
                "roots": [
                    {"id": "r0", "path": "movies-hd"},
                    {"id": "r1", "path": "archive"},
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
            "timeline": timeline,
        }
    )


class TestMoveAssetHandler:
    """move_asset updates the asset's location path and emits one journal entry.

    WHY: location-path mutations are the most common test surface for
    scanner/watcher tests; the journal entry must record both endpoints
    so adapters can verify the move was observed.
    """

    def test_move_updates_location_path(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "move_asset",
                    "target": "a0",
                    "to": "movies-hd/Renamed.mkv",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        entries = apply_event(state, resolved, ids, _RUN_ID, "fs")
        (entry,) = entries
        assert isinstance(entry, AtomicJournalEntry)
        assert entry.phase == JournalPhase.ATOMIC
        assert entry.action == "move_asset"
        assert entry.target_ids == ["a0"]
        assert entry.state_delta["from_path"] == "movies-hd/a0.mkv"
        assert entry.state_delta["to_path"] == "movies-hd/Renamed.mkv"
        (loc,) = state.locations.values()
        assert loc.path == "movies-hd/Renamed.mkv"


class TestRenameFileHandler:
    """rename_file is move_asset with a same-root target — same wire shape.

    WHY: the journal entry's ``action`` field discriminates the two; rename
    is recorded distinctly so adapters know the operation was a rename
    not a cross-root move.
    """

    def test_rename_updates_path_and_records_action(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "rename_file",
                    "target": "a0",
                    "to": "movies-hd/Renamed.mkv",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        (entry,) = apply_event(state, resolved, ids, _RUN_ID, "fs")
        assert entry.action == "rename_file"
        (loc,) = state.locations.values()
        assert loc.path == "movies-hd/Renamed.mkv"


class TestDeleteFileHandler:
    """delete_file removes the location and records the prior path.

    WHY: an oracle that says "this path is now absent" is what scanner
    tests assert against. The journal's ``state_delta.removed_path`` is the
    single source of truth.
    """

    def test_delete_removes_location(self) -> None:
        scenario = _scenario([{"id": "e0", "at": "1s", "action": "delete_file", "target": "a0"}])
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        (entry,) = apply_event(state, resolved, ids, _RUN_ID, "fs")
        assert entry.action == "delete_file"
        assert entry.state_delta["removed_path"] == "movies-hd/a0.mkv"
        assert state.locations == {}


class TestAddFileHandler:
    """add_file places an asset that currently has no location.

    WHY: after a delete_file, an add_file is the supported way to re-place
    the asset; without this handler scenarios that delete-then-add crash.
    """

    def test_add_after_delete_rebinds_location(self) -> None:
        scenario = _scenario(
            [
                {"id": "e0", "at": "1s", "action": "delete_file", "target": "a0"},
                {
                    "id": "e1",
                    "at": "2s",
                    "action": "add_file",
                    "target": "a0",
                    "to": "archive/a0.mkv",
                },
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        resolved = resolve_timeline(scenario)
        for r in resolved:
            apply_event(state, r, ids, _RUN_ID, "fs")
        (loc,) = state.locations.values()
        assert loc.path == "archive/a0.mkv"

    def test_add_rejects_already_placed_asset(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "add_file",
                    "target": "a0",
                    "to": "archive/a0.mkv",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        with pytest.raises(ValueError, match="already has a location"):
            apply_event(state, resolved, ids, _RUN_ID, "fs")


class TestArchiveFileHandler:
    """archive_file moves the asset to its archive destination.

    WHY: archive operations are the same shape as a move (path mutation,
    asset stays placed) but resolve their destination from the scenario's
    declared archive root rather than an inline ``to``. The handler must
    record both endpoints so adapters can verify the archive landed where
    the contract said it would.
    """

    def test_archive_file_handler_moves_location_to_archive_path(self) -> None:
        scenario = _build_minimal_scenario(
            roots=[("movies-hd", "library/movies-hd")],
            works=[("work_001", "asset_hd_main", "mkv")],
        )
        state = build_initial_state(scenario, IdAllocator(TraceRecorder()))
        resolved = _resolve_archive_file(scenario, event_id="ev_arch_001", target="asset_hd_main")
        entries = apply_event(
            state=state,
            resolved=resolved,
            ids=IdAllocator(TraceRecorder()),
            run_id=uuid.UUID("1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01"),
            scenario_id="sc_test",
        )
        loc_id = state.location_id_for_asset("asset_hd_main")
        assert state.locations[loc_id].path == "library/movies-hd/archive/asset_hd_main.mkv"
        assert state.has_location("asset_hd_main"), "archive keeps the asset placed"
        assert len(entries) == 1
        (entry,) = entries
        assert entry.action == TimelineActionName.ARCHIVE_FILE
        assert entry.target_ids == ["asset_hd_main"]
        assert entry.state_delta == {
            "from_path": "library/movies-hd/asset_hd_main.mkv",
            "to_path": "library/movies-hd/archive/asset_hd_main.mkv",
        }

    def test_archive_file_handler_uses_explicit_archive_root(self) -> None:
        scenario = _build_minimal_scenario(
            roots=[
                ("movies-hd", "library/movies-hd"),
                ("cold-storage", "library/cold-storage"),
            ],
            works=[("work_001", "asset_hd_main", "mkv")],
            archive_root="cold-storage",
        )
        state = build_initial_state(scenario, IdAllocator(TraceRecorder()))
        resolved = _resolve_archive_file(scenario, event_id="ev_arch_001", target="asset_hd_main")
        apply_event(
            state=state,
            resolved=resolved,
            ids=IdAllocator(TraceRecorder()),
            run_id=uuid.UUID("1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01"),
            scenario_id="sc_test",
        )
        loc_id = state.location_id_for_asset("asset_hd_main")
        assert state.locations[loc_id].path == "library/cold-storage/asset_hd_main.mkv"
