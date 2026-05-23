"""Layer 2 — ffprobe wrapper with subprocess mocked."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from chaos_librarian.materializer.errors import ProbeParseError
from chaos_librarian.materializer.tooling import probe as probe_mod
from chaos_librarian.materializer.tooling.probe import probe_file

_GOOD_PROBE = json.dumps(
    {
        "format": {
            "format_name": "matroska,webm",
            "duration": "2.000000",
            "size": "12345",
        },
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 640,
                "height": 480,
                "r_frame_rate": "24/1",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "sample_rate": "48000",
                "tags": {"language": "eng"},
            },
        ],
    }
)


def _patch_run(monkeypatch: pytest.MonkeyPatch, stdout: str, returncode: int = 0) -> None:
    def stub(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["ffprobe"], returncode=returncode, stdout=stdout, stderr=""
        )

    monkeypatch.setattr(probe_mod.subprocess, "run", stub)


def test_probe_file_parses_video_and_audio_streams(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: ffprobe-to-ProbedMedia is the only place these fields move
    from JSON strings into typed model attributes; if the mapping breaks,
    the manifest gets garbage values and the Layer 4 smoke test fails
    much later. Catch it here."""
    _patch_run(monkeypatch, _GOOD_PROBE)
    media = probe_file(tmp_path / "fake.mkv")
    assert media.container == "matroska,webm"
    assert media.duration_seconds == 2.0
    assert media.size_bytes == 12345
    video = next(s for s in media.streams if s.kind == "video")
    assert video.codec == "h264"
    assert video.width == 640
    assert video.height == 480
    assert video.fps == 24.0
    audio = next(s for s in media.streams if s.kind == "audio")
    assert audio.codec == "aac"
    assert audio.channels == 2
    assert audio.sample_rate == 48000
    assert audio.language == "eng"


def test_probe_file_raises_on_non_zero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_run(monkeypatch, stdout="", returncode=1)
    with pytest.raises(ProbeParseError):
        probe_file(tmp_path / "broken.mkv")


def test_probe_file_raises_on_unparseable_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_run(monkeypatch, stdout="not json")
    with pytest.raises(ProbeParseError):
        probe_file(tmp_path / "broken.mkv")


def test_probe_file_ignores_subtitle_streams(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Sprint 5 explicitly does NOT add subtitle streams to
    asset.probed.streams[] — sidecar SRTs are separate files and
    embedded subtitles arrive in Sprint 7. If a future ffprobe reports
    one in a Sprint 5 fixture, we drop it silently here."""
    probe = json.loads(_GOOD_PROBE)
    probe["streams"].append({"codec_type": "subtitle", "codec_name": "srt"})
    _patch_run(monkeypatch, json.dumps(probe))
    media = probe_file(tmp_path / "fake.mkv")
    assert all(s.kind != "subtitle" for s in media.streams)
