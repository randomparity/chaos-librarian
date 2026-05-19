"""Layer 3 — orchestrator with run_ffmpeg and probe_file mocked."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.capabilities import (
    Capabilities,
    ReadyFor,
    ToolStatus,
)
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream
from chaos_librarian.contract.materialization import (
    Outcome,
    ToolInvocation,
)
from chaos_librarian.materializer import run as run_mod
from chaos_librarian.materializer.errors import (
    ScenarioValidationError,
    TimelineUnsupportedError,
    ToolFailedError,
    UnsupportedMaterializationError,
)
from chaos_librarian.materializer.run import materialize_scenario

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
INVALID_FIXTURE_DIR = FIXTURE_DIR / "invalid"


@pytest.fixture(autouse=True)
def _patch_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    """All Layer 3 tests assume capabilities pass; only behavior we care
    about is the orchestrator's own logic."""
    caps = Capabilities(
        schema_version=1,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=False,
        ),
    )
    monkeypatch.setattr(run_mod, "detect_capabilities", lambda: caps)


def _patch_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make run_ffmpeg + probe_file both succeed for every asset."""

    def fake_run(
        argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0
    ) -> tuple[ToolInvocation, str]:
        del timeout_s
        output = Path(argv[-1])
        output.write_bytes(b"x")
        invocation = ToolInvocation(
            tool="ffmpeg",
            version=ffmpeg_version,
            command=argv,
            exit_code=0,
            duration_ns=1_000_000,
        )
        return invocation, ""

    def fake_probe(_path: Path) -> ProbedMedia:
        return ProbedMedia(
            container="matroska,webm",
            duration_seconds=1.0,
            size_bytes=1,
            streams=[ProbedStream(kind="video", codec="h264", width=640, height=480, fps=24.0)],
        )

    monkeypatch.setattr(run_mod, "run_ffmpeg", fake_run)
    monkeypatch.setattr(run_mod, "probe_file", fake_probe)


def test_orchestrator_refuses_non_empty_timeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Sprint 5 supports only static scenarios. The orchestrator
    rejects with E_MATERIALIZE_TIMELINE_UNSUPPORTED before any subprocess
    starts, and the spec's lazy-allocation guarantee means no run-dir
    exists on exit."""
    _patch_success(monkeypatch)
    out = tmp_path / "run"
    with pytest.raises(TimelineUnsupportedError):
        materialize_scenario(FIXTURE_DIR / "slow-copy.yaml", out)
    assert not out.exists()


def test_orchestrator_refuses_unsupported_audio_codec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Sprint 5 matrix rejects opus at pre-flight; the run-dir must
    not be created (lazy allocation guarantee, Finding 3)."""
    _patch_success(monkeypatch)
    scenario = tmp_path / "opus.yaml"
    scenario.write_text(_STATIC_SCENARIO_OPUS)
    out = tmp_path / "run"
    with pytest.raises(UnsupportedMaterializationError) as exc:
        materialize_scenario(scenario, out)
    assert exc.value.field == "audio[0].codec"
    assert not out.exists()


def test_orchestrator_records_ffmpeg_failure_and_wipes_library(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: a synthesis-time failure leaves a partial run-dir with the
    sentinel at state=complete (caught failure), library/ wiped, and
    materialization.json populated with the failure record."""

    def fake_run(
        argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0
    ) -> tuple[ToolInvocation, str]:
        del timeout_s
        invocation = ToolInvocation(
            tool="ffmpeg",
            version=ffmpeg_version,
            command=argv,
            exit_code=1,
            duration_ns=500_000,
        )
        return invocation, "ffmpeg simulated failure"

    def fail_probe(_path: Path) -> ProbedMedia:
        pytest.fail("probe should not be called")

    monkeypatch.setattr(run_mod, "run_ffmpeg", fake_run)
    monkeypatch.setattr(run_mod, "probe_file", fail_probe)
    scenario = tmp_path / "static.yaml"
    scenario.write_text(_STATIC_SCENARIO)
    out = tmp_path / "run"
    with pytest.raises(ToolFailedError):
        materialize_scenario(scenario, out)
    assert out.exists()
    assert (out / ".chaos-librarian-run").exists()
    assert list((out / "library").iterdir()) == []
    materialization = (out / "materialization.json").read_text()
    assert '"outcome": "tool_failed"' in materialization


def test_orchestrator_success_path_populates_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: the success path's contract is content_hash + probed populated
    for every asset version, and content_hash populated for every sidecar
    (Finding 3) in manifest.current.json."""
    _patch_success(monkeypatch)
    scenario = tmp_path / "static.yaml"
    scenario.write_text(_STATIC_SCENARIO)
    out = tmp_path / "run"
    artifacts = materialize_scenario(scenario, out)
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    for version in artifacts.current_manifest.versions:
        assert version.content_hash is not None
        assert version.probed is not None
    assert artifacts.current_manifest.sidecars, (
        "_STATIC_SCENARIO declares a sidecar SRT; the manifest must reflect it"
    )
    for sidecar in artifacts.current_manifest.sidecars:
        assert sidecar.content_hash is not None
        assert sidecar.content_hash.startswith("sha256:")


def test_orchestrator_refuses_semantically_invalid_scenario(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Finding 1 — Sprint 5 must not produce filesystem writes for
    scenarios that fail semantic validation (path containment, unsafe
    path components, etc.). The validation gate runs before any run-dir
    allocation. Any invalid fixture suffices; the gate's behavior is
    uniform across semantic-error codes."""
    _patch_success(monkeypatch)
    invalid = INVALID_FIXTURE_DIR / "path-escape.yaml"
    out = tmp_path / "must_not_exist"
    with pytest.raises(ScenarioValidationError) as exc:
        materialize_scenario(invalid, out)
    assert exc.value.validation_report.ok is False
    assert not out.exists()


def test_orchestrator_rejects_embedded_subtitle_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Finding 2 — Sprint 5 supports sidecar-only; embedded lands in
    Sprint 7. Falling through silently would produce media missing the
    requested subtitles."""
    _patch_success(monkeypatch)
    scenario = tmp_path / "embedded.yaml"
    scenario.write_text(_STATIC_SCENARIO_WITH_EMBEDDED_SUBS)
    out = tmp_path / "run"
    with pytest.raises(UnsupportedMaterializationError) as exc:
        materialize_scenario(scenario, out)
    assert exc.value.field == "subtitle[0].mode"
    assert not out.exists()


def test_orchestrator_rejects_unsupported_subtitle_codec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Finding 2 — Sprint 5 supports SRT only; ASS/SSA would otherwise
    fall through preflight and ``write_text`` SRT bytes under an ``.ass``
    filename, silently producing wrong content."""
    _patch_success(monkeypatch)
    scenario = tmp_path / "ass.yaml"
    scenario.write_text(_STATIC_SCENARIO_WITH_ASS_SUBS)
    out = tmp_path / "run"
    with pytest.raises(UnsupportedMaterializationError) as exc:
        materialize_scenario(scenario, out)
    assert exc.value.field == "subtitle[0].codec"
    assert not out.exists()


def test_orchestrator_probes_each_asset_exactly_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Finding 5 — re-probing wastes a subprocess per asset and
    (previously) used a run-dir-relative path that misresolved against
    the CLI cwd. Lock the call count and absolute-path invariant to
    catch a regression that re-introduces the second probe_file call."""

    def fake_run(
        argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0
    ) -> tuple[ToolInvocation, str]:
        del timeout_s
        output = Path(argv[-1])
        output.write_bytes(b"x")
        invocation = ToolInvocation(
            tool="ffmpeg",
            version=ffmpeg_version,
            command=argv,
            exit_code=0,
            duration_ns=1_000_000,
        )
        return invocation, ""

    calls: list[Path] = []

    def counting_probe(path: Path) -> ProbedMedia:
        calls.append(path)
        return ProbedMedia(
            container="matroska,webm",
            duration_seconds=1.0,
            size_bytes=1,
            streams=[ProbedStream(kind="video", codec="h264", width=640, height=480, fps=24.0)],
        )

    monkeypatch.setattr(run_mod, "run_ffmpeg", fake_run)
    monkeypatch.setattr(run_mod, "probe_file", counting_probe)
    scenario = tmp_path / "static.yaml"
    scenario.write_text(_STATIC_SCENARIO)
    out = tmp_path / "run"
    materialize_scenario(scenario, out)
    assert len(calls) == 1
    assert all(path.is_absolute() for path in calls)


_STATIC_SCENARIO = """\
schema_version: 3
scenario_id: static-test
seed: 1
duration_scale: short
library:
  roots:
    - id: r0
      path: library
works:
  - id: w0
    title: Static
    variants:
      - id: va0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: main
              container: mkv
              duration_seconds: 1.0
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
              subtitles:
                - codec: srt
                  language: eng
                  mode: sidecar
                  source: generated_srt
timeline: []
"""

_STATIC_SCENARIO_OPUS = _STATIC_SCENARIO.replace("codec: aac", "codec: opus")

_STATIC_SCENARIO_WITH_EMBEDDED_SUBS = _STATIC_SCENARIO.replace(
    "mode: sidecar",
    "mode: embedded",
)

_STATIC_SCENARIO_WITH_ASS_SUBS = _STATIC_SCENARIO.replace(
    "codec: srt",
    "codec: ass",
)
