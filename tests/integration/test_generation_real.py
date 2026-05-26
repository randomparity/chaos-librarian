"""Real-tool integration coverage for generated scenarios."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.materialization import Outcome
from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
from chaos_librarian.generation import generate_scenario_yaml
from chaos_librarian.materializer.run import materialize_scenario
from chaos_librarian.materializer.tooling.capabilities import (
    MIN_VERSIONS,
    detect_capabilities,
)


def _ffmpeg_meets_minimum() -> bool:
    caps = detect_capabilities()
    return caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum


pytestmark = pytest.mark.skipif(
    not _ffmpeg_meets_minimum(),
    reason=f"ffmpeg/ffprobe >= {MIN_VERSIONS['ffmpeg']} not available",
)


@pytest.mark.parametrize(
    ("lane", "seed"),
    [
        (FuzzLaneName.TV_TOPOLOGY, 463),
        (FuzzLaneName.MUSIC_TOPOLOGY, 464),
    ],
)
def test_topology_materialize_gated_lanes_materialize_successfully(
    tmp_path: Path,
    lane: FuzzLaneName,
    seed: int,
) -> None:
    data = generate_scenario_yaml(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=lane,
        seed=seed,
    )
    scenario_path = tmp_path / f"{lane.value}.yaml"
    scenario_path.write_bytes(data)

    artifacts = materialize_scenario(scenario_path, tmp_path / f"{lane.value}-run")

    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
