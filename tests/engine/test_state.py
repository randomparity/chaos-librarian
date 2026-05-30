"""Tests for chaos_librarian.engine.state."""

from __future__ import annotations

import pytest

from chaos_librarian.contract import MANIFEST_SCHEMA_VERSION
from chaos_librarian.contract.domain import ParentKind
from chaos_librarian.contract.manifest import Manifest, ManifestSidecar
from chaos_librarian.contract.scenario import Scenario, SidecarKind
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.state import WorldState, build_initial_state
from tests.engine.conftest import _build_minimal_scenario


def _scenario_from_dict(data: dict[str, object]) -> Scenario:
    return Scenario.model_validate(data)


def _video_asset_payload(
    asset_id: str = "a0",
    *,
    role: str = "primary_video",
    container: str = "mkv",
    subtitles: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    asset: dict[str, object] = {
        "id": asset_id,
        "role": role,
        "container": container,
        "duration_seconds": 1,
    }
    if subtitles is not None:
        asset["subtitles"] = subtitles
    return asset


def _audio_asset_payload(asset_id: str = "asset_track") -> dict[str, object]:
    return {
        "id": asset_id,
        "role": "main",
        "container": "flac",
        "duration_seconds": 1,
        "audio": [{"codec": "flac", "channels": "stereo", "language": "zxx"}],
    }


def _variant_payload(
    asset: dict[str, object],
    *,
    variant_id: str = "v0",
    bundle_id: str = "b0",
    label: str = "hd",
) -> dict[str, object]:
    return {
        "id": variant_id,
        "label": label,
        "bundle": {"id": bundle_id, "assets": [asset]},
    }


def _minimal_scenario() -> Scenario:
    return _scenario_from_dict(
        {
            "schema_version": 31,
            "scenario_id": "min",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
            "movies": [
                {
                    "id": "movie_0",
                    "title": "T",
                    "layout": "movie_flat",
                    "variants": [_variant_payload(_video_asset_payload())],
                }
            ],
            "series": [],
            "artists": [],
            "timeline": [],
        }
    )


class TestBuildInitialState:
    """The initial WorldState assigns each asset one version and one location.

    WHY: this convention is the contract for downstream consumers. voom-v2
    relies on ``manifest.initial.json`` containing exactly one
    version+location per declared asset, at a deterministic rendered path.
    """

    def test_one_version_and_location_per_asset(self) -> None:
        scenario = _minimal_scenario()
        ids = IdAllocator(TraceRecorder())

        state = build_initial_state(scenario, ids)

        assert len(state.versions) == 1
        assert len(state.locations) == 1

    def test_initial_location_path_uses_hierarchy_renderer_and_first_root(self) -> None:
        scenario = _minimal_scenario()
        ids = IdAllocator(TraceRecorder())

        state = build_initial_state(scenario, ids)

        (loc,) = state.locations.values()
        assert loc.path == "movies-hd/T - hd.mkv"

    def test_world_state_serializes_to_normalized_manifest(self) -> None:
        scenario = _minimal_scenario()
        ids = IdAllocator(TraceRecorder())

        state = build_initial_state(scenario, ids)
        manifest = state.to_manifest()

        assert isinstance(manifest, Manifest)
        assert manifest.schema_version == MANIFEST_SCHEMA_VERSION
        assert [movie.id for movie in manifest.movies] == ["movie_0"]
        assert manifest.series == []
        assert manifest.artists == []
        assert [variant.id for variant in manifest.variants] == ["v0"]
        assert manifest.variants[0].parent_kind is ParentKind.MOVIE
        assert manifest.variants[0].parent_id == "movie_0"
        assert [bundle.id for bundle in manifest.bundles] == ["b0"]
        assert [asset.id for asset in manifest.assets] == ["a0"]
        assert len(manifest.versions) == 1
        assert len(manifest.locations) == 1

    def test_multi_asset_bundle_seeds_domain_rows_once(self) -> None:
        scenario = _scenario_from_dict(
            {
                "schema_version": 31,
                "scenario_id": "two",
                "seed": 1,
                "duration_scale": "short",
                "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
                "movies": [
                    {
                        "id": "movie_0",
                        "title": "T",
                        "layout": "movie_flat",
                        "variants": [
                            {
                                "id": "v0",
                                "label": "hd",
                                "bundle": {
                                    "id": "b0",
                                    "assets": [
                                        _video_asset_payload("a0"),
                                        _video_asset_payload(
                                            "a1",
                                            role="preview",
                                            container="mp4",
                                        ),
                                    ],
                                },
                            }
                        ],
                    }
                ],
                "series": [],
                "artists": [],
                "timeline": [],
            }
        )
        ids = IdAllocator(TraceRecorder())

        state = build_initial_state(scenario, ids)
        manifest = state.to_manifest()

        assert [movie.id for movie in manifest.movies] == ["movie_0"]
        assert [variant.id for variant in manifest.variants] == ["v0"]
        assert [bundle.id for bundle in manifest.bundles] == ["b0"]
        assert sorted(location.path for location in state.locations.values()) == [
            "movies-hd/T - hd - preview.mp4",
            "movies-hd/T - hd - primary_video.mkv",
        ]

    def test_walks_movie_episode_and_track_hierarchies(self) -> None:
        scenario = _scenario_from_dict(
            {
                "schema_version": 31,
                "scenario_id": "all-domains",
                "seed": 1,
                "duration_scale": "short",
                "library": {"roots": [{"id": "primary", "path": "library"}]},
                "movies": [
                    {
                        "id": "movie_orbit",
                        "title": "Orbit",
                        "layout": "movie_flat",
                        "variants": [
                            _variant_payload(
                                _video_asset_payload("asset_movie"),
                                variant_id="variant_movie",
                                bundle_id="bundle_movie",
                                label="1080p",
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
                                "id": "season_specials",
                                "season_number": 0,
                                "title": "Specials",
                                "episodes": [
                                    {
                                        "id": "episode_special_01",
                                        "episode_number": 1,
                                        "title": "First Signal",
                                        "variants": [
                                            _variant_payload(
                                                _video_asset_payload("asset_episode"),
                                                variant_id="variant_episode",
                                                bundle_id="bundle_episode",
                                                label="1080p",
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
                                "discs": [
                                    {
                                        "id": "disc_winter_01",
                                        "disc_number": 1,
                                        "tracks": [
                                            {
                                                "id": "track_opening",
                                                "track_number": 1,
                                                "title": "Opening",
                                                "performers": ["North Index"],
                                                "variants": [
                                                    _variant_payload(
                                                        _audio_asset_payload(),
                                                        variant_id="variant_track",
                                                        bundle_id="bundle_track",
                                                        label="lossless",
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
        ids = IdAllocator(TraceRecorder())

        state = build_initial_state(scenario, ids)
        manifest = state.to_manifest()

        assert [movie.id for movie in manifest.movies] == ["movie_orbit"]
        assert [series.id for series in manifest.series] == ["series_starline"]
        assert [season.id for season in manifest.seasons] == ["season_specials"]
        assert [episode.id for episode in manifest.episodes] == ["episode_special_01"]
        assert [artist.id for artist in manifest.artists] == ["artist_north"]
        assert [album.id for album in manifest.albums] == ["album_winter"]
        assert [disc.id for disc in manifest.discs] == ["disc_winter_01"]
        assert [track.id for track in manifest.tracks] == ["track_opening"]
        assert sorted(location.path for location in state.locations.values()) == [
            "library/North Index/Winter Index/Disc 01/01 - Opening - lossless.flac",
            "library/Orbit - 1080p.mkv",
            "library/Starline/Season 00/Starline - S00E01 - First Signal - 1080p.mkv",
        ]

    def test_empty_bundles_still_seed_variant_and_bundle_rows(self) -> None:
        scenario = _scenario_from_dict(
            {
                "schema_version": 31,
                "scenario_id": "empty-bundles",
                "seed": 1,
                "duration_scale": "short",
                "library": {"roots": [{"id": "primary", "path": "library"}]},
                "movies": [
                    {
                        "id": "movie_orbit",
                        "title": "Orbit",
                        "layout": "movie_flat",
                        "variants": [
                            {
                                "id": "variant_movie",
                                "label": "1080p",
                                "bundle": {"id": "bundle_movie", "assets": []},
                            }
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
                                "id": "season_specials",
                                "season_number": 0,
                                "title": "Specials",
                                "episodes": [
                                    {
                                        "id": "episode_special_01",
                                        "episode_number": 1,
                                        "title": "First Signal",
                                        "variants": [
                                            {
                                                "id": "variant_episode",
                                                "label": "1080p",
                                                "bundle": {
                                                    "id": "bundle_episode",
                                                    "assets": [],
                                                },
                                            }
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
                                "discs": [
                                    {
                                        "id": "disc_winter_01",
                                        "disc_number": 1,
                                        "tracks": [
                                            {
                                                "id": "track_opening",
                                                "track_number": 1,
                                                "title": "Opening",
                                                "performers": ["North Index"],
                                                "variants": [
                                                    {
                                                        "id": "variant_track",
                                                        "label": "lossless",
                                                        "bundle": {
                                                            "id": "bundle_track",
                                                            "assets": [],
                                                        },
                                                    }
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
        ids = IdAllocator(TraceRecorder())

        state = build_initial_state(scenario, ids)
        manifest = state.to_manifest()

        assert [
            (variant.id, variant.parent_kind, variant.parent_id) for variant in manifest.variants
        ] == [
            ("variant_movie", ParentKind.MOVIE, "movie_orbit"),
            ("variant_episode", ParentKind.EPISODE, "episode_special_01"),
            ("variant_track", ParentKind.TRACK, "track_opening"),
        ]
        assert [(bundle.id, bundle.variant_id) for bundle in manifest.bundles] == [
            ("bundle_movie", "variant_movie"),
            ("bundle_episode", "variant_episode"),
            ("bundle_track", "variant_track"),
        ]
        assert manifest.assets == []
        assert manifest.versions == []
        assert manifest.locations == []


class TestWorldStateMutations:
    """The dataclass supports the mutations event handlers need.

    WHY: handler code must be able to look up an asset's current location
    in O(1) and mutate it without rebuilding the entire WorldState.
    """

    def test_move_asset_location_updates_path(self) -> None:
        scenario = _minimal_scenario()
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)

        loc_id = state.location_id_for_asset("a0")
        state.locations[loc_id] = state.locations[loc_id].model_copy(
            update={"path": "movies-hd/Renamed.mkv"}
        )

        (loc,) = state.locations.values()
        assert loc.path == "movies-hd/Renamed.mkv"


def test_world_state_root_path_for_returns_declared_path() -> None:
    scenario = _build_minimal_scenario(
        roots=[("movies-hd", "library/movies-hd"), ("staging", "library/staging")],
        movies=[("movie_001", "asset_hd_main", "mkv")],
    )
    state = build_initial_state(scenario, IdAllocator(TraceRecorder()))

    assert state.root_path_for("movies-hd") == "library/movies-hd"
    assert state.root_path_for("staging") == "library/staging"


def test_world_state_archive_path_for_default_root() -> None:
    scenario = _build_minimal_scenario(
        roots=[("movies-hd", "library/movies-hd")],
        movies=[("movie_001", "asset_hd_main", "mkv")],
    )
    state = build_initial_state(scenario, IdAllocator(TraceRecorder()))

    assert state.archive_path_for("asset_hd_main") == (
        "library/movies-hd/archive/movie_001 - default.mkv"
    )


def test_world_state_archive_path_for_sentinel_value() -> None:
    scenario = _build_minimal_scenario(
        roots=[("movies-hd", "library/movies-hd")],
        movies=[("movie_001", "asset_hd_main", "mkv")],
        archive_root="archive",
    )
    state = build_initial_state(scenario, IdAllocator(TraceRecorder()))

    assert state.archive_path_for("asset_hd_main") == (
        "library/movies-hd/archive/movie_001 - default.mkv"
    )


def test_world_state_archive_path_for_explicit_root() -> None:
    scenario = _build_minimal_scenario(
        roots=[
            ("movies-hd", "library/movies-hd"),
            ("cold-storage", "library/cold-storage"),
        ],
        movies=[("movie_001", "asset_hd_main", "mkv")],
        archive_root="cold-storage",
    )
    state = build_initial_state(scenario, IdAllocator(TraceRecorder()))

    assert state.archive_path_for("asset_hd_main") == "library/cold-storage/movie_001 - default.mkv"


def test_world_state_archive_path_for_unsafe_asset_id_preserves_rendered_suffix() -> None:
    scenario = _build_minimal_scenario(
        roots=[("movies-hd", "library/movies-hd")],
        movies=[("movie_001", "../../escape", "mkv")],
    )
    state = build_initial_state(scenario, IdAllocator(TraceRecorder()))

    assert state.archive_path_for("../../escape") == (
        "library/movies-hd/archive/movie_001 - default.mkv"
    )


def test_sidecar_id_for_path_returns_id_when_match() -> None:
    state = WorldState()
    state.sidecars["sidecar_0001"] = ManifestSidecar(
        id="sidecar_0001",
        asset_id="asset_main",
        kind=SidecarKind.SUBTITLE,
        path="asset_main.eng.srt",
        language="eng",
    )

    assert state.sidecar_id_for_path("asset_main", "asset_main.eng.srt") == "sidecar_0001"


def test_sidecar_id_for_path_raises_keyerror_on_miss() -> None:
    state = WorldState()
    with pytest.raises(KeyError, match="no sidecar"):
        state.sidecar_id_for_path("asset_main", "missing.srt")


def test_sidecar_id_for_path_scoped_by_asset_id() -> None:
    state = WorldState()
    state.sidecars["sidecar_0001"] = ManifestSidecar(
        id="sidecar_0001",
        asset_id="asset_a",
        kind=SidecarKind.SUBTITLE,
        path="a.eng.srt",
        language="eng",
    )
    state.sidecars["sidecar_0002"] = ManifestSidecar(
        id="sidecar_0002",
        asset_id="asset_b",
        kind=SidecarKind.SUBTITLE,
        path="a.eng.srt",
        language="eng",
    )

    assert state.sidecar_id_for_path("asset_a", "a.eng.srt") == "sidecar_0001"
    assert state.sidecar_id_for_path("asset_b", "a.eng.srt") == "sidecar_0002"


def _add_sidecar(
    state: WorldState, sidecar_id: str, asset_id: str, *, renderer_derived: bool
) -> None:
    state.sidecars[sidecar_id] = ManifestSidecar(
        id=sidecar_id,
        asset_id=asset_id,
        kind=SidecarKind.SUBTITLE,
        path=f"{asset_id}.{sidecar_id}.eng.srt",
        language="eng",
    )
    if renderer_derived:
        state._renderer_derived_sidecar_ids.add(sidecar_id)


class TestRendererDerivedSidecarsByAsset:
    """Grouping renderer-derived sidecars in one scan, in manifest order."""

    def test_groups_by_asset_in_manifest_order(self) -> None:
        state = WorldState()
        _add_sidecar(state, "sidecar_0001", "asset_a", renderer_derived=True)
        _add_sidecar(state, "sidecar_0002", "asset_b", renderer_derived=True)
        _add_sidecar(state, "sidecar_0003", "asset_a", renderer_derived=True)

        grouped = state.renderer_derived_sidecars_by_asset(["asset_a", "asset_b"])

        assert [s.id for s in grouped["asset_a"]] == ["sidecar_0001", "sidecar_0003"]
        assert [s.id for s in grouped["asset_b"]] == ["sidecar_0002"]

    def test_excludes_non_renderer_derived_sidecars(self) -> None:
        state = WorldState()
        _add_sidecar(state, "sidecar_0001", "asset_a", renderer_derived=True)
        _add_sidecar(state, "sidecar_0002", "asset_a", renderer_derived=False)

        grouped = state.renderer_derived_sidecars_by_asset(["asset_a"])

        assert [s.id for s in grouped["asset_a"]] == ["sidecar_0001"]

    def test_excludes_assets_outside_requested_set(self) -> None:
        state = WorldState()
        _add_sidecar(state, "sidecar_0001", "asset_a", renderer_derived=True)
        _add_sidecar(state, "sidecar_0002", "asset_b", renderer_derived=True)

        grouped = state.renderer_derived_sidecars_by_asset(["asset_a"])

        assert "asset_b" not in grouped
        assert set(grouped) == {"asset_a"}

    def test_absent_when_no_renderer_derived_sidecars(self) -> None:
        state = WorldState()
        _add_sidecar(state, "sidecar_0001", "asset_a", renderer_derived=False)

        grouped = state.renderer_derived_sidecars_by_asset(["asset_a"])

        assert grouped == {}


class TestBuildInitialStateSeedsDeclaredSidecars:
    """``build_initial_state`` mirrors the validator's projection of subtitles.

    WHY: the validator accepts an event path for any declared
    ``mode: sidecar`` subtitle. The engine handlers resolve that path
    through ``WorldState.sidecar_id_for_path``. If state.sidecars is
    empty for the declared subtitle, validation accepts the scenario but
    the engine raises KeyError mid-run.
    """

    def test_declared_sidecar_subtitle_seeds_one_row_at_rendered_media_path(self) -> None:
        scenario = _scenario_from_dict(
            {
                "schema_version": 31,
                "scenario_id": "side",
                "seed": 1,
                "duration_scale": "short",
                "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
                "movies": [
                    {
                        "id": "movie_0",
                        "title": "T",
                        "layout": "movie_flat",
                        "variants": [
                            _variant_payload(
                                _video_asset_payload(
                                    subtitles=[
                                        {
                                            "codec": "srt",
                                            "language": "eng",
                                            "mode": "sidecar",
                                        }
                                    ]
                                )
                            )
                        ],
                    }
                ],
                "series": [],
                "artists": [],
                "timeline": [],
            }
        )
        ids = IdAllocator(TraceRecorder())

        state = build_initial_state(scenario, ids)

        assert len(state.sidecars) == 1
        (sidecar,) = state.sidecars.values()
        assert sidecar.id == "sidecar_a0_eng"
        assert sidecar.asset_id == "a0"
        assert sidecar.kind == SidecarKind.SUBTITLE.value
        assert sidecar.path == "movies-hd/T - hd.eng.srt"
        assert sidecar.language == "eng"

    def test_embedded_mode_subtitle_is_not_seeded(self) -> None:
        scenario = _scenario_from_dict(
            {
                "schema_version": 31,
                "scenario_id": "emb",
                "seed": 1,
                "duration_scale": "short",
                "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
                "movies": [
                    {
                        "id": "movie_0",
                        "title": "T",
                        "layout": "movie_flat",
                        "variants": [
                            _variant_payload(
                                _video_asset_payload(
                                    subtitles=[
                                        {
                                            "codec": "srt",
                                            "language": "eng",
                                            "mode": "embedded",
                                        }
                                    ]
                                )
                            )
                        ],
                    }
                ],
                "series": [],
                "artists": [],
                "timeline": [],
            }
        )
        ids = IdAllocator(TraceRecorder())

        state = build_initial_state(scenario, ids)

        assert state.sidecars == {}

    def test_sidecar_id_for_path_resolves_declared_subtitle(self) -> None:
        scenario = _scenario_from_dict(
            {
                "schema_version": 31,
                "scenario_id": "side",
                "seed": 1,
                "duration_scale": "short",
                "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
                "movies": [
                    {
                        "id": "movie_0",
                        "title": "T",
                        "layout": "movie_flat",
                        "variants": [
                            _variant_payload(
                                _video_asset_payload(
                                    subtitles=[
                                        {
                                            "codec": "srt",
                                            "language": "eng",
                                            "mode": "sidecar",
                                        }
                                    ]
                                )
                            )
                        ],
                    }
                ],
                "series": [],
                "artists": [],
                "timeline": [],
            }
        )
        ids = IdAllocator(TraceRecorder())

        state = build_initial_state(scenario, ids)

        assert state.sidecar_id_for_path("a0", "movies-hd/T - hd.eng.srt") == ("sidecar_a0_eng")
