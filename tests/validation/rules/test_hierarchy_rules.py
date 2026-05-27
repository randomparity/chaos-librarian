"""Hierarchy validation tests for current Scenario semantic rules."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import cast

from chaos_librarian.contract.validation import ValidationIssue
from chaos_librarian.validation import codes, prepare_run_input, run_validation
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


def _first_movie_asset(raw: dict[str, object]) -> dict[str, object]:
    movie = _mapping(_items(raw["movies"])[0])
    variant = _mapping(_items(movie["variants"])[0])
    bundle = _mapping(variant["bundle"])
    return _mapping(_items(bundle["assets"])[0])


def _first_track_asset(raw: dict[str, object]) -> dict[str, object]:
    artist = _mapping(_items(raw["artists"])[0])
    album = _mapping(_items(artist["albums"])[0])
    disc = _mapping(_items(album["discs"])[0])
    track = _mapping(_items(disc["tracks"])[0])
    variant = _mapping(_items(track["variants"])[0])
    bundle = _mapping(variant["bundle"])
    return _mapping(_items(bundle["assets"])[0])


def _add_destination_series(raw: dict[str, object], *, episode_naming: str) -> None:
    _items(raw["series"]).append(
        {
            "id": "series_destination",
            "title": "Destination",
            "layout": "season_folders",
            "episode_naming": episode_naming,
            "seasons": [
                {
                    "id": "season_destination",
                    "season_number": 1,
                    "title": "Season 1",
                    "episodes": [],
                }
            ],
        }
    )


def _write_music_scenario(path: Path, *, timeline: str) -> None:
    path.write_text(
        f"""schema_version: 23
scenario_id: music-action-validation
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies: []
series: []
artists:
  - id: artist_north
    name: North Index
    layout: artist_album_disc
    track_naming: track_number_title
    albums:
      - id: album_winter
        title: Winter Index
        release_year: 2024
        discs:
          - id: disc_one
            disc_number: 1
            tracks:
              - id: track_one
                track_number: 1
                title: Opening
                performers:
                  - North Index
                variants:
                  - id: variant_track
                    label: Lossless
                    bundle:
                      id: bundle_track
                      assets:
                        - id: asset_track
                          role: main
                          container: flac
                          duration_seconds: 1
                          audio:
                            - source: sine
                              codec: flac
                              channels: stereo
                              language: eng
timeline:
{timeline}
""",
        encoding="utf-8",
    )


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


def test_track_asset_allows_audio_only_flac(music_scenario, empty_index) -> None:
    raw = music_scenario()

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)


def test_track_asset_rejects_video_stream(music_scenario, empty_index) -> None:
    raw = music_scenario()
    asset = _first_track_asset(raw)
    asset["container"] = "mp4"
    asset["audio"] = [{"source": "sine", "codec": "aac", "channels": "stereo", "language": "eng"}]
    asset["video"] = {"source": "color_bars", "codec": "h264", "resolution": "sd"}

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)


def test_movie_asset_rejects_audio_only(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario()
    asset = _first_movie_asset(raw)
    asset["container"] = "flac"
    asset["audio"] = [{"source": "sine", "codec": "flac", "channels": "stereo", "language": "eng"}]
    asset.pop("video")

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)


def test_track_asset_rejects_mp4_aac_video_container(music_scenario, empty_index) -> None:
    raw = music_scenario()
    asset = _first_track_asset(raw)
    asset["container"] = "mp4"
    asset["audio"] = [{"source": "sine", "codec": "aac", "channels": "stereo", "language": "eng"}]

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)


def test_reencode_video_rejects_audio_only_track_asset(music_scenario, empty_index) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "reencode_video",
                "target": "asset_track",
                "codec": "h264",
                "resolution": "sd",
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)


def test_extract_subtitle_rejects_audio_only_track_asset(music_scenario, empty_index) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "extract_subtitle",
                "target": "asset_track",
                "language": "eng",
                "to": "track.eng.srt",
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)


def test_declared_sidecar_uses_rendered_media_stem(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        asset_subtitles=[
            {
                "source": "generated_srt",
                "codec": "srt",
                "language": "eng",
                "mode": "sidecar",
            }
        ],
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "remove_sidecar",
                "target": "a",
                "sidecar_path": "r/Test Movie - l.eng.srt",
            }
        ],
    )
    issues = _issues_for(raw, empty_index)
    assert not any(issue.code == codes.E_SIDECAR_TARGET_UNKNOWN for issue in issues)


def test_slow_copy_temp_equal_to_rendered_initial_path_is_rejected(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        timeline=[
            {
                "id": "copy",
                "at": "1s",
                "action": "slow_copy_start",
                "target": "a",
                "to": "r/Copy.mkv",
                "temp_path": "r/Test Movie - l.mkv",
                "duration": "1s",
            },
            {"id": "commit", "at": "2s", "action": "slow_copy_commit", "for": "copy"},
        ]
    )
    issues = _issues_for(raw, empty_index)
    assert any(issue.code == codes.E_SLOW_COPY_PATH_COLLISION for issue in issues)


def test_reencode_audio_allows_audio_only_track_asset(music_scenario, empty_index) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "reencode_audio",
                "target": "asset_track",
                "from_channels": "stereo",
                "to_channels": "mono",
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)


def test_validation_reencode_video_rejects_audio_only_track_asset(tmp_path: Path) -> None:
    scenario = tmp_path / "track-reencode-video.yaml"
    _write_music_scenario(
        scenario,
        timeline="""  - id: ev
    at: 1s
    action: reencode_video
    target: asset_track
    codec: h264
    resolution: sd
""",
    )

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is False
    assert any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in report.issues)


def test_validation_reencode_audio_allows_audio_only_track_asset(tmp_path: Path) -> None:
    scenario = tmp_path / "track-reencode-audio.yaml"
    _write_music_scenario(
        scenario,
        timeline="""  - id: ev
    at: 1s
    action: reencode_audio
    target: asset_track
    from_channels: stereo
    to_channels: mono
""",
    )

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is True
    assert report.issues == []


def test_validation_remux_container_rejects_audio_only_track_asset(tmp_path: Path) -> None:
    scenario = tmp_path / "track-remux-container.yaml"
    _write_music_scenario(
        scenario,
        timeline="""  - id: ev
    at: 1s
    action: remux_container
    target: asset_track
    to_container: mp3
""",
    )

    report = run_validation(prepare_run_input(scenario))

    assert report.ok is False
    assert any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in report.issues)


def test_corrupt_packet_range_rejects_track_video_stream(music_scenario, empty_index) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "corrupt_packet_range",
                "target": "asset_track",
                "stream": "video",
                "packet_start": 0,
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)


def test_corrupt_packet_range_rejects_track_subtitle_stream(music_scenario, empty_index) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "corrupt_packet_range",
                "target": "asset_track",
                "stream": "subtitle",
                "packet_start": 0,
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)


def test_corrupt_packet_range_allows_track_audio_stream(music_scenario, empty_index) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "corrupt_packet_range",
                "target": "asset_track",
                "stream": "audio",
                "packet_start": 0,
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_MATERIALIZE_UNSUPPORTED for issue in issues)


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


def test_renumber_episode_rejects_duplicate_number_after_mutation(
    series_scenario, empty_index
) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "renumber_episode",
                "target": "episode_one",
                "episode_number": 2,
            }
        ]
    )
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    episodes = _items(season["episodes"])
    duplicate = dict(episodes[0])
    duplicate["id"] = "episode_two"
    duplicate["episode_number"] = 2
    duplicate["variants"] = []
    episodes.append(duplicate)

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_move_track_to_disc_rejects_duplicate_track_number_after_mutation(
    music_scenario, empty_index
) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "move_track_to_disc",
                "target": "track_one",
                "to_disc": "disc_two",
                "track_number": 1,
            }
        ]
    )
    artist = _items(raw["artists"])[0]
    album = _items(artist["albums"])[0]
    _items(album["discs"]).append(
        {
            "id": "disc_two",
            "disc_number": 2,
            "tracks": [
                {
                    "id": "track_two",
                    "track_number": 1,
                    "title": "Second Opening",
                    "performers": ["North Index"],
                    "variants": [],
                }
            ],
        }
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_move_episode_to_absolute_named_season_requires_absolute_number(
    series_scenario, empty_index
) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "move_episode_to_season",
                "target": "episode_one",
                "to_season": "season_destination",
                "episode_number": 1,
            }
        ]
    )
    source_series = _mapping(_items(raw["series"])[0])
    source_season = _mapping(_items(source_series["seasons"])[0])
    source_episode = _mapping(_items(source_season["episodes"])[0])
    source_episode.pop("absolute_number")
    _add_destination_series(raw, episode_naming="absolute_3_digit_title")

    issues = _issues_for(raw, empty_index)

    assert any(
        issue.code == codes.E_HIERARCHY_INVALID and issue.path == "$.timeline[0].action"
        for issue in issues
    )


def test_move_unmanaged_added_episode_to_absolute_named_season_keeps_explicit_path(
    series_scenario, empty_index
) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "delete",
                "at": "1s",
                "action": "delete_file",
                "target": "asset_episode",
            },
            {
                "id": "add",
                "at": "2s",
                "action": "add_file",
                "target": "asset_episode",
                "to": "TV/manual/explicit.mkv",
            },
            {
                "id": "move",
                "at": "3s",
                "action": "move_episode_to_season",
                "target": "episode_one",
                "to_season": "season_destination",
                "episode_number": 1,
            },
        ]
    )
    source_series = _mapping(_items(raw["series"])[0])
    source_season = _mapping(_items(source_series["seasons"])[0])
    source_episode = _mapping(_items(source_season["episodes"])[0])
    source_episode.pop("absolute_number")
    _add_destination_series(raw, episode_naming="absolute_3_digit_title")

    issues = _issues_for(raw, empty_index)

    assert not any(
        issue.code == codes.E_HIERARCHY_INVALID and issue.path == "$.timeline[2].action"
        for issue in issues
    )


def test_move_episode_to_date_named_season_requires_aired_on(series_scenario, empty_index) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "move_episode_to_season",
                "target": "episode_one",
                "to_season": "season_destination",
                "episode_number": 1,
            }
        ]
    )
    source_series = _mapping(_items(raw["series"])[0])
    source_season = _mapping(_items(source_series["seasons"])[0])
    source_episode = _mapping(_items(source_season["episodes"])[0])
    source_episode.pop("aired_on")
    _add_destination_series(raw, episode_naming="date_title")

    issues = _issues_for(raw, empty_index)

    assert any(
        issue.code == codes.E_HIERARCHY_INVALID and issue.path == "$.timeline[0].action"
        for issue in issues
    )


def test_sequential_hierarchy_actions_render_from_mutated_metadata(
    series_scenario, empty_index
) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "rename",
                "at": "1s",
                "action": "rename_season",
                "target": "season_one",
                "title": "Renamed Season",
            },
            {
                "id": "renumber",
                "at": "2s",
                "action": "renumber_episode",
                "target": "episode_one",
                "episode_number": 2,
            },
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_PATH_COLLISION for issue in issues)
    assert not any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


def test_hierarchy_collision_after_root_move_uses_current_root(
    series_scenario, empty_index
) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "move-root",
                "at": "1s",
                "action": "move_between_roots",
                "target": "asset_episode",
                "from_root_id": "tv",
                "to_root_id": "cold",
            },
            {
                "id": "move-other",
                "at": "2s",
                "action": "move_asset",
                "target": "asset_episode_other",
                "to": "Cold/Starline/Season 01/Starline - S01E02 - Pilot - HD.mkv",
            },
            {
                "id": "renumber",
                "at": "3s",
                "action": "renumber_episode",
                "target": "episode_one",
                "episode_number": 2,
            },
        ],
        library={"roots": [{"id": "tv", "path": "TV"}, {"id": "cold", "path": "Cold"}]},
    )
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    episodes = _items(season["episodes"])
    other = dict(episodes[0])
    other["id"] = "episode_other"
    other["episode_number"] = 3
    other["title"] = "Other"
    other["variants"] = [
        {
            "id": "variant_episode_other",
            "label": "Other",
            "bundle": {
                "id": "bundle_episode_other",
                "assets": [
                    {
                        "id": "asset_episode_other",
                        "role": "main",
                        "container": "mkv",
                        "duration_seconds": 1,
                        "video": {"source": "color_bars", "codec": "h264", "resolution": "sd"},
                        "audio": [
                            {
                                "source": "sine",
                                "codec": "aac",
                                "channels": "stereo",
                                "language": "eng",
                            }
                        ],
                    }
                ],
            },
        }
    ]
    episodes.append(other)

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_PATH_COLLISION for issue in issues)


def test_hierarchy_collision_after_manual_move_uses_primary_root(
    series_scenario, empty_index
) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "move-manual",
                "at": "1s",
                "action": "move_asset",
                "target": "asset_episode",
                "to": "Custom/episode.mkv",
            },
            {
                "id": "move-other",
                "at": "2s",
                "action": "move_asset",
                "target": "asset_episode_other",
                "to": "TV/Starline/Season 01/Starline - S01E02 - Pilot - HD.mkv",
            },
            {
                "id": "renumber",
                "at": "3s",
                "action": "renumber_episode",
                "target": "episode_one",
                "episode_number": 2,
            },
        ]
    )
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    episodes = _items(season["episodes"])
    other = dict(episodes[0])
    other["id"] = "episode_other"
    other["episode_number"] = 3
    other["title"] = "Other"
    other["variants"] = [
        {
            "id": "variant_episode_other",
            "label": "Other",
            "bundle": {
                "id": "bundle_episode_other",
                "assets": [
                    {
                        "id": "asset_episode_other",
                        "role": "main",
                        "container": "mkv",
                        "duration_seconds": 1,
                        "video": {"source": "color_bars", "codec": "h264", "resolution": "sd"},
                        "audio": [
                            {
                                "source": "sine",
                                "codec": "aac",
                                "channels": "stereo",
                                "language": "eng",
                            }
                        ],
                    }
                ],
            },
        }
    ]
    episodes.append(other)

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_PATH_COLLISION for issue in issues)


def test_hierarchy_action_under_pending_slow_copy_is_rejected(series_scenario, empty_index) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "copy",
                "at": "1s",
                "action": "slow_copy_start",
                "target": "asset_episode",
                "to": "TV/Starline/Season 01/copy.mkv",
                "temp_path": "TV/Starline/Season 01/copy.part",
                "duration": "2s",
            },
            {
                "id": "renumber",
                "at": "2s",
                "action": "renumber_episode",
                "target": "episode_one",
                "episode_number": 2,
            },
            {"id": "commit", "at": "3s", "action": "slow_copy_commit", "for": "copy"},
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_LIFECYCLE_INVALID for issue in issues)


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


def test_date_title_accepts_aired_on_date_object(series_scenario, empty_index) -> None:
    raw = series_scenario(episode_naming="date_title")
    series = _items(raw["series"])[0]
    season = _items(series["seasons"])[0]
    _items(season["episodes"])[0]["aired_on"] = date(2024, 5, 1)

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_HIERARCHY_INVALID for issue in issues)


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


def test_rendered_initial_asset_path_collision_is_rejected(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario()
    first_movie = _mapping(_items(raw["movies"])[0])
    second_movie = {
        "id": "movie_two",
        "title": first_movie["title"],
        "layout": first_movie["layout"],
        "variants": [
            {
                "id": "v_two",
                "label": "l",
                "bundle": {
                    "id": "b_two",
                    "assets": [
                        {
                            "id": "asset_two",
                            "role": "main",
                            "container": "mkv",
                            "duration_seconds": 1,
                            "video": {
                                "source": "color_bars",
                                "codec": "h264",
                                "resolution": "sd",
                            },
                            "audio": [
                                {
                                    "source": "sine",
                                    "codec": "aac",
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
    _items(raw["movies"]).append(second_movie)

    issues = _issues_for(raw, empty_index)

    assert any(
        issue.code == codes.E_PATH_COLLISION
        and "$.movies[0].variants[0].bundle.assets[0]" in issue.message
        for issue in issues
    )


def test_rendered_title_dot_segment_is_rejected(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario()
    _mapping(_items(raw["movies"])[0])["title"] = "."

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_PATH_CONTAINMENT for issue in issues)


def test_rendered_track_path_uses_music_layout_for_collision_check(
    music_scenario, empty_index
) -> None:
    raw = music_scenario()
    artist = _mapping(_items(raw["artists"])[0])
    artist["layout"] = "artist_album_flat"
    album = _mapping(_items(artist["albums"])[0])
    disc = _mapping(_items(album["discs"])[0])
    original_track = _mapping(_items(disc["tracks"])[0])
    second_track = {
        "id": "track_two",
        "track_number": original_track["track_number"],
        "title": original_track["title"],
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
    _items(album["discs"]).append(
        {
            "id": "disc_two",
            "disc_number": 2,
            "tracks": [second_track],
        }
    )

    issues = _issues_for(raw, empty_index)

    assert any(issue.code == codes.E_PATH_COLLISION for issue in issues)
