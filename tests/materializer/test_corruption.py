"""Tests for the Sprint 10 corruption dispatcher."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import pytest

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.profiles import CorruptionProbeOutcome
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer.errors import CorruptionActionError, ProbeParseError
from chaos_librarian.materializer.phase_b.corruption import handler as corruption_module
from chaos_librarian.materializer.phase_b.corruption.bytes import (
    malformed_id3_header,
    overwrite_range,
    replacement_bytes,
    truncate_bytes,
    zero_range,
)
from chaos_librarian.materializer.phase_b.corruption.handler import (
    CorruptionPhaseBContext,
    apply_corruption_action,
)
from chaos_librarian.materializer.phase_b.media import packet_probe
from chaos_librarian.materializer.tooling._subprocess import RecordedToolResult


def _entry(*, byte_count: int = 8) -> AtomicJournalEntry:
    return AtomicJournalEntry(
        schema_version=1,
        event_id="corrupt_header_001",
        scenario_id="sc",
        run_id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        logical_time_ns=0,
        action=TimelineActionName.CORRUPT_CONTAINER_HEADER,
        target_ids=["asset_main"],
        input_version_ids=["version_0001"],
        output_version_ids=["version_0002"],
        location_ids=["location_0001"],
        state_delta={
            "input_path": "movies-hd/asset.mkv",
            "output_path": "movies-hd/asset.mkv",
            "profile": "malformed-media",
            "corruptor": "container_header_v1",
            "byte_start": 0,
            "byte_count": byte_count,
            "seed_material": "container_header_v1:42:corrupt_header_001:asset_main",
        },
        phase=JournalPhase.ATOMIC,
    )


def _corruption_entry(
    *,
    action: TimelineActionName,
    event_id: str,
    state_delta: dict[str, object],
) -> AtomicJournalEntry:
    return AtomicJournalEntry(
        schema_version=1,
        event_id=event_id,
        scenario_id="sc",
        run_id=uuid.UUID("12345678-1234-5678-1234-567812345678"),
        logical_time_ns=0,
        action=action,
        target_ids=["asset_main"],
        input_version_ids=["version_0001"],
        output_version_ids=["version_0002"],
        location_ids=["location_0001"],
        state_delta=state_delta,
        phase=JournalPhase.ATOMIC,
    )


def _base_delta(**extra: object) -> dict[str, object]:
    return {
        "input_path": "movies-hd/asset.mkv",
        "output_path": "movies-hd/asset.mkv",
        "profile": "malformed-media",
        **extra,
    }


def _probed() -> ProbedMedia:
    return ProbedMedia(container="matroska", duration_seconds=1.0, size_bytes=16, streams=[])


def test_replacement_bytes_are_deterministic() -> None:
    seed_material = "container_header_v1:42:corrupt_header_001:asset_main"

    first = replacement_bytes(seed_material, 128)
    second = replacement_bytes(seed_material, 128)

    assert first == second
    assert first != replacement_bytes(seed_material + ":other", 128)
    assert len(first) == 128


def test_overwrite_range_preserves_length_and_only_changes_requested_slice() -> None:
    data = b"0123456789abcdef"

    output = overwrite_range(data, byte_start=4, byte_count=6, seed_material="seed")

    assert len(output) == len(data)
    assert output[:4] == data[:4]
    assert output[4:10] != data[4:10]
    assert output[10:] == data[10:]


def test_truncate_bytes_rejects_keep_bytes_equal_to_size() -> None:
    with pytest.raises(ValueError, match="shorter than input"):
        truncate_bytes(b"0123456789abcdef", keep_bytes=16)


def test_truncate_bytes_returns_exactly_keep_bytes() -> None:
    assert truncate_bytes(b"0123456789abcdef", keep_bytes=6) == b"012345"


def test_header_corruptor_changes_bytes_without_changing_length(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    original = b"0123456789abcdef"
    asset.write_bytes(original)
    monkeypatch.setattr(corruption_module, "probe_file", lambda _p: _probed())
    ctx = CorruptionPhaseBContext(library_root=tmp_path, resolved_seed=42)

    apply_corruption_action(ctx, _entry(byte_count=8))

    corrupted = asset.read_bytes()
    assert len(corrupted) == len(original)
    assert corrupted[:8] != original[:8]
    assert corrupted[8:] == original[8:]


def test_corruption_action_records_input_and_output_hashes(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    original = b"0123456789abcdef"
    asset.write_bytes(original)
    monkeypatch.setattr(corruption_module, "probe_file", lambda _p: _probed())
    ctx = CorruptionPhaseBContext(library_root=tmp_path, resolved_seed=42)

    action = apply_corruption_action(ctx, _entry(byte_count=8))

    expected_input_hash = "sha256:" + hashlib.sha256(original).hexdigest()
    expected_output_hash = "sha256:" + hashlib.sha256(asset.read_bytes()).hexdigest()
    assert action.input_content_hash == expected_input_hash
    assert action.output_content_hash == expected_output_hash
    assert action.probe_outcome is CorruptionProbeOutcome.STILL_PROBEABLE
    assert ctx.post_phase_b_versions["version_0002"] == (expected_output_hash, _probed())


def test_probe_failure_records_failed_expected(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    asset.write_bytes(b"0123456789abcdef")

    def fail_probe(_path):
        raise ProbeParseError("ffprobe exit 1", payload={"stderr": "invalid data"})

    monkeypatch.setattr(corruption_module, "probe_file", fail_probe)
    ctx = CorruptionPhaseBContext(library_root=tmp_path, resolved_seed=42)

    action = apply_corruption_action(ctx, _entry(byte_count=8))

    assert action.probe_outcome is CorruptionProbeOutcome.FAILED_EXPECTED
    assert action.probe_error_tail == "invalid data"
    assert ctx.post_phase_b_versions["version_0002"][1] is None


def test_probe_failure_tail_replaces_absolute_output_path(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    asset.write_bytes(b"0123456789abcdef")

    def fail_probe(path):
        raise ProbeParseError(
            f"ffprobe exit 1 on {path}",
            payload={
                "path": str(path),
                "stderr": (
                    f"[matroska,webm @ 0xca6c7c000] EBML header parsing failed\n{path}: "
                    "Invalid data found when processing input\n"
                ),
            },
        )

    monkeypatch.setattr(corruption_module, "probe_file", fail_probe)
    ctx = CorruptionPhaseBContext(library_root=tmp_path, resolved_seed=42)

    action = apply_corruption_action(ctx, _entry(byte_count=8))

    assert action.probe_error_tail is not None
    assert str(asset) not in action.probe_error_tail
    assert "0xca6c7c000" not in action.probe_error_tail
    assert action.probe_error_tail == (
        "[matroska,webm @ <addr>] EBML header parsing failed\n"
        "<corrupted-output>: Invalid data found when processing input\n"
    )


def test_probe_success_records_still_probeable(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    asset.write_bytes(b"0123456789abcdef")
    monkeypatch.setattr(corruption_module, "probe_file", lambda _p: _probed())
    ctx = CorruptionPhaseBContext(library_root=tmp_path, resolved_seed=42)

    action = apply_corruption_action(ctx, _entry(byte_count=8))

    assert action.probe_outcome is CorruptionProbeOutcome.STILL_PROBEABLE
    assert action.probe_error_tail is None


def test_missing_input_raises_corruption_action_error(tmp_path) -> None:
    ctx = CorruptionPhaseBContext(library_root=tmp_path, resolved_seed=42)

    with pytest.raises(CorruptionActionError) as exc_info:
        apply_corruption_action(ctx, _entry(byte_count=8))

    assert exc_info.value.error_code == "E_MATERIALIZE_CORRUPTION_FAILED"
    assert exc_info.value.payload["event_id"] == "corrupt_header_001"
    assert exc_info.value.payload["action"] == "corrupt_container_header"


def test_short_file_raises_corruption_action_error(tmp_path) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    asset.write_bytes(b"short")
    ctx = CorruptionPhaseBContext(library_root=tmp_path, resolved_seed=42)

    with pytest.raises(CorruptionActionError, match="shorter than requested corruption range"):
        apply_corruption_action(ctx, _entry(byte_count=8))


def test_truncate_file_shortens_bytes_and_records_hashes(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    original = b"0123456789abcdef"
    asset.write_bytes(original)
    monkeypatch.setattr(corruption_module, "probe_file", lambda _p: _probed())
    ctx = CorruptionPhaseBContext(library_root=tmp_path, resolved_seed=42)
    entry = _corruption_entry(
        action=TimelineActionName.TRUNCATE_FILE,
        event_id="truncate_001",
        state_delta=_base_delta(
            corruptor="truncate_file_v1",
            keep_bytes=6,
            seed_material="truncate_file_v1:42:truncate_001:asset_main",
        ),
    )

    action = apply_corruption_action(ctx, entry)

    assert asset.read_bytes() == b"012345"
    assert action.input_size_bytes == 16
    assert action.output_size_bytes == 6
    assert action.byte_start == 6
    assert action.byte_count == 10
    assert action.input_content_hash == "sha256:" + hashlib.sha256(original).hexdigest()
    assert action.output_content_hash == "sha256:" + hashlib.sha256(b"012345").hexdigest()


def test_truncate_file_rejects_keep_bytes_equal_to_size(tmp_path) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    asset.write_bytes(b"0123456789abcdef")
    ctx = CorruptionPhaseBContext(library_root=tmp_path, resolved_seed=42)
    entry = _corruption_entry(
        action=TimelineActionName.TRUNCATE_FILE,
        event_id="truncate_001",
        state_delta=_base_delta(
            corruptor="truncate_file_v1",
            keep_bytes=16,
            seed_material="truncate_file_v1:42:truncate_001:asset_main",
        ),
    )

    with pytest.raises(CorruptionActionError, match="shorter than input"):
        apply_corruption_action(ctx, entry)


def test_packet_range_corruption_uses_resolved_packet_range(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    original = b"0123456789abcdef"
    asset.write_bytes(original)
    monkeypatch.setattr(corruption_module, "probe_file", lambda _p: _probed())
    monkeypatch.setattr(
        corruption_module,
        "resolve_packet_byte_range",
        lambda _path, **_kwargs: (4, 4),
    )
    ctx = CorruptionPhaseBContext(library_root=tmp_path, resolved_seed=42)
    entry = _corruption_entry(
        action=TimelineActionName.CORRUPT_PACKET_RANGE,
        event_id="packet_corrupt_001",
        state_delta=_base_delta(
            corruptor="packet_range_v1",
            stream="video",
            packet_start=1,
            packet_count=2,
            seed_material="packet_range_v1:42:packet_corrupt_001:asset_main",
        ),
    )

    apply_corruption_action(ctx, entry)

    corrupted = asset.read_bytes()
    assert len(corrupted) == len(original)
    assert corrupted[:4] == original[:4]
    assert corrupted[4:8] != original[4:8]
    assert corrupted[8:] == original[8:]


def test_packet_range_corruption_records_packet_evidence(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    asset.write_bytes(b"0123456789abcdef")
    monkeypatch.setattr(corruption_module, "probe_file", lambda _p: _probed())
    monkeypatch.setattr(
        corruption_module,
        "resolve_packet_byte_range",
        lambda _path, **_kwargs: (4, 4),
    )
    ctx = CorruptionPhaseBContext(library_root=tmp_path, resolved_seed=42)
    entry = _corruption_entry(
        action=TimelineActionName.CORRUPT_PACKET_RANGE,
        event_id="packet_corrupt_001",
        state_delta=_base_delta(
            corruptor="packet_range_v1",
            stream="audio",
            packet_start=1,
            packet_count=2,
            seed_material="packet_range_v1:42:packet_corrupt_001:asset_main",
        ),
    )

    action = apply_corruption_action(ctx, entry)

    assert action.action is TimelineActionName.CORRUPT_PACKET_RANGE
    assert action.stream == "audio"
    assert action.packet_start == 1
    assert action.packet_count == 2
    assert action.byte_start == 4
    assert action.byte_count == 4
    assert action.seed_material == "packet_range_v1:42:packet_corrupt_001:asset_main"


def test_packet_range_corruption_records_ffprobe_invocation(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    asset.write_bytes(b"0123456789abcdef")
    monkeypatch.setattr(corruption_module, "probe_file", lambda _p: _probed())

    def fake_run_ffprobe(argv, **kwargs):
        return RecordedToolResult(
            invocation=ToolInvocation(
                tool="ffprobe",
                version=kwargs["ffprobe_version"],
                command=list(argv),
                exit_code=0,
                duration_ns=1,
            ),
            stderr_tail="",
            stdout='{"packets": [{"pos": "4", "size": "4"}]}',
        )

    monkeypatch.setattr(packet_probe, "_run_ffprobe_packets", fake_run_ffprobe)
    ctx = CorruptionPhaseBContext(
        library_root=tmp_path,
        resolved_seed=42,
        ffprobe_version="ffprobe test",
        invocations=[],
    )
    entry = _corruption_entry(
        action=TimelineActionName.CORRUPT_PACKET_RANGE,
        event_id="packet_corrupt_001",
        state_delta=_base_delta(
            corruptor="packet_range_v1",
            stream="video",
            packet_start=0,
            packet_count=1,
            seed_material="packet_range_v1:42:packet_corrupt_001:asset_main",
        ),
    )

    apply_corruption_action(ctx, entry)

    assert len(ctx.invocations) == 1
    assert ctx.invocations[0].tool == "ffprobe"
    assert ctx.invocations[0].version == "ffprobe test"


def test_invalid_duration_metadata_invokes_ffmpeg_copy_with_duration_tag(
    tmp_path, monkeypatch
) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    asset.write_bytes(b"0123456789abcdef")
    monkeypatch.setattr(corruption_module, "probe_file", lambda _p: _probed())

    def fake_run_ffmpeg(argv: list[str], *, ffmpeg_version: str):
        Path(argv[-1]).write_bytes(asset.read_bytes() + b"!")
        return (
            ToolInvocation(
                tool="ffmpeg",
                version=ffmpeg_version,
                command=argv,
                exit_code=0,
                duration_ns=123,
            ),
            "",
        )

    monkeypatch.setattr(corruption_module, "run_ffmpeg", fake_run_ffmpeg)
    ctx = CorruptionPhaseBContext(
        library_root=tmp_path,
        resolved_seed=42,
        ffmpeg_version="ffmpeg test",
        invocations=[],
    )
    entry = _corruption_entry(
        action=TimelineActionName.WRITE_INVALID_DURATION_METADATA,
        event_id="duration_bad_001",
        state_delta=_base_delta(
            corruptor="invalid_duration_metadata_v1",
            value="not-a-duration",
            seed_material="invalid_duration_metadata_v1:42:duration_bad_001:asset_main",
        ),
    )

    action = apply_corruption_action(ctx, entry)

    assert ctx.invocations
    assert ctx.invocations[0].command == [
        "ffmpeg",
        "-hide_banner",
        "-y",
        "-i",
        str(asset),
        "-map",
        "0",
        "-c",
        "copy",
        "-metadata",
        "duration=not-a-duration",
        str(asset.with_name("asset.tmp.42.mkv")),
    ]
    assert action.action is TimelineActionName.WRITE_INVALID_DURATION_METADATA
    assert action.output_size_bytes == 17


def test_invalid_duration_metadata_failure_carries_invocation_index(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    asset.write_bytes(b"0123456789abcdef")
    monkeypatch.setattr(corruption_module, "probe_file", lambda _p: _probed())

    def fake_run_ffmpeg(argv: list[str], *, ffmpeg_version: str):
        return (
            ToolInvocation(
                tool="ffmpeg",
                version=ffmpeg_version,
                command=argv,
                exit_code=1,
                duration_ns=123,
            ),
            "bad metadata",
        )

    monkeypatch.setattr(corruption_module, "run_ffmpeg", fake_run_ffmpeg)
    ctx = CorruptionPhaseBContext(
        library_root=tmp_path,
        resolved_seed=42,
        ffmpeg_version="ffmpeg test",
        invocations=[],
    )
    entry = _corruption_entry(
        action=TimelineActionName.WRITE_INVALID_DURATION_METADATA,
        event_id="duration_bad_001",
        state_delta=_base_delta(
            corruptor="invalid_duration_metadata_v1",
            value="not-a-duration",
            seed_material="invalid_duration_metadata_v1:42:duration_bad_001:asset_main",
        ),
    )

    with pytest.raises(CorruptionActionError, match="bad metadata") as exc_info:
        apply_corruption_action(ctx, entry)

    assert exc_info.value.tool_invocation_index == 0
    assert ctx.invocations[0].exit_code == 1


def test_invalid_duration_metadata_records_probe_duration_before_and_after(
    tmp_path, monkeypatch
) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    asset.write_bytes(b"0123456789abcdef")

    probe_durations = iter((1.0, 999.0))

    def fake_probe(path: Path) -> ProbedMedia:
        duration = next(probe_durations)
        return ProbedMedia(
            container="matroska",
            duration_seconds=duration,
            size_bytes=path.stat().st_size,
            streams=[],
        )

    def fake_run_ffmpeg(argv: list[str], *, ffmpeg_version: str):
        del ffmpeg_version
        Path(argv[-1]).write_bytes(asset.read_bytes() + b"!")
        return (
            ToolInvocation(
                tool="ffmpeg",
                version="ffmpeg test",
                command=argv,
                exit_code=0,
                duration_ns=123,
            ),
            "",
        )

    monkeypatch.setattr(corruption_module, "probe_file", fake_probe)
    monkeypatch.setattr(corruption_module, "run_ffmpeg", fake_run_ffmpeg)
    ctx = CorruptionPhaseBContext(
        library_root=tmp_path,
        resolved_seed=42,
        ffmpeg_version="ffmpeg test",
        invocations=[],
    )
    entry = _corruption_entry(
        action=TimelineActionName.WRITE_INVALID_DURATION_METADATA,
        event_id="duration_bad_001",
        state_delta=_base_delta(
            corruptor="invalid_duration_metadata_v1",
            value="not-a-duration",
            seed_material="invalid_duration_metadata_v1:42:duration_bad_001:asset_main",
        ),
    )

    action = apply_corruption_action(ctx, entry)

    assert action.metadata == {
        "value": "not-a-duration",
        "input_duration_seconds": 1.0,
        "output_duration_seconds": 999.0,
    }


def test_zero_range_zeros_head_and_preserves_length() -> None:
    out = zero_range(b"abcdefgh", byte_start=0, byte_count=4)
    assert out == b"\x00\x00\x00\x00efgh"
    assert len(out) == 8


def test_zero_range_rejects_overlong() -> None:
    with pytest.raises(ValueError, match="shorter than requested"):
        zero_range(b"ab", byte_start=0, byte_count=4)


def test_malformed_id3_header_in_place_and_starts_with_magic() -> None:
    out = malformed_id3_header(b"\x11" * 32, byte_count=10)
    assert out[:3] == b"ID3"
    assert len(out) == 32
    assert out[10:] == b"\x11" * 22


def test_malformed_id3_header_rejects_overlong() -> None:
    with pytest.raises(ValueError, match="shorter than requested"):
        malformed_id3_header(b"\x11" * 4, byte_count=10)


def _corrupt_tags_entry(*, flavor: str, byte_count: int = 8) -> AtomicJournalEntry:
    return _corruption_entry(
        action=TimelineActionName.CORRUPT_TAGS,
        event_id="corrupt_tags_001",
        state_delta={
            "input_path": "movies-hd/asset.mkv",
            "output_path": "movies-hd/asset.mkv",
            "profile": "malformed-media",
            "corruptor": "tag_corruption_v1",
            "flavor": flavor,
            "byte_count": byte_count,
            "seed_material": "tag_corruption_v1:42:corrupt_tags_001:asset_main",
        },
    )


def test_corrupt_tags_null_bytes_zeros_head(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    asset.write_bytes(b"0123456789abcdef")
    monkeypatch.setattr(corruption_module, "probe_file", lambda _p: _probed())
    ctx = CorruptionPhaseBContext(library_root=tmp_path, resolved_seed=42)

    action = apply_corruption_action(ctx, _corrupt_tags_entry(flavor="null_bytes", byte_count=8))

    corrupted = asset.read_bytes()
    assert corrupted[:8] == b"\x00" * 8
    assert corrupted[8:] == b"89abcdef"
    assert action.action == TimelineActionName.CORRUPT_TAGS
    assert action.metadata == {"flavor": "null_bytes"}


def test_corrupt_tags_malformed_frame_writes_id3_magic(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    asset.write_bytes(b"0123456789abcdef")
    monkeypatch.setattr(corruption_module, "probe_file", lambda _p: _probed())
    ctx = CorruptionPhaseBContext(library_root=tmp_path, resolved_seed=42)

    action = apply_corruption_action(
        ctx, _corrupt_tags_entry(flavor="malformed_frame", byte_count=10)
    )

    corrupted = asset.read_bytes()
    assert corrupted[:3] == b"ID3"
    assert len(corrupted) == 16
    assert action.metadata == {"flavor": "malformed_frame"}
