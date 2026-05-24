"""Layer 4 — real malformed-media materialize/run integration tests."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from textwrap import dedent

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.materializer.tooling.capabilities import MIN_VERSIONS, detect_capabilities

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


def test_interceptor_catalog_fixture_materializes_real_truncate_and_mtime(
    tmp_path: Path,
) -> None:
    out = tmp_path / "interceptor-catalog"

    result = runner.invoke(
        app,
        [
            "materialize",
            str(FIXTURE_DIR / "interceptor-catalog.yaml"),
            "--out",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    report = json.loads((out / "materialization.json").read_text(encoding="utf-8"))
    corruption = report["corruption_actions"][0]
    metadata = next(
        action for action in report["filesystem_actions"] if action["action"] == "touch_mtime"
    )
    assert corruption["action"] == "truncate_file"
    assert corruption["corruptor"] == "truncate_file_v1"
    assert corruption["byte_start"] == 64
    assert corruption["byte_count"] > 0
    assert metadata["event_id"] == "mtime_001"
    assert metadata["mtime_after_ns"] == metadata["mtime_before_ns"] + 2_000_000_000


def test_packet_range_corruption_records_real_packet_evidence(tmp_path: Path) -> None:
    scenario = _write_interceptor_scenario(
        tmp_path,
        scenario_id="packet-range-real",
        timeline="""
          - id: packet_corrupt_001
            at: 1s
            action: corrupt_packet_range
            target: asset_main
            stream: video
            packet_start: 0
            packet_count: 1
        """,
    )
    out = tmp_path / "packet-range"

    result = runner.invoke(
        app,
        ["materialize", str(scenario), "--out", str(out), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    report = json.loads((out / "materialization.json").read_text(encoding="utf-8"))
    action = report["corruption_actions"][0]
    assert action["action"] == "corrupt_packet_range"
    assert action["stream"] == "video"
    assert action["packet_start"] == 0
    assert action["packet_count"] == 1
    assert isinstance(action["byte_start"], int)
    assert action["byte_start"] >= 0
    assert action["byte_count"] > 0


def test_invalid_duration_metadata_records_real_probe_evidence(tmp_path: Path) -> None:
    scenario = _write_interceptor_scenario(
        tmp_path,
        scenario_id="invalid-duration-real",
        timeline="""
          - id: duration_bad_001
            at: 1s
            action: write_invalid_duration_metadata
            target: asset_main
            value: not-a-duration
        """,
    )
    out = tmp_path / "invalid-duration"

    result = runner.invoke(
        app,
        ["materialize", str(scenario), "--out", str(out), "--json"],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    report = json.loads((out / "materialization.json").read_text(encoding="utf-8"))
    action = report["corruption_actions"][0]
    assert action["action"] == "write_invalid_duration_metadata"
    assert action["corruptor"] == "invalid_duration_metadata_v1"
    assert action["metadata"]["value"] == "not-a-duration"
    assert action["metadata"]["input_duration_seconds"] > 0


def test_negative_oracle_fixture_records_actual_and_reported_hash(tmp_path: Path) -> None:
    out = tmp_path / "negative-oracle"

    result = runner.invoke(
        app,
        [
            "materialize",
            str(FIXTURE_DIR / "negative-oracle-hash.yaml"),
            "--out",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    report = json.loads((out / "materialization.json").read_text(encoding="utf-8"))
    manifest = json.loads((out / "manifest.current.json").read_text(encoding="utf-8"))
    action = report["oracle_hash_actions"][0]
    current = manifest["versions"][-1]
    location = manifest["locations"][0]["path"]
    actual_hash = "sha256:" + hashlib.sha256((out / "library" / location).read_bytes()).hexdigest()
    assert action["actual_content_hash"] == actual_hash
    assert action["actual_content_hash"] != action["reported_content_hash"]
    assert current["content_hash"] == action["reported_content_hash"]


def _write_interceptor_scenario(tmp_path: Path, *, scenario_id: str, timeline: str) -> Path:
    path = tmp_path / f"{scenario_id}.yaml"
    timeline_yaml = "\n".join(f"  {line}" for line in dedent(timeline).strip().splitlines())
    body = dedent(
        f"""
        schema_version: 9
        scenario_id: {scenario_id}
        seed: 117
        duration_scale: short
        profiles:
          - malformed-media
        library:
          roots:
            - id: movies_hd
              path: movies-hd
        works:
          - id: work_broken
            title: Interceptor Real
            variants:
              - id: variant_hd
                label: hd
                bundle:
                  id: bundle_hd
                  assets:
                    - id: asset_main
                      role: primary_video
                      container: mkv
                      duration_seconds: 4
                      video:
                        source: color_bars
                        codec: h264
                        resolution: hd
                      audio:
                        - codec: aac
                          channels: stereo
                          language: eng
        timeline:
        """
    ).lstrip()
    path.write_text(f"{body}{timeline_yaml}\n", encoding="utf-8")
    return path
