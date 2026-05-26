"""Phase-B materializer support for hierarchy journal path moves."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.materialization import FilesystemAction
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer.errors import FilesystemActionError
from chaos_librarian.materializer.phase_b.filesystem import (
    apply_filesystem_action,
    make_filesystem_phase_b_context,
)
from tests.materializer.conftest import _atomic_entry
from tests.materializer.test_filesystem import _scenario, _scenario_assets


def _apply(library: Path, entry: JournalEntry) -> FilesystemAction | None:
    ctx = make_filesystem_phase_b_context(
        library_root=library,
        scenario_assets=_scenario_assets(_scenario()),
        resolved_seed=1234,
    )
    return apply_filesystem_action(ctx, entry)


def test_hierarchy_move_rejects_destination_occupied_outside_move_set(
    tmp_path: Path,
) -> None:
    library = tmp_path / "library"
    (library / "tv").mkdir(parents=True)
    source = library / "tv" / "Show - S01E01.mkv"
    occupied = library / "tv" / "Show - S01E02.mkv"
    source.write_bytes(b"source")
    occupied.write_bytes(b"occupied")
    entry = _atomic_entry(
        event_id="renumber_001",
        action=TimelineActionName.RENUMBER_EPISODE,
        target="episode_1",
        state_delta={
            "metadata": {"episode_number": {"before": 1, "after": 2}},
            "path_moves": [
                {
                    "asset_id": "asset_hd_main",
                    "location_id": "location_0001",
                    "from_path": "tv/Show - S01E01.mkv",
                    "to_path": "tv/Show - S01E02.mkv",
                }
            ],
            "sidecar_moves": [],
            "skipped_deleted_asset_ids": [],
        },
    )

    with pytest.raises(FilesystemActionError) as exc_info:
        _apply(library, entry)

    assert exc_info.value.asset_id == "asset_hd_main"
    assert source.read_bytes() == b"source"
    assert occupied.read_bytes() == b"occupied"


def test_hierarchy_move_temp_collision_preserves_unstaged_sources(tmp_path: Path) -> None:
    library = tmp_path / "library"
    (library / "music").mkdir(parents=True)
    first = library / "music" / "01 - First.flac"
    second = library / "music" / "02 - Second.flac"
    preexisting_temp = library / "music" / ".02 - Second.flac.chaos-renumber_disc_001-1.tmp"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    preexisting_temp.write_bytes(b"preexisting")
    entry = _atomic_entry(
        event_id="renumber_disc_001",
        action=TimelineActionName.RENUMBER_DISC,
        target="disc_1",
        state_delta={
            "metadata": {"disc_number": {"before": 1, "after": 2}},
            "path_moves": [
                {
                    "asset_id": "asset_first",
                    "location_id": "location_0001",
                    "from_path": "music/01 - First.flac",
                    "to_path": "music/02 - Second.flac",
                },
                {
                    "asset_id": "asset_second",
                    "location_id": "location_0002",
                    "from_path": "music/02 - Second.flac",
                    "to_path": "music/01 - First.flac",
                },
            ],
            "sidecar_moves": [],
            "skipped_deleted_asset_ids": [],
        },
    )

    with pytest.raises(FilesystemActionError):
        _apply(library, entry)

    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"
    assert preexisting_temp.read_bytes() == b"preexisting"
    assert not (library / "music" / ".01 - First.flac.chaos-renumber_disc_001-0.tmp").exists()


def test_hierarchy_move_blocked_destination_parent_preserves_source(
    tmp_path: Path,
) -> None:
    library = tmp_path / "library"
    (library / "tv").mkdir(parents=True)
    source = library / "tv" / "Show - S01E01.mkv"
    blocked_parent = library / "tv" / "blocked"
    source.write_bytes(b"source")
    blocked_parent.write_bytes(b"not-a-directory")
    entry = _atomic_entry(
        event_id="renumber_001",
        action=TimelineActionName.RENUMBER_EPISODE,
        target="episode_1",
        state_delta={
            "metadata": {"episode_number": {"before": 1, "after": 2}},
            "path_moves": [
                {
                    "asset_id": "asset_hd_main",
                    "location_id": "location_0001",
                    "from_path": "tv/Show - S01E01.mkv",
                    "to_path": "tv/blocked/Show - S01E02.mkv",
                }
            ],
            "sidecar_moves": [],
            "skipped_deleted_asset_ids": [],
        },
    )

    with pytest.raises(FilesystemActionError):
        _apply(library, entry)

    assert source.read_bytes() == b"source"
    assert blocked_parent.read_bytes() == b"not-a-directory"
    assert not (library / "tv" / ".Show - S01E01.mkv.chaos-renumber_001-0.tmp").exists()


def test_hierarchy_move_swaps_paths_via_temporary_siblings(tmp_path: Path) -> None:
    library = tmp_path / "library"
    (library / "music").mkdir(parents=True)
    first = library / "music" / "01 - First.flac"
    second = library / "music" / "02 - Second.flac"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    entry = _atomic_entry(
        event_id="renumber_disc_001",
        action=TimelineActionName.RENUMBER_DISC,
        target="disc_1",
        state_delta={
            "metadata": {"disc_number": {"before": 1, "after": 2}},
            "path_moves": [
                {
                    "asset_id": "asset_first",
                    "location_id": "location_0001",
                    "from_path": "music/01 - First.flac",
                    "to_path": "music/02 - Second.flac",
                },
                {
                    "asset_id": "asset_second",
                    "location_id": "location_0002",
                    "from_path": "music/02 - Second.flac",
                    "to_path": "music/01 - First.flac",
                },
            ],
            "sidecar_moves": [],
            "skipped_deleted_asset_ids": [],
        },
    )

    action = _apply(library, entry)

    assert action is not None
    assert first.read_bytes() == b"second"
    assert second.read_bytes() == b"first"
    assert list((library / "music").glob("*.tmp")) == []


def test_hierarchy_move_moves_renderer_derived_sidecar(tmp_path: Path) -> None:
    library = tmp_path / "library"
    (library / "tv").mkdir(parents=True)
    media = library / "tv" / "Show - S01E01.mkv"
    sidecar = library / "tv" / "Show - S01E01.eng.srt"
    media.write_bytes(b"media")
    sidecar.write_bytes(b"subtitle")
    entry = _atomic_entry(
        event_id="renumber_001",
        action=TimelineActionName.RENUMBER_EPISODE,
        target="episode_1",
        state_delta={
            "metadata": {"episode_number": {"before": 1, "after": 2}},
            "path_moves": [
                {
                    "asset_id": "asset_hd_main",
                    "location_id": "location_0001",
                    "from_path": "tv/Show - S01E01.mkv",
                    "to_path": "tv/Show - S01E02.mkv",
                }
            ],
            "sidecar_moves": [
                {
                    "sidecar_id": "sidecar_asset_hd_main_eng",
                    "asset_id": "asset_hd_main",
                    "from_path": "tv/Show - S01E01.eng.srt",
                    "to_path": "tv/Show - S01E02.eng.srt",
                }
            ],
            "skipped_deleted_asset_ids": [],
        },
    )

    _apply(library, entry)

    assert not media.exists()
    assert not sidecar.exists()
    assert (library / "tv" / "Show - S01E02.mkv").read_bytes() == b"media"
    assert (library / "tv" / "Show - S01E02.eng.srt").read_bytes() == b"subtitle"


def test_hierarchy_move_leaves_explicit_timeline_sidecar_in_place(tmp_path: Path) -> None:
    library = tmp_path / "library"
    (library / "tv").mkdir(parents=True)
    (library / "custom").mkdir(parents=True)
    media = library / "tv" / "Show - S01E01.mkv"
    explicit = library / "custom" / "spanish.srt"
    media.write_bytes(b"media")
    explicit.write_bytes(b"explicit")
    entry = _atomic_entry(
        event_id="renumber_001",
        action=TimelineActionName.RENUMBER_EPISODE,
        target="episode_1",
        state_delta={
            "metadata": {"episode_number": {"before": 1, "after": 2}},
            "path_moves": [
                {
                    "asset_id": "asset_hd_main",
                    "location_id": "location_0001",
                    "from_path": "tv/Show - S01E01.mkv",
                    "to_path": "tv/Show - S01E02.mkv",
                }
            ],
            "sidecar_moves": [],
            "skipped_deleted_asset_ids": [],
        },
    )

    _apply(library, entry)

    assert (library / "tv" / "Show - S01E02.mkv").read_bytes() == b"media"
    assert explicit.read_bytes() == b"explicit"


def test_hierarchy_entry_with_no_moves_is_noop(tmp_path: Path) -> None:
    library = tmp_path / "library"
    library.mkdir()
    entry = _atomic_entry(
        event_id="rename_season_001",
        action=TimelineActionName.RENAME_SEASON,
        target="season_1",
        state_delta={
            "metadata": {"title": {"before": "Old", "after": "New"}},
            "path_moves": [],
            "sidecar_moves": [],
            "skipped_deleted_asset_ids": [],
        },
    )

    assert _apply(library, entry) is None
