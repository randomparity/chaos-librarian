"""Tests for the Sprint 10 corruption dispatcher."""

from __future__ import annotations

import hashlib
import uuid

import pytest

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.manifest import ProbedMedia
from chaos_librarian.contract.profiles import CorruptionProbeOutcome
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.materializer.corruption import (
    _CorruptionContext,
    _replacement_bytes,
    apply_corruption_action,
)
from chaos_librarian.materializer.errors import CorruptionActionError, ProbeParseError


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


def _probed() -> ProbedMedia:
    return ProbedMedia(container="matroska", duration_seconds=1.0, size_bytes=16, streams=[])


def test_replacement_bytes_are_deterministic() -> None:
    seed_material = "container_header_v1:42:corrupt_header_001:asset_main"

    first = _replacement_bytes(seed_material, 128)
    second = _replacement_bytes(seed_material, 128)

    assert first == second
    assert first != _replacement_bytes(seed_material + ":other", 128)
    assert len(first) == 128


def test_header_corruptor_changes_bytes_without_changing_length(tmp_path, monkeypatch) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    original = b"0123456789abcdef"
    asset.write_bytes(original)
    monkeypatch.setattr("chaos_librarian.materializer.corruption.probe_file", lambda _p: _probed())
    ctx = _CorruptionContext(library_root=tmp_path, resolved_seed=42)

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
    monkeypatch.setattr("chaos_librarian.materializer.corruption.probe_file", lambda _p: _probed())
    ctx = _CorruptionContext(library_root=tmp_path, resolved_seed=42)

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

    monkeypatch.setattr("chaos_librarian.materializer.corruption.probe_file", fail_probe)
    ctx = _CorruptionContext(library_root=tmp_path, resolved_seed=42)

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

    monkeypatch.setattr("chaos_librarian.materializer.corruption.probe_file", fail_probe)
    ctx = _CorruptionContext(library_root=tmp_path, resolved_seed=42)

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
    monkeypatch.setattr("chaos_librarian.materializer.corruption.probe_file", lambda _p: _probed())
    ctx = _CorruptionContext(library_root=tmp_path, resolved_seed=42)

    action = apply_corruption_action(ctx, _entry(byte_count=8))

    assert action.probe_outcome is CorruptionProbeOutcome.STILL_PROBEABLE
    assert action.probe_error_tail is None


def test_missing_input_raises_corruption_action_error(tmp_path) -> None:
    ctx = _CorruptionContext(library_root=tmp_path, resolved_seed=42)

    with pytest.raises(CorruptionActionError) as exc_info:
        apply_corruption_action(ctx, _entry(byte_count=8))

    assert exc_info.value.error_code == "E_MATERIALIZE_CORRUPTION_FAILED"
    assert exc_info.value.payload["event_id"] == "corrupt_header_001"
    assert exc_info.value.payload["action"] == "corrupt_container_header"


def test_short_file_raises_corruption_action_error(tmp_path) -> None:
    asset = tmp_path / "movies-hd" / "asset.mkv"
    asset.parent.mkdir()
    asset.write_bytes(b"short")
    ctx = _CorruptionContext(library_root=tmp_path, resolved_seed=42)

    with pytest.raises(CorruptionActionError, match="shorter than requested corruption range"):
        apply_corruption_action(ctx, _entry(byte_count=8))
