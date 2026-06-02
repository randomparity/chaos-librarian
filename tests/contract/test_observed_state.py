"""Tests for the Sprint 9 observed-state consumer contract."""

from __future__ import annotations

from copy import deepcopy
from typing import cast

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import OBSERVED_STATE_SCHEMA_VERSION
from chaos_librarian.contract.observed_state import ObservedState


def _minimal_observed_payload() -> dict[str, object]:
    return {
        "schema_version": OBSERVED_STATE_SCHEMA_VERSION,
        "consumer": {"name": "voom-v2", "version": "0.9.0"},
        "run_id": "7c44eb62-7046-4b8f-a168-eaf3a58e0145",
        "observed_at": "2026-05-22T12:00:00Z",
        "assets": [
            {
                "observed_ref": "obs-asset-1",
                "current_path": "movies/Synthetic.mkv",
            }
        ],
    }


def test_scanner_observed_state_round_trips_minimal_assets() -> None:
    payload = _minimal_observed_payload()

    observed = ObservedState.model_validate(payload)

    assert observed.model_dump(mode="json", exclude_none=True)["assets"] == [
        {
            "observed_ref": "obs-asset-1",
            "current_path": "movies/Synthetic.mkv",
            "sidecars": [],
            "path_history": [],
        }
    ]


def test_prober_observed_state_round_trips_hash_and_probe() -> None:
    payload = _minimal_observed_payload()
    asset = cast("list[dict[str, object]]", payload["assets"])[0]
    asset["content_hash"] = "sha256:" + "a" * 64
    asset["probed"] = {
        "container": "matroska,webm",
        "duration_seconds": 60.0,
        "size_bytes": 123456,
        "streams": [{"kind": "video", "codec": "h264", "width": 1920, "height": 1080}],
    }

    observed = ObservedState.model_validate(payload)

    assert observed.assets[0].content_hash == "sha256:" + "a" * 64
    assert observed.assets[0].probed is not None
    assert observed.assets[0].probed.streams[0].codec == "h264"


def test_watcher_observed_state_round_trips_path_history_and_events() -> None:
    payload = _minimal_observed_payload()
    asset = cast("list[dict[str, object]]", payload["assets"])[0]
    asset["path_history"] = [
        {
            "observed_event_ref": "obs-event-1",
            "related_observed_event_ref": "obs-event-2",
            "action": "slow_copy_start",
            "observed_at": "2026-05-22T12:00:01Z",
            "from_path": "movies/Synthetic.mkv",
            "to_path": "archive/Synthetic.mkv",
            "temp_path": "archive/.Synthetic.mkv.tmp",
        },
        {
            "observed_event_ref": "obs-event-2",
            "related_observed_event_ref": "obs-event-1",
            "action": "slow_copy_commit",
            "observed_at": "2026-05-22T12:00:02Z",
            "to_path": "archive/Synthetic.mkv",
        },
    ]
    payload["events"] = [
        {
            "observed_event_ref": "global-1",
            "related_observed_event_ref": "global-2",
            "observed_ref": "obs-asset-1",
            "action": "delete_file",
            "observed_at": "2026-05-22T12:00:03Z",
            "from_path": "movies/Synthetic.mkv",
        },
        {
            "observed_event_ref": "global-2",
            "related_observed_event_ref": "global-1",
            "observed_ref": "obs-asset-1",
            "action": "add_file",
            "observed_at": "2026-05-22T12:00:04Z",
            "to_path": "archive/Synthetic.mkv",
        },
    ]

    observed = ObservedState.model_validate(payload)

    assert observed.assets[0].path_history[0].action == "slow_copy_start"
    assert observed.events[1].related_observed_event_ref == "global-1"


@pytest.mark.parametrize(
    "action",
    [
        "renumber_episode",
        "move_episode_to_season",
        "rename_season",
        "renumber_disc",
        "move_track_to_disc",
    ],
)
def test_observed_state_accepts_hierarchy_path_history_actions(action: str) -> None:
    payload = _minimal_observed_payload()
    asset = cast("list[dict[str, object]]", payload["assets"])[0]
    asset["path_history"] = [
        {
            "action": action,
            "from_path": "tv/Show/Season 01/Show - S01E01.mkv",
            "to_path": "tv/Show/Season 01/Show - S01E02.mkv",
        }
    ]

    observed = ObservedState.model_validate(payload)

    assert observed.assets[0].path_history[0].action == action


def test_observed_state_rejects_extra_fields() -> None:
    payload = _minimal_observed_payload()
    payload["unexpected"] = True

    with pytest.raises(ValidationError):
        ObservedState.model_validate(payload)


def test_observed_state_rejects_invalid_hash() -> None:
    payload = _minimal_observed_payload()
    asset = cast("list[dict[str, object]]", payload["assets"])[0]
    asset["content_hash"] = "not-a-sha256"

    with pytest.raises(ValidationError):
        ObservedState.model_validate(payload)


def valid_observed_payload() -> dict[str, object]:
    """Return a mutable valid payload for later validation tests."""
    return deepcopy(_minimal_observed_payload())


def _first_asset(payload: dict[str, object]) -> dict[str, object]:
    return cast("list[dict[str, object]]", payload["assets"])[0]


def _history_entry(action: str, **fields: object) -> dict[str, object]:
    entry: dict[str, object] = {"action": action}
    entry.update(fields)
    return entry


def _global_event(ref: str, action: str, **fields: object) -> dict[str, object]:
    event: dict[str, object] = {"observed_event_ref": ref, "action": action}
    event.update(fields)
    return event


def _topology_payload() -> dict[str, object]:
    payload = valid_observed_payload()
    asset = _first_asset(payload)
    asset["variant_ref"] = "variant-1"
    asset["bundle_ref"] = "bundle-1"
    asset["sidecars"] = [
        {
            "observed_ref": "sidecar-1",
            "kind": "subtitle",
            "path": "movies/Synthetic.eng.srt",
        }
    ]
    payload["movies"] = [{"observed_ref": "movie-1", "title": "Synthetic"}]
    payload["series"] = [{"observed_ref": "series-1", "title": "Starline"}]
    payload["seasons"] = [
        {
            "observed_ref": "season-1",
            "series_ref": "series-1",
            "season_number": 1,
            "title": "Season 1",
        }
    ]
    payload["episodes"] = [
        {
            "observed_ref": "episode-1",
            "season_ref": "season-1",
            "episode_number": 1,
            "title": "Pilot",
            "aired_on": None,
            "absolute_number": None,
        }
    ]
    payload["artists"] = [{"observed_ref": "artist-1", "name": "North Index"}]
    payload["albums"] = [
        {
            "observed_ref": "album-1",
            "artist_ref": "artist-1",
            "title": "Winter Index",
            "release_year": 2024,
        }
    ]
    payload["discs"] = [{"observed_ref": "disc-1", "album_ref": "album-1", "disc_number": 1}]
    payload["tracks"] = [
        {
            "observed_ref": "track-1",
            "disc_ref": "disc-1",
            "track_number": 1,
            "title": "Opening",
            "performers": ["North Index"],
        }
    ]
    payload["variants"] = [
        {
            "observed_ref": "variant-1",
            "parent_kind": "movie",
            "parent_ref": "movie-1",
            "label": "hd",
        }
    ]
    payload["bundles"] = [
        {
            "observed_ref": "bundle-1",
            "variant_ref": "variant-1",
            "asset_refs": ["obs-asset-1"],
            "sidecar_refs": [{"asset_ref": "obs-asset-1", "sidecar_ref": "sidecar-1"}],
        }
    ]
    return payload


def _assert_invalid(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        ObservedState.model_validate(payload)


def _assert_extra_forbidden(payload: dict[str, object], loc: tuple[object, ...]) -> None:
    with pytest.raises(ValidationError) as exc_info:
        ObservedState.model_validate(payload)

    assert any(
        error["loc"] == loc and error["type"] == "extra_forbidden"
        for error in exc_info.value.errors()
    )


def test_observed_state_rejects_absolute_current_path() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["current_path"] = "/movies/Synthetic.mkv"
    _assert_invalid(payload)


def test_observed_state_rejects_parent_segment_in_path() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["current_path"] = "movies/../Synthetic.mkv"
    _assert_invalid(payload)


def test_observed_state_rejects_dot_segment_in_path() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["current_path"] = "movies/./Synthetic.mkv"
    _assert_invalid(payload)


def test_observed_state_rejects_empty_segment_in_path() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["current_path"] = "movies//Synthetic.mkv"
    _assert_invalid(payload)


def test_observed_state_rejects_trailing_slash_path() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["current_path"] = "movies/Synthetic.mkv/"
    _assert_invalid(payload)


def test_observed_state_rejects_backslash_path_separator() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["current_path"] = r"movies\Synthetic.mkv"
    _assert_invalid(payload)


def test_observed_state_rejects_nul_byte_in_path() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["current_path"] = "movies/Synthetic\x00.mkv"
    _assert_invalid(payload)


def test_observed_state_rejects_windows_drive_prefix_path() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["current_path"] = "C:/movies/Synthetic.mkv"
    _assert_invalid(payload)


def test_observed_state_rejects_create_sidecar_history_action() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["path_history"] = [_history_entry("create_sidecar")]
    _assert_invalid(payload)


def test_observed_state_rejects_move_without_from_and_to_paths() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["path_history"] = [_history_entry("move_asset", from_path="old.mkv")]
    _assert_invalid(payload)


def test_observed_state_rejects_delete_without_from_path() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["path_history"] = [_history_entry("delete_file")]
    _assert_invalid(payload)


def test_observed_state_rejects_add_without_to_path() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["path_history"] = [_history_entry("add_file")]
    _assert_invalid(payload)


def test_observed_state_rejects_slow_copy_start_without_temp_path() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["path_history"] = [
        _history_entry("slow_copy_start", from_path="old.mkv", to_path="new.mkv")
    ]
    _assert_invalid(payload)


def test_observed_state_rejects_global_event_without_ref_evidence() -> None:
    payload = valid_observed_payload()
    payload["events"] = [_global_event("event-1", "delete_file", from_path="movies/Synthetic.mkv")]
    _assert_invalid(payload)


def test_observed_state_rejects_global_event_with_mixed_ref_modes() -> None:
    payload = valid_observed_payload()
    payload["events"] = [
        _global_event(
            "event-1",
            "move_asset",
            observed_ref="obs-asset-1",
            before_observed_ref="obs-asset-1",
            after_observed_ref="obs-asset-2",
            from_path="movies/Synthetic.mkv",
            to_path="archive/Synthetic.mkv",
        )
    ]
    _assert_invalid(payload)


def test_observed_state_rejects_duplicate_asset_refs() -> None:
    payload = valid_observed_payload()
    payload["assets"] = [deepcopy(_first_asset(payload)), deepcopy(_first_asset(payload))]
    _assert_invalid(payload)


def test_observed_state_rejects_duplicate_sidecar_refs_within_asset() -> None:
    payload = _topology_payload()
    _first_asset(payload)["sidecars"] = [
        {"observed_ref": "sidecar-1", "kind": "subtitle", "path": "one.srt"},
        {"observed_ref": "sidecar-1", "kind": "poster", "path": "one.png"},
    ]
    _assert_invalid(payload)


def test_observed_state_allows_same_sidecar_ref_under_different_assets() -> None:
    payload = valid_observed_payload()
    asset = _first_asset(payload)
    asset["sidecars"] = [{"observed_ref": "sidecar-1", "kind": "subtitle", "path": "one.srt"}]
    second = deepcopy(asset)
    second["observed_ref"] = "obs-asset-2"
    second["current_path"] = "movies/Second.mkv"
    second["sidecars"] = [{"observed_ref": "sidecar-1", "kind": "subtitle", "path": "two.srt"}]
    payload["assets"] = [asset, second]

    ObservedState.model_validate(payload)


def test_observed_state_rejects_dangling_asset_bundle_ref() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["bundle_ref"] = "missing-bundle"
    _assert_invalid(payload)


def test_observed_state_rejects_bundle_asset_ref_not_declared() -> None:
    payload = _topology_payload()
    bundles = cast("list[dict[str, object]]", payload["bundles"])
    bundles[0]["asset_refs"] = ["missing-asset"]
    _assert_invalid(payload)


def test_observed_state_accepts_bundle_sidecar_ref_scoped_by_asset_ref() -> None:
    ObservedState.model_validate(_topology_payload())


def test_observed_state_rejects_cross_bundle_sidecar_ref() -> None:
    payload = _topology_payload()
    bundles = cast("list[dict[str, object]]", payload["bundles"])
    bundles[0]["sidecar_refs"] = [{"asset_ref": "obs-asset-2", "sidecar_ref": "sidecar-1"}]
    _assert_invalid(payload)


def test_observed_state_rejects_old_work_ref() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["work_ref"] = "work-1"
    _assert_extra_forbidden(payload, ("assets", 0, "work_ref"))


def test_observed_state_rejects_old_variant_work_ref() -> None:
    payload = _topology_payload()
    payload["variants"] = [{"observed_ref": "variant-1", "work_ref": "work-1", "label": "hd"}]
    _assert_extra_forbidden(payload, ("variants", 0, "work_ref"))


def test_observed_state_rejects_old_works_field() -> None:
    payload = valid_observed_payload()
    payload["works"] = [{"observed_ref": "work-1", "title": "Synthetic"}]
    _assert_extra_forbidden(payload, ("works",))


def test_observed_state_rejects_duplicate_domain_refs_across_domain_rows() -> None:
    payload = _topology_payload()
    payload["series"] = [
        {"observed_ref": "series-1", "title": "Starline"},
        {"observed_ref": "movie-1", "title": "Duplicate Ref"},
    ]

    with pytest.raises(ValidationError) as exc_info:
        ObservedState.model_validate(payload)

    assert any(
        "duplicate domain observed_ref: movie-1" in error["msg"]
        for error in exc_info.value.errors()
    )


@pytest.mark.parametrize(
    ("field_name", "replacement"),
    [
        (
            "seasons",
            {
                "observed_ref": "season-1",
                "series_ref": "missing-series",
                "season_number": 1,
                "title": "Season 1",
            },
        ),
        (
            "episodes",
            {
                "observed_ref": "episode-1",
                "season_ref": "missing-season",
                "episode_number": 1,
                "title": "Pilot",
                "aired_on": None,
                "absolute_number": None,
            },
        ),
        (
            "albums",
            {
                "observed_ref": "album-1",
                "artist_ref": "missing-artist",
                "title": "Winter Index",
                "release_year": 2024,
            },
        ),
        (
            "discs",
            {"observed_ref": "disc-1", "album_ref": "missing-album", "disc_number": 1},
        ),
        (
            "tracks",
            {
                "observed_ref": "track-1",
                "disc_ref": "missing-disc",
                "track_number": 1,
                "title": "Opening",
                "performers": ["North Index"],
            },
        ),
    ],
)
def test_observed_state_rejects_dangling_domain_parent_refs(
    field_name: str,
    replacement: dict[str, object],
) -> None:
    payload = _topology_payload()
    payload[field_name] = [replacement]
    _assert_invalid(payload)


def test_observed_state_rejects_variant_parent_ref_with_wrong_kind() -> None:
    payload = _topology_payload()
    payload["variants"] = [
        {
            "observed_ref": "variant-1",
            "parent_kind": "track",
            "parent_ref": "movie-1",
            "label": "hd",
        }
    ]
    _assert_invalid(payload)


def test_observed_state_rejects_podcast_variant_until_podcast_rows_exist() -> None:
    payload = _topology_payload()
    payload["variants"] = [
        {
            "observed_ref": "variant-1",
            "parent_kind": "podcast_episode",
            "parent_ref": "podcast-episode-1",
            "label": "default",
        }
    ]

    with pytest.raises(ValidationError) as exc_info:
        ObservedState.model_validate(payload)

    assert any(
        "invalid variant parent_ref: podcast-episode-1" in error["msg"]
        for error in exc_info.value.errors()
    )


def test_observed_state_rejects_bundle_variant_contradiction() -> None:
    payload = _topology_payload()
    _first_asset(payload)["variant_ref"] = "variant-2"
    payload["variants"] = [
        {
            "observed_ref": "variant-1",
            "parent_kind": "movie",
            "parent_ref": "movie-1",
            "label": "hd",
        },
        {
            "observed_ref": "variant-2",
            "parent_kind": "movie",
            "parent_ref": "movie-1",
            "label": "sd",
        },
    ]
    _assert_invalid(payload)


def test_grouped_history_accepts_reciprocal_explicit_links() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["path_history"] = [
        _history_entry(
            "slow_copy_start",
            observed_event_ref="start-1",
            related_observed_event_ref="commit-1",
            from_path="movies/Synthetic.mkv",
            to_path="archive/Synthetic.mkv",
            temp_path="archive/.Synthetic.tmp",
        ),
        _history_entry(
            "slow_copy_commit",
            observed_event_ref="commit-1",
            related_observed_event_ref="start-1",
            to_path="archive/Synthetic.mkv",
        ),
    ]

    ObservedState.model_validate(payload)


def test_grouped_history_accepts_deterministic_implicit_per_asset_links() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["path_history"] = [
        _history_entry("delete_file", from_path="movies/Synthetic.mkv"),
        _history_entry("add_file", to_path="archive/Synthetic.mkv"),
    ]

    ObservedState.model_validate(payload)


def test_grouped_history_rejects_duplicate_per_asset_observed_event_ref() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["path_history"] = [
        _history_entry("delete_file", observed_event_ref="event-1", from_path="old.mkv"),
        _history_entry("add_file", observed_event_ref="event-1", to_path="new.mkv"),
    ]
    _assert_invalid(payload)


def test_grouped_history_rejects_duplicate_global_observed_event_ref() -> None:
    payload = valid_observed_payload()
    payload["events"] = [
        _global_event("event-1", "delete_file", observed_ref="obs-asset-1", from_path="old.mkv"),
        _global_event("event-1", "add_file", observed_ref="obs-asset-1", to_path="new.mkv"),
    ]
    _assert_invalid(payload)


def test_grouped_history_rejects_dangling_related_event_ref() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["path_history"] = [
        _history_entry(
            "slow_copy_start",
            observed_event_ref="start-1",
            related_observed_event_ref="missing-commit",
            from_path="old.mkv",
            to_path="new.mkv",
            temp_path=".tmp",
        )
    ]
    _assert_invalid(payload)


def test_grouped_history_rejects_one_sided_link() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["path_history"] = [
        _history_entry(
            "slow_copy_start",
            observed_event_ref="start-1",
            related_observed_event_ref="commit-1",
            from_path="old.mkv",
            to_path="new.mkv",
            temp_path=".tmp",
        ),
        _history_entry("slow_copy_commit", observed_event_ref="commit-1", to_path="new.mkv"),
    ]
    _assert_invalid(payload)


def test_grouped_history_rejects_non_reciprocal_link() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["path_history"] = [
        _history_entry(
            "slow_copy_start",
            observed_event_ref="start-1",
            related_observed_event_ref="commit-1",
            from_path="old.mkv",
            to_path="new.mkv",
            temp_path=".tmp",
        ),
        _history_entry(
            "slow_copy_commit",
            observed_event_ref="commit-1",
            related_observed_event_ref="other-start",
            to_path="new.mkv",
        ),
    ]
    _assert_invalid(payload)


def test_grouped_history_rejects_mixed_explicit_and_implicit_pair() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["path_history"] = [
        _history_entry(
            "slow_copy_start",
            observed_event_ref="start-1",
            related_observed_event_ref="commit-1",
            from_path="old.mkv",
            to_path="new.mkv",
            temp_path=".tmp",
        ),
        _history_entry("slow_copy_commit", to_path="new.mkv"),
    ]
    _assert_invalid(payload)


def test_grouped_history_rejects_ambiguous_implicit_pairing() -> None:
    payload = valid_observed_payload()
    _first_asset(payload)["path_history"] = [
        _history_entry("delete_file", from_path="old.mkv"),
        _history_entry("add_file", to_path="new-a.mkv"),
        _history_entry("add_file", to_path="new-b.mkv"),
    ]
    _assert_invalid(payload)
