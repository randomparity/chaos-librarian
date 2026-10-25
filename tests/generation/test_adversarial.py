"""The opt-in corpus must reach real recipe shapes without changing defaults."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
from ruamel.yaml import YAML

from chaos_librarian.contract.profiles import CANONICAL_FUZZ_LANES, FuzzLaneName, FuzzProfileName
from chaos_librarian.generation import generate_scenario, plan_generation_batch
from chaos_librarian.generation.lanes import coverage_for_payload
from chaos_librarian.generation.planner import lane_config_for
from chaos_librarian.topology import iter_asset_contexts


def _generated(seed: int = 248):
    return generate_scenario(
        FuzzProfileName.FUZZ_REGRESSION, seed, lane=FuzzLaneName.ADVERSARIAL_MEDIA
    )


def test_adversarial_lane_is_explicit_and_preserves_default_distribution() -> None:
    lane = FuzzLaneName.ADVERSARIAL_MEDIA
    order = CANONICAL_FUZZ_LANES[FuzzProfileName.FUZZ_REGRESSION]
    assert lane not in order
    assert len(order) == 10
    batch = plan_generation_batch(FuzzProfileName.FUZZ_REGRESSION, 248, 20)
    assert [item.lane for item in batch] == list(order) * 2
    assert plan_generation_batch(FuzzProfileName.FUZZ_REGRESSION, 248, 1, lane=lane)[0].lane is lane


def test_generated_corpus_is_bounded_deterministic_and_curated() -> None:
    generated = _generated()
    assert generated.yaml_bytes == _generated().yaml_bytes
    assets = [c.asset for c in iter_asset_contexts(generated.scenario)]
    assert len(assets) == 18
    assert len(generated.scenario.timeline) == 11
    assert max(a.duration_seconds for a in assets) == 2
    assert sum(a.container == "mp3" for a in assets) == 2
    assert max(len(a.audio) for a in assets) == 8
    assert max(len(a.subtitles) for a in assets) == 8
    fixture = Path(__file__).parents[1] / "fixtures/scenarios/fuzz-adversarial-seed-248.yaml"
    assert fixture.read_bytes() == generated.yaml_bytes


@pytest.mark.parametrize("seed", [0, 248, 4294967295])
def test_recipe_coverage_does_not_depend_on_lucky_seeds(seed: int) -> None:
    generated = _generated(seed)
    payload = YAML(typ="safe").load(generated.yaml_bytes)
    required = lane_config_for(
        FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.ADVERSARIAL_MEDIA
    ).required_cells
    assert len([c for c in required if c.startswith("adversarial:")]) == 15
    assert coverage_for_payload(payload).missing_required_cells(required) == frozenset()


@pytest.mark.parametrize(
    ("target", "cell"),
    [
        ("metadata_year", "metadata:year"),
        ("metadata_long", "metadata:long"),
        ("metadata_control", "metadata:control"),
        ("metadata_delete", "metadata:delete"),
        ("damage_mp4_start", "structural:mp4-moov_at_start"),
        ("damage_mp4_end", "structural:mp4-moov_at_end"),
        ("damage_mkv", "structural:mkv-cues"),
        ("damage_mp3", "structural:mp3-16-frames"),
    ],
)
def test_coverage_requires_recipe_parameters_not_action_names(target: str, cell: str) -> None:
    payload = YAML(typ="safe").load(_generated().yaml_bytes)
    changed = copy.deepcopy(payload)
    for event in changed["timeline"]:
        if event.get("target") == target:
            if event["action"] == "edit_metadata":
                event["fields"] = {"title": "ordinary"}
            elif event["action"] == "corrupt_container_header":
                event.pop("region")
                event["bytes"] = 64
            else:
                event.pop("boundary")
                event["keep_bytes"] = 4096
    assert "adversarial:" + cell in coverage_for_payload(payload).cells
    assert "adversarial:" + cell not in coverage_for_payload(changed).cells


@pytest.mark.parametrize("name", ["multiple", "none", "default_forced", "forced_only"])
def test_coverage_reads_dispositions_not_asset_identifiers(name: str) -> None:
    payload = YAML(typ="safe").load(_generated().yaml_bytes)
    for variant in payload["movies"][0]["variants"]:
        asset = variant["bundle"]["assets"][0]
        if asset["id"] == "flags_" + name:
            asset["audio"][0]["default"] = not asset["audio"][0]["default"]
    assert "adversarial:flags:" + name not in coverage_for_payload(payload).cells
