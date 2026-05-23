"""Tests for chaos_librarian.engine.state."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.manifest import Manifest, ManifestSidecar
from chaos_librarian.contract.paths import INITIAL_PATH_TEMPLATE
from chaos_librarian.contract.scenario import Scenario, SidecarKind
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.state import WorldState, build_initial_state
from chaos_librarian.validation import prepare_run_input_from_bytes, run_validation
from chaos_librarian.validation.codes import E_PATH_CONTAINMENT
from tests.engine.conftest import _build_minimal_scenario


def _scenario_from_dict(data: dict[str, object]) -> Scenario:
    return Scenario.model_validate(data)


def _minimal_scenario() -> Scenario:
    return _scenario_from_dict(
        {
            "schema_version": 8,
            "scenario_id": "min",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
            "works": [
                {
                    "id": "w0",
                    "title": "T",
                    "variants": [
                        {
                            "id": "v0",
                            "label": "hd",
                            "bundle": {
                                "id": "b0",
                                "assets": [
                                    {
                                        "id": "a0",
                                        "role": "primary_video",
                                        "container": "mkv",
                                        "duration_seconds": 1,
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
            "timeline": [],
        }
    )


class TestBuildInitialState:
    """The initial WorldState assigns each asset one version and one location.

    WHY: this convention is the contract for downstream consumers — voom-v2
    relies on knowing that ``manifest.initial.json`` contains exactly one
    version+location per declared asset, at a deterministic synthesized path.
    """

    def test_one_version_and_location_per_asset(self) -> None:
        scenario = _minimal_scenario()
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        assert len(state.versions) == 1
        assert len(state.locations) == 1

    def test_initial_location_path_uses_first_root(self) -> None:
        scenario = _minimal_scenario()
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (loc,) = state.locations.values()
        assert loc.path == "movies-hd/a0.mkv"

    def test_world_state_serializes_to_manifest(self) -> None:
        scenario = _minimal_scenario()
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        manifest = state.to_manifest()
        assert isinstance(manifest, Manifest)
        assert manifest.schema_version == 5
        assert [w.id for w in manifest.works] == ["w0"]
        assert [v.id for v in manifest.variants] == ["v0"]
        assert [b.id for b in manifest.bundles] == ["b0"]
        assert [a.id for a in manifest.assets] == ["a0"]
        assert len(manifest.versions) == 1
        assert len(manifest.locations) == 1

    def test_two_assets_get_independent_locations(self) -> None:
        scenario = _scenario_from_dict(
            {
                "schema_version": 8,
                "scenario_id": "two",
                "seed": 1,
                "duration_scale": "short",
                "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
                "works": [
                    {
                        "id": "w0",
                        "title": "T",
                        "variants": [
                            {
                                "id": "v0",
                                "label": "hd",
                                "bundle": {
                                    "id": "b0",
                                    "assets": [
                                        {
                                            "id": "a0",
                                            "role": "primary_video",
                                            "container": "mkv",
                                            "duration_seconds": 1,
                                        },
                                        {
                                            "id": "a1",
                                            "role": "primary_video",
                                            "container": "mp4",
                                            "duration_seconds": 1,
                                        },
                                    ],
                                },
                            }
                        ],
                    }
                ],
                "timeline": [],
            }
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        paths = sorted(loc.path for loc in state.locations.values())
        assert paths == ["movies-hd/a0.mkv", "movies-hd/a1.mp4"]


class TestWorldStateMutations:
    """The dataclass supports the mutations event handlers need.

    WHY: handler code (Task 5+) must be able to look up an asset's current
    location in O(1) and mutate it without rebuilding the entire WorldState.
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


class TestUnsafeAssetIdRejectedBeforeBuildInitialState:
    """A scenario whose ``asset.id`` escapes containment fails validation.

    WHY: ``build_initial_state`` concatenates ``asset.id`` directly into
    the synthesized location path. The validation gate is the only thing
    keeping that concatenation safe; if this regression starts passing
    (i.e. the rule no longer fires) the engine would silently produce a
    manifest path outside the library root. Closes Codex adversarial-
    review finding 3.
    """

    def test_asset_id_traversal_rejected_by_validation(self) -> None:
        yaml_bytes = b"""\
schema_version: 8
scenario_id: unsafe-id
seed: 1
duration_scale: short
library:
  roots:
    - id: r0
      path: movies-hd
works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: ../../escape
              role: primary_video
              container: mkv
              duration_seconds: 1
timeline: []
"""
        run_input = prepare_run_input_from_bytes(
            raw_bytes=yaml_bytes,
            source_label="test:unsafe-id",
        )
        report = run_validation(run_input)
        assert report.ok is False
        assert any(i.code == E_PATH_CONTAINMENT for i in report.issues)


def test_world_state_root_path_for_returns_declared_path() -> None:
    scenario = _build_minimal_scenario(
        roots=[("movies-hd", "library/movies-hd"), ("staging", "library/staging")],
        works=[("work_001", "asset_hd_main", "mkv")],
    )
    state = build_initial_state(scenario, IdAllocator(TraceRecorder()))
    assert state.root_path_for("movies-hd") == "library/movies-hd"
    assert state.root_path_for("staging") == "library/staging"


def test_world_state_archive_path_for_default_root() -> None:
    scenario = _build_minimal_scenario(
        roots=[("movies-hd", "library/movies-hd")],
        works=[("work_001", "asset_hd_main", "mkv")],
    )
    state = build_initial_state(scenario, IdAllocator(TraceRecorder()))
    assert state.archive_path_for("asset_hd_main") == (
        "library/movies-hd/archive/asset_hd_main.mkv"
    )


def test_world_state_archive_path_for_sentinel_value() -> None:
    scenario = _build_minimal_scenario(
        roots=[("movies-hd", "library/movies-hd")],
        works=[("work_001", "asset_hd_main", "mkv")],
        archive_root="archive",
    )
    state = build_initial_state(scenario, IdAllocator(TraceRecorder()))
    assert state.archive_path_for("asset_hd_main") == (
        "library/movies-hd/archive/asset_hd_main.mkv"
    )


def test_world_state_archive_path_for_explicit_root() -> None:
    scenario = _build_minimal_scenario(
        roots=[
            ("movies-hd", "library/movies-hd"),
            ("cold-storage", "library/cold-storage"),
        ],
        works=[("work_001", "asset_hd_main", "mkv")],
        archive_root="cold-storage",
    )
    state = build_initial_state(scenario, IdAllocator(TraceRecorder()))
    assert state.archive_path_for("asset_hd_main") == ("library/cold-storage/asset_hd_main.mkv")


def test_initial_path_template_format() -> None:
    # Module-level constant lifted from build_initial_state so the slow-copy
    # validation rule can format an asset's initial path without duplicating
    # the convention.
    assert (
        INITIAL_PATH_TEMPLATE.format(
            root_path="library/movies-hd",
            asset_id="asset_hd_main",
            container="mkv",
        )
        == "library/movies-hd/asset_hd_main.mkv"
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
    # Same path, different asset — the lookup must respect asset_id.
    assert state.sidecar_id_for_path("asset_a", "a.eng.srt") == "sidecar_0001"
    assert state.sidecar_id_for_path("asset_b", "a.eng.srt") == "sidecar_0002"


class TestBuildInitialStateSeedsDeclaredSidecars:
    """``build_initial_state`` mirrors the validator's projection of declared subtitles.

    WHY: the validator's ``_seed_projection_from_declared`` accepts
    ``embed_subtitle.sidecar_path = <asset>.<lang>.srt`` for any declared
    ``mode: sidecar`` subtitle. The engine handlers (``embed_subtitle``,
    ``update_sidecar``, ``remove_sidecar``) resolve that path through
    ``WorldState.sidecar_id_for_path``. If state.sidecars is empty for the
    declared subtitle, validation accepts the scenario but the engine
    raises KeyError mid-run. The seed below closes that gap.
    """

    def test_declared_sidecar_subtitle_seeds_one_row(self) -> None:
        scenario = _scenario_from_dict(
            {
                "schema_version": 8,
                "scenario_id": "side",
                "seed": 1,
                "duration_scale": "short",
                "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
                "works": [
                    {
                        "id": "w0",
                        "title": "T",
                        "variants": [
                            {
                                "id": "v0",
                                "label": "hd",
                                "bundle": {
                                    "id": "b0",
                                    "assets": [
                                        {
                                            "id": "a0",
                                            "role": "primary_video",
                                            "container": "mkv",
                                            "duration_seconds": 1,
                                            "subtitles": [
                                                {
                                                    "codec": "srt",
                                                    "language": "eng",
                                                    "mode": "sidecar",
                                                }
                                            ],
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                ],
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
        assert sidecar.path == "a0.eng.srt"
        assert sidecar.language == "eng"

    def test_embedded_mode_subtitle_is_not_seeded(self) -> None:
        scenario = _scenario_from_dict(
            {
                "schema_version": 8,
                "scenario_id": "emb",
                "seed": 1,
                "duration_scale": "short",
                "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
                "works": [
                    {
                        "id": "w0",
                        "title": "T",
                        "variants": [
                            {
                                "id": "v0",
                                "label": "hd",
                                "bundle": {
                                    "id": "b0",
                                    "assets": [
                                        {
                                            "id": "a0",
                                            "role": "primary_video",
                                            "container": "mkv",
                                            "duration_seconds": 1,
                                            "subtitles": [
                                                {
                                                    "codec": "srt",
                                                    "language": "eng",
                                                    "mode": "embedded",
                                                }
                                            ],
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                ],
                "timeline": [],
            }
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        assert state.sidecars == {}

    def test_sidecar_id_for_path_resolves_declared_subtitle(self) -> None:
        scenario = _scenario_from_dict(
            {
                "schema_version": 8,
                "scenario_id": "side",
                "seed": 1,
                "duration_scale": "short",
                "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
                "works": [
                    {
                        "id": "w0",
                        "title": "T",
                        "variants": [
                            {
                                "id": "v0",
                                "label": "hd",
                                "bundle": {
                                    "id": "b0",
                                    "assets": [
                                        {
                                            "id": "a0",
                                            "role": "primary_video",
                                            "container": "mkv",
                                            "duration_seconds": 1,
                                            "subtitles": [
                                                {
                                                    "codec": "srt",
                                                    "language": "eng",
                                                    "mode": "sidecar",
                                                }
                                            ],
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                ],
                "timeline": [],
            }
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        assert state.sidecar_id_for_path("a0", "a0.eng.srt") == "sidecar_a0_eng"
