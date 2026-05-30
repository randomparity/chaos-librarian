"""Tests for hierarchy topology helpers."""

from __future__ import annotations

from typing import get_type_hints

import pytest

from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.scenario import Asset, Bundle, Movie, Scenario, Variant
from chaos_librarian.topology import (
    AssetContext,
    asset_contexts_by_id,
    asset_ids_under_target,
    iter_asset_contexts,
)


def _video_asset_payload(asset_id: str) -> dict[str, object]:
    return {
        "id": asset_id,
        "role": "feature",
        "container": "mkv",
        "duration_seconds": 60,
        "video": {"source": "mandelbrot", "codec": "h264", "resolution": "1080p"},
        "audio": [{"codec": "aac", "channels": "stereo", "language": "eng"}],
        "subtitles": [],
    }


def _audio_asset_payload(asset_id: str) -> dict[str, object]:
    return {
        "id": asset_id,
        "role": "main",
        "container": "flac",
        "duration_seconds": 180,
        "audio": [{"codec": "flac", "channels": "stereo", "language": "zxx"}],
        "subtitles": [],
    }


def _variant_payload(
    variant_id: str, bundle_id: str, *assets: dict[str, object]
) -> dict[str, object]:
    return {
        "id": variant_id,
        "label": "1080p" if assets[0]["container"] == "mkv" else "lossless",
        "bundle": {"id": bundle_id, "assets": list(assets)},
    }


def _scenario() -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 31,
            "scenario_id": "topology",
            "seed": 1,
            "duration_scale": "short",
            "profiles": [],
            "library": {"roots": [{"id": "primary", "path": "Library"}]},
            "movies": [
                {
                    "id": "movie_orbit",
                    "title": "Orbit",
                    "layout": "movie_folder",
                    "variants": [
                        _variant_payload(
                            "variant_movie",
                            "bundle_movie",
                            _video_asset_payload("asset_movie"),
                        )
                    ],
                }
            ],
            "series": [
                {
                    "id": "series_starline",
                    "title": "Starline",
                    "layout": "season_folders",
                    "episode_naming": "sxxexx_title",
                    "seasons": [
                        {
                            "id": "season_01",
                            "season_number": 1,
                            "title": "Season 1",
                            "episodes": [
                                {
                                    "id": "episode_01",
                                    "episode_number": 1,
                                    "title": "Pilot",
                                    "aired_on": "2024-05-01",
                                    "absolute_number": 1,
                                    "variants": [
                                        _variant_payload(
                                            "variant_episode",
                                            "bundle_episode",
                                            _video_asset_payload("asset_episode"),
                                        )
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
            "artists": [
                {
                    "id": "artist_north",
                    "name": "North Index",
                    "layout": "artist_album_disc",
                    "track_naming": "track_number_title",
                    "albums": [
                        {
                            "id": "album_winter",
                            "title": "Winter Index",
                            "release_year": 2024,
                            "discs": [
                                {
                                    "id": "disc_01",
                                    "disc_number": 1,
                                    "tracks": [
                                        {
                                            "id": "track_01",
                                            "track_number": 1,
                                            "title": "Opening",
                                            "performers": ["North Index"],
                                            "variants": [
                                                _variant_payload(
                                                    "variant_track",
                                                    "bundle_track",
                                                    _audio_asset_payload("asset_track"),
                                                )
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
            "timeline": [],
        }
    )


def _podcast_scenario() -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 31,
            "scenario_id": "topology-podcast",
            "seed": 1,
            "duration_scale": "short",
            "profiles": [],
            "library": {"roots": [{"id": "primary", "path": "Library"}]},
            "movies": [],
            "series": [],
            "artists": [],
            "podcasts": [
                {
                    "id": "podcast_daily",
                    "title": "The Daily",
                    "layout": "podcast_folder",
                    "episode_naming": "date_slug_title",
                    "episodes": [
                        {
                            "id": "podcast_episode_01",
                            "title": "First Show",
                            "published_at": "2026-05-01T00:00:00Z",
                            "slug": "first-show",
                            "variants": [
                                _variant_payload(
                                    "variant_podcast",
                                    "bundle_podcast",
                                    _audio_asset_payload("asset_podcast"),
                                )
                            ],
                        }
                    ],
                }
            ],
            "timeline": [],
        }
    )


def _multi_asset_bundle_scenario() -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 31,
            "scenario_id": "multi-asset-bundle",
            "seed": 1,
            "duration_scale": "short",
            "profiles": [],
            "library": {"roots": [{"id": "primary", "path": "Library"}]},
            "movies": [
                {
                    "id": "movie_orbit",
                    "title": "Orbit",
                    "layout": "movie_folder",
                    "variants": [
                        _variant_payload(
                            "variant_movie",
                            "bundle_movie",
                            _video_asset_payload("asset_movie_main"),
                            _video_asset_payload("asset_movie_bonus"),
                        )
                    ],
                }
            ],
            "series": [],
            "artists": [],
            "timeline": [],
        }
    )


def test_asset_context_public_type_hints_resolve_at_runtime() -> None:
    hints = get_type_hints(AssetContext)

    assert hints["movie"] == Movie | None
    assert hints["variant"] is Variant
    assert hints["bundle"] is Bundle
    assert hints["asset"] is Asset
    assert get_type_hints(iter_asset_contexts)["scenario"] is Scenario


def test_iter_asset_contexts_preserves_manifest_declaration_order() -> None:
    contexts = list(iter_asset_contexts(_scenario()))

    assert [context.asset.id for context in contexts] == [
        "asset_movie",
        "asset_episode",
        "asset_track",
    ]
    assert [context.parent_kind for context in contexts] == [
        ParentKind.MOVIE,
        ParentKind.EPISODE,
        ParentKind.TRACK,
    ]
    assert contexts[0].parent_id == "movie_orbit"
    assert contexts[1].parent_id == "episode_01"
    assert contexts[1].series is not None
    assert contexts[1].season is not None
    assert contexts[1].episode is not None
    assert contexts[2].parent_id == "track_01"
    assert contexts[2].artist is not None
    assert contexts[2].album is not None
    assert contexts[2].disc is not None
    assert contexts[2].track is not None


def test_iter_asset_contexts_preserves_multi_asset_bundle_order_and_count() -> None:
    contexts = list(iter_asset_contexts(_multi_asset_bundle_scenario()))

    assert [context.asset.id for context in contexts] == [
        "asset_movie_main",
        "asset_movie_bonus",
    ]
    assert [context.bundle_asset_count for context in contexts] == [2, 2]
    assert [context.bundle.id for context in contexts] == [
        "bundle_movie",
        "bundle_movie",
    ]


def test_asset_contexts_by_id_returns_every_asset() -> None:
    contexts = asset_contexts_by_id(_scenario())

    assert set(contexts) == {"asset_movie", "asset_episode", "asset_track"}
    assert contexts["asset_movie"].parent_kind is ParentKind.MOVIE
    assert contexts["asset_episode"].parent_id == "episode_01"
    assert contexts["asset_track"].parent_id == "track_01"


def test_iter_asset_contexts_includes_podcast_episodes() -> None:
    contexts = list(iter_asset_contexts(_podcast_scenario()))

    assert [context.parent_kind for context in contexts] == [ParentKind.PODCAST_EPISODE]
    context = contexts[0]
    assert context.parent_id == "podcast_episode_01"
    assert context.podcast is not None
    assert context.podcast.title == "The Daily"
    assert context.podcast_episode is not None
    assert context.podcast_episode.slug == "first-show"


def test_asset_ids_under_podcast_episode_target() -> None:
    ids = asset_ids_under_target(
        _podcast_scenario(), target_kind="podcast_episode", target_id="podcast_episode_01"
    )

    assert ids == ("asset_podcast",)


@pytest.mark.parametrize(
    ("target_kind", "target_id", "asset_ids"),
    [
        ("movie", "movie_orbit", ("asset_movie",)),
        ("series", "series_starline", ("asset_episode",)),
        ("season", "season_01", ("asset_episode",)),
        ("episode", "episode_01", ("asset_episode",)),
        ("artist", "artist_north", ("asset_track",)),
        ("album", "album_winter", ("asset_track",)),
        ("disc", "disc_01", ("asset_track",)),
        ("track", "track_01", ("asset_track",)),
        ("variant", "variant_movie", ("asset_movie",)),
        ("bundle", "bundle_track", ("asset_track",)),
        ("asset", "asset_movie", ("asset_movie",)),
    ],
)
def test_asset_ids_under_target(
    target_kind: str, target_id: str, asset_ids: tuple[str, ...]
) -> None:
    assert (
        asset_ids_under_target(_scenario(), target_kind=target_kind, target_id=target_id)
        == asset_ids
    )


def test_asset_ids_under_target_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError, match="unknown target_kind"):
        asset_ids_under_target(_scenario(), target_kind="work", target_id="work_001")
