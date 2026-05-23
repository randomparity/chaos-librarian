"""Per-rule tests for network filesystem lag validation."""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


def _rename_event(
    *,
    event_id: str = "rename_001",
    target: str = "a",
    at: str = "1s",
) -> dict[str, object]:
    return {
        "id": event_id,
        "at": at,
        "action": "rename_file",
        "target": target,
        "to": f"r/{target}-renamed.mkv",
    }


def _lag_start(
    *,
    event_id: str = "lag_start_001",
    target: str = "a",
    after: str = "rename_001",
    at: str = "1s",
    duration: str = "2s",
) -> dict[str, object]:
    return {
        "id": event_id,
        "at": at,
        "action": "network_lag_start",
        "effect": "delayed_rename",
        "target": target,
        "after": after,
        "duration": duration,
    }


def _lag_commit(
    *,
    event_id: str = "lag_commit_001",
    start_id: str = "lag_start_001",
    at: str = "3s",
) -> dict[str, object]:
    return {
        "id": event_id,
        "at": at,
        "action": "network_lag_commit",
        "for": start_id,
    }


def _two_asset_works() -> list[dict[str, object]]:
    return [
        {
            "id": "w",
            "title": "t",
            "variants": [
                {
                    "id": "v",
                    "label": "l",
                    "bundle": {
                        "id": "b",
                        "assets": [
                            {
                                "id": "a",
                                "role": "primary_video",
                                "container": "mkv",
                                "duration_seconds": 1,
                            },
                            {
                                "id": "b",
                                "role": "primary_video",
                                "container": "mkv",
                                "duration_seconds": 1,
                            },
                        ],
                    },
                }
            ],
        }
    ]


def _issues(raw: dict[str, object], empty_index) -> IssueCollector:
    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)
    return collector


def test_valid_network_lag_pair_has_no_lifecycle_issue(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        timeline=[
            _rename_event(),
            _lag_start(),
            _lag_commit(),
        ],
    )

    collector = _issues(raw, empty_index)

    assert not any(issue.code == codes.E_LIFECYCLE_INVALID for issue in collector.issues)


def test_network_lag_commit_without_start_emits(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        timeline=[_lag_commit(start_id="missing_start")],
    )

    collector = _issues(raw, empty_index)

    assert any(issue.code == codes.E_LIFECYCLE_INVALID for issue in collector.issues)


def test_network_lag_start_without_commit_emits(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        timeline=[
            _rename_event(),
            _lag_start(),
        ],
    )

    collector = _issues(raw, empty_index)

    assert any(issue.code == codes.E_LIFECYCLE_INVALID for issue in collector.issues)


def test_network_lag_commit_must_match_start_plus_duration(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        timeline=[
            _rename_event(),
            _lag_start(duration="2s"),
            _lag_commit(at="4s"),
        ],
    )

    collector = _issues(raw, empty_index)

    assert any(issue.code == codes.E_LIFECYCLE_INVALID for issue in collector.issues)


def test_network_lag_start_must_immediately_follow_after_event(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        works=_two_asset_works(),
        timeline=[
            _rename_event(),
            _rename_event(event_id="rename_b", target="b"),
            _lag_start(),
            _lag_commit(),
        ],
    )

    collector = _issues(raw, empty_index)

    assert any(issue.code == codes.E_LIFECYCLE_INVALID for issue in collector.issues)


def test_network_lag_start_rejects_future_after_event(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        timeline=[
            _lag_start(),
            _rename_event(),
            _lag_commit(),
        ],
    )

    collector = _issues(raw, empty_index)

    assert any(issue.code == codes.E_LIFECYCLE_INVALID for issue in collector.issues)


def test_network_lag_start_target_must_match_after_event(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        works=_two_asset_works(),
        timeline=[
            _rename_event(target="a"),
            _lag_start(target="b"),
            _lag_commit(),
        ],
    )

    collector = _issues(raw, empty_index)

    assert any(issue.code == codes.E_LIFECYCLE_INVALID for issue in collector.issues)


def test_network_lag_duration_must_be_positive(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        timeline=[
            _rename_event(),
            _lag_start(duration="0ns"),
            _lag_commit(at="1s"),
        ],
    )

    collector = _issues(raw, empty_index)

    assert any(issue.code == codes.E_LIFECYCLE_INVALID for issue in collector.issues)


def test_network_lag_rejects_same_target_mutation_before_commit(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        timeline=[
            _rename_event(),
            _lag_start(duration="10s"),
            {
                "id": "metadata_001",
                "at": "5s",
                "action": "edit_metadata",
                "target": "a",
                "fields": {"title": "still pending"},
            },
            _lag_commit(at="11s"),
        ],
    )

    collector = _issues(raw, empty_index)

    assert any(issue.code == codes.E_LIFECYCLE_INVALID for issue in collector.issues)
