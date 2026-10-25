"""Generated corpus bytes and neutral evidence survive materialize/run/replay."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

import pytest
from typer.testing import CliRunner

from chaos_librarian.adapter.fixture import load_fixture
from chaos_librarian.cli.app import app
from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.generation import generate_scenario_yaml
from chaos_librarian.materializer.runtime import wall_clock
from chaos_librarian.materializer.tooling._subprocess import run_recorded_tool
from chaos_librarian.materializer.tooling.capabilities import detect_capabilities
from chaos_librarian.materializer.tooling.probe import probe_file

_caps = detect_capabilities()
pytestmark = pytest.mark.skipif(
    not (
        _caps.ffmpeg.meets_minimum
        and _caps.ffprobe.meets_minimum
        and _caps.mkvtoolnix.meets_minimum
    ),
    reason="generated adversarial corpus requires ffmpeg/ffprobe >=7 and MKVToolNix >=80",
)


def _probe(path: Path, *, packets: bool = False):
    args = ["ffprobe", "-v", "error", "-of", "json"]
    args += (
        ["-select_streams", "a:0", "-show_packets"]
        if packets
        else ["-show_format", "-show_streams"]
    )
    return run_recorded_tool(
        [*args, str(path)],
        tool="ffprobe",
        version="test",
        timeout_s=15,
        stdout_mode="pipe",
        text=True,
        max_output_bytes=1024 * 1024,
    )


def _assert_bytes_and_evidence(run: Path) -> None:
    report = json.loads((run / "materialization.json").read_text())
    assert report["outcome"] == "success"
    assert len(report["invocations"]) <= 100
    paths = {a["asset_id"]: run / a["location_path"] for a in report["materialized"]}
    assert len(paths) == 18
    assert all(0 < path.stat().st_size <= 64 * 1024 * 1024 for path in paths.values())
    for name, default, forced, count in (
        ("multiple", 1, 0, 2),
        ("none", 0, 0, 2),
        ("default_forced", 1, 1, 2),
        ("forced_only", 0, 1, 8),
    ):
        actual = _probe(paths["flags_" + name])
        assert actual.invocation.exit_code == 0
        streams = json.loads(actual.stdout_text())["streams"]
        for kind in ("audio", "subtitle"):
            selected = [s for s in streams if s["codec_type"] == kind]
            assert len(selected) == count
            assert [
                (s["disposition"]["default"], s["disposition"]["forced"]) for s in selected
            ] == [(default, forced)] * count
        assert next(s for s in streams if s["codec_type"] == "audio")["disposition"]["comment"] == 1

    _assert_metadata(run, paths)
    _assert_structural(report, paths)
    _assert_requested_evidence(run)


def _assert_metadata(run: Path, paths: dict[str, Path]) -> None:
    fixture = load_fixture(run)
    expected = {
        "title": {"title": "Embedded title"},
        "year": {"year": "9999"},
        "long": {"title": "雪" * 1365 + "x"},
        "control": {"title": "雪 café\tline\nnext"},
        "delete": {},
        "missing": {},
        "languages": {},
    }
    for name, fields in expected.items():
        asset_id = "metadata_" + name
        actual = _probe(paths[asset_id])
        assert actual.invocation.exit_code == 0
        raw = json.loads(actual.stdout_text())
        tags = {
            k.casefold(): v
            for k, v in raw["format"].get("tags", {}).items()
            if k.casefold() in {"title", "year"}
        }
        assert tags == fields
        probed = probe_file(paths[asset_id])
        assert probed.format_tags == tags
        versions = [v for v in fixture.current_manifest.versions if v.asset_id == asset_id]
        assert max(versions, key=lambda v: v.index).probed == probed
        if name == "languages":
            assert [
                s["tags"]["language"] for s in raw["streams"] if s["codec_type"] == "audio"
            ] == ["eng", "fra"]
    assert (
        ElementTree.parse(run / "library/movies/Disagreement.nfo").findtext("title")
        == "Sidecar title"
    )
    assert "Embedded title" not in paths["metadata_title"].name


def _assert_structural(report: dict, paths: dict[str, Path]) -> None:
    actions = {a["target_asset_id"]: a for a in report["corruption_actions"]}
    assert set(actions) == {"damage_mp4_start", "damage_mp4_end", "damage_mkv", "damage_mp3"}
    for asset_id, action in actions.items():
        assert action["input_content_hash"] != action["output_content_hash"]
        assert action["byte_count"] > 0
        probed = _probe(paths[asset_id])
        if asset_id.startswith("damage_mp4"):
            assert probed.invocation.exit_code != 0
            assert action["probe_outcome"] == "failed_expected"
        else:
            assert probed.invocation.exit_code == 0
            assert action["probe_outcome"] == "still_probeable"
    assert actions["damage_mp4_start"]["byte_start"] < actions["damage_mp4_end"]["byte_start"]
    for asset_id in ("control_mp4", "control_mkv", "control_mp3"):
        assert _probe(paths[asset_id]).invocation.exit_code == 0
    damaged = _probe(paths["damage_mp3"], packets=True)
    healthy = _probe(paths["control_mp3"], packets=True)
    assert len(json.loads(damaged.stdout_text())["packets"]) == 16
    assert len(json.loads(healthy.stdout_text())["packets"]) > 16


def _assert_requested_evidence(run: Path) -> None:
    journal = [json.loads(line) for line in (run / "journal.jsonl").read_text().splitlines()]
    requested = [e["state_delta"]["fields"] for e in journal if e["action"] == "edit_metadata"]
    assert {"title": "", "year": ""} in requested
    bundle = json.loads((run / "replay.json").read_text())
    assert bundle["applied_events"] == 11
    assert "adversarial-media" in bundle["scenario"]
    assert "mp3_after_16_frames" in bundle["scenario"]


def test_generated_corpus_materializes_runs_and_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Clock time is the nondeterministic boundary; media tools still execute for real.
    now = [0]
    monkeypatch.setattr(wall_clock, "_monotonic_ns", lambda: now[0])
    monkeypatch.setattr(wall_clock, "_sleep_until", lambda deadline: now.__setitem__(0, deadline))
    data = generate_scenario_yaml(
        FuzzProfileName.FUZZ_REGRESSION, 248, lane=FuzzLaneName.ADVERSARIAL_MEDIA
    )
    scenario = tmp_path / "scenario.yaml"
    scenario.write_bytes(data)
    runner = CliRunner()
    for command, out in (("materialize", "materialized"), ("run", "run")):
        args = [command, str(scenario), "--out", str(tmp_path / out), "--json"]
        if command == "run":
            args += ["--duration", "1ms", "--speed", "1000x"]
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.stdout + result.stderr
        _assert_bytes_and_evidence(tmp_path / out)
    result = runner.invoke(
        app,
        [
            "replay",
            str(tmp_path / "run/replay.json"),
            "--out",
            str(tmp_path / "replay"),
            "--against",
            str(tmp_path / "run"),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    _assert_bytes_and_evidence(tmp_path / "replay")
