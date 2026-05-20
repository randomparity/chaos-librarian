"""Layer 4 — Sprint 6 real-tool integration tests.

These tests exercise ``materialize_scenario`` against the actual ffmpeg
toolchain. Each one is gated by ``_ffmpeg_meets_minimum`` so the suite
skips cleanly on systems below the project minimum (e.g. macOS shipping
ffmpeg < 7.0). On an equipped runner they assert the on-disk shape of
the run-dir against the contracted manifest/report payloads.

The exit-criterion test for Sprint 6 lives here:
``test_identity_move_rename_end_to_end`` exercises the engine + phase-B
pipeline end-to-end against real bytes and proves the rename target is
the same content the materializer produced (same sha256, new path).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.materialization import FailureStage, FilesystemAction, Outcome
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer import filesystem as filesystem_mod
from chaos_librarian.materializer import run as run_mod
from chaos_librarian.materializer.capabilities import (
    MIN_VERSIONS,
    detect_capabilities,
)
from chaos_librarian.materializer.errors import (
    FilesystemActionError,
    TimelineUnsupportedError,
)
from chaos_librarian.materializer.run import materialize_scenario
from tests.integration.conftest import (
    _initial_sha256_for,
    _load_asset_report,
    _load_current_manifest,
    _load_materialization_report,
    _load_replay_bundle,
    sha256_of,
)

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _ffmpeg_meets_minimum() -> bool:
    caps = detect_capabilities()
    return caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum


pytestmark = pytest.mark.skipif(
    not _ffmpeg_meets_minimum(),
    reason=f"ffmpeg/ffprobe >= {MIN_VERSIONS['ffmpeg']} not available",
)


def test_identity_move_rename_end_to_end(tmp_path: Path) -> None:
    """EXIT CRITERION. Identity-move-rename runs end-to-end on a real directory.

    Move then rename must land the asset at ``movies-hd/Blazar.mkv`` and
    the file bytes must match what phase A produced (no re-encode happens
    during a filesystem-only timeline).
    """
    out_dir = tmp_path / "run-001"
    artifacts = materialize_scenario(
        FIXTURE_DIR / "identity-move-rename.yaml",
        out_dir,
    )
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS

    library = out_dir / "library"
    # The fixture's final event renames the asset to ``Blazar.mkv``;
    # update the path here if the fixture changes.
    final_path = library / "movies-hd" / "Blazar.mkv"
    assert final_path.exists()
    assert sha256_of(final_path) == _initial_sha256_for("asset_hd_main", out_dir)

    initial_path = library / "movies-hd" / "asset_hd_main.mkv"
    assert not initial_path.exists()

    manifest = _load_current_manifest(out_dir)
    asset_loc = next(loc for loc in manifest.locations if loc.asset_id == "asset_hd_main")
    assert asset_loc.path == "movies-hd/Blazar.mkv"

    asset_report = _load_asset_report(out_dir, "asset_hd_main")
    assert [e.action for e in asset_report.path_history] == [
        TimelineActionName.MOVE_ASSET,
        TimelineActionName.RENAME_FILE,
    ]

    materialization_report = _load_materialization_report(out_dir)
    assert len(materialization_report.filesystem_actions) == 2

    replay_bundle = _load_replay_bundle(out_dir)
    assert replay_bundle.applied_events == 2


def test_slow_copy_real_visibility(tmp_path: Path) -> None:
    """WHY: slow-copy commit must reveal the final file and clean up the
    ``.part`` staging path. The manifest must reflect the committed state
    (``temp_path=None``) and the on-disk bytes must hash to the value
    phase A recorded for the asset."""
    out_dir = tmp_path / "run-001"
    artifacts = materialize_scenario(
        FIXTURE_DIR / "slow-copy-materialize.yaml",
        out_dir,
    )
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS

    library = out_dir / "library"
    final_path = library / "movies-hd" / "Nova.mkv"
    part_path = library / "movies-hd" / "Nova.mkv.part"
    assert final_path.exists()
    assert not part_path.exists()

    manifest = _load_current_manifest(out_dir)
    asset_loc = next(loc for loc in manifest.locations if loc.asset_id == "asset_main")
    assert asset_loc.path == "movies-hd/Nova.mkv"
    assert asset_loc.temp_path is None

    asset_version = next(v for v in manifest.versions if v.asset_id == "asset_main")
    assert asset_version.content_hash == sha256_of(final_path)


def test_archive_file_real(tmp_path: Path) -> None:
    """WHY: archive_file with ``archive_root: null`` derives the destination
    from the primary root's ``<root_path>/archive/`` subdir; the on-disk
    layout must match the synthesized destination."""
    out_dir = tmp_path / "run-001"
    artifacts = materialize_scenario(
        FIXTURE_DIR / "archive-file.yaml",
        out_dir,
    )
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS

    library = out_dir / "library"
    # archive-file.yaml declares ``path: library/movies-hd`` so the
    # archive destination is ``library/movies-hd/archive/`` relative to
    # ``<out_dir>/library/``.
    archived = library / "library" / "movies-hd" / "archive" / "asset_hd_main.mkv"
    assert archived.exists()

    manifest = _load_current_manifest(out_dir)
    asset_loc = next(loc for loc in manifest.locations if loc.asset_id == "asset_hd_main")
    assert asset_loc.path == "library/movies-hd/archive/asset_hd_main.mkv"

    asset_report = _load_asset_report(out_dir, "asset_hd_main")
    assert [e.action for e in asset_report.path_history] == [TimelineActionName.ARCHIVE_FILE]


def test_archive_file_real_with_explicit_root(tmp_path: Path) -> None:
    """WHY: archive_file with a named ``archive_root`` resolves to that
    root's declared path; the on-disk file must land under it, not under
    the primary root's ``archive/`` subdir."""
    out_dir = tmp_path / "run-001"
    artifacts = materialize_scenario(
        FIXTURE_DIR / "archive-file-explicit-root.yaml",
        out_dir,
    )
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS

    library = out_dir / "library"
    archived = library / "library" / "cold-storage" / "asset_hd_main.mkv"
    assert archived.exists()
    not_under_primary = library / "library" / "movies-hd" / "archive" / "asset_hd_main.mkv"
    assert not not_under_primary.exists()

    manifest = _load_current_manifest(out_dir)
    asset_loc = next(loc for loc in manifest.locations if loc.asset_id == "asset_hd_main")
    assert asset_loc.path == "library/cold-storage/asset_hd_main.mkv"


def test_move_between_roots_real(tmp_path: Path) -> None:
    """WHY: move_between_roots crosses the asset to the destination root's
    declared path; both the on-disk layout and the manifest location
    must reflect the new root, with no remnant under the source root."""
    out_dir = tmp_path / "run-001"
    artifacts = materialize_scenario(
        FIXTURE_DIR / "move-between-roots.yaml",
        out_dir,
    )
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS

    library = out_dir / "library"
    moved = library / "library" / "cold-storage" / "asset_hd_main.mkv"
    source = library / "library" / "movies-hd" / "asset_hd_main.mkv"
    assert moved.exists()
    assert not source.exists()

    manifest = _load_current_manifest(out_dir)
    asset_loc = next(loc for loc in manifest.locations if loc.asset_id == "asset_hd_main")
    assert asset_loc.path == "library/cold-storage/asset_hd_main.mkv"

    asset_report = _load_asset_report(out_dir, "asset_hd_main")
    assert [e.action for e in asset_report.path_history] == [
        TimelineActionName.MOVE_BETWEEN_ROOTS,
    ]


def test_create_sidecar_real_via_timeline(tmp_path: Path) -> None:
    """WHY: a ``create_sidecar`` timeline event writes a deterministic SRT
    at the event's ``to:`` path and stamps the resulting hash on the
    matching ``ManifestSidecar`` row. The sidecar_id on that row must
    match the id the engine allocated (recorded in the journal's
    ``state_delta['sidecar_id']``).

    Post-#39 the rule no longer requires the timeline language to be
    declared on the asset; this fixture is a "timeline-only" sidecar
    (no declared subtitles). The manifest carries one row with the
    engine-allocated id and the phase-B content hash.
    """
    out_dir = tmp_path / "run-001"
    artifacts = materialize_scenario(
        FIXTURE_DIR / "sidecar-create-via-timeline.yaml",
        out_dir,
    )
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS

    srt_path = out_dir / "library" / "movies-hd" / "Pulsar.eng.srt"
    assert srt_path.exists()

    # Extract the engine-allocated sidecar_id from the create_sidecar
    # journal entry's state_delta. The lookup keys the manifest row by
    # id so the test pins the engine ↔ materializer ↔ manifest chain.
    journal_lines = (out_dir / "journal.jsonl").read_text().splitlines()
    create_entries = [
        json.loads(line)
        for line in journal_lines
        if json.loads(line).get("action") == "create_sidecar"
    ]
    assert len(create_entries) == 1
    timeline_sidecar_id = create_entries[0]["state_delta"]["sidecar_id"]

    manifest = _load_current_manifest(out_dir)
    timeline_row = next(s for s in manifest.sidecars if s.id == timeline_sidecar_id)
    assert timeline_row.asset_id == "asset_main"
    assert timeline_row.language == "eng"
    assert timeline_row.path == "movies-hd/Pulsar.eng.srt"
    assert (
        timeline_row.content_hash == "sha256:" + hashlib.sha256(srt_path.read_bytes()).hexdigest()
    )


def test_create_sidecar_collides_with_declared_subtitle(tmp_path: Path) -> None:
    """WHY: when an asset declares a sidecar AND the timeline emits a
    ``create_sidecar`` for the same ``(asset_id, language)``, phase A
    defers to phase B (#39): the timeline ``create_sidecar`` is the
    authoritative writer for that language, so phase A skips the
    declared write to avoid orphaning a file on disk. The manifest
    carries one row keyed by the engine-allocated sidecar_id; the
    phase-A declared file does NOT exist on disk.
    """
    out_dir = tmp_path / "run-001"
    artifacts = materialize_scenario(
        FIXTURE_DIR / "sidecar-collision.yaml",
        out_dir,
    )
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS

    library = out_dir / "library"
    declared_srt = library / "asset_main.eng.srt"
    timeline_srt = library / "movies-hd" / "Meridian.eng.timeline.srt"
    # Phase A skipped the declared write; only the timeline file landed.
    assert not declared_srt.exists()
    assert timeline_srt.exists()

    manifest = _load_current_manifest(out_dir)
    matching = [s for s in manifest.sidecars if s.asset_id == "asset_main" and s.language == "eng"]
    assert len(matching) == 1
    row = matching[0]
    # Engine-allocated id (``sidecar_<NNNN>``), NOT the synthetic
    # ``sidecar_<asset>_<lang>`` id ``augment_manifest`` would assign to
    # a declared-only sidecar.
    assert row.id != "sidecar_asset_main_eng"
    assert row.path == "movies-hd/Meridian.eng.timeline.srt"
    assert row.content_hash == "sha256:" + hashlib.sha256(timeline_srt.read_bytes()).hexdigest()


def test_phase_b_failure_cleans_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """WHY: an OSError raised inside phase B must wrap to
    ``FilesystemActionError`` and route through ``cleanup_failed_run``:
    ``library/`` is wiped, ``materialization.json`` records outcome
    ``fs_failed`` with a ``stage=filesystem`` failure whose
    ``invocation_index`` is ``None`` (filesystem stage is not a
    subprocess invocation).

    The trigger: pre-delete the asset's source file just before the
    first ``_dispatch_one`` call walks the journal; the first
    ``move_asset`` helper raises ``OSError`` from ``src.replace(dst)``.
    Sprint 7 replaced the single ``apply_phase_b`` orchestrator entry
    point with a per-entry dispatcher, so the trigger now hooks the
    first dispatch call instead of the outer walk.
    """
    original_dispatch = filesystem_mod._dispatch_one
    call_count = {"n": 0}

    def tampered_dispatch_one(
        ctx: filesystem_mod._PhaseBContext, entry: JournalEntry
    ) -> FilesystemAction | None:
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Identity-move-rename starts the asset at
            # ``library/movies-hd/asset_hd_main.mkv``; deleting it
            # before the first dispatch runs forces the first
            # ``move_asset`` helper to fail with ENOENT.
            (ctx.library_root / "movies-hd" / "asset_hd_main.mkv").unlink()
        return original_dispatch(ctx, entry)

    monkeypatch.setattr(filesystem_mod, "_dispatch_one", tampered_dispatch_one)
    monkeypatch.setattr(run_mod, "_dispatch_one", tampered_dispatch_one)

    out_dir = tmp_path / "run-001"
    with pytest.raises(FilesystemActionError):
        materialize_scenario(FIXTURE_DIR / "identity-move-rename.yaml", out_dir)

    # ``library/`` is wiped entirely on the fs_failed path (no empty
    # placeholder, unlike the tool_failed path).
    assert not (out_dir / "library").exists()

    report = _load_materialization_report(out_dir)
    assert report.outcome is Outcome.FS_FAILED
    assert report.failures
    fs_failures = [f for f in report.failures if f.stage is FailureStage.FILESYSTEM]
    assert len(fs_failures) == 1
    assert fs_failures[0].invocation_index is None


def test_mixed_supported_unsupported_action_rejected(tmp_path: Path) -> None:
    """WHY: ``preflight_timeline`` must reject any timeline that contains
    even one unsupported action before run-dir allocation; the
    lazy-allocation invariant means ``out_dir`` stays unallocated on
    rejection."""
    out_dir = tmp_path / "run-001"
    with pytest.raises(TimelineUnsupportedError) as exc_info:
        materialize_scenario(FIXTURE_DIR / "mixed-supported-unsupported.yaml", out_dir)
    assert exc_info.value.error_code == "E_MATERIALIZE_TIMELINE_UNSUPPORTED"
    assert exc_info.value.payload["action"] == "add_file"
    assert not out_dir.exists()
