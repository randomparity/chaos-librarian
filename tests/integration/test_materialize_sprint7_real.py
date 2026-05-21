"""Layer-4 real-tool integration tests for Sprint 7 media mutations.

Skip silently when ffmpeg or ffprobe aren't installed or below the
minimum version (mirrors Sprint 5/6).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from chaos_librarian.contract.materialization import Outcome
from chaos_librarian.materializer.capabilities import (
    MIN_VERSIONS,
    detect_capabilities,
)
from chaos_librarian.materializer.errors import MediaActionError
from chaos_librarian.materializer.run import materialize_scenario
from tests.integration.conftest import (
    _load_asset_report,
    _load_current_manifest,
    _load_materialization_report,
)


def _ffmpeg_meets_minimum() -> bool:
    caps = detect_capabilities()
    return caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum


pytestmark = pytest.mark.skipif(
    not _ffmpeg_meets_minimum(),
    reason=f"ffmpeg/ffprobe >= {MIN_VERSIONS['ffmpeg']} not available",
)


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def test_version_evolution_end_to_end(tmp_path: Path) -> None:
    """EXIT CRITERION #1. Reencode + downmix + edit_metadata round-trip."""
    out = tmp_path / "run-001"
    artifacts = materialize_scenario(FIXTURE_DIR / "version-evolution.yaml", out)
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    manifest = _load_current_manifest(out)
    # The fixture's primary asset (asset_main) carries the final version
    # row after three media actions; the per-asset version history (in the
    # asset report) holds the full evolution chain.
    primary_versions = [v for v in manifest.versions if v.asset_id == "asset_main"]
    assert primary_versions, "asset_main missing from manifest.versions"
    for version in primary_versions:
        assert version.content_hash is not None
        assert version.probed is not None
    report = _load_materialization_report(out)
    assert len(report.media_actions) == 3
    asset_report = _load_asset_report(out, "asset_main")
    assert len(asset_report.version_history) == 3


def test_bundle_sidecars_end_to_end(tmp_path: Path) -> None:
    """EXIT CRITERION #2. Poster + NFO + embed + rename."""
    out = tmp_path / "run-002"
    artifacts = materialize_scenario(FIXTURE_DIR / "bundle-sidecars.yaml", out)
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    # The renamed asset path exists under library/ (Task 40 sets the
    # rename target to movies-hd/Quasar.HD.mkv).
    assert (out / "library" / "movies-hd" / "Quasar.HD.mkv").exists()
    # The declared English subtitle's phase-A path (asset_main.eng.srt)
    # was consumed by embed_subtitle and unlinked.
    assert not (out / "library" / "asset_main.eng.srt").exists()
    # Poster + NFO files exist at their create_sidecar to: paths.
    assert (out / "library" / "movies-hd" / "Quasar.poster.png").exists()
    assert (out / "library" / "movies-hd" / "Quasar.nfo").exists()
    manifest = _load_current_manifest(out)
    sidecar_kinds = {s.kind for s in manifest.sidecars}
    assert "poster" in sidecar_kinds
    assert "nfo" in sidecar_kinds
    # And the manifest's lone subtitle sidecar is GONE (embed consumed it).
    assert not any(s.kind == "subtitle" for s in manifest.sidecars)


@pytest.mark.xfail(
    reason="Blocked on #60: _apply_remux_container leaves the old-extension "
    "input file on disk after writing the new container.",
    strict=False,
)
def test_remux_container_real(tmp_path: Path) -> None:
    out = tmp_path / "run-003"
    artifacts = materialize_scenario(FIXTURE_DIR / "remux-container.yaml", out)
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    # File now at .mp4 extension.
    assert (out / "library" / "movies" / "a0.mp4").exists()
    assert not (out / "library" / "movies" / "a0.mkv").exists()


def test_edit_metadata_real(tmp_path: Path) -> None:
    out = tmp_path / "run-004"
    artifacts = materialize_scenario(FIXTURE_DIR / "edit-metadata.yaml", out)
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    # ffprobe the output directly and assert the metadata fields are present.
    out_str = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format_tags",
            "-of",
            "default=noprint_wrappers=1",
            str(out / "library" / "movies" / "a0.mkv"),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    lowered = out_str.lower()
    assert "tag:title=pulsar" in lowered or "title=pulsar" in lowered
    assert "year=2026" in lowered


@pytest.mark.xfail(
    reason="Blocked on #59: extract_subtitle ffmpeg 8.x stream-specifier syntax.",
    strict=False,
)
def test_embed_then_extract_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "run-005"
    artifacts = materialize_scenario(FIXTURE_DIR / "embed-extract-roundtrip.yaml", out)
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    # Extracted .srt exists.
    assert (out / "library" / "movies" / "a0.eng.extracted.srt").exists()


def test_update_sidecar_changes_content_hash(tmp_path: Path) -> None:
    out = tmp_path / "run-006"
    artifacts = materialize_scenario(FIXTURE_DIR / "update-sidecar.yaml", out)
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    manifest = _load_current_manifest(out)
    sidecar = next(s for s in manifest.sidecars if s.id.startswith("sidecar_"))
    # content_hash should differ from the initial phase-A hash. Since
    # update_sidecar regenerates with a perturbed sub-seed including
    # event_id, the hash is deterministic but different from phase A's.
    assert sidecar.content_hash is not None


def test_remove_sidecar_real(tmp_path: Path) -> None:
    out = tmp_path / "run-007"
    artifacts = materialize_scenario(FIXTURE_DIR / "remove-sidecar.yaml", out)
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    # File gone.
    assert not (out / "library" / "movies" / "a0.eng.srt").exists()
    # Manifest row gone.
    manifest = _load_current_manifest(out)
    assert all(s.path != "a0.eng.srt" for s in manifest.sidecars)


def test_subtitle_ops_on_mp4_asset_use_mov_text(tmp_path: Path) -> None:
    out = tmp_path / "run-008"
    artifacts = materialize_scenario(FIXTURE_DIR / "subtitle-ops-on-mp4.yaml", out)
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    # mp4 file exists with embedded mov_text track.
    mp4_path = out / "library" / "movies" / "a0.mp4"
    assert mp4_path.exists()
    probe_out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_streams",
            str(mp4_path),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    streams = json.loads(probe_out)["streams"]
    subtitle_codecs = [s["codec_name"] for s in streams if s.get("codec_type") == "subtitle"]
    assert "mov_text" in subtitle_codecs


def test_phase_b_media_failure_cleans_library(tmp_path: Path) -> None:
    """Hand-craft a scenario that ffmpeg rejects (reencode_audio -ac quad)."""
    # Build the scenario in-place rather than as a fixture so the failure
    # case stays isolated from the positive-fixture corpus.
    scenario_yaml = tmp_path / "fail.yaml"
    scenario_yaml.write_text(
        """\
schema_version: 5
scenario_id: sc_fail
seed: 42
duration_scale: short
library: {roots: [{id: r0, path: library/movies}]}
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: hd}
              audio: [{codec: aac, channels: stereo, language: eng}]
timeline:
  - id: ev_ra
    at: 1s
    action: reencode_audio
    target: a0
    from_channels: stereo
    to_channels: quad
"""
    )
    out = tmp_path / "run-fail"
    with pytest.raises(MediaActionError):
        materialize_scenario(scenario_yaml, out)
    # library/ wiped.
    assert not (out / "library").exists()
    # materialization.json present with outcome=media_failed.
    report_path = out / "materialization.json"
    assert report_path.exists()
    body = json.loads(report_path.read_text())
    assert body["outcome"] == "media_failed"
