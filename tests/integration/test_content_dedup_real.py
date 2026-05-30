"""Layer 4 — real ffmpeg integration for same_content_as / hash_collision_with.

Skipped if ffmpeg/ffprobe < minimum. Exercises the two #180 features
end-to-end through the real materialize toolchain.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.materializer.tooling.capabilities import MIN_VERSIONS, detect_capabilities

runner = CliRunner()


def _ffmpeg_meets_minimum() -> bool:
    caps = detect_capabilities()
    return caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum


pytestmark = pytest.mark.skipif(
    not _ffmpeg_meets_minimum(),
    reason=f"ffmpeg/ffprobe >= {MIN_VERSIONS['ffmpeg']} not available",
)


_SAME_CONTENT_YAML = """\
schema_version: 30
scenario_id: same-content-real
seed: 7
duration_scale: short
library: {roots: [{id: r, path: library}]}
movies:
  - id: w0
    title: Dup
    layout: movie_flat
    variants:
      - id: v_ref
        label: ref
        bundle:
          id: b_ref
          assets:
            - id: a_ref
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: sd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
      - id: v_dup
        label: dup
        bundle:
          id: b_dup
          assets:
            - id: a_dup
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: sd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
              same_content_as: a_ref
series: []
artists: []
timeline: []
"""


_COLLISION_YAML = """\
schema_version: 30
scenario_id: hash-collision-real
seed: 7
duration_scale: short
library: {roots: [{id: r, path: library}]}
movies:
  - id: w0
    title: Collide
    layout: movie_flat
    variants:
      - id: v_ref
        label: ref
        bundle:
          id: b_ref
          assets:
            - id: a_ref
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: color_bars, codec: h264, resolution: sd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
      - id: v_decoy
        label: decoy
        bundle:
          id: b_decoy
          assets:
            - id: a_decoy
              role: primary_video
              container: mkv
              duration_seconds: 1
              video: {source: mandelbrot, codec: h264, resolution: sd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
              hash_collision_with: a_ref
              collision_prefix_len: 8
series: []
artists: []
timeline: []
"""


def _version_hash(manifest: Manifest, asset_id: str) -> str:
    version = next(v for v in manifest.versions if v.asset_id == asset_id)
    assert version.content_hash is not None
    return version.content_hash


def _on_disk_hash(out: Path, manifest: Manifest, asset_id: str) -> str:
    location = next(loc for loc in manifest.locations if loc.asset_id == asset_id)
    path = out / "library" / location.path
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def test_same_content_as_produces_identical_files_and_hashes(tmp_path: Path) -> None:
    scenario = tmp_path / "same.yaml"
    scenario.write_text(_SAME_CONTENT_YAML)
    out = tmp_path / "same"
    result = runner.invoke(app, ["materialize", str(scenario), "--out", str(out), "--json"])
    assert result.exit_code == 0, result.stdout + result.stderr
    manifest = Manifest.model_validate_json((out / "manifest.current.json").read_text())

    ref_bytes = _read_asset(out, manifest, "a_ref")
    dup_bytes = _read_asset(out, manifest, "a_dup")
    assert dup_bytes == ref_bytes
    assert _version_hash(manifest, "a_dup") == _version_hash(manifest, "a_ref")


def test_hash_collision_records_oracle_prefix_collision(tmp_path: Path) -> None:
    scenario = tmp_path / "collide.yaml"
    scenario.write_text(_COLLISION_YAML)
    out = tmp_path / "collide"
    result = runner.invoke(app, ["materialize", str(scenario), "--out", str(out), "--json"])
    assert result.exit_code == 0, result.stdout + result.stderr
    manifest = Manifest.model_validate_json((out / "manifest.current.json").read_text())

    ref_recorded = _version_hash(manifest, "a_ref")
    decoy_recorded = _version_hash(manifest, "a_decoy")
    # recorded hashes share exactly the 8-char prefix and differ at full length
    assert (
        decoy_recorded[len("sha256:") : len("sha256:") + 8]
        == ref_recorded[len("sha256:") : len("sha256:") + 8]
    )
    assert decoy_recorded != ref_recorded
    # oracle-only: the decoy's real on-disk sha256 does NOT carry the prefix
    on_disk = _on_disk_hash(out, manifest, "a_decoy")
    assert on_disk != decoy_recorded


def test_hash_collision_is_deterministic_across_runs(tmp_path: Path) -> None:
    # Materialize twice; the collided recorded hash must be byte-stable (this is
    # what makes run == replay, since both restamp via the same augment_manifest).
    hashes = []
    for i in range(2):
        scenario = tmp_path / f"collide_{i}.yaml"
        scenario.write_text(_COLLISION_YAML)
        out = tmp_path / f"collide_{i}"
        result = runner.invoke(app, ["materialize", str(scenario), "--out", str(out), "--json"])
        assert result.exit_code == 0, result.stdout + result.stderr
        manifest = Manifest.model_validate_json((out / "manifest.current.json").read_text())
        hashes.append(_version_hash(manifest, "a_decoy"))
    assert hashes[0] == hashes[1]


def _read_asset(out: Path, manifest: Manifest, asset_id: str) -> bytes:
    location = next(loc for loc in manifest.locations if loc.asset_id == asset_id)
    return (out / "library" / location.path).read_bytes()
