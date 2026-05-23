"""Tests for the scenario schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import SCENARIO_SCHEMA_VERSION
from chaos_librarian.contract.scenario import (
    AUDIO_CHANNEL_COUNTS_BY_NAME,
    ArchiveFileEvent,
    Asset,
    AudioChannelLayout,
    AudioSource,
    AudioTrack,
    Bundle,
    CorruptContainerHeaderEvent,
    CreateSidecarEvent,
    DurationScale,
    EditMetadataEvent,
    EmbedSubtitleEvent,
    ExtractSubtitleEvent,
    Library,
    LibraryRoot,
    MoveAssetEvent,
    MoveBetweenRootsEvent,
    ReencodeAudioEvent,
    ReencodeVideoEvent,
    RemoveSidecarEvent,
    RemuxContainerEvent,
    Scenario,
    SidecarKind,
    SlowCopyCommitEvent,
    SlowCopyStartEvent,
    SubtitleMode,
    SubtitleSource,
    SubtitleTrack,
    TimelineActionName,
    UpdateSidecarEvent,
    Variant,
    VideoSource,
    VideoTrack,
    Work,
)


def _minimal_scenario() -> Scenario:
    return Scenario(
        schema_version=SCENARIO_SCHEMA_VERSION,
        scenario_id="t",
        seed=1,
        duration_scale=DurationScale.SHORT,
        library=Library(roots=(LibraryRoot(id="movies_hd", path="movies-hd"),)),
        works=(
            Work(
                id="w1",
                title="W1",
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
        timeline=(),
    )


def test_minimal_scenario_roundtrip() -> None:
    s = _minimal_scenario()
    loaded = Scenario.model_validate_json(s.model_dump_json())
    assert loaded == s


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


def test_scenario_schema_version_is_eight() -> None:
    assert SCENARIO_SCHEMA_VERSION == 8


def test_scenario_accepts_profile_labels() -> None:
    payload = _minimal_scenario().model_dump(mode="json")
    payload["schema_version"] = SCENARIO_SCHEMA_VERSION
    payload["profiles"] = [
        "malformed-media",
        "performance-smoke",
        "performance-scale",
        "performance-stress",
        "network-fs-lag",
    ]

    scenario = Scenario.model_validate(payload)

    assert tuple(profile.value for profile in scenario.profiles) == tuple(payload["profiles"])


def test_scenario_rejects_unknown_profile_value() -> None:
    payload = _minimal_scenario().model_dump(mode="json")
    payload["schema_version"] = SCENARIO_SCHEMA_VERSION
    payload["profiles"] = ["not-a-profile"]

    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)


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


def test_scenario_v4_actions_round_trip_at_v8():
    payload = {
        "schema_version": SCENARIO_SCHEMA_VERSION,
        "scenario_id": "sc_arch_001",
        "seed": 42,
        "duration_scale": "short",
        "library": {
            "roots": [{"id": "movies-hd", "path": "library/movies-hd"}],
            "archive_root": None,
        },
        "works": [],
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


def test_scenario_v8_round_trip_with_sprint_7_events():
    payload = {
        "schema_version": SCENARIO_SCHEMA_VERSION,
        "scenario_id": "sc_s7_001",
        "seed": 42,
        "duration_scale": "short",
        "library": {"roots": [{"id": "r0", "path": "library/r0"}]},
        "works": [],
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
