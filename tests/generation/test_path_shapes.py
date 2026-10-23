"""Path coverage must describe locators independently of identical media content."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.generation import generate_scenario
from chaos_librarian.generation.lanes import coverage_for_payload
from chaos_librarian.generation.planner import lane_config_for


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("movies/café.mkv", {"path:unicode-basename", "path:nfc"}),
        ("映画/plain.mkv", {"path:unicode-parent"}),
        ("movies/cafe\u0301.mkv", {"path:unicode-basename", "path:nfd"}),
        ("movies/-option.mkv", {"path:leading-dash"}),
        ("movies/a b;[$].mkv", {"path:whitespace", "path:metacharacters"}),
        ("movies/line\nbreak\t.mkv", {"path:control"}),
        ("movies/" + "x" * 246 + ".mkv", {"path:long-component"}),
        (("directory/" * 60) + "a.mkv", {"path:deep"}),
    ],
)
def test_path_cells_follow_destinations_not_content(path: str, expected: set[str]) -> None:
    payload: dict[str, object] = {
        "timeline": [{"action": "rename_file", "to": path, "target": "same_bytes"}]
    }
    assert expected <= coverage_for_payload(payload).cells
    payload["timeline"] = [{"action": "rename_file", "to": "movies/plain.mkv"}]
    assert not any(cell.startswith("path:") for cell in coverage_for_payload(payload).cells)


@pytest.mark.parametrize("seed", [0, 232, 2**32])
def test_core_fs_requires_portable_path_cells_and_remains_deterministic(seed: int) -> None:
    first = generate_scenario(FuzzProfileName.FUZZ_REGRESSION, seed, lane=FuzzLaneName.CORE_FS)
    second = generate_scenario(FuzzProfileName.FUZZ_REGRESSION, seed, lane=FuzzLaneName.CORE_FS)
    assert first.yaml_bytes == second.yaml_bytes
    required = {"path:unicode-basename", "path:unicode-parent", "path:leading-dash"}
    config = lane_config_for(profile=FuzzProfileName.FUZZ_REGRESSION, lane=FuzzLaneName.CORE_FS)
    assert required <= config.required_cells
    payload = first.scenario.model_dump(mode="json", by_alias=True)
    assert required <= coverage_for_payload(payload).cells
