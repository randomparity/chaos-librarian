"""Phase-A synthesis helper coverage."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.content_sources import (
    CacheDisposition,
    ContentSourceCapabilities,
    ContentSourceEvidence,
    ContentTrackKind,
)
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
from chaos_librarian.contract.materialization import MaterializedAsset, ToolInvocation
from chaos_librarian.engine import run_plan
from chaos_librarian.materializer import synthesis as synthesis_mod
from chaos_librarian.materializer.synthesis import (
    MaterializeAssetResult,
    materialize_assets_phase_a,
)
from chaos_librarian.validation import prepare_run_input, run_validation

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
_RECIPE_DIGEST = "sha256:" + "f" * 64


def test_materialize_assets_phase_a_collects_and_stamps_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_input = prepare_run_input(FIXTURE_DIR / "static-library.yaml")
    validation_report = run_validation(run_input)
    assert validation_report.ok
    artifacts = run_plan(run_input=run_input, validation_report=validation_report)

    monkeypatch.setattr(synthesis_mod, "materialize_one_asset", _fake_materialize_one_asset)

    phase_a = materialize_assets_phase_a(
        scenario=run_input.scenario,
        out_dir=tmp_path,
        artifacts=artifacts,
        caps=_caps(),
        stamp_manifest=True,
    )

    expected_assets = ["a_hd_main", "a_1080_main", "a_sd_main"]
    assert [item.asset_id for item in phase_a.materialized_assets] == expected_assets
    assert [item.asset_id for item in phase_a.content_sources] == expected_assets
    assert [item.command[-1] for item in phase_a.invocations] == expected_assets
    assert set(phase_a.probed_by_asset) == set(expected_assets)
    assert artifacts.current_manifest.sidecars
    assert all(version.content_hash is not None for version in artifacts.current_manifest.versions)
    assert all(sidecar.content_hash is not None for sidecar in artifacts.current_manifest.sidecars)


def _caps() -> Capabilities:
    return Capabilities(
        schema_version=3,
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
        ),
    )


def _fake_materialize_one_asset(
    asset,
    resolved_seed,
    out_dir: Path,
    caps,
    invocation_index: int,
    *,
    root_path: str,
    skip_languages=frozenset(),
) -> MaterializeAssetResult:
    del resolved_seed, out_dir, caps, root_path
    data = f"{asset.id}-bytes".encode()
    content_hash = "sha256:" + hashlib.sha256(data).hexdigest()
    sidecar_hashes = {
        (asset.id, sub.language): "sha256:" + hashlib.sha256(sub.language.encode()).hexdigest()
        for sub in asset.subtitles
        if sub.language not in skip_languages
    }
    return MaterializeAssetResult(
        invocation=ToolInvocation(
            tool="ffmpeg",
            version="7.1.1",
            command=["ffmpeg", asset.id],
            exit_code=0,
            duration_ns=1,
        ),
        materialized_asset=MaterializedAsset(
            asset_id=asset.id,
            location_path=f"library/{asset.id}.{asset.container}",
            content_hash=content_hash,
            size_bytes=len(data),
            duration_seconds=asset.duration_seconds,
            invocation_index=invocation_index,
        ),
        probed=ProbedMedia(
            container=asset.container,
            duration_seconds=asset.duration_seconds,
            size_bytes=len(data),
            streams=[ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480)],
        ),
        sidecar_hashes=sidecar_hashes,
        content_sources=(
            ContentSourceEvidence(
                asset_id=asset.id,
                track_kind=ContentTrackKind.VIDEO,
                source="fake-video",
                provider="fake-provider",
                recipe_digest=_RECIPE_DIGEST,
                cache_disposition=CacheDisposition.NOT_CACHEABLE,
            ),
        ),
    )
