"""In-memory expected library state.

Mirrors ``chaos_librarian.contract.manifest.Manifest`` field-for-field but
is mutable and indexed by id for O(1) lookup. Event handlers in
``chaos_librarian.engine.events`` consume and mutate ``WorldState``;
``to_manifest`` serializes it back to the contract type at the end of a
plan-only run.

The initial-location convention is implemented in ``build_initial_state``:
every declared asset gets ``version_NNNN`` and ``location_NNNN`` at the
rendered hierarchy path under ``scenario.library.roots[0].path``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chaos_librarian.contract import MANIFEST_SCHEMA_VERSION
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAlbum,
    ManifestArtist,
    ManifestAsset,
    ManifestBundle,
    ManifestDisc,
    ManifestEpisode,
    ManifestLocation,
    ManifestMovie,
    ManifestSeason,
    ManifestSeries,
    ManifestSidecar,
    ManifestTrack,
    ManifestVariant,
    ManifestVersion,
)
from chaos_librarian.contract.scenario import (
    ArtistLayout,
    EpisodeNaming,
    MovieLayout,
    Scenario,
    SeriesLayout,
    SidecarKind,
    SubtitleMode,
    TrackNaming,
)
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.errors import ChaosLibrarianValueError
from chaos_librarian.path_rendering import (
    RenderableAssetContext,
    render_asset_path,
    render_declared_sidecar_path,
)
from chaos_librarian.topology import AssetContext, iter_asset_contexts


@dataclass
class WorldState:
    """Mutable mirror of ``Manifest`` indexed by id."""

    movies: dict[str, ManifestMovie] = field(default_factory=dict)
    series: dict[str, ManifestSeries] = field(default_factory=dict)
    seasons: dict[str, ManifestSeason] = field(default_factory=dict)
    episodes: dict[str, ManifestEpisode] = field(default_factory=dict)
    artists: dict[str, ManifestArtist] = field(default_factory=dict)
    albums: dict[str, ManifestAlbum] = field(default_factory=dict)
    discs: dict[str, ManifestDisc] = field(default_factory=dict)
    tracks: dict[str, ManifestTrack] = field(default_factory=dict)
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

    # Journal-derived evidence used by an immediately following multi-phase event.
    # Not serialized into the manifest; only supports same-run handlers.
    previous_event_delta: tuple[str, dict[str, object]] | None = None
    pending_network_lags: dict[str, dict[str, object]] = field(default_factory=dict)

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

    def sidecar_id_for_path(self, asset_id: str, path: str) -> str:
        """Return the sidecar_id whose (asset_id, path) pair matches.

        Validation guarantees the lookup succeeds for any well-formed
        scenario (rule_sidecar_target rejects misses before the engine
        runs). The engine raises KeyError rather than emitting a journal
        entry — a missing sidecar here is a bug at this layer.

        Raises:
            KeyError: no sidecar matches.
        """
        for sid, sidecar in self.sidecars.items():
            if sidecar.asset_id == asset_id and sidecar.path == path:
                return sid
        raise KeyError(f"no sidecar for asset {asset_id!r} at path {path!r}")

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
            schema_version=MANIFEST_SCHEMA_VERSION,
            movies=list(self.movies.values()),
            series=list(self.series.values()),
            seasons=list(self.seasons.values()),
            episodes=list(self.episodes.values()),
            artists=list(self.artists.values()),
            albums=list(self.albums.values()),
            discs=list(self.discs.values()),
            tracks=list(self.tracks.values()),
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
    - one ``ManifestLocation`` with id ``location_NNNN`` at the rendered
      hierarchy path under ``scenario.library.roots[0].path``
    - one ``ManifestSidecar`` per declared subtitle with ``mode=sidecar``,
      id ``sidecar_<asset.id>_<language>`` next to the rendered media
      path. Embedded subtitles are skipped. This mirrors the validator's
      ``_seed_projection_from_declared``
      projection so Sprint 7 handlers (``embed_subtitle``,
      ``update_sidecar``, ``remove_sidecar``, ``extract_subtitle``) can
      resolve a declared sidecar via ``sidecar_id_for_path`` instead of
      raising KeyError.

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

    _seed_domain_rows(state, scenario)
    for context in iter_asset_contexts(scenario):
        _seed_asset_context(state, context, ids, primary_root.path)

    return state


def _seed_domain_rows(state: WorldState, scenario: Scenario) -> None:
    for movie in scenario.movies:
        state.movies[movie.id] = ManifestMovie(
            id=movie.id,
            title=movie.title,
            layout=movie.layout.value,
        )
    for series in scenario.series:
        state.series[series.id] = ManifestSeries(
            id=series.id,
            title=series.title,
            layout=series.layout.value,
            episode_naming=series.episode_naming.value,
        )
        for season in series.seasons:
            state.seasons[season.id] = ManifestSeason(
                id=season.id,
                series_id=series.id,
                season_number=season.season_number,
                title=season.title,
            )
            for episode in season.episodes:
                state.episodes[episode.id] = ManifestEpisode(
                    id=episode.id,
                    season_id=season.id,
                    episode_number=episode.episode_number,
                    title=episode.title,
                    aired_on=episode.aired_on,
                    absolute_number=episode.absolute_number,
                )
    for artist in scenario.artists:
        state.artists[artist.id] = ManifestArtist(
            id=artist.id,
            name=artist.name,
            layout=artist.layout.value,
            track_naming=artist.track_naming.value,
        )
        for album in artist.albums:
            state.albums[album.id] = ManifestAlbum(
                id=album.id,
                artist_id=artist.id,
                title=album.title,
                release_year=album.release_year,
            )
            for disc in album.discs:
                state.discs[disc.id] = ManifestDisc(
                    id=disc.id,
                    album_id=album.id,
                    disc_number=disc.disc_number,
                )
                for track in disc.tracks:
                    state.tracks[track.id] = ManifestTrack(
                        id=track.id,
                        disc_id=disc.id,
                        track_number=track.track_number,
                        title=track.title,
                        performers=list(track.performers),
                    )


def _seed_asset_context(
    state: WorldState,
    context: AssetContext,
    ids: IdAllocator,
    primary_root_path: str,
) -> None:
    variant = context.variant
    bundle = context.bundle
    asset = context.asset
    state.variants[variant.id] = ManifestVariant(
        id=variant.id,
        parent_kind=context.parent_kind,
        parent_id=context.parent_id,
        label=variant.label,
    )
    state.bundles[bundle.id] = ManifestBundle(id=bundle.id, variant_id=variant.id)
    state.assets[asset.id] = ManifestAsset(
        id=asset.id,
        bundle_id=bundle.id,
        role=asset.role,
        container=asset.container,
        duration_seconds=asset.duration_seconds,
    )
    state.bind_version(
        asset.id,
        ManifestVersion(id=ids.next_version_id(), asset_id=asset.id, index=0),
    )
    media_path = render_asset_path(_renderable_asset_context(context, primary_root_path))
    state.bind_location(
        asset.id,
        ManifestLocation(
            id=ids.next_location_id(),
            asset_id=asset.id,
            path=media_path,
        ),
    )
    for subtitle in asset.subtitles:
        if subtitle.mode is not SubtitleMode.SIDECAR:
            continue
        sidecar_id = f"sidecar_{asset.id}_{subtitle.language}"
        state.sidecars[sidecar_id] = ManifestSidecar(
            id=sidecar_id,
            asset_id=asset.id,
            kind=SidecarKind.SUBTITLE.value,
            path=render_declared_sidecar_path(media_path, subtitle.language),
            language=subtitle.language,
        )


def _renderable_asset_context(
    context: AssetContext,
    root_path: str,
) -> RenderableAssetContext:
    return RenderableAssetContext(
        parent_kind=context.parent_kind,
        root_path=root_path,
        layout=_layout_for_context(context),
        naming=_naming_for_context(context),
        movie_title=context.movie.title if context.movie is not None else None,
        series_title=context.series.title if context.series is not None else None,
        season_number=context.season.season_number if context.season is not None else None,
        episode_number=(context.episode.episode_number if context.episode is not None else None),
        episode_title=context.episode.title if context.episode is not None else None,
        aired_on=context.episode.aired_on if context.episode is not None else None,
        absolute_number=(context.episode.absolute_number if context.episode is not None else None),
        artist_name=context.artist.name if context.artist is not None else None,
        album_title=context.album.title if context.album is not None else None,
        disc_number=context.disc.disc_number if context.disc is not None else None,
        track_number=context.track.track_number if context.track is not None else None,
        track_title=context.track.title if context.track is not None else None,
        variant_label=context.variant.label,
        asset_role=context.asset.role,
        asset_container=context.asset.container,
        bundle_asset_count=context.bundle_asset_count,
    )


def _layout_for_context(context: AssetContext) -> MovieLayout | SeriesLayout | ArtistLayout:
    if context.movie is not None:
        return context.movie.layout
    if context.series is not None:
        return context.series.layout
    if context.artist is not None:
        return context.artist.layout
    raise ChaosLibrarianValueError(f"asset {context.asset.id} has no hierarchy layout")


def _naming_for_context(context: AssetContext) -> EpisodeNaming | TrackNaming | None:
    if context.series is not None:
        return context.series.episode_naming
    if context.artist is not None:
        return context.artist.track_naming
    return None
