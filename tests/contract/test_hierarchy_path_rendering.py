"""Contract tests for hierarchy path rendering."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields
from datetime import UTC, date, datetime
from typing import cast

import pytest

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import (
    ArtistLayout,
    EditionKind,
    EpisodeNaming,
    MovieLayout,
    PodcastEpisodeNaming,
    PodcastLayout,
    SeriesLayout,
    TrackNaming,
)
from chaos_librarian.path_rendering import (
    RenderableAssetContext,
    clean_display_component,
    render_asset_path,
    render_declared_sidecar_path,
    replace_root_prefix,
)


def _ctx(**overrides: object) -> RenderableAssetContext:
    fields: dict[str, object] = {
        "parent_kind": ParentKind.MOVIE,
        "root_path": "Movies",
        "layout": MovieLayout.MOVIE_FLAT,
        "naming": None,
        "movie_title": "Orbit",
        "series_title": None,
        "season_number": None,
        "episode_number": None,
        "episode_title": None,
        "aired_on": None,
        "absolute_number": None,
        "artist_name": None,
        "album_title": None,
        "disc_number": None,
        "track_number": None,
        "track_title": None,
        "podcast_title": None,
        "published_at": None,
        "episode_slug": None,
        "edition": None,
        "variant_label": "1080p",
        "asset_role": "feature",
        "asset_container": "mkv",
        "bundle_asset_count": 1,
    }
    fields.update(overrides)
    return RenderableAssetContext(**fields)


def test_clean_display_component_normalizes_display_text() -> None:
    assert clean_display_component("  A / B   C  ") == "A - B C"
    assert clean_display_component("A\\B") == "A-B"


@pytest.mark.parametrize("value", ["", "   ", ".", " .. "])
def test_clean_display_component_rejects_invalid_components(value: str) -> None:
    with pytest.raises(ValueError, match="display component"):
        clean_display_component(value)


@pytest.mark.parametrize("control_character", ["\x00", "\t", "\x1f", "\x7f"])
def test_clean_display_component_rejects_ascii_control_characters(
    control_character: str,
) -> None:
    with pytest.raises(ValueError, match="control"):
        clean_display_component(f"A{control_character}B")


def test_movie_flat_path() -> None:
    assert render_asset_path(_ctx()) == "Movies/Orbit - 1080p.mkv"


def test_movie_folder_path() -> None:
    assert render_asset_path(_ctx(layout=MovieLayout.MOVIE_FOLDER)) == (
        "Movies/Orbit/Orbit - 1080p.mkv"
    )


def test_movie_flat_with_edition_renders_token() -> None:
    assert render_asset_path(_ctx(edition=EditionKind.DIRECTORS_CUT)) == (
        "Movies/Orbit - 1080p {edition-Director's Cut}.mkv"
    )


def test_movie_folder_with_edition_renders_token() -> None:
    assert render_asset_path(
        _ctx(layout=MovieLayout.MOVIE_FOLDER, edition=EditionKind.EXTENDED)
    ) == ("Movies/Orbit/Orbit - 1080p {edition-Extended}.mkv")


def test_movie_edition_none_renders_unchanged() -> None:
    assert render_asset_path(_ctx(edition=None)) == "Movies/Orbit - 1080p.mkv"


def test_movie_edition_token_follows_role_suffix_for_multi_asset_bundle() -> None:
    assert render_asset_path(_ctx(bundle_asset_count=2, edition=EditionKind.UNRATED)) == (
        "Movies/Orbit - 1080p - feature {edition-Unrated}.mkv"
    )


@pytest.mark.parametrize(
    ("edition", "token"),
    [
        (EditionKind.THEATRICAL, "Theatrical"),
        (EditionKind.DIRECTORS_CUT, "Director's Cut"),
        (EditionKind.EXTENDED, "Extended"),
        (EditionKind.UNRATED, "Unrated"),
    ],
)
def test_each_edition_kind_renders_title_case_token(edition: EditionKind, token: str) -> None:
    assert render_asset_path(_ctx(edition=edition)) == (
        f"Movies/Orbit - 1080p {{edition-{token}}}.mkv"
    )


def test_edition_sidecar_inherits_edition_stem() -> None:
    media = "Movies/Orbit - 1080p {edition-Director's Cut}.mkv"
    assert render_declared_sidecar_path(media, "en", codec="srt") == (
        "Movies/Orbit - 1080p {edition-Director's Cut}.en.srt"
    )


def test_tv_sxxexx_season_folder_path() -> None:
    assert (
        render_asset_path(
            _ctx(
                parent_kind=ParentKind.EPISODE,
                root_path="TV",
                layout=SeriesLayout.SEASON_FOLDERS,
                naming=EpisodeNaming.SXXEXX_TITLE,
                movie_title=None,
                series_title="Starline",
                season_number=1,
                episode_number=1,
                episode_title="Pilot",
                aired_on=date(2024, 5, 1),
                absolute_number=7,
            )
        )
        == "TV/Starline/Season 01/Starline - S01E01 - Pilot - 1080p.mkv"
    )


def test_tv_one_xx_flat_path() -> None:
    assert (
        render_asset_path(
            _ctx(
                parent_kind=ParentKind.EPISODE,
                root_path="TV",
                layout=SeriesLayout.SERIES_FLAT,
                naming=EpisodeNaming.ONE_XX_TITLE,
                movie_title=None,
                series_title="Starline",
                season_number=1,
                episode_number=1,
                episode_title="Pilot",
            )
        )
        == "TV/Starline/Starline - 1x01 - Pilot - 1080p.mkv"
    )


def test_tv_absolute_number_path() -> None:
    assert (
        render_asset_path(
            _ctx(
                parent_kind=ParentKind.EPISODE,
                root_path="TV",
                layout=SeriesLayout.SERIES_FLAT,
                naming=EpisodeNaming.ABSOLUTE_3_DIGIT_TITLE,
                movie_title=None,
                series_title="Starline",
                season_number=1,
                episode_number=7,
                episode_title="Signal",
                absolute_number=7,
            )
        )
        == "TV/Starline/Starline - 007 - Signal - 1080p.mkv"
    )


def test_tv_date_path() -> None:
    assert (
        render_asset_path(
            _ctx(
                parent_kind=ParentKind.EPISODE,
                root_path="TV",
                layout=SeriesLayout.SERIES_FLAT,
                naming=EpisodeNaming.DATE_TITLE,
                movie_title=None,
                series_title="Starline",
                season_number=1,
                episode_number=1,
                episode_title="Pilot",
                aired_on=date(2024, 5, 1),
            )
        )
        == "TV/Starline/Starline - 2024-05-01 - Pilot - 1080p.mkv"
    )


def test_music_disc_folder_track_number_path() -> None:
    assert (
        render_asset_path(
            _ctx(
                parent_kind=ParentKind.TRACK,
                root_path="Music",
                layout=ArtistLayout.ARTIST_ALBUM_DISC,
                naming=TrackNaming.TRACK_NUMBER_TITLE,
                movie_title=None,
                artist_name="North Index",
                album_title="Winter Index",
                disc_number=1,
                track_number=1,
                track_title="Opening",
                variant_label="lossless",
                asset_container="flac",
            )
        )
        == "Music/North Index/Winter Index/Disc 01/01 - Opening - lossless.flac"
    )


def test_music_flat_disc_track_number_path() -> None:
    assert (
        render_asset_path(
            _ctx(
                parent_kind=ParentKind.TRACK,
                root_path="Music",
                layout=ArtistLayout.ARTIST_ALBUM_FLAT,
                naming=TrackNaming.DISC_TRACK_NUMBER_TITLE,
                movie_title=None,
                artist_name="North Index",
                album_title="Winter Index",
                disc_number=1,
                track_number=1,
                track_title="Opening",
                variant_label="lossless",
                asset_container="flac",
            )
        )
        == "Music/North Index/Winter Index/01-01 - Opening - lossless.flac"
    )


def test_render_podcast_episode_path() -> None:
    assert (
        render_asset_path(
            _ctx(
                parent_kind=ParentKind.PODCAST_EPISODE,
                root_path="Podcasts",
                layout=PodcastLayout.PODCAST_FOLDER,
                naming=PodcastEpisodeNaming.DATE_SLUG_TITLE,
                movie_title=None,
                podcast_title="The Daily",
                published_at=datetime(2026, 5, 1, 9, 30, tzinfo=UTC),
                episode_slug="ep-001",
                episode_title="First Show",
                variant_label="default",
                asset_container="mp3",
            )
        )
        == "Podcasts/The Daily/2026-05-01 - ep-001 - First Show - default.mp3"
    )


def test_render_podcast_episode_uses_utc_date_for_non_utc_instant() -> None:
    # An instant just after UTC midnight renders the UTC date, not a local one.
    assert (
        render_asset_path(
            _ctx(
                parent_kind=ParentKind.PODCAST_EPISODE,
                root_path="Podcasts",
                layout=PodcastLayout.PODCAST_FOLDER,
                naming=PodcastEpisodeNaming.DATE_SLUG_TITLE,
                movie_title=None,
                podcast_title="The Daily",
                published_at=datetime(2026, 5, 2, 1, 0, tzinfo=UTC),
                episode_slug="ep-002",
                episode_title="Next",
                variant_label="default",
                asset_container="mp3",
            )
        )
        == "Podcasts/The Daily/2026-05-02 - ep-002 - Next - default.mp3"
    )


def test_multi_asset_bundle_uses_asset_role_suffix() -> None:
    assert (
        render_asset_path(_ctx(layout=MovieLayout.MOVIE_FOLDER, bundle_asset_count=2))
        == "Movies/Orbit/Orbit - 1080p - feature.mkv"
    )


def test_renderable_asset_context_rejects_positional_construction() -> None:
    context = _ctx()
    values = tuple(getattr(context, field.name) for field in fields(RenderableAssetContext))
    constructor = cast(Callable[..., RenderableAssetContext], RenderableAssetContext)

    with pytest.raises(TypeError, match="positional"):
        constructor(*values)


@pytest.mark.parametrize(
    "root_path",
    ["/Movies", "C:/Movies", "Movies//HD", "Movies/../HD", "Movies/./HD"],
)
def test_render_asset_path_rejects_invalid_root_segments(root_path: str) -> None:
    with pytest.raises(ValueError, match="path must"):
        render_asset_path(_ctx(root_path=root_path))


@pytest.mark.parametrize(
    "overrides",
    [
        {"movie_title": ".."},
        {"variant_label": "."},
        {"asset_container": "../mkv"},
        {"asset_container": "mkv/evil"},
        {"asset_container": "mkv.evil"},
    ],
)
def test_render_asset_path_rejects_invalid_rendered_components(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match=r"display component|asset_container"):
        render_asset_path(_ctx(**overrides))


def test_render_declared_sidecar_path_stays_next_to_media_stem() -> None:
    assert render_declared_sidecar_path("TV/Starline/Pilot.mkv", "eng") == (
        "TV/Starline/Pilot.eng.srt"
    )


def test_render_declared_sidecar_path_uses_codec_extension() -> None:
    assert render_declared_sidecar_path("TV/Starline/Pilot.mkv", "jpn", codec="ass") == (
        "TV/Starline/Pilot.jpn.ass"
    )
    assert render_declared_sidecar_path("TV/Starline/Pilot.mkv", "spa", codec="ssa") == (
        "TV/Starline/Pilot.spa.ssa"
    )


def test_render_declared_sidecar_path_rejects_invalid_media_path() -> None:
    with pytest.raises(ValueError, match="relative POSIX"):
        render_declared_sidecar_path("/TV/Starline/Pilot.mkv", "eng")


def test_render_declared_sidecar_path_requires_extension_on_filename() -> None:
    with pytest.raises(ValueError, match="file extension"):
        render_declared_sidecar_path("TV.v1/Pilot", "eng")


def test_replace_root_prefix_swaps_only_the_root_component() -> None:
    assert (
        replace_root_prefix(
            "Movies/Orbit/Orbit - 1080p.mkv",
            from_root="Movies",
            to_root="Archive",
        )
        == "Archive/Orbit/Orbit - 1080p.mkv"
    )


def test_replace_root_prefix_rejects_non_root_prefix_match() -> None:
    with pytest.raises(ValueError, match="from_root"):
        replace_root_prefix(
            "Movies-HD/Orbit.mkv",
            from_root="Movies",
            to_root="Archive",
        )
