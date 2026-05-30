"""Layer 4 — real materialize integration tests for music artifacts (#118).

Covers the three v1 capabilities end to end through the ``materialize`` CLI:
poster image-format variety (WebP/JPEG), the CUE sidecar kind, and corrupt_tags
byte corruption. ffmpeg-gated; skips in CI when the toolchain is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.materializer.tooling.capabilities import (
    MIN_VERSIONS,
    detect_capabilities,
)

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"

_RIFF = b"RIFF"
_WEBP = b"WEBP"
_JPEG_SOI = b"\xff\xd8"


def _ffmpeg_meets_minimum() -> bool:
    caps = detect_capabilities()
    return caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum


pytestmark = pytest.mark.skipif(
    not _ffmpeg_meets_minimum(),
    reason=f"ffmpeg/ffprobe >= {MIN_VERSIONS['ffmpeg']} not available",
)


def _materialize(scenario: str, out: Path) -> None:
    result = runner.invoke(
        app, ["materialize", str(FIXTURE_DIR / scenario), "--out", str(out), "--json"]
    )
    assert result.exit_code == 0, result.stdout + result.stderr


def test_poster_image_format_materializes_webp_and_jpeg(tmp_path: Path) -> None:
    out = tmp_path / "poster"
    _materialize("poster-image-format.yaml", out)

    webp = out / "library" / "music" / "cover.webp"
    jpg = out / "library" / "music" / "folder.jpg"
    assert webp.is_file()
    assert jpg.is_file()
    webp_head = webp.read_bytes()[:12]
    assert webp_head[:4] == _RIFF
    assert webp_head[8:12] == _WEBP
    assert jpg.read_bytes()[:2] == _JPEG_SOI

    manifest = json.loads((out / "manifest.current.json").read_text(encoding="utf-8"))
    sidecar_paths = {s["path"] for s in manifest["sidecars"]}
    assert any(p.endswith("cover.webp") for p in sidecar_paths)
    assert any(p.endswith("folder.jpg") for p in sidecar_paths)


def test_cue_sidecar_materializes_with_kind_cue(tmp_path: Path) -> None:
    out = tmp_path / "cue"
    _materialize("cue-sidecar.yaml", out)

    cue = out / "library" / "music" / "album.cue"
    assert cue.is_file()
    assert cue.read_bytes().startswith(b"PERFORMER")

    manifest = json.loads((out / "manifest.current.json").read_text(encoding="utf-8"))
    cue_rows = [s for s in manifest["sidecars"] if s["kind"] == "cue"]
    assert len(cue_rows) == 1
    assert cue_rows[0]["path"].endswith("album.cue")


def test_corrupt_tags_records_flavor_and_corrupts_head(tmp_path: Path) -> None:
    out = tmp_path / "tags"
    _materialize("corrupt-tags.yaml", out)

    report = json.loads((out / "materialization.json").read_text(encoding="utf-8"))
    flavors = {
        a["metadata"]["flavor"]
        for a in report["corruption_actions"]
        if a["action"] == "corrupt_tags"
    }
    assert flavors == {"null_bytes", "malformed_frame"}

    manifest = json.loads((out / "manifest.current.json").read_text(encoding="utf-8"))
    corruptors = {
        v["corruption"]["corruptor"]
        for v in manifest["versions"]
        if v.get("corruption") is not None
    }
    assert "tag_corruption_v1" in corruptors
