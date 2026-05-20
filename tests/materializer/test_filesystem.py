"""Phase-B dispatcher tests for ``materializer/filesystem.py``.

One test per per-action helper, plus the dispatcher's contracts:
``OSError`` wraps into ``FilesystemActionError`` carrying the originating
event id, errno, and action; unknown actions are dropped silently so
future engine-only events do not crash phase B.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.scenario import Scenario, TimelineActionName
from chaos_librarian.materializer.errors import FilesystemActionError
from chaos_librarian.materializer.filesystem import apply_phase_b
from chaos_librarian.materializer.recipes import srt_payload
from tests.engine.conftest import _build_minimal_scenario
from tests.materializer.conftest import (
    _atomic_entry,
    _committed_entry,
    _started_entry,
)


def _scenario() -> Scenario:
    """Build the minimal Scenario every phase-B test shares."""
    return _build_minimal_scenario(
        roots=[
            ("movies-hd", "library/movies-hd"),
            ("cold-storage", "library/cold-storage"),
        ],
        works=[("work_001", "asset_hd_main", "mkv")],
        archive_root="archive",
    )


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
    actions, sidecar_hashes = apply_phase_b(
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
    actions, _ = apply_phase_b(
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
    actions, _ = apply_phase_b(
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
    actions, _ = apply_phase_b(
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
    actions, _ = apply_phase_b(
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
    actions, _ = apply_phase_b(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    assert not (library / "movies-hd" / "asset_hd_main.mkv").exists()
    assert (library / "cold-storage" / "asset_hd_main.mkv").read_bytes() == b"bytes"
    assert len(actions) == 1
    assert actions[0].action is TimelineActionName.MOVE_BETWEEN_ROOTS


def test_apply_create_sidecar_writes_srt_and_returns_hash_keyed_by_sidecar_id(
    tmp_path: Path,
) -> None:
    """WHY: create_sidecar must write a deterministic SRT body (so the
    manifest content_hash is reproducible across runs) AND return that
    body's sha256 keyed by sidecar_id (so manifest_build can stamp the
    ManifestSidecar row without re-reading the file)."""
    library = tmp_path / "library"
    library.mkdir()
    journal = [
        _atomic_entry(
            event_id="cs_001",
            action=TimelineActionName.CREATE_SIDECAR,
            target="asset_hd_main",
            state_delta={
                "sidecar_path": "movies-hd/asset_hd_main.en.srt",
                "sidecar_id": "sidecar_0001",
                "language": "en",
            },
        )
    ]
    actions, sidecar_hashes = apply_phase_b(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    written = (library / "movies-hd" / "asset_hd_main.en.srt").read_bytes()
    # The asset declared duration_seconds=1 in _build_minimal_scenario.
    expected_body = srt_payload(language="en", duration_s=1, seed=1234).encode("utf-8")
    assert written == expected_body
    assert "sidecar_0001" in sidecar_hashes
    # sha256 hex is exactly 64 chars.
    assert len(sidecar_hashes["sidecar_0001"]) == 64
    assert len(actions) == 1
    assert actions[0].action is TimelineActionName.CREATE_SIDECAR
    assert actions[0].to_path == "movies-hd/asset_hd_main.en.srt"


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
    actions, _ = apply_phase_b(
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
    actions, _ = apply_phase_b(
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
    apply_phase_b(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    assert (library / "movies-hd" / "elsewhere.mkv").read_bytes() == b"slow-copy bytes"
    assert not (library / "movies-hd" / "asset_hd_main.mkv").exists()
    assert not (library / "movies-hd" / "asset_hd_main.mkv.partial").exists()


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
    actions, sidecar_hashes = apply_phase_b(
        library_root=library,
        journal=journal,
        scenario=_scenario(),
        resolved_seed=1234,
    )
    assert actions == []
    assert sidecar_hashes == {}


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
        apply_phase_b(
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
