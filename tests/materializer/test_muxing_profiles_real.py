"""Real mkvmerge smoke tests for Matroska/WebM muxing profiles."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus
from chaos_librarian.contract.content_sources import ContentSourceCapabilities
from chaos_librarian.contract.scenario import (
    Asset,
    MatroskaMuxingProfile,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.materializer.content.synthesis import materialize_one_asset

pytestmark = pytest.mark.skipif(
    any(shutil.which(tool) is None for tool in ("ffmpeg", "ffprobe", "mkvmerge", "mkvinfo")),
    reason="ffmpeg, ffprobe, mkvmerge, and mkvinfo are required for muxing profile tests",
)


def test_materialize_mkv_no_cues_removes_cues(tmp_path: Path) -> None:
    result = materialize_one_asset(
        _asset(MatroskaMuxingProfile.NO_CUES),
        138,
        tmp_path / "run",
        _caps(),
        0,
        rendered_relative_path="r/A.mkv",
    )

    info = _mkvinfo(tmp_path / "run" / "library" / "r" / "A.mkv")

    assert "+ Cues" not in info
    assert "(KaxCues)" not in info
    assert any(source.source == "no_cues" for source in result.content_sources)


def test_materialize_mkv_dense_cues_writes_multiple_cue_points(tmp_path: Path) -> None:
    materialize_one_asset(
        _asset(MatroskaMuxingProfile.DENSE_CUES),
        138,
        tmp_path / "run",
        _caps(),
        0,
        rendered_relative_path="r/A.mkv",
    )

    assert _mkvinfo(tmp_path / "run" / "library" / "r" / "A.mkv").count("+ Cue point") > 1


def test_materialize_mkv_short_clusters_writes_multiple_clusters(tmp_path: Path) -> None:
    materialize_one_asset(
        _asset(MatroskaMuxingProfile.SHORT_CLUSTERS),
        138,
        tmp_path / "run",
        _caps(),
        0,
        rendered_relative_path="r/A.mkv",
    )

    info = _mkvinfo(tmp_path / "run" / "library" / "r" / "A.mkv")
    assert _top_level_cluster_count(info) > 1


def test_materialize_webm_short_clusters_is_probe_visible(tmp_path: Path) -> None:
    asset = _asset(MatroskaMuxingProfile.SHORT_CLUSTERS, container="webm", codec="vp9")

    result = materialize_one_asset(
        asset,
        138,
        tmp_path / "run",
        _caps(),
        0,
        rendered_relative_path="r/A.webm",
    )

    assert result.probed.container == "matroska,webm"
    assert result.probed.streams[0].codec == "vp9"
    info = _mkvinfo(tmp_path / "run" / "library" / "r" / "A.webm")
    assert _top_level_cluster_count(info) > 1


def _asset(
    profile: MatroskaMuxingProfile,
    *,
    container: str = "mkv",
    codec: str = "h264",
) -> Asset:
    return Asset(
        id="asset_muxed",
        role="main",
        container=container,
        duration_seconds=1.0,
        matroska_muxing_profile=profile,
        video=VideoTrack(source=VideoSource.COLOR_BARS, codec=codec, resolution="sd"),
    )


def _caps() -> Capabilities:
    return Capabilities(
        schema_version=7,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(
            found=True,
            version="98.0",
            path="/x/mkvmerge",
            meets_minimum=True,
        ),
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


def _mkvinfo(path: Path) -> str:
    completed = subprocess.run(
        ["mkvinfo", "--all", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def _top_level_cluster_count(info: str) -> int:
    return sum(1 for line in info.splitlines() if line.strip() == "|+ Cluster")
