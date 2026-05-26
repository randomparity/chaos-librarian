"""Phase-B dispatcher tests for ``materializer/phase_b/filesystem.py``.

One test per per-action helper, plus the dispatcher's contracts:
``OSError`` wraps into ``FilesystemActionError`` carrying the originating
event id, errno, and action; unknown actions are dropped silently so
future engine-only events do not crash phase B.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.materialization import FilesystemAction
from chaos_librarian.contract.scenario import Asset, Scenario, TimelineActionName
from chaos_librarian.materializer.errors import FilesystemActionError
from chaos_librarian.materializer.phase_b import filesystem as filesystem_module
from chaos_librarian.materializer.phase_b.filesystem import (
    apply_filesystem_action,
    make_filesystem_phase_b_context,
)
from chaos_librarian.topology import iter_asset_contexts
from tests.materializer.conftest import (
    _atomic_entry,
    _committed_entry,
    _started_entry,
)


def _scenario() -> Scenario:
    """Build the minimal Scenario every phase-B test shares."""
    return _movie_scenario(
        roots=[
            ("movies-hd", "library/movies-hd"),
            ("cold-storage", "library/cold-storage"),
        ],
        assets=[("asset_hd_main", "mkv")],
        archive_root="archive",
    )


def _movie_scenario(
    *,
    roots: list[tuple[str, str]],
    assets: list[tuple[str, str]],
    archive_root: str | None = None,
) -> Scenario:
    library: dict[str, object] = {
        "roots": [{"id": root_id, "path": path} for root_id, path in roots],
    }
    if archive_root is not None:
        library["archive_root"] = archive_root
    movies = [
        {
            "id": f"movie_{index:03d}",
            "title": f"Movie {index}",
            "layout": "movie_flat",
            "variants": [
                {
                    "id": f"variant_{index:03d}",
                    "label": "default",
                    "bundle": {
                        "id": f"bundle_{index:03d}",
                        "assets": [
                            {
                                "id": asset_id,
                                "role": "primary_video",
                                "container": container,
                                "duration_seconds": 1,
                            }
                        ],
                    },
                }
            ],
        }
        for index, (asset_id, container) in enumerate(assets, start=1)
    ]
    return Scenario.model_validate(
        {
            "schema_version": 15,
            "scenario_id": "materializer-filesystem-test",
            "seed": 1,
            "duration_scale": "short",
            "library": library,
            "movies": movies,
            "series": [],
            "artists": [],
            "timeline": [],
        }
    )


def _scenario_assets(scenario: Scenario) -> dict[str, Asset]:
    return {context.asset.id: context.asset for context in iter_asset_contexts(scenario)}


def _apply_entries(
    *,
    library_root: Path,
    journal: list[JournalEntry],
    scenario: Scenario,
    resolved_seed: int,
) -> tuple[list[FilesystemAction], dict[str, str]]:
    ctx = make_filesystem_phase_b_context(
        library_root=library_root,
        scenario_assets=_scenario_assets(scenario),
        resolved_seed=resolved_seed,
    )
    actions: list[FilesystemAction] = []
    for entry in journal:
        action = apply_filesystem_action(ctx, entry)
        if action is not None:
            actions.append(action)
    return actions, dict(ctx.phase_b_sidecar_hashes)


def test_filesystem_module_has_no_phase_b_orchestrator() -> None:
    assert not hasattr(filesystem_module, "apply_phase_b")


def test_apply_move_asset_renames_file(tmp_path: Path) -> None:
    """WHY: move_asset must rename src->dst on disk and emit a
    FilesystemAction whose action discriminator is MOVE_ASSET so the
    audit log distinguishes it from rename_file / archive_file."""
    library = tmp_path / "library"
    (library / "movies-hd").mkdir(parents=True)
    (library / "movies-hd" / "asset_hd_main.mkv").write_bytes(b"bytes")
    journal = [
        _atomic_entry(
            event_id="move_001",
            action=TimelineActionName.MOVE_ASSET,
            target="asset_hd_main",
            state_delta={
                "from_path": "movies-hd/asset_hd_main.mkv",
                "to_path": "movies-hd/renamed.mkv",
            },
        )
    ]
    actions, sidecar_hashes = _apply_entries(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    assert not (library / "movies-hd" / "asset_hd_main.mkv").exists()
    assert (library / "movies-hd" / "renamed.mkv").read_bytes() == b"bytes"
    assert len(actions) == 1
    assert actions[0].action is TimelineActionName.MOVE_ASSET
    assert actions[0].target_asset_id == "asset_hd_main"
    assert actions[0].from_path == "movies-hd/asset_hd_main.mkv"
    assert actions[0].to_path == "movies-hd/renamed.mkv"
    assert actions[0].temp_path is None
    assert actions[0].duration_ns > 0
    assert sidecar_hashes == {}


def test_apply_rename_file_is_alias_of_move(tmp_path: Path) -> None:
    """WHY: rename_file shares the move_asset helper body but must emit
    the RENAME_FILE discriminator -- consumers reading filesystem_actions
    need to tell rename from move without re-walking the scenario."""
    library = tmp_path / "library"
    (library / "movies-hd").mkdir(parents=True)
    (library / "movies-hd" / "asset_hd_main.mkv").write_bytes(b"bytes")
    journal = [
        _atomic_entry(
            event_id="rename_001",
            action=TimelineActionName.RENAME_FILE,
            target="asset_hd_main",
            state_delta={
                "from_path": "movies-hd/asset_hd_main.mkv",
                "to_path": "movies-hd/renamed.mkv",
            },
        )
    ]
    actions, _ = _apply_entries(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    assert len(actions) == 1
    assert actions[0].action is TimelineActionName.RENAME_FILE


def test_apply_delete_file_unlinks(tmp_path: Path) -> None:
    """WHY: delete_file removes the file at removed_path; the emitted
    FilesystemAction carries from_path (the removed path) and a null
    to_path so the audit log preserves what was lost."""
    library = tmp_path / "library"
    (library / "movies-hd").mkdir(parents=True)
    (library / "movies-hd" / "asset_hd_main.mkv").write_bytes(b"bytes")
    journal = [
        _atomic_entry(
            event_id="del_001",
            action=TimelineActionName.DELETE_FILE,
            target="asset_hd_main",
            state_delta={"removed_path": "movies-hd/asset_hd_main.mkv"},
        )
    ]
    actions, _ = _apply_entries(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    assert not (library / "movies-hd" / "asset_hd_main.mkv").exists()
    assert len(actions) == 1
    assert actions[0].action is TimelineActionName.DELETE_FILE
    assert actions[0].from_path == "movies-hd/asset_hd_main.mkv"
    assert actions[0].to_path is None


def test_apply_delete_then_add_file_restores_bytes(tmp_path: Path) -> None:
    """WHY: in materialize/run, add_file means a previously deleted file
    reappears. Phase B must preserve the deleted bytes and write them to
    the new path instead of synthesizing unrelated content."""
    library = tmp_path / "library"
    (library / "movies-hd").mkdir(parents=True)
    original = library / "movies-hd" / "asset_hd_main.mkv"
    original.write_bytes(b"restored bytes")
    journal = [
        _atomic_entry(
            event_id="del_001",
            action=TimelineActionName.DELETE_FILE,
            target="asset_hd_main",
            state_delta={"removed_path": "movies-hd/asset_hd_main.mkv"},
        ),
        _atomic_entry(
            event_id="add_001",
            action=TimelineActionName.ADD_FILE,
            target="asset_hd_main",
            state_delta={"added_path": "movies-hd/restored.mkv"},
        ),
    ]
    actions, _ = _apply_entries(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    assert not original.exists()
    assert (library / "movies-hd" / "restored.mkv").read_bytes() == b"restored bytes"
    assert [action.action for action in actions] == [
        TimelineActionName.DELETE_FILE,
        TimelineActionName.ADD_FILE,
    ]


def test_apply_archive_file_moves_to_archive_root(tmp_path: Path) -> None:
    """WHY: archive_file routes through the shared move helper but must
    emit an ARCHIVE_FILE discriminator and respect whichever destination
    the engine wrote into state_delta -- the materializer is path-driven,
    not policy-driven."""
    library = tmp_path / "library"
    (library / "movies-hd").mkdir(parents=True)
    (library / "movies-hd" / "asset_hd_main.mkv").write_bytes(b"bytes")
    journal = [
        _atomic_entry(
            event_id="arch_001",
            action=TimelineActionName.ARCHIVE_FILE,
            target="asset_hd_main",
            state_delta={
                "from_path": "movies-hd/asset_hd_main.mkv",
                "to_path": "archive/asset_hd_main.mkv",
            },
        )
    ]
    actions, _ = _apply_entries(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    assert not (library / "movies-hd" / "asset_hd_main.mkv").exists()
    assert (library / "archive" / "asset_hd_main.mkv").read_bytes() == b"bytes"
    assert len(actions) == 1
    assert actions[0].action is TimelineActionName.ARCHIVE_FILE
    assert actions[0].to_path == "archive/asset_hd_main.mkv"


def test_apply_archive_file_with_explicit_root(tmp_path: Path) -> None:
    """WHY: an explicit ``archive_root`` from the scenario surfaces in
    state_delta as a normal ``to_path`` value -- the helper must move
    bytes to whichever directory the engine picked, not the default."""
    library = tmp_path / "library"
    (library / "movies-hd").mkdir(parents=True)
    (library / "movies-hd" / "asset_hd_main.mkv").write_bytes(b"bytes")
    journal = [
        _atomic_entry(
            event_id="arch_explicit",
            action=TimelineActionName.ARCHIVE_FILE,
            target="asset_hd_main",
            state_delta={
                "from_path": "movies-hd/asset_hd_main.mkv",
                "to_path": "cold-storage/asset_hd_main.mkv",
            },
        )
    ]
    actions, _ = _apply_entries(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    assert (library / "cold-storage" / "asset_hd_main.mkv").read_bytes() == b"bytes"
    assert len(actions) == 1
    assert actions[0].to_path == "cold-storage/asset_hd_main.mkv"


def test_apply_move_between_roots_crosses_roots(tmp_path: Path) -> None:
    """WHY: move_between_roots is a special-cased move whose to_path lies
    under a different root id; the helper must follow the state_delta
    paths exactly and the action discriminator must distinguish it from
    plain move_asset."""
    library = tmp_path / "library"
    (library / "movies-hd").mkdir(parents=True)
    (library / "movies-hd" / "asset_hd_main.mkv").write_bytes(b"bytes")
    journal = [
        _atomic_entry(
            event_id="mbr_001",
            action=TimelineActionName.MOVE_BETWEEN_ROOTS,
            target="asset_hd_main",
            state_delta={
                "from_path": "movies-hd/asset_hd_main.mkv",
                "to_path": "cold-storage/asset_hd_main.mkv",
                "from_root_id": "movies-hd",
                "to_root_id": "cold-storage",
            },
        )
    ]
    actions, _ = _apply_entries(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    assert not (library / "movies-hd" / "asset_hd_main.mkv").exists()
    assert (library / "cold-storage" / "asset_hd_main.mkv").read_bytes() == b"bytes"
    assert len(actions) == 1
    assert actions[0].action is TimelineActionName.MOVE_BETWEEN_ROOTS


def test_apply_slow_copy_start_writes_full_bytes_to_temp_path(tmp_path: Path) -> None:
    """WHY: phase B materializes the staging artifact at slow_copy_start
    -- the temp file must hold the same bytes as the source; commit
    later renames in place. If start dropped bytes, commit would publish
    a truncated final file."""
    library = tmp_path / "library"
    (library / "movies-hd").mkdir(parents=True)
    (library / "movies-hd" / "asset_hd_main.mkv").write_bytes(b"slow-copy bytes")
    journal = [
        _started_entry(
            event_id="sc_start",
            target="asset_hd_main",
            temp_path="movies-hd/asset_hd_main.mkv.partial",
            state_delta={
                "initial_path_at_start": "movies-hd/asset_hd_main.mkv",
                "temp_path": "movies-hd/asset_hd_main.mkv.partial",
                "final_path": "movies-hd/final.mkv",
            },
        )
    ]
    actions, _ = _apply_entries(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    staged = library / "movies-hd" / "asset_hd_main.mkv.partial"
    assert staged.read_bytes() == b"slow-copy bytes"
    # Source remains until commit promotes the temp file.
    assert (library / "movies-hd" / "asset_hd_main.mkv").exists()
    assert len(actions) == 1
    assert actions[0].action is TimelineActionName.SLOW_COPY_START
    assert actions[0].temp_path == "movies-hd/asset_hd_main.mkv.partial"
    assert actions[0].to_path == "movies-hd/final.mkv"


def test_apply_slow_copy_start_does_not_read_source_into_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    library = tmp_path / "library"
    (library / "movies-hd").mkdir(parents=True)
    (library / "movies-hd" / "asset_hd_main.mkv").write_bytes(b"slow-copy bytes")
    journal = [
        _started_entry(
            event_id="sc_start",
            target="asset_hd_main",
            temp_path="movies-hd/asset_hd_main.mkv.partial",
            state_delta={
                "initial_path_at_start": "movies-hd/asset_hd_main.mkv",
                "temp_path": "movies-hd/asset_hd_main.mkv.partial",
                "final_path": "movies-hd/final.mkv",
            },
        )
    ]

    def fail_read_bytes(self: Path) -> bytes:
        raise AssertionError(f"slow copy should stream from source path: {self}")

    monkeypatch.setattr(Path, "read_bytes", fail_read_bytes)

    actions, _ = _apply_entries(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )

    staged = library / "movies-hd" / "asset_hd_main.mkv.partial"
    with staged.open("rb") as handle:
        assert handle.read() == b"slow-copy bytes"
    assert len(actions) == 1
    assert actions[0].action is TimelineActionName.SLOW_COPY_START


def test_apply_slow_copy_commit_renames_temp_to_final(tmp_path: Path) -> None:
    """WHY: commit promotes the staged temp file to the final path. The
    dispatcher must thread pending_slow_copy state from start to commit
    via related_event_id -- otherwise commit can't recover which temp
    file belongs to which final."""
    library = tmp_path / "library"
    (library / "movies-hd").mkdir(parents=True)
    (library / "movies-hd" / "asset_hd_main.mkv").write_bytes(b"slow-copy bytes")
    journal = [
        _started_entry(
            event_id="sc_start",
            target="asset_hd_main",
            temp_path="movies-hd/asset_hd_main.mkv.partial",
            state_delta={
                "initial_path_at_start": "movies-hd/asset_hd_main.mkv",
                "temp_path": "movies-hd/asset_hd_main.mkv.partial",
                "final_path": "movies-hd/asset_hd_main.mkv",
            },
        ),
        _committed_entry(
            event_id="sc_commit",
            target="asset_hd_main",
            related_event_id="sc_start",
            state_delta={"final_path": "movies-hd/asset_hd_main.mkv"},
        ),
    ]
    actions, _ = _apply_entries(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    final = library / "movies-hd" / "asset_hd_main.mkv"
    assert final.read_bytes() == b"slow-copy bytes"
    assert not (library / "movies-hd" / "asset_hd_main.mkv.partial").exists()
    assert len(actions) == 2
    assert actions[1].action is TimelineActionName.SLOW_COPY_COMMIT
    assert actions[1].from_path == "movies-hd/asset_hd_main.mkv.partial"
    assert actions[1].to_path == "movies-hd/asset_hd_main.mkv"


def test_apply_slow_copy_commit_unlinks_initial_when_different_from_final(
    tmp_path: Path,
) -> None:
    """WHY: when commit's final_path differs from the recorded
    initial_path, the original file is the second-copy's residue; commit
    must unlink it so the library/ tree doesn't accumulate the
    pre-renamed source after the slow-copy lands at a new location."""
    library = tmp_path / "library"
    (library / "movies-hd").mkdir(parents=True)
    (library / "movies-hd" / "asset_hd_main.mkv").write_bytes(b"slow-copy bytes")
    journal = [
        _started_entry(
            event_id="sc_start",
            target="asset_hd_main",
            temp_path="movies-hd/asset_hd_main.mkv.partial",
            state_delta={
                "initial_path_at_start": "movies-hd/asset_hd_main.mkv",
                "temp_path": "movies-hd/asset_hd_main.mkv.partial",
                "final_path": "movies-hd/elsewhere.mkv",
            },
        ),
        _committed_entry(
            event_id="sc_commit",
            target="asset_hd_main",
            related_event_id="sc_start",
            state_delta={"final_path": "movies-hd/elsewhere.mkv"},
        ),
    ]
    _apply_entries(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    assert (library / "movies-hd" / "elsewhere.mkv").read_bytes() == b"slow-copy bytes"
    assert not (library / "movies-hd" / "asset_hd_main.mkv").exists()
    assert not (library / "movies-hd" / "asset_hd_main.mkv.partial").exists()


def test_apply_remove_sidecar_unlinks_file_and_returns_action(tmp_path: Path) -> None:
    """WHY: remove_sidecar unlinks the sidecar at removed_sidecar_path; the
    emitted FilesystemAction carries from_path (the removed path) and a
    null to_path so the audit log preserves what was lost -- mirroring
    delete_file's contract for the sidecar case. The materializer routes
    this here (not media.py) because no ffmpeg work is required."""
    library = tmp_path / "library"
    (library / "movies-hd").mkdir(parents=True)
    sidecar = library / "movies-hd" / "asset_hd_main.en.srt"
    sidecar.write_bytes(b"x")
    journal = [
        _atomic_entry(
            event_id="rs_001",
            action=TimelineActionName.REMOVE_SIDECAR,
            target="asset_hd_main",
            state_delta={
                "removed_sidecar_id": "sidecar_0001",
                "removed_sidecar_path": "movies-hd/asset_hd_main.en.srt",
            },
        )
    ]
    actions, _ = _apply_entries(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    assert not sidecar.exists()
    assert len(actions) == 1
    assert actions[0].action is TimelineActionName.REMOVE_SIDECAR
    assert actions[0].from_path == "movies-hd/asset_hd_main.en.srt"
    assert actions[0].to_path is None
    assert actions[0].temp_path is None


def test_apply_touch_mtime_updates_mtime_without_changing_bytes(tmp_path: Path) -> None:
    library = tmp_path / "library"
    (library / "movies-hd").mkdir(parents=True)
    asset = library / "movies-hd" / "asset_hd_main.mkv"
    asset.write_bytes(b"same bytes")
    before_hash = "sha256:" + hashlib.sha256(asset.read_bytes()).hexdigest()
    before_mtime_ns = asset.stat().st_mtime_ns
    journal = [
        _atomic_entry(
            event_id="mtime_001",
            action=TimelineActionName.TOUCH_MTIME,
            target="asset_hd_main",
            state_delta={
                "path": "movies-hd/asset_hd_main.mkv",
                "profile": "filesystem-artifacts",
                "offset": "2s",
            },
        )
    ]

    actions, _ = _apply_entries(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )

    after_mtime_ns = asset.stat().st_mtime_ns
    assert "sha256:" + hashlib.sha256(asset.read_bytes()).hexdigest() == before_hash
    assert after_mtime_ns == before_mtime_ns + 2_000_000_000
    assert len(actions) == 1
    assert actions[0].action is TimelineActionName.TOUCH_MTIME
    assert actions[0].from_path == "movies-hd/asset_hd_main.mkv"
    assert actions[0].to_path == "movies-hd/asset_hd_main.mkv"
    assert actions[0].content_hash == before_hash
    assert actions[0].mtime_before_ns == before_mtime_ns
    assert actions[0].mtime_after_ns == after_mtime_ns


def test_apply_unknown_action_returns_none_from_dispatch(tmp_path: Path) -> None:
    """WHY: Sprint 6 preflight already rejects unsupported actions, but
    the dispatcher must not crash if a future engine-only action (e.g. a
    media mutation re-encode) reaches phase B; defense in depth keeps
    library/ intact when the contract layers are out of sync."""
    library = tmp_path / "library"
    library.mkdir()
    journal = [
        _atomic_entry(
            event_id="rv_001",
            action=TimelineActionName.REENCODE_VIDEO,
            target="asset_hd_main",
            state_delta={"resolution": "hd", "codec": "h264"},
        )
    ]
    actions, sidecar_hashes = _apply_entries(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    assert actions == []
    assert sidecar_hashes == {}


def test_apply_non_oserror_also_wraps_into_filesystem_action_error(tmp_path: Path) -> None:
    """WHY: handlers can raise non-OSError on contract drift -- e.g. a
    slow_copy_commit entry whose ``related_event_id`` was never staged
    surfaces as ``KeyError`` from ``pending_slow_copy.pop``. The dispatcher
    must wrap any handler exception into FilesystemActionError so the CLI
    still produces a structured exit-5 payload (errno=None because there
    is no underlying syscall errno). Otherwise the bare KeyError escapes
    the cleanup path and library/ stays partially populated."""
    library = tmp_path / "library"
    library.mkdir()
    journal = [
        _committed_entry(
            event_id="sc_orphan_commit",
            target="asset_hd_main",
            related_event_id="sc_start_never_happened",
            state_delta={"final_path": "movies-hd/asset_hd_main.mkv"},
        )
    ]
    with pytest.raises(FilesystemActionError) as exc_info:
        _apply_entries(
            library_root=library,
            journal=journal,
            scenario=_scenario(),
            resolved_seed=1234,
        )
    err = exc_info.value
    assert err.event_id == "sc_orphan_commit"
    assert err.action is TimelineActionName.SLOW_COPY_COMMIT
    assert err.asset_id == "asset_hd_main"
    assert err.payload["errno"] is None
    assert err.payload["action"] == "slow_copy_commit"
    assert err.payload["event_id"] == "sc_orphan_commit"


def test_apply_oserror_wraps_into_filesystem_action_error(tmp_path: Path) -> None:
    """WHY: any OSError from a phase-B helper must surface as a typed
    FilesystemActionError carrying the originating event_id, action, and
    errno so the CLI handler can emit a structured exit-5 payload
    without introspecting __cause__."""
    library = tmp_path / "library"
    library.mkdir()
    journal = [
        _atomic_entry(
            event_id="move_missing",
            action=TimelineActionName.MOVE_ASSET,
            target="asset_hd_main",
            state_delta={
                "from_path": "ghost.mkv",
                "to_path": "movies-hd/new.mkv",
            },
        )
    ]
    with pytest.raises(FilesystemActionError) as exc_info:
        _apply_entries(
            library_root=library,
            journal=journal,
            scenario=_scenario(),
            resolved_seed=1234,
        )
    err = exc_info.value
    assert err.event_id == "move_missing"
    assert err.action is TimelineActionName.MOVE_ASSET
    assert err.asset_id == "asset_hd_main"
    # errno 2 = ENOENT (No such file or directory).
    assert err.payload["errno"] == 2
    assert err.payload["action"] == "move_asset"
    assert err.payload["event_id"] == "move_missing"
