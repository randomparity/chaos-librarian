"""Tests for the scenario schema."""

from __future__ import annotations

from typing import cast

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import SCENARIO_SCHEMA_VERSION
from chaos_librarian.contract.profiles import FuzzProfileName
from chaos_librarian.contract.scenario import (
    AUDIO_CHANNEL_COUNTS_BY_NAME,
    FUZZ_GENERATION_PROFILE_VERSION,
    Album,
    ArchiveFileEvent,
    Artist,
    ArtistLayout,
    Asset,
    AudioChannelLayout,
    AudioSource,
    AudioTrack,
    Bundle,
    CorruptContainerHeaderEvent,
    CreateSidecarEvent,
    Disc,
    DurationScale,
    EditMetadataEvent,
    EmbedSubtitleEvent,
    Episode,
    EpisodeNaming,
    ExtractSubtitleEvent,
    Library,
    LibraryRoot,
    MoveAssetEvent,
    MoveBetweenRootsEvent,
    Movie,
    MovieLayout,
    NetworkLagCommitEvent,
    NetworkLagStartEvent,
    ReencodeAudioEvent,
    ReencodeVideoEvent,
    RemoveSidecarEvent,
    RemuxContainerEvent,
    Scenario,
    Season,
    Series,
    SeriesLayout,
    SidecarKind,
    SlowCopyCommitEvent,
    SlowCopyStartEvent,
    SubtitleMode,
    SubtitleSource,
    SubtitleTrack,
    TimelineActionName,
    Track,
    TrackNaming,
    UpdateSidecarEvent,
    Variant,
    VideoColorRange,
    VideoColorSpace,
    VideoFieldOrder,
    VideoHdrMode,
    VideoSource,
    VideoTrack,
    VideoVfrCadence,
    generation_budget_for,
)


def _minimal_scenario() -> Scenario:
    return Scenario(
        schema_version=SCENARIO_SCHEMA_VERSION,
        scenario_id="t",
        seed=1,
        duration_scale=DurationScale.SHORT,
        library=Library(roots=(LibraryRoot(id="movies_hd", path="movies-hd"),)),
        movies=(
            Movie(
                id="movie_1",
                title="Movie 1",
                layout=MovieLayout.MOVIE_FLAT,
                variants=(
                    Variant(
                        id="v1",
                        label="hd",
                        bundle=Bundle(
                            id="b1",
                            assets=(
                                Asset(
                                    id="a1",
                                    role="primary_video",
                                    container="mkv",
                                    duration_seconds=12,
                                    video=VideoTrack(
                                        source=VideoSource.MANDELBROT,
                                        codec="h264",
                                        resolution="1080p",
                                    ),
                                    audio=(
                                        AudioTrack(
                                            codec="aac",
                                            channels=AudioChannelLayout.STEREO,
                                            language="eng",
                                        ),
                                    ),
                                    subtitles=(),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
        series=(),
        artists=(),
        timeline=(),
    )


def _scenario_payload_with_event(
    event: dict[str, object], profiles: list[str] | None = None
) -> dict[str, object]:
    payload = _minimal_scenario().model_dump(mode="json")
    payload["schema_version"] = SCENARIO_SCHEMA_VERSION
    payload["profiles"] = profiles or []
    payload["timeline"] = [event]
    return payload


def _video_asset_payload(asset_id: str = "asset_main") -> dict[str, object]:
    return {
        "id": asset_id,
        "role": "feature",
        "container": "mkv",
        "duration_seconds": 60.0,
        "video": {"source": "mandelbrot", "codec": "h264", "resolution": "1080p"},
        "audio": [{"codec": "aac", "channels": "stereo", "language": "eng"}],
        "subtitles": [],
    }


def _audio_asset_payload(asset_id: str = "asset_track") -> dict[str, object]:
    return {
        "id": asset_id,
        "role": "main",
        "container": "flac",
        "duration_seconds": 180.0,
        "audio": [{"codec": "flac", "channels": "stereo", "language": "zxx"}],
        "subtitles": [],
    }


def _variant_payload(asset: dict[str, object]) -> dict[str, object]:
    return {
        "id": f"variant_{asset['id']}",
        "label": "1080p" if asset["container"] == "mkv" else "lossless",
        "bundle": {"id": f"bundle_{asset['id']}", "assets": [asset]},
    }


def _base_payload() -> dict[str, object]:
    return {
        "schema_version": SCENARIO_SCHEMA_VERSION,
        "scenario_id": "contract-hierarchy",
        "seed": 1,
        "duration_scale": "short",
        "profiles": [],
        "library": {"roots": [{"id": "primary", "path": "Library"}]},
        "movies": [],
        "series": [],
        "artists": [],
        "timeline": [],
    }


def test_minimal_scenario_roundtrip() -> None:
    s = _minimal_scenario()
    loaded = Scenario.model_validate_json(s.model_dump_json())
    assert loaded == s


def test_movie_only_scenario_v16_payload() -> None:
    payload = _base_payload()
    payload["movies"] = [
        {
            "id": "movie_orbit",
            "title": "Orbit",
            "layout": "movie_flat",
            "variants": [_variant_payload(_video_asset_payload("asset_orbit"))],
        }
    ]

    scenario = Scenario.model_validate(payload)

    assert scenario.schema_version == 16
    assert scenario.movies[0].layout is MovieLayout.MOVIE_FLAT
    assert scenario.series == ()
    assert scenario.artists == ()


def test_tv_only_scenario_accepts_season_zero_specials() -> None:
    payload = _base_payload()
    payload["series"] = [
        {
            "id": "series_starline",
            "title": "Starline",
            "layout": "season_folders",
            "episode_naming": "sxxexx_title",
            "seasons": [
                {
                    "id": "season_specials",
                    "season_number": 0,
                    "title": "Specials",
                    "episodes": [
                        {
                            "id": "episode_special_01",
                            "episode_number": 1,
                            "title": "First Signal",
                            "aired_on": "2024-05-01",
                            "absolute_number": 7,
                            "variants": [_variant_payload(_video_asset_payload("asset_special"))],
                        }
                    ],
                }
            ],
        }
    ]

    scenario = Scenario.model_validate(payload)

    assert scenario.series[0].layout is SeriesLayout.SEASON_FOLDERS
    assert scenario.series[0].episode_naming is EpisodeNaming.SXXEXX_TITLE
    assert scenario.series[0].seasons[0].season_number == 0


def test_music_only_scenario_v13_payload() -> None:
    payload = _base_payload()
    payload["artists"] = [
        {
            "id": "artist_north",
            "name": "North Index",
            "layout": "artist_album_disc",
            "track_naming": "track_number_title",
            "albums": [
                {
                    "id": "album_winter",
                    "title": "Winter Index",
                    "release_year": 2024,
                    "discs": [
                        {
                            "id": "disc_winter_01",
                            "disc_number": 1,
                            "tracks": [
                                {
                                    "id": "track_opening",
                                    "track_number": 1,
                                    "title": "Opening",
                                    "performers": ["North Index"],
                                    "variants": [_variant_payload(_audio_asset_payload())],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    scenario = Scenario.model_validate(payload)

    assert scenario.artists[0].layout is ArtistLayout.ARTIST_ALBUM_DISC
    assert scenario.artists[0].track_naming is TrackNaming.TRACK_NUMBER_TITLE
    track = scenario.artists[0].albums[0].discs[0].tracks[0]
    assert track.performers == ("North Index",)


def test_track_performers_default_to_empty_tuple() -> None:
    payload = _base_payload()
    payload["artists"] = [
        {
            "id": "artist_north",
            "name": "North Index",
            "layout": "artist_album_flat",
            "track_naming": "disc_track_number_title",
            "albums": [
                {
                    "id": "album_winter",
                    "title": "Winter Index",
                    "discs": [
                        {
                            "id": "disc_winter_01",
                            "disc_number": 1,
                            "tracks": [
                                {
                                    "id": "track_opening",
                                    "track_number": 1,
                                    "title": "Opening",
                                    "variants": [_variant_payload(_audio_asset_payload())],
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    ]

    scenario = Scenario.model_validate(payload)

    assert scenario.artists[0].albums[0].discs[0].tracks[0].performers == ()


def test_hierarchy_model_constructors_accept_tuple_fields() -> None:
    episode = Episode(
        id="episode_pilot",
        episode_number=1,
        title="Pilot",
        variants=(),
    )
    series = Series(
        id="series_starline",
        title="Starline",
        layout=SeriesLayout.SEASON_FOLDERS,
        episode_naming=EpisodeNaming.SXXEXX_TITLE,
        seasons=(Season(id="season_1", season_number=1, title="Season 1", episodes=(episode,)),),
    )
    track = Track(id="track_opening", track_number=1, title="Opening", variants=())
    artist = Artist(
        id="artist_north",
        name="North Index",
        layout=ArtistLayout.ARTIST_ALBUM_DISC,
        track_naming=TrackNaming.TRACK_NUMBER_TITLE,
        albums=(
            Album(
                id="album_winter",
                title="Winter Index",
                discs=(Disc(id="disc_1", disc_number=1, tracks=(track,)),),
            ),
        ),
    )

    assert series.seasons[0].episodes[0].id == "episode_pilot"
    assert artist.albums[0].discs[0].tracks[0].id == "track_opening"


def test_scenario_v13_rejects_works_field() -> None:
    payload = _base_payload()
    payload["works"] = [{"id": "work_old", "title": "Old", "variants": []}]

    with pytest.raises(ValidationError) as exc_info:
        Scenario.model_validate(payload)

    assert "works" in str(exc_info.value)


def test_timeline_action_discriminator() -> None:
    s = _minimal_scenario()
    s = s.model_copy(
        update={
            "timeline": (
                MoveAssetEvent(id="t1", at="2s", target="a1", to="movies-hd/X.mkv"),
                ReencodeVideoEvent(id="t2", at="5s", target="a1", resolution="sd", codec="h264"),
                SlowCopyStartEvent(
                    id="t3",
                    at="6s",
                    target="a1",
                    to="movies-hd/Final.mkv",
                    temp_path="movies-hd/Final.mkv.part",
                    duration="3s",
                ),
                SlowCopyCommitEvent(id="t4", at="9s", for_="t3"),
            )
        }
    )
    loaded = Scenario.model_validate_json(s.model_dump_json(by_alias=True))
    assert [type(e).__name__ for e in loaded.timeline] == [
        "MoveAssetEvent",
        "ReencodeVideoEvent",
        "SlowCopyStartEvent",
        "SlowCopyCommitEvent",
    ]


@pytest.mark.parametrize(
    ("event", "expected_type"),
    [
        (
            {
                "id": "ev_renumber_episode",
                "at": "1s",
                "action": "renumber_episode",
                "target": "episode_special_01",
                "episode_number": 2,
                "absolute_number": 8,
            },
            "RenumberEpisodeEvent",
        ),
        (
            {
                "id": "ev_move_episode",
                "at": "2s",
                "action": "move_episode_to_season",
                "target": "episode_special_01",
                "to_season": "season_starline_01",
                "episode_number": 1,
            },
            "MoveEpisodeToSeasonEvent",
        ),
        (
            {
                "id": "ev_rename_season",
                "at": "3s",
                "action": "rename_season",
                "target": "season_specials",
                "title": "Special Episodes",
            },
            "RenameSeasonEvent",
        ),
        (
            {
                "id": "ev_renumber_disc",
                "at": "4s",
                "action": "renumber_disc",
                "target": "disc_winter_01",
                "disc_number": 2,
            },
            "RenumberDiscEvent",
        ),
        (
            {
                "id": "ev_move_track",
                "at": "5s",
                "action": "move_track_to_disc",
                "target": "track_opening",
                "to_disc": "disc_winter_02",
                "track_number": 4,
            },
            "MoveTrackToDiscEvent",
        ),
    ],
)
def test_hierarchy_timeline_event_discriminators(
    event: dict[str, object], expected_type: str
) -> None:
    payload = _base_payload()
    payload["timeline"] = [event]

    scenario = Scenario.model_validate(payload)

    assert type(scenario.timeline[0]).__name__ == expected_type


def test_unknown_action_rejected() -> None:
    bad = _minimal_scenario().model_dump(mode="json")
    bad["timeline"] = [{"id": "t1", "at": "1s", "action": "bogus", "target": "a1"}]
    with pytest.raises(ValidationError):
        Scenario.model_validate(bad)


def test_unknown_schema_version_rejected() -> None:
    bad = _minimal_scenario().model_dump(mode="json")
    bad["schema_version"] = 999
    with pytest.raises(ValidationError):
        Scenario.model_validate(bad)


def test_slow_copy_commit_uses_for_alias() -> None:
    s = SlowCopyCommitEvent(id="c1", at="9s", for_="s1")
    blob = s.model_dump_json(by_alias=True)
    assert '"for":"s1"' in blob


def test_video_track_source_accepts_enum_values() -> None:
    """WHY: Sprint 5 narrows VideoTrack.source from str to a fixed enum.

    The schema authors must not silently typo `mandlebrot` and have it
    pass; an unknown value must raise ValidationError at parse time.
    """
    track = VideoTrack(source=VideoSource.MANDELBROT, codec="h264", resolution="hd")
    assert track.source is VideoSource.MANDELBROT


def test_video_track_source_rejects_unknown_value() -> None:
    payload = {"source": "mandlebrot", "codec": "h264", "resolution": "hd"}
    with pytest.raises(ValidationError):
        VideoTrack.model_validate(payload)


def test_audio_track_source_defaults_to_sine() -> None:
    """WHY: existing fixtures don't set AudioTrack.source; the default
    must preserve their parse without edits."""
    track = AudioTrack.model_validate({"codec": "aac", "channels": "stereo", "language": "eng"})
    assert track.source is AudioSource.SINE
    assert track.channels is AudioChannelLayout.STEREO


def test_audio_channel_layout_enum_values() -> None:
    assert AudioChannelLayout.MONO.value == "mono"
    assert AudioChannelLayout.STEREO.value == "stereo"
    assert AudioChannelLayout.TWO_ONE.value == "2.1"
    assert AudioChannelLayout.FIVE_ONE.value == "5.1"
    assert AudioChannelLayout.SEVEN_ONE.value == "7.1"
    assert AUDIO_CHANNEL_COUNTS_BY_NAME == {
        "mono": 1,
        "stereo": 2,
        "2.1": 3,
        "5.1": 6,
        "7.1": 8,
    }


def test_audio_track_channels_rejects_unknown_value() -> None:
    payload = {"codec": "aac", "channels": "quad", "language": "eng"}
    with pytest.raises(ValidationError):
        AudioTrack.model_validate(payload)


def test_reencode_audio_event_channels_reject_unknown_value() -> None:
    payload = {
        "id": "ev_ra_001",
        "at": "1s",
        "action": "reencode_audio",
        "target": "asset_main",
        "from_channels": "stereo",
        "to_channels": "quad",
    }
    with pytest.raises(ValidationError):
        ReencodeAudioEvent.model_validate(payload)


def test_subtitle_track_source_defaults_to_generated_srt() -> None:
    track = SubtitleTrack(codec="srt", language="eng", mode=SubtitleMode.SIDECAR)
    assert track.source is SubtitleSource.GENERATED_SRT


def test_video_vfr_cadence_enum_values() -> None:
    assert VideoVfrCadence.TWENTY_FOUR_TO_THIRTY.value == "24_to_30"
    assert VideoVfrCadence.THIRTY_TO_SIXTY.value == "30_to_60"
    assert VideoVfrCadence.TWENTY_FOUR_THIRTY_SIXTY.value == "24_30_60"


def test_video_track_vfr_cadence_defaults_to_none() -> None:
    track = VideoTrack.model_validate({"source": "color_bars", "codec": "h264", "resolution": "sd"})

    assert track.vfr_cadence is None


def test_video_track_accepts_supported_vfr_cadence() -> None:
    track = VideoTrack.model_validate(
        {
            "source": "color_bars",
            "codec": "h264",
            "resolution": "sd",
            "vfr_cadence": "24_to_30",
        }
    )

    assert track.vfr_cadence is VideoVfrCadence.TWENTY_FOUR_TO_THIRTY


def test_video_track_accepts_yaml_numeric_vfr_cadence() -> None:
    """WHY: YAML parses unquoted ``24_30_60`` as integer ``243060``.
    Scenario authors should not have to discover that parser edge by
    trial and error for a documented cadence value."""
    track = VideoTrack.model_validate(
        {
            "source": "color_bars",
            "codec": "h264",
            "resolution": "sd",
            "vfr_cadence": 243060,
        }
    )

    assert track.vfr_cadence is VideoVfrCadence.TWENTY_FOUR_THIRTY_SIXTY


def test_video_track_rejects_float_vfr_cadence_alias() -> None:
    payload = {
        "source": "color_bars",
        "codec": "h264",
        "resolution": "sd",
        "vfr_cadence": 243060.0,
    }

    with pytest.raises(ValidationError):
        VideoTrack.model_validate(payload)


def test_video_track_rejects_unknown_vfr_cadence() -> None:
    payload = {
        "source": "color_bars",
        "codec": "h264",
        "resolution": "sd",
        "vfr_cadence": "12_to_144",
    }

    with pytest.raises(ValidationError):
        VideoTrack.model_validate(payload)


def test_video_field_order_enum_values() -> None:
    assert VideoFieldOrder.TOP_FIELD_FIRST.value == "top_field_first"
    assert VideoFieldOrder.BOTTOM_FIELD_FIRST.value == "bottom_field_first"


def test_video_track_field_order_defaults_to_none() -> None:
    track = VideoTrack.model_validate({"source": "color_bars", "codec": "h264", "resolution": "sd"})

    assert track.field_order is None


def test_video_track_accepts_supported_field_order() -> None:
    track = VideoTrack.model_validate(
        {
            "source": "color_bars",
            "codec": "h264",
            "resolution": "sd",
            "field_order": "top_field_first",
        }
    )

    assert track.field_order is VideoFieldOrder.TOP_FIELD_FIRST


def test_video_track_rejects_unknown_field_order() -> None:
    payload = {
        "source": "color_bars",
        "codec": "h264",
        "resolution": "sd",
        "field_order": "sideways",
    }

    with pytest.raises(ValidationError):
        VideoTrack.model_validate(payload)


def test_video_color_space_enum_values() -> None:
    assert VideoColorSpace.BT601.value == "bt601"
    assert VideoColorSpace.BT709.value == "bt709"
    assert VideoColorSpace.BT2020.value == "bt2020"


def test_video_color_range_enum_values() -> None:
    assert VideoColorRange.LIMITED.value == "limited"
    assert VideoColorRange.FULL.value == "full"


def test_video_track_color_signaling_defaults_to_none() -> None:
    track = VideoTrack.model_validate({"source": "color_bars", "codec": "h264", "resolution": "sd"})

    assert track.color_space is None
    assert track.color_range is None


def test_video_track_accepts_supported_color_signaling() -> None:
    track = VideoTrack.model_validate(
        {
            "source": "color_bars",
            "codec": "h264",
            "resolution": "sd",
            "color_space": "bt709",
            "color_range": "full",
        }
    )

    assert track.color_space is VideoColorSpace.BT709
    assert track.color_range is VideoColorRange.FULL


def test_video_track_rejects_unknown_color_space() -> None:
    payload = {
        "source": "color_bars",
        "codec": "h264",
        "resolution": "sd",
        "color_space": "ntsc_j",
    }

    with pytest.raises(ValidationError):
        VideoTrack.model_validate(payload)


def test_video_track_rejects_unknown_color_range() -> None:
    payload = {
        "source": "color_bars",
        "codec": "h264",
        "resolution": "sd",
        "color_range": "wide",
    }

    with pytest.raises(ValidationError):
        VideoTrack.model_validate(payload)


def test_video_hdr_mode_enum_values() -> None:
    assert VideoHdrMode.HDR10.value == "hdr10"
    assert VideoHdrMode.HLG.value == "hlg"


def test_video_track_hdr_mode_defaults_to_none() -> None:
    track = VideoTrack.model_validate({"source": "color_bars", "codec": "hevc", "resolution": "sd"})

    assert track.hdr_mode is None


def test_video_track_accepts_supported_hdr_mode() -> None:
    track = VideoTrack.model_validate(
        {
            "source": "color_bars",
            "codec": "hevc",
            "resolution": "sd",
            "hdr_mode": "hdr10",
        }
    )

    assert track.hdr_mode is VideoHdrMode.HDR10


def test_video_track_rejects_unknown_hdr_mode() -> None:
    payload = {
        "source": "color_bars",
        "codec": "hevc",
        "resolution": "sd",
        "hdr_mode": "pqish",
    }

    with pytest.raises(ValidationError):
        VideoTrack.model_validate(payload)


def test_scenario_schema_version_is_sixteen() -> None:
    assert SCENARIO_SCHEMA_VERSION == 16


def test_scenario_accepts_profile_labels() -> None:
    payload = _minimal_scenario().model_dump(mode="json")
    payload["schema_version"] = SCENARIO_SCHEMA_VERSION
    payload["profiles"] = [
        "malformed-media",
        "performance-smoke",
        "performance-scale",
        "performance-stress",
        "network-fs-lag",
        "filesystem-artifacts",
        "negative-oracle",
        "fuzz-smoke",
        "fuzz-regression",
    ]

    scenario = Scenario.model_validate(payload)

    assert tuple(profile.value for profile in scenario.profiles) == tuple(payload["profiles"])


def test_scenario_rejects_unknown_profile_value() -> None:
    payload = _minimal_scenario().model_dump(mode="json")
    payload["schema_version"] = SCENARIO_SCHEMA_VERSION
    payload["profiles"] = ["not-a-profile"]

    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def _generated_scenario_payload() -> dict[str, object]:
    payload = _minimal_scenario().model_dump(mode="json")
    payload["schema_version"] = SCENARIO_SCHEMA_VERSION
    payload["profiles"] = ["fuzz-smoke"]
    payload["generation"] = {
        "generator": "chaos-librarian",
        "profile": "fuzz-smoke",
        "lane": "smoke",
        "profile_version": 3,
        "seed": 1,
        "budgets": {
            "movies": 3,
            "series": 0,
            "seasons": 0,
            "episodes": 0,
            "artists": 0,
            "albums": 0,
            "discs": 0,
            "tracks": 0,
            "variants": 4,
            "bundles": 4,
            "assets": 4,
            "sidecars": 8,
            "timeline_events": 12,
        },
    }
    return payload


def test_scenario_accepts_fuzz_generation_metadata() -> None:
    scenario = Scenario.model_validate(_generated_scenario_payload())

    assert scenario.generation is not None
    assert scenario.generation.generator == "chaos-librarian"
    assert scenario.generation.profile.value == "fuzz-smoke"
    assert scenario.generation.lane.value == "smoke"
    assert scenario.generation.seed == 1
    assert scenario.generation.budgets.movies == 3
    assert scenario.generation.budgets.timeline_events == 12


def test_generation_budget_uses_domain_counts() -> None:
    budget = generation_budget_for(FuzzProfileName.FUZZ_SMOKE)

    assert FUZZ_GENERATION_PROFILE_VERSION == 3
    assert budget.movies == 3
    assert budget.series == 0
    assert budget.seasons == 0
    assert budget.episodes == 0
    assert budget.artists == 0
    assert budget.albums == 0
    assert budget.discs == 0
    assert budget.tracks == 0
    assert budget.variants == 4
    assert budget.bundles == 4
    assert budget.assets == 4
    assert budget.sidecars == 8
    assert budget.timeline_events == 12
    assert not hasattr(budget, "works")


def test_scenario_accepts_fuzz_lane_metadata() -> None:
    scenario = Scenario.model_validate(_generated_scenario_payload())

    assert scenario.generation is not None
    assert scenario.generation.lane.value == "smoke"


def test_generation_lane_must_match_profile() -> None:
    payload = _generated_scenario_payload()
    generation = cast(dict[str, object], payload["generation"])
    generation["lane"] = "media-rewrite"

    with pytest.raises(ValidationError, match=r"generation\.lane"):
        Scenario.model_validate(payload)


def test_generation_lane_is_required() -> None:
    payload = _generated_scenario_payload()
    generation = cast(dict[str, object], payload["generation"])
    del generation["lane"]

    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_generation_profile_must_be_top_level_profile() -> None:
    payload = _generated_scenario_payload()
    payload["profiles"] = []

    with pytest.raises(ValidationError, match=r"generation\.profile"):
        Scenario.model_validate(payload)


def test_generation_rejects_seed_random() -> None:
    payload = _generated_scenario_payload()
    payload["seed"] = "random"

    with pytest.raises(ValidationError, match=r"generation\.seed"):
        Scenario.model_validate(payload)


def test_generation_seed_must_match_scenario_seed() -> None:
    payload = _generated_scenario_payload()
    payload["seed"] = 2

    with pytest.raises(ValidationError, match=r"generation\.seed"):
        Scenario.model_validate(payload)


def test_generation_profile_version_must_be_supported() -> None:
    payload = _generated_scenario_payload()
    generation = cast(dict[str, object], payload["generation"])
    generation["profile_version"] = 1

    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


def test_generation_budget_must_match_profile() -> None:
    payload = _generated_scenario_payload()
    generation = cast(dict[str, object], payload["generation"])
    budgets = cast(dict[str, object], generation["budgets"])
    budgets["timeline_events"] = 13

    with pytest.raises(ValidationError, match=r"generation\.budgets"):
        Scenario.model_validate(payload)


def test_network_lag_events_round_trip() -> None:
    payload = _minimal_scenario().model_dump(mode="json")
    payload["profiles"] = ["network-fs-lag"]
    payload["timeline"] = [
        {
            "id": "rename_001",
            "at": "10s",
            "action": "rename_file",
            "target": "a1",
            "to": "movies-hd/a1-renamed.mkv",
        },
        {
            "id": "lag_rename_start",
            "at": "10s",
            "action": "network_lag_start",
            "effect": "delayed_rename",
            "target": "a1",
            "after": "rename_001",
            "duration": "2s",
        },
        {
            "id": "lag_rename_commit",
            "at": "12s",
            "action": "network_lag_commit",
            "for": "lag_rename_start",
        },
    ]

    scenario = Scenario.model_validate(payload)

    assert [event.action for event in scenario.timeline] == [
        TimelineActionName.RENAME_FILE,
        TimelineActionName.NETWORK_LAG_START,
        TimelineActionName.NETWORK_LAG_COMMIT,
    ]
    assert isinstance(scenario.timeline[1], NetworkLagStartEvent)
    assert scenario.timeline[1].effect.value == "delayed_rename"
    assert scenario.timeline[1].after == "rename_001"
    assert isinstance(scenario.timeline[2], NetworkLagCommitEvent)
    assert scenario.timeline[2].for_ == "lag_rename_start"
    dumped = scenario.model_dump(mode="json", by_alias=True)
    assert dumped["timeline"][2]["for"] == "lag_rename_start"


def test_corrupt_container_header_defaults_to_64_bytes() -> None:
    event = CorruptContainerHeaderEvent.model_validate(
        {
            "id": "corrupt_header_001",
            "at": "1s",
            "action": "corrupt_container_header",
            "target": "asset_main",
        }
    )

    assert event.bytes == 64
    assert event.action == TimelineActionName.CORRUPT_CONTAINER_HEADER


def test_corrupt_container_header_rejects_zero_bytes() -> None:
    payload = {
        "id": "corrupt_header_001",
        "at": "1s",
        "action": "corrupt_container_header",
        "target": "asset_main",
        "bytes": 0,
    }

    with pytest.raises(ValidationError):
        CorruptContainerHeaderEvent.model_validate(payload)


def test_corrupt_container_header_rejects_4097_bytes() -> None:
    payload = {
        "id": "corrupt_header_001",
        "at": "1s",
        "action": "corrupt_container_header",
        "target": "asset_main",
        "bytes": 4097,
    }

    with pytest.raises(ValidationError):
        CorruptContainerHeaderEvent.model_validate(payload)


@pytest.mark.parametrize(
    "event",
    [
        {
            "id": "truncate_001",
            "at": "1s",
            "action": "truncate_file",
            "target": "a1",
            "keep_bytes": 64,
        },
        {
            "id": "packet_corrupt_001",
            "at": "2s",
            "action": "corrupt_packet_range",
            "target": "a1",
            "stream": "video",
            "packet_start": 0,
            "packet_count": 2,
        },
        {
            "id": "duration_bad_001",
            "at": "3s",
            "action": "write_invalid_duration_metadata",
            "target": "a1",
            "value": "not-a-duration",
        },
        {
            "id": "mtime_001",
            "at": "4s",
            "action": "touch_mtime",
            "target": "a1",
            "offset": "2s",
        },
        {
            "id": "wrong_hash_001",
            "at": "5s",
            "action": "wrong_oracle_hash",
            "target": "a1",
        },
    ],
)
def test_scenario_v13_accepts_interceptor_events(event: dict[str, object]) -> None:
    payload = _scenario_payload_with_event(
        event,
        profiles=["filesystem-artifacts", "negative-oracle"],
    )

    scenario = Scenario.model_validate(payload)

    assert scenario.schema_version == SCENARIO_SCHEMA_VERSION
    assert scenario.timeline[0].id == event["id"]


@pytest.mark.parametrize(
    ("event", "field_name"),
    [
        (
            {
                "id": "truncate_001",
                "at": "1s",
                "action": "truncate_file",
                "target": "a1",
                "keep_bytes": 0,
            },
            "keep_bytes",
        ),
        (
            {
                "id": "packet_corrupt_001",
                "at": "2s",
                "action": "corrupt_packet_range",
                "target": "a1",
                "stream": "video",
                "packet_start": -1,
                "packet_count": 2,
            },
            "packet_start",
        ),
        (
            {
                "id": "packet_corrupt_001",
                "at": "2s",
                "action": "corrupt_packet_range",
                "target": "a1",
                "stream": "video",
                "packet_start": 0,
                "packet_count": 0,
            },
            "packet_count",
        ),
        (
            {
                "id": "mtime_001",
                "at": "4s",
                "action": "touch_mtime",
                "target": "a1",
                "offset": "",
            },
            "offset",
        ),
    ],
)
def test_scenario_v13_rejects_invalid_interceptor_bounds(
    event: dict[str, object], field_name: str
) -> None:
    payload = _scenario_payload_with_event(event)

    with pytest.raises(ValidationError) as exc_info:
        Scenario.model_validate(payload)

    assert any(field_name in err["loc"] for err in exc_info.value.errors())


def test_wrong_oracle_hash_rejects_unexpected_bytes_field() -> None:
    payload = _scenario_payload_with_event(
        {
            "id": "wrong_hash_001",
            "at": "5s",
            "action": "wrong_oracle_hash",
            "target": "a1",
            "bytes": 64,
        }
    )

    with pytest.raises(ValidationError) as exc_info:
        Scenario.model_validate(payload)

    assert any(err["type"] == "extra_forbidden" for err in exc_info.value.errors())


def test_archive_file_event_round_trip():
    payload = {
        "id": "ev_arch_001",
        "at": "0ns",
        "action": "archive_file",
        "target": "asset_hd_main",
    }
    event = ArchiveFileEvent.model_validate(payload)
    assert event.target == "asset_hd_main"
    assert event.action == TimelineActionName.ARCHIVE_FILE
    assert event.model_dump(mode="json")["action"] == "archive_file"


def test_archive_file_event_rejects_to_field():
    payload = {
        "id": "ev_arch_001",
        "at": "0ns",
        "action": "archive_file",
        "target": "asset_hd_main",
        "to": "movies-hd/archive/asset_hd_main.mkv",
    }
    with pytest.raises(ValidationError) as exc_info:
        ArchiveFileEvent.model_validate(payload)
    assert any(err["type"] == "extra_forbidden" for err in exc_info.value.errors())


def test_move_between_roots_event_round_trip():
    payload = {
        "id": "ev_mbr_001",
        "at": "0ns",
        "action": "move_between_roots",
        "target": "asset_hd_main",
        "from_root_id": "movies-hd",
        "to_root_id": "movies-archive",
    }
    event = MoveBetweenRootsEvent.model_validate(payload)
    assert event.from_root_id == "movies-hd"
    assert event.to_root_id == "movies-archive"


def test_move_between_roots_requires_both_root_ids():
    payload = {
        "id": "ev_mbr_001",
        "at": "0ns",
        "action": "move_between_roots",
        "target": "asset_hd_main",
        "from_root_id": "movies-hd",
    }
    with pytest.raises(ValidationError) as exc_info:
        MoveBetweenRootsEvent.model_validate(payload)
    assert any(
        err["type"] == "missing" and err["loc"] == ("to_root_id",)
        for err in exc_info.value.errors()
    )


def test_library_archive_root_defaults_to_none():
    library = Library(roots=(LibraryRoot(id="movies-hd", path="library/movies-hd"),))
    assert library.archive_root is None


def test_library_archive_root_accepts_sentinel_string():
    library = Library(
        roots=(LibraryRoot(id="movies-hd", path="library/movies-hd"),),
        archive_root="archive",
    )
    assert library.archive_root == "archive"


def test_library_archive_root_accepts_real_root_id():
    library = Library(
        roots=(
            LibraryRoot(id="movies-hd", path="library/movies-hd"),
            LibraryRoot(id="staging", path="library/staging"),
        ),
        archive_root="staging",
    )
    assert library.archive_root == "staging"


def test_scenario_archive_actions_round_trip():
    payload = {
        "schema_version": SCENARIO_SCHEMA_VERSION,
        "scenario_id": "sc_arch_001",
        "seed": 42,
        "duration_scale": "short",
        "library": {
            "roots": [{"id": "movies-hd", "path": "library/movies-hd"}],
            "archive_root": None,
        },
        "movies": [],
        "series": [],
        "artists": [],
        "timeline": [
            {
                "id": "ev_arch_001",
                "at": "0ns",
                "action": "archive_file",
                "target": "asset_hd_main",
            },
        ],
    }
    scenario = Scenario.model_validate(payload)
    assert scenario.schema_version == SCENARIO_SCHEMA_VERSION
    assert scenario.timeline[0].action == TimelineActionName.ARCHIVE_FILE


def test_sidecar_kind_enum_values():
    assert SidecarKind.SUBTITLE.value == "subtitle"
    assert SidecarKind.POSTER.value == "poster"
    assert SidecarKind.NFO.value == "nfo"


def test_create_sidecar_default_kind_is_subtitle():
    payload = {
        "id": "ev_cs_001",
        "at": "1s",
        "action": "create_sidecar",
        "target": "asset_main",
        "to": "asset_main.eng.srt",
        "language": "eng",
    }
    event = CreateSidecarEvent.model_validate(payload)
    assert event.kind == SidecarKind.SUBTITLE


def test_create_sidecar_subtitle_requires_language():
    payload = {
        "id": "ev_cs_001",
        "at": "1s",
        "action": "create_sidecar",
        "target": "asset_main",
        "to": "x.srt",
        "kind": "subtitle",
    }
    with pytest.raises(ValidationError, match="subtitle sidecar requires language"):
        CreateSidecarEvent.model_validate(payload)


def test_create_sidecar_poster_forbids_language():
    payload = {
        "id": "ev_cs_001",
        "at": "1s",
        "action": "create_sidecar",
        "target": "asset_main",
        "to": "p.png",
        "kind": "poster",
        "language": "eng",
    }
    with pytest.raises(ValidationError, match="poster sidecar forbids language"):
        CreateSidecarEvent.model_validate(payload)


def test_create_sidecar_nfo_forbids_language():
    payload = {
        "id": "ev_cs_001",
        "at": "1s",
        "action": "create_sidecar",
        "target": "asset_main",
        "to": "x.nfo",
        "kind": "nfo",
        "language": "eng",
    }
    with pytest.raises(ValidationError, match="nfo sidecar forbids language"):
        CreateSidecarEvent.model_validate(payload)


def test_create_sidecar_poster_round_trip():
    payload = {
        "id": "ev_cs_001",
        "at": "1s",
        "action": "create_sidecar",
        "target": "asset_main",
        "to": "asset_main.poster.png",
        "kind": "poster",
    }
    event = CreateSidecarEvent.model_validate(payload)
    assert event.kind == SidecarKind.POSTER
    assert event.language is None


def test_remux_container_event_round_trip():
    payload = {
        "id": "ev_rmx_001",
        "at": "2s",
        "action": "remux_container",
        "target": "asset_main",
        "to_container": "mp4",
    }
    event = RemuxContainerEvent.model_validate(payload)
    assert event.to_container == "mp4"
    assert event.action == TimelineActionName.REMUX_CONTAINER


def test_edit_metadata_event_round_trip():
    payload = {
        "id": "ev_em_001",
        "at": "3s",
        "action": "edit_metadata",
        "target": "asset_main",
        "fields": {"title": "Pulsar", "artist": "x"},
    }
    event = EditMetadataEvent.model_validate(payload)
    assert event.fields == {"title": "Pulsar", "artist": "x"}


def test_edit_metadata_rejects_empty_fields():
    payload = {
        "id": "ev_em_001",
        "at": "3s",
        "action": "edit_metadata",
        "target": "asset_main",
        "fields": {},
    }
    with pytest.raises(ValidationError, match="empty"):
        EditMetadataEvent.model_validate(payload)


def test_embed_subtitle_event_round_trip():
    payload = {
        "id": "ev_es_001",
        "at": "4s",
        "action": "embed_subtitle",
        "target": "asset_main",
        "sidecar_path": "asset_main.eng.srt",
    }
    event = EmbedSubtitleEvent.model_validate(payload)
    assert event.sidecar_path == "asset_main.eng.srt"


def test_extract_subtitle_event_round_trip():
    payload = {
        "id": "ev_xs_001",
        "at": "5s",
        "action": "extract_subtitle",
        "target": "asset_main",
        "to": "asset_main.fra.srt",
        "language": "fra",
    }
    event = ExtractSubtitleEvent.model_validate(payload)
    assert event.to == "asset_main.fra.srt"
    assert event.language == "fra"


def test_remove_sidecar_event_round_trip():
    payload = {
        "id": "ev_rs_001",
        "at": "6s",
        "action": "remove_sidecar",
        "target": "asset_main",
        "sidecar_path": "asset_main.eng.srt",
    }
    event = RemoveSidecarEvent.model_validate(payload)
    assert event.target == "asset_main"
    assert event.sidecar_path == "asset_main.eng.srt"


def test_update_sidecar_event_round_trip():
    payload = {
        "id": "ev_us_001",
        "at": "7s",
        "action": "update_sidecar",
        "target": "asset_main",
        "sidecar_path": "asset_main.eng.srt",
    }
    event = UpdateSidecarEvent.model_validate(payload)
    assert event.target == "asset_main"
    assert event.sidecar_path == "asset_main.eng.srt"


def test_scenario_round_trip_with_sprint_7_events():
    payload = {
        "schema_version": SCENARIO_SCHEMA_VERSION,
        "scenario_id": "sc_s7_001",
        "seed": 42,
        "duration_scale": "short",
        "library": {"roots": [{"id": "r0", "path": "library/r0"}]},
        "movies": [],
        "series": [],
        "artists": [],
        "timeline": [
            {
                "id": "e0",
                "at": "0s",
                "action": "remux_container",
                "target": "asset_main",
                "to_container": "mp4",
            },
        ],
    }
    scenario = Scenario.model_validate(payload)
    assert scenario.schema_version == SCENARIO_SCHEMA_VERSION
    assert scenario.timeline[0].action == TimelineActionName.REMUX_CONTAINER
