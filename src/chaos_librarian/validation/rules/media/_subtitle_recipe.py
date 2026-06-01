"""Shared subtitle recipe matrices for the declared and timeline paths.

The declared-subtitle path (``materialize_media_matrix``) accepts srt/ass/ssa;
the timeline ``create_sidecar`` path (``create_sidecar_content``) is SRT-only in
v1 because ``_apply_create_sidecar`` does not synthesize ASS bodies. Both share
the SRT encoding set so a future encoding addition flows to both.
"""

from __future__ import annotations

from typing import Final

from chaos_librarian.contract.scenario import (
    SubtitleCodec,
    SubtitleEncoding,
    SubtitleSource,
)

SRT_SUBTITLE_ENCODINGS: Final[frozenset[SubtitleEncoding]] = frozenset(
    {
        SubtitleEncoding.UTF8,
        SubtitleEncoding.UTF8_BOM,
        SubtitleEncoding.UTF16_LE,
        SubtitleEncoding.ISO_8859_1,
    }
)
_ASS_SUBTITLE_ENCODINGS: Final[frozenset[SubtitleEncoding]] = frozenset(
    {SubtitleEncoding.UTF8, SubtitleEncoding.UTF8_BOM}
)

SUBTITLE_RECIPE_MATRIX: Final[
    dict[tuple[SubtitleCodec, SubtitleSource], frozenset[SubtitleEncoding]]
] = {
    (SubtitleCodec.SRT, SubtitleSource.GENERATED_SRT): SRT_SUBTITLE_ENCODINGS,
    (SubtitleCodec.ASS, SubtitleSource.STYLED_ASS): _ASS_SUBTITLE_ENCODINGS,
    (SubtitleCodec.SSA, SubtitleSource.STYLED_ASS): _ASS_SUBTITLE_ENCODINGS,
}

CREATE_SIDECAR_SUBTITLE_MATRIX: Final[
    dict[tuple[SubtitleCodec, SubtitleSource], frozenset[SubtitleEncoding]]
] = {
    (SubtitleCodec.SRT, SubtitleSource.GENERATED_SRT): SRT_SUBTITLE_ENCODINGS,
}
