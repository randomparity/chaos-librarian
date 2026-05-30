"""Pin the validation and materializer asset-walker orders in lockstep.

``same_content_as`` / ``hash_collision_with`` correctness depends on the
validator's declaration-order check (``validation.rules._common.iter_asset_contexts``,
a raw-dict walk) and the materializer's actual copy/stamp order
(``topology.iter_asset_contexts``, a model walk) yielding assets in the *same*
order. They are independent implementations; this test fails loudly if a future
reorder of either walker diverges, rather than silently corrupting a duplicate or
collision scenario at materialize time.
"""

from __future__ import annotations

from chaos_librarian.contract.scenario import (
    Album,
    Artist,
    ArtistLayout,
    Asset,
    AudioChannelLayout,
    AudioTrack,
    Bundle,
    Disc,
    DurationScale,
    Episode,
    EpisodeNaming,
    Library,
    LibraryRoot,
    Movie,
    MovieLayout,
    Scenario,
    Season,
    Series,
    SeriesLayout,
    Track,
    TrackNaming,
    Variant,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.topology import iter_asset_contexts as topology_iter_asset_contexts
from chaos_librarian.validation.rules._common import (
    iter_asset_contexts as validation_iter_asset_contexts,
)


def _video_asset(asset_id: str) -> Asset:
    return Asset(
        id=asset_id,
        role="primary_video",
        container="mkv",
        duration_seconds=5,
        video=VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution="hd"),
        audio=(AudioTrack(codec="aac", channels=AudioChannelLayout.STEREO, language="eng"),),
    )


def _audio_asset(asset_id: str) -> Asset:
    return Asset(
        id=asset_id,
        role="main",
        container="flac",
        duration_seconds=5,
        audio=(AudioTrack(codec="flac", channels=AudioChannelLayout.STEREO, language="zxx"),),
    )


def _variant(variant_id: str, bundle_id: str, asset: Asset) -> Variant:
    return Variant(id=variant_id, label="hd", bundle=Bundle(id=bundle_id, assets=(asset,)))


def _multi_tree_scenario() -> Scenario:
    return Scenario(
        schema_version=25,
        scenario_id="walker-order",
        seed=1,
        duration_scale=DurationScale.SHORT,
        library=Library(roots=(LibraryRoot(id="r", path="library"),)),
        movies=(
            Movie(
                id="movie_1",
                title="Movie 1",
                layout=MovieLayout.MOVIE_FLAT,
                variants=(_variant("mv1", "mb1", _video_asset("asset_movie")),),
            ),
        ),
        series=(
            Series(
                id="series_1",
                title="Series 1",
                layout=SeriesLayout.SEASON_FOLDERS,
                episode_naming=EpisodeNaming.SXXEXX_TITLE,
                seasons=(
                    Season(
                        id="season_1",
                        season_number=1,
                        title="Season 1",
                        episodes=(
                            Episode(
                                id="episode_1",
                                episode_number=1,
                                title="Ep 1",
                                variants=(_variant("ev1", "eb1", _video_asset("asset_episode")),),
                            ),
                        ),
                    ),
                ),
            ),
        ),
        artists=(
            Artist(
                id="artist_1",
                name="Artist 1",
                layout=ArtistLayout.ARTIST_ALBUM_DISC,
                track_naming=TrackNaming.TRACK_NUMBER_TITLE,
                albums=(
                    Album(
                        id="album_1",
                        title="Album 1",
                        discs=(
                            Disc(
                                id="disc_1",
                                disc_number=1,
                                tracks=(
                                    Track(
                                        id="track_1",
                                        track_number=1,
                                        title="Track 1",
                                        variants=(
                                            _variant("tv1", "tb1", _audio_asset("asset_track")),
                                        ),
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
        timeline=(),
    )


def test_validation_and_topology_asset_walkers_agree() -> None:
    scenario = _multi_tree_scenario()
    raw = scenario.model_dump(mode="json")

    validation_ids = [context.asset["id"] for context in validation_iter_asset_contexts(raw)]
    topology_ids = [context.asset.id for context in topology_iter_asset_contexts(scenario)]

    # Exercises all three asset trees (movie, episode, track) so the lockstep
    # guarantee is fully pinned, not just the movie branch.
    assert validation_ids == ["asset_movie", "asset_episode", "asset_track"]
    assert topology_ids == validation_ids
