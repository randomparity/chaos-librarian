"""Load every sample scenario through the Pydantic model.

This is the structural smoke-test for the contract. If any sample stops
loading, Sprint 0 has either regressed the schema or the sample is stale.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from chaos_librarian.contract.scenario import Scenario

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _scenario_files() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.yaml"))


def test_at_least_three_samples_ship() -> None:
    assert len(_scenario_files()) >= 3


@pytest.mark.parametrize("path", _scenario_files(), ids=lambda p: p.name)
def test_sample_scenario_loads(path: Path) -> None:
    yaml = YAML(typ="safe")
    data = yaml.load(path.read_text())
    Scenario.model_validate(data)
