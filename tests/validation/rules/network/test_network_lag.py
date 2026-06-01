"""Per-rule tests for network filesystem lag validation."""

from __future__ import annotations

from chaos_librarian.validation import codes
from chaos_librarian.validation.reporting import IssueCollector
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


def _delete_event(*, event_id: str = "delete_001", at: str = "1s") -> dict[str, object]:
    return {
        "id": event_id,
        "at": at,
        "action": "delete_file",
        "target": "a",
    }


def _add_event(
    *,
    event_id: str = "add_001",
    at: str = "2s",
    to: str = "r/a-restored.mkv",
) -> dict[str, object]:
    return {
        "id": event_id,
        "at": at,
        "action": "add_file",
        "target": "a",
        "to": to,
    }


def _slow_copy_start_event(
    *,
    event_id: str = "copy_start_001",
    at: str = "2s",
) -> dict[str, object]:
    return {
        "id": event_id,
        "at": at,
        "action": "slow_copy_start",
        "target": "a",
        "to": "r/a-copy.mkv",
        "temp_path": "r/a-copy.mkv.part",
        "duration": "3s",
    }


def _slow_copy_commit_event(
    *,
    event_id: str = "copy_commit_001",
    start_id: str = "copy_start_001",
    at: str = "5s",
) -> dict[str, object]:
    return {
        "id": event_id,
        "at": at,
        "action": "slow_copy_commit",
        "for": start_id,
    }


def _lag_start(
    *,
    event_id: str = "lag_start_001",
    effect: str = "delayed_rename",
    target: str = "a",
    after: str = "rename_001",
    at: str = "1s",
    duration: str = "2s",
) -> dict[str, object]:
    return {
        "id": event_id,
        "at": at,
        "action": "network_lag_start",
        "effect": effect,
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


def _two_asset_movies() -> list[dict[str, object]]:
    return [
        {
            "id": "m",
            "title": "t",
            "layout": "movie_flat",
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


def test_network_lag_start_at_must_match_after_event(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        timeline=[
            _rename_event(at="1s"),
            _lag_start(at="2s", duration="2s"),
            _lag_commit(at="4s"),
        ],
    )

    collector = _issues(raw, empty_index)

    assert any(
        issue.code == codes.E_LIFECYCLE_INVALID
        and "same at" in issue.message
        and "rename_001" in issue.message
        for issue in collector.issues
    )


def test_network_lag_start_must_immediately_follow_after_event(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        movies=_two_asset_movies(),
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
        movies=_two_asset_movies(),
        timeline=[
            _rename_event(target="a"),
            _lag_start(target="b"),
            _lag_commit(),
        ],
    )

    collector = _issues(raw, empty_index)

    assert any(issue.code == codes.E_LIFECYCLE_INVALID for issue in collector.issues)


def test_network_lag_start_target_must_match_slow_copy_commit_target(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        movies=_two_asset_movies(),
        timeline=[
            _slow_copy_start_event(at="1s"),
            _slow_copy_commit_event(at="4s"),
            _lag_start(
                effect="delayed_visibility",
                target="b",
                after="copy_commit_001",
                at="4s",
            ),
            _lag_commit(at="6s"),
        ],
    )

    collector = _issues(raw, empty_index)

    assert any(
        issue.code == codes.E_LIFECYCLE_INVALID
        and "target 'b' does not match" in issue.message
        and "target 'a'" in issue.message
        for issue in collector.issues
    )


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


def test_delayed_visibility_allows_add_file_restore(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        timeline=[
            _delete_event(at="1s"),
            _add_event(at="2s"),
            _lag_start(effect="delayed_visibility", after="add_001", at="2s"),
            _lag_commit(at="4s"),
        ],
    )

    collector = _issues(raw, empty_index)

    assert not any(issue.code == codes.E_LIFECYCLE_INVALID for issue in collector.issues)


def test_delayed_visibility_rejects_rename_file(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        timeline=[
            _rename_event(),
            _lag_start(effect="delayed_visibility"),
            _lag_commit(),
        ],
    )

    collector = _issues(raw, empty_index)

    assert any(
        issue.code == codes.E_LIFECYCLE_INVALID
        and "delayed_visibility" in issue.message
        and "rename_file" in issue.message
        for issue in collector.issues
    )


def test_delayed_rename_rejects_add_file_restore(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        timeline=[
            _delete_event(at="1s"),
            _add_event(at="2s"),
            _lag_start(effect="delayed_rename", after="add_001", at="2s"),
            _lag_commit(at="4s"),
        ],
    )

    collector = _issues(raw, empty_index)

    assert any(
        issue.code == codes.E_LIFECYCLE_INVALID
        and "delayed_rename" in issue.message
        and "add_file" in issue.message
        for issue in collector.issues
    )


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


def test_network_lag_rejects_same_target_slow_copy_commit_before_commit(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        profiles=["network-fs-lag"],
        timeline=[
            _slow_copy_start_event(at="1s"),
            _rename_event(at="2s"),
            _lag_start(duration="10s", at="2s"),
            _slow_copy_commit_event(at="4s"),
            _lag_commit(at="12s"),
        ],
    )

    collector = _issues(raw, empty_index)

    issue = next(
        issue
        for issue in collector.issues
        if issue.code == codes.E_LIFECYCLE_INVALID
        and "copy_commit_001" in issue.message
        and "pending network lag window" in issue.message
    )
    assert issue.path == "$.timeline[3].for"
