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


def _profile_gated_event(action: str, **fields: object) -> dict[str, object]:
    return {
        "id": f"{action}_001",
        "at": "1s",
        "action": action,
        "target": "a",
        **fields,
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


def test_malformed_media_interceptor_without_profile_emits_e_profile_required(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        timeline=[
            _profile_gated_event("truncate_file", keep_bytes=64),
            _profile_gated_event(
                "corrupt_packet_range",
                stream="video",
                packet_start=0,
                packet_count=1,
            ),
            _profile_gated_event("write_invalid_duration_metadata", value="invalid"),
        ],
    )
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    issues = [issue for issue in collector.issues if issue.code == codes.E_PROFILE_REQUIRED]
    assert len(issues) == 3
    assert {issue.path for issue in issues} == {
        "$.timeline[0].action",
        "$.timeline[1].action",
        "$.timeline[2].action",
    }


def test_malformed_media_interceptor_with_profile_passes_profile_rule(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        profiles=["malformed-media"],
        timeline=[
            _profile_gated_event("truncate_file", keep_bytes=64),
            _profile_gated_event(
                "corrupt_packet_range",
                stream="video",
                packet_start=0,
                packet_count=1,
            ),
            _profile_gated_event("write_invalid_duration_metadata", value="invalid"),
        ],
    )
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert not any(issue.code == codes.E_PROFILE_REQUIRED for issue in collector.issues)


def test_corrupt_tags_without_profile_emits_e_profile_required(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(timeline=[_profile_gated_event("corrupt_tags", flavor="null_bytes")])
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert any(issue.code == codes.E_PROFILE_REQUIRED for issue in collector.issues)


def test_corrupt_tags_with_malformed_media_passes_profile_rule(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        profiles=["malformed-media"],
        timeline=[_profile_gated_event("corrupt_tags", flavor="malformed_frame")],
    )
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert not any(issue.code == codes.E_PROFILE_REQUIRED for issue in collector.issues)


def test_filesystem_artifact_interceptor_without_profile_emits_e_profile_required(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(timeline=[_profile_gated_event("touch_mtime", offset="2s")])
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert any(issue.code == codes.E_PROFILE_REQUIRED for issue in collector.issues)


def test_filesystem_artifact_interceptor_with_profile_passes_profile_rule(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        profiles=["filesystem-artifacts"],
        timeline=[_profile_gated_event("touch_mtime", offset="2s")],
    )
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert not any(issue.code == codes.E_PROFILE_REQUIRED for issue in collector.issues)


def test_negative_oracle_interceptor_without_profile_emits_e_profile_required(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(timeline=[_profile_gated_event("wrong_oracle_hash")])
    collector = IssueCollector()

    run_semantic_pass(raw, empty_index, collector)

    assert any(issue.code == codes.E_PROFILE_REQUIRED for issue in collector.issues)


def test_negative_oracle_interceptor_with_profile_passes_profile_rule(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        profiles=["negative-oracle"],
        timeline=[_profile_gated_event("wrong_oracle_hash")],
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
