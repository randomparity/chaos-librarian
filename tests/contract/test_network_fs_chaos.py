"""Contract tests for the network-fs-chaos event variants and report record."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from chaos_librarian.contract.materialization import (
    NetworkFsChaosAction,
    NetworkFsChaosCondition,
)
from chaos_librarian.contract.scenario import (
    AcquireLockEvent,
    ChangePermissionsEvent,
    LockType,
    ReadonlyState,
    ReleaseLockEvent,
    RemountPathEvent,
    SimulateQuotaExceededEvent,
    SimulateStaleHandleEvent,
    TimelineActionName,
    ToggleReadonlyEvent,
    UnmountPathEvent,
)


def test_change_permissions_round_trip() -> None:
    event = ChangePermissionsEvent.model_validate(
        {"id": "e1", "at": "1s", "action": "change_permissions", "target": "asset-1", "mode": "000"}
    )
    assert event.action is TimelineActionName.CHANGE_PERMISSIONS
    assert event.target == "asset-1"
    assert event.mode == "000"


@pytest.mark.parametrize("mode", ["000", "644", "4644", "755"])
def test_change_permissions_accepts_octal_modes(mode: str) -> None:
    event = ChangePermissionsEvent.model_validate(
        {"id": "e1", "at": "1s", "action": "change_permissions", "target": "a", "mode": mode}
    )
    assert event.mode == mode


@pytest.mark.parametrize("mode", ["abc", "99", "12345", "", "64", "8"])
def test_change_permissions_rejects_non_octal_mode(mode: str) -> None:
    with pytest.raises(ValidationError):
        ChangePermissionsEvent.model_validate(
            {"id": "e1", "at": "1s", "action": "change_permissions", "target": "a", "mode": mode}
        )


def test_simulate_quota_exceeded_round_trip() -> None:
    event = SimulateQuotaExceededEvent.model_validate(
        {"id": "e1", "at": "1s", "action": "simulate_quota_exceeded", "target": "asset-1"}
    )
    assert event.action is TimelineActionName.SIMULATE_QUOTA_EXCEEDED
    assert event.target == "asset-1"


@pytest.mark.parametrize("mode", ["readonly", "readwrite"])
def test_toggle_readonly_round_trip(mode: str) -> None:
    event = ToggleReadonlyEvent.model_validate(
        {"id": "e1", "at": "1s", "action": "toggle_readonly", "target": "lib/sub", "mode": mode}
    )
    assert event.mode is ReadonlyState(mode)


def test_toggle_readonly_rejects_bad_mode() -> None:
    with pytest.raises(ValidationError):
        ToggleReadonlyEvent.model_validate(
            {"id": "e1", "at": "1s", "action": "toggle_readonly", "target": "a", "mode": "rw"}
        )


def test_simulate_stale_handle_round_trip() -> None:
    event = SimulateStaleHandleEvent.model_validate(
        {"id": "e1", "at": "1s", "action": "simulate_stale_handle", "target": "asset-1"}
    )
    assert event.action is TimelineActionName.SIMULATE_STALE_HANDLE


def test_unmount_path_round_trip() -> None:
    event = UnmountPathEvent.model_validate(
        {"id": "e1", "at": "1s", "action": "unmount_path", "target": "lib/sub"}
    )
    assert event.action is TimelineActionName.UNMOUNT_PATH
    assert event.target == "lib/sub"


@pytest.mark.parametrize("for_key", ["for", "for_"])
def test_remount_path_accepts_for_alias(for_key: str) -> None:
    event = RemountPathEvent.model_validate(
        {"id": "e2", "at": "5s", "action": "remount_path", for_key: "e1"}
    )
    assert event.for_ == "e1"


def test_remount_path_serializes_for() -> None:
    event = RemountPathEvent.model_validate(
        {"id": "e2", "at": "5s", "action": "remount_path", "for": "e1"}
    )
    assert event.model_dump(by_alias=True)["for"] == "e1"


@pytest.mark.parametrize("lock_type", ["shared", "exclusive"])
def test_acquire_lock_round_trip(lock_type: str) -> None:
    event = AcquireLockEvent.model_validate(
        {
            "id": "e1",
            "at": "1s",
            "action": "acquire_lock",
            "target": "asset-1",
            "lock_type": lock_type,
        }
    )
    assert event.lock_type is LockType(lock_type)


def test_acquire_lock_rejects_bad_lock_type() -> None:
    with pytest.raises(ValidationError):
        AcquireLockEvent.model_validate(
            {"id": "e1", "at": "1s", "action": "acquire_lock", "target": "a", "lock_type": "rw"}
        )


@pytest.mark.parametrize("for_key", ["for", "for_"])
def test_release_lock_accepts_for_alias(for_key: str) -> None:
    event = ReleaseLockEvent.model_validate(
        {"id": "e2", "at": "5s", "action": "release_lock", for_key: "e1"}
    )
    assert event.for_ == "e1"


def test_network_fs_chaos_action_round_trip() -> None:
    record = NetworkFsChaosAction.model_validate(
        {
            "event_id": "e1",
            "action": "change_permissions",
            "target_ref": "asset-1",
            "condition": "eacces",
            "enforced": True,
            "mode": "000",
        }
    )
    assert record.condition is NetworkFsChaosCondition.EACCES
    assert record.enforced is True
    assert record.mode == "000"


def test_network_fs_chaos_action_rejects_extra_field() -> None:
    with pytest.raises(ValidationError):
        NetworkFsChaosAction.model_validate(
            {
                "event_id": "e1",
                "action": "acquire_lock",
                "target_ref": "asset-1",
                "condition": "eagain",
                "enforced": False,
                "bogus": 1,
            }
        )
