"""Raw hierarchy-to-path rendering projection helpers."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    ArtistLayout,
    EditionKind,
    EpisodeNaming,
    MovieLayout,
    PodcastEpisodeNaming,
    PodcastLayout,
    SeriesLayout,
    SidecarKind,
    SubtitleMode,
    TrackNaming,
)
from chaos_librarian.path_rendering import (
    RenderableAssetContext,
    render_asset_path,
    render_declared_sidecar_path,
)
from chaos_librarian.validation.rules.core.raw_helpers import (
    _as_list,
    _as_mapping,
    _enum,
    _Loc,
    _RawMapping,
    _str_or_default,
)
from chaos_librarian.validation.rules.hierarchy.walkers import (
    RawAssetContext,
    iter_asset_contexts,
    primary_root_path,
)


@dataclass(frozen=True, slots=True)
class DeclaredSidecar:
    """One declared sidecar-mode subtitle projected from the raw scenario tree."""

    asset_id: str
    path: str
    kind: str
    language: str | None
    codec: str = "srt"
    source: str = "generated_srt"
    encoding: str = "utf8"
    timing_profile: str = "normal"


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
            if sub is None or _enum(SubtitleMode, sub.get("mode")) is not SubtitleMode.SIDECAR:
                continue
            language = sub.get("language")
            if not isinstance(language, str):
                continue
            codec = _str_or_default(sub.get("codec"), "srt")
            source = _str_or_default(sub.get("source"), "generated_srt")
            encoding = _str_or_default(sub.get("encoding"), "utf8")
            timing_profile = _str_or_default(sub.get("timing_profile"), "normal")
            try:
                media_path = render_asset_path(renderable)
                path = render_declared_sidecar_path(media_path, language, codec=codec)
            except ValueError:
                continue
            yield DeclaredSidecar(
                asset_id=asset_id,
                path=path,
                kind=SidecarKind.SUBTITLE.value,
                language=language,
                codec=codec,
                source=source,
                encoding=encoding,
                timing_profile=timing_profile,
            )


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
    if parent_kind is ParentKind.PODCAST_EPISODE:
        return _podcast_renderable_context(raw_context, parent_kind, root_path)
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


def _movie_renderable_context(
    raw_context: RawAssetContext, parent_kind: ParentKind, root_path: str
) -> RenderableAssetContext | None:
    if raw_context.movie is None:
        return None
    layout = _enum(MovieLayout, raw_context.movie.get("layout"))
    movie_title = _str_field(raw_context.movie, "title")
    tail = _tail_render_fields(raw_context)
    if layout is None or movie_title is None or tail is None:
        return None
    # _enum tolerates None/absent; only the movie branch reads edition (ADR 0010).
    edition = _enum(EditionKind, raw_context.variant.get("edition"))
    return RenderableAssetContext(
        parent_kind=parent_kind,
        root_path=root_path,
        layout=layout,
        movie_title=movie_title,
        edition=edition,
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
    layout = _enum(SeriesLayout, raw_context.series.get("layout"))
    naming = _enum(EpisodeNaming, raw_context.series.get("episode_naming"))
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
        series_title=series_title,
        season_number=season_number,
        episode_number=episode_number,
        episode_title=episode_title,
        aired_on=aired_on,
        absolute_number=absolute_number,
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
    layout = _enum(ArtistLayout, raw_context.artist.get("layout"))
    naming = _enum(TrackNaming, raw_context.artist.get("track_naming"))
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


def _podcast_renderable_context(
    raw_context: RawAssetContext, parent_kind: ParentKind, root_path: str
) -> RenderableAssetContext | None:
    if raw_context.podcast is None or raw_context.podcast_episode is None:
        return None
    layout = _enum(PodcastLayout, raw_context.podcast.get("layout"))
    naming = _enum(PodcastEpisodeNaming, raw_context.podcast.get("episode_naming"))
    podcast_title = _str_field(raw_context.podcast, "title")
    episode_title = _str_field(raw_context.podcast_episode, "title")
    slug = _str_field(raw_context.podcast_episode, "slug")
    published_at = _datetime_field(raw_context.podcast_episode, "published_at")
    tail = _tail_render_fields(raw_context)
    if layout is None or naming is None or podcast_title is None:
        return None
    if episode_title is None or slug is None or published_at is None:
        return None
    if tail is None:
        return None
    return RenderableAssetContext(
        parent_kind=parent_kind,
        root_path=root_path,
        layout=layout,
        naming=naming,
        podcast_title=podcast_title,
        published_at=published_at,
        episode_slug=slug,
        episode_title=episode_title,
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


def _datetime_field(mapping: _RawMapping, field: str) -> datetime | None:
    value = mapping.get(field)
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
