"""Shared types, raw-data narrowing helpers, and cross-rule walkers for
``validation/rules/``.

Every rule module in this subpackage imports the ``Rule`` callable type
and the shape-narrowing helpers from here. ``IssueCollector`` and
``LineIndex`` are kept behind ``TYPE_CHECKING`` because importing them
at runtime would re-introduce the ``pipeline → semantic → rules →
pipeline`` import cycle that the package layout is designed to avoid.

The ``iter_*`` walkers and ``NS_*`` namespace constants live here so that
rule modules depend on each other only through ``semantic.py``'s
``_RULES`` registry, never through direct imports of cross-cutting
walkers. See issue #27.
"""

from __future__ import annotations

import enum
from collections.abc import Callable, Iterator, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING, Final, cast

from chaos_librarian.clock import DurationParseError, parse_duration
from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    ArtistLayout,
    EpisodeNaming,
    MovieLayout,
    SeriesLayout,
    SidecarKind,
    TimelineActionName,
    TrackNaming,
)
from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.path_rendering import (
    RenderableAssetContext,
    render_asset_path,
    render_declared_sidecar_path,
    replace_root_prefix,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = [
    "NS_ALBUM_ID",
    "NS_ARTIST_ID",
    "NS_ASSET_ID",
    "NS_BUNDLE_ID",
    "NS_DISC_ID",
    "NS_EPISODE_ID",
    "NS_MOVIE_ID",
    "NS_SEASON_ID",
    "NS_SERIES_ID",
    "NS_TRACK_ID",
    "NS_VARIANT_ID",
    "DeclaredSidecar",
    "HierarchyMutation",
    "HierarchyProjection",
    "RawAssetContext",
    "Reporter",
    "Rule",
    "_Loc",
    "_RawMapping",
    "_as_list",
    "_as_mapping",
    "_iter_timeline_events",
    "_list_at_path",
    "build_hierarchy_projection",
    "entity_ids_by_kind",
    "is_hierarchy_action",
    "iter_asset_contexts",
    "iter_asset_ids",
    "iter_assets_with_loc",
    "iter_declared_roots",
    "iter_declared_sidecars",
    "iter_entity_ids",
    "iter_global_namespaces",
    "primary_root_path",
    "renderable_context_for",
    "rendered_asset_paths",
    "try_parse_duration",
]


_Loc = tuple[str | int, ...]
_RawMapping = Mapping[str, object]
Rule = Callable[[_RawMapping, "LineIndex", "IssueCollector"], None]


@dataclass(frozen=True, slots=True)
class Reporter:
    """Binds ``collector`` + ``line_index`` once per rule invocation.

    Replaces 5-kwarg ``collector.add(code=..., severity=...,
    message=..., loc=..., line_index=line_index)`` sites with 3-kwarg
    ``reporter.error(code=..., message=..., loc=...)``. Internal
    rule helpers thread one ``reporter`` arg instead of carrying
    ``collector`` and ``line_index`` separately.
    """

    collector: IssueCollector
    line_index: LineIndex

    def error(self, *, code: str, message: str, loc: _Loc) -> None:
        self.collector.add(
            code=code,
            severity=ValidationSeverity.ERROR,
            message=message,
            loc=loc,
            line_index=self.line_index,
        )

    def warning(self, *, code: str, message: str, loc: _Loc) -> None:
        self.collector.add(
            code=code,
            severity=ValidationSeverity.WARNING,
            message=message,
            loc=loc,
            line_index=self.line_index,
        )


@dataclass(frozen=True, slots=True)
class DeclaredSidecar:
    """One declared sidecar-mode subtitle projected from the raw scenario tree."""

    asset_id: str
    path: str
    kind: str
    language: str | None


@dataclass(frozen=True, slots=True)
class RawAssetContext:
    """One raw asset plus its surrounding hierarchy and YAML-path locations."""

    asset: _RawMapping
    asset_loc: _Loc
    parent_kind: str
    parent_id: str
    movie: _RawMapping | None
    movie_loc: _Loc | None
    series: _RawMapping | None
    series_loc: _Loc | None
    season: _RawMapping | None
    season_loc: _Loc | None
    episode: _RawMapping | None
    episode_loc: _Loc | None
    artist: _RawMapping | None
    artist_loc: _Loc | None
    album: _RawMapping | None
    album_loc: _Loc | None
    disc: _RawMapping | None
    disc_loc: _Loc | None
    track: _RawMapping | None
    track_loc: _Loc | None
    variant: _RawMapping
    variant_loc: _Loc
    bundle: _RawMapping
    bundle_loc: _Loc
    bundle_asset_count: int


# Typo-safe namespace keys for ``iter_global_namespaces`` callers — string
# literals would silently break the namespace filter / per-namespace dicts.
NS_MOVIE_ID: Final = "movie_id"
NS_SERIES_ID: Final = "series_id"
NS_SEASON_ID: Final = "season_id"
NS_EPISODE_ID: Final = "episode_id"
NS_ARTIST_ID: Final = "artist_id"
NS_ALBUM_ID: Final = "album_id"
NS_DISC_ID: Final = "disc_id"
NS_TRACK_ID: Final = "track_id"
NS_VARIANT_ID: Final = "variant_id"
NS_BUNDLE_ID: Final = "bundle_id"
NS_ASSET_ID: Final = "asset_id"


def _as_mapping(node: object) -> _RawMapping | None:
    """Narrow an ``object`` to ``Mapping[str, object]`` for safe ``.get`` calls.

    Returns None when ``node`` is non-mapping so the rule can skip the malformed
    sub-tree (Pydantic's shape pass owns the E_FIELD_TYPE report). ``cast`` is
    needed because ``isinstance`` against a generic alias is erased at runtime.
    """
    if isinstance(node, Mapping):
        return cast("_RawMapping", node)
    return None


def _as_list(node: object) -> list[object] | None:
    """Narrow an ``object`` to ``list[object]``; mirror of ``_as_mapping``."""
    if isinstance(node, list):
        return cast("list[object]", node)
    return None


def _list_at_path(raw: _RawMapping, path_parts: tuple[str, ...]) -> list[object] | None:
    """Walk ``path_parts`` from ``raw`` and return the list at the end, or None."""
    node: object = raw
    for part in path_parts:
        parent = _as_mapping(node)
        if parent is None:
            return None
        node = parent.get(part)
    return _as_list(node)


def _iter_timeline_events(raw: _RawMapping) -> Iterator[tuple[int, _RawMapping]]:
    """Yield ``(idx, event)`` for each well-shaped event under ``raw["timeline"]``.

    Centralizes the iterate-and-narrow preamble every timeline-walking rule
    needs. Malformed events (non-mapping) are skipped silently — the shape
    pass already reported them.
    """
    timeline = _as_list(raw.get("timeline"))
    if timeline is None:
        return
    for idx, event_obj in enumerate(timeline):
        event = _as_mapping(event_obj)
        if event is None:
            continue
        yield idx, event


def try_parse_duration(raw_str: str) -> int | None:
    """Parse a duration string; return None instead of raising.

    Rules that re-parse a duration string for arithmetic (5b: slow-copy
    timing, 7: timeline order) need to skip pairs where the input is
    malformed — Rule 3 has already flagged those with E_DURATION_SYNTAX,
    and re-reporting them as order/timing failures would be noise.
    """
    try:
        return parse_duration(raw_str)
    except DurationParseError:
        return None


def iter_declared_roots(raw: _RawMapping) -> Iterator[tuple[str, str | None]]:
    """Yield ``(root_id, root_path)`` for each well-shaped ``library.roots[]`` entry.

    ``root_id`` is guaranteed to be a string (entries with non-string ids
    are skipped — Pydantic's shape pass owns those errors). ``root_path``
    is ``None`` when the entry's ``path`` field is missing or non-string;
    callers needing both fields filter on ``p is not None``.
    """
    for root_obj in _list_at_path(raw, ("library", "roots")) or []:
        root = _as_mapping(root_obj)
        if root is None:
            continue
        root_id = root.get("id")
        if not isinstance(root_id, str):
            continue
        path = root.get("path")
        yield root_id, path if isinstance(path, str) else None


def primary_root_path(raw: _RawMapping) -> str | None:
    """Return ``library.roots[0].path`` if well-shaped, else ``None``.

    Mirrors ``build_initial_state``'s primary-root convention: the engine
    synthesizes every initial asset location under
    ``<library.roots[0].path>/...``. Strictly inspects the *first* entry —
    if it's malformed, returns ``None`` rather than falling through to a
    later root (the engine would have failed on ``roots[0]`` too). Returns
    ``None`` when the library is empty or the first entry's path doesn't
    narrow to a string — Pydantic's shape pass owns those errors.
    """
    roots = _list_at_path(raw, ("library", "roots")) or []
    if not roots:
        return None
    primary = _as_mapping(roots[0])
    if primary is None:
        return None
    path = primary.get("path")
    return path if isinstance(path, str) else None


def iter_global_namespaces(
    raw: _RawMapping,
) -> Iterator[tuple[str, str, _Loc]]:
    """Yield ``(namespace, id_value, loc)`` for every hierarchy and tail id.

    Walks Scenario v12 movie, series, and artist hierarchy tails in declaration
    order and skips malformed sub-trees whose shape Pydantic would have rejected.
    Root and timeline ids are intentionally handled by ``id_duplicate.py``.
    """
    yield from iter_entity_ids(raw)


def iter_asset_ids(raw: _RawMapping) -> Iterator[str]:
    """Yield every ``asset_id`` value defined in the scenario.

    Implemented as a filter over ``iter_asset_contexts`` so asset-targeted
    rules share exactly one raw hierarchy traversal.
    """
    for context in iter_asset_contexts(raw):
        asset_id = context.asset.get("id")
        if isinstance(asset_id, str):
            yield asset_id


def iter_assets_with_loc(
    raw: _RawMapping,
) -> Iterator[tuple[_RawMapping, _Loc]]:
    """Yield ``(asset_mapping, loc)`` for every well-shaped asset.

    Reuses ``iter_asset_contexts`` so rules inspect a single Scenario v12
    hierarchy walk.
    """
    for context in iter_asset_contexts(raw):
        yield context.asset, context.asset_loc


def iter_declared_sidecars(raw: _RawMapping) -> Iterator[DeclaredSidecar]:
    """Yield declared sidecar-mode subtitles using rendered asset paths."""
    root_path = primary_root_path(raw)
    if root_path is None:
        return
    for context in iter_asset_contexts(raw):
        asset = context.asset
        asset_id = asset.get("id")
        if not isinstance(asset_id, str):
            continue
        renderable = renderable_context_for(context, root_path)
        if renderable is None:
            continue
        for sub_obj in _as_list(asset.get("subtitles")) or []:
            sub = _as_mapping(sub_obj)
            if sub is None or sub.get("mode") != "sidecar":
                continue
            language = sub.get("language")
            if not isinstance(language, str):
                continue
            try:
                media_path = render_asset_path(renderable)
                path = render_declared_sidecar_path(media_path, language)
            except ValueError:
                continue
            yield DeclaredSidecar(
                asset_id=asset_id,
                path=path,
                kind=SidecarKind.SUBTITLE.value,
                language=language,
            )


def iter_entity_ids(raw: _RawMapping) -> Iterator[tuple[str, str, _Loc]]:
    """Yield hierarchy and tail ids in declaration order with raw locations."""
    yield from _iter_movie_entity_ids(raw)
    yield from _iter_series_entity_ids(raw)
    yield from _iter_artist_entity_ids(raw)


def entity_ids_by_kind(raw: _RawMapping) -> dict[str, set[str]]:
    """Return ``kind -> ids`` for hierarchy and tail ids."""
    ids: dict[str, set[str]] = {
        "movie": set(),
        "series": set(),
        "season": set(),
        "episode": set(),
        "artist": set(),
        "album": set(),
        "disc": set(),
        "track": set(),
        "variant": set(),
        "bundle": set(),
        "asset": set(),
    }
    for namespace, value, _loc in iter_global_namespaces(raw):
        kind = namespace.removesuffix("_id")
        ids[kind].add(value)
    return ids


def iter_asset_contexts(raw: _RawMapping) -> Iterator[RawAssetContext]:
    """Yield every well-shaped raw asset context in declaration order."""
    yield from _iter_movie_asset_contexts(raw)
    yield from _iter_episode_asset_contexts(raw)
    yield from _iter_track_asset_contexts(raw)


def renderable_context_for(
    raw_context: RawAssetContext, root_path: str
) -> RenderableAssetContext | None:
    """Convert a raw asset context to a renderer input, or None when incomplete."""
    parent_kind = _parent_kind(raw_context.parent_kind)
    if parent_kind is ParentKind.MOVIE:
        return _movie_renderable_context(raw_context, parent_kind, root_path)
    if parent_kind is ParentKind.EPISODE:
        return _episode_renderable_context(raw_context, parent_kind, root_path)
    if parent_kind is ParentKind.TRACK:
        return _track_renderable_context(raw_context, parent_kind, root_path)
    return None


def rendered_asset_paths(raw: _RawMapping) -> dict[str, tuple[str, _Loc]]:
    """Return ``asset_id -> (rendered_path, asset_loc)`` for renderable assets."""
    root_path = primary_root_path(raw)
    if root_path is None:
        return {}

    paths: dict[str, tuple[str, _Loc]] = {}
    for context in iter_asset_contexts(raw):
        asset_id = _str_field(context.asset, "id")
        renderable = renderable_context_for(context, root_path)
        if asset_id is None or renderable is None:
            continue
        try:
            paths[asset_id] = (render_asset_path(renderable), context.asset_loc)
        except ValueError:
            continue
    return paths


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
        self.assets: dict[str, _AssetTail] = {}
        initial_paths = rendered_asset_paths(raw)
        self.current_paths = {asset_id: path for asset_id, (path, _loc) in initial_paths.items()}
        self._renderer_managed_asset_ids = set(initial_paths)
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
        tail = self.assets.get(asset_id)
        if tail is None:
            return None
        root_path = self._render_root_path_for_asset(asset_id)
        if root_path is None:
            return None
        try:
            if tail.parent_id in self.episodes:
                return self._render_episode_asset(tail, root_path=root_path)
            if tail.parent_id in self.tracks:
                return self._render_track_asset(tail, root_path=root_path)
        except ValueError:
            return None
        return self.current_paths.get(asset_id)

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
        if not isinstance(target, str) or self.archive_base_path is None:
            return
        current_path = self.current_paths.get(target)
        if current_path is None:
            return
        current_root = self._current_root_for_path(current_path)
        if current_root is None:
            return
        try:
            self.current_paths[target] = replace_root_prefix(
                current_path,
                from_root=current_root,
                to_root=self.archive_base_path,
            )
        except ValueError:
            return

    def _project_move_between_roots(self, event: Mapping[str, object]) -> None:
        target = event.get("target")
        from_root_id = event.get("from_root_id")
        to_root_id = event.get("to_root_id")
        if not (
            isinstance(target, str)
            and isinstance(from_root_id, str)
            and isinstance(to_root_id, str)
        ):
            return
        current_path = self.current_paths.get(target)
        from_root = self.root_paths.get(from_root_id)
        to_root = self.root_paths.get(to_root_id)
        if current_path is None or from_root is None or to_root is None:
            return
        try:
            self.current_paths[target] = replace_root_prefix(
                current_path,
                from_root=from_root,
                to_root=to_root,
            )
        except ValueError:
            return

    def _project_remux_container(self, event: Mapping[str, object]) -> None:
        target = event.get("target")
        to_container = event.get("to_container")
        if not isinstance(target, str) or not isinstance(to_container, str):
            return
        current_path = self.current_paths.get(target)
        if current_path is None:
            return
        self.current_paths[target] = _swap_extension(current_path, to_container)

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
    def _move_list_item(source: list[str], value: str, destination: list[str]) -> None:
        with suppress(ValueError):
            source.remove(value)
        if value not in destination:
            destination.append(value)


def _swap_extension(path: str, new_ext: str) -> str:
    basename = path.rsplit("/", 1)[-1]
    if "." in basename:
        base = path.rsplit(".", 1)[0]
        return f"{base}.{new_ext}"
    return f"{path}.{new_ext}"


def build_hierarchy_projection(raw: Mapping[str, object]) -> HierarchyProjection:
    """Build a mutable hierarchy projection for timeline-walking rules."""
    return HierarchyProjection(raw)


def is_hierarchy_action(action: object) -> bool:
    """Return whether ``action`` is a hierarchy timeline mutation."""
    return action in {
        TimelineActionName.RENUMBER_EPISODE,
        TimelineActionName.MOVE_EPISODE_TO_SEASON,
        TimelineActionName.RENAME_SEASON,
        TimelineActionName.RENUMBER_DISC,
        TimelineActionName.MOVE_TRACK_TO_DISC,
    }


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


def _iter_movie_entity_ids(raw: _RawMapping) -> Iterator[tuple[str, str, _Loc]]:
    movies = _as_list(raw.get("movies"))
    if movies is None:
        return
    for m_idx, movie_obj in enumerate(movies):
        movie = _as_mapping(movie_obj)
        if movie is None:
            continue
        movie_loc: _Loc = ("movies", m_idx)
        yield from _entity_id(movie, namespace=NS_MOVIE_ID, loc=movie_loc)
        yield from _iter_variant_entity_ids(
            movie.get("variants"), variants_path=(*movie_loc, "variants")
        )


def _iter_series_entity_ids(raw: _RawMapping) -> Iterator[tuple[str, str, _Loc]]:
    series_items = _as_list(raw.get("series"))
    if series_items is None:
        return
    for s_idx, series_obj in enumerate(series_items):
        series = _as_mapping(series_obj)
        if series is None:
            continue
        series_loc: _Loc = ("series", s_idx)
        yield from _entity_id(series, namespace=NS_SERIES_ID, loc=series_loc)
        seasons = _as_list(series.get("seasons"))
        if seasons is None:
            continue
        for season_idx, season_obj in enumerate(seasons):
            season = _as_mapping(season_obj)
            if season is None:
                continue
            season_loc = (*series_loc, "seasons", season_idx)
            yield from _entity_id(season, namespace=NS_SEASON_ID, loc=season_loc)
            yield from _iter_episode_entity_ids(season, season_loc=season_loc)


def _iter_episode_entity_ids(
    season: _RawMapping, *, season_loc: _Loc
) -> Iterator[tuple[str, str, _Loc]]:
    episodes = _as_list(season.get("episodes"))
    if episodes is None:
        return
    for ep_idx, episode_obj in enumerate(episodes):
        episode = _as_mapping(episode_obj)
        if episode is None:
            continue
        episode_loc = (*season_loc, "episodes", ep_idx)
        yield from _entity_id(episode, namespace=NS_EPISODE_ID, loc=episode_loc)
        yield from _iter_variant_entity_ids(
            episode.get("variants"), variants_path=(*episode_loc, "variants")
        )


def _iter_artist_entity_ids(raw: _RawMapping) -> Iterator[tuple[str, str, _Loc]]:
    artists = _as_list(raw.get("artists"))
    if artists is None:
        return
    for artist_idx, artist_obj in enumerate(artists):
        artist = _as_mapping(artist_obj)
        if artist is None:
            continue
        artist_loc: _Loc = ("artists", artist_idx)
        yield from _entity_id(artist, namespace=NS_ARTIST_ID, loc=artist_loc)
        albums = _as_list(artist.get("albums"))
        if albums is None:
            continue
        for album_idx, album_obj in enumerate(albums):
            album = _as_mapping(album_obj)
            if album is None:
                continue
            album_loc = (*artist_loc, "albums", album_idx)
            yield from _entity_id(album, namespace=NS_ALBUM_ID, loc=album_loc)
            yield from _iter_disc_entity_ids(album, album_loc=album_loc)


def _iter_disc_entity_ids(
    album: _RawMapping, *, album_loc: _Loc
) -> Iterator[tuple[str, str, _Loc]]:
    discs = _as_list(album.get("discs"))
    if discs is None:
        return
    for disc_idx, disc_obj in enumerate(discs):
        disc = _as_mapping(disc_obj)
        if disc is None:
            continue
        disc_loc = (*album_loc, "discs", disc_idx)
        yield from _entity_id(disc, namespace=NS_DISC_ID, loc=disc_loc)
        yield from _iter_track_entity_ids(disc, disc_loc=disc_loc)


def _iter_track_entity_ids(disc: _RawMapping, *, disc_loc: _Loc) -> Iterator[tuple[str, str, _Loc]]:
    tracks = _as_list(disc.get("tracks"))
    if tracks is None:
        return
    for track_idx, track_obj in enumerate(tracks):
        track = _as_mapping(track_obj)
        if track is None:
            continue
        track_loc = (*disc_loc, "tracks", track_idx)
        yield from _entity_id(track, namespace=NS_TRACK_ID, loc=track_loc)
        yield from _iter_variant_entity_ids(
            track.get("variants"), variants_path=(*track_loc, "variants")
        )


def _entity_id(
    entity: _RawMapping, *, namespace: str, loc: _Loc
) -> Iterator[tuple[str, str, _Loc]]:
    value = entity.get("id")
    if isinstance(value, str):
        yield namespace, value, (*loc, "id")


def _iter_variant_entity_ids(
    variants_obj: object, *, variants_path: _Loc
) -> Iterator[tuple[str, str, _Loc]]:
    variants = _as_list(variants_obj)
    if variants is None:
        return
    for v_idx, variant_obj in enumerate(variants):
        variant = _as_mapping(variant_obj)
        if variant is None:
            continue
        variant_loc = (*variants_path, v_idx)
        yield from _entity_id(variant, namespace=NS_VARIANT_ID, loc=variant_loc)
        bundle = _as_mapping(variant.get("bundle"))
        if bundle is None:
            continue
        bundle_loc = (*variant_loc, "bundle")
        yield from _entity_id(bundle, namespace=NS_BUNDLE_ID, loc=bundle_loc)
        yield from _iter_bundle_assets(bundle.get("assets"), bundle_path=bundle_loc)


def _iter_bundle_assets(
    assets_obj: object, *, bundle_path: _Loc
) -> Iterator[tuple[str, str, _Loc]]:
    """Yield asset ids for each well-shaped asset under one bundle."""
    assets = _as_list(assets_obj)
    if assets is None:
        return
    for a_idx, asset_obj in enumerate(assets):
        asset = _as_mapping(asset_obj)
        if asset is None:
            continue
        a_id = asset.get("id")
        if isinstance(a_id, str):
            yield NS_ASSET_ID, a_id, (*bundle_path, "assets", a_idx, "id")


def _iter_movie_asset_contexts(raw: _RawMapping) -> Iterator[RawAssetContext]:
    movies = _as_list(raw.get("movies"))
    if movies is None:
        return
    for m_idx, movie_obj in enumerate(movies):
        movie = _as_mapping(movie_obj)
        if movie is None:
            continue
        movie_loc: _Loc = ("movies", m_idx)
        for tail in _iter_variant_asset_tail(movie.get("variants"), (*movie_loc, "variants")):
            yield RawAssetContext(
                asset=tail.asset,
                asset_loc=tail.asset_loc,
                parent_kind=ParentKind.MOVIE.value,
                parent_id=_id_or_empty(movie),
                movie=movie,
                movie_loc=movie_loc,
                series=None,
                series_loc=None,
                season=None,
                season_loc=None,
                episode=None,
                episode_loc=None,
                artist=None,
                artist_loc=None,
                album=None,
                album_loc=None,
                disc=None,
                disc_loc=None,
                track=None,
                track_loc=None,
                variant=tail.variant,
                variant_loc=tail.variant_loc,
                bundle=tail.bundle,
                bundle_loc=tail.bundle_loc,
                bundle_asset_count=tail.bundle_asset_count,
            )


def _iter_episode_asset_contexts(raw: _RawMapping) -> Iterator[RawAssetContext]:
    series_items = _as_list(raw.get("series"))
    if series_items is None:
        return
    for s_idx, series_obj in enumerate(series_items):
        series = _as_mapping(series_obj)
        if series is None:
            continue
        series_loc: _Loc = ("series", s_idx)
        yield from _iter_series_asset_contexts(series, series_loc=series_loc)


def _iter_series_asset_contexts(
    series: _RawMapping, *, series_loc: _Loc
) -> Iterator[RawAssetContext]:
    seasons = _as_list(series.get("seasons"))
    if seasons is None:
        return
    for season_idx, season_obj in enumerate(seasons):
        season = _as_mapping(season_obj)
        if season is None:
            continue
        season_loc = (*series_loc, "seasons", season_idx)
        yield from _iter_season_asset_contexts(
            series, series_loc=series_loc, season=season, season_loc=season_loc
        )


def _iter_season_asset_contexts(
    series: _RawMapping,
    *,
    series_loc: _Loc,
    season: _RawMapping,
    season_loc: _Loc,
) -> Iterator[RawAssetContext]:
    episodes = _as_list(season.get("episodes"))
    if episodes is None:
        return
    for ep_idx, episode_obj in enumerate(episodes):
        episode = _as_mapping(episode_obj)
        if episode is None:
            continue
        episode_loc = (*season_loc, "episodes", ep_idx)
        for tail in _iter_variant_asset_tail(episode.get("variants"), (*episode_loc, "variants")):
            yield RawAssetContext(
                asset=tail.asset,
                asset_loc=tail.asset_loc,
                parent_kind=ParentKind.EPISODE.value,
                parent_id=_id_or_empty(episode),
                movie=None,
                movie_loc=None,
                series=series,
                series_loc=series_loc,
                season=season,
                season_loc=season_loc,
                episode=episode,
                episode_loc=episode_loc,
                artist=None,
                artist_loc=None,
                album=None,
                album_loc=None,
                disc=None,
                disc_loc=None,
                track=None,
                track_loc=None,
                variant=tail.variant,
                variant_loc=tail.variant_loc,
                bundle=tail.bundle,
                bundle_loc=tail.bundle_loc,
                bundle_asset_count=tail.bundle_asset_count,
            )


def _iter_track_asset_contexts(raw: _RawMapping) -> Iterator[RawAssetContext]:
    artists = _as_list(raw.get("artists"))
    if artists is None:
        return
    for artist_idx, artist_obj in enumerate(artists):
        artist = _as_mapping(artist_obj)
        if artist is None:
            continue
        artist_loc: _Loc = ("artists", artist_idx)
        yield from _iter_artist_asset_contexts(artist, artist_loc=artist_loc)


def _iter_artist_asset_contexts(
    artist: _RawMapping, *, artist_loc: _Loc
) -> Iterator[RawAssetContext]:
    albums = _as_list(artist.get("albums"))
    if albums is None:
        return
    for album_idx, album_obj in enumerate(albums):
        album = _as_mapping(album_obj)
        if album is None:
            continue
        album_loc = (*artist_loc, "albums", album_idx)
        yield from _iter_album_asset_contexts(
            artist, artist_loc=artist_loc, album=album, album_loc=album_loc
        )


def _iter_album_asset_contexts(
    artist: _RawMapping,
    *,
    artist_loc: _Loc,
    album: _RawMapping,
    album_loc: _Loc,
) -> Iterator[RawAssetContext]:
    discs = _as_list(album.get("discs"))
    if discs is None:
        return
    for disc_idx, disc_obj in enumerate(discs):
        disc = _as_mapping(disc_obj)
        if disc is None:
            continue
        disc_loc = (*album_loc, "discs", disc_idx)
        yield from _iter_disc_asset_contexts(
            artist=artist,
            artist_loc=artist_loc,
            album=album,
            album_loc=album_loc,
            disc=disc,
            disc_loc=disc_loc,
        )


def _iter_disc_asset_contexts(
    *,
    artist: _RawMapping,
    artist_loc: _Loc,
    album: _RawMapping,
    album_loc: _Loc,
    disc: _RawMapping,
    disc_loc: _Loc,
) -> Iterator[RawAssetContext]:
    tracks = _as_list(disc.get("tracks"))
    if tracks is None:
        return
    for track_idx, track_obj in enumerate(tracks):
        track = _as_mapping(track_obj)
        if track is None:
            continue
        track_loc = (*disc_loc, "tracks", track_idx)
        for tail in _iter_variant_asset_tail(track.get("variants"), (*track_loc, "variants")):
            yield RawAssetContext(
                asset=tail.asset,
                asset_loc=tail.asset_loc,
                parent_kind=ParentKind.TRACK.value,
                parent_id=_id_or_empty(track),
                movie=None,
                movie_loc=None,
                series=None,
                series_loc=None,
                season=None,
                season_loc=None,
                episode=None,
                episode_loc=None,
                artist=artist,
                artist_loc=artist_loc,
                album=album,
                album_loc=album_loc,
                disc=disc,
                disc_loc=disc_loc,
                track=track,
                track_loc=track_loc,
                variant=tail.variant,
                variant_loc=tail.variant_loc,
                bundle=tail.bundle,
                bundle_loc=tail.bundle_loc,
                bundle_asset_count=tail.bundle_asset_count,
            )


@dataclass(frozen=True, slots=True)
class _RawTailContext:
    asset: _RawMapping
    asset_loc: _Loc
    variant: _RawMapping
    variant_loc: _Loc
    bundle: _RawMapping
    bundle_loc: _Loc
    bundle_asset_count: int


def _iter_variant_asset_tail(
    variants_obj: object, variants_path: _Loc
) -> Iterator[_RawTailContext]:
    variants = _as_list(variants_obj)
    if variants is None:
        return
    for v_idx, variant_obj in enumerate(variants):
        variant = _as_mapping(variant_obj)
        if variant is None:
            continue
        variant_loc = (*variants_path, v_idx)
        bundle = _as_mapping(variant.get("bundle"))
        if bundle is None:
            continue
        bundle_loc = (*variant_loc, "bundle")
        assets = _as_list(bundle.get("assets"))
        if assets is None:
            continue
        for a_idx, asset_obj in enumerate(assets):
            asset = _as_mapping(asset_obj)
            if asset is None:
                continue
            yield _RawTailContext(
                asset=asset,
                asset_loc=(*bundle_loc, "assets", a_idx),
                variant=variant,
                variant_loc=variant_loc,
                bundle=bundle,
                bundle_loc=bundle_loc,
                bundle_asset_count=len(assets),
            )


def _movie_renderable_context(
    raw_context: RawAssetContext, parent_kind: ParentKind, root_path: str
) -> RenderableAssetContext | None:
    if raw_context.movie is None:
        return None
    layout = _movie_layout(raw_context.movie.get("layout"))
    movie_title = _str_field(raw_context.movie, "title")
    tail = _tail_render_fields(raw_context)
    if layout is None or movie_title is None or tail is None:
        return None
    return RenderableAssetContext(
        parent_kind=parent_kind,
        root_path=root_path,
        layout=layout,
        naming=None,
        movie_title=movie_title,
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
        variant_label=tail[0],
        asset_role=tail[1],
        asset_container=tail[2],
        bundle_asset_count=tail[3],
    )


def _episode_renderable_context(
    raw_context: RawAssetContext, parent_kind: ParentKind, root_path: str
) -> RenderableAssetContext | None:
    if raw_context.series is None or raw_context.season is None or raw_context.episode is None:
        return None
    layout = _series_layout(raw_context.series.get("layout"))
    naming = _episode_naming(raw_context.series.get("episode_naming"))
    series_title = _str_field(raw_context.series, "title")
    season_number = _int_field(raw_context.season, "season_number")
    episode_number = _int_field(raw_context.episode, "episode_number")
    episode_title = _str_field(raw_context.episode, "title")
    tail = _tail_render_fields(raw_context)
    if layout is None or naming is None or series_title is None:
        return None
    if season_number is None or episode_number is None or episode_title is None:
        return None
    if tail is None:
        return None
    aired_on = _date_field(raw_context.episode, "aired_on")
    absolute_number = _int_field(raw_context.episode, "absolute_number")
    if (naming is EpisodeNaming.DATE_TITLE and aired_on is None) or (
        naming is EpisodeNaming.ABSOLUTE_3_DIGIT_TITLE and absolute_number is None
    ):
        return None
    return RenderableAssetContext(
        parent_kind=parent_kind,
        root_path=root_path,
        layout=layout,
        naming=naming,
        movie_title=None,
        series_title=series_title,
        season_number=season_number,
        episode_number=episode_number,
        episode_title=episode_title,
        aired_on=aired_on,
        absolute_number=absolute_number,
        artist_name=None,
        album_title=None,
        disc_number=None,
        track_number=None,
        track_title=None,
        variant_label=tail[0],
        asset_role=tail[1],
        asset_container=tail[2],
        bundle_asset_count=tail[3],
    )


def _track_renderable_context(
    raw_context: RawAssetContext, parent_kind: ParentKind, root_path: str
) -> RenderableAssetContext | None:
    if raw_context.artist is None or raw_context.album is None:
        return None
    if raw_context.disc is None or raw_context.track is None:
        return None
    layout = _artist_layout(raw_context.artist.get("layout"))
    naming = _track_naming(raw_context.artist.get("track_naming"))
    artist_name = _str_field(raw_context.artist, "name")
    album_title = _str_field(raw_context.album, "title")
    disc_number = _int_field(raw_context.disc, "disc_number")
    track_number = _int_field(raw_context.track, "track_number")
    track_title = _str_field(raw_context.track, "title")
    tail = _tail_render_fields(raw_context)
    if layout is None or naming is None or artist_name is None or album_title is None:
        return None
    if disc_number is None or track_number is None or track_title is None:
        return None
    if tail is None:
        return None
    return RenderableAssetContext(
        parent_kind=parent_kind,
        root_path=root_path,
        layout=layout,
        naming=naming,
        movie_title=None,
        series_title=None,
        season_number=None,
        episode_number=None,
        episode_title=None,
        aired_on=None,
        absolute_number=None,
        artist_name=artist_name,
        album_title=album_title,
        disc_number=disc_number,
        track_number=track_number,
        track_title=track_title,
        variant_label=tail[0],
        asset_role=tail[1],
        asset_container=tail[2],
        bundle_asset_count=tail[3],
    )


def _tail_render_fields(raw_context: RawAssetContext) -> tuple[str, str, str, int] | None:
    variant_label = _str_field(raw_context.variant, "label")
    asset_role = _str_field(raw_context.asset, "role")
    asset_container = _str_field(raw_context.asset, "container")
    if variant_label is None or asset_role is None or asset_container is None:
        return None
    return (
        variant_label,
        asset_role,
        asset_container,
        raw_context.bundle_asset_count,
    )


def _parent_kind(value: str) -> ParentKind | None:
    try:
        return ParentKind(value)
    except ValueError:
        return None


def _movie_layout(value: object) -> MovieLayout | None:
    if not isinstance(value, str):
        return None
    try:
        return MovieLayout(value)
    except ValueError:
        return None


def _series_layout(value: object) -> SeriesLayout | None:
    if not isinstance(value, str):
        return None
    try:
        return SeriesLayout(value)
    except ValueError:
        return None


def _artist_layout(value: object) -> ArtistLayout | None:
    if not isinstance(value, str):
        return None
    try:
        return ArtistLayout(value)
    except ValueError:
        return None


def _episode_naming(value: object) -> EpisodeNaming | None:
    if not isinstance(value, str):
        return None
    try:
        return EpisodeNaming(value)
    except ValueError:
        return None


def _track_naming(value: object) -> TrackNaming | None:
    if not isinstance(value, str):
        return None
    try:
        return TrackNaming(value)
    except ValueError:
        return None


def _str_field(mapping: _RawMapping, field: str) -> str | None:
    value = mapping.get(field)
    return value if isinstance(value, str) else None


def _int_field(mapping: _RawMapping, field: str) -> int | None:
    value = mapping.get(field)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return None


def _date_field(mapping: _RawMapping, field: str) -> date | None:
    value = mapping.get(field)
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _id_or_empty(mapping: _RawMapping) -> str:
    value = mapping.get("id")
    return value if isinstance(value, str) else ""
