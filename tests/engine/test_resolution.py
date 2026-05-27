"""Tests for chaos_librarian.engine.resolution."""

from __future__ import annotations

from pathlib import Path

from chaos_librarian.contract.scenario import (
    MoveAssetEvent,
    Scenario,
    SlowCopyCommitEvent,
    SlowCopyStartEvent,
    TimelineActionName,
)
from chaos_librarian.engine.resolution import ResolvedEvent, resolve_timeline, step_boundaries
from chaos_librarian.validation import prepare_run_input

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _resolve_fixture(scenario_name: str) -> list[ResolvedEvent]:
    run_input = prepare_run_input(FIXTURE_DIR / scenario_name)
    return resolve_timeline(Scenario.model_validate(run_input.raw_data))


def _scenario(timeline: list[dict[str, object]]) -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 21,
            "scenario_id": "t",
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
            "series": [],
            "artists": [],
            "timeline": timeline,
        }
    )


class TestResolveTimeline:
    """resolve_timeline produces (at_ns, idx, event) triples ordered by time.

    WHY: event handlers and the plan engine must walk a numeric timeline,
    not the string ``at:`` values; the order is the journal's emission
    order, which is part of the contract.
    """

    def test_empty_timeline_returns_empty(self) -> None:
        scenario = _scenario([])
        assert resolve_timeline(scenario) == []

    def test_single_event_returns_one(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "2s",
                    "action": "move_asset",
                    "target": "a0",
                    "to": "movies-hd/x.mkv",
                }
            ]
        )
        resolved = resolve_timeline(scenario)
        assert len(resolved) == 1
        assert resolved[0].at_ns == 2_000_000_000
        assert resolved[0].declared_index == 0
        assert resolved[0].event.action == TimelineActionName.MOVE_ASSET

    def test_multiple_events_preserve_declared_order(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "2s",
                    "action": "move_asset",
                    "target": "a0",
                    "to": "movies-hd/x.mkv",
                },
                {
                    "id": "e1",
                    "at": "5s",
                    "action": "rename_file",
                    "target": "a0",
                    "to": "movies-hd/y.mkv",
                },
            ]
        )
        resolved = resolve_timeline(scenario)
        assert [r.event.id for r in resolved] == ["e0", "e1"]
        assert [r.at_ns for r in resolved] == [2_000_000_000, 5_000_000_000]

    def test_ties_keep_declared_order(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "2s",
                    "action": "move_asset",
                    "target": "a0",
                    "to": "movies-hd/x.mkv",
                },
                {
                    "id": "e1",
                    "at": "2s",
                    "action": "rename_file",
                    "target": "a0",
                    "to": "movies-hd/y.mkv",
                },
            ]
        )
        resolved = resolve_timeline(scenario)
        assert [r.event.id for r in resolved] == ["e0", "e1"]

    def test_zero_at_is_valid(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "0",
                    "action": "move_asset",
                    "target": "a0",
                    "to": "movies-hd/x.mkv",
                }
            ]
        )
        resolved = resolve_timeline(scenario)
        assert resolved[0].at_ns == 0


class TestStepBoundaries:
    """step_boundaries pairs adjacent slow_copy halves into single step units.

    WHY: step_boundaries is the single source of truth for step-unit
    semantics across run_plan, step_fixture, replay_plan_bundle, and
    inspect. Wrong boundaries here mean ``--steps N`` and ``--next N``
    count the wrong thing — exactly the Codex round 3 finding 1 failure
    mode.
    """

    def test_atomic_only_scenario(self) -> None:
        resolved = _resolve_fixture("identity-move-rename.yaml")
        assert step_boundaries(resolved) == [1, 2]

    def test_slow_copy_adjacent_pair_is_one_step(self) -> None:
        resolved = _resolve_fixture("slow-copy.yaml")
        assert step_boundaries(resolved) == [2]

    def test_non_adjacent_slow_copy_degrades_to_singles(self) -> None:
        # A slow_copy_start with an atomic move between it and the commit half,
        # plus a non-matching ``for_`` on the commit, must NOT pair: each event
        # becomes its own single-event step.
        start = SlowCopyStartEvent(
            id="copy_start_001",
            at="1s",
            target="a0",
            to="movies-hd/x.mkv",
            temp_path="movies-hd/x.mkv.part",
            duration="3s",
        )
        move = MoveAssetEvent(id="move_001", at="2s", target="a0", to="movies-hd/y.mkv")
        commit = SlowCopyCommitEvent(id="copy_commit_001", at="3s", for_="other_start")
        resolved = [
            ResolvedEvent(at_ns=1_000_000_000, declared_index=0, event=start),
            ResolvedEvent(at_ns=2_000_000_000, declared_index=1, event=move),
            ResolvedEvent(at_ns=3_000_000_000, declared_index=2, event=commit),
        ]
        assert step_boundaries(resolved) == [1, 2, 3]

    def test_empty_timeline(self) -> None:
        assert step_boundaries([]) == []
