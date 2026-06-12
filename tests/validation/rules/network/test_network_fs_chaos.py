"""Tests for network-fs-chaos profile gate, target, and pairing rules."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.profile_policy import REQUIRED_PROFILES_BY_ACTION
from chaos_librarian.contract.profiles import ProfileName
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.validation import codes
from chaos_librarian.validation.reporting import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass

_CHAOS_PROFILE = ProfileName.NETWORK_FS_CHAOS.value

_NEW_ACTIONS = [
    TimelineActionName.CHANGE_PERMISSIONS.value,
    TimelineActionName.SIMULATE_QUOTA_EXCEEDED.value,
    TimelineActionName.TOGGLE_READONLY.value,
    TimelineActionName.SIMULATE_STALE_HANDLE.value,
    TimelineActionName.UNMOUNT_PATH.value,
    TimelineActionName.REMOUNT_PATH.value,
    TimelineActionName.ACQUIRE_LOCK.value,
    TimelineActionName.RELEASE_LOCK.value,
]


def _chaos_event(
    action: str, idx: int = 0, fields: dict[str, object] | None = None
) -> dict[str, object]:
    event: dict[str, object] = {"id": f"{action}_{idx}", "at": "1s", "action": action}
    if fields:
        event.update(fields)
    return event


def _rename_event(*, at: str = "1s") -> dict[str, object]:
    return {
        "id": "rename_0",
        "at": at,
        "action": "rename_file",
        "target": "a",
        "to": "r/a-renamed.mkv",
    }


def _lag_start(*, at: str = "1s", duration: str = "2s") -> dict[str, object]:
    return {
        "id": "lag_start_0",
        "at": at,
        "action": "network_lag_start",
        "effect": "delayed_rename",
        "target": "a",
        "after": "rename_0",
        "duration": duration,
    }


def _lag_commit(*, at: str = "3s") -> dict[str, object]:
    return {
        "id": "lag_commit_0",
        "at": at,
        "action": "network_lag_commit",
        "for": "lag_start_0",
    }


def _codes(collector: IssueCollector) -> set[str]:
    return {issue.code for issue in collector.issues}


def _messages(collector: IssueCollector) -> list[str]:
    return [issue.message for issue in collector.issues]


# --- single source of truth -------------------------------------------------


@pytest.mark.parametrize("action", _NEW_ACTIONS)
def test_every_new_action_is_gated_by_network_fs_chaos(action: str) -> None:
    assert REQUIRED_PROFILES_BY_ACTION[TimelineActionName(action)] is (ProfileName.NETWORK_FS_CHAOS)


# --- profile gate -----------------------------------------------------------


def test_change_permissions_without_profile_emits_e_profile_required(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        timeline=[_chaos_event("change_permissions", fields={"target": "a", "mode": "000"})]
    )
    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)
    assert codes.E_PROFILE_REQUIRED in _codes(collector)


def test_change_permissions_with_profile_passes_profile_rule(minimal_scenario, empty_index) -> None:
    raw = minimal_scenario(
        profiles=[_CHAOS_PROFILE],
        timeline=[_chaos_event("change_permissions", fields={"target": "a", "mode": "000"})],
    )
    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)
    assert codes.E_PROFILE_REQUIRED not in _codes(collector)


def test_acquire_lock_without_profile_emits_e_profile_required(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        timeline=[
            _chaos_event("acquire_lock", fields={"target": "a", "lock_type": "exclusive"}),
            _chaos_event("release_lock", idx=1, fields={"for": "acquire_lock_0"}),
        ]
    )
    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)
    assert codes.E_PROFILE_REQUIRED in _codes(collector)


# --- asset-only target validation -------------------------------------------


@pytest.mark.parametrize(
    ("action", "fields"),
    [
        ("simulate_quota_exceeded", {}),
        ("simulate_stale_handle", {}),
        ("acquire_lock", {"lock_type": "shared"}),
    ],
)
def test_asset_only_action_unknown_target_emits_e_target_unknown(
    action: str, fields: dict[str, object], minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        profiles=[_CHAOS_PROFILE],
        timeline=[_chaos_event(action, fields={"target": "missing_asset", **fields})],
    )
    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)
    assert codes.E_TARGET_UNKNOWN in _codes(collector)


@pytest.mark.parametrize(
    ("action", "fields"),
    [
        ("simulate_quota_exceeded", {}),
        ("simulate_stale_handle", {}),
        ("acquire_lock", {"lock_type": "shared"}),
    ],
)
def test_asset_only_action_known_target_clean(
    action: str, fields: dict[str, object], minimal_scenario, empty_index
) -> None:
    timeline = [_chaos_event(action, fields={"target": "a", **fields})]
    if action == "acquire_lock":
        timeline.append(_chaos_event("release_lock", idx=1, fields={"for": "acquire_lock_0"}))
    raw = minimal_scenario(profiles=[_CHAOS_PROFILE], timeline=timeline)
    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)
    assert codes.E_TARGET_UNKNOWN not in _codes(collector)


# --- path-or-asset target validation ----------------------------------------


@pytest.mark.parametrize("action", ["change_permissions", "toggle_readonly", "unmount_path"])
def test_path_or_asset_action_asset_target_clean(
    action: str, minimal_scenario, empty_index
) -> None:
    timeline = [_chaos_event(action, fields={"target": "a", **_path_action_fields(action)})]
    if action == "unmount_path":
        timeline.append(_chaos_event("remount_path", idx=1, fields={"for": "unmount_path_0"}))
    raw = minimal_scenario(profiles=[_CHAOS_PROFILE], timeline=timeline)
    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)
    assert codes.E_PATH_CONTAINMENT not in _codes(collector)
    assert codes.E_TARGET_UNKNOWN not in _codes(collector)


@pytest.mark.parametrize("action", ["change_permissions", "toggle_readonly", "unmount_path"])
def test_path_or_asset_action_library_path_clean(
    action: str, minimal_scenario, empty_index
) -> None:
    timeline = [
        _chaos_event(action, fields={"target": "r/sub/clip.mkv", **_path_action_fields(action)})
    ]
    if action == "unmount_path":
        timeline.append(_chaos_event("remount_path", idx=1, fields={"for": "unmount_path_0"}))
    raw = minimal_scenario(profiles=[_CHAOS_PROFILE], timeline=timeline)
    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)
    assert codes.E_PATH_CONTAINMENT not in _codes(collector)


@pytest.mark.parametrize("action", ["change_permissions", "toggle_readonly", "unmount_path"])
def test_path_or_asset_action_escaping_path_emits_e_path_containment(
    action: str, minimal_scenario, empty_index
) -> None:
    timeline = [
        _chaos_event(action, fields={"target": "../../etc/passwd", **_path_action_fields(action)})
    ]
    if action == "unmount_path":
        timeline.append(_chaos_event("remount_path", idx=1, fields={"for": "unmount_path_0"}))
    raw = minimal_scenario(profiles=[_CHAOS_PROFILE], timeline=timeline)
    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)
    assert codes.E_PATH_CONTAINMENT in _codes(collector)


# --- cross-family window overlap ---------------------------------------------


def test_path_unmount_during_network_lag_emits_e_lifecycle_invalid(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        profiles=[_CHAOS_PROFILE, ProfileName.NETWORK_FS_LAG.value],
        timeline=[
            _rename_event(at="1s"),
            _lag_start(at="1s", duration="3s"),
            _chaos_event("unmount_path", idx=0, fields={"at": "2s", "target": "r"}),
            _chaos_event("remount_path", idx=1, fields={"at": "3s", "for": "unmount_path_0"}),
            _lag_commit(at="4s"),
        ],
    )

    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)

    assert codes.E_LIFECYCLE_INVALID in _codes(collector)
    assert any("overlaps network_lag_start" in message for message in _messages(collector))


def test_network_lag_during_path_unmount_emits_e_lifecycle_invalid(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        profiles=[_CHAOS_PROFILE, ProfileName.NETWORK_FS_LAG.value],
        timeline=[
            _chaos_event("unmount_path", idx=0, fields={"at": "1s", "target": "r"}),
            _rename_event(at="2s"),
            _lag_start(at="2s", duration="1s"),
            _lag_commit(at="3s"),
            _chaos_event("remount_path", idx=1, fields={"at": "4s", "for": "unmount_path_0"}),
        ],
    )

    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)

    assert codes.E_LIFECYCLE_INVALID in _codes(collector)
    assert any("overlaps unmount_path" in message for message in _messages(collector))


def test_network_lag_allows_unmount_path_for_disjoint_subtree(
    minimal_scenario, empty_index
) -> None:
    raw = minimal_scenario(
        profiles=[_CHAOS_PROFILE, ProfileName.NETWORK_FS_LAG.value],
        timeline=[
            _rename_event(at="1s"),
            _lag_start(at="1s", duration="3s"),
            _chaos_event("unmount_path", idx=0, fields={"at": "2s", "target": "r/other"}),
            _chaos_event("remount_path", idx=1, fields={"at": "3s", "for": "unmount_path_0"}),
            _lag_commit(at="4s"),
        ],
    )

    collector = IssueCollector()
    run_semantic_pass(raw, empty_index, collector)

    assert not any("overlaps network_lag_start" in message for message in _messages(collector))


def _path_action_fields(action: str) -> dict[str, object]:
    if action == "change_permissions":
        return {"mode": "000"}
    if action == "toggle_readonly":
        return {"mode": "readonly"}
    return {}
