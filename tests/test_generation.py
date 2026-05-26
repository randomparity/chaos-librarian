"""Tests for deterministic fuzz scenario generation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from ruamel.yaml import YAML

from chaos_librarian import generation_lanes
from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName, ProfileName
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.generation import (
    GeneratedScenarioCoverageError,
    GeneratedScenarioValidationError,
    generate_scenario_yaml,
    write_generated_scenario,
)
from chaos_librarian.generation_lanes import (
    coverage_for_payload,
    lane_config_for,
    profiles_for_lane,
)
from chaos_librarian.scenario_io import parse_scenario_bytes

VALID_SEED_MANIFEST_GATES = frozenset({"validate", "plan", "replay", "materialize", "run"})


def _parse_generated(data: bytes) -> Scenario:
    raw, _ = parse_scenario_bytes(data, source=Path("<generated>"))
    return Scenario.model_validate(raw)


def _generated_payload(
    profile: FuzzProfileName,
    lane: FuzzLaneName,
    seed: int,
) -> dict[str, object]:
    yaml = YAML(typ="safe")
    data = generate_scenario_yaml(profile=profile, lane=lane, seed=seed)
    payload = yaml.load(data.decode())
    assert isinstance(payload, dict)
    return payload


def test_generate_same_profile_and_seed_is_byte_identical() -> None:
    first = generate_scenario_yaml(profile=FuzzProfileName.FUZZ_SMOKE, seed=123)
    second = generate_scenario_yaml(profile=FuzzProfileName.FUZZ_SMOKE, seed=123)

    assert first == second


def test_generate_different_seed_changes_yaml() -> None:
    first = generate_scenario_yaml(profile=FuzzProfileName.FUZZ_SMOKE, seed=123)
    second = generate_scenario_yaml(profile=FuzzProfileName.FUZZ_SMOKE, seed=124)

    assert first != second


def test_generated_yaml_validates_as_scenario() -> None:
    scenario = _parse_generated(
        generate_scenario_yaml(profile=FuzzProfileName.FUZZ_SMOKE, seed=123)
    )

    assert scenario.scenario_id == "fuzz-smoke-smoke-seed-123"
    assert [profile.value for profile in scenario.profiles] == ["fuzz-smoke"]
    assert scenario.generation is not None
    assert scenario.generation.profile is FuzzProfileName.FUZZ_SMOKE
    assert scenario.generation.lane.value == "smoke"
    assert scenario.generation.seed == 123


def test_profiles_for_lane_orders_fuzz_profile_first() -> None:
    profiles = profiles_for_lane(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MALFORMED,
    )

    assert profiles == (
        ProfileName.FUZZ_REGRESSION,
        ProfileName.MALFORMED_MEDIA,
    )


def test_lane_config_rejects_profile_mismatch() -> None:
    with pytest.raises(ValueError, match="not valid"):
        lane_config_for(
            profile=FuzzProfileName.FUZZ_SMOKE,
            lane=FuzzLaneName.MEDIA_REWRITE,
        )


@pytest.mark.parametrize(
    ("profile", "lane", "seed"),
    [
        (FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE, 9),
        (FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE, 123),
        (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.CORE_FS, 456),
        (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MEDIA_REWRITE, 457),
        (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.SIDECAR_SUBTITLE, 458),
        (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MALFORMED, 459),
        (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.NEGATIVE_ORACLE, 460),
        (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.FILESYSTEM_ARTIFACT, 461),
        (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.NETWORK_LAG, 462),
    ],
)
def test_generated_lane_meets_required_coverage(
    profile: FuzzProfileName,
    lane: FuzzLaneName,
    seed: int,
) -> None:
    payload = _generated_payload(profile=profile, lane=lane, seed=seed)
    config = lane_config_for(profile=profile, lane=lane)

    missing = coverage_for_payload(payload).missing_required_cells(config.required_cells)
    assert missing == frozenset()


@pytest.mark.parametrize(
    ("lane", "required_profiles"),
    [
        (FuzzLaneName.MALFORMED, ("fuzz-regression", "malformed-media")),
        (FuzzLaneName.NEGATIVE_ORACLE, ("fuzz-regression", "negative-oracle")),
        (FuzzLaneName.FILESYSTEM_ARTIFACT, ("fuzz-regression", "filesystem-artifacts")),
        (FuzzLaneName.NETWORK_LAG, ("fuzz-regression", "network-fs-lag")),
    ],
)
def test_generated_gated_lanes_include_required_profiles(
    lane: FuzzLaneName,
    required_profiles: tuple[str, ...],
) -> None:
    payload = _generated_payload(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=lane,
        seed=459,
    )

    profiles = payload["profiles"]
    assert isinstance(profiles, list)
    assert tuple(profiles) == required_profiles


def test_seed_manifest_lists_supported_lanes_and_generates_valid_yaml() -> None:
    manifest_path = Path(__file__).resolve().parent / "fixtures" / "fuzz-seeds.yaml"
    yaml = YAML(typ="safe")
    manifest = yaml.load(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(manifest, dict)

    cases = _seed_manifest_cases(manifest)
    expected_cases = frozenset(generation_lanes.LANE_CONFIGS)
    assert frozenset((profile, lane) for profile, lane, _, _ in cases) == expected_cases

    for profile, lane, seed, gates in cases:
        assert frozenset(gates) <= VALID_SEED_MANIFEST_GATES
        payload = _generated_payload(profile=profile, lane=lane, seed=seed)
        config = lane_config_for(profile=profile, lane=lane)
        missing = coverage_for_payload(payload).missing_required_cells(config.required_cells)
        assert missing == frozenset()


def _seed_manifest_cases(
    manifest: dict[object, object],
) -> tuple[tuple[FuzzProfileName, FuzzLaneName, int, tuple[str, ...]], ...]:
    cases: list[tuple[FuzzProfileName, FuzzLaneName, int, tuple[str, ...]]] = []
    profile_keys = {
        "fuzz_smoke": FuzzProfileName.FUZZ_SMOKE,
        "fuzz_regression": FuzzProfileName.FUZZ_REGRESSION,
    }
    for key, profile in profile_keys.items():
        entries = manifest.get(key)
        assert isinstance(entries, list)
        for entry in entries:
            assert isinstance(entry, dict)
            entry = cast(dict[str, object], entry)
            lane = FuzzLaneName(entry["lane"])
            seed = entry["seed"]
            gates = entry["gates"]
            assert isinstance(seed, int)
            assert isinstance(gates, list)
            cases.append((profile, lane, seed, tuple(str(gate) for gate in gates)))
    return tuple(cases)


def test_committed_generated_fixtures_match_generator() -> None:
    fixture_dir = Path(__file__).resolve().parent / "fixtures" / "scenarios"
    cases = [
        (
            fixture_dir / "fuzz-smoke-seed-123.yaml",
            FuzzProfileName.FUZZ_SMOKE,
            FuzzLaneName.SMOKE,
            123,
        ),
        (
            fixture_dir / "fuzz-regression-seed-456.yaml",
            FuzzProfileName.FUZZ_REGRESSION,
            FuzzLaneName.CORE_FS,
            456,
        ),
    ]
    for path, profile, lane, seed in cases:
        expected = generate_scenario_yaml(profile=profile, lane=lane, seed=seed)
        assert path.read_bytes() == expected


def test_generate_rejects_missing_required_coverage(monkeypatch: pytest.MonkeyPatch) -> None:
    key = (FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE)
    config = generation_lanes.LANE_CONFIGS[key]
    monkeypatch.setitem(
        generation_lanes.LANE_CONFIGS,
        key,
        replace(config, required_cells=frozenset({"missing:required-cell"})),
    )

    with pytest.raises(GeneratedScenarioCoverageError, match="missing required coverage"):
        generate_scenario_yaml(
            profile=FuzzProfileName.FUZZ_SMOKE,
            lane=FuzzLaneName.SMOKE,
            seed=123,
        )


def test_generate_rejects_budget_overflow(monkeypatch: pytest.MonkeyPatch) -> None:
    key = (FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE)
    config = generation_lanes.LANE_CONFIGS[key]
    monkeypatch.setitem(generation_lanes.LANE_CONFIGS, key, replace(config, works=4))

    with pytest.raises(
        GeneratedScenarioValidationError,
        match="generated scenario failed validation",
    ):
        generate_scenario_yaml(
            profile=FuzzProfileName.FUZZ_SMOKE,
            lane=FuzzLaneName.SMOKE,
            seed=123,
        )


def test_atomic_write_rejects_existing_destination(tmp_path: Path) -> None:
    out = tmp_path / "scenario.yaml"
    out.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_generated_scenario(out, b"replacement")

    assert out.read_text(encoding="utf-8") == "existing"
