"""Tests for chaos_librarian.engine.state."""

from __future__ import annotations

from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.state import build_initial_state
from chaos_librarian.validation import prepare_run_input_from_bytes, run_validation
from chaos_librarian.validation.codes import E_PATH_CONTAINMENT


def _scenario_from_dict(data: dict[str, object]) -> Scenario:
    return Scenario.model_validate(data)


def _minimal_scenario() -> Scenario:
    return _scenario_from_dict(
        {
            "schema_version": 2,
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
        assert manifest.schema_version == 2
        assert [w.id for w in manifest.works] == ["w0"]
        assert [v.id for v in manifest.variants] == ["v0"]
        assert [b.id for b in manifest.bundles] == ["b0"]
        assert [a.id for a in manifest.assets] == ["a0"]
        assert len(manifest.versions) == 1
        assert len(manifest.locations) == 1

    def test_two_assets_get_independent_locations(self) -> None:
        scenario = _scenario_from_dict(
            {
                "schema_version": 2,
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
schema_version: 2
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
