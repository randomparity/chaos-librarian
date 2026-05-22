"""Normalized evidence indexes for adapter matching."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from chaos_librarian.adapter.fixture import OracleFixture
from chaos_librarian.contract.manifest import ManifestSidecar, ProbedMedia
from chaos_librarian.contract.observed_state import (
    ObservedAsset,
    ObservedEvent,
    ObservedPathHistoryEntry,
    ObservedSidecar,
    ObservedState,
)
from chaos_librarian.contract.reports import PathHistoryEntry


@dataclass(frozen=True)
class OracleAssetView:
    asset_id: str
    bundle_id: str
    current_path: str | None
    content_hash: str | None
    probed: ProbedMedia | None
    path_history: tuple[PathHistoryEntry, ...]
    sidecars: tuple[ManifestSidecar, ...]


@dataclass(frozen=True)
class ObservedAssetView:
    observed_ref: str
    current_path: str | None
    content_hash: str | None
    probed: ProbedMedia | None
    work_ref: str | None
    variant_ref: str | None
    bundle_ref: str | None
    sidecars: tuple[ObservedSidecar, ...]
    path_history: tuple[ObservedPathHistoryEntry, ...]


@dataclass(frozen=True)
class OracleTopologyView:
    asset_id: str
    bundle_id: str
    variant_id: str
    work_id: str
    work_title: str | None
    variant_label: str | None
    bundle_asset_ids: tuple[str, ...]


@dataclass(frozen=True)
class ObservedTopologyView:
    observed_ref: str
    bundle_ref: str | None
    variant_ref: str | None
    work_ref: str | None
    work_title: str | None
    variant_label: str | None
    bundle_asset_refs: tuple[str, ...]


@dataclass(frozen=True)
class OracleIndex:
    assets: Mapping[str, OracleAssetView]
    topology: Mapping[str, OracleTopologyView] = field(default_factory=dict)
    current_path_to_asset_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    historical_path_to_asset_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    hash_to_asset_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    topology_key_to_asset_ids: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_views(
        cls,
        *,
        assets: Sequence[OracleAssetView],
        topology: Sequence[OracleTopologyView] = (),
    ) -> OracleIndex:
        asset_map = {asset.asset_id: asset for asset in assets}
        topology_map = {view.asset_id: view for view in topology}
        return cls(
            assets=asset_map,
            topology=topology_map,
            current_path_to_asset_ids=_lookup_by(
                assets,
                id_of=lambda asset: asset.asset_id,
                keys_of=lambda asset: (asset.current_path,),
            ),
            historical_path_to_asset_ids=_lookup_by(
                assets,
                id_of=lambda asset: asset.asset_id,
                keys_of=_oracle_history_paths,
            ),
            hash_to_asset_ids=_lookup_by(
                assets,
                id_of=lambda asset: asset.asset_id,
                keys_of=lambda asset: (asset.content_hash,),
            ),
            topology_key_to_asset_ids=_lookup_by(
                topology,
                id_of=lambda view: view.asset_id,
                keys_of=lambda view: (
                    topology_key(view.work_title, view.variant_label, len(view.bundle_asset_ids)),
                ),
            ),
        )

    @classmethod
    def from_fixture(cls, fixture: OracleFixture) -> OracleIndex:
        sidecars_by_asset = _manifest_sidecars_by_asset(fixture.current_manifest.sidecars)
        versions_by_asset = {
            version.asset_id: version for version in fixture.current_manifest.versions
        }
        locations_by_asset = {
            location.asset_id: location for location in fixture.current_manifest.locations
        }
        assets = []
        for manifest_asset in fixture.initial_manifest.assets:
            version = versions_by_asset.get(manifest_asset.id)
            location = locations_by_asset.get(manifest_asset.id)
            report = fixture.reports.assets[manifest_asset.id]
            assets.append(
                OracleAssetView(
                    asset_id=manifest_asset.id,
                    bundle_id=manifest_asset.bundle_id,
                    current_path=location.path if location is not None else None,
                    content_hash=version.content_hash if version is not None else None,
                    probed=version.probed if version is not None else None,
                    path_history=tuple(report.path_history),
                    sidecars=tuple(sidecars_by_asset.get(manifest_asset.id, ())),
                )
            )
        return cls.from_views(assets=tuple(assets), topology=_oracle_topology(fixture))


@dataclass(frozen=True)
class ObservedIndex:
    assets: Mapping[str, ObservedAssetView]
    topology: Mapping[str, ObservedTopologyView] = field(default_factory=dict)
    events: tuple[ObservedEvent, ...] = ()
    current_path_to_refs: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    historical_path_to_refs: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    hash_to_refs: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    topology_key_to_refs: Mapping[str, tuple[str, ...]] = field(default_factory=dict)

    @classmethod
    def from_views(
        cls,
        *,
        assets: Sequence[ObservedAssetView],
        topology: Sequence[ObservedTopologyView] = (),
        events: Sequence[ObservedEvent] = (),
    ) -> ObservedIndex:
        asset_map = {asset.observed_ref: asset for asset in assets}
        topology_map = {view.observed_ref: view for view in topology}
        return cls(
            assets=asset_map,
            topology=topology_map,
            events=tuple(events),
            current_path_to_refs=_lookup_by(
                assets,
                id_of=lambda asset: asset.observed_ref,
                keys_of=lambda asset: (asset.current_path,),
            ),
            historical_path_to_refs=_lookup_by(
                assets,
                id_of=lambda asset: asset.observed_ref,
                keys_of=lambda asset: (asset.current_path, *_observed_history_paths(asset)),
            ),
            hash_to_refs=_lookup_by(
                assets,
                id_of=lambda asset: asset.observed_ref,
                keys_of=lambda asset: (asset.content_hash,),
            ),
            topology_key_to_refs=_lookup_by(
                topology,
                id_of=lambda view: view.observed_ref,
                keys_of=lambda view: (
                    topology_key(view.work_title, view.variant_label, len(view.bundle_asset_refs)),
                ),
            ),
        )

    @classmethod
    def from_state(cls, state: ObservedState) -> ObservedIndex:
        assets = tuple(_observed_asset_view(asset) for asset in state.assets)
        return cls.from_views(
            assets=assets,
            topology=_observed_topology(state),
            events=state.events,
        )


def topology_key(
    work_title: str | None,
    variant_label: str | None,
    bundle_member_count: int,
) -> str | None:
    """Return the consumer-neutral topology key, if enough facts exist."""
    if work_title is None and variant_label is None and bundle_member_count == 0:
        return None
    return f"{work_title or ''}|{variant_label or ''}|{bundle_member_count}"


def _lookup_by[T](
    items: Sequence[T],
    *,
    id_of: Callable[[T], str],
    keys_of: Callable[[T], Sequence[str | None]],
) -> dict[str, tuple[str, ...]]:
    values: dict[str, list[str]] = {}
    for item in items:
        item_id = id_of(item)
        for key in keys_of(item):
            if key is not None:
                values.setdefault(key, []).append(item_id)
    return {key: tuple(sorted(ids)) for key, ids in values.items()}


def _oracle_history_paths(asset: OracleAssetView) -> tuple[str, ...]:
    paths: list[str] = []
    for entry in asset.path_history:
        paths.extend(path for path in (entry.from_path, entry.to_path, entry.temp_path) if path)
    return tuple(paths)


def _observed_history_paths(asset: ObservedAssetView) -> tuple[str, ...]:
    paths: list[str] = []
    for entry in asset.path_history:
        paths.extend(path for path in (entry.from_path, entry.to_path, entry.temp_path) if path)
    return tuple(paths)


def _manifest_sidecars_by_asset(
    sidecars: Sequence[ManifestSidecar],
) -> dict[str, list[ManifestSidecar]]:
    result: dict[str, list[ManifestSidecar]] = {}
    for sidecar in sidecars:
        result.setdefault(sidecar.asset_id, []).append(sidecar)
    return result


def _oracle_topology(fixture: OracleFixture) -> tuple[OracleTopologyView, ...]:
    bundles = {bundle.id: bundle for bundle in fixture.initial_manifest.bundles}
    variants = {variant.id: variant for variant in fixture.initial_manifest.variants}
    works = {work.id: work for work in fixture.initial_manifest.works}
    bundle_members: dict[str, list[str]] = {}
    for asset in fixture.initial_manifest.assets:
        bundle_members.setdefault(asset.bundle_id, []).append(asset.id)
    views: list[OracleTopologyView] = []
    for asset in fixture.initial_manifest.assets:
        bundle = bundles[asset.bundle_id]
        variant = variants[bundle.variant_id]
        work = works[variant.work_id]
        views.append(
            OracleTopologyView(
                asset_id=asset.id,
                bundle_id=bundle.id,
                variant_id=variant.id,
                work_id=work.id,
                work_title=work.title,
                variant_label=variant.label,
                bundle_asset_ids=tuple(sorted(bundle_members[bundle.id])),
            )
        )
    return tuple(views)


def _observed_asset_view(asset: ObservedAsset) -> ObservedAssetView:
    return ObservedAssetView(
        observed_ref=asset.observed_ref,
        current_path=asset.current_path,
        content_hash=asset.content_hash,
        probed=asset.probed,
        work_ref=asset.work_ref,
        variant_ref=asset.variant_ref,
        bundle_ref=asset.bundle_ref,
        sidecars=tuple(asset.sidecars),
        path_history=tuple(asset.path_history),
    )


def _observed_topology(state: ObservedState) -> tuple[ObservedTopologyView, ...]:
    works = {work.observed_ref: work for work in state.works}
    variants = {variant.observed_ref: variant for variant in state.variants}
    bundles = {bundle.observed_ref: bundle for bundle in state.bundles}
    containing_bundle = _observed_containing_bundle(state)
    views: list[ObservedTopologyView] = []
    for asset in state.assets:
        bundle = bundles.get(asset.bundle_ref or "") or containing_bundle.get(asset.observed_ref)
        variant_ref = asset.variant_ref or (bundle.variant_ref if bundle else None)
        variant = variants.get(variant_ref or "")
        work_ref = asset.work_ref or (variant.work_ref if variant else None)
        work = works.get(work_ref or "")
        views.append(
            ObservedTopologyView(
                observed_ref=asset.observed_ref,
                bundle_ref=bundle.observed_ref if bundle else asset.bundle_ref,
                variant_ref=variant_ref,
                work_ref=work_ref,
                work_title=work.title if work else None,
                variant_label=variant.label if variant else None,
                bundle_asset_refs=tuple(sorted(bundle.asset_refs)) if bundle else (),
            )
        )
    return tuple(views)


def _observed_containing_bundle(state: ObservedState):
    result = {}
    for bundle in state.bundles:
        for asset_ref in bundle.asset_refs:
            result[asset_ref] = bundle
    return result
