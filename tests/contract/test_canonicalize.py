"""Layer 4 sibling — canonicalize() strips volatile fields without losing
structural ones."""

from __future__ import annotations

from chaos_librarian.contract.canonicalize import canonicalize
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


def _manifest(*, content_hash: str | None, probed: ProbedMedia | None) -> Manifest:
    return Manifest(
        schema_version=2,
        works=[ManifestWork(id="w0", title="Title")],
        variants=[ManifestVariant(id="va0", work_id="w0", label="hd")],
        bundles=[ManifestBundle(id="b0", variant_id="va0")],
        assets=[
            ManifestAsset(
                id="a0", bundle_id="b0", role="main", container="mkv", duration_seconds=2.0
            )
        ],
        versions=[
            ManifestVersion(
                id="v0",
                asset_id="a0",
                index=0,
                content_hash=content_hash,
                probed=probed,
            )
        ],
        locations=[ManifestLocation(id="l0", asset_id="a0", path="library/w0/va0/main.mkv")],
        sidecars=[
            ManifestSidecar(
                id="s0",
                asset_id="a0",
                kind="srt",
                path="library/w0/va0/main.eng.srt",
                content_hash="sha256:" + "f" * 64,
            )
        ],
    )


def test_canonicalize_strips_content_hash_and_probed():
    """WHY: cross-toolchain hash comparison is meaningless; only the
    structural shape (works/variants/bundles/assets/versions/locations/
    sidecars + their ids and paths) is comparable."""
    left = _manifest(
        content_hash="sha256:" + "0" * 64,
        probed=ProbedMedia(
            container="matroska,webm",
            duration_seconds=2.0,
            size_bytes=12345,
            streams=[ProbedStream(kind="video", codec="h264", width=640, height=480, fps=24.0)],
        ),
    )
    right = _manifest(content_hash=None, probed=None)
    assert canonicalize(left) == canonicalize(right)


def test_canonicalize_preserves_structural_fields():
    """WHY: a too-aggressive strip would make every manifest compare equal."""
    m = _manifest(content_hash=None, probed=None)
    out = canonicalize(m)
    assert [w["id"] for w in out["works"]] == ["w0"]
    assert out["assets"][0]["container"] == "mkv"
    assert out["locations"][0]["path"] == "library/w0/va0/main.mkv"
    assert out["sidecars"][0]["path"] == "library/w0/va0/main.eng.srt"


def test_canonicalize_strips_sidecar_content_hash():
    """WHY: sidecar bytes also differ across toolchains (subtle UTF-8 BOM
    handling, newline conventions); the structural sidecar entry stays."""
    m = _manifest(content_hash=None, probed=None)
    out = canonicalize(m)
    assert "content_hash" not in out["sidecars"][0]
