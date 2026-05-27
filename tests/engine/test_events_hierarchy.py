"""Tests for hierarchy timeline event handlers."""

from __future__ import annotations

import uuid
from typing import Any

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.scenario import Scenario, TimelineActionName
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state
from tests.engine.conftest import _engine_event_context

_RUN_ID = uuid.UUID("87654321-4321-6789-4321-678987654321")


def _apply_timeline(scenario: Scenario) -> tuple[Any, ...]:
    ids = IdAllocator(TraceRecorder())
    state = build_initial_state(scenario, ids)
    entries: list[object] = []
    for resolved in resolve_timeline(scenario):
        entries.extend(
            apply_event(
                state=state,
                resolved=resolved,
                ids=ids,
                ctx=_engine_event_context(scenario.scenario_id, run_id=_RUN_ID),
            )
        )
    return state, *entries


def _series_scenario(timeline: list[dict[str, object]]) -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 19,
            "scenario_id": "hierarchy-series",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "tv", "path": "library/tv"}]},
            "movies": [],
            "series": [
                {
                    "id": "series_1",
                    "title": "Show",
                    "layout": "season_folders",
                    "episode_naming": "sxxexx_title",
                    "seasons": [
                        {
                            "id": "season_1",
                            "season_number": 1,
                            "title": "Original",
                            "episodes": [
                                {
                                    "id": "episode_1",
                                    "episode_number": 1,
                                    "absolute_number": 11,
                                    "title": "Pilot",
                                    "variants": [
                                        {
                                            "id": "variant_1",
                                            "label": "web",
                                            "bundle": {
                                                "id": "bundle_1",
                                                "assets": [
                                                    {
                                                        "id": "episode_asset",
                                                        "role": "primary_video",
                                                        "container": "mkv",
                                                        "duration_seconds": 1,
                                                        "subtitles": [
                                                            {
                                                                "codec": "srt",
                                                                "language": "eng",
                                                                "mode": "sidecar",
                                                            }
                                                        ],
                                                    }
                                                ],
                                            },
                                        }
                                    ],
                                }
                            ],
                        },
                        {
                            "id": "season_2",
                            "season_number": 2,
                            "title": "Second",
                            "episodes": [],
                        },
                    ],
                }
            ],
            "artists": [],
            "timeline": timeline,
        }
    )


def _series_two_asset_scenario(timeline: list[dict[str, object]]) -> Scenario:
    payload = _series_scenario(timeline).model_dump(mode="json")
    assets = payload["series"][0]["seasons"][0]["episodes"][0]["variants"][0]["bundle"]["assets"]
    assets.append(
        {
            "id": "bonus_asset",
            "role": "commentary",
            "container": "mkv",
            "duration_seconds": 1,
        }
    )
    return Scenario.model_validate(payload)


def _music_scenario(timeline: list[dict[str, object]]) -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 19,
            "scenario_id": "hierarchy-music",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "music", "path": "library/music"}]},
            "movies": [],
            "series": [],
            "artists": [
                {
                    "id": "artist_1",
                    "name": "Artist",
                    "layout": "artist_album_disc",
                    "track_naming": "disc_track_number_title",
                    "albums": [
                        {
                            "id": "album_1",
                            "title": "Album",
                            "release_year": 2026,
                            "discs": [
                                {
                                    "id": "disc_1",
                                    "disc_number": 1,
                                    "tracks": [
                                        {
                                            "id": "track_1",
                                            "track_number": 1,
                                            "title": "Opener",
                                            "variants": [
                                                {
                                                    "id": "variant_track_1",
                                                    "label": "flac",
                                                    "bundle": {
                                                        "id": "bundle_track_1",
                                                        "assets": [
                                                            {
                                                                "id": "track_asset",
                                                                "role": "audio",
                                                                "container": "flac",
                                                                "duration_seconds": 1,
                                                            }
                                                        ],
                                                    },
                                                }
                                            ],
                                        }
                                    ],
                                },
                                {
                                    "id": "disc_2",
                                    "disc_number": 2,
                                    "tracks": [],
                                },
                            ],
                        }
                    ],
                }
            ],
            "timeline": timeline,
        }
    )


def test_renumber_episode_moves_asset_and_renderer_derived_sidecar_only() -> None:
    """WHY: hierarchy metadata changes must rerender declared paths, not explicit sidecars."""
    scenario = _series_scenario(
        [
            {
                "id": "ev_sidecar",
                "at": "1s",
                "action": "create_sidecar",
                "target": "episode_asset",
                "to": "library/custom/spanish.srt",
                "language": "spa",
            },
            {
                "id": "ev_renumber",
                "at": "2s",
                "action": "renumber_episode",
                "target": "episode_1",
                "episode_number": 2,
                "absolute_number": 12,
            },
        ]
    )
    state, _sidecar_entry, entry = _apply_timeline(scenario)

    assert isinstance(entry, AtomicJournalEntry)
    assert entry.phase == JournalPhase.ATOMIC
    assert entry.action == TimelineActionName.RENUMBER_EPISODE
    assert entry.target_ids == ["episode_1", "episode_asset"]
    assert state.episodes["episode_1"].episode_number == 2
    assert state.episodes["episode_1"].absolute_number == 12
    assert entry.state_delta["metadata"] == {
        "episode_number": {"before": 1, "after": 2},
        "absolute_number": {"before": 11, "after": 12},
    }
    assert entry.state_delta["path_moves"] == [
        {
            "asset_id": "episode_asset",
            "location_id": "location_0001",
            "from_path": "library/tv/Show/Season 01/Show - S01E01 - Pilot - web.mkv",
            "to_path": "library/tv/Show/Season 01/Show - S01E02 - Pilot - web.mkv",
        }
    ]
    assert entry.state_delta["sidecar_moves"] == [
        {
            "sidecar_id": "sidecar_episode_asset_eng",
            "asset_id": "episode_asset",
            "from_path": "library/tv/Show/Season 01/Show - S01E01 - Pilot - web.eng.srt",
            "to_path": "library/tv/Show/Season 01/Show - S01E02 - Pilot - web.eng.srt",
        }
    ]
    assert entry.state_delta["skipped_deleted_asset_ids"] == []
    assert state.sidecars["sidecar_0001"].path == "library/custom/spanish.srt"


def test_move_episode_to_season_composes_with_current_episode_metadata() -> None:
    """WHY: sequential hierarchy actions must rerender from WorldState, not Scenario."""
    scenario = _series_scenario(
        [
            {
                "id": "ev_renumber",
                "at": "1s",
                "action": "renumber_episode",
                "target": "episode_1",
                "episode_number": 3,
            },
            {
                "id": "ev_move",
                "at": "2s",
                "action": "move_episode_to_season",
                "target": "episode_1",
                "to_season": "season_2",
                "episode_number": 1,
            },
        ]
    )
    state, _renumber_entry, entry = _apply_timeline(scenario)

    assert state.episodes["episode_1"].season_id == "season_2"
    assert state.episodes["episode_1"].episode_number == 1
    assert entry.target_ids == ["episode_1", "episode_asset"]
    assert entry.state_delta["metadata"] == {
        "season_id": {"before": "season_1", "after": "season_2"},
        "episode_number": {"before": 3, "after": 1},
    }
    assert entry.state_delta["path_moves"] == [
        {
            "asset_id": "episode_asset",
            "location_id": "location_0001",
            "from_path": "library/tv/Show/Season 01/Show - S01E03 - Pilot - web.mkv",
            "to_path": "library/tv/Show/Season 02/Show - S02E01 - Pilot - web.mkv",
        }
    ]


def test_hierarchy_rerender_preserves_current_episode_root() -> None:
    """WHY: hierarchy metadata changes must not undo a prior root relocation."""
    payload = _series_scenario(
        [
            {
                "id": "ev_move_root",
                "at": "1s",
                "action": "move_between_roots",
                "target": "episode_asset",
                "from_root_id": "tv",
                "to_root_id": "cold",
            },
            {
                "id": "ev_renumber",
                "at": "2s",
                "action": "renumber_episode",
                "target": "episode_1",
                "episode_number": 2,
            },
        ]
    ).model_dump(mode="json")
    payload["library"]["roots"].append({"id": "cold", "path": "library/cold"})
    scenario = Scenario.model_validate(payload)

    state, _move_entry, entry = _apply_timeline(scenario)

    assert entry.state_delta["path_moves"] == [
        {
            "asset_id": "episode_asset",
            "location_id": "location_0001",
            "from_path": "library/cold/Show/Season 01/Show - S01E01 - Pilot - web.mkv",
            "to_path": "library/cold/Show/Season 01/Show - S01E02 - Pilot - web.mkv",
        }
    ]
    loc_id = state.location_id_for_asset("episode_asset")
    assert state.locations[loc_id].path == (
        "library/cold/Show/Season 01/Show - S01E02 - Pilot - web.mkv"
    )


def test_hierarchy_rerender_after_manual_move_falls_back_to_primary_root() -> None:
    """WHY: manual moves outside declared roots must not crash hierarchy actions."""
    scenario = _series_scenario(
        [
            {
                "id": "ev_move_manual",
                "at": "1s",
                "action": "move_asset",
                "target": "episode_asset",
                "to": "library/manual/episode.mkv",
            },
            {
                "id": "ev_renumber",
                "at": "2s",
                "action": "renumber_episode",
                "target": "episode_1",
                "episode_number": 2,
            },
        ]
    )

    state, _move_entry, entry = _apply_timeline(scenario)

    assert entry.state_delta["path_moves"] == [
        {
            "asset_id": "episode_asset",
            "location_id": "location_0001",
            "from_path": "library/manual/episode.mkv",
            "to_path": "library/tv/Show/Season 01/Show - S01E02 - Pilot - web.mkv",
        }
    ]
    loc_id = state.location_id_for_asset("episode_asset")
    assert state.locations[loc_id].path == (
        "library/tv/Show/Season 01/Show - S01E02 - Pilot - web.mkv"
    )


def test_rename_season_updates_metadata_without_path_moves_for_current_renderer() -> None:
    """WHY: season title is manifest metadata, but today's renderer does not use it."""
    scenario = _series_scenario(
        [
            {
                "id": "ev_rename_season",
                "at": "1s",
                "action": "rename_season",
                "target": "season_1",
                "title": "Renamed",
            }
        ]
    )
    state, entry = _apply_timeline(scenario)

    assert state.seasons["season_1"].title == "Renamed"
    assert entry.target_ids == ["season_1", "episode_asset"]
    assert entry.state_delta["metadata"] == {"title": {"before": "Original", "after": "Renamed"}}
    assert entry.state_delta["path_moves"] == []
    assert entry.state_delta["sidecar_moves"] == []
    assert entry.state_delta["skipped_deleted_asset_ids"] == []


def test_renumber_disc_moves_track_assets_under_disc_layout() -> None:
    """WHY: music disc metadata is part of renderer-derived paths."""
    scenario = _music_scenario(
        [
            {
                "id": "ev_renumber_disc",
                "at": "1s",
                "action": "renumber_disc",
                "target": "disc_1",
                "disc_number": 2,
            }
        ]
    )
    state, entry = _apply_timeline(scenario)

    assert state.discs["disc_1"].disc_number == 2
    assert entry.target_ids == ["disc_1", "track_asset"]
    assert entry.state_delta["metadata"] == {"disc_number": {"before": 1, "after": 2}}
    assert entry.state_delta["path_moves"] == [
        {
            "asset_id": "track_asset",
            "location_id": "location_0001",
            "from_path": "library/music/Artist/Album/Disc 01/01-01 - Opener - flac.flac",
            "to_path": "library/music/Artist/Album/Disc 02/02-01 - Opener - flac.flac",
        }
    ]


def test_hierarchy_rerender_preserves_current_track_root() -> None:
    """WHY: music hierarchy moves share the same renderer root semantics as episodes."""
    payload = _music_scenario(
        [
            {
                "id": "ev_move_root",
                "at": "1s",
                "action": "move_between_roots",
                "target": "track_asset",
                "from_root_id": "music",
                "to_root_id": "cold",
            },
            {
                "id": "ev_renumber_disc",
                "at": "2s",
                "action": "renumber_disc",
                "target": "disc_1",
                "disc_number": 2,
            },
        ]
    ).model_dump(mode="json")
    payload["library"]["roots"].append({"id": "cold", "path": "library/cold"})
    scenario = Scenario.model_validate(payload)

    state, _move_entry, entry = _apply_timeline(scenario)

    assert entry.state_delta["path_moves"] == [
        {
            "asset_id": "track_asset",
            "location_id": "location_0001",
            "from_path": "library/cold/Artist/Album/Disc 01/01-01 - Opener - flac.flac",
            "to_path": "library/cold/Artist/Album/Disc 02/02-01 - Opener - flac.flac",
        }
    ]
    loc_id = state.location_id_for_asset("track_asset")
    assert state.locations[loc_id].path == (
        "library/cold/Artist/Album/Disc 02/02-01 - Opener - flac.flac"
    )


def test_move_track_to_disc_changes_disc_and_track_number() -> None:
    """WHY: moving a track must update both hierarchy membership and rendered path."""
    scenario = _music_scenario(
        [
            {
                "id": "ev_move_track",
                "at": "1s",
                "action": "move_track_to_disc",
                "target": "track_1",
                "to_disc": "disc_2",
                "track_number": 3,
            }
        ]
    )
    state, entry = _apply_timeline(scenario)

    assert state.tracks["track_1"].disc_id == "disc_2"
    assert state.tracks["track_1"].track_number == 3
    assert entry.target_ids == ["track_1", "track_asset"]
    assert entry.state_delta["metadata"] == {
        "disc_id": {"before": "disc_1", "after": "disc_2"},
        "track_number": {"before": 1, "after": 3},
    }
    assert entry.state_delta["path_moves"] == [
        {
            "asset_id": "track_asset",
            "location_id": "location_0001",
            "from_path": "library/music/Artist/Album/Disc 01/01-01 - Opener - flac.flac",
            "to_path": "library/music/Artist/Album/Disc 02/02-03 - Opener - flac.flac",
        }
    ]


def test_deleted_assets_are_reported_and_not_rerendered() -> None:
    """WHY: delete-then-hierarchy must not invent a new location for missing files."""
    scenario = _series_two_asset_scenario(
        [
            {"id": "ev_delete", "at": "1s", "action": "delete_file", "target": "bonus_asset"},
            {
                "id": "ev_renumber",
                "at": "2s",
                "action": "renumber_episode",
                "target": "episode_1",
                "episode_number": 2,
            },
        ]
    )
    state, _delete_entry, entry = _apply_timeline(scenario)

    assert not state.has_location("bonus_asset")
    assert entry.target_ids == ["episode_1", "episode_asset", "bonus_asset"]
    assert entry.state_delta["skipped_deleted_asset_ids"] == ["bonus_asset"]
    assert entry.state_delta["path_moves"] == [
        {
            "asset_id": "episode_asset",
            "location_id": "location_0001",
            "from_path": (
                "library/tv/Show/Season 01/Show - S01E01 - Pilot - web - primary_video.mkv"
            ),
            "to_path": (
                "library/tv/Show/Season 01/Show - S01E02 - Pilot - web - primary_video.mkv"
            ),
        }
    ]


def test_add_file_after_delete_keeps_explicit_path_after_later_hierarchy_change() -> None:
    """WHY: re-added files have explicit paths and must not silently rejoin renderer paths."""
    scenario = _series_scenario(
        [
            {"id": "ev_delete", "at": "1s", "action": "delete_file", "target": "episode_asset"},
            {
                "id": "ev_add",
                "at": "2s",
                "action": "add_file",
                "target": "episode_asset",
                "to": "library/manual/restored.mkv",
            },
            {
                "id": "ev_renumber",
                "at": "3s",
                "action": "renumber_episode",
                "target": "episode_1",
                "episode_number": 2,
            },
        ]
    )
    state, _delete_entry, _add_entry, entry = _apply_timeline(scenario)

    loc_id = state.location_id_for_asset("episode_asset")
    assert state.locations[loc_id].path == "library/manual/restored.mkv"
    assert entry.state_delta["path_moves"] == []
    assert entry.state_delta["sidecar_moves"] == []
    assert entry.state_delta["skipped_deleted_asset_ids"] == []
