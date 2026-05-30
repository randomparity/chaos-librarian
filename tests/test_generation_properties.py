"""Property tests for deterministic fuzz scenario generation."""

from __future__ import annotations

from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from chaos_librarian import generation_planner
from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.generation import generate_scenario_yaml
from chaos_librarian.generation_lanes import coverage_for_payload
from chaos_librarian.generation_planner import lane_config_for
from chaos_librarian.scenario_io import parse_scenario_bytes

LANE_CASES: tuple[tuple[FuzzProfileName, FuzzLaneName], ...] = tuple(
    sorted(
        generation_planner.LANE_CONFIGS,
        key=lambda item: (item[0].value, item[1].value),
    )
)


def _parse(data: bytes) -> Scenario:
    raw, _ = parse_scenario_bytes(data, source=Path("<generated-property>"))
    return Scenario.model_validate(raw)


@settings(
    max_examples=64,
    deadline=None,
    suppress_health_check=(HealthCheck.function_scoped_fixture,),
)
@given(
    case=st.sampled_from(LANE_CASES),
    seed=st.integers(min_value=0, max_value=10_000),
)
def test_generated_scenarios_are_deterministic_and_valid(
    case: tuple[FuzzProfileName, FuzzLaneName],
    seed: int,
) -> None:
    profile, lane = case

    first = generate_scenario_yaml(profile=profile, lane=lane, seed=seed)
    second = generate_scenario_yaml(profile=profile, lane=lane, seed=seed)

    assert first == second
    scenario = _parse(first)
    assert scenario.generation is not None
    assert scenario.generation.profile is profile
    assert scenario.generation.lane is lane


@settings(max_examples=64, deadline=None)
@given(
    case=st.sampled_from(LANE_CASES),
    seed=st.integers(min_value=0, max_value=10_000),
)
def test_generated_scenarios_meet_lane_coverage(
    case: tuple[FuzzProfileName, FuzzLaneName],
    seed: int,
) -> None:
    profile, lane = case
    data = generate_scenario_yaml(profile=profile, lane=lane, seed=seed)
    raw, _ = parse_scenario_bytes(data, source=Path("<generated-property>"))
    config = lane_config_for(profile=profile, lane=lane)

    assert coverage_for_payload(raw).missing_required_cells(config.required_cells) == frozenset()
