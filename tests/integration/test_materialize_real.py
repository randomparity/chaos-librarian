"""Layer 4 — real ffmpeg integration tests. Skipped if ffmpeg < 7.0."""

from __future__ import annotations

import hashlib
import json
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
