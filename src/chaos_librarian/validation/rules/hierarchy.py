"""Domain hierarchy semantic validation for the current Scenario contract."""

from __future__ import annotations

import os
from collections.abc import Mapping
from datetime import date
from typing import TYPE_CHECKING

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    EpisodeNaming,
    TimelineActionName,
)
from chaos_librarian.validation.codes import (
    E_HIERARCHY_INVALID,
    E_MATERIALIZE_UNSUPPORTED,
    E_PATH_COLLISION,
    format_jsonpath,
)
from chaos_librarian.validation.rules._common import (
    HierarchyMutation,
    HierarchyProjection,
    RawAssetContext,
    Reporter,
    _as_list,
    _as_mapping,
    _iter_timeline_events,
    _Loc,
    build_hierarchy_projection,
    first_or_duplicate,
    is_hierarchy_action,
    iter_asset_contexts,
    rendered_asset_paths,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = [
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
        first = first_or_duplicate(seen, normalized, (asset_id, loc))
        if first is not None:
            first_asset_id, first_loc = first
            first_path = format_jsonpath(first_loc)
            reporter.error(
                code=E_PATH_COLLISION,
                message=(
                    f"rendered initial path {normalized!r} for asset {asset_id!r} "
                    f"collides with asset {first_asset_id!r} at {first_path}"
                ),
                loc=loc,
            )


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
        if not is_hierarchy_action(action):
            projection.project_non_hierarchy_event(event, pending_slow_copies)
            continue
        mutation = projection.apply(event)
        _check_hierarchy_rendered_paths(mutation=mutation, event_idx=idx, reporter=reporter)
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


def _check_hierarchy_rendered_paths(
    *, mutation: HierarchyMutation, event_idx: int, reporter: Reporter
) -> None:
    for old_path, new_path in mutation.path_changes.values():
        if old_path is not None and new_path is None:
            _report_error(
                reporter,
                "hierarchy action makes an active asset path unrenderable",
                _event_loc(event_idx),
            )
            return


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


def _event_loc(event_idx: int) -> _Loc:
    return ("timeline", event_idx, "action")


def _normalize(path: str) -> str:
    return os.path.normpath(path)


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
    if action in {
        TimelineActionName.REENCODE_VIDEO,
        TimelineActionName.REMUX_CONTAINER,
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
