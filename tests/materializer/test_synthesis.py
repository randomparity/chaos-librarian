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
from chaos_librarian.validation import prepare_run_input_from_bytes, run_validation

_RECIPE_DIGEST = "sha256:" + "f" * 64


def test_materialize_assets_phase_a_collects_and_stamps_manifest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=b"""\
schema_version: 12
scenario_id: static-library
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies:
  - id: w_movie
    title: Static Library Smoke Test
    layout: movie_flat
    variants:
      - id: va_hd
        label: hd
        bundle:
          id: b_hd
          assets:
            - id: a_hd_main
              role: main
              container: mkv
              duration_seconds: 2.0
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
      - id: va_1080
        label: 1080p
        bundle:
          id: b_1080
          assets:
            - id: a_1080_main
              role: main
              container: mp4
              duration_seconds: 2.0
              video:
                source: solid_color
                codec: h264
                resolution: "1080p"
              audio:
                - source: channel_tones
                  codec: aac
                  channels: "5.1"
                  language: eng
      - id: va_sd_subs
        label: sd-subs
        bundle:
          id: b_sd_subs
          assets:
            - id: a_sd_main
              role: main
              container: mkv
              duration_seconds: 2.0
              video:
                source: mandelbrot
                codec: h264
                resolution: sd
              audio:
                - source: sine
                  codec: aac
                  channels: mono
                  language: eng
              subtitles:
                - source: generated_srt
                  codec: srt
                  language: eng
                  mode: sidecar
series: []
artists: []
timeline: []
""",
        source_label="test:static-library.yaml",
    )
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
    expected_paths = [
        "library/library/Static Library Smoke Test - hd.mkv",
        "library/library/Static Library Smoke Test - 1080p.mp4",
        "library/library/Static Library Smoke Test - sd-subs.mkv",
    ]
    assert [item.asset_id for item in phase_a.materialized_assets] == expected_assets
    assert [item.location_path for item in phase_a.materialized_assets] == expected_paths
    assert [item.asset_id for item in phase_a.content_sources] == expected_assets
    assert [item.command[-1] for item in phase_a.invocations] == expected_paths
    assert set(phase_a.probed_by_asset) == set(expected_assets)
    assert artifacts.current_manifest.sidecars
    assert all(version.content_hash is not None for version in artifacts.current_manifest.versions)
    assert all(sidecar.content_hash is not None for sidecar in artifacts.current_manifest.sidecars)


def test_materialize_assets_phase_a_passes_rendered_path_for_unsafe_asset_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=b"""\
schema_version: 12
scenario_id: unsafe-id-materialize
seed: 1
duration_scale: short
library:
  roots:
    - id: r
      path: r
movies:
  - id: movie_safe
    title: Rendered Safe
    layout: movie_flat
    variants:
      - id: variant_safe
        label: hd
        bundle:
          id: bundle_safe
          assets:
            - id: ../../../escape
              role: main
              container: mkv
              duration_seconds: 1
              video:
                source: color_bars
                codec: h264
                resolution: sd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []
timeline: []
""",
        source_label="test:unsafe-id-materialize.yaml",
    )
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

    assert [item.location_path for item in phase_a.materialized_assets] == [
        "library/r/Rendered Safe - hd.mkv"
    ]
    assert [item.command[-1] for item in phase_a.invocations] == [
        "library/r/Rendered Safe - hd.mkv"
    ]


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
    rendered_relative_path: str,
    skip_languages=frozenset(),
) -> MaterializeAssetResult:
    del resolved_seed, out_dir, caps
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
            command=["ffmpeg", str(Path("library") / rendered_relative_path)],
            exit_code=0,
            duration_ns=1,
        ),
        materialized_asset=MaterializedAsset(
            asset_id=asset.id,
            location_path=str(Path("library") / rendered_relative_path),
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
