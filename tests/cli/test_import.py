"""CLI tests for the ``import`` command (issue #105).

Why: the command's exit-code contract (0/1/2/4) and JSON report shape are
consumer-facing; these tests pin them without requiring ffprobe (the prober
is stubbed).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.cli.commands import import_media
from chaos_librarian.contract import CAPABILITIES_SCHEMA_VERSION
from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.content_sources import ContentSourceCapabilities
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
from chaos_librarian.importer import probe_input
from chaos_librarian.topology import iter_asset_contexts
from chaos_librarian.validation.input import prepare_run_input_from_bytes

runner = CliRunner()


@pytest.fixture
def media_dir(tmp_path: Path) -> Path:
    movie = tmp_path / "input" / "My Film"
    movie.mkdir(parents=True)
    (movie / "My Film.mkv").write_bytes(b"media-bytes")
    return tmp_path / "input"


@pytest.fixture
def stub_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake(path: Path, *, self_contained_only: bool = False) -> ProbedMedia:
        assert self_contained_only
        return ProbedMedia(
            container="mkv",
            duration_seconds=1.0,
            size_bytes=8,
            streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480)],
        )

    monkeypatch.setattr(probe_input, "probe_file", fake)


def _stub_capabilities_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_detect() -> Capabilities:
        return Capabilities(
            schema_version=CAPABILITIES_SCHEMA_VERSION,
            ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x", meets_minimum=True),
            ffprobe=ToolStatus(found=True, version="7.1.1", path="/x", meets_minimum=True),
            mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
            platform="test",
            content_sources=ContentSourceCapabilities(),
            ready_for=ReadyFor(
                materialize_static=True,
                materialize_filesystem_mutations=True,
                materialize_media_mutations=False,
                materialize_hevc_video=True,
                materialize_hdr_video=True,
                materialize_resolution_switch_video=True,
                materialize_audio_recipes=True,
                materialize_matroska_muxing_profiles=True,
                materialize_webm_video=True,
            ),
        )

    monkeypatch.setattr(import_media, "detect_capabilities", fake_detect)


def _stub_capabilities_no_ffprobe(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_detect() -> Capabilities:
        return Capabilities(
            schema_version=CAPABILITIES_SCHEMA_VERSION,
            ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x", meets_minimum=True),
            ffprobe=ToolStatus(found=False, meets_minimum=False),
            mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
            platform="test",
            content_sources=ContentSourceCapabilities(),
            ready_for=ReadyFor(
                materialize_static=False,
                materialize_filesystem_mutations=False,
                materialize_media_mutations=False,
                materialize_hevc_video=False,
                materialize_hdr_video=False,
                materialize_resolution_switch_video=False,
                materialize_audio_recipes=False,
                materialize_matroska_muxing_profiles=False,
                materialize_webm_video=False,
            ),
        )

    monkeypatch.setattr(import_media, "detect_capabilities", fake_detect)


def test_import_help_lists_command() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "import" in result.output


def test_import_rejects_existing_out(media_dir: Path, tmp_path: Path) -> None:
    existing = tmp_path / "scenario.yaml"
    existing.write_text("x")
    result = runner.invoke(app, ["import", str(media_dir), "--out", str(existing)])
    assert result.exit_code == 2
    assert "already exists" in result.output


def test_import_rejects_bad_mode(media_dir: Path, tmp_path: Path) -> None:
    result = runner.invoke(
        app, ["import", str(media_dir), "--out", str(tmp_path / "s.yaml"), "--mode", "chaos"]
    )
    assert result.exit_code == 2


def test_import_requires_ffprobe(
    media_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_capabilities_no_ffprobe(monkeypatch)
    result = runner.invoke(
        app,
        [
            "import",
            str(media_dir),
            "--out",
            str(tmp_path / "s.yaml"),
            "--json",
        ],
    )
    assert result.exit_code == 4
    payload = json.loads(result.output)
    assert payload["error_code"] == "E_IMPORT_FAILED"


def test_import_empty_dir_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_capabilities_ok(monkeypatch)
    empty = tmp_path / "empty-input"
    empty.mkdir()
    result = runner.invoke(
        app,
        ["import", str(empty), "--out", str(tmp_path / "s.yaml"), "--json"],
    )
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["error_code"] == "E_IMPORT_FAILED"


def test_import_success_json_report(
    media_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_probe: None,
) -> None:
    _stub_capabilities_ok(monkeypatch)
    out = tmp_path / "out" / "scenario.yaml"
    out.parent.mkdir(parents=True)
    result = runner.invoke(app, ["import", str(media_dir), "--out", str(out), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["files_imported"] == 1
    assert payload["works"]["movies"] == 1
    assert out.exists()
    assert (out.parent / "media").is_dir()
    assert set(payload) == {
        "scenario_path",
        "bundle_dir",
        "files_scanned",
        "files_imported",
        "files_skipped",
        "works",
        "sidecars",
        "bundle_bytes",
        "warnings",
    }
    assert sorted(p.name for p in out.parent.iterdir()) == ["media", "scenario.yaml"]


def test_import_success_human_output(
    media_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_probe: None,
) -> None:
    _stub_capabilities_ok(monkeypatch)
    out = tmp_path / "scenario.yaml"
    result = runner.invoke(app, ["import", str(media_dir), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "import: wrote" in result.output


@pytest.mark.parametrize(
    ("files", "options", "imported", "skip_reason"),
    [
        (["Artist/Album/01 Song.flac"], [], 1, None),
        (["Artist/Album/Disc 01/01 Song.flac", "Artist/Album/Disc 02/01 Song.flac"], [], 2, None),
        (["Show/Season 01/S01E01 Pilot.mkv", "Show/Season 02/S02E01 Return.mkv"], [], 2, None),
        ([f"Show/Season 01/S01E{i:02d} Episode.mkv" for i in range(1, 7)], [], 6, None),
        (["A/A.mkv", "B/B.mkv"], ["--mode", "dedup"], 1, "mode:duplicate"),
        (["A/A.mkv", "B/B.mkv"], ["--max-works", "1"], 1, "cap:max_works"),
        (["A/A.mkv", "A/B.mkv"], ["--max-variants", "1"], 1, "cap:max_variants"),
        (["A/A.mkv"], ["--max-duration-s", "2"], 1, None),
        (
            ["A/A.mkv", "B/B.mkv"],
            ["--mode", "sample", "--max-works", "1"],
            1,
            "cap:max_works_sample",
        ),
    ],
)
def test_import_topology_and_modes_emit_valid_scenarios(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stub_probe: None,
    files: list[str],
    options: list[str],
    imported: int,
    skip_reason: str | None,
) -> None:
    _stub_capabilities_ok(monkeypatch)
    root = tmp_path / "input"
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"same original")
    result = runner.invoke(
        app,
        [
            "import",
            str(root),
            "--out",
            str(tmp_path / "s.yaml"),
            "--json",
            *options,
            "--mapping-out",
            str(tmp_path / "mapping.json"),
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["files_imported"] == imported
    if skip_reason:
        assert skip_reason in {item["reason"] for item in report["files_skipped"]}
    mapping = json.loads((tmp_path / "mapping.json").read_text())
    scenario = prepare_run_input_from_bytes(
        raw_bytes=(tmp_path / "s.yaml").read_bytes(), source_label="<test>"
    ).scenario
    assert scenario is not None
    assert set(mapping.values()) == {c.asset.id for c in iter_asset_contexts(scenario)}
    assert len(mapping) == imported
    assert set(mapping) == set(files) - {
        Path(item["path"]).relative_to(root).as_posix() for item in report["files_skipped"]
    }


def test_import_duration_cap_filters_before_emitting_topology(
    media_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _stub_capabilities_ok(monkeypatch)
    long_file = media_dir / "Long" / "Long.mkv"
    long_file.parent.mkdir()
    long_file.write_bytes(b"long")

    def fake(path: Path, *, self_contained_only: bool = False) -> ProbedMedia:
        assert self_contained_only
        return ProbedMedia(
            container="mkv",
            duration_seconds=10 if path == long_file else 1,
            size_bytes=4,
            streams=[],
        )

    monkeypatch.setattr(probe_input, "probe_file", fake)
    result = runner.invoke(
        app,
        [
            "import",
            str(media_dir),
            "--out",
            str(tmp_path / "s.yaml"),
            "--max-duration-s",
            "2",
            "--mapping-out",
            str(tmp_path / "mapping.json"),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["files_imported"] == 1
    assert report["files_skipped"] == [{"path": str(long_file), "reason": "cap:max_duration_s"}]
    assert set(json.loads((tmp_path / "mapping.json").read_text())) == {"My Film/My Film.mkv"}


def test_import_variant_cap_keeps_only_surviving_sidecars(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_probe: None
) -> None:
    _stub_capabilities_ok(monkeypatch)
    root = tmp_path / "input"
    root.mkdir()
    (root / "A.mkv").write_bytes(b"a")
    (root / "B.mkv").write_bytes(b"b")
    (root / "B.en.srt").write_text("subtitle")
    result = runner.invoke(
        app,
        ["import", str(root), "--out", str(tmp_path / "s.yaml"), "--max-variants", "1", "--json"],
    )
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["sidecars"]["subtitles"] == 0
    assert {item["reason"] for item in report["files_skipped"]} == {
        "cap:max_variants",
        "orphaned_sidecar",
    }


def test_import_sanitizes_input_and_sidecar_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_probe: None
) -> None:
    _stub_capabilities_ok(monkeypatch)
    root = tmp_path / "input\nname"
    root.mkdir()
    (root / "Film\nName.mkv").write_bytes(b"media")
    (root / "Film\nName.en.srt").write_text("subtitle")
    result = runner.invoke(app, ["import", str(root), "--out", str(tmp_path / "s.yaml"), "--json"])
    assert result.exit_code == 0, result.output


def test_import_disambiguates_slug_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_probe: None
) -> None:
    _stub_capabilities_ok(monkeypatch)
    root = tmp_path / "input"
    for name in ["A", "A!", "A-1"]:
        movie = root / name / "Film.mkv"
        movie.parent.mkdir(parents=True)
        movie.write_bytes(b"media")
    result = runner.invoke(app, ["import", str(root), "--out", str(tmp_path / "s.yaml"), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["files_imported"] == 3


@pytest.mark.parametrize(
    "files",
    [
        ["Show/Season 01/S01E01.mkv"],
        ["A/Show/Season 01/S01E01 Pilot.mkv", "B/Show/Season 01/S01E01 Pilot.mkv"],
        ["A/Artist/Album/01 Song.flac", "B/Artist/Album/01 Song.flac"],
        ["Artist/Album!/01 Song.flac", "Artist/Album/01 Song.flac"],
    ],
)
def test_import_preserves_distinct_hierarchies_with_normalized_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_probe: None, files: list[str]
) -> None:
    _stub_capabilities_ok(monkeypatch)
    root = tmp_path / "input"
    for name in files:
        media = root / name
        media.parent.mkdir(parents=True, exist_ok=True)
        media.write_bytes(b"media")
    out = tmp_path / "s.yaml"
    result = runner.invoke(app, ["import", str(root), "--out", str(out), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["files_imported"] == len(files)
    result = runner.invoke(app, ["plan", str(out), "--out", str(tmp_path / "preview")])
    assert result.exit_code == 0, result.output


@pytest.mark.parametrize("names", [["Main"], ["A", "Av1"]])
def test_import_ids_do_not_collide_with_root_or_derived_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_probe: None, names: list[str]
) -> None:
    _stub_capabilities_ok(monkeypatch)
    root = tmp_path / "input"
    for name in names:
        media = root / name / "Film.mkv"
        media.parent.mkdir(parents=True)
        media.write_bytes(b"media")
    result = runner.invoke(app, ["import", str(root), "--out", str(tmp_path / "s.yaml"), "--json"])
    assert result.exit_code == 0, result.output


def test_import_mapping_preserves_relative_names_and_sorted_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stub_probe: None
) -> None:
    _stub_capabilities_ok(monkeypatch)
    root = tmp_path / "input"
    names = ["Z/Film.mkv", 'A/Film "é"\n.mkv']
    for name in names:
        source = root / name
        source.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(b"same content")
    outputs = []
    for number in range(2):
        mapping = tmp_path / f"mapping-{number}.json"
        result = runner.invoke(
            app,
            [
                "import",
                str(root),
                "--out",
                str(tmp_path / f"s-{number}.yaml"),
                "--mapping-out",
                str(mapping),
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(mapping.read_text())
        assert set(payload) == set(names)
        assert len(set(payload.values())) == 2
        outputs.append(mapping.read_bytes())
        assert outputs[-1] == (json.dumps(payload, sort_keys=True, indent=2) + "\n").encode()
    assert outputs[0] == outputs[1]


@pytest.mark.parametrize(
    "destination",
    [
        "existing",
        "dangling",
        "scenario",
        "input",
        "media",
        "input-alias",
        "media-alias",
        "missing-parent",
        "file-parent",
    ],
)
def test_import_mapping_rejects_unsafe_destinations_before_probe(
    media_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, destination: str
) -> None:
    out = tmp_path / "scenario.yaml"
    bundle = tmp_path / "media"
    bundle.mkdir()
    target = tmp_path / "mapping.json"
    if destination == "existing":
        target.write_bytes(b"preserved")
    elif destination == "dangling":
        target.symlink_to(tmp_path / "missing")
    elif destination == "scenario":
        target = out
    elif destination in {"input", "media", "input-alias", "media-alias"}:
        parent = media_dir if destination.startswith("input") else bundle
        if destination.endswith("alias"):
            alias = tmp_path / "alias"
            alias.symlink_to(parent, target_is_directory=True)
            parent = alias
        target = parent / "mapping.json"
    elif destination == "missing-parent":
        target = tmp_path / "missing" / "mapping.json"
    else:
        parent = tmp_path / "file"
        parent.write_bytes(b"preserved")
        target = parent / "mapping.json"

    def unexpected_probe() -> None:
        pytest.fail("invalid mapping path must fail before capability detection")

    monkeypatch.setattr(import_media, "detect_capabilities", unexpected_probe)
    result = runner.invoke(
        app, ["import", str(media_dir), "--out", str(out), "--mapping-out", str(target)]
    )
    assert result.exit_code == 2, result.output
    assert "--mapping-out" in re.sub(r"\x1b\[[0-9;]*m", "", result.output)
    assert not out.exists()
    assert not list(bundle.iterdir())
    if destination == "existing":
        assert target.read_bytes() == b"preserved"
    elif destination == "dangling":
        assert target.is_symlink()
