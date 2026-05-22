"""Layer 4 — real malformed-media materialize/run integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.materializer.capabilities import MIN_VERSIONS, detect_capabilities

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _ffmpeg_meets_minimum() -> bool:
    caps = detect_capabilities()
    return caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum


pytestmark = pytest.mark.skipif(
    not _ffmpeg_meets_minimum(),
    reason=f"ffmpeg/ffprobe >= {MIN_VERSIONS['ffmpeg']} not available",
)


def test_malformed_media_fixture_materializes_real_corruption(tmp_path: Path) -> None:
    out = tmp_path / "malformed"

    result = runner.invoke(
        app,
        [
            "materialize",
            str(FIXTURE_DIR / "malformed-container-header.yaml"),
            "--out",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    report = json.loads((out / "materialization.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.current.json").read_text(encoding="utf-8"))
    asset_report = json.loads((out / "reports" / "assets" / "asset_main.json").read_text())
    assert report["outcome"] == "success"
    assert len(report["corruption_actions"]) == 1
    assert manifest["versions"][-1]["corruption"]["corruptor"] == "container_header_v1"
    assert asset_report["current"]["corruption"]["event_id"] == "corrupt_header_001"


def test_malformed_media_fixture_replay_matches_same_toolchain(tmp_path: Path) -> None:
    source = tmp_path / "source"
    replay = tmp_path / "replay"
    run_result = runner.invoke(
        app,
        [
            "run",
            str(FIXTURE_DIR / "malformed-container-header.yaml"),
            "--out",
            str(source),
            "--duration",
            "2ms",
            "--speed",
            "1000x",
            "--json",
        ],
    )
    assert run_result.exit_code == 0, run_result.stdout + run_result.stderr

    replay_result = runner.invoke(
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

    assert replay_result.exit_code == 0, replay_result.stdout + replay_result.stderr
