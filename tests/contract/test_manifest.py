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
    ManifestVariant,
    ManifestVersion,
    ManifestWork,
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
