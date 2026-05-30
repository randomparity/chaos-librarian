"""CUE sidecar kind on the create_sidecar event (#118)."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.scenario import CreateSidecarEvent, SidecarKind


def test_cue_sidecar_accepts_body_and_forbids_language() -> None:
    event = CreateSidecarEvent.model_validate(
        {
            "id": "e1",
            "at": "0s",
            "target": "asset-1",
            "to": "Album/album.cue",
            "kind": "cue",
            "body": 'FILE "a.flac" WAVE\n  TRACK 01 AUDIO',
        }
    )
    assert event.kind is SidecarKind.CUE
    assert event.body is not None


def test_cue_sidecar_default_body_is_none() -> None:
    event = CreateSidecarEvent.model_validate(
        {"id": "e1", "at": "0s", "target": "asset-1", "to": "a.cue", "kind": "cue"}
    )
    assert event.kind is SidecarKind.CUE
    assert event.body is None


def test_cue_sidecar_rejects_language() -> None:
    with pytest.raises(ValueError, match="cue sidecar forbids language"):
        CreateSidecarEvent.model_validate(
            {
                "id": "e1",
                "at": "0s",
                "target": "asset-1",
                "to": "a.cue",
                "kind": "cue",
                "language": "en",
            }
        )


def test_cue_sidecar_rejects_subtitle_codec() -> None:
    with pytest.raises(ValueError, match="only valid for subtitle"):
        CreateSidecarEvent.model_validate(
            {
                "id": "e1",
                "at": "0s",
                "target": "asset-1",
                "to": "a.cue",
                "kind": "cue",
                "codec": "srt",
            }
        )
