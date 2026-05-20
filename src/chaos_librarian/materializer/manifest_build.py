"""Post-synthesis manifest mutation: stamp content_hash + probed + sidecar rows."""

from __future__ import annotations

from collections.abc import Mapping

from chaos_librarian.contract.manifest import Manifest, ManifestSidecar, ProbedMedia
from chaos_librarian.contract.materialization import MaterializedAsset
from chaos_librarian.contract.scenario import Asset

__all__ = ["augment_manifest", "augment_timeline_sidecars", "find_sidecar_for"]


def augment_manifest(
    manifest: Manifest,
    asset: Asset,
    materialized: MaterializedAsset,
    probed: ProbedMedia,
    sidecar_hashes: dict[tuple[str, str], str],
) -> None:
    """Stamp ``content_hash`` + ``probed`` onto the version record and
    append/update ``ManifestSidecar`` rows for materialized sidecars.

    The engine does not pre-populate sidecars from ``scenario.subtitles``
    (sidecars there are added only via ``create_sidecar`` timeline events).
    Materialize must reflect the materialized sidecars in the manifest so
    consumers see the bytes they were promised; we append one
    ``ManifestSidecar`` per materialized language with a deterministic id
    derived from the asset and language.

    ``probed`` is passed in by ``materialize_one_asset`` (which already
    ran ffprobe on the absolute output path). Re-probing via
    ``probe_file(Path(materialized.location_path))`` would dispatch
    against a run-dir-relative string and either miss the file or resolve
    against an unrelated local ``library/`` from the CLI cwd.
    """
    for version in manifest.versions:
        if version.asset_id == asset.id:
            version.content_hash = materialized.content_hash
            version.probed = probed
            break
    for sub in asset.subtitles:
        key = (asset.id, sub.language)
        content_hash = sidecar_hashes.get(key)
        if content_hash is None:
            continue
        sidecar_path = f"library/{asset.id}.{sub.language}.srt"
        existing = find_sidecar_for(manifest, asset.id, sub.language)
        if existing is None:
            manifest.sidecars.append(
                ManifestSidecar(
                    id=f"sidecar_{asset.id}_{sub.language}",
                    asset_id=asset.id,
                    kind=sub.codec,
                    path=sidecar_path,
                    language=sub.language,
                    content_hash=content_hash,
                )
            )
        else:
            existing.content_hash = content_hash


def augment_timeline_sidecars(
    manifest: Manifest, phase_b_sidecar_hashes: Mapping[str, str]
) -> None:
    """Stamp ``content_hash`` on timeline-created sidecar rows by ``sidecar_id``.

    Sprint 5's ``augment_manifest`` covers declared subtitles (keyed by
    ``(asset_id, language)``); Sprint 6's timeline-created sidecars need
    a separate path because the engine handler allocates a fresh
    ``sidecar_id`` and the bytes are hashed inside phase B, not phase A.

    Rows whose ``id`` is not present in ``phase_b_sidecar_hashes`` are
    left unchanged — declared subtitles stay at their phase-A hash, and
    timeline sidecars whose hash didn't make it into the map (impossible
    in practice; defensive) keep ``content_hash=None``.
    """
    for sidecar in manifest.sidecars:
        content_hash = phase_b_sidecar_hashes.get(sidecar.id)
        if content_hash is not None:
            sidecar.content_hash = content_hash


def find_sidecar_for(manifest: Manifest, asset_id: str, language: str) -> ManifestSidecar | None:
    """Return the ``ManifestSidecar`` for ``(asset_id, language)``, or ``None``.

    Matches on the explicit ``language`` field (manifest v3+). The previous
    substring-match on ``sidecar.path`` (``language in path``) mis-resolved
    whenever one language tag appeared as a substring of another (e.g.
    looking up ``"en"`` would match a ``"library/x.eng.srt"`` row). The
    field is required from v3 so every row has a comparable key.
    """
    for sidecar in manifest.sidecars:
        if sidecar.asset_id == asset_id and sidecar.language == language:
            return sidecar
    return None
