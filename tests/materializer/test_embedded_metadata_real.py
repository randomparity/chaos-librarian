"""Real FFmpeg smoke tests for embedded chapters and cover art."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.content_sources import ContentSourceCapabilities, ContentTrackKind
from chaos_librarian.contract.scenario import (
    Asset,
    AudioChannelLayout,
    AudioSource,
    AudioTrack,
    EmbeddedChapters,
    EmbeddedCoverArt,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.materializer.content.synthesis import materialize_one_asset

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg and ffprobe are required for real embedded metadata smoke tests",
)


def test_materialize_mp4_embedded_metadata_is_probe_visible(tmp_path: Path) -> None:
    asset = Asset(
        id="asset_embed_mp4",
        role="main",
        container="mp4",
        duration_seconds=1.0,
        embedded_chapters=EmbeddedChapters(count=2, title_prefix="Scene"),
        embedded_cover_art=EmbeddedCoverArt(),
        video=VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution="sd"),
        audio=(
            AudioTrack(
                source=AudioSource.SINE,
                codec="aac",
                channels=AudioChannelLayout.STEREO,
                language="eng",
            ),
        ),
    )

    result = materialize_one_asset(
        asset,
        137,
        tmp_path / "run",
        _caps(),
        0,
        rendered_relative_path="r/Embedded.mp4",
    )

    assert len(result.probed.chapters) == 2
    assert result.probed.chapters[0].title is not None
    assert result.probed.chapters[0].title.startswith("Scene 01 ")
    assert any(stream.attached_pic is True for stream in result.probed.streams)
    assert {source.track_kind for source in result.content_sources} >= {
        ContentTrackKind.CHAPTERS,
        ContentTrackKind.COVER_ART,
    }


def test_materialize_mkv_embedded_chapters_are_probe_visible(tmp_path: Path) -> None:
    asset = Asset(
        id="asset_embed_mkv",
        role="main",
        container="mkv",
        duration_seconds=1.0,
        embedded_chapters=EmbeddedChapters(count=2, title_prefix="Scene"),
        video=VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution="sd"),
        audio=(
            AudioTrack(
                source=AudioSource.SINE,
                codec="aac",
                channels=AudioChannelLayout.STEREO,
                language="eng",
            ),
        ),
    )

    result = materialize_one_asset(
        asset,
        137,
        tmp_path / "run",
        _caps(),
        0,
        rendered_relative_path="r/Embedded.mkv",
    )

    assert len(result.probed.chapters) == 2
    assert [chapter.start_ms for chapter in result.probed.chapters] == [0, 500]
    assert result.probed.chapters[1].title is not None
    assert result.probed.chapters[1].title.startswith("Scene 02 ")


def _caps() -> Capabilities:
    return Capabilities(
        schema_version=7,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        content_sources=ContentSourceCapabilities(),
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=False,
            materialize_hevc_video=True,
            materialize_hdr_video=True,
            materialize_resolution_switch_video=True,
            materialize_audio_recipes=True,
            materialize_matroska_muxing_profiles=True,
            materialize_webm_video=True,
        ),
    )
