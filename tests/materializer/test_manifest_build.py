"""Tests for ``augment_timeline_sidecars``.

Sprint 5's ``augment_manifest`` stamps ``content_hash`` on declared
subtitle sidecars (keyed on ``(asset_id, language)`` after the materializer
hashes their bytes during phase A). Sprint 6's timeline-created sidecars
are allocated a fresh ``sidecar_id`` by the engine handler and hashed
inside phase B; ``augment_timeline_sidecars`` is the symmetric path that
stamps those rows by ``sidecar_id`` after phase B returns.
"""

from __future__ import annotations

from chaos_librarian.contract import MANIFEST_SCHEMA_VERSION
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAsset,
    ManifestBundle,
    ManifestSidecar,
    ManifestVariant,
    ManifestWork,
)
from chaos_librarian.materializer.manifest_build import augment_timeline_sidecars


def _build_manifest_with_sidecar(
    *,
    sidecar_id: str,
    asset_id: str,
    language: str,
    path: str,
    content_hash: str | None,
) -> Manifest:
    """Build a minimal Manifest carrying a single ``ManifestSidecar`` row.

    The work/variant/bundle/asset scaffolding is the bare minimum required
    by the Manifest contract; only the sidecar row matters for these tests.
    """
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        works=[ManifestWork(id="w0", title="W")],
        variants=[ManifestVariant(id="v0", work_id="w0", label="hd")],
        bundles=[ManifestBundle(id="b0", variant_id="v0")],
        assets=[
            ManifestAsset(
                id=asset_id,
                bundle_id="b0",
                role="main",
                container="mkv",
                duration_seconds=1.0,
            )
        ],
        versions=[],
        locations=[],
        sidecars=[
            ManifestSidecar(
                id=sidecar_id,
                asset_id=asset_id,
                kind="srt",
                path=path,
                language=language,
                content_hash=content_hash,
            )
        ],
    )


def test_augment_timeline_sidecars_stamps_hash_on_matching_row() -> None:
    """A timeline-created sidecar row gets its phase-B hash stamped by sidecar_id.

    WHY: the engine handler for ``create_sidecar`` allocates a fresh
    ``sidecar_id`` and adds a ``ManifestSidecar`` row with
    ``content_hash=None``; phase B hashes the rendered bytes and returns
    a ``{sidecar_id: sha256}`` map. This function is what closes the loop
    by stamping the hash onto the row before the manifest is written.
    """
    manifest = _build_manifest_with_sidecar(
        sidecar_id="sidecar_0001",
        asset_id="asset_hd_main",
        language="en",
        path="movies-hd/asset_hd_main.en.srt",
        content_hash=None,
    )
    fake_hash = "sha256:" + ("abc123" * 10 + "abc1")  # 64-char fake sha, prefixed
    augment_timeline_sidecars(
        manifest,
        {"sidecar_0001": fake_hash},
    )
    sidecar = next(s for s in manifest.sidecars if s.id == "sidecar_0001")
    assert sidecar.content_hash == fake_hash


def test_augment_timeline_sidecars_leaves_unmatched_rows_alone() -> None:
    """Declared sidecars (whose content_hash was populated by augment_manifest)
    must not be touched by augment_timeline_sidecars.

    WHY: the two augment helpers operate on disjoint row sets. Declared
    subtitles are hashed in phase A and stamped by ``augment_manifest``
    keyed on ``(asset_id, language)``; timeline sidecars are hashed in
    phase B and stamped here keyed on ``sidecar_id``. A timeline row's
    sidecar_id won't appear in a declared row, so iterating the hash map
    must never overwrite a declared row's existing hash.
    """
    declared_hash = "sha256:" + "d" * 64
    timeline_hash = "sha256:" + "t" * 64
    manifest = _build_manifest_with_sidecar(
        sidecar_id="sidecar_declared",
        asset_id="asset_hd_main",
        language="en",
        path="asset_hd_main.en.srt",
        content_hash=declared_hash,
    )
    augment_timeline_sidecars(manifest, {"sidecar_timeline": timeline_hash})
    sidecar = next(s for s in manifest.sidecars if s.id == "sidecar_declared")
    assert sidecar.content_hash == declared_hash


def test_augment_timeline_sidecars_empty_dict_noop() -> None:
    """An empty hash map leaves every sidecar row untouched.

    WHY: scenarios without any ``create_sidecar`` (or ``rotate_subtitle``)
    timeline events produce an empty phase-B sidecar-hash map; the
    function must accept that cleanly without mutating anything.
    """
    existing_hash = "sha256:" + "e" * 64
    manifest = _build_manifest_with_sidecar(
        sidecar_id="sidecar_existing",
        asset_id="asset_hd_main",
        language="en",
        path="asset_hd_main.en.srt",
        content_hash=existing_hash,
    )
    augment_timeline_sidecars(manifest, {})
    sidecar = next(s for s in manifest.sidecars if s.id == "sidecar_existing")
    assert sidecar.content_hash == existing_hash
