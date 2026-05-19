"""Tests for the manifest schema."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import MANIFEST_SCHEMA_VERSION
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAsset,
    ManifestBundle,
    ManifestLocation,
    ManifestSidecar,
    ManifestVariant,
    ManifestVersion,
    ManifestWork,
    ProbedMedia,
    ProbedStream,
)


def _empty_manifest() -> Manifest:
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        works=[],
        variants=[],
        bundles=[],
        assets=[],
        versions=[],
        locations=[],
        sidecars=[],
    )


def test_empty_manifest_roundtrip() -> None:
    m = _empty_manifest()
    loaded = Manifest.model_validate_json(m.model_dump_json())
    assert loaded == m


def test_populated_manifest_roundtrip() -> None:
    m = Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        works=[ManifestWork(id="w1", title="W1")],
        variants=[ManifestVariant(id="v1", work_id="w1", label="hd")],
        bundles=[ManifestBundle(id="b1", variant_id="v1")],
        assets=[
            ManifestAsset(
                id="a1",
                bundle_id="b1",
                role="primary_video",
                container="mkv",
                duration_seconds=12,
            )
        ],
        versions=[ManifestVersion(id="ver1", asset_id="a1", index=0)],
        locations=[ManifestLocation(id="loc1", asset_id="a1", path="movies-hd/A.mkv")],
        sidecars=[],
    )
    loaded = Manifest.model_validate_json(m.model_dump_json())
    assert loaded == m


def test_rejects_unknown_schema_version() -> None:
    bad = _empty_manifest().model_dump(mode="json")
    bad["schema_version"] = 999
    with pytest.raises(ValidationError):
        Manifest.model_validate(bad)


def test_probed_stream_video_only_fields():
    """WHY: Stream subtype fields (width/height/fps for video, channels for
    audio, default/forced for subtitle) must coexist on one model so the
    same `streams[]` array can hold heterogeneous entries from ffprobe."""
    stream = ProbedStream(kind="video", codec="h264", width=1920, height=1080, fps=24.0)
    assert stream.channels is None
    assert stream.sample_rate is None


def test_probed_media_round_trip():
    media = ProbedMedia(
        container="matroska,webm",
        duration_seconds=2.0,
        size_bytes=12345,
        streams=[
            ProbedStream(kind="video", codec="h264", width=640, height=480, fps=24.0),
            ProbedStream(kind="audio", codec="aac", channels=2, sample_rate=48000),
        ],
    )
    payload = media.model_dump_json(exclude_none=True)
    loaded = ProbedMedia.model_validate_json(payload)
    assert loaded == media


def test_manifest_version_probed_defaults_none():
    """WHY: plan-only manifests must stay bit-identical post-v2 bump.
    The default None plus exclude_none=True in the writer guarantees that."""
    version = ManifestVersion(id="v0", asset_id="a0", index=0)
    payload = version.model_dump(exclude_none=True)
    assert "probed" not in payload
    assert "content_hash" not in payload


def test_manifest_sidecar_content_hash_optional():
    sidecar = ManifestSidecar(
        id="s0", asset_id="a0", kind="srt", path="library/a/0.eng.srt", language="eng"
    )
    assert sidecar.content_hash is None
    payload = sidecar.model_dump(exclude_none=True)
    assert "content_hash" not in payload


def test_manifest_schema_version_is_three():
    assert MANIFEST_SCHEMA_VERSION == 3
