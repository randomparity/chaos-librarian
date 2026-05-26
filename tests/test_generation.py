"""Tests for deterministic fuzz scenario generation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from ruamel.yaml import YAML

from chaos_librarian import generation_lanes
from chaos_librarian.contract.profiles import (
    FUZZ_LANES_BY_PROFILE,
    FuzzLaneName,
    FuzzProfileName,
    ProfileName,
)
from chaos_librarian.contract.scenario import EmbedSubtitleEvent, ExtractSubtitleEvent, Scenario
from chaos_librarian.engine import run_plan
from chaos_librarian.generation import (
    GeneratedScenarioCoverageError,
    GeneratedScenarioValidationError,
    generate_scenario_yaml,
    write_generated_scenario,
)
from chaos_librarian.generation_lanes import (
    coverage_for_payload,
    lane_config_for,
)
from chaos_librarian.materializer.preflight import preflight_asset, preflight_timeline
from chaos_librarian.scenario_io import parse_scenario_bytes
from chaos_librarian.topology import iter_asset_contexts
from chaos_librarian.validation import prepare_run_input_from_bytes, run_validation

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


def test_lane_config_orders_fuzz_profile_first() -> None:
    config = lane_config_for(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MALFORMED,
    )

    assert config.profiles == (
        ProfileName.FUZZ_REGRESSION,
        ProfileName.MALFORMED_MEDIA,
    )


def test_lane_configs_cover_allowed_lane_contract() -> None:
    configured_by_profile: dict[FuzzProfileName, set[FuzzLaneName]] = {}
    for profile, lane in generation_lanes.LANE_CONFIGS:
        configured_by_profile.setdefault(profile, set()).add(lane)

    assert {
        profile: frozenset(lanes) for profile, lanes in configured_by_profile.items()
    } == FUZZ_LANES_BY_PROFILE


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


def test_seed_manifest_materialize_gates_pass_preflight() -> None:
    """WHY: materialize-gated generated lanes must not emit unsupported media shape."""
    manifest_path = Path(__file__).resolve().parent / "fixtures" / "fuzz-seeds.yaml"
    yaml = YAML(typ="safe")
    manifest = yaml.load(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(manifest, dict)

    cases = _seed_manifest_cases(manifest)
    for profile, lane, seed, gates in cases:
        if "materialize" not in gates:
            continue
        scenario = _parse_generated(generate_scenario_yaml(profile=profile, lane=lane, seed=seed))

        preflight_timeline(scenario)
        for context in iter_asset_contexts(scenario):
            preflight_asset(
                parent_kind=context.parent_kind,
                video=context.asset.video,
                audios=context.asset.audio,
                subtitles=context.asset.subtitles,
                container=context.asset.container,
            )


def test_sidecar_subtitle_lane_embeds_before_extracting() -> None:
    """WHY: materialize extract needs a subtitle stream created by a prior embed."""
    scenario = _parse_generated(
        generate_scenario_yaml(
            profile=FuzzProfileName.FUZZ_REGRESSION,
            lane=FuzzLaneName.SIDECAR_SUBTITLE,
            seed=458,
        )
    )

    actions = [event.action.value for event in scenario.timeline]
    embed_index = actions.index("embed_subtitle")
    extract_index = actions.index("extract_subtitle")
    embed_event = scenario.timeline[embed_index]
    extract_event = scenario.timeline[extract_index]

    assert isinstance(embed_event, EmbedSubtitleEvent)
    assert isinstance(extract_event, ExtractSubtitleEvent)
    assert embed_index < extract_index
    assert embed_event.target == extract_event.target


def test_sidecar_subtitle_lane_updates_final_manifest_sidecars() -> None:
    """WHY: materialize update_sidecar resolves sidecar metadata from final manifest rows."""
    data = generate_scenario_yaml(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.SIDECAR_SUBTITLE,
        seed=458,
    )
    run_input = prepare_run_input_from_bytes(raw_bytes=data, source_label="<generated>")
    validation_report = run_validation(run_input)
    assert validation_report.ok
    artifacts = run_plan(run_input=run_input, validation_report=validation_report)
    final_sidecar_ids = {sidecar.id for sidecar in artifacts.current_manifest.sidecars}
    update_sidecar_ids = {
        str(entry.state_delta["sidecar_id"])
        for entry in artifacts.journal
        if entry.action == "update_sidecar"
    }

    assert update_sidecar_ids
    assert update_sidecar_ids <= final_sidecar_ids


def test_malformed_lane_avoids_media_rewrite_after_corruption() -> None:
    """WHY: materialize cannot ffmpeg-rewrite intentionally malformed files again."""
    payload = _generated_payload(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MALFORMED,
        seed=459,
    )
    _assert_no_media_rewrite_after_corruption(payload["timeline"])


def test_malformed_lane_skips_media_fill_when_all_assets_corrupted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY: no stable target must mean no fill-in media rewrite events."""
    key = (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MALFORMED)
    config = generation_lanes.LANE_CONFIGS[key]
    monkeypatch.setitem(
        generation_lanes.LANE_CONFIGS,
        key,
        replace(config, movies=4, timeline_events=8),
    )

    payload = _generated_payload(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MALFORMED,
        seed=1,
    )

    _assert_no_media_rewrite_after_corruption(payload["timeline"])


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


def _assert_no_media_rewrite_after_corruption(timeline: object) -> None:
    assert isinstance(timeline, list)
    corrupted_assets: set[str] = set()
    corruption_actions = {
        "corrupt_container_header",
        "truncate_file",
        "corrupt_packet_range",
        "write_invalid_duration_metadata",
    }
    media_rewrite_actions = {
        "reencode_video",
        "reencode_audio",
        "remux_container",
        "edit_metadata",
        "embed_subtitle",
        "extract_subtitle",
    }
    for event in timeline:
        assert isinstance(event, dict)
        event = cast(dict[str, object], event)
        action = event.get("action")
        target = event.get("target")
        if not isinstance(action, str) or not isinstance(target, str):
            continue
        assert not (action in media_rewrite_actions and target in corrupted_assets)
        if action in corruption_actions:
            corrupted_assets.add(target)


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
    monkeypatch.setitem(generation_lanes.LANE_CONFIGS, key, replace(config, movies=4))

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
