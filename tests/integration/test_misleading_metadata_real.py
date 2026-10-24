"""Bounded #246 corpus: compare actual bytes with intent and oracle evidence."""

from __future__ import annotations

import json
from pathlib import Path
from xml.etree import ElementTree

import pytest
from ruamel.yaml import YAML
from typer.testing import CliRunner

from chaos_librarian.adapter.compare import compare_fixture_to_observed
from chaos_librarian.adapter.fixture import load_fixture
from chaos_librarian.cli.app import app
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.materializer.run import materialize_scenario
from chaos_librarian.materializer.tooling._subprocess import run_recorded_tool
from chaos_librarian.materializer.tooling.capabilities import detect_capabilities
from chaos_librarian.materializer.tooling.probe import probe_file
from tests.support.adapter import observed_from_fixture

_caps = detect_capabilities()
pytestmark = pytest.mark.skipif(
    not (_caps.ffmpeg.meets_minimum and _caps.ffprobe.meets_minimum),
    reason="ffmpeg/ffprobe >=7 required for retained metadata proof",
)
_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/scenarios/edit-metadata.yaml"


def _scenario(tmp_path: Path, fields: dict[str, str] | None) -> Path:
    payload = YAML(typ="safe").load(_FIXTURE.read_text())
    payload["seed"] = 246
    asset = payload["movies"][0]["variants"][0]["bundle"]["assets"][0]
    asset["video"]["resolution"] = "sd"
    if fields is None:
        payload["timeline"] = []
        asset["audio"].append({"codec": "aac", "channels": "stereo", "language": "fra"})
    else:
        payload["timeline"][0]["fields"] = fields
        payload["timeline"].append(
            {
                "id": "nfo",
                "at": "2s",
                "action": "create_sidecar",
                "target": "a0",
                "kind": "nfo",
                "to": "movies/T.nfo",
                "body": "<movie><title>Sidecar title</title></movie>",
            }
        )
        if fields.get("title") == "":
            payload["timeline"].insert(
                0,
                {
                    "id": "prior",
                    "at": "0s",
                    "action": "edit_metadata",
                    "target": "a0",
                    "fields": {"title": "Title to delete", "year": "2026"},
                },
            )
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(payload))
    return path


def _actual(run: Path) -> ProbedMedia:
    media = next((run / "library").rglob("*.mkv"))
    assert media.stat().st_size <= 64 * 1024 * 1024
    raw = run_recorded_tool(
        ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(media)],
        tool="ffprobe",
        version="",
        timeout_s=15,
        stdout_mode="pipe",
        text=True,
        max_output_bytes=1024 * 1024,
    )
    assert raw.invocation.exit_code == 0, raw.stderr_tail
    payload = json.loads(raw.stdout_text())
    actual = {
        k.casefold(): v
        for k, v in payload["format"].get("tags", {}).items()
        if k.casefold() in {"title", "year"}
    }
    probed = probe_file(media, max_output_bytes=1024 * 1024)
    assert probed.format_tags == actual
    assert 0 < probed.duration_seconds <= 30
    audio = [s for s in payload["streams"] if s["codec_type"] == "audio"]
    assert len(audio) <= 2
    assert [s.language for s in probed.streams if s.kind.value == "audio"] == [
        s["tags"]["language"] for s in audio
    ]
    fixture = load_fixture(run)
    assert max(fixture.current_manifest.versions, key=lambda v: v.index).probed == probed
    return probed


@pytest.mark.parametrize(
    "fields",
    [
        {"title": "Embedded title"},
        {"year": "9999"},
        {"title": "雪" * 1365 + "x"},
        {"title": "雪 café\tline\nnext"},
        {"title": "", "year": ""},
    ],
)
def test_misleading_metadata_retained_in_real_bytes(
    tmp_path: Path,
    fields: dict[str, str],
) -> None:
    source = tmp_path / "run"
    materialize_scenario(_scenario(tmp_path, fields), source)
    probed = _actual(source)
    assert probed.format_tags == {k: v for k, v in fields.items() if v != ""}
    media = next((source / "library").rglob("*.mkv"))
    nfo_title = ElementTree.parse(source / "library/movies/T.nfo").findtext("title")
    assert nfo_title == "Sidecar title"
    assert probed.format_tags is not None
    if fields.get("title"):
        assert fields["title"] not in media.name
        assert nfo_title != probed.format_tags["title"]
    journal = [json.loads(line) for line in (source / "journal.jsonl").read_text().splitlines()]
    assert (
        next(e for e in journal if e["event_id"] == "ev_edit_meta")["state_delta"]["fields"]
        == fields
    )


def test_metadata_run_replay_and_comparison(tmp_path: Path) -> None:
    scenario = _scenario(tmp_path, {"title": "Embedded title", "year": "9999"})
    runner = CliRunner()
    source, replay = tmp_path / "run", tmp_path / "replay"
    result = runner.invoke(
        app,
        [
            "run",
            str(scenario),
            "--out",
            str(source),
            "--duration",
            "3s",
            "--speed",
            "1000x",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    probed = _actual(source)
    assert probed.format_tags == {"title": "Embedded title", "year": "9999"}
    bundle = json.loads((source / "replay.json").read_text())
    replay_input = YAML(typ="safe").load(bundle["scenario"])
    assert replay_input["timeline"][0]["fields"] == probed.format_tags
    result = runner.invoke(
        app,
        [
            "replay",
            str(source / "replay.json"),
            "--out",
            str(replay),
            "--against",
            str(source),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert _actual(replay).format_tags == probed.format_tags
    fixture = load_fixture(source)
    observed = observed_from_fixture(fixture)
    observed.assets[0].probed = probed.model_copy(deep=True)
    assert compare_fixture_to_observed(fixture, observed).ok
    tags = probed.format_tags
    assert tags is not None
    for key in ("title", "year"):
        altered = observed.model_copy(deep=True)
        assert altered.assets[0].probed is not None
        assert altered.assets[0].probed.format_tags is not None
        altered.assets[0].probed.format_tags[key] = "different"
        report = compare_fixture_to_observed(fixture, altered)
        assert not report.ok
        assert any(f.expected == {f"format_tags.{key}": tags[key]} for f in report.findings)


def test_missing_tags_and_conflicting_stream_languages(tmp_path: Path) -> None:
    source = tmp_path / "run"
    materialize_scenario(_scenario(tmp_path, None), source)
    probed = _actual(source)
    assert probed.format_tags == {}
    assert [s.language for s in probed.streams if s.kind.value == "audio"] == ["eng", "fra"]
    fixture = load_fixture(source)
    observed = observed_from_fixture(fixture)
    observed.assets[0].probed = probed.model_copy(deep=True)
    assert compare_fixture_to_observed(fixture, observed).ok
    observed.assets[0].probed.streams[-1].language = "eng"
    assert not compare_fixture_to_observed(fixture, observed).ok
