"""Layer-3 materializer orchestrator tests for Sprint 7 — mocked ffmpeg.

WHY: Sprint 7 replaces Sprint 6's single ``apply_phase_b`` call with a
unified per-journal-entry walk that dispatches to ``filesystem.apply_filesystem_action``
(stdlib ops) or ``media.apply_media_action`` (ffmpeg-backed). These tests
exercise both the success path (one media action recorded) and the
media-failure path (``MediaActionError`` raised, ``library/`` wiped, and
``materialization.json`` written with ``outcome=media_failed``) without
requiring real ffmpeg on the host.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import chaos_librarian.materializer.preparation.run_setup as prep_mod
from chaos_librarian.contract.capabilities import (
    Capabilities,
    ReadyFor,
    ToolStatus,
)
from chaos_librarian.contract.content_sources import ContentSourceCapabilities
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.materialization import Outcome, ToolInvocation
from chaos_librarian.materializer.errors import MediaActionError
from chaos_librarian.materializer.run import materialize_scenario

_REENCODE_SCENARIO_BODY = """\
schema_version: 32
scenario_id: sc_test
seed: 42
duration_scale: short
library:
  roots:
    - id: r0
      path: library/r0
movies:
  - id: movie_0
    title: T
    layout: movie_flat
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
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []
timeline:
  - id: ev_rv_001
    at: 1s
    action: reencode_video
    target: a0
    resolution: sd
    codec: h264
"""


def _write_scenario(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "scenario.yaml"
    path.write_text(body)
    return path


def _fake_capabilities() -> Capabilities:
    return Capabilities(
        schema_version=7,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=False,
            materialize_hevc_video=True,
            materialize_hdr_video=True,
            materialize_resolution_switch_video=True,
            materialize_audio_recipes=True,
            materialize_matroska_muxing_profiles=True,
            materialize_webm_video=True,
        ),
    )


@pytest.fixture
def mocked_ffmpeg_and_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch run_ffmpeg + probe_file (synthesis + media) + detect_capabilities."""

    def fake_run(
        argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0
    ) -> tuple[ToolInvocation, str]:
        del timeout_s
        Path(argv[-1]).write_bytes(b"x" * 100)
        return (
            ToolInvocation(
                tool="ffmpeg",
                version=ffmpeg_version,
                command=list(argv),
                exit_code=0,
                duration_ns=1,
            ),
            "",
        )

    def fake_probe(_path: Path, **_kwargs: object) -> ProbedMedia:
        return ProbedMedia(
            container="matroska",
            duration_seconds=1.0,
            size_bytes=100,
            streams=[],
        )

    monkeypatch.setattr("chaos_librarian.materializer.phase_b.media.run_ffmpeg", fake_run)
    monkeypatch.setattr("chaos_librarian.materializer.phase_b.media.probe_file", fake_probe)
    monkeypatch.setattr("chaos_librarian.materializer.content.synthesis.run_ffmpeg", fake_run)
    monkeypatch.setattr("chaos_librarian.materializer.content.synthesis.probe_file", fake_probe)
    monkeypatch.setattr(prep_mod, "detect_capabilities", _fake_capabilities)


def test_materialize_reencode_video_timeline_runs_phase_b(
    tmp_path: Path, mocked_ffmpeg_and_probe: None
) -> None:
    """WHY: a reencode_video timeline must walk through the unified phase-B
    dispatcher and produce a single MediaAction in the report. This locks
    the orchestrator's contract that media ops are now first-class
    citizens alongside stdlib ops."""
    del mocked_ffmpeg_and_probe
    scenario_yaml = _write_scenario(tmp_path, _REENCODE_SCENARIO_BODY)
    out_dir = tmp_path / "run-001"
    artifacts = materialize_scenario(scenario_yaml, out_dir)
    assert (out_dir / "library").exists()
    report = artifacts.materialization_report
    assert report.outcome == Outcome.SUCCESS
    assert len(report.media_actions) == 1
    assert report.media_actions[0].action.value == "reencode_video"


def test_materialize_media_failure_wipes_library_and_writes_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """WHY: a MediaActionError from a phase-B media handler must route
    through ``finalize_failure_phase_b`` with ``outcome=media_failed``,
    wipe ``library/`` entirely, and leave a readable
    ``materialization.json`` for ``inspect`` / ``clean`` consumers."""

    def fake_run_success(
        argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0
    ) -> tuple[ToolInvocation, str]:
        """Phase-A synthesis succeeds; only phase-B media calls fail."""
        del timeout_s
        Path(argv[-1]).write_bytes(b"x" * 100)
        return (
            ToolInvocation(
                tool="ffmpeg",
                version=ffmpeg_version,
                command=list(argv),
                exit_code=0,
                duration_ns=1,
            ),
            "",
        )

    def failing_run(
        argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0
    ) -> tuple[ToolInvocation, str]:
        del timeout_s
        return (
            ToolInvocation(
                tool="ffmpeg",
                version=ffmpeg_version,
                command=list(argv),
                exit_code=1,
                duration_ns=1,
            ),
            "stub stderr",
        )

    def fake_probe(_path: Path, **_kwargs: object) -> ProbedMedia:
        return ProbedMedia(
            container="matroska",
            duration_seconds=1.0,
            size_bytes=100,
            streams=[],
        )

    # Synthesis (phase A) must succeed so phase B is reached.
    monkeypatch.setattr(
        "chaos_librarian.materializer.content.synthesis.run_ffmpeg",
        fake_run_success,
    )
    monkeypatch.setattr("chaos_librarian.materializer.content.synthesis.probe_file", fake_probe)
    # Media handlers (phase B) fail with non-zero exit.
    monkeypatch.setattr("chaos_librarian.materializer.phase_b.media.run_ffmpeg", failing_run)
    monkeypatch.setattr("chaos_librarian.materializer.phase_b.media.probe_file", fake_probe)
    monkeypatch.setattr(prep_mod, "detect_capabilities", _fake_capabilities)

    scenario_yaml = _write_scenario(tmp_path, _REENCODE_SCENARIO_BODY)
    out_dir = tmp_path / "run-002"
    with pytest.raises(MediaActionError):
        materialize_scenario(scenario_yaml, out_dir)
    # library/ wiped — phase-B failures leave no placeholder.
    assert not (out_dir / "library").exists()
    # materialization.json present with outcome=media_failed.
    report_path = out_dir / "materialization.json"
    assert report_path.exists()
    body = json.loads(report_path.read_text())
    assert body["outcome"] == "media_failed"
