"""Real-tool coverage for the VOOM CI scenario pack."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, assert_never

import pytest

from chaos_librarian.contract.materialization import Outcome
from chaos_librarian.contract.profiles import CorruptionProbeOutcome
from chaos_librarian.materializer.run import materialize_scenario
from chaos_librarian.materializer.runtime.wall_clock import run_wall_clock_scenario
from chaos_librarian.materializer.tooling.capabilities import detect_capabilities
from tests.integration.conftest import _load_materialization_report

PACK_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios" / "voom-ci"
CAPABILITIES = detect_capabilities()
CapabilityName = Literal[
    "materialize_static",
    "materialize_hevc_video",
    "materialize_media_mutations",
]

MATERIALIZE_CASES: tuple[tuple[str, CapabilityName], ...] = (
    ("static-library-baseline.yaml", "materialize_static"),
    ("h264-transcode-candidate.yaml", "materialize_static"),
    ("hevc-noop.yaml", "materialize_hevc_video"),
    ("single-step-media-mutation.yaml", "materialize_media_mutations"),
    ("malformed-media-header.yaml", "materialize_media_mutations"),
)


def _is_ready(field_name: CapabilityName) -> bool:
    match field_name:
        case "materialize_static":
            return CAPABILITIES.ready_for.materialize_static
        case "materialize_hevc_video":
            return CAPABILITIES.ready_for.materialize_hevc_video
        case "materialize_media_mutations":
            return CAPABILITIES.ready_for.materialize_media_mutations
        case _:
            assert_never(field_name)


def _skip_unless_ready(field_name: CapabilityName) -> None:
    if _is_ready(field_name):
        return
    pytest.skip(f"requires capabilities.ready_for.{field_name}")


@pytest.mark.parametrize(("fixture_name", "capability"), MATERIALIZE_CASES)
def test_voom_ci_fixture_materializes(
    fixture_name: str,
    capability: CapabilityName,
    tmp_path: Path,
) -> None:
    _skip_unless_ready(capability)

    out_dir = tmp_path / Path(fixture_name).stem
    artifacts = materialize_scenario(PACK_DIR / fixture_name, out_dir)
    report = _load_materialization_report(out_dir)

    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    assert report.outcome is Outcome.SUCCESS
    if fixture_name == "malformed-media-header.yaml":
        assert len(report.corruption_actions) == 1
        action = report.corruption_actions[0]
        assert action.event_id == "corrupt_header_001"
        assert action.target_asset_id == "asset_malformed_main"
        assert action.corruptor == "container_header_v1"
        assert action.byte_count == 64
        assert action.seed_material == (
            "container_header_v1:9705:corrupt_header_001:asset_malformed_main"
        )
        assert action.probe_outcome is CorruptionProbeOutcome.FAILED_EXPECTED


def test_voom_ci_single_step_mutation_runs_for_live_rescan(tmp_path: Path) -> None:
    _skip_unless_ready("materialize_media_mutations")

    out_dir = tmp_path / "run-single-step-media-mutation"
    artifacts = run_wall_clock_scenario(
        PACK_DIR / "single-step-media-mutation.yaml",
        out_dir,
        duration="2s",
        speed="20x",
    )

    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    assert artifacts.replay_bundle.applied_events == 1
    assert _load_materialization_report(out_dir).outcome is Outcome.SUCCESS
