"""Tests for chaos_librarian.engine.resolution."""

from __future__ import annotations

from chaos_librarian.contract.scenario import Scenario, TimelineActionName
from chaos_librarian.engine.resolution import resolve_timeline


def _scenario(timeline: list[dict[str, object]]) -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 1,
            "scenario_id": "t",
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
