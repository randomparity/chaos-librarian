"""Post-synthesis manifest mutation: stamp content_hash + probed + sidecar rows."""

from __future__ import annotations

from collections.abc import Mapping

from chaos_librarian.contract.manifest import Manifest, ManifestSidecar, ProbedMedia
from chaos_librarian.contract.materialization import MaterializedAsset
from chaos_librarian.contract.scenario import Asset, SidecarKind

__all__ = [
    "augment_manifest",
    "augment_timeline_sidecars",
    "augment_updated_sidecars",
    "augment_versions",
    "find_sidecar_for",
]


def augment_manifest(
    manifest: Manifest,
    asset: Asset,
    materialized: MaterializedAsset,
    probed: ProbedMedia,
    sidecar_hashes: dict[tuple[str, str], str],
    *,
    skip_languages: frozenset[str] = frozenset(),
) -> None:
    """Stamp ``content_hash`` + ``probed`` onto the version record and
    update ``ManifestSidecar`` rows for materialized declared sidecars.

    ``build_initial_state`` seeds one ``ManifestSidecar`` per declared
    sidecar-mode subtitle into ``state.sidecars`` (Sprint 7), so the
    serialized manifest already carries the row. Materialize then stamps
    the phase-A ``content_hash`` onto the existing row. If the engine
    consumed the declared subtitle (``embed_subtitle`` / ``remove_sidecar``
    drop the row from ``state.sidecars``), the row is no longer in
    ``manifest.sidecars`` and we deliberately do NOT re-add it — the
    engine's removal is authoritative.

    ``skip_languages`` mirrors the same kwarg on ``write_sidecars``:
    languages a timeline ``create_sidecar`` will produce are skipped here
    so the manifest carries the timeline row (with the engine-allocated
    sidecar_id), not a phase-A row that would be hidden by the manifest
    v3 ``(asset_id, language)`` uniqueness collapse.

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
        if sub.language in skip_languages:
            continue
        key = (asset.id, sub.language)
        content_hash = sidecar_hashes.get(key)
        if content_hash is None:
            continue
        existing = find_sidecar_for(manifest, asset.id, language=sub.language)
        if existing is not None:
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


def augment_versions(
    manifest: Manifest,
    post_phase_b_versions: Mapping[str, tuple[str, ProbedMedia | None]],
) -> None:
    """Stamp ``content_hash`` + ``probed`` onto every version whose id is in the map.

    Sprint 7 wiring: each successful media handler (``reencode_*``,
    ``remux_container``, ``edit_metadata``, ``embed_subtitle``) registers
    its new version's ``content_hash`` + ``probed`` here; this function
    drains the map into the manifest. Version ids not present in the map
    are left untouched, and entries keyed on ids that aren't in the
    manifest are silently ignored (defensive against deleted rows).
    """
    for version in manifest.versions:
        entry = post_phase_b_versions.get(version.id)
        if entry is None:
            continue
        content_hash, probed = entry
        version.content_hash = content_hash
        version.probed = probed


def augment_updated_sidecars(
    manifest: Manifest,
    post_phase_b_sidecars: Mapping[str, tuple[str, str]],
) -> None:
    """Stamp ``content_hash`` + ``path`` on sidecar rows touched by update / extract.

    Mirrors ``augment_timeline_sidecars`` shape (Sprint 6) but for the
    Sprint 7 ``update_sidecar`` / ``extract_subtitle`` outputs. Maps
    ``sidecar_id -> (content_hash, path)`` — ``extract_subtitle`` writes
    to a new ``to`` path so the path is part of the mutation.
    """
    for sidecar in manifest.sidecars:
        entry = post_phase_b_sidecars.get(sidecar.id)
        if entry is None:
            continue
        content_hash, path = entry
        sidecar.content_hash = content_hash
        sidecar.path = path


def find_sidecar_for(
    manifest: Manifest,
    asset_id: str,
    *,
    language: str | None = None,
    kind: SidecarKind = SidecarKind.SUBTITLE,
) -> ManifestSidecar | None:
    """Return the ``ManifestSidecar`` matching ``(asset_id, language, kind)`` or ``None``.

    Subtitle (default): keyed by ``(asset_id, language)``. Other kinds
    (``poster``, ``nfo``): keyed by ``(asset_id, kind)`` — one poster per
    asset, one NFO per asset. ``language`` is ``None`` for non-subtitle
    kinds (manifest v4 made the field optional precisely so poster/NFO
    rows don't need to fabricate a language tag).
    """
    for sidecar in manifest.sidecars:
        if sidecar.asset_id != asset_id:
            continue
        if kind is SidecarKind.SUBTITLE:
            if sidecar.kind == SidecarKind.SUBTITLE.value and sidecar.language == language:
                return sidecar
        elif sidecar.kind == kind.value:
            return sidecar
    return None
