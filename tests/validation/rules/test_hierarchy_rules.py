"""Hierarchy validation tests for Scenario v12 semantic rules."""

from __future__ import annotations

from typing import cast

from chaos_librarian.contract.validation import ValidationIssue
from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


def _items(node: object) -> list[dict[str, object]]:
    return cast("list[dict[str, object]]", node)


def _mapping(node: object) -> dict[str, object]:
    return cast("dict[str, object]", node)


def _issues_for(raw: dict[str, object], empty_index) -> list[ValidationIssue]:
    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)
    return collector.issues


def test_movie_asset_target_is_found_by_raw_hierarchy_walker(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        timeline=[{"id": "ev", "at": "1s", "action": "delete_file", "target": "a"}]
    )

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_TARGET_UNKNOWN for issue in issues)


def test_episode_asset_target_is_found_by_raw_hierarchy_walker(
    series_scenario, empty_index
) -> None:
    raw = series_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "delete_file",
                "target": "asset_episode",
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_TARGET_UNKNOWN for issue in issues)


def test_track_asset_target_is_found_by_raw_hierarchy_walker(music_scenario, empty_index) -> None:
    raw = music_scenario(
        timeline=[
            {
                "id": "ev",
                "at": "1s",
                "action": "delete_file",
                "target": "asset_track",
            }
        ]
    )

    issues = _issues_for(raw, empty_index)

    assert not any(issue.code == codes.E_TARGET_UNKNOWN for issue in issues)
