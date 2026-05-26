"""Tests for performance profile budget validation."""

from __future__ import annotations

from typing import cast

from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


def _asset(asset_id: str) -> dict[str, object]:
    return {
        "id": asset_id,
        "role": "primary_video",
        "container": "mkv",
        "duration_seconds": 1,
    }


def _first_movie_bundle(raw: dict[str, object]) -> dict[str, object]:
    movies = cast("list[dict[str, object]]", raw["movies"])
    movie = movies[0]
    variants = cast("list[dict[str, object]]", movie["variants"])
    variant = variants[0]
    return cast("dict[str, object]", variant["bundle"])


def test_performance_smoke_asset_ceiling_emits(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(profiles=["performance-smoke"])
    bundle = _first_movie_bundle(raw)
    bundle["assets"] = [_asset(f"a{i}") for i in range(41)]
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert any(
        issue.code == codes.E_PROFILE_BUDGET_EXCEEDED
        and "assets" in issue.message
        and "performance-smoke" in issue.message
        for issue in collector.issues
    )


def test_performance_smoke_timeline_ceiling_emits(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["performance-smoke"],
        timeline=[
            {
                "id": f"move_{i}",
                "at": f"{i}ns",
                "action": "move_asset",
                "target": "a",
                "to": f"r/a-{i}.mkv",
            }
            for i in range(161)
        ],
    )
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert any(
        issue.code == codes.E_PROFILE_BUDGET_EXCEEDED
        and "timeline events" in issue.message
        and "performance-smoke" in issue.message
        for issue in collector.issues
    )


def test_performance_smoke_within_static_ceiling_passes(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["performance-smoke"],
        timeline=[
            {
                "id": "move_1",
                "at": "1ns",
                "action": "move_asset",
                "target": "a",
                "to": "r/a-1.mkv",
            }
        ],
    )
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert not any(issue.code == codes.E_PROFILE_BUDGET_EXCEEDED for issue in collector.issues)


def test_fuzz_smoke_asset_ceiling_emits(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(profiles=["fuzz-smoke"])
    bundle = _first_movie_bundle(raw)
    bundle["assets"] = [_asset(f"a{i}") for i in range(5)]
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert any(
        issue.code == codes.E_PROFILE_BUDGET_EXCEEDED
        and "assets" in issue.message
        and "fuzz-smoke" in issue.message
        for issue in collector.issues
    )


def test_fuzz_smoke_timeline_ceiling_emits(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["fuzz-smoke"],
        timeline=[
            {
                "id": f"move_{i}",
                "at": f"{i}ns",
                "action": "move_asset",
                "target": "a",
                "to": f"r/a-{i}.mkv",
            }
            for i in range(13)
        ],
    )
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert any(
        issue.code == codes.E_PROFILE_BUDGET_EXCEEDED
        and "timeline events" in issue.message
        and "fuzz-smoke" in issue.message
        for issue in collector.issues
    )


def test_fuzz_regression_accepts_fuzz_smoke_sized_case(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["fuzz-regression"],
        timeline=[
            {
                "id": f"move_{i}",
                "at": f"{i}ns",
                "action": "move_asset",
                "target": "a",
                "to": f"r/a-{i}.mkv",
            }
            for i in range(13)
        ],
    )
    bundle = _first_movie_bundle(raw)
    bundle["assets"] = [_asset(f"a{i}") for i in range(5)]
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert not any(issue.code == codes.E_PROFILE_BUDGET_EXCEEDED for issue in collector.issues)
