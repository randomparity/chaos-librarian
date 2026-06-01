"""Shared subtitle recipe matrices used by the declared and timeline paths."""

from __future__ import annotations

from chaos_librarian.validation.rules.media._subtitle_recipe import (
    CREATE_SIDECAR_SUBTITLE_MATRIX,
    SRT_SUBTITLE_ENCODINGS,
    SUBTITLE_RECIPE_MATRIX,
)


def test_srt_encodings_shared() -> None:
    expected = frozenset({"utf8", "utf8_bom", "utf16_le", "iso_8859_1"})
    assert expected == SRT_SUBTITLE_ENCODINGS


def test_declared_matrix_still_accepts_ass() -> None:
    assert ("ass", "styled_ass") in SUBTITLE_RECIPE_MATRIX
    assert ("ssa", "styled_ass") in SUBTITLE_RECIPE_MATRIX


def test_timeline_matrix_is_srt_only() -> None:
    assert set(CREATE_SIDECAR_SUBTITLE_MATRIX) == {("srt", "generated_srt")}
    assert CREATE_SIDECAR_SUBTITLE_MATRIX[("srt", "generated_srt")] == SRT_SUBTITLE_ENCODINGS
