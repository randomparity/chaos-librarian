"""Declared-track projection tests.

The projection turns a scenario's per-asset ``video``/``audio``/``subtitles``
declarations into a JSON-serializable map the viewer can show in plan-only
mode (where ffprobe never ran, so ``version.probed`` is absent everywhere).
"""

from __future__ import annotations

from chaos_librarian.contract.scenario import (
    Asset,
    AudioChannelLayout,
    AudioTrack,
    SubtitleCodec,
    SubtitleMode,
    SubtitleTrack,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.visualize.tracks import asset_track_rows


def _asset(**overrides: object) -> Asset:
    base: dict[str, object] = {
        "id": "a1",
        "role": "main",
        "container": "mkv",
        "duration_seconds": 1.0,
    }
    base.update(overrides)
    return Asset.model_validate(base)


def test_video_audio_subtitle_projected_in_stream_order() -> None:
    asset = _asset(
        video=VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution="1080p"),
        audio=(
            AudioTrack(codec="aac", channels=AudioChannelLayout.FIVE_ONE, language="eng"),
            AudioTrack(codec="ac3", channels=AudioChannelLayout.STEREO, language="deu"),
        ),
        subtitles=(
            SubtitleTrack(codec=SubtitleCodec.SRT, language="eng", mode=SubtitleMode.SIDECAR),
        ),
    )
    rows = asset_track_rows(asset)
    assert [r["kind"] for r in rows] == ["video", "audio", "audio", "subtitle"]
    assert rows[0] == {"kind": "video", "codec": "h264", "language": None, "detail": "1080p"}
    assert rows[1] == {"kind": "audio", "codec": "aac", "language": "eng", "detail": "5.1"}
    assert rows[2] == {"kind": "audio", "codec": "ac3", "language": "deu", "detail": "stereo"}
    assert rows[3] == {
        "kind": "subtitle",
        "codec": "srt",
        "language": "eng",
        "detail": "sidecar",
    }


def test_asset_without_tracks_projects_empty() -> None:
    assert asset_track_rows(_asset()) == []


def test_rows_are_json_native_strings() -> None:
    # StrEnum fields (channels, subtitle codec/mode) must serialize as plain
    # strings, never enum members, so json.dumps in the renderer stays clean.
    track = AudioTrack(codec="aac", channels=AudioChannelLayout.MONO, language="eng")
    (row,) = asset_track_rows(_asset(audio=(track,)))
    assert type(row["detail"]) is str
    assert type(row["codec"]) is str
