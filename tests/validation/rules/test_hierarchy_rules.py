"""Hierarchy validation tests for Scenario v12 semantic rules."""

from __future__ import annotations

from typing import cast

from chaos_librarian.contract.validation import ValidationIssue
from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.rules._common import iter_asset_contexts, renderable_context_for
from chaos_librarian.validation.semantic import run_semantic_pass


def _items(node: object) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", node)


def _mapping(node: object) -> dict[str, object]:
    return cast("dict[str, object]", node)


def _issues_for(raw: dict[str, object], empty_index) -> list[ValidationIssue]:
    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)
    return collector.issues


def test_movie_asset_target_is_found_by_raw_hierarchy_walker(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        timeline=[{"id": "ev", "at": "1s", "action": "delete_file", "target": "a"}]
    )

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_TARGET_UNKNOWN for issue in issues)


def test_episode_asset_target_is_found_by_raw_hierarchy_walker(
    series_scenario, empty_index
) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "delete_file",
                "target": "asset_episode",
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_TARGET_UNKNOWN for issue in issues)


def test_track_asset_target_is_found_by_raw_hierarchy_walker(music_scenario, empty_index) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "delete_file",
                "target": "asset_track",
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_TARGET_UNKNOWN for issue in issues)


def test_renumber_episode_requires_episode_target(series_scenario, empty_index) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "renumber_episode",
                "target": "season_one",
                "episode_number": 2,
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_TARGET_UNKNOWN for issue in issues)


def test_move_episode_to_season_requires_known_destination_season(
    series_scenario, empty_index
) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "move_episode_to_season",
                "target": "episode_one",
                "to_season": "season_missing",
                "episode_number": 2,
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(
        issue.code == codes.E_TARGET_UNKNOWN and issue.path == "$.timeline[0].to_season"
        for issue in issues
    )


def test_move_track_to_disc_requires_track_target(music_scenario, empty_index) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "move_track_to_disc",
                "target": "disc_one",
                "to_disc": "disc_one",
                "track_number": 2,
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_TARGET_UNKNOWN for issue in issues)


def test_move_track_to_disc_requires_known_destination_disc(music_scenario, empty_index) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "move_track_to_disc",
                "target": "track_one",
                "to_disc": "disc_missing",
                "track_number": 2,
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(
        issue.code == codes.E_TARGET_UNKNOWN and issue.path == "$.timeline[0].to_disc"
        for issue in issues
    )


def test_duplicate_id_across_root_and_movie_is_rejected(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario()
    _items(raw["movies"])[0]["id"] = "r"

    issues = _issues_for(raw, empty_index)

    dup = [issue for issue in issues if issue.code == codes.E_ID_DUPLICATE]
    assert len(dup) == 1
    assert "movie_id" in dup[0].message
    assert "'r'" in dup[0].message


def test_duplicate_id_across_episode_and_asset_is_rejected(series_scenario, empty_index) -> None:
    raw = series_scenario()
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    _items(season["episodes"])[0]["id"] = "asset_episode"

    issues = _issues_for(raw, empty_index)

    assert any(
        issue.code == codes.E_ID_DUPLICATE
        and "episode_id" in issue.message
        and "'asset_episode'" in issue.message
        for issue in issues
    )


def test_duplicate_id_across_album_and_timeline_event_is_rejected(
    music_scenario, empty_index
) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "album_winter",
                "at": "1s",
                "action": "delete_file",
                "target": "asset_track",
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(
        issue.code == codes.E_ID_DUPLICATE
        and "timeline_id" in issue.message
        and "'album_winter'" in issue.message
        for issue in issues
    )


def test_date_named_episode_without_aired_on_is_not_renderable(series_scenario) -> None:
    raw = series_scenario(episode_naming="date_title")
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    episode = _items(season["episodes"])[0]
    episode.pop("aired_on")
    context = next(iter_asset_contexts(raw))

    renderable = renderable_context_for(context, "TV")

    assert renderable is None


def test_date_named_episode_with_malformed_aired_on_is_not_renderable(
    series_scenario,
) -> None:
    raw = series_scenario(episode_naming="date_title")
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    episode = _items(season["episodes"])[0]
    episode["aired_on"] = "not-a-date"
    context = next(iter_asset_contexts(raw))

    renderable = renderable_context_for(context, "TV")

    assert renderable is None


def test_absolute_named_episode_without_absolute_number_is_not_renderable(
    series_scenario,
) -> None:
    raw = series_scenario(episode_naming="absolute_3_digit_title")
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    episode = _items(season["episodes"])[0]
    episode.pop("absolute_number")
    context = next(iter_asset_contexts(raw))

    renderable = renderable_context_for(context, "TV")

    assert renderable is None


def test_season_zero_specials_is_valid(series_scenario, empty_index) -> None:
    raw = series_scenario()
    series = _items(raw["series"])[0]
    _items(series["seasons"])[0]["season_number"] = 0

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_duplicate_episode_number_in_one_season_is_rejected(series_scenario, empty_index) -> None:
    raw = series_scenario()
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    episodes = _items(season["episodes"])
    duplicate = dict(episodes[0])
    duplicate["id"] = "episode_two"
    episodes.append(duplicate)

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_date_title_requires_aired_on(series_scenario, empty_index) -> None:
    raw = series_scenario(episode_naming="date_title")
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    _items(season["episodes"])[0].pop("aired_on")

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_absolute_3_digit_title_requires_absolute_number(series_scenario, empty_index) -> None:
    raw = series_scenario(episode_naming="absolute_3_digit_title")
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    _items(season["episodes"])[0].pop("absolute_number")

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_duplicate_disc_number_in_one_album_is_rejected(music_scenario, empty_index) -> None:
    raw = music_scenario()
    artist = _items(raw["artists"])[0]
    album = _items(artist["albums"])[0]
    duplicate: dict[str, object] = {
        "id": "disc_two",
        "disc_number": 1,
        "tracks": [],
    }
    _items(album["discs"]).append(duplicate)

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_duplicate_track_number_in_one_disc_is_rejected(music_scenario, empty_index) -> None:
    raw = music_scenario()
    artist = _items(raw["artists"])[0]
    album = _items(artist["albums"])[0]
    disc = _items(album["discs"])[0]
    tracks = _items(disc["tracks"])
    duplicate = dict(tracks[0])
    duplicate["id"] = "track_two"
    duplicate["variants"] = []
    tracks.append(duplicate)

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)
