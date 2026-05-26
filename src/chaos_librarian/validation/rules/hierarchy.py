"""Domain hierarchy semantic validation for Scenario v12."""

from __future__ import annotations

import enum
import os
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    ArtistLayout,
    EpisodeNaming,
    SeriesLayout,
    TimelineActionName,
    TrackNaming,
)
from chaos_librarian.path_rendering import RenderableAssetContext, render_asset_path
from chaos_librarian.validation.codes import (
    E_HIERARCHY_INVALID,
    E_MATERIALIZE_UNSUPPORTED,
    E_PATH_COLLISION,
    format_jsonpath,
)
from chaos_librarian.validation.rules._common import (
    RawAssetContext,
    Reporter,
    _as_list,
    _as_mapping,
    _iter_timeline_events,
    _Loc,
    iter_asset_contexts,
    primary_root_path,
    rendered_asset_paths,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = [
    "build_hierarchy_projection",
    "rule_hierarchy_invariants",
    "rule_hierarchy_timeline",
    "rule_media_action_compatible_with_parent",
    "rule_rendered_path_collisions",
]


def rule_hierarchy_invariants(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject hierarchy numbering conflicts and naming recipe dependency gaps."""
    reporter = Reporter(collector=collector, line_index=line_index)
    _check_series(raw, reporter)
    _check_artists(raw, reporter)


def rule_rendered_path_collisions(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject duplicate rendered initial media paths."""
    reporter = Reporter(collector=collector, line_index=line_index)
    seen: dict[str, tuple[str, _Loc]] = {}
    for asset_id, (path, loc) in rendered_asset_paths(raw).items():
        normalized = os.path.normpath(path)
        if normalized in seen:
            first_asset_id, first_loc = seen[normalized]
            first_path = format_jsonpath(first_loc)
            reporter.error(
                code=E_PATH_COLLISION,
                message=(
                    f"rendered initial path {normalized!r} for asset {asset_id!r} "
                    f"collides with asset {first_asset_id!r} at {first_path}"
                ),
                loc=loc,
            )
        else:
            seen[normalized] = (asset_id, loc)


def rule_hierarchy_timeline(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Replay hierarchy timeline actions and reject invalid projected states."""
    reporter = Reporter(collector=collector, line_index=line_index)
    projection = build_hierarchy_projection(raw)
    pending_slow_copies: dict[str, tuple[str, str]] = {}
    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        if not _is_hierarchy_action(action):
            _project_non_hierarchy_current_path(
                event, projection.current_paths, pending_slow_copies
            )
            continue
        mutation = projection.apply(event)
        _check_hierarchy_mutation_numbers(
            projection=projection,
            mutation=mutation,
            event_idx=idx,
            reporter=reporter,
        )
        _check_hierarchy_path_collisions(
            projection=projection,
            mutation=mutation,
            event_idx=idx,
            reporter=reporter,
        )


def rule_media_action_compatible_with_parent(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject media stream actions that cannot apply to the target's parent kind."""
    reporter = Reporter(collector=collector, line_index=line_index)
    assets_by_id = _asset_contexts_by_id(raw)
    for idx, event in _iter_timeline_events(raw):
        target = event.get("target")
        if not isinstance(target, str):
            continue
        context = assets_by_id.get(target)
        if context is None or context.parent_kind != ParentKind.TRACK.value:
            continue
        _check_track_media_action(event=event, event_idx=idx, reporter=reporter)


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


@dataclass(frozen=True, slots=True)
class HierarchyMutation:
    affected_asset_ids: frozenset[str]
    affected_season_ids: frozenset[str]
    affected_album_ids: frozenset[str]
    affected_disc_ids: frozenset[str]
    path_changes: Mapping[str, tuple[str | None, str | None]]


class HierarchyProjection:
    """Mutable validation-only projection for hierarchy timeline actions."""

    def __init__(self, raw: Mapping[str, object]) -> None:
        self.root_path = primary_root_path(raw)
        self.series: dict[str, _SeriesState] = {}
        self.seasons: dict[str, _SeasonState] = {}
        self.episodes: dict[str, _EpisodeState] = {}
        self.artists: dict[str, _ArtistState] = {}
        self.albums: dict[str, _AlbumState] = {}
        self.discs: dict[str, _DiscState] = {}
        self.tracks: dict[str, _TrackState] = {}
        self.assets: dict[str, _AssetTail] = {}
        self.current_paths = {
            asset_id: path for asset_id, (path, _loc) in rendered_asset_paths(raw).items()
        }
        self._seed_series(raw)
        self._seed_artists(raw)
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
        path_changes = self._refresh_paths(affected_assets, before)
        return HierarchyMutation(
            affected_asset_ids=frozenset(affected_assets),
            affected_season_ids=frozenset(seasons),
            affected_album_ids=frozenset(albums),
            affected_disc_ids=frozenset(discs),
            path_changes=path_changes,
        )

    def affected_asset_ids(self, event: Mapping[str, object]) -> set[str]:
        """Return assets under the hierarchy entity targeted by ``event``."""
        target = event.get("target")
        if not isinstance(target, str):
            return set()
        action = event.get("action")
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
        return set()

    def render_asset_path(self, asset_id: str) -> str | None:
        """Render one asset from the current hierarchy snapshot."""
        if self.root_path is None:
            return None
        tail = self.assets.get(asset_id)
        if tail is None:
            return None
        try:
            if tail.parent_id in self.episodes:
                return self._render_episode_asset(tail)
            if tail.parent_id in self.tracks:
                return self._render_track_asset(tail)
        except ValueError:
            return None
        return self.current_paths.get(asset_id)

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

    def _refresh_paths(
        self, asset_ids: set[str], before: Mapping[str, str | None]
    ) -> dict[str, tuple[str | None, str | None]]:
        changes: dict[str, tuple[str | None, str | None]] = {}
        for asset_id in asset_ids:
            new_path = self.render_asset_path(asset_id)
            if new_path is None:
                self.current_paths.pop(asset_id, None)
            else:
                self.current_paths[asset_id] = new_path
            old_path = before.get(asset_id)
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

    def _render_episode_asset(self, tail: _AssetTail) -> str | None:
        episode = self.episodes[tail.parent_id]
        season = self.seasons.get(episode.season_id)
        if season is None or self.root_path is None:
            return None
        series = self.series.get(season.series_id)
        if series is None:
            return None
        context = RenderableAssetContext(
            parent_kind=ParentKind.EPISODE,
            root_path=self.root_path,
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

    def _render_track_asset(self, tail: _AssetTail) -> str | None:
        track = self.tracks[tail.parent_id]
        disc = self.discs.get(track.disc_id)
        if disc is None or self.root_path is None:
            return None
        album = self.albums.get(disc.album_id)
        artist = self.artists.get(album.artist_id) if album is not None else None
        if album is None or artist is None:
            return None
        context = RenderableAssetContext(
            parent_kind=ParentKind.TRACK,
            root_path=self.root_path,
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

    @staticmethod
    def _move_list_item(source: list[str], value: str, destination: list[str]) -> None:
        with suppress(ValueError):
            source.remove(value)
        if value not in destination:
            destination.append(value)


def build_hierarchy_projection(raw: Mapping[str, object]) -> HierarchyProjection:
    """Build a mutable hierarchy projection for timeline-walking rules."""
    return HierarchyProjection(raw)


def _check_hierarchy_mutation_numbers(
    *,
    projection: HierarchyProjection,
    mutation: HierarchyMutation,
    event_idx: int,
    reporter: Reporter,
) -> None:
    for season_id in mutation.affected_season_ids:
        _check_projected_episode_numbers(
            projection=projection,
            season_id=season_id,
            event_idx=event_idx,
            reporter=reporter,
        )
    for album_id in mutation.affected_album_ids:
        _check_projected_disc_numbers(
            projection=projection,
            album_id=album_id,
            event_idx=event_idx,
            reporter=reporter,
        )
    for disc_id in mutation.affected_disc_ids:
        _check_projected_track_numbers(
            projection=projection,
            disc_id=disc_id,
            event_idx=event_idx,
            reporter=reporter,
        )


def _check_projected_episode_numbers(
    *,
    projection: HierarchyProjection,
    season_id: str,
    event_idx: int,
    reporter: Reporter,
) -> None:
    season = projection.seasons.get(season_id)
    if season is None:
        return
    seen: set[int] = set()
    for episode_id in season.episode_ids:
        episode = projection.episodes.get(episode_id)
        if episode is None:
            continue
        if episode.episode_number in seen:
            _report_error(
                reporter,
                "duplicate episode_number after hierarchy action",
                _event_loc(event_idx),
            )
            return
        seen.add(episode.episode_number)


def _check_projected_disc_numbers(
    *,
    projection: HierarchyProjection,
    album_id: str,
    event_idx: int,
    reporter: Reporter,
) -> None:
    seen: set[int] = set()
    for disc in projection.discs.values():
        if disc.album_id != album_id:
            continue
        if disc.disc_number in seen:
            _report_error(
                reporter,
                "duplicate disc_number after hierarchy action",
                _event_loc(event_idx),
            )
            return
        seen.add(disc.disc_number)


def _check_projected_track_numbers(
    *,
    projection: HierarchyProjection,
    disc_id: str,
    event_idx: int,
    reporter: Reporter,
) -> None:
    disc = projection.discs.get(disc_id)
    if disc is None:
        return
    seen: set[int] = set()
    for track_id in disc.track_ids:
        track = projection.tracks.get(track_id)
        if track is None:
            continue
        if track.track_number in seen:
            _report_error(
                reporter,
                "duplicate track_number after hierarchy action",
                _event_loc(event_idx),
            )
            return
        seen.add(track.track_number)


def _check_hierarchy_path_collisions(
    *,
    projection: HierarchyProjection,
    mutation: HierarchyMutation,
    event_idx: int,
    reporter: Reporter,
) -> None:
    if not mutation.affected_asset_ids:
        return
    outside_paths = {
        _normalize(path): asset_id
        for asset_id, path in projection.current_paths.items()
        if asset_id not in mutation.affected_asset_ids
    }
    seen_inside: dict[str, str] = {}
    for asset_id in mutation.affected_asset_ids:
        path = projection.current_paths.get(asset_id)
        if path is None:
            continue
        normalized = _normalize(path)
        outside_asset_id = outside_paths.get(normalized)
        if outside_asset_id is not None:
            _report_projected_path_collision(reporter, path, asset_id, outside_asset_id, event_idx)
        elif normalized in seen_inside:
            _report_projected_path_collision(
                reporter, path, asset_id, seen_inside[normalized], event_idx
            )
        else:
            seen_inside[normalized] = asset_id


def _report_projected_path_collision(
    reporter: Reporter, path: str, asset_id: str, other_asset_id: str, event_idx: int
) -> None:
    reporter.error(
        code=E_PATH_COLLISION,
        message=(
            f"rendered hierarchy path {path!r} for asset {asset_id!r} "
            f"collides with asset {other_asset_id!r}"
        ),
        loc=_event_loc(event_idx),
    )


def _project_non_hierarchy_current_path(
    event: Mapping[str, object],
    current_paths: dict[str, str],
    pending_slow_copies: dict[str, tuple[str, str]],
) -> None:
    action = event.get("action")
    if action in {
        TimelineActionName.MOVE_ASSET,
        TimelineActionName.RENAME_FILE,
        TimelineActionName.ADD_FILE,
    }:
        _project_to_field_path(event, current_paths)
    elif action == TimelineActionName.DELETE_FILE:
        target = event.get("target")
        if isinstance(target, str):
            current_paths.pop(target, None)
    elif action == TimelineActionName.SLOW_COPY_START:
        _project_slow_copy_start(event, pending_slow_copies)
    elif action == TimelineActionName.SLOW_COPY_COMMIT:
        _project_slow_copy_commit(event, pending_slow_copies, current_paths)
    elif action == TimelineActionName.REMUX_CONTAINER:
        _project_remux_container(event, current_paths)


def _project_to_field_path(event: Mapping[str, object], current_paths: dict[str, str]) -> None:
    target = event.get("target")
    path = event.get("to")
    if isinstance(target, str) and isinstance(path, str):
        current_paths[target] = path


def _project_slow_copy_start(
    event: Mapping[str, object],
    pending_slow_copies: dict[str, tuple[str, str]],
) -> None:
    event_id = event.get("id")
    target = event.get("target")
    final_path = event.get("to")
    if isinstance(event_id, str) and isinstance(target, str) and isinstance(final_path, str):
        pending_slow_copies[event_id] = (target, final_path)


def _project_slow_copy_commit(
    event: Mapping[str, object],
    pending_slow_copies: dict[str, tuple[str, str]],
    current_paths: dict[str, str],
) -> None:
    start_id = event.get("for")
    if not isinstance(start_id, str):
        return
    pending = pending_slow_copies.pop(start_id, None)
    if pending is None:
        return
    target, final_path = pending
    current_paths[target] = final_path


def _project_remux_container(event: Mapping[str, object], current_paths: dict[str, str]) -> None:
    target = event.get("target")
    to_container = event.get("to_container")
    if not isinstance(target, str) or not isinstance(to_container, str):
        return
    current_path = current_paths.get(target)
    if current_path is None:
        return
    current_paths[target] = _swap_extension(current_path, to_container)


def _swap_extension(path: str, new_ext: str) -> str:
    basename = path.rsplit("/", 1)[-1]
    if "." in basename:
        base = path.rsplit(".", 1)[0]
        return f"{base}.{new_ext}"
    return f"{path}.{new_ext}"


def _is_hierarchy_action(action: object) -> bool:
    return action in {
        TimelineActionName.RENUMBER_EPISODE,
        TimelineActionName.MOVE_EPISODE_TO_SEASON,
        TimelineActionName.RENAME_SEASON,
        TimelineActionName.RENUMBER_DISC,
        TimelineActionName.MOVE_TRACK_TO_DISC,
    }


def _event_loc(event_idx: int) -> _Loc:
    return ("timeline", event_idx, "action")


def _normalize(path: str) -> str:
    return os.path.normpath(path)


def _str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _int(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _date(value: object) -> date | None:
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _enum[T: enum.StrEnum](enum_type: type[T], value: object) -> T | None:
    if not isinstance(value, str):
        return None
    try:
        return enum_type(value)
    except ValueError:
        return None


def _check_series(raw: Mapping[str, object], reporter: Reporter) -> None:
    series_items = _as_list(raw.get("series"))
    if series_items is None:
        return
    for s_idx, series_obj in enumerate(series_items):
        series = _as_mapping(series_obj)
        if series is None:
            continue
        naming = series.get("episode_naming")
        seasons = _as_list(series.get("seasons"))
        if seasons is None:
            continue
        for season_idx, season_obj in enumerate(seasons):
            season = _as_mapping(season_obj)
            if season is None:
                continue
            _check_season(
                season=season,
                season_loc=("series", s_idx, "seasons", season_idx),
                episode_naming=naming,
                reporter=reporter,
            )


def _check_season(
    *,
    season: Mapping[str, object],
    season_loc: _Loc,
    episode_naming: object,
    reporter: Reporter,
) -> None:
    episodes = _as_list(season.get("episodes"))
    if episodes is None:
        return
    seen: set[int] = set()
    for ep_idx, episode_obj in enumerate(episodes):
        episode = _as_mapping(episode_obj)
        if episode is None:
            continue
        episode_loc = (*season_loc, "episodes", ep_idx)
        episode_number = episode.get("episode_number")
        if isinstance(episode_number, int) and not isinstance(episode_number, bool):
            if episode_number in seen:
                _report_error(
                    reporter,
                    "duplicate episode_number",
                    (*episode_loc, "episode_number"),
                )
            else:
                seen.add(episode_number)
        _check_episode_naming(
            episode=episode,
            episode_loc=episode_loc,
            episode_naming=episode_naming,
            reporter=reporter,
        )


def _check_episode_naming(
    *,
    episode: Mapping[str, object],
    episode_loc: _Loc,
    episode_naming: object,
    reporter: Reporter,
) -> None:
    if episode_naming == EpisodeNaming.DATE_TITLE.value and not _is_date_value(
        episode.get("aired_on")
    ):
        _report_error(reporter, "date_title episodes require aired_on", (*episode_loc, "aired_on"))
    if episode_naming == EpisodeNaming.ABSOLUTE_3_DIGIT_TITLE.value:
        absolute_number = episode.get("absolute_number")
        if not _is_positive_int(absolute_number):
            _report_error(
                reporter,
                "absolute_3_digit_title episodes require positive absolute_number",
                (*episode_loc, "absolute_number"),
            )


def _check_artists(raw: Mapping[str, object], reporter: Reporter) -> None:
    artists = _as_list(raw.get("artists"))
    if artists is None:
        return
    for artist_idx, artist_obj in enumerate(artists):
        artist = _as_mapping(artist_obj)
        if artist is None:
            continue
        albums = _as_list(artist.get("albums"))
        if albums is None:
            continue
        for album_idx, album_obj in enumerate(albums):
            album = _as_mapping(album_obj)
            if album is None:
                continue
            _check_album(
                album=album,
                album_loc=("artists", artist_idx, "albums", album_idx),
                reporter=reporter,
            )


def _check_album(
    *,
    album: Mapping[str, object],
    album_loc: _Loc,
    reporter: Reporter,
) -> None:
    discs = _as_list(album.get("discs"))
    if discs is None:
        return
    seen: set[int] = set()
    for disc_idx, disc_obj in enumerate(discs):
        disc = _as_mapping(disc_obj)
        if disc is None:
            continue
        disc_loc = (*album_loc, "discs", disc_idx)
        disc_number = disc.get("disc_number")
        if isinstance(disc_number, int) and not isinstance(disc_number, bool):
            if disc_number in seen:
                _report_error(reporter, "duplicate disc_number", (*disc_loc, "disc_number"))
            else:
                seen.add(disc_number)
        _check_disc_tracks(disc=disc, disc_loc=disc_loc, reporter=reporter)


def _check_disc_tracks(
    *,
    disc: Mapping[str, object],
    disc_loc: _Loc,
    reporter: Reporter,
) -> None:
    tracks = _as_list(disc.get("tracks"))
    if tracks is None:
        return
    seen: set[int] = set()
    for track_idx, track_obj in enumerate(tracks):
        track = _as_mapping(track_obj)
        if track is None:
            continue
        track_number = track.get("track_number")
        if not isinstance(track_number, int) or isinstance(track_number, bool):
            continue
        track_loc = (*disc_loc, "tracks", track_idx, "track_number")
        if track_number in seen:
            _report_error(reporter, "duplicate track_number", track_loc)
        else:
            seen.add(track_number)


def _asset_contexts_by_id(raw: Mapping[str, object]) -> dict[str, RawAssetContext]:
    contexts: dict[str, RawAssetContext] = {}
    for context in iter_asset_contexts(raw):
        asset_id = context.asset.get("id")
        if isinstance(asset_id, str):
            contexts[asset_id] = context
    return contexts


def _check_track_media_action(
    *,
    event: Mapping[str, object],
    event_idx: int,
    reporter: Reporter,
) -> None:
    action = event.get("action")
    if action == TimelineActionName.REENCODE_VIDEO or action in {
        TimelineActionName.EMBED_SUBTITLE,
        TimelineActionName.EXTRACT_SUBTITLE,
    }:
        _report_media_action_error(reporter, action, ("timeline", event_idx, "target"))
    elif action == TimelineActionName.CORRUPT_PACKET_RANGE:
        _check_track_packet_range_action(event=event, event_idx=event_idx, reporter=reporter)


def _check_track_packet_range_action(
    *,
    event: Mapping[str, object],
    event_idx: int,
    reporter: Reporter,
) -> None:
    stream = event.get("stream")
    if stream not in {"video", "subtitle"}:
        return
    _report_media_action_error(
        reporter,
        event.get("action"),
        ("timeline", event_idx, "stream"),
    )


def _report_media_action_error(reporter: Reporter, action: object, loc: _Loc) -> None:
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message=f"{action!r} is not supported for track assets",
        loc=loc,
    )


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_date_value(value: object) -> bool:
    return isinstance(value, str | date)


def _report_error(reporter: Reporter, message: str, loc: _Loc) -> None:
    reporter.error(code=E_HIERARCHY_INVALID, message=message, loc=loc)
