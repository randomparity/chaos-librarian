"""Importer unit tests — scan, topology, staging, emit (no ffprobe needed).

Why: the importer turns a real directory into a scenario bundle; these
tests pin the deterministic classification conventions (spec + ADR 0012)
with a stubbed prober so a missing ffprobe cannot mask logic regressions.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import cast

import pytest

from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
from chaos_librarian.contract.validation import ValidationIssue, ValidationSeverity
from chaos_librarian.importer import emit
from chaos_librarian.importer.emit import (
    ImportReport,
    apply_work_caps,
    compute_staging,
    emit_import_bundle,
    plan_staging,
)
from chaos_librarian.importer.probe_input import ProbedInput, probe_inputs
from chaos_librarian.importer.scan import ScannedFile, SkipRecord, scan_directory
from chaos_librarian.importer.topology import ImportedWork, build_topology

# ---- scan -------------------------------------------------------------------


def test_scan_classifies_by_case_insensitive_suffix(tmp_path: Path) -> None:
    (tmp_path / "Movie.MKV").write_bytes(b"x")
    (tmp_path / "song.FLAC").write_bytes(b"x")
    (tmp_path / "sub.SRT").write_bytes(b"x")
    (tmp_path / "movie.nfo").write_bytes(b"x")
    (tmp_path / "poster.JPG").write_bytes(b"x")
    (tmp_path / "cue.CUE").write_bytes(b"x")
    (tmp_path / "junk.txt").write_bytes(b"x")

    scanned, skipped = scan_directory(tmp_path)
    kinds = {f.path.name: f.kind for f in scanned}
    assert kinds["Movie.MKV"] == "video"
    assert kinds["song.FLAC"] == "audio"
    assert kinds["sub.SRT"] == "subtitle"
    assert kinds["movie.nfo"] == "nfo"
    assert kinds["poster.JPG"] == "poster"
    assert {s.path.name for s in skipped} == {"cue.CUE", "junk.txt"}
    assert all(s.reason == "unrecognized" for s in skipped)


def test_scan_skips_hidden_dirs(tmp_path: Path) -> None:
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "Movie.mkv").write_bytes(b"x")
    scanned, _ = scan_directory(tmp_path)
    assert scanned == []


# ---- probe (stubbed) ---------------------------------------------------------


@pytest.fixture
def stub_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub probe_file with canned ProbedMedia for any input."""

    def _fake(path: Path, *, self_contained_only: bool = False) -> ProbedMedia:
        assert self_contained_only
        return ProbedMedia(
            container=path.suffix.lstrip(".").lower(),
            duration_seconds=1.0,
            size_bytes=8,
            streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480)],
        )

    monkeypatch.setattr("chaos_librarian.importer.probe_input.probe_file", _fake)


def _probed_video(path: Path, sha: str) -> ProbedInput:
    return ProbedInput(
        scanned=ScannedFile(path=path, kind="video"),
        probed=ProbedMedia(
            container="mkv",
            duration_seconds=1.0,
            size_bytes=8,
            streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480)],
        ),
        sha256=sha,
    )


def _probed_audio(path: Path, sha: str) -> ProbedInput:
    return ProbedInput(
        scanned=ScannedFile(path=path, kind="audio"),
        probed=ProbedMedia(
            container="flac",
            duration_seconds=1.0,
            size_bytes=8,
            streams=[ProbedStream(kind=StreamKind.AUDIO, codec="flac")],
        ),
        sha256=sha,
    )


def _probe_media_files(paths: list[ScannedFile]) -> tuple[list[ProbedInput], list[SkipRecord]]:
    media = [s for s in paths if s.kind in {"video", "audio"}]
    return probe_inputs(media)


def _sidecars_of(scanned: list[ScannedFile]) -> list[ScannedFile]:
    return [s for s in scanned if s.kind not in {"video", "audio"}]


def test_topology_movie_folder_with_variants_and_sidecars(tmp_path: Path, stub_probe: None) -> None:
    movie_dir = tmp_path / "The Matrix"
    movie_dir.mkdir()
    a = movie_dir / "The Matrix.mkv"
    b = movie_dir / "The Matrix.mp4"
    a.write_bytes(b"a" * 8)
    b.write_bytes(b"b" * 8)
    (movie_dir / "The Matrix.en.srt").write_text("1\n00:00:00,000 --> 00:00:01,000\nhi\n")
    (movie_dir / "The Matrix.srt").write_text("dup\n")  # same (video, lang)
    (movie_dir / "poster.jpg").write_bytes(b"p")

    scanned, _skips = scan_directory(tmp_path)
    probed, probe_skips = _probe_media_files(scanned)
    works, skips = build_topology(probed, _sidecars_of(scanned), tmp_path)

    assert len(works) == 1
    work = works[0]
    assert work.kind == "movie"
    assert work.payload["layout"] == "movie_folder"
    assert len(work.asset_payloads) == 2
    skip_pairs = {(s.path.name, s.reason) for s in skips}
    assert ("The Matrix.srt", "sidecar_duplicate") in skip_pairs

    subtitle_events = [
        e for e in work.sidecar_events if isinstance(e, dict) and e.get("kind") == "subtitle"
    ]
    assert len(subtitle_events) == 1
    first = subtitle_events[0]
    assert first["language"] == "en"
    assert str(first["body"]).startswith("1\n")
    poster_events = [
        e for e in work.sidecar_events if isinstance(e, dict) and e.get("kind") == "poster"
    ]
    assert len(poster_events) == 1
    assert poster_events[0]["image_format"] == "jpeg"
    assert probe_skips == []


def test_topology_season_folders(tmp_path: Path, stub_probe: None) -> None:
    season = tmp_path / "Friends" / "Season 01"
    season.mkdir(parents=True)
    (season / "S01E01 - Pilot.mkv").write_bytes(b"1" * 8)
    (season / "S01E02 - Beach.mkv").write_bytes(b"2" * 8)
    (season / "Episode 3.mkv").write_bytes(b"3" * 8)  # unparseable

    scanned, _ = scan_directory(tmp_path)
    probed, _ = _probe_media_files(scanned)
    works, skips = build_topology(probed, [], tmp_path)

    assert len(works) == 1
    assert works[0].kind == "series"
    seasons = works[0].payload["seasons"]
    assert isinstance(seasons, list)
    assert len(seasons) == 1
    first_season = cast("dict[str, object]", seasons[0])
    episodes = first_season["episodes"]
    assert isinstance(episodes, list)
    assert len(episodes) == 2
    assert any(s.reason == "topology:no_anchor" for s in skips)


def test_topology_duplicate_episode_skipped(tmp_path: Path, stub_probe: None) -> None:
    season = tmp_path / "Show" / "Season 1"
    season.mkdir(parents=True)
    (season / "S01E05 - Cut.mkv").write_bytes(b"1" * 8)
    (season / "S01E05 - Other Cut.mkv").write_bytes(b"2" * 8)

    scanned, _ = scan_directory(tmp_path)
    probed, _ = _probe_media_files(scanned)
    works, skips = build_topology(probed, [], tmp_path)
    assert len(works) == 1
    seasons = works[0].payload["seasons"]
    assert isinstance(seasons, list)
    first = cast("dict[str, object]", seasons[0])
    assert len(cast("list[object]", first["episodes"])) == 1
    assert any(s.reason == "topology:duplicate_episode" for s in skips)


def test_topology_season_at_root_is_unanchored(tmp_path: Path, stub_probe: None) -> None:
    season = tmp_path / "Season 02"
    season.mkdir()
    (season / "S02E01.mkv").write_bytes(b"x" * 8)
    scanned, _ = scan_directory(tmp_path)
    probed, _ = _probe_media_files(scanned)
    works, skips = build_topology(probed, [], tmp_path)
    assert works == []
    assert [s.reason for s in skips] == ["topology:no_anchor"]


def test_topology_music_and_unanchored_audio(tmp_path: Path, stub_probe: None) -> None:
    album = tmp_path / "Artist" / "Album"
    album.mkdir(parents=True)
    (album / "01 Song.flac").write_bytes(b"1" * 8)
    (tmp_path / "Loose.flac").write_bytes(b"2" * 8)
    bare_artist = tmp_path / "Bare"
    bare_artist.mkdir()
    (bare_artist / "NoAlbum.flac").write_bytes(b"3" * 8)

    scanned, _ = scan_directory(tmp_path)
    probed, _ = _probe_media_files(scanned)
    works, skips = build_topology(probed, [], tmp_path)

    assert len(works) == 1
    assert works[0].kind == "artist"
    albums = works[0].payload["albums"]
    assert isinstance(albums, list)
    assert len(albums) == 1
    first_album = cast("dict[str, object]", albums[0])
    discs = first_album["discs"]
    assert isinstance(discs, list)
    first_disc = cast("dict[str, object]", discs[0])
    assert len(cast("list[object]", first_disc["tracks"])) == 1
    assert [s.reason for s in skips] == ["topology:no_anchor", "topology:no_anchor"]


def test_orphaned_sidecar_reported(tmp_path: Path, stub_probe: None) -> None:
    (tmp_path / "Lonely.srt").write_text("x\n")
    movie = tmp_path / "Other Movie.mkv"
    movie.write_bytes(b"x" * 8)

    scanned, _ = scan_directory(tmp_path)
    probed, _ = _probe_media_files(scanned)
    sidecars = _sidecars_of(scanned)
    works, skips = build_topology(probed, sidecars, tmp_path)
    assert len(works) == 1
    assert [s.reason for s in skips] == ["orphaned_sidecar"]


# ---- staging / caps -----------------------------------------------------------


def _work_with_assets(count: int) -> ImportedWork:
    work = ImportedWork(kind="movie", id="w", payload={"id": "w", "variants": []})
    for i in range(count):
        asset_id = f"imp-{i}"
        work.asset_payloads.append(
            {"id": asset_id, "import_source": {"path": f"__BUNDLE__#{i:064x}"}}
        )
        work.asset_sources[asset_id] = Path(f"/x/{i}.mkv")
    return work


def test_work_caps_trim_variants_then_works() -> None:
    work_a = _work_with_assets(3)
    work_b = _work_with_assets(1)
    works = [work_a, work_b]
    skips: list[SkipRecord] = []
    apply_work_caps(works, skips, mode="full", max_works=2, max_variants=2)
    assert len(works) == 2
    assert len(work_a.asset_payloads) == 2
    assert [s.reason for s in skips].count("cap:max_variants") == 1


def test_plan_staging_duration_cap() -> None:
    slow = _probed_video(Path("/x/slow.mkv"), "a" * 64)
    slow.probed.duration_seconds = 99.0
    fast = _probed_video(Path("/x/fast.mkv"), "b" * 64)
    accepted, skips = plan_staging(
        [slow, fast], [], mode="full", max_works=None, max_duration_s=5.0
    )
    assert [i.scanned.path for i in accepted] == [Path("/x/fast.mkv")]
    assert [s.reason for s in skips] == ["cap:max_duration_s"]


def test_compute_staging_dedups_by_content() -> None:
    work = ImportedWork(kind="movie", id="w", payload={})
    shared = "c" * 64
    other_digest = "d" * 64
    for i, digest in enumerate((shared, shared, other_digest)):
        work.asset_payloads.append(
            {"id": f"a{i}", "import_source": {"path": f"__BUNDLE__#{digest}"}}
        )
    same_content_a = _probed_video(Path("/x/a.mkv"), shared)
    same_content_b = _probed_video(Path("/x/a2.mkv"), shared)
    other = _probed_video(Path("/x/b.mkv"), other_digest)
    staged, seen = compute_staging([same_content_a, same_content_b, other], [work])
    assert len(staged) == 2
    assert seen == {shared, other_digest}


# ---- emit ---------------------------------------------------------------------


def _prepare_works(
    tmp_path: Path,
) -> tuple[list[ImportedWork], list[tuple[Path, Path]], list[SkipRecord], Path]:
    movie_dir = tmp_path / "input" / "My Film"
    movie_dir.mkdir(parents=True)
    source = movie_dir / "My Film.mkv"
    source.write_bytes(b"media-bytes")

    scanned, _ = scan_directory(movie_dir)
    probed, _ = _probe_media_files(scanned)
    works, skips = build_topology(probed, _sidecars_of(scanned), movie_dir)
    accepted, all_skips = plan_staging(
        probed, skips, mode="full", max_works=None, max_duration_s=None
    )
    staged, _seen = compute_staging(accepted, works)
    return works, staged, all_skips, source


def test_emit_writes_bundle_and_validates(tmp_path: Path, stub_probe: None) -> None:
    works, staged, skips, source = _prepare_works(tmp_path)
    out = tmp_path / "out" / "scenario.yaml"
    report: ImportReport = emit_import_bundle(tmp_path / "input", out, works, staged, skips)

    assert out.exists()
    yaml_text = out.read_text()
    assert "schema_version: 34" in yaml_text
    assert "import_source" in yaml_text
    bundle_file = next((tmp_path / "out" / "media").glob("*.mkv"))
    assert bundle_file.read_bytes() == source.read_bytes()
    assert report.files_imported == 1
    assert report.works["movies"] == 1


def test_emit_rolls_back_on_validation_failure(
    tmp_path: Path, stub_probe: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken_run_validation(run_input: object):
        return type(
            "R",
            (),
            {
                "ok": False,
                "issues": [
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        code="E_TEST",
                        message="boom",
                        line=None,
                        column=None,
                        path=None,
                    )
                ],
            },
        )()

    monkeypatch.setattr("chaos_librarian.importer.emit.run_validation", broken_run_validation)
    works, staged, skips, _source = _prepare_works(tmp_path)
    out = tmp_path / "out" / "scenario.yaml"
    with pytest.raises(ValueError, match="failed validation"):
        emit_import_bundle(tmp_path / "input", out, works, staged, skips)
    assert not out.exists()
    bundle_dir = tmp_path / "out" / "media"
    assert not bundle_dir.exists() or not any(bundle_dir.iterdir())


def test_probe_hashes_without_reading_entire_media(
    tmp_path: Path, stub_probe: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "movie.mkv"
    source.write_bytes(b"media")

    def reject_read_bytes(path: Path) -> bytes:
        raise AssertionError("real media must be hashed with bounded memory")

    monkeypatch.setattr(Path, "read_bytes", reject_read_bytes)
    probed, skips = probe_inputs([ScannedFile(source, "video")])
    assert len(probed) == 1
    assert skips == []


@pytest.mark.parametrize("failure", ["validation", "copy", "publication"])
def test_emit_rollback_preserves_existing_bundle_and_yaml(
    tmp_path: Path, stub_probe: None, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    works, staged, skips, source = _prepare_works(tmp_path)
    out = tmp_path / "out" / "scenario.yaml"
    bundle = out.parent / "media"
    bundle.mkdir(parents=True)
    existing = bundle / staged[0][1]
    existing.write_bytes(source.read_bytes())
    if failure == "publication":
        out.write_bytes(b"another scenario")
    elif failure == "validation":

        def fail_report(*args: object) -> None:
            raise ValueError("forced validation error")

        monkeypatch.setattr(emit, "_build_report", fail_report)
    else:
        second = source.with_name("second.mkv")
        second.write_bytes(b"second")
        staged.append((second, Path("second.mkv")))
        original_copy = emit.shutil.copyfileobj

        def partial_copy(src, dst, *args):
            if src.name == str(second):
                dst.write(b"partial")
                raise OSError("forced disk error")
            return original_copy(src, dst, *args)

        monkeypatch.setattr(emit.shutil, "copyfileobj", partial_copy)
    with pytest.raises((ValueError, OSError)):
        emit_import_bundle(tmp_path / "input", out, works, staged, skips)
    assert existing.read_bytes() == source.read_bytes()
    assert sorted(p.name for p in bundle.iterdir()) == [existing.name]
    if failure == "publication":
        assert out.read_bytes() == b"another scenario"
    else:
        assert not out.exists()


def test_sidecar_matches_full_stem_and_preserves_line_endings(tmp_path: Path) -> None:
    (tmp_path / "Film.mkv").write_bytes(b"a")
    (tmp_path / "Film Two.mkv").write_bytes(b"b")
    subtitle = tmp_path / "Film Two.en.srt"
    subtitle.write_bytes(b"1\r\n00:00:00,000 --> 00:00:01,000\r\noriginal\r\n")
    works, skips = build_topology(
        [
            _probed_video(tmp_path / "Film.mkv", "a" * 64),
            _probed_video(tmp_path / "Film Two.mkv", "b" * 64),
        ],
        [ScannedFile(subtitle, "subtitle")],
        tmp_path,
    )
    event = works[0].sidecar_events[0]
    assert works[0].asset_sources[str(event["target"])] == tmp_path / "Film Two.mkv"
    assert str(event["body"]).encode() == subtitle.read_bytes()
    assert skips == []


def test_scan_rejects_special_files_without_opening_them(tmp_path: Path) -> None:
    fifo = tmp_path / "Movie.nfo"
    os.mkfifo(fifo)
    scanned, skips = scan_directory(tmp_path)
    assert scanned == []
    assert skips == [SkipRecord(fifo, "unrecognized")]


def test_emit_rejects_source_changes_after_hashing(tmp_path: Path, stub_probe: None) -> None:
    works, staged, skips, source = _prepare_works(tmp_path)
    source.write_bytes(b"changed after probing")
    out = tmp_path / "out" / "scenario.yaml"
    with pytest.raises(ValueError, match="source changed"):
        emit_import_bundle(tmp_path / "input", out, works, staged, skips)
    assert not out.exists()
    assert not list((out.parent / "media").iterdir())


@pytest.mark.parametrize("existing_bundle", [False, True])
@pytest.mark.parametrize("failure", ["io", "race"])
def test_mapping_publication_failure_rolls_back_only_owned_outputs(
    tmp_path: Path,
    stub_probe: None,
    monkeypatch: pytest.MonkeyPatch,
    existing_bundle: bool,
    failure: str,
) -> None:
    works, staged, skips, source = _prepare_works(tmp_path)
    out = tmp_path / "out" / "scenario.yaml"
    bundle = out.parent / "media"
    bundle.mkdir(parents=True)
    existing = bundle / staged[0][1]
    if existing_bundle:
        existing.write_bytes(source.read_bytes())
    mapping = tmp_path / "mapping.json"
    original_write = emit._atomic_write

    def fail_mapping(path: Path, data: bytes) -> None:
        if path == mapping:
            if failure == "race":
                mapping.write_bytes(b"other writer")
                return original_write(path, data)
            raise OSError("mapping disk error")
        return original_write(path, data)

    monkeypatch.setattr(emit, "_atomic_write", fail_mapping)
    with pytest.raises(OSError, match="File exists" if failure == "race" else "mapping disk error"):
        emit_import_bundle(tmp_path / "input", out, works, staged, skips, mapping_out=mapping)
    assert not out.exists()
    assert sorted(bundle.iterdir()) == ([existing] if existing_bundle else [])
    if failure == "race":
        assert mapping.read_bytes() == b"other writer"
    else:
        assert not mapping.exists()
    assert source.read_bytes() == b"media-bytes"


def test_emitter_rejects_mapping_collision_before_staging(tmp_path: Path, stub_probe: None) -> None:
    works, staged, skips, _source = _prepare_works(tmp_path)
    out = tmp_path / "out" / "scenario.yaml"
    out.parent.mkdir()
    with pytest.raises(ValueError, match="mapping"):
        emit_import_bundle(tmp_path / "input", out, works, staged, skips, mapping_out=out)
    assert not (out.parent / "media").exists()


def test_emitter_chaos_uses_only_surviving_topology(tmp_path: Path, stub_probe: None) -> None:
    timelines = []
    for extra_capped_work in (False, True):
        root = tmp_path / str(extra_capped_work) / "input"
        movie = root / "aaa"
        movie.mkdir(parents=True)
        (movie / "aaa.mkv").write_bytes(b"first media")
        (movie / "aaa.nfo").write_text("sidecar")
        if extra_capped_work:
            dropped = root / "import-chaos-0001"
            dropped.mkdir()
            (dropped / "dropped.mkv").write_bytes(b"different media")
        scanned, _ = scan_directory(root)
        probed, _ = _probe_media_files(scanned)
        works, skips = build_topology(probed, _sidecars_of(scanned), root)
        apply_work_caps(works, skips, mode="full", max_works=1, max_variants=4)
        staged, _ = compute_staging(probed, works)
        out = root.parent / "out" / "scenario.yaml"
        emit_import_bundle(root, out, works, staged, skips, chaos_seed=42, chaos_events=3)
        run_input = emit.prepare_run_input_from_bytes(
            raw_bytes=out.read_bytes(), source_label="test"
        )
        assert emit.run_validation(run_input).ok
        scenario = run_input.scenario
        assert scenario is not None
        assert scenario.seed == 42
        assert len(scenario.timeline) == 4
        assert scenario.timeline[0].action == "create_sidecar"
        assert scenario.timeline[1].action == "rename_file"
        assert scenario.timeline[1].id == "import-chaos-0001"
        timelines.append([event.model_dump(mode="json") for event in scenario.timeline])
    assert timelines[0] == timelines[1]


def test_emitter_chaos_preserves_mixed_import_topology(tmp_path: Path, stub_probe: None) -> None:
    root = tmp_path / "input"
    for name in ("Film/Film.mkv", "Show/Season 01/Show S01E01.mkv", "Artist/Album/01 Song.flac"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(name.encode())
    scanned, _ = scan_directory(root)
    probed, _ = _probe_media_files(scanned)
    works, skips = build_topology(probed, [], root)
    staged, _ = compute_staging(probed, works)
    out = tmp_path / "out" / "scenario.yaml"
    report = emit_import_bundle(root, out, works, staged, skips, chaos_seed=1, chaos_events=40)
    assert report.works == {"movies": 1, "series": 1, "artists": 1}
    run_input = emit.prepare_run_input_from_bytes(raw_bytes=out.read_bytes(), source_label="test")
    assert emit.run_validation(run_input).ok
    assert run_input.scenario is not None
    assert len(run_input.scenario.timeline) == 40
    assert {event.action for event in run_input.scenario.timeline} == {
        "rename_file",
        "move_asset",
        "touch_mtime",
    }
