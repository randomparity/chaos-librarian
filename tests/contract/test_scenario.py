"""Tests for the scenario schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import SCENARIO_SCHEMA_VERSION
from chaos_librarian.contract.scenario import (
    Asset,
    AudioTrack,
    Bundle,
    Library,
    LibraryRoot,
    MoveAssetEvent,
    ReencodeVideoEvent,
    Scenario,
    SlowCopyCommitEvent,
    SlowCopyStartEvent,
    SubtitleTrack,  # noqa: F401  -- verifies public re-export of subtitle track type
    Variant,
    VideoTrack,
    Work,
)


def _minimal_scenario() -> Scenario:
    return Scenario(
        schema_version=SCENARIO_SCHEMA_VERSION,
        scenario_id="t",
        seed=1,
        duration_scale="short",
        library=Library(roots=[LibraryRoot(id="movies_hd", path="movies-hd")]),
        works=[
            Work(
                id="w1",
                title="W1",
                variants=[
                    Variant(
                        id="v1",
                        label="hd",
                        bundle=Bundle(
                            id="b1",
                            assets=[
                                Asset(
                                    id="a1",
                                    role="primary_video",
                                    container="mkv",
                                    duration_seconds=12,
                                    video=VideoTrack(
                                        source="mandelbrot",
                                        codec="h264",
                                        resolution="1080p",
                                    ),
                                    audio=[
                                        AudioTrack(
                                            codec="aac",
                                            channels="stereo",
                                            language="eng",
                                        )
                                    ],
                                    subtitles=[],
                                )
                            ],
                        ),
                    )
                ],
            )
        ],
        timeline=[],
    )


def test_minimal_scenario_roundtrip() -> None:
    s = _minimal_scenario()
    loaded = Scenario.model_validate_json(s.model_dump_json())
    assert loaded == s


def test_timeline_action_discriminator() -> None:
    s = _minimal_scenario()
    s = s.model_copy(
        update={
            "timeline": [
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
            ]
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
