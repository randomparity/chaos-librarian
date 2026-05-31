"""Mutable hierarchy projection shared by timeline validation rules."""

from __future__ import annotations

import enum
from collections.abc import Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Final

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    HIERARCHY_TIMELINE_ACTIONS,
    ArtistLayout,
    EpisodeNaming,
    PodcastEpisodeNaming,
    PodcastLayout,
    SeriesLayout,
    TimelineActionName,
    TrackNaming,
)
from chaos_librarian.path_rendering import (
    RenderableAssetContext,
    render_asset_path,
    replace_root_prefix,
)
from chaos_librarian.validation.rules.hierarchy_walkers import (
    iter_asset_contexts,
    iter_declared_roots,
    primary_root_path,
    rendered_asset_paths,
)
from chaos_librarian.validation.rules.raw_helpers import (
    _as_list,
    _as_mapping,
    _date,
    _enum,
    _int,
    _Loc,
    _parse_datetime,
    _str,
)


@dataclass(slots=True)
class _AssetTail:
    id: str
    parent_id: str
    variant_label: str
    asset_role: str
    asset_container: str
    bundle_asset_count: int
    loc: _Loc


@dataclass(slots=True)
class _SeriesState:
    id: str
    title: str
    layout: SeriesLayout
    episode_naming: EpisodeNaming


@dataclass(slots=True)
class _EpisodeState:
    id: str
    season_id: str
    episode_number: int
    title: str
    aired_on: date | None
    absolute_number: int | None
    asset_ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class _SeasonState:
    id: str
    series_id: str
    season_number: int
    title: str
    episode_ids: list[str]


@dataclass(slots=True)
class _ArtistState:
    id: str
    name: str
    layout: ArtistLayout
    track_naming: TrackNaming


@dataclass(slots=True)
class _AlbumState:
    id: str
    artist_id: str
    title: str


@dataclass(slots=True)
class _DiscState:
    id: str
    album_id: str
    disc_number: int
    track_ids: list[str]


@dataclass(slots=True)
class _TrackState:
    id: str
    disc_id: str
    track_number: int
    title: str
    asset_ids: set[str] = field(default_factory=set)


@dataclass(slots=True)
class _PodcastState:
    id: str
    title: str
    layout: PodcastLayout
    episode_naming: PodcastEpisodeNaming


@dataclass(slots=True)
class _PodcastEpisodeState:
    id: str
    podcast_id: str
    title: str
    published_at: datetime
    slug: str
    stale: bool
    asset_ids: set[str] = field(default_factory=set)


@dataclass(frozen=True, slots=True)
class HierarchyMutation:
    affected_asset_ids: frozenset[str]
    affected_season_ids: frozenset[str]
    affected_album_ids: frozenset[str]
    affected_disc_ids: frozenset[str]
    path_changes: Mapping[str, tuple[str | None, str | None]]


class SwapValidity(enum.StrEnum):
    """Result of validating a numbering-swap event's two operands.

    ``MISSING`` (an operand id does not resolve) is treated as OK by the
    timeline rule because ``rule_target_unknown`` already reported the missing
    id; ``apply`` no-ops the exchange in every non-``OK`` case.
    """

    OK = "ok"
    SELF_SWAP = "self_swap"
    NOT_SAME_PARENT = "not_same_parent"
    MISSING = "missing"


# Each swap action's second-operand field plus the projection entity-map attribute
# and the parent-id attribute used for the same-parent check.
_SWAP_SPEC_BY_ACTION: Final[dict[str, tuple[str, str, str]]] = {
    TimelineActionName.SWAP_EPISODE_NUMBERS: ("with_episode", "episodes", "season_id"),
    TimelineActionName.SWAP_DISC_NUMBERS: ("with_disc", "discs", "album_id"),
    TimelineActionName.SWAP_TRACK_NUMBERS: ("with_track", "tracks", "disc_id"),
}

# The mutable number field each swap exchanges on the projection entity state.
_SWAP_NUMBER_FIELD_BY_ACTION: Final[dict[str, str]] = {
    TimelineActionName.SWAP_EPISODE_NUMBERS: "episode_number",
    TimelineActionName.SWAP_DISC_NUMBERS: "disc_number",
    TimelineActionName.SWAP_TRACK_NUMBERS: "track_number",
}


class HierarchyProjection:
    """Mutable validation-only projection for hierarchy timeline actions."""

    def __init__(self, raw: Mapping[str, object]) -> None:
        self.root_path: str | None = primary_root_path(raw)
        self.root_paths: dict[str, str] = {
            root_id: path for root_id, path in iter_declared_roots(raw) if path is not None
        }
        self.archive_base_path: str | None = self._archive_base_path(raw)
        self.series: dict[str, _SeriesState] = {}
        self.seasons: dict[str, _SeasonState] = {}
        self.episodes: dict[str, _EpisodeState] = {}
        self.artists: dict[str, _ArtistState] = {}
        self.albums: dict[str, _AlbumState] = {}
        self.discs: dict[str, _DiscState] = {}
        self.tracks: dict[str, _TrackState] = {}
        self.podcasts: dict[str, _PodcastState] = {}
        self.podcast_episodes: dict[str, _PodcastEpisodeState] = {}
        self.assets: dict[str, _AssetTail] = {}
        initial_paths = rendered_asset_paths(raw)
        self.current_paths = {asset_id: path for asset_id, (path, _loc) in initial_paths.items()}
        self._renderer_managed_asset_ids = set(initial_paths)
        self._seed_series(raw)
        self._seed_artists(raw)
        self._seed_podcasts(raw)
        self._seed_assets(raw)

    def apply(self, event: Mapping[str, object]) -> HierarchyMutation:
        """Apply one hierarchy action and return affected IDs and path changes."""
        affected_assets = self.affected_asset_ids(event)
        before = {asset_id: self.current_paths.get(asset_id) for asset_id in affected_assets}
        seasons: set[str] = set()
        albums: set[str] = set()
        discs: set[str] = set()
        action = event.get("action")
        if action == TimelineActionName.RENUMBER_EPISODE:
            seasons.update(self._apply_renumber_episode(event))
        elif action == TimelineActionName.MOVE_EPISODE_TO_SEASON:
            seasons.update(self._apply_move_episode(event))
        elif action == TimelineActionName.RENAME_SEASON:
            seasons.update(self._apply_rename_season(event))
        elif action == TimelineActionName.RENUMBER_DISC:
            albums.update(self._apply_renumber_disc(event))
        elif action == TimelineActionName.MOVE_TRACK_TO_DISC:
            discs.update(self._apply_move_track(event))
        elif action == TimelineActionName.REPUBLISH_EPISODE:
            self._apply_republish_episode(event)
        elif action in _SWAP_SPEC_BY_ACTION:
            self._apply_swap(event, seasons=seasons, albums=albums, discs=discs)
        path_changes = self._refresh_paths(affected_assets, before)
        return HierarchyMutation(
            affected_asset_ids=frozenset(affected_assets),
            affected_season_ids=frozenset(seasons),
            affected_album_ids=frozenset(albums),
            affected_disc_ids=frozenset(discs),
            path_changes=path_changes,
        )

    def project_non_hierarchy_event(
        self,
        event: Mapping[str, object],
        pending_slow_copies: dict[str, tuple[str, str]],
    ) -> None:
        """Project non-hierarchy path actions using engine renderer-management rules."""
        action = event.get("action")
        if action in {
            TimelineActionName.MOVE_ASSET,
            TimelineActionName.RENAME_FILE,
            TimelineActionName.ADD_FILE,
        }:
            self._project_to_field_path(event)
        elif action == TimelineActionName.DELETE_FILE:
            self._project_delete_file(event)
        elif action == TimelineActionName.SLOW_COPY_START:
            self._project_slow_copy_start(event, pending_slow_copies)
        elif action == TimelineActionName.SLOW_COPY_COMMIT:
            self._project_slow_copy_commit(event, pending_slow_copies)
        elif action == TimelineActionName.ARCHIVE_FILE:
            self._project_archive_file(event)
        elif action == TimelineActionName.MOVE_BETWEEN_ROOTS:
            self._project_move_between_roots(event)
        elif action == TimelineActionName.REMUX_CONTAINER:
            self._project_remux_container(event)

    def archive_file_destination(self, event: Mapping[str, object]) -> str | None:
        """Return the archive destination for ``event`` without mutating state."""
        target = event.get("target")
        if not isinstance(target, str) or self.archive_base_path is None:
            return None
        current_path = self.current_paths.get(target)
        if current_path is None:
            return None
        current_root = self.current_root_for_path(current_path)
        return replace_root_prefix(
            current_path,
            from_root=current_root,
            to_root=self.archive_base_path,
        )

    def move_between_roots_destination(self, event: Mapping[str, object]) -> str | None:
        """Return the move-between-roots destination without mutating state."""
        target = event.get("target")
        from_root_id = event.get("from_root_id")
        to_root_id = event.get("to_root_id")
        if not (
            isinstance(target, str)
            and isinstance(from_root_id, str)
            and isinstance(to_root_id, str)
        ):
            return None
        current_path = self.current_paths.get(target)
        from_root = self.root_paths.get(from_root_id)
        to_root = self.root_paths.get(to_root_id)
        if current_path is None or from_root is None or to_root is None:
            return None
        return replace_root_prefix(
            current_path,
            from_root=from_root,
            to_root=to_root,
        )

    def current_root_for_path(self, path: str) -> str:
        """Return the longest declared root that ``path`` lives under, or raise."""
        current_root = self._current_root_for_path(path)
        if current_root is None:
            raise ValueError("current path does not start with a declared root")
        return current_root

    def affected_asset_ids(self, event: Mapping[str, object]) -> set[str]:
        """Return assets under the hierarchy entity targeted by ``event``."""
        action = event.get("action")
        if isinstance(action, str) and action in _SWAP_SPEC_BY_ACTION:
            return self._swap_affected_asset_ids(action, event)
        target = event.get("target")
        if not isinstance(target, str):
            return set()
        return self._single_target_affected_asset_ids(action, target)

    def _single_target_affected_asset_ids(self, action: object, target: str) -> set[str]:
        if action in {
            TimelineActionName.RENUMBER_EPISODE,
            TimelineActionName.MOVE_EPISODE_TO_SEASON,
        }:
            episode = self.episodes.get(target)
            return set() if episode is None else set(episode.asset_ids)
        if action == TimelineActionName.RENAME_SEASON:
            return self._asset_ids_for_season(target)
        if action == TimelineActionName.RENUMBER_DISC:
            return self._asset_ids_for_disc(target)
        if action == TimelineActionName.MOVE_TRACK_TO_DISC:
            track = self.tracks.get(target)
            return set() if track is None else set(track.asset_ids)
        if action == TimelineActionName.REPUBLISH_EPISODE:
            episode = self.podcast_episodes.get(target)
            return set() if episode is None else set(episode.asset_ids)
        return set()

    def swap_validity(self, event: Mapping[str, object]) -> SwapValidity:
        """Classify a numbering-swap event's two operands without mutating state."""
        action = event.get("action")
        if not isinstance(action, str) or action not in _SWAP_SPEC_BY_ACTION:
            return SwapValidity.OK
        target = event.get("target")
        with_field, entity_attr, parent_attr = _SWAP_SPEC_BY_ACTION[action]
        other = event.get(with_field)
        if not isinstance(target, str) or not isinstance(other, str):
            return SwapValidity.MISSING
        if target == other:
            return SwapValidity.SELF_SWAP
        entities: Mapping[str, object] = getattr(self, entity_attr)
        a = entities.get(target)
        b = entities.get(other)
        if a is None or b is None:
            return SwapValidity.MISSING
        if getattr(a, parent_attr) != getattr(b, parent_attr):
            return SwapValidity.NOT_SAME_PARENT
        return SwapValidity.OK

    def _swap_affected_asset_ids(self, action: str, event: Mapping[str, object]) -> set[str]:
        with_field, _entity_attr, _parent_attr = _SWAP_SPEC_BY_ACTION[action]
        affected: set[str] = set()
        for entity_id in (event.get("target"), event.get(with_field)):
            if isinstance(entity_id, str):
                affected.update(self._swap_entity_asset_ids(action, entity_id))
        return affected

    def _swap_entity_asset_ids(self, action: str, entity_id: str) -> set[str]:
        if action == TimelineActionName.SWAP_EPISODE_NUMBERS:
            episode = self.episodes.get(entity_id)
            return set() if episode is None else set(episode.asset_ids)
        if action == TimelineActionName.SWAP_DISC_NUMBERS:
            return self._asset_ids_for_disc(entity_id)
        track = self.tracks.get(entity_id)
        return set() if track is None else set(track.asset_ids)

    def _apply_swap(
        self,
        event: Mapping[str, object],
        *,
        seasons: set[str],
        albums: set[str],
        discs: set[str],
    ) -> None:
        action = event.get("action")
        if not isinstance(action, str) or action not in _SWAP_SPEC_BY_ACTION:
            return
        if self.swap_validity(event) is not SwapValidity.OK:
            return  # rule layer reports SELF_SWAP / NOT_SAME_PARENT; MISSING is target-unknown
        with_field, entity_attr, parent_attr = _SWAP_SPEC_BY_ACTION[action]
        number_field = _SWAP_NUMBER_FIELD_BY_ACTION[action]
        target = event.get("target")
        other = event.get(with_field)
        if not isinstance(target, str) or not isinstance(other, str):
            return
        entities: Mapping[str, object] = getattr(self, entity_attr)
        a = entities[target]
        b = entities[other]
        a_number = getattr(a, number_field)
        setattr(a, number_field, getattr(b, number_field))
        setattr(b, number_field, a_number)
        affected_parent = {getattr(a, parent_attr)}
        if action == TimelineActionName.SWAP_EPISODE_NUMBERS:
            seasons.update(affected_parent)
        elif action == TimelineActionName.SWAP_DISC_NUMBERS:
            albums.update(affected_parent)
        else:
            discs.update(affected_parent)

    def render_asset_path(self, asset_id: str) -> str | None:
        """Render one asset from the current hierarchy snapshot."""
        tail = self.assets.get(asset_id)
        if tail is None:
            return None
        root_path = self._render_root_path_for_asset(asset_id)
        if root_path is None:
            return None
        renderer = self._renderer_for_parent_kind(tail)
        if renderer is None:
            return self.current_paths.get(asset_id)
        try:
            return renderer(tail, root_path=root_path)
        except ValueError:
            return None

    def _renderer_for_parent_kind(self, tail: _AssetTail) -> Callable[..., str | None] | None:
        if tail.parent_id in self.episodes:
            return self._render_episode_asset
        if tail.parent_id in self.tracks:
            return self._render_track_asset
        if tail.parent_id in self.podcast_episodes:
            return self._render_podcast_asset
        return None

    def _render_root_path_for_asset(self, asset_id: str) -> str | None:
        current_path = self.current_paths.get(asset_id)
        if current_path is None:
            return self.root_path
        current_root = self._current_root_for_path(current_path)
        return current_root if current_root is not None else self.root_path

    def _seed_series(self, raw: Mapping[str, object]) -> None:
        series_items = _as_list(raw.get("series")) or []
        for series_obj in series_items:
            series = _as_mapping(series_obj)
            if series is None:
                continue
            series_id = _str(series.get("id"))
            layout = _enum(SeriesLayout, series.get("layout"))
            naming = _enum(EpisodeNaming, series.get("episode_naming"))
            title = _str(series.get("title"))
            if series_id is None or layout is None or naming is None or title is None:
                continue
            self.series[series_id] = _SeriesState(series_id, title, layout, naming)
            self._seed_seasons(series, series_id=series_id)

    def _seed_seasons(self, series: Mapping[str, object], *, series_id: str) -> None:
        for season_obj in _as_list(series.get("seasons")) or []:
            season = _as_mapping(season_obj)
            if season is None:
                continue
            season_id = _str(season.get("id"))
            season_number = _int(season.get("season_number"))
            title = _str(season.get("title"))
            if season_id is None or season_number is None or title is None:
                continue
            episode_ids = self._seed_episodes(season, season_id=season_id)
            self.seasons[season_id] = _SeasonState(
                season_id, series_id, season_number, title, episode_ids
            )

    def _seed_episodes(self, season: Mapping[str, object], *, season_id: str) -> list[str]:
        episode_ids: list[str] = []
        for episode_obj in _as_list(season.get("episodes")) or []:
            episode = _as_mapping(episode_obj)
            if episode is None:
                continue
            episode_id = _str(episode.get("id"))
            episode_number = _int(episode.get("episode_number"))
            title = _str(episode.get("title"))
            if episode_id is None or episode_number is None or title is None:
                continue
            episode_ids.append(episode_id)
            self.episodes[episode_id] = _EpisodeState(
                id=episode_id,
                season_id=season_id,
                episode_number=episode_number,
                title=title,
                aired_on=_date(episode.get("aired_on")),
                absolute_number=_int(episode.get("absolute_number")),
            )
        return episode_ids

    def _seed_artists(self, raw: Mapping[str, object]) -> None:
        for artist_obj in _as_list(raw.get("artists")) or []:
            artist = _as_mapping(artist_obj)
            if artist is None:
                continue
            artist_id = _str(artist.get("id"))
            name = _str(artist.get("name"))
            layout = _enum(ArtistLayout, artist.get("layout"))
            naming = _enum(TrackNaming, artist.get("track_naming"))
            if artist_id is None or name is None or layout is None or naming is None:
                continue
            self.artists[artist_id] = _ArtistState(artist_id, name, layout, naming)
            self._seed_albums(artist, artist_id=artist_id)

    def _seed_albums(self, artist: Mapping[str, object], *, artist_id: str) -> None:
        for album_obj in _as_list(artist.get("albums")) or []:
            album = _as_mapping(album_obj)
            if album is None:
                continue
            album_id = _str(album.get("id"))
            title = _str(album.get("title"))
            if album_id is None or title is None:
                continue
            self.albums[album_id] = _AlbumState(album_id, artist_id, title)
            self._seed_discs(album, album_id=album_id)

    def _seed_discs(self, album: Mapping[str, object], *, album_id: str) -> None:
        for disc_obj in _as_list(album.get("discs")) or []:
            disc = _as_mapping(disc_obj)
            if disc is None:
                continue
            disc_id = _str(disc.get("id"))
            disc_number = _int(disc.get("disc_number"))
            if disc_id is None or disc_number is None:
                continue
            track_ids = self._seed_tracks(disc, disc_id=disc_id)
            self.discs[disc_id] = _DiscState(disc_id, album_id, disc_number, track_ids)

    def _seed_tracks(self, disc: Mapping[str, object], *, disc_id: str) -> list[str]:
        track_ids: list[str] = []
        for track_obj in _as_list(disc.get("tracks")) or []:
            track = _as_mapping(track_obj)
            if track is None:
                continue
            track_id = _str(track.get("id"))
            track_number = _int(track.get("track_number"))
            title = _str(track.get("title"))
            if track_id is None or track_number is None or title is None:
                continue
            track_ids.append(track_id)
            self.tracks[track_id] = _TrackState(track_id, disc_id, track_number, title)
        return track_ids

    def _seed_podcasts(self, raw: Mapping[str, object]) -> None:
        for podcast_obj in _as_list(raw.get("podcasts")) or []:
            podcast = _as_mapping(podcast_obj)
            if podcast is None:
                continue
            podcast_id = _str(podcast.get("id"))
            title = _str(podcast.get("title"))
            layout = _enum(PodcastLayout, podcast.get("layout"))
            naming = _enum(PodcastEpisodeNaming, podcast.get("episode_naming"))
            if podcast_id is None or title is None or layout is None or naming is None:
                continue
            self.podcasts[podcast_id] = _PodcastState(podcast_id, title, layout, naming)
            self._seed_podcast_episodes(podcast, podcast_id=podcast_id)

    def _seed_podcast_episodes(self, podcast: Mapping[str, object], *, podcast_id: str) -> None:
        for episode_obj in _as_list(podcast.get("episodes")) or []:
            episode = _as_mapping(episode_obj)
            if episode is None:
                continue
            episode_id = _str(episode.get("id"))
            title = _str(episode.get("title"))
            slug = _str(episode.get("slug"))
            published_at = _parse_datetime(episode.get("published_at"))
            if episode_id is None or title is None or slug is None or published_at is None:
                continue
            self.podcast_episodes[episode_id] = _PodcastEpisodeState(
                id=episode_id,
                podcast_id=podcast_id,
                title=title,
                published_at=published_at,
                slug=slug,
                stale=bool(episode.get("stale", False)),
            )

    def _seed_assets(self, raw: Mapping[str, object]) -> None:
        for context in iter_asset_contexts(raw):
            asset_id = _str(context.asset.get("id"))
            variant_label = _str(context.variant.get("label"))
            role = _str(context.asset.get("role"))
            container = _str(context.asset.get("container"))
            if asset_id is None:
                continue
            if variant_label is None or role is None or container is None:
                continue
            tail = _AssetTail(
                id=asset_id,
                parent_id=context.parent_id,
                variant_label=variant_label,
                asset_role=role,
                asset_container=container,
                bundle_asset_count=context.bundle_asset_count,
                loc=context.asset_loc,
            )
            self.assets[asset_id] = tail
            if context.parent_id in self.episodes:
                self.episodes[context.parent_id].asset_ids.add(asset_id)
            elif context.parent_id in self.tracks:
                self.tracks[context.parent_id].asset_ids.add(asset_id)
            elif context.parent_id in self.podcast_episodes:
                self.podcast_episodes[context.parent_id].asset_ids.add(asset_id)

    def _apply_renumber_episode(self, event: Mapping[str, object]) -> set[str]:
        target = event.get("target")
        episode_number = _int(event.get("episode_number"))
        if not isinstance(target, str) or episode_number is None:
            return set()
        episode = self.episodes.get(target)
        if episode is None:
            return set()
        episode.episode_number = episode_number
        absolute_number = _int(event.get("absolute_number"))
        if absolute_number is not None:
            episode.absolute_number = absolute_number
        return {episode.season_id}

    def _apply_republish_episode(self, event: Mapping[str, object]) -> None:
        target = event.get("target")
        published_at = _parse_datetime(event.get("published_at"))
        if not isinstance(target, str) or published_at is None:
            return
        episode = self.podcast_episodes.get(target)
        if episode is None:
            return
        episode.published_at = published_at
        episode.stale = False
        slug = _str(event.get("slug"))
        if slug is not None:
            episode.slug = slug

    def _apply_move_episode(self, event: Mapping[str, object]) -> set[str]:
        target = event.get("target")
        to_season = event.get("to_season")
        episode_number = _int(event.get("episode_number"))
        if not isinstance(target, str) or not isinstance(to_season, str):
            return set()
        episode = self.episodes.get(target)
        destination = self.seasons.get(to_season)
        if episode is None or destination is None or episode_number is None:
            return set()
        old_season_id = episode.season_id
        self._move_list_item(
            self.seasons[old_season_id].episode_ids,
            target,
            destination.episode_ids,
        )
        episode.season_id = to_season
        episode.episode_number = episode_number
        absolute_number = _int(event.get("absolute_number"))
        if absolute_number is not None:
            episode.absolute_number = absolute_number
        return {old_season_id, to_season}

    def _apply_rename_season(self, event: Mapping[str, object]) -> set[str]:
        target = event.get("target")
        title = _str(event.get("title"))
        if not isinstance(target, str) or title is None:
            return set()
        season = self.seasons.get(target)
        if season is None:
            return set()
        season.title = title
        return {target}

    def _apply_renumber_disc(self, event: Mapping[str, object]) -> set[str]:
        target = event.get("target")
        disc_number = _int(event.get("disc_number"))
        if not isinstance(target, str) or disc_number is None:
            return set()
        disc = self.discs.get(target)
        if disc is None:
            return set()
        disc.disc_number = disc_number
        return {disc.album_id}

    def _apply_move_track(self, event: Mapping[str, object]) -> set[str]:
        target = event.get("target")
        to_disc = event.get("to_disc")
        track_number = _int(event.get("track_number"))
        if not isinstance(target, str) or not isinstance(to_disc, str):
            return set()
        track = self.tracks.get(target)
        destination = self.discs.get(to_disc)
        if track is None or destination is None or track_number is None:
            return set()
        old_disc_id = track.disc_id
        self._move_list_item(self.discs[old_disc_id].track_ids, target, destination.track_ids)
        track.disc_id = to_disc
        track.track_number = track_number
        return {old_disc_id, to_disc}

    def _project_to_field_path(self, event: Mapping[str, object]) -> None:
        target = event.get("target")
        path = event.get("to")
        if isinstance(target, str) and isinstance(path, str):
            self.current_paths[target] = path

    def _project_delete_file(self, event: Mapping[str, object]) -> None:
        target = event.get("target")
        if isinstance(target, str):
            self.current_paths.pop(target, None)
            self._renderer_managed_asset_ids.discard(target)

    def _project_slow_copy_start(
        self,
        event: Mapping[str, object],
        pending_slow_copies: dict[str, tuple[str, str]],
    ) -> None:
        event_id = event.get("id")
        target = event.get("target")
        final_path = event.get("to")
        if isinstance(event_id, str) and isinstance(target, str) and isinstance(final_path, str):
            pending_slow_copies[event_id] = (target, final_path)

    def _project_slow_copy_commit(
        self,
        event: Mapping[str, object],
        pending_slow_copies: dict[str, tuple[str, str]],
    ) -> None:
        start_id = event.get("for")
        if not isinstance(start_id, str):
            return
        pending = pending_slow_copies.pop(start_id, None)
        if pending is None:
            return
        target, final_path = pending
        self.current_paths[target] = final_path

    def _project_archive_file(self, event: Mapping[str, object]) -> None:
        target = event.get("target")
        if not isinstance(target, str):
            return
        try:
            destination = self.archive_file_destination(event)
        except ValueError:
            return
        if destination is None:
            return
        self.current_paths[target] = destination

    def _project_move_between_roots(self, event: Mapping[str, object]) -> None:
        target = event.get("target")
        if not isinstance(target, str):
            return
        try:
            destination = self.move_between_roots_destination(event)
        except ValueError:
            return
        if destination is None:
            return
        self.current_paths[target] = destination

    def _project_remux_container(self, event: Mapping[str, object]) -> None:
        target = event.get("target")
        to_container = event.get("to_container")
        if not isinstance(target, str) or not isinstance(to_container, str):
            return
        current_path = self.current_paths.get(target)
        if current_path is None:
            return
        self.current_paths[target] = self._swap_extension(current_path, to_container)

    def _refresh_paths(
        self, asset_ids: set[str], before: Mapping[str, str | None]
    ) -> dict[str, tuple[str | None, str | None]]:
        changes: dict[str, tuple[str | None, str | None]] = {}
        for asset_id in asset_ids:
            if asset_id not in self._renderer_managed_asset_ids:
                continue
            old_path = before.get(asset_id)
            if old_path is None:
                continue
            new_path = self.render_asset_path(asset_id)
            if new_path is None:
                self.current_paths.pop(asset_id, None)
            else:
                self.current_paths[asset_id] = new_path
            if old_path != new_path:
                changes[asset_id] = (old_path, new_path)
        return changes

    def _asset_ids_for_season(self, season_id: str) -> set[str]:
        season = self.seasons.get(season_id)
        if season is None:
            return set()
        asset_ids: set[str] = set()
        for episode_id in season.episode_ids:
            episode = self.episodes.get(episode_id)
            if episode is not None:
                asset_ids.update(episode.asset_ids)
        return asset_ids

    def _asset_ids_for_disc(self, disc_id: str) -> set[str]:
        disc = self.discs.get(disc_id)
        if disc is None:
            return set()
        asset_ids: set[str] = set()
        for track_id in disc.track_ids:
            track = self.tracks.get(track_id)
            if track is not None:
                asset_ids.update(track.asset_ids)
        return asset_ids

    def _render_episode_asset(self, tail: _AssetTail, *, root_path: str) -> str | None:
        episode = self.episodes[tail.parent_id]
        season = self.seasons.get(episode.season_id)
        if season is None:
            return None
        series = self.series.get(season.series_id)
        if series is None:
            return None
        context = RenderableAssetContext(
            parent_kind=ParentKind.EPISODE,
            root_path=root_path,
            layout=series.layout,
            naming=series.episode_naming,
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
            variant_label=tail.variant_label,
            asset_role=tail.asset_role,
            asset_container=tail.asset_container,
            bundle_asset_count=tail.bundle_asset_count,
        )
        return render_asset_path(context)

    def _render_track_asset(self, tail: _AssetTail, *, root_path: str) -> str | None:
        track = self.tracks[tail.parent_id]
        disc = self.discs.get(track.disc_id)
        if disc is None:
            return None
        album = self.albums.get(disc.album_id)
        artist = self.artists.get(album.artist_id) if album is not None else None
        if album is None or artist is None:
            return None
        context = RenderableAssetContext(
            parent_kind=ParentKind.TRACK,
            root_path=root_path,
            layout=artist.layout,
            naming=artist.track_naming,
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
            variant_label=tail.variant_label,
            asset_role=tail.asset_role,
            asset_container=tail.asset_container,
            bundle_asset_count=tail.bundle_asset_count,
        )
        return render_asset_path(context)

    def _render_podcast_asset(self, tail: _AssetTail, *, root_path: str) -> str | None:
        episode = self.podcast_episodes[tail.parent_id]
        podcast = self.podcasts.get(episode.podcast_id)
        if podcast is None:
            return None
        context = RenderableAssetContext(
            parent_kind=ParentKind.PODCAST_EPISODE,
            root_path=root_path,
            layout=podcast.layout,
            naming=podcast.episode_naming,
            podcast_title=podcast.title,
            published_at=episode.published_at,
            episode_slug=episode.slug,
            episode_title=episode.title,
            variant_label=tail.variant_label,
            asset_role=tail.asset_role,
            asset_container=tail.asset_container,
            bundle_asset_count=tail.bundle_asset_count,
        )
        return render_asset_path(context)

    def _archive_base_path(self, raw: Mapping[str, object]) -> str | None:
        if self.root_path is None:
            return None
        library = _as_mapping(raw.get("library"))
        archive_root = library.get("archive_root") if library is not None else None
        if archive_root is None or archive_root == "archive":
            return f"{self.root_path}/archive"
        if isinstance(archive_root, str):
            return self.root_paths.get(archive_root)
        return None

    def _current_root_for_path(self, path: str) -> str | None:
        root_paths: list[str] = list(self.root_paths.values())
        root_paths.sort(key=len, reverse=True)
        for root_path in root_paths:
            if path == root_path or path.startswith(f"{root_path}/"):
                return root_path
        return None

    @staticmethod
    def _swap_extension(path: str, new_ext: str) -> str:
        """Replace the path's file extension with ``new_ext`` (no leading dot)."""
        basename = path.rsplit("/", 1)[-1]
        if "." in basename:
            base = path.rsplit(".", 1)[0]
            return f"{base}.{new_ext}"
        return f"{path}.{new_ext}"

    @staticmethod
    def _move_list_item(source: list[str], value: str, destination: list[str]) -> None:
        with suppress(ValueError):
            source.remove(value)
        if value not in destination:
            destination.append(value)


def build_hierarchy_projection(raw: Mapping[str, object]) -> HierarchyProjection:
    """Build a mutable hierarchy projection for timeline-walking rules."""
    return HierarchyProjection(raw)


def is_hierarchy_action(action: object) -> bool:
    """Return whether ``action`` is a hierarchy timeline mutation."""
    return action in HIERARCHY_TIMELINE_ACTIONS
