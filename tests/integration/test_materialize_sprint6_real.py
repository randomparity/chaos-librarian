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
from collections.abc import Sequence
from pathlib import Path

import pytest

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.materialization import FailureStage, FilesystemAction, Outcome
from chaos_librarian.contract.scenario import Scenario, TimelineActionName
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

    ``E_SIDECAR_LANGUAGE_INVALID`` requires the asset to declare the
    timeline event's language in ``asset.subtitles``; the fixture
    therefore declares one eng subtitle. The engine collapses the
    declared + timeline pair into a single ``ManifestSidecar`` row keyed
    by the timeline-allocated id (manifest v3 ``(asset_id, language)``
    uniqueness). The row's ``content_hash`` is the timeline (phase-B)
    file's hash, since ``augment_timeline_sidecars`` runs last.
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
    # Phase-B writes the timeline-sidecar hash as plain hex (no
    # ``sha256:`` prefix); phase-A asset hashing in synthesis.py uses
    # the ``sha256:`` prefix. Tracked as a follow-up — assert the actual
    # bytes-equivalent form here.
    assert timeline_row.content_hash == hashlib.sha256(srt_path.read_bytes()).hexdigest()


def test_create_sidecar_collides_with_declared_subtitle(tmp_path: Path) -> None:
    """WHY: when an asset declares a sidecar AND the timeline emits a
    ``create_sidecar`` for the same ``(asset_id, language)``, BOTH files
    must land on disk — the declared one at
    ``library/<asset_id>.<lang>.srt`` (phase A) and the timeline one at
    the event's ``to:`` path (phase B). The manifest v3 invariant pins
    ``(asset_id, language)`` to a single ``ManifestSidecar`` row, so the
    two files share a single row whose ``content_hash`` reflects the
    phase-B bytes (``augment_timeline_sidecars`` runs last in
    ``run.py``). This collapse is correct per the manifest contract,
    but it leaves the phase-A file orphaned from the manifest — tracked
    as a follow-up issue.
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
    assert declared_srt.exists()
    assert timeline_srt.exists()

    manifest = _load_current_manifest(out_dir)
    matching = [s for s in manifest.sidecars if s.asset_id == "asset_main" and s.language == "eng"]
    # Manifest v3 keys ``ManifestSidecar`` uniquely on
    # ``(asset_id, language)``; the engine+materializer collapse the
    # declared + timeline pair into a single row.
    assert len(matching) == 1
    row = matching[0]
    # Engine-allocated id (``sidecar_<NNNN>``), NOT the synthetic
    # ``sidecar_<asset>_<lang>`` id ``augment_manifest`` would assign to
    # a declared-only sidecar.
    assert row.id != "sidecar_asset_main_eng"
    assert row.path == "movies-hd/Meridian.eng.timeline.srt"
    # Manifest row's ``content_hash`` reflects the phase-B bytes
    # (``augment_timeline_sidecars`` overwrote any phase-A value).
    assert row.content_hash == hashlib.sha256(timeline_srt.read_bytes()).hexdigest()


def test_phase_b_failure_cleans_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """WHY: an OSError raised inside phase B must wrap to
    ``FilesystemActionError`` and route through ``cleanup_failed_run``:
    ``library/`` is wiped, ``materialization.json`` records outcome
    ``fs_failed`` with a ``stage=filesystem`` failure whose
    ``invocation_index`` is ``None`` (filesystem stage is not a
    subprocess invocation).

    The trigger: pre-delete the asset's source file just before
    ``apply_phase_b`` walks the journal; the first ``move_asset`` helper
    raises ``OSError`` from ``src.replace(dst)``.
    """
    original_apply = filesystem_mod.apply_phase_b

    def tampered_apply_phase_b(
        *,
        library_root: Path,
        journal: Sequence[JournalEntry],
        scenario: Scenario,
        resolved_seed: int,
    ) -> tuple[list[FilesystemAction], dict[str, str]]:
        # Identity-move-rename starts the asset at
        # ``library/movies-hd/asset_hd_main.mkv``; deleting it before
        # phase B starts forces the first move_asset to fail.
        (library_root / "movies-hd" / "asset_hd_main.mkv").unlink()
        return original_apply(
            library_root=library_root,
            journal=journal,
            scenario=scenario,
            resolved_seed=resolved_seed,
        )

    monkeypatch.setattr(run_mod, "apply_phase_b", tampered_apply_phase_b)

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
    assert exc_info.value.payload["action"] == "reencode_video"
    assert not out_dir.exists()
