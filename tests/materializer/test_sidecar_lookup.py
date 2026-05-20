"""Regression tests for ``find_sidecar_for`` after the manifest v3 bump.

Issue #13: pre-v3 ``find_sidecar_for`` keyed on a substring match
(``language in sidecar.path``) which mis-resolved whenever one language
tag was a substring of another (e.g. ``"en"`` matching
``"library/x.eng.srt"``). v3 adds an explicit ``language`` field on
``ManifestSidecar`` and the lookup now compares on that field directly.
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
from chaos_librarian.materializer.manifest_build import find_sidecar_for


def _manifest_with_sidecars(*sidecars: ManifestSidecar) -> Manifest:
    """A minimal Manifest carrying just the sidecars under test."""
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        works=[ManifestWork(id="w0", title="W")],
        variants=[ManifestVariant(id="v0", work_id="w0", label="hd")],
        bundles=[ManifestBundle(id="b0", variant_id="v0")],
        assets=[
            ManifestAsset(
                id="a0", bundle_id="b0", role="main", container="mkv", duration_seconds=1.0
            )
        ],
        versions=[],
        locations=[],
        sidecars=list(sidecars),
    )


def test_lookup_distinguishes_substring_colliding_languages() -> None:
    """``en`` and ``eng`` are distinct keys even though one is a substring of the other.

    WHY: this is the exact pre-v3 failure mode. A substring path-match on
    ``"en"`` would have matched ``library/a0.eng.srt`` and returned the
    wrong sidecar; the materializer would have stamped ``content_hash``
    onto the eng row when the caller meant the en row. The v3 schema's
    explicit ``language`` field rules this out by construction.
    """
    en = ManifestSidecar(
        id="sidecar_a0_en",
        asset_id="a0",
        kind="srt",
        path="library/a0.en.srt",
        language="en",
    )
    eng = ManifestSidecar(
        id="sidecar_a0_eng",
        asset_id="a0",
        kind="srt",
        path="library/a0.eng.srt",
        language="eng",
    )
    manifest = _manifest_with_sidecars(en, eng)

    assert find_sidecar_for(manifest, "a0", "en") is en
    assert find_sidecar_for(manifest, "a0", "eng") is eng


def test_lookup_filters_by_asset_id() -> None:
    """Two assets can independently carry the same language tag."""
    a0_en = ManifestSidecar(
        id="sidecar_a0_en",
        asset_id="a0",
        kind="srt",
        path="library/a0.en.srt",
        language="en",
    )
    a1_en = ManifestSidecar(
        id="sidecar_a1_en",
        asset_id="a1",
        kind="srt",
        path="library/a1.en.srt",
        language="en",
    )
    manifest = _manifest_with_sidecars(a0_en, a1_en)

    assert find_sidecar_for(manifest, "a0", "en") is a0_en
    assert find_sidecar_for(manifest, "a1", "en") is a1_en
