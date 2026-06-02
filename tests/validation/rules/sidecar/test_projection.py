"""Tests for sidecar projection row construction."""

from __future__ import annotations

from chaos_librarian.contract.scenario import (
    SidecarKind,
    SubtitleCodec,
    SubtitleEncoding,
    SubtitleSource,
    SubtitleTimingProfile,
)
from chaos_librarian.validation.rules.sidecar.projection import (
    create_sidecar_projection_row,
    extracted_subtitle_projection_row,
)


def test_create_sidecar_projection_row_uses_subtitle_enum_fields() -> None:
    """Raw create-sidecar recipe strings should become enum members."""
    row = create_sidecar_projection_row(
        {
            "kind": "subtitle",
            "language": "jpn",
            "codec": "ass",
            "source": "styled_ass",
            "encoding": "utf8_bom",
        }
    )

    assert row is not None
    assert row.kind is SidecarKind.SUBTITLE
    assert row.language == "jpn"
    assert row.codec is SubtitleCodec.ASS
    assert row.source is SubtitleSource.STYLED_ASS
    assert row.encoding is SubtitleEncoding.UTF8_BOM
    assert row.timing_profile is SubtitleTimingProfile.NORMAL
    assert not row.uses_default_subtitle_recipe


def test_create_sidecar_projection_row_defaults_omitted_subtitle_recipe_fields() -> None:
    """Omitted create-sidecar recipe fields should use materializer defaults."""
    row = create_sidecar_projection_row(
        {
            "kind": "subtitle",
            "language": "eng",
        }
    )

    assert row is not None
    assert row.kind is SidecarKind.SUBTITLE
    assert row.codec is SubtitleCodec.SRT
    assert row.source is SubtitleSource.GENERATED_SRT
    assert row.encoding is SubtitleEncoding.UTF8
    assert row.uses_default_subtitle_recipe


def test_create_sidecar_projection_row_skips_malformed_subtitle_recipe_fields() -> None:
    """Malformed raw enum fields belong to shape validation, not projection."""
    assert (
        create_sidecar_projection_row(
            {
                "kind": "subtitle",
                "language": "eng",
                "codec": 0,
            }
        )
        is None
    )
    assert (
        create_sidecar_projection_row(
            {
                "kind": "subtitle",
                "language": "eng",
                "source": "bogus",
            }
        )
        is None
    )


def test_extracted_subtitle_projection_row_uses_default_subtitle_enums() -> None:
    """Extracted subtitles inherit the default subtitle recipe."""
    row = extracted_subtitle_projection_row({"language": "spa"})

    assert row.kind is SidecarKind.SUBTITLE
    assert row.language == "spa"
    assert row.codec is SubtitleCodec.SRT
    assert row.source is SubtitleSource.GENERATED_SRT
    assert row.encoding is SubtitleEncoding.UTF8
    assert row.timing_profile is SubtitleTimingProfile.NORMAL
    assert row.uses_default_subtitle_recipe


def test_non_subtitle_projection_row_uses_typed_kind_with_default_recipe() -> None:
    """Non-subtitle rows should still use typed sidecar kinds."""
    row = create_sidecar_projection_row({"kind": "poster", "to": "cover.png"})

    assert row is not None
    assert row.kind is SidecarKind.POSTER
    assert row.language is None
    assert row.uses_default_subtitle_recipe is False
