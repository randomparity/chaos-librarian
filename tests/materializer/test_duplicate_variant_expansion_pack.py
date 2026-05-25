"""Materializer coverage for the duplicate/variant expansion-pack fixture."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.content_sources import ContentSourceCapabilities
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import resolve_seed
from chaos_librarian.materializer import synthesis as synthesis_mod
from chaos_librarian.materializer.preflight import iter_assets
from chaos_librarian.materializer.synthesis import materialize_one_asset
from chaos_librarian.validation import prepare_run_input_from_bytes

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
EXPANSION_FIXTURE = FIXTURE_DIR / "duplicate-variant-expanded.yaml"


def test_duplicate_variant_expansion_pack_materialized_hash_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: prober exports need real manifest hashes, not just identical YAML recipes."""
    monkeypatch.setattr(synthesis_mod, "run_ffmpeg", _fake_run_ffmpeg)
    monkeypatch.setattr(synthesis_mod, "probe_file", _fake_probe_file)

    scenario = _scenario()
    hashes = _materialized_hashes(scenario, tmp_path / "run")

    assert hashes["asset_echo_hd_a"] == hashes["asset_echo_hd_b"]
    assert hashes["asset_pair_disc_a"] == hashes["asset_pair_disc_b"]
    assert hashes["asset_echo_sd"] != hashes["asset_echo_hd_a"]
    assert hashes["asset_ladder_1080p"] != hashes["asset_ladder_sd"]


def _scenario() -> Scenario:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=EXPANSION_FIXTURE.read_bytes(),
        source_label=f"test:{EXPANSION_FIXTURE.name}",
    )
    return run_input.scenario


def _materialized_hashes(scenario: Scenario, out_dir: Path) -> dict[str, str]:
    seed = resolve_seed(scenario.seed)
    root_path = scenario.library.roots[0].path
    caps = _capabilities()
    hashes: dict[str, str] = {}
    for invocation_index, asset in enumerate(iter_assets(scenario)):
        result = materialize_one_asset(
            asset,
            seed,
            out_dir,
            caps,
            invocation_index,
            root_path=root_path,
        )
        hashes[asset.id] = result.materialized_asset.content_hash
    return hashes


def _capabilities() -> Capabilities:
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


def _fake_run_ffmpeg(
    argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0
) -> tuple[ToolInvocation, str]:
    del timeout_s
    output = Path(argv[-1])
    output.write_bytes(_synthetic_media_payload(argv))
    invocation = ToolInvocation(
        tool="ffmpeg",
        version=ffmpeg_version,
        command=argv,
        exit_code=0,
        duration_ns=1_000_000,
    )
    return invocation, ""


def _synthetic_media_payload(argv: list[str]) -> bytes:
    recipe = "\0".join(argv[:-1]).encode()
    return hashlib.sha256(recipe).hexdigest().encode()


def _fake_probe_file(_path: Path) -> ProbedMedia:
    return ProbedMedia(
        container="matroska,webm",
        duration_seconds=1.0,
        size_bytes=64,
        streams=[
            ProbedStream(kind=StreamKind.VIDEO, codec="h264", width=640, height=480, fps=24.0)
        ],
    )
