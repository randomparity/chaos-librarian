"""Import-asset contract: ImportSource exclusivity, shape, subtitle body.

Why: issue #105 adds scenario-bundled file-reference assets (ADR 0012). An
import asset materializes by copying the referenced bundle file, so it must
declare no synthesis tracks/knobs (the bytes carry the properties) and must
not combine with the existing content-link fields. The v33 contract also
widens ``CreateSidecarEvent.body`` to subtitle kind so imported ``.srt``
text survives byte-exact.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaos_librarian.contract.scenario import Asset, CreateSidecarEvent, ImportSource


def _import_asset_payload(**overrides):
    payload = {
        "id": "imp-abc",
        "role": "main",
        "container": "mkv",
        "duration_seconds": 12.5,
        "import_source": {"path": "media/abc.mkv"},
    }
    payload.update(overrides)
    return payload


def test_import_source_roundtrip():
    asset = Asset.model_validate(_import_asset_payload())
    assert asset.import_source == ImportSource(path="media/abc.mkv")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("video", {"source": "mandelbrot", "codec": "h264", "resolution": "sd"}),
        ("mp4_moov_placement", "moov_at_start"),
        ("matroska_muxing_profile", "no_cues"),
        ("embedded_chapters", {"count": 3}),
        ("embedded_cover_art", {"image_format": "png"}),
    ],
)
def test_import_asset_forbids_synthesis_knobs(field, value):
    payload = _import_asset_payload(**{field: value})
    with pytest.raises(ValidationError, match="import_source asset forbids"):
        Asset.model_validate(payload)


def test_import_asset_forbids_tracks():
    payload = _import_asset_payload(
        audio=[{"codec": "aac", "channels": "stereo", "language": "en"}]
    )
    with pytest.raises(ValidationError, match="import_source asset forbids"):
        Asset.model_validate(payload)


def test_import_asset_forbids_declared_subtitles():
    payload = _import_asset_payload(
        subtitles=[
            {
                "source": "generated_srt",
                "codec": "srt",
                "language": "en",
                "mode": "sidecar",
            }
        ]
    )
    with pytest.raises(ValidationError, match="import_source asset forbids"):
        Asset.model_validate(payload)


def test_import_source_mutually_exclusive_with_links():
    payload = _import_asset_payload(same_content_as="other-asset")
    with pytest.raises(ValidationError, match="mutually exclusive"):
        Asset.model_validate(payload)


def test_non_import_asset_still_allows_tracks():
    payload = {
        "id": "syn-1",
        "role": "main",
        "container": "mkv",
        "duration_seconds": 5.0,
        "video": {"source": "mandelbrot", "codec": "h264", "resolution": "sd"},
    }
    asset = Asset.model_validate(payload)
    assert asset.import_source is None


def test_subtitle_sidecar_event_accepts_body():
    event = CreateSidecarEvent.model_validate(
        {
            "id": "ev1",
            "at": "0s",
            "target": "imp-abc",
            "to": "Movie.en.srt",
            "language": "en",
            "kind": "subtitle",
            "codec": "srt",
            "body": "1\n00:00:00,000 --> 00:00:01,000\nhi\n",
        }
    )
    assert event.body == "1\n00:00:00,000 --> 00:00:01,000\nhi\n"


def test_poster_sidecar_event_still_forbids_body():
    payload = {
        "id": "ev2",
        "at": "0s",
        "target": "imp-abc",
        "to": "poster.png",
        "kind": "poster",
        "body": "x",
    }
    with pytest.raises(ValidationError, match="body is only valid"):
        CreateSidecarEvent.model_validate(payload)
