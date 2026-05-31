"""Tests for deterministic fuzz scenario generation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from ruamel.yaml import YAML

from chaos_librarian.contract.profiles import (
    CANONICAL_FUZZ_LANES,
    FUZZ_LANES_BY_PROFILE,
    FuzzLaneName,
    FuzzProfileName,
    ProfileName,
)
from chaos_librarian.contract.scenario import EmbedSubtitleEvent, ExtractSubtitleEvent, Scenario
from chaos_librarian.engine import run_plan
from chaos_librarian.generation import (
    BatchItem,
    GeneratedScenarioCoverageError,
    GeneratedScenarioValidationError,
    generate_scenario,
    generate_scenario_yaml,
    plan_generation_batch,
    scenario_id_for,
    write_generated_scenario,
)
from chaos_librarian.generation import planner as generation_planner
from chaos_librarian.generation.lanes import coverage_for_payload
from chaos_librarian.generation.planner import lane_config_for
from chaos_librarian.materializer.preflight import preflight_asset, preflight_timeline
from chaos_librarian.topology import iter_asset_contexts
from chaos_librarian.validation import prepare_run_input_from_bytes, run_validation
from chaos_librarian.validation.rules.profile_opt_in import REQUIRED_PROFILES_BY_ACTION
from chaos_librarian.validation.scenario_io import parse_scenario_bytes

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
    for profile, lane in generation_planner.LANE_CONFIGS:
        configured_by_profile.setdefault(profile, set()).add(lane)

    assert {
        profile: frozenset(lanes) for profile, lanes in configured_by_profile.items()
    } == FUZZ_LANES_BY_PROFILE


def test_lane_profiles_cover_every_profile_gated_action_they_emit() -> None:
    """WHY: validation owns action->required-profile; generation must not drift.

    Every profile-gated action a lane emits (its action coverage cells) must
    have its required profile declared, derived from validation's single source
    of truth. If validation gates an action a lane already covers, this fails
    until the lane's derived profiles pick it up.
    """
    for (profile, lane), config in generation_planner.LANE_CONFIGS.items():
        declared = {p.value for p in config.profiles}
        for cell in config.required_cells:
            action = cell.removeprefix("action:")
            if cell == action:
                continue
            required = REQUIRED_PROFILES_BY_ACTION.get(action)
            if required is None:
                continue
            assert required in declared, (
                f"{profile.value}/{lane.value} emits gated action {action!r} "
                f"but does not declare required profile {required!r}"
            )


def test_lane_required_event_builder_satisfies_required_action_cells() -> None:
    """WHY: required cells and the events that satisfy them are one source.

    Each lane's ``required_events`` builder must emit every action named by the
    lane's required action cells. This pins the co-located builder to the cells
    so adding a cell without the matching event (or vice versa) fails here.
    """
    for (profile, lane), config in generation_planner.LANE_CONFIGS.items():
        planner = generation_planner.TimelinePlanner(
            root_id="r",
            root_path="r",
            secondary_root_id="cold-storage",
            assets=generation_planner._planned_assets(config=config),
        )
        config.required_events(planner)
        emitted = {event.action.value for event in planner.events}
        required_actions = {
            cell.removeprefix("action:")
            for cell in config.required_cells
            if cell.startswith("action:")
        }
        missing = required_actions - emitted
        assert missing == set(), (
            f"{profile.value}/{lane.value} required_events omits actions {missing}"
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
        (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.TV_TOPOLOGY, 463),
        (FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MUSIC_TOPOLOGY, 464),
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


def test_tv_topology_lane_emits_explicit_series_hierarchy() -> None:
    payload = _generated_payload(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.TV_TOPOLOGY,
        seed=463,
    )

    assert payload["movies"] == []
    series = cast(list[dict[str, object]], payload["series"])
    assert len(series) == 1
    assert series[0]["id"] == "series_001"
    assert series[0]["layout"] == "season_folders"
    assert series[0]["episode_naming"] == "sxxexx_title"
    seasons = cast(list[dict[str, object]], series[0]["seasons"])
    assert [season["id"] for season in seasons] == ["season_001", "season_002"]
    episodes = [
        episode
        for season in seasons
        for episode in cast(list[dict[str, object]], season["episodes"])
    ]
    assert [episode["id"] for episode in episodes] == ["episode_001", "episode_002"]

    actions = {event["action"] for event in cast(list[dict[str, object]], payload["timeline"])}
    assert {
        "renumber_episode",
        "move_episode_to_season",
        "rename_file",
        "reencode_video",
    } <= actions


def test_music_topology_lane_emits_explicit_artist_hierarchy_and_audio_only_track() -> None:
    payload = _generated_payload(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MUSIC_TOPOLOGY,
        seed=464,
    )

    assert payload["movies"] == []
    assert payload["series"] == []
    artists = cast(list[dict[str, object]], payload["artists"])
    assert len(artists) == 1
    assert artists[0]["id"] == "artist_001"
    assert artists[0]["layout"] == "artist_album_disc"
    assert artists[0]["track_naming"] == "disc_track_number_title"
    albums = cast(list[dict[str, object]], artists[0]["albums"])
    discs = cast(list[dict[str, object]], albums[0]["discs"])
    assert [disc["id"] for disc in discs] == ["disc_001", "disc_002"]
    tracks = [track for disc in discs for track in cast(list[dict[str, object]], disc["tracks"])]
    assert [track["id"] for track in tracks] == ["track_001", "track_002"]

    variants = cast(list[dict[str, object]], tracks[0]["variants"])
    bundle = cast(dict[str, object], variants[0]["bundle"])
    assets = cast(list[dict[str, object]], bundle["assets"])
    first_asset = assets[0]
    assert first_asset["role"] == "primary_audio"
    assert first_asset["container"] == "flac"
    assert "video" not in first_asset
    assert cast(list[dict[str, object]], first_asset["audio"])[0]["codec"] == "flac"

    actions = {event["action"] for event in cast(list[dict[str, object]], payload["timeline"])}
    assert {"renumber_disc", "move_track_to_disc", "rename_file", "reencode_audio"} <= actions


def test_music_topology_reencode_targets_materializable_audio_asset() -> None:
    payload = _generated_payload(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MUSIC_TOPOLOGY,
        seed=464,
    )
    artists = cast(list[dict[str, object]], payload["artists"])
    albums = cast(list[dict[str, object]], artists[0]["albums"])
    discs = cast(list[dict[str, object]], albums[0]["discs"])
    tracks = [track for disc in discs for track in cast(list[dict[str, object]], disc["tracks"])]
    first_variant = cast(list[dict[str, object]], tracks[0]["variants"])[0]
    first_bundle = cast(dict[str, object], first_variant["bundle"])
    first_asset = cast(list[dict[str, object]], first_bundle["assets"])[0]
    second_variant = cast(list[dict[str, object]], tracks[1]["variants"])[0]
    second_bundle = cast(dict[str, object], second_variant["bundle"])
    second_asset = cast(list[dict[str, object]], second_bundle["assets"])[0]
    reencode_event = next(
        event
        for event in cast(list[dict[str, object]], payload["timeline"])
        if event["action"] == "reencode_audio"
    )

    assert first_asset["id"] == "track_asset_001"
    assert first_asset["container"] == "flac"
    assert "video" not in first_asset
    assert cast(list[dict[str, object]], first_asset["audio"])[0]["codec"] == "flac"
    assert second_variant["label"] == "m4a"
    assert second_asset["id"] == "track_asset_002"
    assert second_asset["container"] == "m4a"
    assert cast(list[dict[str, object]], second_asset["audio"])[0]["codec"] == "aac"
    assert reencode_event["target"] == second_asset["id"]


def test_tv_topology_move_episode_crosses_season_folders() -> None:
    data = generate_scenario_yaml(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.TV_TOPOLOGY,
        seed=463,
    )
    run_input = prepare_run_input_from_bytes(raw_bytes=data, source_label="<generated>")
    validation_report = run_validation(run_input)
    assert validation_report.ok
    artifacts = run_plan(run_input=run_input, validation_report=validation_report)
    move_entry = next(
        entry for entry in artifacts.journal if entry.action == "move_episode_to_season"
    )

    path_moves = cast(list[dict[str, object]], move_entry.state_delta["path_moves"])
    assert any(
        "Season 01" in str(move["from_path"]) and "Season 02" in str(move["to_path"])
        for move in path_moves
    )


def test_seed_manifest_lists_supported_lanes_and_generates_valid_yaml() -> None:
    manifest_path = Path(__file__).resolve().parent / "fixtures" / "fuzz-seeds.yaml"
    yaml = YAML(typ="safe")
    manifest = yaml.load(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(manifest, dict)

    cases = _seed_manifest_cases(manifest)
    expected_cases = frozenset(generation_planner.LANE_CONFIGS)
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
    config = generation_planner.LANE_CONFIGS[key]
    monkeypatch.setitem(
        generation_planner.LANE_CONFIGS,
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
    config = generation_planner.LANE_CONFIGS[key]
    monkeypatch.setitem(
        generation_planner.LANE_CONFIGS,
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
    config = generation_planner.LANE_CONFIGS[key]
    monkeypatch.setitem(generation_planner.LANE_CONFIGS, key, replace(config, movies=4))

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


def test_scenario_id_for_matches_generated_scenario_id() -> None:
    generated = generate_scenario(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.CORE_FS,
        seed=456,
    )
    assert generated.scenario.scenario_id == scenario_id_for(
        FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.CORE_FS, 456
    )
    assert scenario_id_for(FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE, 7) == (
        "fuzz-smoke-smoke-seed-7"
    )


def test_plan_batch_fixed_lane_increments_seed() -> None:
    items = plan_generation_batch(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.CORE_FS,
        seed=99,
        count=3,
    )
    assert items == (
        BatchItem(lane=FuzzLaneName.CORE_FS, seed=99),
        BatchItem(lane=FuzzLaneName.CORE_FS, seed=100),
        BatchItem(lane=FuzzLaneName.CORE_FS, seed=101),
    )


def test_plan_batch_cycles_lanes_when_lane_is_none() -> None:
    order = CANONICAL_FUZZ_LANES[FuzzProfileName.FUZZ_REGRESSION]
    n = len(order)
    items = plan_generation_batch(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=None,
        seed=42,
        count=n + 2,
    )
    assert len(items) == n + 2
    assert [it.lane for it in items[:n]] == list(order)
    assert items[n].lane == order[0]
    assert items[n].seed == 42 + n
    assert [it.seed for it in items] == list(range(42, 42 + n + 2))


def test_plan_batch_smoke_uses_smoke_lane() -> None:
    items = plan_generation_batch(profile=FuzzProfileName.FUZZ_SMOKE, lane=None, seed=5, count=4)
    assert all(it.lane == FuzzLaneName.SMOKE for it in items)
    assert [it.seed for it in items] == [5, 6, 7, 8]


def test_plan_batch_count_one_returns_single_item() -> None:
    items = plan_generation_batch(
        profile=FuzzProfileName.FUZZ_SMOKE, lane=FuzzLaneName.SMOKE, seed=1, count=1
    )
    assert items == (BatchItem(lane=FuzzLaneName.SMOKE, seed=1),)


def test_plan_batch_rejects_non_positive_count() -> None:
    with pytest.raises(ValueError, match="count must be >= 1"):
        plan_generation_batch(
            profile=FuzzProfileName.FUZZ_SMOKE, lane=FuzzLaneName.SMOKE, seed=1, count=0
        )
