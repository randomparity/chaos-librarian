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
from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAsset,
    ManifestBundle,
    ManifestMovie,
    ManifestSidecar,
    ManifestVariant,
    ManifestVersion,
    ProbedMedia,
)
from chaos_librarian.contract.materialization import MaterializedAsset
from chaos_librarian.contract.scenario import Asset, SidecarKind
from chaos_librarian.materializer.manifest_build import (
    augment_manifest,
    augment_timeline_sidecars,
    augment_updated_sidecars,
    augment_versions,
    find_sidecar_for,
)
from chaos_librarian.materializer.phase_b.oracle_hash import collided_hash_for


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
        movies=[ManifestMovie(id="m0", title="W", layout="movie_flat")],
        series=[],
        seasons=[],
        episodes=[],
        artists=[],
        albums=[],
        discs=[],
        tracks=[],
        variants=[
            ManifestVariant(
                id="v0",
                parent_kind=ParentKind.MOVIE,
                parent_id="m0",
                label="hd",
            )
        ],
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
                kind=SidecarKind.SUBTITLE,
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


def _minimal_manifest_with_one_version(version_id: str) -> Manifest:
    """Build a minimal Manifest carrying a single ``ManifestVersion`` row."""
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        movies=[ManifestMovie(id="m0", title="W", layout="movie_flat")],
        series=[],
        seasons=[],
        episodes=[],
        artists=[],
        albums=[],
        discs=[],
        tracks=[],
        variants=[
            ManifestVariant(
                id="v0",
                parent_kind=ParentKind.MOVIE,
                parent_id="m0",
                label="hd",
            )
        ],
        bundles=[ManifestBundle(id="b0", variant_id="v0")],
        assets=[
            ManifestAsset(
                id="a0",
                bundle_id="b0",
                role="main",
                container="mkv",
                duration_seconds=1.0,
            )
        ],
        versions=[ManifestVersion(id=version_id, asset_id="a0", index=0)],
        locations=[],
        sidecars=[],
    )


def _minimal_manifest_with_one_sidecar(
    sidecar_id: str, path: str, *, language: str | None = "eng"
) -> Manifest:
    """Build a minimal Manifest carrying a single subtitle ``ManifestSidecar`` row."""
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        movies=[ManifestMovie(id="m0", title="W", layout="movie_flat")],
        series=[],
        seasons=[],
        episodes=[],
        artists=[],
        albums=[],
        discs=[],
        tracks=[],
        variants=[
            ManifestVariant(
                id="v0",
                parent_kind=ParentKind.MOVIE,
                parent_id="m0",
                label="hd",
            )
        ],
        bundles=[ManifestBundle(id="b0", variant_id="v0")],
        assets=[
            ManifestAsset(
                id="a",
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
                asset_id="a",
                kind=SidecarKind.SUBTITLE,
                path=path,
                language=language,
            )
        ],
    )


def _minimal_manifest_with_poster(sidecar_id: str, asset_id: str, path: str) -> Manifest:
    """Build a minimal Manifest carrying a single poster ``ManifestSidecar`` row."""
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        movies=[ManifestMovie(id="m0", title="W", layout="movie_flat")],
        series=[],
        seasons=[],
        episodes=[],
        artists=[],
        albums=[],
        discs=[],
        tracks=[],
        variants=[
            ManifestVariant(
                id="v0",
                parent_kind=ParentKind.MOVIE,
                parent_id="m0",
                label="hd",
            )
        ],
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
                kind=SidecarKind.POSTER,
                path=path,
                language=None,
            )
        ],
    )


def _stub_probed_media() -> ProbedMedia:
    """Minimal ProbedMedia stub for augment_versions tests."""
    return ProbedMedia(container="matroska", duration_seconds=1.0, size_bytes=100, streams=[])


def test_augment_versions_stamps_content_hash_and_probed() -> None:
    """``augment_versions`` stamps content_hash + probed onto matched version rows.

    WHY: Sprint 7 media handlers (reencode_*, remux_container, edit_metadata,
    embed_subtitle) each produce a new version row that needs its
    content_hash + probed metadata filled in after phase B. This helper
    drains the {version_id: (hash, probed)} map into the manifest.
    """
    manifest = _minimal_manifest_with_one_version("v1")
    probed = _stub_probed_media()
    augment_versions(manifest, {"v1": ("sha256:" + "a" * 64, probed)})
    version = next(v for v in manifest.versions if v.id == "v1")
    assert version.content_hash == "sha256:" + "a" * 64
    assert version.probed is probed


def test_augment_versions_ignores_unknown_ids() -> None:
    """Entries keyed on a non-existent version id leave the manifest untouched.

    WHY: phase B may legitimately register a hash for a version that was
    deleted or never made it into the manifest; defensively, the helper
    must skip such entries rather than raise.
    """
    manifest = _minimal_manifest_with_one_version("v1")
    augment_versions(manifest, {"v_missing": ("sha256:" + "a" * 64, None)})
    version = next(v for v in manifest.versions if v.id == "v1")
    assert version.content_hash is None


def test_augment_updated_sidecars_stamps_hash_and_path() -> None:
    """``augment_updated_sidecars`` stamps content_hash + path onto matched rows.

    WHY: Sprint 7 update_sidecar / extract_subtitle handlers produce new
    bytes (new hash) and possibly a new on-disk path (extract_subtitle
    writes to a new ``to`` path). This helper drains the
    {sidecar_id: (hash, path)} map into the manifest after phase B.
    """
    manifest = _minimal_manifest_with_one_sidecar("sidecar_0001", "a.eng.srt")
    augment_updated_sidecars(
        manifest,
        {"sidecar_0001": ("sha256:" + "b" * 64, "a.eng.srt")},
    )
    sidecar = next(s for s in manifest.sidecars if s.id == "sidecar_0001")
    assert sidecar.content_hash == "sha256:" + "b" * 64
    assert sidecar.path == "a.eng.srt"


def test_find_sidecar_for_poster_uses_asset_id_and_kind() -> None:
    """Non-subtitle kinds key on (asset_id, kind), ignoring language.

    WHY: poster and NFO sidecars carry ``language=None`` (manifest v4)
    and there is exactly one per asset per kind. The lookup must match
    by kind instead of by language so handlers like update_sidecar can
    locate the row to mutate.
    """
    manifest = _minimal_manifest_with_poster("sidecar_0001", "a0", "a0.poster.png")
    found = find_sidecar_for(manifest, "a0", language=None, kind=SidecarKind.POSTER)
    assert found is not None
    assert found.kind == SidecarKind.POSTER.value


def test_find_sidecar_for_subtitle_keeps_language_keyed_lookup() -> None:
    """Subtitle (default kind) still keys on (asset_id, language).

    WHY: the kind-branching refactor must not regress the existing
    subtitle path; the default ``kind="subtitle"`` keyword must reproduce
    the pre-Sprint-7 (asset_id, language) lookup unchanged.
    """
    manifest = _minimal_manifest_with_one_sidecar("sidecar_0001", "a.eng.srt", language="eng")
    found = find_sidecar_for(manifest, "a", language="eng", kind=SidecarKind.SUBTITLE)
    assert found is not None


def _collision_manifest(referent_hash: str | None) -> Manifest:
    """Two-asset manifest: referent (a1) with a stamped version, collider (a2)."""
    return Manifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        movies=[ManifestMovie(id="m0", title="W", layout="movie_flat")],
        series=[],
        seasons=[],
        episodes=[],
        artists=[],
        albums=[],
        discs=[],
        tracks=[],
        variants=[
            ManifestVariant(id="v0", parent_kind=ParentKind.MOVIE, parent_id="m0", label="hd")
        ],
        bundles=[ManifestBundle(id="b0", variant_id="v0")],
        assets=[
            ManifestAsset(
                id="a1", bundle_id="b0", role="main", container="mkv", duration_seconds=1.0
            ),
            ManifestAsset(
                id="a2", bundle_id="b0", role="main", container="mkv", duration_seconds=1.0
            ),
        ],
        versions=[
            ManifestVersion(id="ver_a1", asset_id="a1", index=0, content_hash=referent_hash),
            ManifestVersion(id="ver_a2", asset_id="a2", index=0, content_hash=None),
        ],
        locations=[],
        sidecars=[],
    )


def _materialized(asset_id: str, content_hash: str) -> MaterializedAsset:
    return MaterializedAsset(
        asset_id=asset_id,
        location_path=f"library/{asset_id}.mkv",
        content_hash=content_hash,
        size_bytes=16,
        duration_seconds=1.0,
        invocation_index=0,
    )


def _dedup_asset(
    asset_id: str,
    *,
    same_content_as: str | None = None,
    hash_collision_with: str | None = None,
    collision_prefix_len: int | None = None,
) -> Asset:
    return Asset(
        id=asset_id,
        role="main",
        container="mkv",
        duration_seconds=1.0,
        same_content_as=same_content_as,
        hash_collision_with=hash_collision_with,
        collision_prefix_len=collision_prefix_len,
    )


def _probed_media() -> ProbedMedia:
    return ProbedMedia(container="matroska", duration_seconds=1.0, size_bytes=16, streams=[])


def test_augment_manifest_stamps_real_hash_without_collision() -> None:
    real = "sha256:" + "a" * 64
    manifest = _collision_manifest(referent_hash="sha256:" + "b" * 64)
    augment_manifest(manifest, _dedup_asset("a2"), _materialized("a2", real), _probed_media(), {})
    version = next(v for v in manifest.versions if v.asset_id == "a2")
    assert version.content_hash == real


def test_augment_manifest_stamps_collided_hash() -> None:
    referent_hash = "sha256:" + "b" * 64
    real = "sha256:" + "a" * 64
    manifest = _collision_manifest(referent_hash=referent_hash)
    augment_manifest(
        manifest,
        _dedup_asset("a2", hash_collision_with="a1", collision_prefix_len=8),
        _materialized("a2", real),
        _probed_media(),
        {},
    )
    version = next(v for v in manifest.versions if v.asset_id == "a2")
    expected = collided_hash_for(referent_hash, real, 8)
    assert version.content_hash == expected
    assert version.content_hash is not None
    shared = version.content_hash.removeprefix("sha256:")[:8]
    assert shared == referent_hash.removeprefix("sha256:")[:8]
    assert version.content_hash != real


def _three_asset_manifest() -> Manifest:
    """A1 (referent), A2 (same_content_as A1), A3 (hash_collision_with A2)."""
    base = _collision_manifest(referent_hash=None)
    base.assets.append(
        ManifestAsset(id="a3", bundle_id="b0", role="main", container="mkv", duration_seconds=1.0)
    )
    base.versions.append(ManifestVersion(id="ver_a3", asset_id="a3", index=0, content_hash=None))
    return base


def test_collision_referencing_same_content_duplicate_reads_copied_hash() -> None:
    """A collision whose referent is itself a same_content_as duplicate shares the
    duplicate's *copied* full hash prefix (the one cross-feature interaction the
    spec permits)."""
    manifest = _three_asset_manifest()
    copied_hash = "sha256:" + "c" * 64  # A2's copied (== A1's) full hash
    probed = _probed_media()
    # Stamp A2 (same_content_as A1) with the copied full hash.
    augment_manifest(
        manifest,
        _dedup_asset("a2", same_content_as="a1"),
        _materialized("a2", copied_hash),
        probed,
        {},
    )
    # A3 collides with A2; its prefix must come from A2's stamped (copied) hash.
    real = "sha256:" + "d" * 64
    augment_manifest(
        manifest,
        _dedup_asset("a3", hash_collision_with="a2", collision_prefix_len=8),
        _materialized("a3", real),
        probed,
        {},
    )
    a3_hash = next(v.content_hash for v in manifest.versions if v.asset_id == "a3")
    assert a3_hash is not None
    assert a3_hash.removeprefix("sha256:")[:8] == copied_hash.removeprefix("sha256:")[:8]
    assert a3_hash != real
