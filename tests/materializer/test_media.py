"""Tests for materializer/media.py."""

from __future__ import annotations

import pytest

from chaos_librarian.materializer.media import (
    _MediaContext,
    _subtitle_codec_for_container,
)


def test_subtitle_codec_mkv_uses_srt():
    assert _subtitle_codec_for_container("mkv") == "srt"


def test_subtitle_codec_webm_uses_srt():
    assert _subtitle_codec_for_container("webm") == "srt"


def test_subtitle_codec_mp4_uses_mov_text():
    assert _subtitle_codec_for_container("mp4") == "mov_text"


def test_subtitle_codec_m4v_uses_mov_text():
    assert _subtitle_codec_for_container("m4v") == "mov_text"


def test_subtitle_codec_mov_uses_mov_text():
    assert _subtitle_codec_for_container("mov") == "mov_text"


def test_subtitle_codec_unsupported_container_raises():
    with pytest.raises(ValueError, match="unsupported"):
        _subtitle_codec_for_container("ogg")


def test_media_context_construction(tmp_path):
    ctx = _MediaContext(
        library_root=tmp_path,
        scenario_assets={},
        resolved_seed=42,
        ffmpeg_version="7.0",
        ffprobe_version="7.0",
        post_phase_b_versions={},
        post_phase_b_sidecars={},
        invocations=[],
    )
    assert ctx.library_root == tmp_path
    assert ctx.resolved_seed == 42
    assert ctx.post_phase_b_versions == {}
