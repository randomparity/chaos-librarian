"""Shared phase-B dispatch helpers."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from chaos_librarian.contract.journal import AtomicJournalEntry
from chaos_librarian.contract.manifest import Manifest, ManifestSidecar, ManifestVersion
from chaos_librarian.contract.materialization import (
    CorruptionAction,
    FailureStage,
    FilesystemAction,
    MediaAction,
    Outcome,
)
from chaos_librarian.contract.profiles import CorruptionProbeOutcome
from chaos_librarian.contract.scenario import SidecarKind, TimelineActionName
from chaos_librarian.materializer import phase_b
from chaos_librarian.materializer.errors import (
    CorruptionActionError,
    FilesystemActionError,
    MediaActionError,
)
from chaos_librarian.materializer.phase_b.corruption import CorruptionPhaseBContext
from chaos_librarian.materializer.phase_b.filesystem import FilesystemPhaseBContext
from chaos_librarian.materializer.phase_b.media import MediaPhaseBContext

RUN_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64
HASH_C = "sha256:" + "c" * 64
HASH_D = "sha256:" + "d" * 64


def test_dispatch_phase_b_entry_routes_filesystem_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path)
    entry = _entry(TimelineActionName.MOVE_ASSET)
    expected = FilesystemAction(
        event_id=entry.event_id,
        action=TimelineActionName.MOVE_ASSET,
        target_asset_id="asset_main",
        from_path="old.mkv",
        to_path="new.mkv",
        duration_ns=7,
    )

    monkeypatch.setattr(phase_b, "apply_filesystem_action", lambda _ctx, _entry: expected)

    phase_b.dispatch_phase_b_entry(state, entry)

    assert state.filesystem_actions == [expected]
    assert state.media_actions == []
    assert state.corruption_actions == []


def test_dispatch_phase_b_entry_routes_media_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path)
    entry = _entry(TimelineActionName.REENCODE_VIDEO)
    expected = MediaAction(
        event_id=entry.event_id,
        action=TimelineActionName.REENCODE_VIDEO,
        target_asset_id="asset_main",
        input_path="asset.mkv",
        output_path="asset.mkv",
        output_version_id="version_0002",
        output_content_hash=HASH_A,
        duration_ns=7,
    )

    monkeypatch.setattr(phase_b, "apply_media_action", lambda _ctx, _entry: expected)

    phase_b.dispatch_phase_b_entry(state, entry)

    assert state.filesystem_actions == []
    assert state.media_actions == [expected]
    assert state.corruption_actions == []


def test_dispatch_phase_b_entry_routes_corruption_actions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path)
    entry = _entry(TimelineActionName.CORRUPT_CONTAINER_HEADER)
    expected = CorruptionAction(
        event_id=entry.event_id,
        action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
        target_asset_id="asset_main",
        input_path="asset.mkv",
        output_path="asset.mkv",
        output_version_id="version_0002",
        input_content_hash=HASH_A,
        output_content_hash=HASH_B,
        corruptor="container_header_v1",
        input_size_bytes=128,
        output_size_bytes=128,
        byte_start=0,
        byte_count=64,
        seed_material="container_header_v1:7:corrupt_header_001:asset_main",
        probe_outcome=CorruptionProbeOutcome.FAILED_EXPECTED,
        duration_ns=7,
    )

    monkeypatch.setattr(phase_b, "apply_corruption_action", lambda _ctx, _entry: expected)

    phase_b.dispatch_phase_b_entry(state, entry)

    assert state.filesystem_actions == []
    assert state.media_actions == []
    assert state.corruption_actions == [expected]


def test_dispatch_phase_b_entry_rejects_actions_outside_current_dispatch_sets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _state(tmp_path)
    entry = _entry(TimelineActionName.MOVE_ASSET)
    monkeypatch.setattr(phase_b, "supports_filesystem_action", lambda _action: False)
    monkeypatch.setattr(phase_b, "supports_media_action", lambda _action: False)
    monkeypatch.setattr(phase_b, "supports_corruption_action", lambda _action: False)

    with pytest.raises(MediaActionError, match="unsupported phase-B action"):
        phase_b.dispatch_phase_b_entry(state, entry)


def test_augment_phase_b_outputs_stamps_all_phase_b_evidence(tmp_path: Path) -> None:
    state = _state(tmp_path)
    state.fs_ctx.phase_b_sidecar_hashes["sidecar_timeline"] = HASH_A
    state.media_ctx.post_phase_b_versions["version_media"] = (HASH_B, None)
    state.corruption_ctx.post_phase_b_versions["version_corrupt"] = (HASH_C, None)
    state.media_ctx.post_phase_b_sidecars["sidecar_updated"] = (HASH_D, "new.srt")
    manifest = Manifest(
        schema_version=6,
        works=[],
        variants=[],
        bundles=[],
        assets=[],
        versions=[
            ManifestVersion(id="version_media", asset_id="asset_main", index=1),
            ManifestVersion(id="version_corrupt", asset_id="asset_main", index=2),
        ],
        locations=[],
        sidecars=[
            ManifestSidecar(
                id="sidecar_timeline",
                asset_id="asset_main",
                kind=SidecarKind.SUBTITLE,
                path="timeline.srt",
                language="eng",
            ),
            ManifestSidecar(
                id="sidecar_updated",
                asset_id="asset_main",
                kind=SidecarKind.SUBTITLE,
                path="old.srt",
                language="spa",
            ),
        ],
    )

    phase_b.augment_phase_b_outputs(manifest, state)

    assert manifest.versions[0].content_hash == HASH_B
    assert manifest.versions[1].content_hash == HASH_C
    assert manifest.sidecars[0].content_hash == HASH_A
    assert manifest.sidecars[1].content_hash == HASH_D
    assert manifest.sidecars[1].path == "new.srt"


def test_phase_b_failure_helpers_map_error_classes() -> None:
    fs_error = FilesystemActionError(
        "move failed",
        event_id="move_001",
        action=TimelineActionName.MOVE_ASSET,
        cause=RuntimeError("missing file"),
        asset_id="asset_main",
    )
    media_error = MediaActionError(
        "media failed",
        event_id="media_001",
        action=TimelineActionName.REENCODE_VIDEO,
        cause=RuntimeError("ffmpeg failed"),
        asset_id="asset_main",
        tool_invocation_index=3,
    )
    corruption_error = CorruptionActionError(
        "corruption failed",
        event_id="corrupt_001",
        action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
        cause=RuntimeError("short file"),
        asset_id="asset_main",
    )

    assert phase_b.phase_b_failure_outcome(fs_error) is Outcome.FS_FAILED
    assert phase_b.phase_b_failure_record(fs_error).stage is FailureStage.FILESYSTEM
    assert phase_b.phase_b_failure_outcome(media_error) is Outcome.MEDIA_FAILED
    media_record = phase_b.phase_b_failure_record(media_error)
    assert media_record.stage is FailureStage.MEDIA
    assert media_record.invocation_index == 3
    assert phase_b.phase_b_failure_outcome(corruption_error) is Outcome.CORRUPTION_FAILED
    assert phase_b.phase_b_failure_record(corruption_error).stage is FailureStage.CORRUPTION


def _state(tmp_path: Path) -> phase_b.PhaseBState:
    return phase_b.PhaseBState(
        fs_ctx=FilesystemPhaseBContext(
            library_root=tmp_path,
            scenario_assets={},
            resolved_seed=7,
        ),
        media_ctx=MediaPhaseBContext(
            library_root=tmp_path,
            scenario_assets={},
            resolved_seed=7,
            ffmpeg_version="ffmpeg-test",
            ffprobe_version="ffprobe-test",
            invocations=[],
        ),
        corruption_ctx=CorruptionPhaseBContext(
            library_root=tmp_path,
            resolved_seed=7,
        ),
    )


def _entry(action: TimelineActionName) -> AtomicJournalEntry:
    return AtomicJournalEntry(
        schema_version=1,
        event_id=f"{action.value}_001",
        scenario_id="scenario_001",
        run_id=RUN_ID,
        logical_time_ns=0,
        action=action.value,
        target_ids=["asset_main"],
        input_version_ids=["version_0001"],
        output_version_ids=["version_0002"],
        location_ids=["location_0001"],
        state_delta={},
    )
