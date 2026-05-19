"""Per-entity report builders.

``build_report_set`` is a pure function: it takes the initial manifest,
the current manifest, and the journal, and returns a ``ReportSet`` of
sorted, immutable report tuples. Both ``run_plan`` (after the timeline
loop) and ``step_fixture`` (after each advance) call it; neither owns
any persistence — see ``engine/writer.py`` for that.

Iteration order is lexicographic on id so report files are bit-identical
for the same logical state.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestBundle,
    ManifestLocation,
    ManifestVariant,
    ManifestVersion,
    ManifestWork,
)
from chaos_librarian.contract.reports import (
    AssetHistoryEntry,
    AssetReport,
    AssetSnapshot,
    BundleReport,
    VariantReport,
    WorkReport,
)
from chaos_librarian.errors import ChaosLibrarianValueError


@dataclass(frozen=True)
class ReportSet:
    """Sorted, immutable bundle of every per-entity report a fixture emits."""

    assets: tuple[AssetReport, ...]
    works: tuple[WorkReport, ...]
    variants: tuple[VariantReport, ...]
    bundles: tuple[BundleReport, ...]


def build_report_set(
    *,
    initial: Manifest,
    current: Manifest,
    journal: Iterable[JournalEntry],
) -> ReportSet:
    """Derive per-entity reports from manifest + journal state.

    Args:
        initial: The initial manifest emitted at ``t=0``.
        current: The manifest reflecting the state after the journal's
            last entry.
        journal: Every journal entry in the run so far. Iterated once.

    Returns:
        ``ReportSet`` sorted lexicographically by id within each tuple.
    """
    journal_list = list(journal)
    assets = tuple(
        sorted(
            (
                _build_asset_report(asset.id, initial, current, journal_list)
                for asset in initial.assets
            ),
            key=lambda a: a.asset_id,
        )
    )
    works = tuple(
        sorted(
            (_build_work_report(w, initial) for w in initial.works),
            key=lambda r: r.work_id,
        )
    )
    variants = tuple(
        sorted(
            (_build_variant_report(v, initial) for v in initial.variants),
            key=lambda r: r.variant_id,
        )
    )
    bundles = tuple(
        sorted(
            (_build_bundle_report(b, initial, current) for b in initial.bundles),
            key=lambda r: r.bundle_id,
        )
    )
    return ReportSet(assets=assets, works=works, variants=variants, bundles=bundles)


def _snapshot_for(asset_id: str, manifest: Manifest) -> AssetSnapshot | None:
    version = _find_by_asset_id(asset_id, manifest.versions)
    if version is None:
        return None
    location = _find_by_asset_id(asset_id, manifest.locations)
    if location is None:
        return None
    return AssetSnapshot(
        location_path=location.path,
        version_id=version.id,
        version_index=version.index,
    )


def _find_by_asset_id[T: ManifestVersion | ManifestLocation](
    asset_id: str, items: list[T]
) -> T | None:
    """Linear search by ``asset_id`` over a manifest sub-collection."""
    for item in items:
        if item.asset_id == asset_id:
            return item
    return None


def _build_asset_report(
    asset_id: str,
    initial: Manifest,
    current: Manifest,
    journal: list[JournalEntry],
) -> AssetReport:
    initial_snapshot = _snapshot_for(asset_id, initial)
    if initial_snapshot is None:
        raise ChaosLibrarianValueError(f"asset {asset_id} missing from initial manifest")
    history = [
        AssetHistoryEntry(
            logical_time_ns=entry.logical_time_ns,
            event_id=entry.event_id,
            action=entry.action,
            state_delta=dict(entry.state_delta),
        )
        for entry in journal
        if asset_id in entry.target_ids
    ]
    return AssetReport(
        schema_version=2,
        asset_id=asset_id,
        initial=initial_snapshot,
        history=history,
        current=_snapshot_for(asset_id, current),
    )


def _build_work_report(work: ManifestWork, initial: Manifest) -> WorkReport:
    variant_ids = sorted(v.id for v in initial.variants if v.work_id == work.id)
    asset_ids: list[str] = []
    for v in initial.variants:
        if v.work_id != work.id:
            continue
        for b in initial.bundles:
            if b.variant_id != v.id:
                continue
            asset_ids.extend(a.id for a in initial.assets if a.bundle_id == b.id)
    return WorkReport(
        schema_version=1,
        work_id=work.id,
        title=work.title,
        variant_ids=variant_ids,
        asset_ids=sorted(asset_ids),
    )


def _build_variant_report(variant: ManifestVariant, initial: Manifest) -> VariantReport:
    bundle = next(
        (b for b in initial.bundles if b.variant_id == variant.id),
        None,
    )
    if bundle is None:
        raise ChaosLibrarianValueError(f"variant {variant.id} has no bundle")
    asset_ids = sorted(a.id for a in initial.assets if a.bundle_id == bundle.id)
    return VariantReport(
        schema_version=1,
        variant_id=variant.id,
        work_id=variant.work_id,
        label=variant.label,
        bundle_id=bundle.id,
        asset_ids=asset_ids,
    )


def _build_bundle_report(
    bundle: ManifestBundle, initial: Manifest, current: Manifest
) -> BundleReport:
    asset_ids = sorted(a.id for a in initial.assets if a.bundle_id == bundle.id)
    asset_id_set = set(asset_ids)
    sidecar_ids = sorted(s.id for s in current.sidecars if s.asset_id in asset_id_set)
    return BundleReport(
        schema_version=1,
        bundle_id=bundle.id,
        variant_id=bundle.variant_id,
        asset_ids=asset_ids,
        sidecar_ids=sidecar_ids,
    )
