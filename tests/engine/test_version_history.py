"""Tests for ``derive_version_history`` — pure journal projection."""

from __future__ import annotations

from typing import Any, Final

import pytest
from pydantic import TypeAdapter

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.engine.version_history import derive_version_history

_JOURNAL_ENTRY_ADAPTER: Final[TypeAdapter[JournalEntry]] = TypeAdapter(JournalEntry)


def _validated_entry(payload: dict[str, Any]) -> JournalEntry:
    return _JOURNAL_ENTRY_ADAPTER.validate_python(payload)


def _atomic(
    *,
    event_id: str,
    action: TimelineActionName,
    logical_time_ns: int,
    target: str,
    input_version_ids: list[str] | None = None,
    output_version_ids: list[str] | None = None,
    **state_delta: object,
) -> dict[str, Any]:
    """Build a dict shaped like an AtomicJournalEntry for projection tests."""
    return {
        "schema_version": 1,
        "event_id": event_id,
        "scenario_id": "sc_test",
        "run_id": "1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01",
        "logical_time_ns": logical_time_ns,
        "action": action.value,
        "target_ids": [target],
        "input_version_ids": input_version_ids or [],
        "output_version_ids": output_version_ids or [],
        "location_ids": [],
        "state_delta": state_delta,
        "phase": "atomic",
    }


def test_version_history_empty_for_asset_with_no_version_events() -> None:
    """WHY: assets that never get version-affecting events report empty version_history."""
    journal: list[JournalEntry] = []
    assert derive_version_history("asset_hd_main", journal) == []


def test_version_history_filters_filesystem_actions() -> None:
    """WHY: move/rename/delete don't allocate versions; they must not pollute the projection."""
    journal = [
        _validated_entry(
            _atomic(
                event_id="ev_move",
                action=TimelineActionName.MOVE_ASSET,
                logical_time_ns=1,
                target="asset_hd_main",
                from_path="a",
                to_path="b",
            )
        ),
    ]
    assert derive_version_history("asset_hd_main", journal) == []


def test_version_history_excludes_extract_subtitle() -> None:
    """WHY: extract_subtitle allocates a sidecar, not a version (spec design #9)."""
    journal = [
        _validated_entry(
            _atomic(
                event_id="ev_extract",
                action=TimelineActionName.EXTRACT_SUBTITLE,
                logical_time_ns=1,
                target="asset_hd_main",
                sidecar_id="sidecar_0001",
                language="eng",
            )
        ),
    ]
    assert derive_version_history("asset_hd_main", journal) == []


def test_version_history_filters_other_assets() -> None:
    """WHY: per-asset projection must not leak version events from sibling assets."""
    journal = [
        _validated_entry(
            _atomic(
                event_id="ev_other",
                action=TimelineActionName.REENCODE_VIDEO,
                logical_time_ns=1,
                target="asset_other",
                input_version_ids=["v_in"],
                output_version_ids=["v_out"],
                resolution="sd",
                codec="h264",
            )
        ),
    ]
    assert derive_version_history("asset_hd_main", journal) == []


def test_version_history_includes_reencode_video_with_summary() -> None:
    """WHY: state_delta_summary must preserve the contract-locked keys per action."""
    journal = [
        _validated_entry(
            _atomic(
                event_id="ev_reencode",
                action=TimelineActionName.REENCODE_VIDEO,
                logical_time_ns=1_000_000_000,
                target="asset_hd_main",
                input_version_ids=["version_0001"],
                output_version_ids=["version_0002"],
                resolution="sd",
                codec="h264",
                # extra non-preserved key (e.g., input_path) must not leak
                input_path="movies-hd/a.mkv",
                output_path="movies-hd/a.mkv",
            )
        ),
    ]
    history = derive_version_history("asset_hd_main", journal)
    assert len(history) == 1
    entry = history[0]
    assert entry.event_id == "ev_reencode"
    assert entry.action == TimelineActionName.REENCODE_VIDEO
    assert entry.logical_time_ns == 1_000_000_000
    assert entry.input_version_id == "version_0001"
    assert entry.output_version_id == "version_0002"
    assert entry.state_delta_summary == {"resolution": "sd", "codec": "h264"}


def test_derive_version_history_includes_corruption_summary() -> None:
    journal = [
        _validated_entry(
            _atomic(
                event_id="corrupt_header_001",
                action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
                logical_time_ns=1_000_000_000,
                target="asset_hd_main",
                input_version_ids=["version_0001"],
                output_version_ids=["version_0002"],
                profile="malformed-media",
                corruptor="container_header_v1",
                byte_start=0,
                byte_count=64,
                seed_material="container_header_v1:42:corrupt_header_001:asset_hd_main",
                input_path="movies-hd/a.mkv",
                output_path="movies-hd/a.mkv",
            )
        ),
    ]

    history = derive_version_history("asset_hd_main", journal)

    assert len(history) == 1
    entry = history[0]
    assert entry.event_id == "corrupt_header_001"
    assert entry.action == TimelineActionName.CORRUPT_CONTAINER_HEADER
    assert entry.input_version_id == "version_0001"
    assert entry.output_version_id == "version_0002"
    assert entry.state_delta_summary == {
        "profile": "malformed-media",
        "corruptor": "container_header_v1",
        "byte_start": 0,
        "byte_count": 64,
        "seed_material": "container_header_v1:42:corrupt_header_001:asset_hd_main",
    }
    assert list(entry.state_delta_summary) == [
        "profile",
        "corruptor",
        "byte_start",
        "byte_count",
        "seed_material",
    ]


@pytest.mark.parametrize(
    ("action", "state_delta", "expected_summary"),
    [
        (
            TimelineActionName.TRUNCATE_FILE,
            {
                "profile": "malformed-media",
                "corruptor": "truncate_file_v1",
                "keep_bytes": 64,
                "seed_material": "truncate_file_v1:42:truncate_001:asset_hd_main",
                "input_path": "movies-hd/a.mkv",
                "output_path": "movies-hd/a.mkv",
            },
            {
                "profile": "malformed-media",
                "corruptor": "truncate_file_v1",
                "keep_bytes": 64,
                "seed_material": "truncate_file_v1:42:truncate_001:asset_hd_main",
            },
        ),
        (
            TimelineActionName.CORRUPT_PACKET_RANGE,
            {
                "profile": "malformed-media",
                "corruptor": "packet_range_v1",
                "stream": "video",
                "packet_start": 0,
                "packet_count": 2,
                "seed_material": "packet_range_v1:42:packet_corrupt_001:asset_hd_main",
                "input_path": "movies-hd/a.mkv",
                "output_path": "movies-hd/a.mkv",
            },
            {
                "profile": "malformed-media",
                "corruptor": "packet_range_v1",
                "stream": "video",
                "packet_start": 0,
                "packet_count": 2,
                "seed_material": "packet_range_v1:42:packet_corrupt_001:asset_hd_main",
            },
        ),
        (
            TimelineActionName.WRITE_INVALID_DURATION_METADATA,
            {
                "profile": "malformed-media",
                "corruptor": "invalid_duration_metadata_v1",
                "value": "not-a-duration",
                "seed_material": "invalid_duration_metadata_v1:42:duration_bad_001:asset_hd_main",
                "input_path": "movies-hd/a.mkv",
                "output_path": "movies-hd/a.mkv",
            },
            {
                "profile": "malformed-media",
                "corruptor": "invalid_duration_metadata_v1",
                "value": "not-a-duration",
                "seed_material": "invalid_duration_metadata_v1:42:duration_bad_001:asset_hd_main",
            },
        ),
        (
            TimelineActionName.WRONG_ORACLE_HASH,
            {
                "profile": "negative-oracle",
                "algorithm": "sha256",
                "seed_material": "wrong_oracle_hash_v1:42:wrong_hash_001:asset_hd_main",
                "input_path": "movies-hd/a.mkv",
                "output_path": "movies-hd/a.mkv",
            },
            {
                "profile": "negative-oracle",
                "algorithm": "sha256",
                "seed_material": "wrong_oracle_hash_v1:42:wrong_hash_001:asset_hd_main",
            },
        ),
    ],
)
def test_derive_version_history_includes_interceptor_summaries(
    action: TimelineActionName,
    state_delta: dict[str, object],
    expected_summary: dict[str, object],
) -> None:
    journal = [
        _validated_entry(
            _atomic(
                event_id="ev_interceptor",
                action=action,
                logical_time_ns=1_000_000_000,
                target="asset_hd_main",
                input_version_ids=["version_0001"],
                output_version_ids=["version_0002"],
                **state_delta,
            )
        ),
    ]

    history = derive_version_history("asset_hd_main", journal)

    assert len(history) == 1
    assert history[0].action == action
    assert history[0].state_delta_summary == expected_summary


def test_derive_version_history_excludes_touch_mtime() -> None:
    journal = [
        _validated_entry(
            _atomic(
                event_id="touch_mtime_001",
                action=TimelineActionName.TOUCH_MTIME,
                logical_time_ns=1_000_000_000,
                target="asset_hd_main",
                path="movies-hd/a.mkv",
                profile="filesystem-artifacts",
                offset="2s",
            )
        ),
    ]

    assert derive_version_history("asset_hd_main", journal) == []


def test_version_history_orders_by_journal_order_across_all_5_actions() -> None:
    """WHY: all five version-affecting actions surface in order with their summaries."""
    journal = [
        _validated_entry(
            _atomic(
                event_id="ev_reencode_video",
                action=TimelineActionName.REENCODE_VIDEO,
                logical_time_ns=1,
                target="asset_hd_main",
                input_version_ids=["v0"],
                output_version_ids=["v1"],
                resolution="sd",
                codec="h264",
            )
        ),
        _validated_entry(
            _atomic(
                event_id="ev_reencode_audio",
                action=TimelineActionName.REENCODE_AUDIO,
                logical_time_ns=2,
                target="asset_hd_main",
                input_version_ids=["v1"],
                output_version_ids=["v2"],
                from_channels="stereo",
                to_channels="5.1",
            )
        ),
        _validated_entry(
            _atomic(
                event_id="ev_remux",
                action=TimelineActionName.REMUX_CONTAINER,
                logical_time_ns=3,
                target="asset_hd_main",
                input_version_ids=["v2"],
                output_version_ids=["v3"],
                from_container="mkv",
                to_container="mp4",
            )
        ),
        _validated_entry(
            _atomic(
                event_id="ev_edit",
                action=TimelineActionName.EDIT_METADATA,
                logical_time_ns=4,
                target="asset_hd_main",
                input_version_ids=["v3"],
                output_version_ids=["v4"],
                fields={"title": "New Title"},
            )
        ),
        _validated_entry(
            _atomic(
                event_id="ev_embed",
                action=TimelineActionName.EMBED_SUBTITLE,
                logical_time_ns=5,
                target="asset_hd_main",
                input_version_ids=["v4"],
                output_version_ids=["v5"],
                language="eng",
                kind="subtitles",
            )
        ),
    ]
    history = derive_version_history("asset_hd_main", journal)
    assert [e.event_id for e in history] == [
        "ev_reencode_video",
        "ev_reencode_audio",
        "ev_remux",
        "ev_edit",
        "ev_embed",
    ]
    assert [e.action for e in history] == [
        TimelineActionName.REENCODE_VIDEO,
        TimelineActionName.REENCODE_AUDIO,
        TimelineActionName.REMUX_CONTAINER,
        TimelineActionName.EDIT_METADATA,
        TimelineActionName.EMBED_SUBTITLE,
    ]
    assert history[0].state_delta_summary == {"resolution": "sd", "codec": "h264"}
    assert history[1].state_delta_summary == {
        "from_channels": "stereo",
        "to_channels": "5.1",
    }
    assert history[2].state_delta_summary == {
        "from_container": "mkv",
        "to_container": "mp4",
    }
    assert history[3].state_delta_summary == {"fields": {"title": "New Title"}}
    assert history[4].state_delta_summary == {"language": "eng", "kind": "subtitles"}
    # version chain threads correctly
    assert [e.input_version_id for e in history] == ["v0", "v1", "v2", "v3", "v4"]
    assert [e.output_version_id for e in history] == ["v1", "v2", "v3", "v4", "v5"]
