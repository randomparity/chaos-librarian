"""Contract tests for the VOOM-focused CI scenario pack."""

from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from chaos_librarian.contract.scenario import Scenario

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios" / "voom-ci"

EXPECTED_FIXTURES = (
    "h264-transcode-candidate.yaml",
    "hevc-noop.yaml",
    "malformed-media-header.yaml",
    "single-step-media-mutation.yaml",
    "static-library-baseline.yaml",
)


def _load_yaml(path: Path) -> object:
    yaml = YAML(typ="safe")
    return yaml.load(path.read_text(encoding="utf-8"))


def test_voom_ci_pack_file_list_is_stable() -> None:
    found = tuple(path.name for path in sorted(FIXTURE_DIR.glob("*.yaml")))

    assert found == EXPECTED_FIXTURES


@pytest.mark.parametrize("fixture_name", EXPECTED_FIXTURES)
def test_voom_ci_pack_scenario_validates(fixture_name: str) -> None:
    scenario = Scenario.model_validate(_load_yaml(FIXTURE_DIR / fixture_name))

    assert scenario.scenario_id == f"voom-ci-{Path(fixture_name).stem}"
