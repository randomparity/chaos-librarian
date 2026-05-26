"""Tests for ``derive_path_history`` — pure journal projection."""

from __future__ import annotations

from typing import Any, Final

from pydantic import TypeAdapter

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.engine.path_history import derive_path_history

_JOURNAL_ENTRY_ADAPTER: Final[TypeAdapter[JournalEntry]] = TypeAdapter(JournalEntry)


def _validated_entry(payload: dict[str, Any]) -> JournalEntry:
    return _JOURNAL_ENTRY_ADAPTER.validate_python(payload)


def _atomic(
    *,
    event_id: str,
    action: TimelineActionName,
    logical_time_ns: int,
    target: str,
    target_ids: list[str] | None = None,
    **state_delta: object,
) -> dict[str, Any]:
    """Build a dict shaped like an AtomicJournalEntry for projection tests."""
    return {
        "schema_version": 1,
        "event_id": event_id,
        "scenario_id": "sc_test",
        "run_id": "1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01",
        "logical_time_ns": logical_time_ns,
        "action": action.value,
        "target_ids": target_ids or [target],
        "input_version_ids": [],
        "output_version_ids": [],
        "location_ids": [],
        "state_delta": state_delta,
        "phase": "atomic",
    }


def _started(
    *,
    event_id: str,
    logical_time_ns: int,
    target: str,
    temp_path: str,
    **state_delta: object,
) -> dict[str, Any]:
    """Build a dict shaped like a StartedJournalEntry for projection tests.

    Mirrors ``_handle_slow_copy_start``: ``temp_path`` is duplicated onto
    ``state_delta`` so the projection has a single, action-agnostic source
    of truth for path-bearing keys.
    """
    delta: dict[str, object] = {"temp_path": temp_path, **state_delta}
    return {
        "schema_version": 1,
        "event_id": event_id,
        "scenario_id": "sc_test",
        "run_id": "1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01",
        "logical_time_ns": logical_time_ns,
        "action": TimelineActionName.SLOW_COPY_START.value,
        "target_ids": [target],
        "input_version_ids": [],
        "output_version_ids": [],
        "location_ids": [],
        "state_delta": delta,
        "phase": "started",
        "temp_path": temp_path,
    }


def _committed(
    *,
    event_id: str,
    logical_time_ns: int,
    target: str,
    related_event_id: str,
    **state_delta: object,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "event_id": event_id,
        "scenario_id": "sc_test",
        "run_id": "1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01",
        "logical_time_ns": logical_time_ns,
        "action": TimelineActionName.SLOW_COPY_COMMIT.value,
        "target_ids": [target],
        "input_version_ids": [],
        "output_version_ids": [],
        "location_ids": [],
        "state_delta": state_delta,
        "phase": "committed",
        "related_event_id": related_event_id,
    }


def test_path_history_empty_for_asset_with_no_filesystem_events() -> None:
    """WHY: assets that never move/rename/delete should report empty path_history."""
    journal: list[JournalEntry] = []
    assert derive_path_history("asset_hd_main", journal) == []


def test_path_history_orders_by_logical_time_ns() -> None:
    """WHY: external consumers depend on journal-order traversal of the projection."""
    journal = [
        _validated_entry(
            _atomic(
                event_id="ev_move_1",
                action=TimelineActionName.MOVE_ASSET,
                logical_time_ns=1_000_000_000,
                target="asset_hd_main",
                from_path="a",
                to_path="b",
            )
        ),
        _validated_entry(
            _atomic(
                event_id="ev_rename_1",
                action=TimelineActionName.RENAME_FILE,
                logical_time_ns=2_000_000_000,
                target="asset_hd_main",
                from_path="b",
                to_path="c",
            )
        ),
    ]
    history = derive_path_history("asset_hd_main", journal)
    assert [e.event_id for e in history] == ["ev_move_1", "ev_rename_1"]
    assert history[0].from_path == "a"
    assert history[0].to_path == "b"
    assert history[1].from_path == "b"
    assert history[1].to_path == "c"


def test_path_history_filters_non_filesystem_actions() -> None:
    """WHY: reencode events touch bytes but not paths; they must not pollute the projection."""
    journal = [
        _validated_entry(
            _atomic(
                event_id="ev_reencode",
                action=TimelineActionName.REENCODE_VIDEO,
                logical_time_ns=1,
                target="asset_hd_main",
                resolution="1080p",
                codec="h264",
            )
        ),
    ]
    assert derive_path_history("asset_hd_main", journal) == []


def test_path_history_filters_other_assets() -> None:
    """WHY: per-asset projection must not leak events from sibling assets."""
    journal = [
        _validated_entry(
            _atomic(
                event_id="ev_other",
                action=TimelineActionName.MOVE_ASSET,
                logical_time_ns=1,
                target="asset_other",
                from_path="x",
                to_path="y",
            )
        ),
    ]
    assert derive_path_history("asset_hd_main", journal) == []


def test_path_history_includes_slow_copy_pair() -> None:
    """WHY: both phases of a slow_copy must surface so consumers can reconstruct staging.

    The ``started`` entry carries ``temp_path`` and ``initial_path_at_start``;
    the ``committed`` entry carries ``final_path``. The projection flattens
    those into the typed ``from_path`` / ``to_path`` / ``temp_path`` fields.
    """
    journal = [
        _validated_entry(
            _started(
                event_id="ev_slow_start",
                logical_time_ns=1_000_000_000,
                target="asset_hd_main",
                temp_path="movies-hd/.tmp/blazar.mkv.partial",
                # state_delta mirrors the handler's emission contract
                # (see engine.events._STATE_DELTA_KEYS for SLOW_COPY_START):
                # temp_path lives in state_delta even though it also appears
                # on the StartedJournalEntry envelope.
                final_path="movies-hd/blazar.mkv",
                initial_path_at_start="movies-hd/blazar.old.mkv",
            )
        ),
        _validated_entry(
            _committed(
                event_id="ev_slow_commit",
                logical_time_ns=2_000_000_000,
                target="asset_hd_main",
                related_event_id="ev_slow_start",
                final_path="movies-hd/blazar.mkv",
            )
        ),
    ]
    history = derive_path_history("asset_hd_main", journal)
    assert [e.event_id for e in history] == ["ev_slow_start", "ev_slow_commit"]

    start = history[0]
    assert start.action == TimelineActionName.SLOW_COPY_START
    assert start.temp_path == "movies-hd/.tmp/blazar.mkv.partial"
    assert start.from_path == "movies-hd/blazar.old.mkv"
    assert start.to_path == "movies-hd/blazar.mkv"

    commit = history[1]
    assert commit.action == TimelineActionName.SLOW_COPY_COMMIT
    assert commit.temp_path is None
    assert commit.from_path is None
    assert commit.to_path == "movies-hd/blazar.mkv"


def test_path_history_includes_archive_file_and_move_between_roots() -> None:
    """WHY: Sprint 6 mutations must populate path_history via the same projection."""
    journal = [
        _validated_entry(
            _atomic(
                event_id="ev_archive",
                action=TimelineActionName.ARCHIVE_FILE,
                logical_time_ns=1_000_000_000,
                target="asset_hd_main",
                from_path="movies-hd/blazar.mkv",
                to_path="archive/blazar.mkv",
            )
        ),
        _validated_entry(
            _atomic(
                event_id="ev_move_roots",
                action=TimelineActionName.MOVE_BETWEEN_ROOTS,
                logical_time_ns=2_000_000_000,
                target="asset_hd_main",
                from_path="archive/blazar.mkv",
                to_path="movies-hd/asset_hd_main.mkv",
                from_root_id="root_archive",
                to_root_id="root_hd",
            )
        ),
    ]
    history = derive_path_history("asset_hd_main", journal)
    assert [e.event_id for e in history] == ["ev_archive", "ev_move_roots"]

    archived = history[0]
    assert archived.action == TimelineActionName.ARCHIVE_FILE
    assert archived.from_path == "movies-hd/blazar.mkv"
    assert archived.to_path == "archive/blazar.mkv"
    assert archived.temp_path is None

    moved = history[1]
    assert moved.action == TimelineActionName.MOVE_BETWEEN_ROOTS
    assert moved.from_path == "archive/blazar.mkv"
    assert moved.to_path == "movies-hd/asset_hd_main.mkv"
    assert moved.temp_path is None


def test_path_history_projects_hierarchy_path_moves() -> None:
    """WHY: hierarchy journal entries carry per-asset path moves inside state_delta."""
    journal = [
        _validated_entry(
            _atomic(
                event_id="ev_renumber_episode",
                action=TimelineActionName.RENUMBER_EPISODE,
                logical_time_ns=1_000_000_000,
                target="episode_1",
                target_ids=["episode_1", "asset_hd_main", "asset_other"],
                metadata={"episode_number": {"before": 1, "after": 2}},
                path_moves=[
                    {
                        "asset_id": "asset_hd_main",
                        "location_id": "location_0001",
                        "from_path": "library/tv/Show/S01E01.mkv",
                        "to_path": "library/tv/Show/S01E02.mkv",
                    },
                    {
                        "asset_id": "asset_other",
                        "location_id": "location_0002",
                        "from_path": "library/tv/Show/S01E01-extra.mkv",
                        "to_path": "library/tv/Show/S01E02-extra.mkv",
                    },
                ],
                sidecar_moves=[],
                skipped_deleted_asset_ids=[],
            )
        )
    ]

    history = derive_path_history("asset_hd_main", journal)

    assert len(history) == 1
    (entry,) = history
    assert entry.event_id == "ev_renumber_episode"
    assert entry.action == TimelineActionName.RENUMBER_EPISODE
    assert entry.from_path == "library/tv/Show/S01E01.mkv"
    assert entry.to_path == "library/tv/Show/S01E02.mkv"
    assert entry.temp_path is None
