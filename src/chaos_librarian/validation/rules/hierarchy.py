"""Domain hierarchy semantic validation for Scenario v12."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import TYPE_CHECKING

from chaos_librarian.contract.scenario import EpisodeNaming
from chaos_librarian.validation.codes import E_HIERARCHY_INVALID
from chaos_librarian.validation.rules._common import (
    Reporter,
    _as_list,
    _as_mapping,
    _Loc,
)

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector

__all__ = ["rule_hierarchy_invariants"]


def rule_hierarchy_invariants(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject hierarchy numbering conflicts and naming recipe dependency gaps."""
    reporter = Reporter(collector=collector, line_index=line_index)
    _check_series(raw, reporter)
    _check_artists(raw, reporter)


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


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_date_value(value: object) -> bool:
    return isinstance(value, str | date)


def _report_error(reporter: Reporter, message: str, loc: _Loc) -> None:
    reporter.error(code=E_HIERARCHY_INVALID, message=message, loc=loc)
