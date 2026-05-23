"""Duplicate/variant expansion-pack fixture and adapter recipe tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.adapter.compare import compare_fixture_to_observed
from chaos_librarian.adapter.fixture import OracleFixture, load_fixture
from chaos_librarian.adapter.index import OracleIndex
from chaos_librarian.contract.scenario import Asset, Scenario
from chaos_librarian.materializer.preflight import preflight_asset, preflight_timeline
from chaos_librarian.validation import prepare_run_input_from_bytes
from tests.support.adapter import (
    observed_from_fixture as _observed_from_fixture,
)
from tests.support.adapter import (
    write_plan_fixture as _write_plan_fixture,
)

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


def test_duplicate_variant_expansion_pack_oracle_evidence(
    oracle_fixture: OracleFixture,
) -> None:
    """WHY: the fixture must expose the ambiguous topology cases adapters document."""
    oracle_index = OracleIndex.from_fixture(oracle_fixture)

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


def test_duplicate_variant_path_and_topology_recipe_compares_clean(
    oracle_fixture: OracleFixture,
) -> None:
    """WHY: scanner exports that include current paths can disambiguate duplicates."""
    observed = _observed_from_fixture(oracle_fixture, include_topology=True)

    report = compare_fixture_to_observed(oracle_fixture, observed)

    assert report.ok is True
    assert report.findings == []


def test_duplicate_variant_pathless_topology_export_reports_ambiguity(
    oracle_fixture: OracleFixture,
) -> None:
    """WHY: topology alone cannot safely pick between same-label duplicate variants."""
    observed = _observed_from_fixture(
        oracle_fixture,
        include_current_paths=False,
        include_topology=True,
    )

    report = compare_fixture_to_observed(oracle_fixture, observed)

    assert {
        finding.evidence[0].value
        for finding in report.findings
        if finding.code == "D_MATCH_AMBIGUOUS"
    } == {
        "Synthetic Echo|hd|1",
        "Synthetic Pair|hd|2",
    }


def test_duplicate_variant_pathless_topology_export_reports_deleted_unique_matches(
    oracle_fixture: OracleFixture,
) -> None:
    """WHY: current_path=None still means the consumer observed the asset as absent."""
    observed = _observed_from_fixture(
        oracle_fixture,
        include_current_paths=False,
        include_topology=True,
    )

    report = compare_fixture_to_observed(oracle_fixture, observed)

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


@pytest.fixture(scope="module")
def oracle_fixture(tmp_path_factory: pytest.TempPathFactory) -> OracleFixture:
    return _plan_fixture(tmp_path_factory.mktemp("duplicate-variant-expanded"))


def _plan_fixture(tmp_path: Path) -> OracleFixture:
    run_dir = _write_plan_fixture(tmp_path, "duplicate-variant-expanded.yaml")
    return load_fixture(run_dir)


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
