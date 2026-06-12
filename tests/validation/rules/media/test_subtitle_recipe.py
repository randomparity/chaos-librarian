"""Shared subtitle recipe matrices used by the declared and timeline paths."""

from __future__ import annotations

from chaos_librarian.contract.scenario import SubtitleCodec, SubtitleEncoding, SubtitleSource
from chaos_librarian.validation.rules.media._subtitle_recipe import (
    CREATE_SIDECAR_SUBTITLE_MATRIX,
    SRT_SUBTITLE_ENCODINGS,
    SUBTITLE_RECIPE_MATRIX,
)


def test_srt_encodings_shared() -> None:
    expected = frozenset(
        {
            SubtitleEncoding.UTF8,
            SubtitleEncoding.UTF8_BOM,
            SubtitleEncoding.UTF16_LE,
            SubtitleEncoding.ISO_8859_1,
        }
    )
    assert expected == SRT_SUBTITLE_ENCODINGS


def test_declared_matrix_still_accepts_ass() -> None:
    assert (SubtitleCodec.ASS, SubtitleSource.STYLED_ASS) in SUBTITLE_RECIPE_MATRIX
    assert (SubtitleCodec.SSA, SubtitleSource.STYLED_ASS) in SUBTITLE_RECIPE_MATRIX


def test_timeline_matrix_matches_declared_recipes() -> None:
    assert CREATE_SIDECAR_SUBTITLE_MATRIX == SUBTITLE_RECIPE_MATRIX
    assert (
        CREATE_SIDECAR_SUBTITLE_MATRIX[(SubtitleCodec.SRT, SubtitleSource.GENERATED_SRT)]
        == SRT_SUBTITLE_ENCODINGS
    )
