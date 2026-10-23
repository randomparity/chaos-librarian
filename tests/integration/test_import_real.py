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

from chaos_librarian.materializer.errors import ProbeParseError
from chaos_librarian.materializer.tooling.probe import probe_file


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
    (movie_dir / "Sample Movie.nfo").write_text("<movie><title>Original</title></movie>\n")
    album_dir = tmp_path / "input" / "Artist" / "Album"
    album_dir.mkdir(parents=True)
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=32000",
            "-t",
            "0.5",
            "-c:a",
            "flac",
            str(album_dir / "01 Song.flac"),
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
    assert report["files_imported"] == 2
    assert report["files_scanned"] == 5
    # Sidecars are attached (and copied) but reported separately from media.
    assert report["sidecars"] == {"subtitles": 1, "nfo": 1, "posters": 1}
    assert report["works"] == {"movies": 1, "series": 0, "artists": 1}

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
    original_movie = media_input / "Sample Movie" / "Sample Movie.mp4"
    assert mp4s[0].read_bytes() == original_movie.read_bytes()
    assert probe_file(mp4s[0]) == probe_file(original_movie)
    flacs = list(library.rglob("*.flac"))
    assert len(flacs) == 1
    original_audio = media_input / "Artist" / "Album" / "01 Song.flac"
    assert flacs[0].read_bytes() == original_audio.read_bytes()
    assert probe_file(flacs[0]) == probe_file(original_audio)

    # 5. Sidecars land in the library with original content (criterion 4).
    srts = [p for p in library.rglob("*.srt") if p.name.endswith(".en.srt")]
    assert len(srts) == 1
    assert (
        srts[0].read_bytes() == (media_input / "Sample Movie" / "Sample Movie.en.srt").read_bytes()
    )
    nfos = list(library.rglob("*.nfo"))
    assert len(nfos) == 1
    assert nfos[0].read_bytes() == (media_input / "Sample Movie" / "Sample Movie.nfo").read_bytes()
    posters = list(library.rglob("poster.jpg"))
    assert len(posters) == 1


def test_import_probe_rejects_secondary_resource_reads(tmp_path: Path) -> None:
    _require("ffmpeg")
    _require("ffprobe")
    segment = tmp_path / "outside.ts"
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
            "mpeg2video",
            str(segment),
        ],
        check=True,
        timeout=60,
    )
    root = tmp_path / "input"
    root.mkdir()
    playlist = root / "Playlist.m3u8"
    playlist.write_text(
        "#EXTM3U\n#EXT-X-VERSION:3\n#EXT-X-TARGETDURATION:1\n"
        f"#EXT-X-MEDIA-SEQUENCE:0\n#EXTINF:1.0,\n{segment}\n#EXT-X-ENDLIST\n"
    )
    assert probe_file(playlist).streams
    with pytest.raises(ProbeParseError):
        probe_file(playlist, self_contained_only=True)

    scenario = tmp_path / "unsafe.yaml"
    scenario.write_text("""schema_version: 33
scenario_id: imported-playlist
seed: 0
duration_scale: normal
library:
  roots: [{id: main, path: imported}]
movies:
  - id: movie
    title: Movie
    layout: movie_flat
    variants:
      - id: variant
        label: default
        bundle:
          id: bundle
          assets:
            - id: asset
              role: main
              container: m3u8
              duration_seconds: 1
              import_source: {path: input/Playlist.m3u8}
series: []
artists: []
timeline: []
""")
    result = subprocess.run(
        [
            "uv",
            "run",
            "chaos-librarian",
            "materialize",
            str(scenario),
            "--out",
            str(tmp_path / "run"),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        cwd=Path(__file__).parents[2],
    )
    assert result.returncode == 5, result.stdout + result.stderr
    assert json.loads(result.stderr)["error_code"] == "E_MATERIALIZE_PROBE_PARSE_FAILED"


def test_import_sidecars_stay_beside_their_own_media(media_input: Path, tmp_path: Path) -> None:
    other = media_input / "Other Movie"
    other.mkdir()
    shutil.copyfile(media_input / "Sample Movie" / "Sample Movie.mp4", other / "Sample Movie.mp4")
    shutil.copyfile(media_input / "Sample Movie" / "poster.jpg", other / "poster.jpg")
    (other / "Sample Movie.en.srt").write_text("different subtitle")
    (other / "Sample Movie.nfo").write_text("<movie>different NFO</movie>")
    scenario = tmp_path / "scenario.yaml"
    out = tmp_path / "run"
    for args in [
        ["import", str(media_input), "--out", str(scenario)],
        ["materialize", str(scenario), "--out", str(out)],
    ]:
        result = subprocess.run(
            ["uv", "run", "chaos-librarian", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            cwd=Path(__file__).parents[2],
        )
        assert result.returncode == 0, result.stdout + result.stderr
    videos = list((out / "library").rglob("*.mp4"))
    assert len(videos) == 2
    subtitle_bodies = set()
    nfo_bodies = set()
    for video in videos:
        (subtitle,) = video.parent.glob("*.en.srt")
        (nfo,) = video.parent.glob("*.nfo")
        assert (video.parent / "poster.jpg").is_file()
        subtitle_bodies.add(subtitle.read_text())
        nfo_bodies.add(nfo.read_text())
    assert len(subtitle_bodies) == 2
    assert len(nfo_bodies) == 2


def test_import_preserves_sidecars_with_colliding_sanitized_stems(
    media_input: Path, tmp_path: Path
) -> None:
    root = tmp_path / "collisions"
    movie = root / "Movie"
    movie.mkdir(parents=True)
    for stem, body in [("Cut!", "first"), ("Cut?", "second")]:
        shutil.copyfile(media_input / "Sample Movie" / "Sample Movie.mp4", movie / f"{stem}.mp4")
        (movie / f"{stem}.nfo").write_text(body)
        (movie / f"{stem}.en.srt").write_text(body)
    scenario = tmp_path / "scenario.yaml"
    out = tmp_path / "run"
    for args in [
        ["import", str(root), "--out", str(scenario)],
        ["materialize", str(scenario), "--out", str(out)],
    ]:
        result = subprocess.run(
            ["uv", "run", "chaos-librarian", *args],
            capture_output=True,
            text=True,
            check=False,
            timeout=60,
            cwd=Path(__file__).parents[2],
        )
        assert result.returncode == 0, result.stdout + result.stderr
    for suffix in ["*.nfo", "*.en.srt"]:
        sidecars = list((out / "library").rglob(suffix))
        assert len(sidecars) == 2
        assert {path.read_text() for path in sidecars} == {"first", "second"}
