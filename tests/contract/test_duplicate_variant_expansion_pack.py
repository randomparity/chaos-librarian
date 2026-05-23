"""Duplicate/variant expansion-pack fixture and adapter recipe tests."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chaos_librarian.adapter.compare import compare_fixture_to_observed
from chaos_librarian.adapter.fixture import OracleFixture, load_fixture
from chaos_librarian.adapter.index import OracleIndex
from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.content_sources import ContentSourceCapabilities
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream, StreamKind
from chaos_librarian.contract.materialization import Outcome, ToolInvocation
from chaos_librarian.contract.observed_state import (
    ObservedAsset,
    ObservedBundle,
    ObservedConsumer,
    ObservedState,
    ObservedVariant,
    ObservedWork,
)
from chaos_librarian.contract.scenario import Asset, Scenario
from chaos_librarian.engine import run_plan
from chaos_librarian.engine.writer import write_fixture
from chaos_librarian.materializer import run as run_mod
from chaos_librarian.materializer import synthesis as synthesis_mod
from chaos_librarian.materializer.preflight import preflight_asset, preflight_timeline
from chaos_librarian.materializer.run import MaterializeArtifacts, materialize_scenario
from chaos_librarian.validation import prepare_run_input_from_bytes, run_validation

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
EXPANSION_FIXTURE = FIXTURE_DIR / "duplicate-variant-expanded.yaml"


def test_duplicate_variant_expansion_pack_defines_expected_cases() -> None:
    """WHY: issue #73 needs a broader pack without changing the first-pack fixture."""
    scenario = _scenario()

    assert scenario.scenario_id == "duplicate-variant-expanded"
    assert [work.id for work in scenario.works] == [
        "work_echo",
        "work_pair",
        "work_ladder",
    ]
    assert _variant_labels(scenario, "work_echo") == ("hd", "hd", "sd")
    assert _variant_labels(scenario, "work_pair") == ("hd",)
    assert _variant_labels(scenario, "work_ladder") == ("1080p", "sd")
    assert _asset_recipe(scenario, "asset_echo_hd_a") == _asset_recipe(
        scenario,
        "asset_echo_hd_b",
    )
    assert _asset_recipe(scenario, "asset_pair_disc_a") == _asset_recipe(
        scenario,
        "asset_pair_disc_b",
    )

    preflight_timeline(scenario)
    for asset in _assets(scenario):
        preflight_asset(asset.video, asset.audio, asset.subtitles, asset.container)


def test_duplicate_variant_expansion_pack_oracle_evidence(tmp_path: Path) -> None:
    """WHY: the fixture must expose the ambiguous topology cases adapters document."""
    fixture = _plan_fixture(tmp_path)
    oracle_index = OracleIndex.from_fixture(fixture)

    assert all(len(asset_ids) == 1 for asset_ids in oracle_index.current_path_to_asset_ids.values())
    assert oracle_index.topology_key_to_asset_ids["Synthetic Echo|hd|1"] == (
        "asset_echo_hd_a",
        "asset_echo_hd_b",
    )
    assert oracle_index.topology_key_to_asset_ids["Synthetic Pair|hd|2"] == (
        "asset_pair_disc_a",
        "asset_pair_disc_b",
    )
    assert oracle_index.topology_key_to_asset_ids["Synthetic Ladder|1080p|1"] == (
        "asset_ladder_1080p",
    )
    assert oracle_index.topology_key_to_asset_ids["Synthetic Ladder|sd|1"] == ("asset_ladder_sd",)


def test_duplicate_variant_expansion_pack_materialized_hash_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: prober exports need real manifest hashes, not just identical YAML recipes."""
    _patch_materializer(monkeypatch)

    artifacts = materialize_scenario(EXPANSION_FIXTURE, tmp_path / "run")
    hashes = _content_hashes_by_asset(artifacts)

    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    assert hashes["asset_echo_hd_a"] == hashes["asset_echo_hd_b"]
    assert hashes["asset_pair_disc_a"] == hashes["asset_pair_disc_b"]
    assert hashes["asset_echo_sd"] != hashes["asset_echo_hd_a"]
    assert hashes["asset_ladder_1080p"] != hashes["asset_ladder_sd"]


def test_duplicate_variant_path_and_topology_recipe_compares_clean(tmp_path: Path) -> None:
    """WHY: scanner exports that include current paths can disambiguate duplicates."""
    fixture = _plan_fixture(tmp_path)
    observed = _observed_from_fixture(fixture, include_paths=True)

    report = compare_fixture_to_observed(fixture, observed)

    assert report.ok is True
    assert report.findings == []


def test_duplicate_variant_topology_only_recipe_reports_ambiguity(tmp_path: Path) -> None:
    """WHY: topology alone cannot safely pick between same-label duplicate variants."""
    fixture = _plan_fixture(tmp_path)
    observed = _observed_from_fixture(fixture, include_paths=False)

    report = compare_fixture_to_observed(fixture, observed)

    assert report.ok is False
    assert {finding.code.value for finding in report.findings} == {
        "D_DELETION_MISMATCH",
        "D_MATCH_AMBIGUOUS",
    }
    assert {
        finding.evidence[0].value
        for finding in report.findings
        if finding.code == "D_MATCH_AMBIGUOUS"
    } == {
        "Synthetic Echo|hd|1",
        "Synthetic Pair|hd|2",
    }
    assert {
        finding.oracle_asset_id
        for finding in report.findings
        if finding.code == "D_DELETION_MISMATCH"
    } == {
        "asset_echo_sd",
        "asset_ladder_1080p",
        "asset_ladder_sd",
    }


def _scenario() -> Scenario:
    run_input = prepare_run_input_from_bytes(
        raw_bytes=EXPANSION_FIXTURE.read_bytes(),
        source_label=f"test:{EXPANSION_FIXTURE.name}",
    )
    return run_input.scenario


def _plan_fixture(tmp_path: Path) -> OracleFixture:
    scenario_bytes = EXPANSION_FIXTURE.read_bytes()
    run_input = prepare_run_input_from_bytes(
        raw_bytes=scenario_bytes,
        source_label=f"test:{EXPANSION_FIXTURE.name}",
    )
    report = run_validation(run_input)
    assert report.ok, [issue.code for issue in report.issues]
    artifacts = run_plan(run_input=run_input, validation_report=report)
    run_dir = tmp_path / "run"
    write_fixture(run_dir, artifacts, scenario_bytes)
    return load_fixture(run_dir)


def _patch_materializer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run_mod, "detect_capabilities", _capabilities)
    monkeypatch.setattr(synthesis_mod, "run_ffmpeg", _fake_run_ffmpeg)
    monkeypatch.setattr(synthesis_mod, "probe_file", _fake_probe_file)


def _capabilities() -> Capabilities:
    return Capabilities(
        schema_version=2,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=False,
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
    """Return stable bytes for the ffmpeg recipe, ignoring the output path."""
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


def _content_hashes_by_asset(artifacts: MaterializeArtifacts) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for version in artifacts.current_manifest.versions:
        assert version.content_hash is not None
        hashes[version.asset_id] = version.content_hash
    return hashes


def _variant_labels(scenario: Scenario, work_id: str) -> tuple[str, ...]:
    work = next(work for work in scenario.works if work.id == work_id)
    return tuple(variant.label for variant in work.variants)


def _assets(scenario: Scenario) -> tuple[Asset, ...]:
    return tuple(
        asset
        for work in scenario.works
        for variant in work.variants
        for asset in variant.bundle.assets
    )


def _asset_recipe(scenario: Scenario, asset_id: str) -> tuple[object, ...]:
    asset = next(asset for asset in _assets(scenario) if asset.id == asset_id)
    assert asset.video is not None
    return (
        asset.container,
        asset.duration_seconds,
        asset.video.source,
        asset.video.codec,
        asset.video.resolution,
        tuple((audio.source, audio.codec, audio.channels, audio.language) for audio in asset.audio),
        tuple(asset.subtitles),
    )


def _observed_from_fixture(fixture: OracleFixture, *, include_paths: bool) -> ObservedState:
    work_refs = {work.id: f"observed-{work.id}" for work in fixture.current_manifest.works}
    variant_refs = {
        variant.id: f"observed-{variant.id}" for variant in fixture.current_manifest.variants
    }
    bundle_refs = {
        bundle.id: f"observed-{bundle.id}" for bundle in fixture.current_manifest.bundles
    }
    bundle_by_id = {bundle.id: bundle for bundle in fixture.current_manifest.bundles}
    variant_by_id = {variant.id: variant for variant in fixture.current_manifest.variants}
    locations = {location.asset_id: location for location in fixture.current_manifest.locations}

    return ObservedState(
        schema_version=1,
        consumer=ObservedConsumer(name="issue-73-recipe", version="1.0"),
        run_id=fixture.run_id,
        observed_at=datetime(2026, 5, 23, tzinfo=UTC),
        assets=[
            ObservedAsset(
                observed_ref=f"observed-{asset.id}",
                current_path=locations[asset.id].path if include_paths else None,
                work_ref=work_refs[variant_by_id[bundle_by_id[asset.bundle_id].variant_id].work_id],
                variant_ref=variant_refs[bundle_by_id[asset.bundle_id].variant_id],
                bundle_ref=bundle_refs[asset.bundle_id],
            )
            for asset in fixture.current_manifest.assets
        ],
        works=[
            ObservedWork(observed_ref=work_refs[work.id], title=work.title)
            for work in fixture.current_manifest.works
        ],
        variants=[
            ObservedVariant(
                observed_ref=variant_refs[variant.id],
                work_ref=work_refs[variant.work_id],
                label=variant.label,
            )
            for variant in fixture.current_manifest.variants
        ],
        bundles=[
            ObservedBundle(
                observed_ref=bundle_refs[bundle.id],
                variant_ref=variant_refs[bundle.variant_id],
                asset_refs=[
                    f"observed-{asset.id}"
                    for asset in fixture.current_manifest.assets
                    if asset.bundle_id == bundle.id
                ],
            )
            for bundle in fixture.current_manifest.bundles
        ],
    )
