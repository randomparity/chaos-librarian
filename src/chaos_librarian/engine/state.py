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

from collections.abc import Collection
from dataclasses import dataclass, field

from chaos_librarian.contract import MANIFEST_SCHEMA_VERSION
from chaos_librarian.contract.domain import ParentKind
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
    ManifestPodcast,
    ManifestPodcastEpisode,
    ManifestSeason,
    ManifestSeries,
    ManifestSidecar,
    ManifestTrack,
    ManifestVariant,
    ManifestVersion,
)
from chaos_librarian.contract.scenario import (
    Artist,
    ArtistLayout,
    EpisodeNaming,
    Movie,
    MovieLayout,
    Podcast,
    PodcastEpisodeNaming,
    PodcastLayout,
    Scenario,
    Series,
    SeriesLayout,
    SidecarKind,
    SubtitleMode,
    TrackNaming,
    Variant,
)
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.errors import ChaosLibrarianValueError
from chaos_librarian.path_rendering import (
    RenderableAssetContext,
    render_asset_path,
    render_declared_sidecar_path,
    replace_root_prefix,
)
from chaos_librarian.topology import AssetContext, iter_asset_contexts, renderable_asset_context


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
    podcasts: dict[str, ManifestPodcast] = field(default_factory=dict)
    podcast_episodes: dict[str, ManifestPodcastEpisode] = field(default_factory=dict)
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
    # Open network-fs-chaos windows keyed by the open event's id; the close
    # event (release_lock / remount_path) pops the matching entry. Twins of
    # pending_network_lags.
    pending_locks: dict[str, dict[str, object]] = field(default_factory=dict)
    pending_unmounts: dict[str, dict[str, object]] = field(default_factory=dict)

    # Populated once in ``build_initial_state`` from ``scenario.library`` so
    # archive_file / move_between_roots handlers can resolve root paths and
    # preserve rendered suffixes while moving assets across roots.
    _root_paths: dict[str, str] = field(default_factory=dict)
    _archive_base_path: str = ""
    _primary_root_path: str = ""
    _renderer_managed_asset_ids: set[str] = field(default_factory=set)
    _renderer_derived_sidecar_ids: set[str] = field(default_factory=set)

    def root_path_for(self, root_id: str) -> str:
        """Return the declared path of the library root with this id.

        Raises:
            KeyError: if ``root_id`` was not declared in the scenario.
        """
        return self._root_paths[root_id]

    def archive_path_for(self, asset_id: str) -> str:
        """Return the archive destination for ``asset_id``.

        Preserves the asset's current rendered path suffix and replaces
        only its current declared root prefix with the configured archive
        base. Validation has already proven the archive root resolves.
        """
        loc_id = self.location_id_for_asset(asset_id)
        current_path = self.locations[loc_id].path
        current_root = self._current_root_for_path(current_path)
        return replace_root_prefix(
            current_path,
            from_root=current_root,
            to_root=self._archive_base_path,
        )

    def _current_root_for_path(self, path: str) -> str:
        root_paths: list[str] = list(self._root_paths.values())
        root_paths.sort(key=len, reverse=True)
        for root_path in root_paths:
            if path == root_path or path.startswith(f"{root_path}/"):
                return root_path
        raise ChaosLibrarianValueError(
            f"current path {path!r} does not start with a declared library root"
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
        self._renderer_managed_asset_ids.discard(asset_id)

    def bind_version(self, asset_id: str, version: ManifestVersion) -> None:
        """Register a new version for ``asset_id``."""
        self.versions[version.id] = version
        self._asset_to_version[asset_id] = version.id

    def renderer_manages_asset(self, asset_id: str) -> bool:
        """Return True if hierarchy actions should rerender this asset."""
        return asset_id in self._renderer_managed_asset_ids

    def renderer_derived_sidecars_by_asset(
        self, asset_ids: Collection[str]
    ) -> dict[str, list[ManifestSidecar]]:
        """Group renderer-derived declared sidecars under each asset in ``asset_ids``.

        Scans ``self.sidecars`` once, in manifest order, so each asset's list
        keeps manifest order. Assets with no renderer-derived sidecars are
        absent from the result.
        """
        wanted = set(asset_ids)
        grouped: dict[str, list[ManifestSidecar]] = {}
        for sidecar_id, sidecar in self.sidecars.items():
            if sidecar.asset_id in wanted and sidecar_id in self._renderer_derived_sidecar_ids:
                grouped.setdefault(sidecar.asset_id, []).append(sidecar)
        return grouped

    def discard_renderer_sidecar(self, sidecar_id: str) -> None:
        """Mark a removed sidecar as no longer renderer-derived."""
        self._renderer_derived_sidecar_ids.discard(sidecar_id)

    def asset_ids_for_episode(self, episode_id: str) -> list[str]:
        """Return asset ids under ``episode_id`` in manifest order."""
        return self._asset_ids_for_parent(ParentKind.EPISODE, episode_id)

    def asset_ids_for_season(self, season_id: str) -> list[str]:
        """Return asset ids under ``season_id`` in manifest order."""
        episode_ids = {
            episode_id
            for episode_id, episode in self.episodes.items()
            if episode.season_id == season_id
        }
        parent_refs = {(ParentKind.EPISODE, episode_id) for episode_id in episode_ids}
        return [asset_id for asset_id in self.assets if self._asset_parent(asset_id) in parent_refs]

    def asset_ids_for_disc(self, disc_id: str) -> list[str]:
        """Return asset ids under ``disc_id`` in manifest order."""
        track_ids = {
            track_id for track_id, track in self.tracks.items() if track.disc_id == disc_id
        }
        parent_refs = {(ParentKind.TRACK, track_id) for track_id in track_ids}
        return [asset_id for asset_id in self.assets if self._asset_parent(asset_id) in parent_refs]

    def asset_ids_for_track(self, track_id: str) -> list[str]:
        """Return asset ids under ``track_id`` in manifest order."""
        return self._asset_ids_for_parent(ParentKind.TRACK, track_id)

    def asset_ids_for_podcast_episode(self, episode_id: str) -> list[str]:
        """Return asset ids under ``episode_id`` in manifest order."""
        return self._asset_ids_for_parent(ParentKind.PODCAST_EPISODE, episode_id)

    def render_path_for_asset(self, asset_id: str) -> str:
        """Render ``asset_id`` from current mutable metadata."""
        return render_asset_path(self.renderable_context_for_asset(asset_id))

    def _render_root_path_for_asset(self, asset_id: str) -> str:
        if not self.has_location(asset_id):
            return self._primary_root_path
        loc_id = self.location_id_for_asset(asset_id)
        try:
            return self._current_root_for_path(self.locations[loc_id].path)
        except ChaosLibrarianValueError:
            return self._primary_root_path

    def renderable_context_for_asset(self, asset_id: str) -> RenderableAssetContext:
        """Build a renderer context from normalized current WorldState metadata."""
        asset = self.assets[asset_id]
        bundle = self.bundles[asset.bundle_id]
        variant = self.variants[bundle.variant_id]
        root_path = self._render_root_path_for_asset(asset_id)
        bundle_asset_count = sum(
            1 for candidate in self.assets.values() if candidate.bundle_id == bundle.id
        )
        if variant.parent_kind is ParentKind.MOVIE:
            movie = self.movies[variant.parent_id]
            # No movie hierarchy/path action re-renders from manifest context, so
            # the edition (carried only on the scenario Variant, not ManifestVariant)
            # is not needed here; initial seeding renders it through
            # topology.renderable_asset_context. See ADR 0010.
            return RenderableAssetContext(
                parent_kind=ParentKind.MOVIE,
                root_path=root_path,
                layout=MovieLayout(movie.layout),
                naming=None,
                movie_title=movie.title,
                series_title=None,
                season_number=None,
                episode_number=None,
                episode_title=None,
                aired_on=None,
                absolute_number=None,
                artist_name=None,
                album_title=None,
                disc_number=None,
                track_number=None,
                track_title=None,
                variant_label=variant.label,
                asset_role=asset.role,
                asset_container=asset.container,
                bundle_asset_count=bundle_asset_count,
            )
        if variant.parent_kind is ParentKind.EPISODE:
            episode = self.episodes[variant.parent_id]
            season = self.seasons[episode.season_id]
            series = self.series[season.series_id]
            return RenderableAssetContext(
                parent_kind=ParentKind.EPISODE,
                root_path=root_path,
                layout=SeriesLayout(series.layout),
                naming=EpisodeNaming(series.episode_naming),
                movie_title=None,
                series_title=series.title,
                season_number=season.season_number,
                episode_number=episode.episode_number,
                episode_title=episode.title,
                aired_on=episode.aired_on,
                absolute_number=episode.absolute_number,
                artist_name=None,
                album_title=None,
                disc_number=None,
                track_number=None,
                track_title=None,
                variant_label=variant.label,
                asset_role=asset.role,
                asset_container=asset.container,
                bundle_asset_count=bundle_asset_count,
            )
        if variant.parent_kind is ParentKind.TRACK:
            track = self.tracks[variant.parent_id]
            disc = self.discs[track.disc_id]
            album = self.albums[disc.album_id]
            artist = self.artists[album.artist_id]
            return RenderableAssetContext(
                parent_kind=ParentKind.TRACK,
                root_path=root_path,
                layout=ArtistLayout(artist.layout),
                naming=TrackNaming(artist.track_naming),
                movie_title=None,
                series_title=None,
                season_number=None,
                episode_number=None,
                episode_title=None,
                aired_on=None,
                absolute_number=None,
                artist_name=artist.name,
                album_title=album.title,
                disc_number=disc.disc_number,
                track_number=track.track_number,
                track_title=track.title,
                variant_label=variant.label,
                asset_role=asset.role,
                asset_container=asset.container,
                bundle_asset_count=bundle_asset_count,
            )
        if variant.parent_kind is ParentKind.PODCAST_EPISODE:
            episode = self.podcast_episodes[variant.parent_id]
            podcast = self.podcasts[episode.podcast_id]
            return RenderableAssetContext(
                parent_kind=ParentKind.PODCAST_EPISODE,
                root_path=root_path,
                layout=PodcastLayout(podcast.layout),
                naming=PodcastEpisodeNaming(podcast.episode_naming),
                podcast_title=podcast.title,
                published_at=episode.published_at,
                episode_slug=episode.slug,
                episode_title=episode.title,
                variant_label=variant.label,
                asset_role=asset.role,
                asset_container=asset.container,
                bundle_asset_count=bundle_asset_count,
            )
        raise ChaosLibrarianValueError(f"asset {asset_id!r} has unsupported parent kind")

    def _asset_ids_for_parent(self, parent_kind: ParentKind, parent_id: str) -> list[str]:
        return [
            asset_id
            for asset_id in self.assets
            if self._asset_parent(asset_id) == (parent_kind, parent_id)
        ]

    def _asset_parent(self, asset_id: str) -> tuple[ParentKind, str]:
        asset = self.assets[asset_id]
        bundle = self.bundles[asset.bundle_id]
        variant = self.variants[bundle.variant_id]
        return (variant.parent_kind, variant.parent_id)

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
            podcasts=list(self.podcasts.values()),
            podcast_episodes=list(self.podcast_episodes.values()),
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
      ``seed_sidecar_projection``
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
    state._primary_root_path = primary_root.path
    archive_root = scenario.library.archive_root
    if archive_root is None or archive_root == "archive":
        archive_base = f"{primary_root.path}/archive"
    else:
        archive_base = state._root_paths[archive_root]
    state._archive_base_path = archive_base

    _seed_domain_rows(state, scenario)
    for context in iter_asset_contexts(scenario):
        _seed_asset_context(state, context, ids, primary_root.path)

    return state


def _seed_domain_rows(state: WorldState, scenario: Scenario) -> None:
    _seed_movie_rows(state, scenario.movies)
    _seed_series_rows(state, scenario.series)
    _seed_artist_rows(state, scenario.artists)
    _seed_podcast_rows(state, scenario.podcasts)


def _seed_movie_rows(state: WorldState, movies: tuple[Movie, ...]) -> None:
    for movie in movies:
        state.movies[movie.id] = ManifestMovie(
            id=movie.id,
            title=movie.title,
            layout=movie.layout.value,
        )
        for variant in movie.variants:
            _seed_variant_bundle_rows(state, variant, ParentKind.MOVIE, movie.id)


def _seed_series_rows(state: WorldState, series_list: tuple[Series, ...]) -> None:
    for series in series_list:
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
                for variant in episode.variants:
                    _seed_variant_bundle_rows(state, variant, ParentKind.EPISODE, episode.id)


def _seed_artist_rows(state: WorldState, artists: tuple[Artist, ...]) -> None:
    for artist in artists:
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
                    for variant in track.variants:
                        _seed_variant_bundle_rows(state, variant, ParentKind.TRACK, track.id)


def _seed_podcast_rows(state: WorldState, podcasts: tuple[Podcast, ...]) -> None:
    for podcast in podcasts:
        state.podcasts[podcast.id] = ManifestPodcast(
            id=podcast.id,
            title=podcast.title,
            layout=podcast.layout.value,
            episode_naming=podcast.episode_naming.value,
        )
        for episode in podcast.episodes:
            state.podcast_episodes[episode.id] = ManifestPodcastEpisode(
                id=episode.id,
                podcast_id=podcast.id,
                title=episode.title,
                published_at=episode.published_at,
                slug=episode.slug,
                stale=episode.stale,
            )
            for variant in episode.variants:
                _seed_variant_bundle_rows(state, variant, ParentKind.PODCAST_EPISODE, episode.id)


def _seed_variant_bundle_rows(
    state: WorldState,
    variant: Variant,
    parent_kind: ParentKind,
    parent_id: str,
) -> None:
    state.variants[variant.id] = ManifestVariant(
        id=variant.id,
        parent_kind=parent_kind,
        parent_id=parent_id,
        label=variant.label,
    )
    state.bundles[variant.bundle.id] = ManifestBundle(
        id=variant.bundle.id,
        variant_id=variant.id,
    )


def _seed_asset_context(
    state: WorldState,
    context: AssetContext,
    ids: IdAllocator,
    primary_root_path: str,
) -> None:
    bundle = context.bundle
    asset = context.asset
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
    media_path = render_asset_path(renderable_asset_context(context, primary_root_path))
    state.bind_location(
        asset.id,
        ManifestLocation(
            id=ids.next_location_id(),
            asset_id=asset.id,
            path=media_path,
        ),
    )
    state._renderer_managed_asset_ids.add(asset.id)
    for subtitle in asset.subtitles:
        if subtitle.mode is not SubtitleMode.SIDECAR:
            continue
        sidecar_id = f"sidecar_{asset.id}_{subtitle.language}"
        state.sidecars[sidecar_id] = ManifestSidecar(
            id=sidecar_id,
            asset_id=asset.id,
            kind=SidecarKind.SUBTITLE.value,
            path=render_declared_sidecar_path(
                media_path,
                subtitle.language,
                codec=subtitle.codec.value,
            ),
            language=subtitle.language,
        )
        state._renderer_derived_sidecar_ids.add(sidecar_id)
