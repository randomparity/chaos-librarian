"""End-to-end import integration test with real ffmpeg/ffprobe/mkvmerge.

Why (issue #105 acceptance criteria 2-4): the unit suite stubs the prober;
this test proves the whole chain — scan, probe, classify, sidecar attach,
bundle copy, re-validation, plan, materialize — against real tools and that
materialized media matches the imported originals.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _require(tool: str) -> None:
    if shutil.which(tool) is None:
        pytest.skip(f"{tool} not installed")


@pytest.fixture
def media_input(tmp_path: Path) -> Path:
    """Tiny real-media tree: one movie with an .srt sidecar and a poster."""
    _require("ffmpeg")
    _require("ffprobe")
    movie_dir = tmp_path / "input" / "Sample Movie"
    movie_dir.mkdir(parents=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=red:size=64x64:rate=10",
            "-t",
            "1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(movie_dir / "Sample Movie.mp4"),
        ],
        check=True,
        timeout=120,
    )
    subtitle_body = "1\n00:00:00,000 --> 00:00:01,000\nHello from import\n"
    (movie_dir / "Sample Movie.en.srt").write_text(subtitle_body)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:size=32x32",
            "-frames:v",
            "1",
            str(movie_dir / "poster.jpg"),
        ],
        check=True,
        timeout=60,
    )
    return tmp_path / "input"


def test_import_end_to_end_with_real_tools(media_input: Path, tmp_path: Path) -> None:
    out_yaml = tmp_path / "out" / "scenario.yaml"
    out_yaml.parent.mkdir(parents=True)

    def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            ["uv", "run", "chaos-librarian", *args],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parents[2],
            timeout=600,
            check=False,
        )
        return result

    # 1. Import produces a scenario bundle.
    imp = run_cli("import", str(media_input), "--out", str(out_yaml), "--json")
    assert imp.returncode == 0, imp.stderr + imp.stdout
    report = json.loads(imp.stdout)
    assert report["files_imported"] == 1
    # Sidecars are attached (and copied) but reported separately from media.
    assert report["sidecars"] == {"subtitles": 1, "nfo": 0, "posters": 1}
    assert report["works"]["movies"] == 1

    # 2. The emitted scenario validates (acceptance criterion 2).
    val = run_cli("validate", str(out_yaml), "--json")
    assert val.returncode == 0, val.stderr + val.stdout

    # 3. Plan and materialize succeed end to end (criteria 5).
    plan_dir = tmp_path / "plan"
    mat_dir = tmp_path / "run"
    plan = run_cli("plan", str(out_yaml), "--out", str(plan_dir))
    assert plan.returncode == 0, plan.stderr + plan.stdout
    mat = run_cli("materialize", str(out_yaml), "--out", str(mat_dir))
    assert mat.returncode == 0, mat.stderr + mat.stdout

    # 4. Materialized media matches the imported original (criterion 3).
    library = mat_dir / "library"
    mp4s = sorted(library.rglob("*.mp4"))
    assert len(mp4s) == 1
    original_probe = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                str(media_input / "Sample Movie" / "Sample Movie.mp4"),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
    )
    copy_probe = json.loads(
        subprocess.run(
            [
                "ffprobe",
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                str(mp4s[0]),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        ).stdout
    )
    assert (
        abs(float(original_probe["format"]["duration"]) - float(copy_probe["format"]["duration"]))
        < 0.05
    )
    # Imported assets are byte-identical copies of the originals.
    assert mp4s[0].read_bytes() == (media_input / "Sample Movie" / "Sample Movie.mp4").read_bytes()

    # 5. Sidecars land in the library with original content (criterion 4).
    srts = [p for p in library.rglob("*.srt") if p.name.endswith(".en.srt")]
    assert len(srts) == 1
    assert "Hello from import" in srts[0].read_text()
    posters = list(library.rglob("poster.jpg"))
    assert len(posters) == 1
