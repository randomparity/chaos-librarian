"""Real bytes, run replay and consumer comparison for ambiguous dispositions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.adapter.compare import compare_fixture_to_observed
from chaos_librarian.adapter.fixture import load_fixture
from chaos_librarian.cli.app import app
from chaos_librarian.contract import SCENARIO_SCHEMA_VERSION
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.scenario import AudioTrackRole
from chaos_librarian.materializer.tooling.capabilities import detect_capabilities
from chaos_librarian.materializer.tooling.probe import probe_file
from tests.materializer.test_track_dispositions import feature_asset
from tests.support.adapter import observed_from_fixture

_caps = detect_capabilities()
pytestmark = pytest.mark.skipif(
    not (_caps.ffmpeg.meets_minimum and _caps.ffprobe.meets_minimum),
    reason="ffmpeg/ffprobe >=7 required for real disposition proof",
)


def _scenario(tmp_path: Path, default: bool, forced: bool, count: int) -> Path:
    asset = feature_asset()
    flags = {"default": default, "forced": forced}
    audio = tuple(asset.audio[0].model_copy(update=flags) for _ in range(count))
    audio = (audio[0].model_copy(update={"role": AudioTrackRole.COMMENTARY}), *audio[1:])
    asset = asset.model_copy(
        update={
            "audio": audio,
            "subtitles": tuple(asset.subtitles[0].model_copy(update=flags) for _ in range(count)),
        }
    )
    payload = {
        "schema_version": SCENARIO_SCHEMA_VERSION,
        "scenario_id": "track-flags",
        "seed": 245,
        "duration_scale": "short",
        "library": {"roots": [{"id": "root", "path": "library"}]},
        "movies": [
            {
                "id": "movie",
                "title": "Flags",
                "layout": "movie_flat",
                "variants": [
                    {
                        "id": "variant",
                        "label": "sd",
                        "bundle": {"id": "bundle", "assets": [asset.model_dump(mode="json")]},
                    }
                ],
            }
        ],
        "series": [],
        "artists": [],
        "timeline": [],
    }
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(payload))
    return path


def _assert_output(run: Path, default: bool, forced: bool, count: int) -> ProbedMedia:
    path = next((run / "library").rglob("*.mkv"))
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )
    streams = json.loads(result.stdout)["streams"]
    for kind in ("audio", "subtitle"):
        selected = [s for s in streams if s["codec_type"] == kind]
        assert len(selected) == count
        assert [(s["disposition"]["default"], s["disposition"]["forced"]) for s in selected] == [
            (int(default), int(forced))
        ] * count
    assert next(s for s in streams if s["codec_type"] == "audio")["disposition"]["comment"] == 1
    assert not list((run / "library").rglob("*.srt"))
    probed = probe_file(path)
    assert 0.15 <= probed.duration_seconds <= 0.4
    fixture = load_fixture(run)
    assert fixture.current_manifest.versions[0].probed == probed
    return probed


@pytest.mark.parametrize(
    ("default", "forced", "count"),
    [(True, False, 2), (False, False, 2), (True, True, 2), (False, True, 8)],
)
def test_dispositions_real_run_replay_and_comparison(
    tmp_path: Path, default: bool, forced: bool, count: int
) -> None:
    scenario = _scenario(tmp_path, default, forced, count)
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
            "1ms",
            "--speed",
            "1000x",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    probed = _assert_output(source, default, forced, count)
    bundle = json.loads((source / "replay.json").read_text())
    assert '"default"' in bundle["scenario"]
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
    replayed = _assert_output(replay, default, forced, count)
    assert [(s.default, s.forced) for s in replayed.streams] == [
        (s.default, s.forced) for s in probed.streams
    ]
    fixture = load_fixture(source)
    observed = observed_from_fixture(fixture)
    observed.assets[0].probed = probed.model_copy(deep=True)
    assert compare_fixture_to_observed(fixture, observed).ok
    for kind in ("audio", "subtitle"):
        for flag in ("default", "forced"):
            altered = observed.model_copy(deep=True)
            assert altered.assets[0].probed is not None
            index = next(
                i for i, s in enumerate(altered.assets[0].probed.streams) if s.kind.value == kind
            )
            stream = altered.assets[0].probed.streams[index]
            setattr(stream, flag, not getattr(stream, flag))
            report = compare_fixture_to_observed(fixture, altered)
            assert not report.ok
            assert any(
                f.expected == {f"streams.{index}.{flag}": getattr(stream, flag) is False}
                for f in report.findings
            )
