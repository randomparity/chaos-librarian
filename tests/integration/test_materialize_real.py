"""Layer 4 — real ffmpeg integration tests. Skipped if ffmpeg < 7.0."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from itertools import pairwise
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.canonicalize import canonicalize
from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.materializer.tooling.capabilities import (
    MIN_VERSIONS,
    detect_capabilities,
)

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _ffmpeg_meets_minimum() -> bool:
    caps = detect_capabilities()
    return caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum


pytestmark = pytest.mark.skipif(
    not _ffmpeg_meets_minimum(),
    reason=f"ffmpeg/ffprobe >= {MIN_VERSIONS['ffmpeg']} not available",
)


def test_materialize_static_library_smoke(tmp_path: Path) -> None:
    """WHY: end-to-end smoke — every asset must exist, probe successfully,
    content_hash must match the file bytes, no failures, AND (Finding 1)
    sidecars must exist with content_hash matching file bytes, with NO
    subtitle entries in asset.probed.streams[]."""
    out = tmp_path / "smoke"
    result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "static-library.yaml"), "--out", str(out), "--json"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    manifest = Manifest.model_validate_json((out / "manifest.current.json").read_text())
    materialization = json.loads((out / "materialization.json").read_text())
    assert materialization["outcome"] == "success"
    assert materialization["failures"] == []

    library_root = out / "library"
    for version in manifest.versions:
        location = next(loc for loc in manifest.locations if loc.asset_id == version.asset_id)
        # ManifestLocation.path is relative to <run-dir>/library/ (spec
        # "Path Containment"). Sprint 5 happened to put files at
        # ``out / location.path`` because synthesis ignored the asset's
        # primary root path; Sprint 6 fixes that and the assertion follows
        # the documented contract.
        path = library_root / location.path
        assert path.exists()
        assert version.content_hash is not None
        actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        assert version.content_hash == actual
        assert version.probed is not None
        assert all(s.kind != "subtitle" for s in version.probed.streams)

    for sidecar in manifest.sidecars:
        path = library_root / sidecar.path
        assert path.exists()
        assert sidecar.content_hash is not None
        actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        assert sidecar.content_hash == actual


def test_materialize_bitexact_same_toolchain(tmp_path: Path) -> None:
    """WHY: bit-exact determinism within a fixed toolchain is the Sprint 5
    contract; two runs of the same scenario+seed must produce identical
    content_hash values for every asset."""
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    for out in (out_a, out_b):
        result = runner.invoke(
            app,
            ["materialize", str(FIXTURE_DIR / "static-library.yaml"), "--out", str(out)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
    manifest_a = Manifest.model_validate_json((out_a / "manifest.current.json").read_text())
    manifest_b = Manifest.model_validate_json((out_b / "manifest.current.json").read_text())
    hashes_a = sorted((v.asset_id, v.content_hash) for v in manifest_a.versions)
    hashes_b = sorted((v.asset_id, v.content_hash) for v in manifest_b.versions)
    assert hashes_a == hashes_b


def test_materialize_cross_mode_logical_oracle_ids(tmp_path: Path) -> None:
    """WHY: plan-only and materialize must produce the same logical-oracle
    structure for the same scenario+seed; the canonicalize() helper proves
    the manifests match modulo stripped fields (content_hash + probed).

    Sprint 5 scope: the engine does NOT pre-populate sidecars declared via
    ``scenario.subtitles`` (sidecars in plan-only manifests come only from
    ``create_sidecar`` timeline events). The materializer augments its
    manifest with one ManifestSidecar per materialized SRT (run.py
    ``_augment_manifest``). The two modes therefore disagree on the
    sidecars list for static scenarios. We compare structural fields
    excluding sidecars; the smoke test above already pins materialize-side
    sidecar invariants. Lifting this scope limit is tracked for a future
    sprint (engine populates static sidecars in initial state).
    """
    plan_out = tmp_path / "plan"
    mat_out = tmp_path / "mat"
    plan_result = runner.invoke(
        app, ["plan", str(FIXTURE_DIR / "static-library.yaml"), "--out", str(plan_out)]
    )
    assert plan_result.exit_code == 0, plan_result.stdout + plan_result.stderr
    mat_result = runner.invoke(
        app, ["materialize", str(FIXTURE_DIR / "static-library.yaml"), "--out", str(mat_out)]
    )
    assert mat_result.exit_code == 0, mat_result.stdout + mat_result.stderr
    plan_manifest = Manifest.model_validate_json((plan_out / "manifest.current.json").read_text())
    mat_manifest = Manifest.model_validate_json((mat_out / "manifest.current.json").read_text())
    plan_canonical = canonicalize(plan_manifest)
    mat_canonical = canonicalize(mat_manifest)
    plan_canonical.pop("sidecars", None)
    mat_canonical.pop("sidecars", None)
    assert plan_canonical == mat_canonical
    assert (plan_out / "journal.jsonl").read_text() == (mat_out / "journal.jsonl").read_text()


def test_materialize_hevc_mkv_when_libx265_available(tmp_path: Path) -> None:
    """WHY: issue #95 requires real HEVC/H.265 synthesis when the host
    FFmpeg advertises libx265."""
    caps = detect_capabilities()
    if not caps.ready_for.materialize_hevc_video:
        pytest.skip("FFmpeg libx265 encoder not available")
    out = tmp_path / "hevc"
    result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "hevc-mkv.yaml"), "--out", str(out), "--json"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr

    manifest = Manifest.model_validate_json((out / "manifest.current.json").read_text())
    video_streams = [
        stream
        for version in manifest.versions
        if version.probed is not None
        for stream in version.probed.streams
        if stream.kind == "video"
    ]
    assert [stream.codec for stream in video_streams] == ["hevc"]


@pytest.mark.parametrize(
    ("cadence", "expected_intervals"),
    [
        ("24_to_30", ({41, 42}, {33, 34})),
        ("30_to_60", ({33, 34}, {16, 17})),
        ("24_30_60", ({41, 42}, {33, 34}, {16, 17})),
    ],
)
def test_materialize_vfr_video_has_variable_packet_intervals(
    cadence: str, expected_intervals: tuple[set[int], ...], tmp_path: Path
) -> None:
    """WHY: #129 needs packet cadence to differ from plain CFR, not only a
    schema knob. ffprobe packet PTS deltas prove each supported cadence
    materializes with its requested timing sections."""
    scenario_path = _vfr_scenario_for(cadence, tmp_path)
    out = tmp_path / "vfr"
    result = runner.invoke(
        app,
        ["materialize", str(scenario_path), "--out", str(out), "--json"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    media_path = next((out / "library").rglob("*.mkv"))

    deltas = _video_packet_deltas(media_path)

    assert len(set(deltas)) > 1
    for interval in expected_intervals:
        assert any(delta in interval for delta in deltas)


@pytest.mark.parametrize(
    ("field_order", "expected_probe"),
    [
        ("top_field_first", "tb"),
        ("bottom_field_first", "bt"),
    ],
)
def test_materialize_interlaced_video_reports_field_order(
    field_order: str, expected_probe: str, tmp_path: Path
) -> None:
    """WHY: #130 needs scanner-visible interlaced metadata, not only a
    scenario knob. ffprobe field_order proves the encoded stream carries
    the requested ordering."""
    scenario_path = _interlaced_scenario_for(field_order, tmp_path)
    out = tmp_path / "interlaced"
    result = runner.invoke(
        app,
        ["materialize", str(scenario_path), "--out", str(out), "--json"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    media_path = next((out / "library").rglob("*.mkv"))

    assert _video_field_order(media_path) == expected_probe


def test_capabilities_real() -> None:
    """WHY: the capabilities CLI is the agent's entry point for capability
    probing — round-trip the JSON through Capabilities to lock the
    contract."""
    completed = subprocess.run(
        ["uv", "run", "chaos-librarian", "capabilities", "--json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    Capabilities.model_validate_json(completed.stdout)


def _video_packet_deltas(path: Path) -> list[int]:
    completed = subprocess.run(
        [
            "ffprobe",
            "-hide_banner",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "packet=pts_time",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    pts_values = sorted(
        float(packet["pts_time"])
        for packet in payload["packets"]
        if isinstance(packet, dict) and "pts_time" in packet
    )
    return [round((current - previous) * 1000) for previous, current in pairwise(pts_values)]


def _video_field_order(path: Path) -> str:
    completed = subprocess.run(
        [
            "ffprobe",
            "-hide_banner",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=field_order",
            "-of",
            "json",
            str(path),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    streams = payload["streams"]
    assert len(streams) == 1
    return streams[0]["field_order"]


def _vfr_scenario_for(cadence: str, tmp_path: Path) -> Path:
    scenario = (FIXTURE_DIR / "vfr-video.yaml").read_text()
    scenario = scenario.replace("scenario_id: vfr-video", f"scenario_id: vfr-video-{cadence}")
    scenario = scenario.replace("vfr_cadence: 24_30_60", f"vfr_cadence: {cadence}")
    scenario_path = tmp_path / f"vfr-{cadence}.yaml"
    scenario_path.write_text(scenario)
    return scenario_path


def _interlaced_scenario_for(field_order: str, tmp_path: Path) -> Path:
    scenario = (FIXTURE_DIR / "interlaced-video.yaml").read_text()
    scenario = scenario.replace(
        "scenario_id: interlaced-video",
        f"scenario_id: interlaced-video-{field_order}",
    )
    scenario = scenario.replace(
        "field_order: top_field_first",
        f"field_order: {field_order}",
    )
    scenario_path = tmp_path / f"interlaced-{field_order}.yaml"
    scenario_path.write_text(scenario)
    return scenario_path


def _install_failing_ffmpeg(bin_dir: Path) -> None:
    """Drop an ``ffmpeg`` shim into ``bin_dir`` that fakes a healthy ``-version``
    response but fails (exit 1) on any real materialize invocation.

    The capability gate at the top of ``materialize_scenario`` re-probes
    ffmpeg via ``shutil.which`` + ``ffmpeg -version`` on every call; a shim
    that always exits 1 would trip the gate (exit 4) before we ever reach
    the synthesis loop we want to fail. Responding correctly to ``-version``
    keeps the gate green so the failure surfaces from the orchestrator's
    ``ToolFailedError`` path (exit 5), which is the contract under test.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    shim = bin_dir / "ffmpeg"
    shim.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "-version" ]; then\n'
        '  echo "ffmpeg version 7.0"\n'
        "  exit 0\n"
        "fi\n"
        "exit 1\n"
    )
    shim.chmod(0o755)


def test_materialize_unsupported_codec_fails_validation_before_allocation(tmp_path: Path) -> None:
    """WHY: unsupported static media values now fail semantic validation before
    preflight or run-dir allocation; the envelope must omit
    materialization_report_path."""
    bad_yaml = (
        (FIXTURE_DIR / "static-library.yaml").read_text().replace("codec: aac", "codec: opus", 1)
    )
    scenario_path = tmp_path / "opus.yaml"
    scenario_path.write_text(bad_yaml)
    out = tmp_path / "no_run_dir_please"
    result = runner.invoke(app, ["materialize", str(scenario_path), "--out", str(out), "--json"])
    assert result.exit_code == 3
    payload = json.loads(result.stderr)
    assert payload["error_code"] == "E_MATERIALIZE_VALIDATION_FAILED"
    validation_report = payload["details"]["validation_report"]
    assert any(
        issue["code"] == "E_MATERIALIZE_UNSUPPORTED" for issue in validation_report["issues"]
    )
    assert "materialization_report_path" not in payload
    assert not out.exists()


def test_materialize_tool_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """WHY: a synthesis-time tool failure must wipe library/, write a
    failure-decorated materialization.json, and flip the sentinel to
    state=complete (caught failure). Finding 4: replay.json and
    manifest.current.json must still exist so inspect/clean keep working."""
    bin_dir = tmp_path / "bin"
    _install_failing_ffmpeg(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    out = tmp_path / "failed"
    result = runner.invoke(
        app,
        [
            "materialize",
            str(FIXTURE_DIR / "static-library.yaml"),
            "--out",
            str(out),
            "--json",
        ],
    )
    assert result.exit_code == 5, result.stdout + result.stderr
    assert (out / ".chaos-librarian-run").exists()
    sentinel = json.loads((out / ".chaos-librarian-run").read_text())
    assert sentinel["state"] == "complete"
    assert list((out / "library").iterdir()) == []
    report = json.loads((out / "materialization.json").read_text())
    assert report["outcome"] == "tool_failed"
    assert report["failures"]
    for required in ("replay.json", "manifest.current.json"):
        assert (out / required).exists(), required


def test_inspect_works_against_failed_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """WHY: Finding 4 — ``inspect`` reads ``replay.json`` and
    ``manifest.current.json`` unguarded; a failed run-dir missing either
    file crashes the command with exit 1. ``cleanup_failed_run`` must
    emit both so the standard inspect surface keeps working post-failure,
    and ``clean`` must then accept the failed run-dir."""
    bin_dir = tmp_path / "bin"
    _install_failing_ffmpeg(bin_dir)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")

    out = tmp_path / "failed_for_inspect"
    materialize_result = runner.invoke(
        app,
        [
            "materialize",
            str(FIXTURE_DIR / "static-library.yaml"),
            "--out",
            str(out),
            "--json",
        ],
    )
    assert materialize_result.exit_code == 5, materialize_result.stdout + materialize_result.stderr

    inspect_result = runner.invoke(app, ["inspect", str(out), "--json"])
    assert inspect_result.exit_code == 0, inspect_result.stdout + inspect_result.stderr
    inspect_payload = json.loads(inspect_result.stdout)
    assert inspect_payload["sentinel"]["state"] == "complete"
    assert inspect_payload["execution_mode"] == "materialize"

    clean_result = runner.invoke(app, ["clean", str(out)])
    assert clean_result.exit_code == 0, clean_result.stdout + clean_result.stderr
    assert not out.exists()


def test_materialize_interrupted_recovery(tmp_path: Path) -> None:
    """WHY: Finding 2 — uncaught signals leave state=in_progress; inspect
    surfaces it, step refuses with E_SENTINEL_IN_PROGRESS exit 7, clean
    accepts the dir.

    A real signal-interrupted materialize is hard to simulate
    cross-platform; the contract under test is the sentinel ``state``
    surface alone, so mutating the sentinel of a successful plan run-dir
    is a faithful stand-in.
    """
    out = tmp_path / "partial"
    plan_result = runner.invoke(
        app, ["plan", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out)]
    )
    assert plan_result.exit_code == 0, plan_result.stdout + plan_result.stderr
    sentinel_path = out / ".chaos-librarian-run"
    blob = json.loads(sentinel_path.read_text())
    blob["state"] = "in_progress"
    sentinel_path.write_text(json.dumps(blob, indent=2) + "\n")

    inspect_result = runner.invoke(app, ["inspect", str(out), "--json"])
    assert inspect_result.exit_code == 0, inspect_result.stdout + inspect_result.stderr
    assert json.loads(inspect_result.stdout)["sentinel"]["state"] == "in_progress"

    step_result = runner.invoke(app, ["step", str(out), "--json"])
    assert step_result.exit_code == 7, step_result.stdout + step_result.stderr
    step_payload = json.loads(step_result.stderr)
    assert step_payload["error_code"] == "E_SENTINEL_IN_PROGRESS"

    clean_result = runner.invoke(app, ["clean", str(out)])
    assert clean_result.exit_code == 0, clean_result.stdout + clean_result.stderr
    assert not out.exists()
