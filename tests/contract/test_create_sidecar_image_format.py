"""Poster image_format selector on create_sidecar (#118)."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.scenario import CreateSidecarEvent, PosterImageFormat


def test_poster_accepts_image_format() -> None:
    event = CreateSidecarEvent.model_validate(
        {
            "id": "e1",
            "at": "0s",
            "target": "a",
            "to": "cover.webp",
            "kind": "poster",
            "image_format": "webp",
        }
    )
    assert event.image_format is PosterImageFormat.WEBP


def test_poster_image_format_defaults_none() -> None:
    event = CreateSidecarEvent.model_validate(
        {"id": "e1", "at": "0s", "target": "a", "to": "cover.png", "kind": "poster"}
    )
    assert event.image_format is None


def test_image_format_rejected_on_nfo() -> None:
    with pytest.raises(ValueError, match="image_format is only valid for poster"):
        CreateSidecarEvent.model_validate(
            {
                "id": "e1",
                "at": "0s",
                "target": "a",
                "to": "x.nfo",
                "kind": "nfo",
                "image_format": "png",
            }
        )


def test_image_format_rejected_with_video_media_type() -> None:
    with pytest.raises(ValueError, match="image_format cannot be combined with media_type"):
        CreateSidecarEvent.model_validate(
            {
                "id": "e1",
                "at": "0s",
                "target": "a",
                "to": "cover.png",
                "kind": "poster",
                "image_format": "png",
                "media_type": "video",
            }
        )
