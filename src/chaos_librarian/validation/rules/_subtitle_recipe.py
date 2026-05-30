"""Shared subtitle recipe matrices for the declared and timeline paths.

The declared-subtitle path (``materialize_media_matrix``) accepts srt/ass/ssa;
the timeline ``create_sidecar`` path (``create_sidecar_content``) is SRT-only in
v1 because ``_apply_create_sidecar`` does not synthesize ASS bodies. Both share
the SRT encoding set so a future encoding addition flows to both.
"""

from __future__ import annotations

from typing import Final

SRT_SUBTITLE_ENCODINGS: Final[frozenset[str]] = frozenset(
    {"utf8", "utf8_bom", "utf16_le", "iso_8859_1"}
)
_ASS_SUBTITLE_ENCODINGS: Final[frozenset[str]] = frozenset({"utf8", "utf8_bom"})

SUBTITLE_RECIPE_MATRIX: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("srt", "generated_srt"): SRT_SUBTITLE_ENCODINGS,
    ("ass", "styled_ass"): _ASS_SUBTITLE_ENCODINGS,
    ("ssa", "styled_ass"): _ASS_SUBTITLE_ENCODINGS,
}

CREATE_SIDECAR_SUBTITLE_MATRIX: Final[dict[tuple[str, str], frozenset[str]]] = {
    ("srt", "generated_srt"): SRT_SUBTITLE_ENCODINGS,
}
