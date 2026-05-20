"""In-memory expected library state.

Mirrors ``chaos_librarian.contract.manifest.Manifest`` field-for-field but
is mutable and indexed by id for O(1) lookup. Event handlers in
``chaos_librarian.engine.events`` consume and mutate ``WorldState``;
``to_manifest`` serializes it back to the contract type at the end of a
plan-only run.

The initial-location convention is implemented in ``build_initial_state``:
every declared asset gets ``version_NNNN`` and ``location_NNNN`` at the
synthesized path ``<roots[0].path>/<asset.id>.<container>``. See
docs/contract/manifest-initial-state.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAsset,
    ManifestBundle,
    ManifestLocation,
    ManifestSidecar,
    ManifestVariant,
    ManifestVersion,
    ManifestWork,
)
from chaos_librarian.contract.paths import INITIAL_PATH_TEMPLATE
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.errors import ChaosLibrarianValueError


@dataclass
class WorldState:
    """Mutable mirror of ``Manifest`` indexed by id."""

    works: dict[str, ManifestWork] = field(default_factory=dict)
    variants: dict[str, ManifestVariant] = field(default_factory=dict)
    bundles: dict[str, ManifestBundle] = field(default_factory=dict)
    assets: dict[str, ManifestAsset] = field(default_factory=dict)
    versions: dict[str, ManifestVersion] = field(default_factory=dict)
    locations: dict[str, ManifestLocation] = field(default_factory=dict)
    sidecars: dict[str, ManifestSidecar] = field(default_factory=dict)

    # Reverse indices so handlers can find an asset's current location/version
    # without an O(n) scan.
    _asset_to_location: dict[str, str] = field(default_factory=dict)
    _asset_to_version: dict[str, str] = field(default_factory=dict)

    # Maps slow_copy_start event_id → (location_id, final_path). Drained on commit.
    pending_slow_copies: dict[str, tuple[str, str]] = field(default_factory=dict)

    # Sprint 6 additions: populated once in ``build_initial_state`` from
    # ``scenario.library`` so the archive_file / move_between_roots handlers
    # can resolve a root id or compute an asset's archive destination
    # without re-deriving the convention each call.
    _root_paths: dict[str, str] = field(default_factory=dict)
    _archive_path_template: str = ""

    def root_path_for(self, root_id: str) -> str:
        """Return the declared path of the library root with this id.

        Raises:
            KeyError: if ``root_id`` was not declared in the scenario.
        """
        return self._root_paths[root_id]

    def archive_path_for(self, asset_id: str) -> str:
        """Return the archive destination for ``asset_id``.

        Formats ``_archive_path_template`` with the asset's container.
        Validation (``rules/target_unknown.rule_root_unknown``) has
        already proven the archive root resolves, so the template is
        populated and the format call cannot KeyError.
        """
        asset = self.assets[asset_id]
        return self._archive_path_template.format(
            asset_id=asset_id,
            container=asset.container,
        )

    def location_id_for_asset(self, asset_id: str) -> str:
        """Return the location id currently bound to ``asset_id``.

        Raises:
            KeyError: if the asset has no current location.
        """
        return self._asset_to_location[asset_id]

    def version_id_for_asset(self, asset_id: str) -> str:
        """Return the version id currently bound to ``asset_id``."""
        return self._asset_to_version[asset_id]

    def has_location(self, asset_id: str) -> bool:
        """Return True if ``asset_id`` is currently placed at some location."""
        return asset_id in self._asset_to_location

    def bind_location(self, asset_id: str, location: ManifestLocation) -> None:
        """Register a new location for ``asset_id``."""
        self.locations[location.id] = location
        self._asset_to_location[asset_id] = location.id

    def unbind_location(self, asset_id: str) -> None:
        """Remove the asset's current location (delete_file)."""
        loc_id = self._asset_to_location.pop(asset_id)
        self.locations.pop(loc_id)

    def bind_version(self, asset_id: str, version: ManifestVersion) -> None:
        """Register a new version for ``asset_id``."""
        self.versions[version.id] = version
        self._asset_to_version[asset_id] = version.id

    def to_manifest(self) -> Manifest:
        """Serialize back to the immutable Pydantic Manifest."""
        return Manifest(
            schema_version=3,
            works=list(self.works.values()),
            variants=list(self.variants.values()),
            bundles=list(self.bundles.values()),
            assets=list(self.assets.values()),
            versions=list(self.versions.values()),
            locations=list(self.locations.values()),
            sidecars=list(self.sidecars.values()),
        )


def build_initial_state(scenario: Scenario, ids: IdAllocator) -> WorldState:
    """Construct the initial WorldState for a scenario.

    Each declared asset receives:
    - one ``ManifestVersion`` with id ``version_NNNN`` and ``index=0``
    - one ``ManifestLocation`` with id ``location_NNNN`` at path
      ``<roots[0].path>/<asset.id>.<container>``

    Raises:
        ValueError: if the scenario has zero library roots (impossible
            after Sprint 1's shape pass, but defensive).
    """
    if not scenario.library.roots:
        raise ChaosLibrarianValueError(
            "scenario has no library roots; cannot synthesize initial paths"
        )
    primary_root = scenario.library.roots[0]
    state = WorldState()
    state._root_paths = {root.id: root.path for root in scenario.library.roots}
    archive_root = scenario.library.archive_root
    if archive_root is None or archive_root == "archive":
        archive_base = f"{primary_root.path}/archive"
    else:
        archive_base = state._root_paths[archive_root]
    state._archive_path_template = f"{archive_base}/{{asset_id}}.{{container}}"

    for work in scenario.works:
        state.works[work.id] = ManifestWork(id=work.id, title=work.title)
        for variant in work.variants:
            state.variants[variant.id] = ManifestVariant(
                id=variant.id, work_id=work.id, label=variant.label
            )
            bundle = variant.bundle
            state.bundles[bundle.id] = ManifestBundle(id=bundle.id, variant_id=variant.id)
            for asset in bundle.assets:
                state.assets[asset.id] = ManifestAsset(
                    id=asset.id,
                    bundle_id=bundle.id,
                    role=asset.role,
                    container=asset.container,
                    duration_seconds=asset.duration_seconds,
                )
                version_id = ids.next_version_id()
                state.bind_version(
                    asset.id,
                    ManifestVersion(id=version_id, asset_id=asset.id, index=0),
                )
                location_id = ids.next_location_id()
                state.bind_location(
                    asset.id,
                    ManifestLocation(
                        id=location_id,
                        asset_id=asset.id,
                        path=INITIAL_PATH_TEMPLATE.format(
                            root_path=primary_root.path,
                            asset_id=asset.id,
                            container=asset.container,
                        ),
                    ),
                )

    return state
