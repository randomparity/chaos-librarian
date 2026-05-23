"""Tests for malformed-media profile opt-in validation."""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


def _corruption_event(target: str = "a") -> dict[str, object]:
    return {
        "id": "corrupt_header_001",
        "at": "1s",
        "action": "corrupt_container_header",
        "target": target,
    }


def _lag_start_event() -> dict[str, object]:
    return {
        "id": "lag_start_001",
        "at": "1s",
        "action": "network_lag_start",
        "effect": "delayed_rename",
        "target": "a",
        "after": "rename_001",
        "duration": "1s",
    }


def test_corruption_without_profile_emits_e_profile_required(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(timeline=[_corruption_event()])
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert any(issue.code == codes.E_PROFILE_REQUIRED for issue in collector.issues)


def test_corruption_with_malformed_media_profile_passes_profile_rule(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        profiles=["malformed-media"],
        timeline=[_corruption_event()],
    )
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert not any(issue.code == codes.E_PROFILE_REQUIRED for issue in collector.issues)


def test_network_lag_without_profile_emits_e_profile_required(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(timeline=[_lag_start_event()])
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert any(issue.code == codes.E_PROFILE_REQUIRED for issue in collector.issues)


def test_network_lag_with_profile_passes_profile_rule(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(profiles=["network-fs-lag"], timeline=[_lag_start_event()])
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert not any(issue.code == codes.E_PROFILE_REQUIRED for issue in collector.issues)


def test_corruption_unknown_target_emits_e_target_unknown(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["malformed-media"],
        timeline=[_corruption_event(target="missing_asset")],
    )
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert any(issue.code == codes.E_TARGET_UNKNOWN for issue in collector.issues)
