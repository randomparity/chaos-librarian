"""Tests for the scenario schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import SCENARIO_SCHEMA_VERSION
from chaos_librarian.contract.scenario import (
    ArchiveFileEvent,
    Asset,
    AudioSource,
    AudioTrack,
    Bundle,
    DurationScale,
    Library,
    LibraryRoot,
    MoveAssetEvent,
    MoveBetweenRootsEvent,
    ReencodeVideoEvent,
    Scenario,
    SlowCopyCommitEvent,
    SlowCopyStartEvent,
    SubtitleMode,
    SubtitleSource,
    SubtitleTrack,
    TimelineActionName,
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
                                            channels="stereo",
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
    track = AudioTrack(codec="aac", channels="stereo", language="eng")
    assert track.source is AudioSource.SINE


def test_subtitle_track_source_defaults_to_generated_srt() -> None:
    track = SubtitleTrack(codec="srt", language="eng", mode=SubtitleMode.SIDECAR)
    assert track.source is SubtitleSource.GENERATED_SRT


def test_scenario_schema_version_is_four() -> None:
    assert SCENARIO_SCHEMA_VERSION == 4


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


def test_scenario_v4_round_trip_with_new_events():
    payload = {
        "schema_version": 4,
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
    assert scenario.schema_version == 4
    assert scenario.timeline[0].action == TimelineActionName.ARCHIVE_FILE
