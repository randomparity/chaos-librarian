"""Authored disposition intent must survive validation and media production."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import Asset, AudioTrack, SubtitleTrack
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.preparation.preflight import preflight_asset


def feature_asset(**updates: object) -> Asset:
    payload: dict[str, object] = {
        "id": "a_flags",
        "role": "main",
        "container": "mkv",
        "duration_seconds": 0.2,
        "video": {"source": "color_bars", "codec": "h264", "resolution": "sd"},
        "audio": [
            {
                "codec": "aac",
                "channels": "stereo",
                "language": "eng",
                "default": True,
                "forced": False,
            }
        ]
        * 2,
        "subtitles": [
            {"codec": "srt", "language": "eng", "mode": "embedded", "default": True, "forced": True}
        ]
        * 2,
    }
    payload.update(updates)
    return Asset.model_validate(payload)


def test_flags_roundtrip_distinguishes_false_from_unspecified() -> None:
    asset = feature_asset()
    restored = Asset.model_validate_json(asset.model_dump_json())
    assert [(s.default, s.forced) for s in restored.subtitles] == [(True, True)] * 2
    assert restored.audio[0].forced is False
    assert (
        AudioTrack.model_validate({"codec": "aac", "channels": "stereo", "language": "eng"}).default
        is None
    )
    assert (
        SubtitleTrack.model_validate({"codec": "srt", "language": "eng", "mode": "sidecar"}).forced
        is None
    )


def test_typed_preflight_accepts_complete_feature() -> None:
    preflight_asset(parent_kind=ParentKind.MOVIE, asset=feature_asset())


@pytest.mark.parametrize(
    "updates",
    [
        {"duration_seconds": 31},
        {"duration_seconds": float("inf")},
        {"container": "mp4"},
        {"embedded_chapters": {"count": 2}},
        {"video": {"source": "color_bars", "codec": "h264", "resolution": "hd"}},
        {"matroska_muxing_profile": "no_cues"},
    ],
)
def test_typed_preflight_rejects_unsupported_asset_context(updates: dict[str, object]) -> None:
    with pytest.raises(UnsupportedMaterializationError):
        preflight_asset(parent_kind=ParentKind.MOVIE, asset=feature_asset(**updates))


def test_typed_preflight_rejects_partial_flags_and_ninth_track() -> None:
    asset = feature_asset()
    for audio in (asset.audio * 5, (asset.audio[0].model_copy(update={"forced": None}),)):
        with pytest.raises(UnsupportedMaterializationError):
            preflight_asset(
                parent_kind=ParentKind.MOVIE, asset=asset.model_copy(update={"audio": audio})
            )


def test_typed_preflight_accepts_maximum_tracks_and_duration() -> None:
    asset = feature_asset(duration_seconds=30)
    preflight_asset(
        parent_kind=ParentKind.MOVIE,
        asset=asset.model_copy(update={"audio": asset.audio * 4, "subtitles": asset.subtitles * 4}),
    )
