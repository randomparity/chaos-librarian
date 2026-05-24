"""Tests for deterministic fuzz scenario generation."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.profiles import FuzzProfileName
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.generation import generate_scenario_yaml, write_generated_scenario
from chaos_librarian.scenario_io import parse_scenario_bytes


def _parse_generated(data: bytes) -> Scenario:
    raw, _ = parse_scenario_bytes(data, source=Path("<generated>"))
    return Scenario.model_validate(raw)


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

    assert scenario.scenario_id == "fuzz-smoke-seed-123"
    assert [profile.value for profile in scenario.profiles] == ["fuzz-smoke"]
    assert scenario.generation is not None
    assert scenario.generation.profile is FuzzProfileName.FUZZ_SMOKE
    assert scenario.generation.seed == 123


def test_atomic_write_rejects_existing_destination(tmp_path: Path) -> None:
    out = tmp_path / "scenario.yaml"
    out.write_text("existing", encoding="utf-8")

    with pytest.raises(FileExistsError):
        write_generated_scenario(out, b"replacement")

    assert out.read_text(encoding="utf-8") == "existing"
