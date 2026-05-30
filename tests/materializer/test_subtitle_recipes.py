"""Tests for declared subtitle recipe rendering."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.scenario import (
    SubtitleCodec,
    SubtitleEncoding,
    SubtitleSource,
    SubtitleTimingProfile,
)
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.tooling.subtitles import subtitle_payload_bytes


def test_srt_utf8_bom_payload_starts_with_bom() -> None:
    body = subtitle_payload_bytes(
        codec=SubtitleCodec.SRT,
        source=SubtitleSource.GENERATED_SRT,
        encoding=SubtitleEncoding.UTF8_BOM,
        timing_profile=SubtitleTimingProfile.NORMAL,
        language="eng",
        duration_s=2.0,
        seed=42,
    )

    assert body.startswith(b"\xef\xbb\xbf")
    assert b"00:00:02,000" in body


def test_srt_utf16_le_payload_starts_with_bom() -> None:
    body = subtitle_payload_bytes(
        codec=SubtitleCodec.SRT,
        source=SubtitleSource.GENERATED_SRT,
        encoding=SubtitleEncoding.UTF16_LE,
        timing_profile=SubtitleTimingProfile.NORMAL,
        language="eng",
        duration_s=2.0,
        seed=42,
    )

    assert body.startswith(b"\xff\xfe")
    assert "chaos-librarian".encode("utf-16-le") in body


def test_srt_iso_8859_1_payload_is_latin1() -> None:
    body = subtitle_payload_bytes(
        codec=SubtitleCodec.SRT,
        source=SubtitleSource.GENERATED_SRT,
        encoding=SubtitleEncoding.ISO_8859_1,
        timing_profile=SubtitleTimingProfile.NORMAL,
        language="fra",
        duration_s=2.0,
        seed=42,
    )

    assert body.decode("iso-8859-1").startswith("1\n")


def test_srt_iso_8859_1_non_latin1_language_raises_unsupported() -> None:
    # The language is embedded in the cue text; a non-Latin-1 language under
    # ISO-8859-1 must surface as a structured error, not a raw UnicodeEncodeError.
    with pytest.raises(UnsupportedMaterializationError) as exc_info:
        subtitle_payload_bytes(
            codec=SubtitleCodec.SRT,
            source=SubtitleSource.GENERATED_SRT,
            encoding=SubtitleEncoding.ISO_8859_1,
            timing_profile=SubtitleTimingProfile.NORMAL,
            language="日本語",
            duration_s=2.0,
            seed=42,
        )
    assert exc_info.value.field == "subtitle.encoding"


def test_srt_overlap_payload_has_overlapping_cues() -> None:
    body = subtitle_payload_bytes(
        codec=SubtitleCodec.SRT,
        source=SubtitleSource.GENERATED_SRT,
        encoding=SubtitleEncoding.UTF8,
        timing_profile=SubtitleTimingProfile.OVERLAP,
        language="eng",
        duration_s=2.0,
        seed=42,
    ).decode("utf-8")

    assert "00:00:00,000 --> 00:00:01,000" in body
    assert "00:00:00,500 --> 00:00:02,000" in body


def test_srt_out_of_range_payload_exceeds_asset_duration() -> None:
    body = subtitle_payload_bytes(
        codec=SubtitleCodec.SRT,
        source=SubtitleSource.GENERATED_SRT,
        encoding=SubtitleEncoding.UTF8,
        timing_profile=SubtitleTimingProfile.OUT_OF_RANGE,
        language="eng",
        duration_s=2.0,
        seed=42,
    ).decode("utf-8")

    assert "00:00:00,000 --> 00:00:32,000" in body


def test_ass_payload_contains_style_and_position_tags() -> None:
    body = subtitle_payload_bytes(
        codec=SubtitleCodec.ASS,
        source=SubtitleSource.STYLED_ASS,
        encoding=SubtitleEncoding.UTF8,
        timing_profile=SubtitleTimingProfile.OVERLAP,
        language="jpn",
        duration_s=2.0,
        seed=42,
    ).decode("utf-8")

    assert "[V4+ Styles]" in body
    assert "Style: ChaosDefault" in body
    assert r"{\pos(" in body
    assert body.count("Dialogue:") == 2


def test_ssa_payload_uses_v4_styles_section() -> None:
    body = subtitle_payload_bytes(
        codec=SubtitleCodec.SSA,
        source=SubtitleSource.STYLED_ASS,
        encoding=SubtitleEncoding.UTF8_BOM,
        timing_profile=SubtitleTimingProfile.OUT_OF_RANGE,
        language="spa",
        duration_s=1.0,
        seed=42,
    )

    decoded = body.decode("utf-8-sig")
    assert "[V4 Styles]" in decoded
    assert "0:00:31.00" in decoded
