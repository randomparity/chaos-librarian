"""Tests for the materializer preflight gate.

The action-set gate admits every timeline action the current materializer can
execute. Unsupported actions must raise ``TimelineUnsupportedError`` before
phase A allocates a run-dir.
"""

from __future__ import annotations

import pytest

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    AudioChannelLayout,
    AudioTrack,
    Scenario,
    SubtitleCodec,
    SubtitleEncoding,
    SubtitleMode,
    SubtitleSource,
    SubtitleTimingProfile,
    SubtitleTrack,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.materializer.errors import (
    TimelineUnsupportedError,
    UnsupportedMaterializationError,
)
from chaos_librarian.materializer.preflight import (
    SUPPORTED_S6_ACTIONS,
    SUPPORTED_S10_ACTIONS,
    preflight_asset,
    preflight_timeline,
)


def _scenario_with_timeline(events: list[tuple[str, str, dict]]) -> Scenario:
    """Build a minimal v4 Scenario whose timeline carries ``events``.

    Each entry is ``(action, target, extra_fields)``; ``extra_fields`` is
    merged into the event dict before validation. Event ids are
    auto-generated as ``ev_0001``, ``ev_0002``, ...  and times are
    monotonic (``0ns``, ``1ns``, ...).
    """
    timeline = [
        {
            "id": f"ev_{index + 1:04d}",
            "at": f"{index}ns",
            "action": action,
            "target": target,
            **extra,
        }
        for index, (action, target, extra) in enumerate(events)
    ]
    return Scenario.model_validate(
        {
            "schema_version": 25,
            "scenario_id": "preflight-test",
            "seed": 1,
            "duration_scale": "short",
            "library": {
                "roots": [
                    {"id": "movies-hd", "path": "library/movies-hd"},
                    {"id": "cold-storage", "path": "library/cold-storage"},
                ],
            },
            "movies": [
                {
                    "id": "movie_001",
                    "title": "Test Movie",
                    "layout": "movie_flat",
                    "variants": [
                        {
                            "id": "variant_001",
                            "label": "default",
                            "bundle": {
                                "id": "bundle_001",
                                "assets": [
                                    {
                                        "id": "asset_hd_main",
                                        "role": "primary_video",
                                        "container": "mkv",
                                        "duration_seconds": 1,
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
            "series": [],
            "artists": [],
            "timeline": timeline,
        }
    )


def test_preflight_timeline_accepts_supported_actions() -> None:
    """WHY: the Sprint 6 matrix permits these eight actions; preflight
    must let them through so phase B can execute them."""
    scenario = _scenario_with_timeline(
        [
            ("move_asset", "asset_hd_main", {"to": "movies-hd/new.mkv"}),
            ("rename_file", "asset_hd_main", {"to": "movies-hd/renamed.mkv"}),
            ("archive_file", "asset_hd_main", {}),
            (
                "move_between_roots",
                "asset_hd_main",
                {"from_root_id": "movies-hd", "to_root_id": "cold-storage"},
            ),
        ]
    )
    preflight_timeline(scenario)  # should not raise


def test_preflight_timeline_accepts_delete_then_add_file() -> None:
    """WHY: ``add_file`` is restoration after a prior delete. Preflight
    must allow the pair through so Phase B can restore the deleted bytes."""
    scenario = _scenario_with_timeline(
        [
            ("delete_file", "asset_hd_main", {}),
            ("add_file", "asset_hd_main", {"to": "movies-hd/new.mkv"}),
        ]
    )
    preflight_timeline(scenario)


def test_preflight_timeline_empty_timeline_accepted() -> None:
    """WHY: static scenarios remain valid materialize targets in Sprint 6;
    the action-set gate is a no-op when there are no events."""
    scenario = _scenario_with_timeline([])
    preflight_timeline(scenario)


def test_supported_s6_actions_includes_add_file_and_excludes_reencodes() -> None:
    """WHY: current stdlib materialize support includes restoration via
    ``add_file``. Media mutations stay outside this set because media.py
    owns their dispatch."""
    supported_values = {a.value for a in SUPPORTED_S6_ACTIONS}
    assert "add_file" in supported_values
    assert "reencode_video" not in supported_values
    assert "reencode_audio" not in supported_values
    assert len(SUPPORTED_S6_ACTIONS) == 9


@pytest.mark.parametrize(
    ("action_name", "extra_fields"),
    [
        ("remux_container", {"to_container": "mp4"}),
        ("edit_metadata", {"fields": {"k": "v"}}),
        ("embed_subtitle", {"sidecar_path": "a0.eng.srt"}),
        ("extract_subtitle", {"to": "a0.fra.srt", "language": "fra"}),
        ("remove_sidecar", {"sidecar_path": "a0.eng.srt"}),
        ("update_sidecar", {"sidecar_path": "a0.eng.srt"}),
    ],
)
def test_preflight_timeline_accepts_sprint_7_actions(
    action_name: str, extra_fields: dict[str, object]
) -> None:
    """WHY: Sprint 7 widens the gate to allow the six new media/sidecar
    actions; preflight must let each one through so phase B's media and
    stdlib dispatchers can execute it."""
    scenario = _scenario_with_timeline([(action_name, "asset_hd_main", extra_fields)])
    preflight_timeline(scenario)  # should not raise


def test_preflight_accepts_corrupt_container_header() -> None:
    scenario = _scenario_with_timeline(
        [("corrupt_container_header", "asset_hd_main", {"bytes": 64})]
    )

    preflight_timeline(scenario)


def test_preflight_accepts_malformed_media_corruption_actions() -> None:
    scenario = _scenario_with_timeline(
        [
            ("truncate_file", "asset_hd_main", {"keep_bytes": 64}),
            (
                "corrupt_packet_range",
                "asset_hd_main",
                {"stream": "video", "packet_start": 0, "packet_count": 2},
            ),
            (
                "write_invalid_duration_metadata",
                "asset_hd_main",
                {"value": "not-a-duration"},
            ),
        ]
    )

    preflight_timeline(scenario)


def test_preflight_accepts_touch_mtime_for_filesystem_dispatch() -> None:
    scenario = _scenario_with_timeline([("touch_mtime", "asset_hd_main", {"offset": "2s"})])

    preflight_timeline(scenario)


def test_preflight_accepts_wrong_oracle_hash() -> None:
    scenario = _scenario_with_timeline([("wrong_oracle_hash", "asset_hd_main", {})])

    preflight_timeline(scenario)


@pytest.mark.parametrize(
    ("action_name", "extra_fields"),
    [
        ("renumber_episode", {"episode_number": 2}),
        ("move_episode_to_season", {"to_season": "season_2", "episode_number": 1}),
        ("rename_season", {"title": "Renamed"}),
        ("renumber_disc", {"disc_number": 2}),
        ("move_track_to_disc", {"to_disc": "disc_2", "track_number": 3}),
    ],
)
def test_preflight_timeline_accepts_hierarchy_actions(
    action_name: str, extra_fields: dict[str, object]
) -> None:
    scenario = _scenario_with_timeline([(action_name, "hierarchy_target", extra_fields)])
    preflight_timeline(scenario)


def test_supported_s10_actions_exported_from_preflight() -> None:
    assert "corrupt_container_header" in {action.value for action in SUPPORTED_S10_ACTIONS}
    assert "wrong_oracle_hash" in {action.value for action in SUPPORTED_S10_ACTIONS}


def test_preflight_timeline_rejects_network_lag_for_materialize() -> None:
    scenario = _scenario_with_timeline(
        [
            (
                "network_lag_start",
                "asset_hd_main",
                {
                    "effect": "delayed_rename",
                    "after": "rename_001",
                    "duration": "1ns",
                },
            )
        ]
    )

    with pytest.raises(TimelineUnsupportedError):
        preflight_timeline(scenario)


def test_preflight_timeline_accepts_network_lag_for_run() -> None:
    scenario = _scenario_with_timeline(
        [
            (
                "network_lag_start",
                "asset_hd_main",
                {
                    "effect": "delayed_rename",
                    "after": "rename_001",
                    "duration": "1ns",
                },
            )
        ]
    )

    preflight_timeline(scenario, allow_network_lag=True)


def test_preflight_accepts_supported_subtitle_recipes() -> None:
    preflight_asset(
        parent_kind=ParentKind.MOVIE,
        video=VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution="sd"),
        audios=[AudioTrack(codec="aac", channels=AudioChannelLayout.STEREO, language="eng")],
        subtitles=[
            SubtitleTrack(
                codec=SubtitleCodec.ASS,
                source=SubtitleSource.STYLED_ASS,
                language="jpn",
                mode=SubtitleMode.SIDECAR,
            ),
            SubtitleTrack(
                codec=SubtitleCodec.SRT,
                language="eng",
                mode=SubtitleMode.SIDECAR,
                encoding=SubtitleEncoding.UTF16_LE,
                timing_profile=SubtitleTimingProfile.OVERLAP,
            ),
        ],
        container="mkv",
    )


def test_preflight_rejects_ass_utf16_encoding() -> None:
    with pytest.raises(UnsupportedMaterializationError) as exc_info:
        preflight_asset(
            parent_kind=ParentKind.MOVIE,
            video=VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution="sd"),
            audios=[],
            subtitles=[
                SubtitleTrack(
                    codec=SubtitleCodec.ASS,
                    source=SubtitleSource.STYLED_ASS,
                    language="jpn",
                    mode=SubtitleMode.SIDECAR,
                    encoding=SubtitleEncoding.UTF16_LE,
                )
            ],
            container="mkv",
        )

    assert exc_info.value.field == "subtitle[0].encoding"
