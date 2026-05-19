"""Layer 4 — real ffmpeg integration tests. Skipped if ffmpeg < 7.0."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.canonicalize import canonicalize
from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.materializer.capabilities import (
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

    for version in manifest.versions:
        location = next(loc for loc in manifest.locations if loc.asset_id == version.asset_id)
        path = out / location.path
        assert path.exists()
        assert version.content_hash is not None
        actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        assert version.content_hash == actual
        assert version.probed is not None
        assert all(s.kind != "subtitle" for s in version.probed.streams)

    for sidecar in manifest.sidecars:
        path = out / sidecar.path
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


def test_materialize_unsupported_codec(tmp_path: Path) -> None:
    """WHY: lazy allocation (Finding 3) — pre-synthesis rejection must
    leave NO on-disk artifact; the stdout JSON must omit
    materialization_report_path."""
    bad_yaml = (
        (FIXTURE_DIR / "static-library.yaml").read_text().replace("codec: aac", "codec: opus", 1)
    )
    scenario_path = tmp_path / "opus.yaml"
    scenario_path.write_text(bad_yaml)
    out = tmp_path / "no_run_dir_please"
    result = runner.invoke(app, ["materialize", str(scenario_path), "--out", str(out), "--json"])
    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "E_MATERIALIZE_UNSUPPORTED"
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
    assert step_payload["error"] == "E_SENTINEL_IN_PROGRESS"

    clean_result = runner.invoke(app, ["clean", str(out)])
    assert clean_result.exit_code == 0, clean_result.stdout + clean_result.stderr
    assert not out.exists()
