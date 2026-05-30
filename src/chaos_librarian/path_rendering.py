"""Domain-aware media path rendering."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    ArtistLayout,
    EpisodeNaming,
    MovieLayout,
    PodcastEpisodeNaming,
    PodcastLayout,
    SeriesLayout,
    TrackNaming,
)

_WINDOWS_DRIVE_PREFIX_LENGTH = 2
_ASCII_C0_CONTROL_LIMIT = 32
_ASCII_DELETE = 127


@dataclass(frozen=True, slots=True, kw_only=True)
class RenderableAssetContext:
    parent_kind: ParentKind
    root_path: str
    layout: MovieLayout | SeriesLayout | ArtistLayout | PodcastLayout
    # Domain fields default to None so builders set only the rows on their branch;
    # kw_only lets these defaults precede the required tail fields below.
    naming: EpisodeNaming | TrackNaming | PodcastEpisodeNaming | None = None
    movie_title: str | None = None
    series_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None
    episode_title: str | None = None
    aired_on: date | None = None
    absolute_number: int | None = None
    artist_name: str | None = None
    album_title: str | None = None
    disc_number: int | None = None
    track_number: int | None = None
    track_title: str | None = None
    podcast_title: str | None = None
    published_at: datetime | None = None
    episode_slug: str | None = None
    variant_label: str
    asset_role: str
    asset_container: str
    bundle_asset_count: int


def clean_display_component(value: str) -> str:
    """Normalize one display-derived path component or raise ValueError."""
    if any(
        ord(character) < _ASCII_C0_CONTROL_LIMIT or ord(character) == _ASCII_DELETE
        for character in value
    ):
        raise ValueError("display component must not contain ASCII control characters")
    cleaned = " ".join(value.strip().split())
    cleaned = cleaned.replace("/", "-").replace("\\", "-")
    if cleaned in {"", ".", ".."}:
        raise ValueError("display component must not be empty, '.', or '..'")
    return cleaned


def render_asset_path(ctx: RenderableAssetContext) -> str:
    """Render the media file path for one asset context."""
    root = _validate_relative_posix_path(ctx.root_path)
    if ctx.parent_kind is ParentKind.MOVIE:
        parts = _movie_parts(root, ctx)
    elif ctx.parent_kind is ParentKind.EPISODE:
        parts = _episode_parts(root, ctx)
    elif ctx.parent_kind is ParentKind.TRACK:
        parts = _track_parts(root, ctx)
    elif ctx.parent_kind is ParentKind.PODCAST_EPISODE:
        parts = _podcast_parts(root, ctx)
    else:
        raise ValueError(f"unsupported parent_kind: {ctx.parent_kind}")
    return _join_path(*parts)


def render_declared_sidecar_path(media_path: str, language: str, *, codec: str = "srt") -> str:
    """Render the declared sidecar path next to the media stem."""
    media_path = _validate_relative_posix_path(media_path)
    language = clean_display_component(language)
    codec = clean_asset_container(codec)
    directory, directory_separator, filename = media_path.rpartition("/")
    stem, separator, extension = filename.rpartition(".")
    if not separator or not extension:
        raise ValueError("media_path must include a file extension")
    parent = f"{directory}{directory_separator}"
    return _validate_relative_posix_path(f"{parent}{stem}.{language}.{codec}")


def replace_root_prefix(path: str, *, from_root: str, to_root: str) -> str:
    """Replace only the library root prefix of a rendered media path."""
    path = _validate_relative_posix_path(path)
    from_root = _validate_relative_posix_path(from_root)
    to_root = _validate_relative_posix_path(to_root)
    if path == from_root:
        return to_root
    prefix = f"{from_root}/"
    if not path.startswith(prefix):
        raise ValueError("path does not start with from_root as a path component")
    return _validate_relative_posix_path(f"{to_root}/{path[len(prefix) :]}")


def _validate_relative_posix_path(path: str) -> str:
    if path == "" or path.startswith("/") or "\\" in path or "\x00" in path:
        raise ValueError("path must be a relative POSIX path")
    first_segment = path.split("/", 1)[0]
    has_drive_prefix = (
        len(first_segment) == _WINDOWS_DRIVE_PREFIX_LENGTH
        and first_segment[1] == ":"
        and first_segment[0].isalpha()
    )
    if has_drive_prefix:
        raise ValueError("path must not contain a Windows drive prefix")
    if any(segment in {"", ".", ".."} for segment in path.split("/")):
        raise ValueError("path must not contain empty, dot, or parent segments")
    return path


def _join_path(*parts: str) -> str:
    return _validate_relative_posix_path("/".join(parts))


def _filename(stem: str, ctx: RenderableAssetContext) -> str:
    label = clean_display_component(ctx.variant_label)
    role_suffix = ""
    if ctx.bundle_asset_count > 1:
        role_suffix = f" - {clean_display_component(ctx.asset_role)}"
    container = clean_asset_container(ctx.asset_container)
    return f"{stem} - {label}{role_suffix}.{container}"


def clean_asset_container(container: str) -> str:
    """Normalize a media container token or raise ValueError.

    The token names a file extension ("mp4", "mkv"); it must carry no path
    syntax. Shared by path rendering and the remux-target validation rule so
    initial and remuxed containers obey one constraint.
    """
    if any(char in container for char in (".", "/", "\\", "\x00")):
        raise ValueError("asset_container must not contain dot or path syntax")
    return clean_display_component(container)


def _movie_parts(root: str, ctx: RenderableAssetContext) -> tuple[str, ...]:
    if not isinstance(ctx.layout, MovieLayout):
        raise ValueError("movie context requires MovieLayout")
    movie_title = _required(ctx.movie_title, "movie_title")
    title = clean_display_component(movie_title)
    filename = _filename(title, ctx)
    if ctx.layout is MovieLayout.MOVIE_FLAT:
        return (root, filename)
    if ctx.layout is MovieLayout.MOVIE_FOLDER:
        return (root, title, filename)
    raise ValueError(f"unsupported movie layout: {ctx.layout}")


def _episode_parts(root: str, ctx: RenderableAssetContext) -> tuple[str, ...]:
    if not isinstance(ctx.layout, SeriesLayout):
        raise ValueError("episode context requires SeriesLayout")
    series = clean_display_component(_required(ctx.series_title, "series_title"))
    stem = _episode_stem(ctx)
    filename = _filename(stem, ctx)
    if ctx.layout is SeriesLayout.SEASON_FOLDERS:
        season_number = _required_int(ctx.season_number, "season_number")
        season_folder = f"Season {season_number:02d}"
        return (root, series, season_folder, filename)
    if ctx.layout is SeriesLayout.SERIES_FLAT:
        return (root, series, filename)
    raise ValueError(f"unsupported series layout: {ctx.layout}")


def _episode_stem(ctx: RenderableAssetContext) -> str:
    series = clean_display_component(_required(ctx.series_title, "series_title"))
    title = clean_display_component(_required(ctx.episode_title, "episode_title"))
    season_number = _required_int(ctx.season_number, "season_number")
    episode_number = _required_int(ctx.episode_number, "episode_number")
    if ctx.naming is EpisodeNaming.SXXEXX_TITLE:
        return f"{series} - S{season_number:02d}E{episode_number:02d} - {title}"
    if ctx.naming is EpisodeNaming.ONE_XX_TITLE:
        return f"{series} - {season_number}x{episode_number:02d} - {title}"
    if ctx.naming is EpisodeNaming.ABSOLUTE_3_DIGIT_TITLE:
        absolute = _required_int(ctx.absolute_number, "absolute_number")
        return f"{series} - {absolute:03d} - {title}"
    if ctx.naming is EpisodeNaming.DATE_TITLE:
        aired_on = _required(ctx.aired_on, "aired_on")
        return f"{series} - {aired_on.isoformat()} - {title}"
    raise ValueError("episode context requires EpisodeNaming")


def _track_parts(root: str, ctx: RenderableAssetContext) -> tuple[str, ...]:
    if not isinstance(ctx.layout, ArtistLayout):
        raise ValueError("track context requires ArtistLayout")
    artist = clean_display_component(_required(ctx.artist_name, "artist_name"))
    album = clean_display_component(_required(ctx.album_title, "album_title"))
    stem = _track_stem(ctx)
    filename = _filename(stem, ctx)
    if ctx.layout is ArtistLayout.ARTIST_ALBUM_DISC:
        disc_number = _required_int(ctx.disc_number, "disc_number")
        return (root, artist, album, f"Disc {disc_number:02d}", filename)
    if ctx.layout is ArtistLayout.ARTIST_ALBUM_FLAT:
        return (root, artist, album, filename)
    raise ValueError(f"unsupported artist layout: {ctx.layout}")


def _track_stem(ctx: RenderableAssetContext) -> str:
    title = clean_display_component(_required(ctx.track_title, "track_title"))
    disc_number = _required_int(ctx.disc_number, "disc_number")
    track_number = _required_int(ctx.track_number, "track_number")
    if ctx.naming is TrackNaming.TRACK_NUMBER_TITLE:
        return f"{track_number:02d} - {title}"
    if ctx.naming is TrackNaming.DISC_TRACK_NUMBER_TITLE:
        return f"{disc_number:02d}-{track_number:02d} - {title}"
    raise ValueError("track context requires TrackNaming")


def _podcast_parts(root: str, ctx: RenderableAssetContext) -> tuple[str, ...]:
    if not isinstance(ctx.layout, PodcastLayout):
        raise ValueError("podcast context requires PodcastLayout")
    podcast = clean_display_component(_required(ctx.podcast_title, "podcast_title"))
    stem = _podcast_stem(ctx)
    filename = _filename(stem, ctx)
    if ctx.layout is PodcastLayout.PODCAST_FOLDER:
        return (root, podcast, filename)
    raise ValueError(f"unsupported podcast layout: {ctx.layout}")


def _podcast_stem(ctx: RenderableAssetContext) -> str:
    title = clean_display_component(_required(ctx.episode_title, "episode_title"))
    slug = clean_display_component(_required(ctx.episode_slug, "episode_slug"))
    published_at = _required(ctx.published_at, "published_at")
    if ctx.naming is PodcastEpisodeNaming.DATE_SLUG_TITLE:
        date_str = published_at.astimezone(UTC).date().isoformat()
        return f"{date_str} - {slug} - {title}"
    raise ValueError("podcast context requires PodcastEpisodeNaming")


def _required[T](value: T | None, field_name: str) -> T:
    if value is None:
        raise ValueError(f"{field_name} is required")
    return value


def _required_int(value: int | None, field_name: str) -> int:
    if value is None:
        raise ValueError(f"{field_name} is required")
    return value
