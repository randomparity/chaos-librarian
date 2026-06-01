"""Behavior tests for mutable hierarchy projection state."""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from chaos_librarian.validation.rules.hierarchy.projection import HierarchyProjection

ScenarioBuilder = Callable[..., dict[str, object]]


def test_project_non_hierarchy_event_tracks_direct_path_mutations(
    minimal_scenario: ScenarioBuilder,
) -> None:
    """Direct path actions must keep the projection aligned with engine state."""
    projection = HierarchyProjection(minimal_scenario())
    pending_slow_copies: dict[str, tuple[str, str]] = {}

    projection.project_non_hierarchy_event(
        {"action": "move_asset", "target": "a", "to": "r/moved.mkv"},
        pending_slow_copies,
    )
    assert projection.current_paths["a"] == "r/moved.mkv"

    projection.project_non_hierarchy_event(
        {"action": "rename_file", "target": "a", "to": "r/renamed.mkv"},
        pending_slow_copies,
    )
    assert projection.current_paths["a"] == "r/renamed.mkv"

    projection.project_non_hierarchy_event(
        {"action": "add_file", "target": "a", "to": "r/added.mkv"},
        pending_slow_copies,
    )
    assert projection.current_paths["a"] == "r/added.mkv"

    projection.project_non_hierarchy_event(
        {"action": "remux_container", "target": "a", "to_container": "mp4"},
        pending_slow_copies,
    )
    assert projection.current_paths["a"] == "r/added.mp4"

    projection.project_non_hierarchy_event(
        {"action": "delete_file", "target": "a"},
        pending_slow_copies,
    )
    assert "a" not in projection.current_paths


def test_slow_copy_commit_applies_pending_path(
    minimal_scenario: ScenarioBuilder,
) -> None:
    """A slow-copy start must not move the asset until the matching commit."""
    projection = HierarchyProjection(minimal_scenario())
    pending_slow_copies: dict[str, tuple[str, str]] = {}
    original_path = projection.current_paths["a"]

    projection.project_non_hierarchy_event(
        {
            "id": "copy_a",
            "action": "slow_copy_start",
            "target": "a",
            "to": "r/copied.mkv",
        },
        pending_slow_copies,
    )
    assert projection.current_paths["a"] == original_path
    assert pending_slow_copies == {"copy_a": ("a", "r/copied.mkv")}

    projection.project_non_hierarchy_event(
        {"action": "slow_copy_commit", "for": "copy_a"},
        pending_slow_copies,
    )
    assert pending_slow_copies == {}
    assert projection.current_paths["a"] == "r/copied.mkv"


def test_render_asset_path_falls_back_to_primary_root(
    series_scenario: ScenarioBuilder,
) -> None:
    """Hierarchy rendering should recover when an asset lacks a declared root."""
    projection = HierarchyProjection(series_scenario())

    projection.current_paths.pop("asset_episode")
    missing_path = projection.render_asset_path("asset_episode")
    assert missing_path is not None
    assert missing_path.startswith("TV/")

    projection.current_paths["asset_episode"] = "Detached/Pilot.mkv"
    assert projection.render_asset_path("asset_episode") == missing_path


def test_archive_and_root_move_projection_handle_valid_and_invalid_roots(
    minimal_scenario: ScenarioBuilder,
) -> None:
    """Derived-root path actions should mutate only when root replacement is valid."""
    raw = minimal_scenario(
        library={
            "roots": [
                {"id": "r", "path": "r"},
                {"id": "cold-storage", "path": "cold-storage"},
            ],
            "archive_root": "cold-storage",
        }
    )
    projection = HierarchyProjection(raw)
    pending_slow_copies: dict[str, tuple[str, str]] = {}

    projection.current_paths["a"] = "r/movie.mkv"
    projection.project_non_hierarchy_event(
        {"action": "archive_file", "target": "a"},
        pending_slow_copies,
    )
    assert projection.current_paths["a"] == "cold-storage/movie.mkv"

    projection.project_non_hierarchy_event(
        {
            "action": "move_between_roots",
            "target": "a",
            "from_root_id": "cold-storage",
            "to_root_id": "r",
        },
        pending_slow_copies,
    )
    assert projection.current_paths["a"] == "r/movie.mkv"

    projection.current_paths["a"] = "Detached/movie.mkv"
    projection.project_non_hierarchy_event(
        {"action": "archive_file", "target": "a"},
        pending_slow_copies,
    )
    assert projection.current_paths["a"] == "Detached/movie.mkv"

    projection.project_non_hierarchy_event(
        {
            "action": "move_between_roots",
            "target": "a",
            "from_root_id": "missing",
            "to_root_id": "r",
        },
        pending_slow_copies,
    )
    assert projection.current_paths["a"] == "Detached/movie.mkv"


def test_swap_refreshes_renderer_managed_paths(
    music_scenario: ScenarioBuilder,
) -> None:
    """Swapping track numbers must refresh all affected renderer-owned paths."""
    raw = music_scenario()
    _append_second_track(raw)
    projection = HierarchyProjection(raw)
    before = {
        "asset_track": projection.current_paths["asset_track"],
        "asset_track_two": projection.current_paths["asset_track_two"],
    }

    mutation = projection.apply(
        {
            "action": "swap_track_numbers",
            "target": "track_one",
            "with_track": "track_two",
        }
    )

    assert mutation.affected_asset_ids == frozenset({"asset_track", "asset_track_two"})
    assert mutation.affected_disc_ids == frozenset({"disc_one"})
    assert set(mutation.path_changes) == {"asset_track", "asset_track_two"}
    for asset_id, old_path in before.items():
        change = mutation.path_changes[asset_id]
        assert change[0] == old_path
        assert projection.current_paths[asset_id] == change[1]
        assert projection.current_paths[asset_id] != old_path


def _append_second_track(raw: dict[str, object]) -> None:
    artists = cast("list[dict[str, object]]", raw["artists"])
    albums = cast("list[dict[str, object]]", artists[0]["albums"])
    discs = cast("list[dict[str, object]]", albums[0]["discs"])
    tracks = cast("list[dict[str, object]]", discs[0]["tracks"])
    tracks.append(
        {
            "id": "track_two",
            "track_number": 2,
            "title": "Closing",
            "performers": ["North Index"],
            "variants": [
                {
                    "id": "variant_track_two",
                    "label": "Lossless",
                    "bundle": {
                        "id": "bundle_track_two",
                        "assets": [
                            {
                                "id": "asset_track_two",
                                "role": "main",
                                "container": "flac",
                                "duration_seconds": 1,
                                "audio": [
                                    {
                                        "source": "sine",
                                        "codec": "flac",
                                        "channels": "stereo",
                                        "language": "eng",
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
        }
    )
