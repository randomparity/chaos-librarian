"""Tests for chaos_librarian.engine.journal_io.serialize_journal_bytes.

The byte form produced here is the shared input to both the on-disk
``journal.jsonl`` writer and the ``journal_digest`` SHA-256 in the
replay bundle, so the line shape, ordering, and terminator are part of
the contract.
"""

from __future__ import annotations

import uuid

from pydantic import TypeAdapter

from chaos_librarian.contract import JOURNAL_SCHEMA_VERSION
from chaos_librarian.contract.journal import (
    AbortedJournalEntry,
    AtomicJournalEntry,
    CommittedJournalEntry,
    JournalEntry,
    JournalPhase,
    ProgressedJournalEntry,
    StartedJournalEntry,
)
from chaos_librarian.engine.journal_io import serialize_journal_bytes

_RUN_ID = uuid.UUID("00000000-0000-0000-0000-00000000abcd")


def _atomic(event_id: str = "e1", logical_time_ns: int = 1_000_000_000) -> AtomicJournalEntry:
    return AtomicJournalEntry(
        schema_version=JOURNAL_SCHEMA_VERSION,
        event_id=event_id,
        scenario_id="sc",
        run_id=_RUN_ID,
        logical_time_ns=logical_time_ns,
        action="move_asset",
        target_ids=["a1"],
    )


def test_empty_iterable_returns_empty_bytes() -> None:
    assert serialize_journal_bytes([]) == b""


def test_jsonl_ordering_preserves_input_sequence() -> None:
    entries = [
        _atomic("e1", 1_000_000_000),
        _atomic("e2", 2_000_000_000),
        _atomic("e3", 3_000_000_000),
    ]
    data = serialize_journal_bytes(entries)
    lines = data.split(b"\n")
    # Trailing terminator yields an empty tail element; strip it.
    assert lines[-1] == b""
    decoded = [TypeAdapter(JournalEntry).validate_json(line) for line in lines[:-1]]
    assert [entry.event_id for entry in decoded] == ["e1", "e2", "e3"]


def test_each_entry_terminates_with_newline() -> None:
    data = serialize_journal_bytes([_atomic(), _atomic("e2")])
    # Two entries plus terminator newline => exactly 2 newlines, none missing.
    assert data.count(b"\n") == 2
    assert data.endswith(b"\n")
    # No bare CR or extra whitespace separators.
    assert b"\r" not in data


def test_atomic_round_trip() -> None:
    entry = _atomic()
    data = serialize_journal_bytes([entry])
    [decoded] = [
        TypeAdapter(JournalEntry).validate_json(line) for line in data.split(b"\n") if line
    ]
    assert decoded == entry
    assert decoded.phase is JournalPhase.ATOMIC


def test_started_phase_round_trip() -> None:
    entry = StartedJournalEntry(
        schema_version=JOURNAL_SCHEMA_VERSION,
        event_id="s1",
        scenario_id="sc",
        run_id=_RUN_ID,
        logical_time_ns=5_000_000_000,
        action="slow_copy_start",
        target_ids=["a1"],
        phase=JournalPhase.STARTED,
        temp_path="movies-hd/A.mkv.part",
    )
    data = serialize_journal_bytes([entry])
    [decoded] = [
        TypeAdapter(JournalEntry).validate_json(line) for line in data.split(b"\n") if line
    ]
    assert decoded == entry
    assert isinstance(decoded, StartedJournalEntry)
    assert decoded.temp_path == "movies-hd/A.mkv.part"


def test_progressed_phase_round_trip() -> None:
    entry = ProgressedJournalEntry(
        schema_version=JOURNAL_SCHEMA_VERSION,
        event_id="p1",
        scenario_id="sc",
        run_id=_RUN_ID,
        logical_time_ns=6_000_000_000,
        action="slow_copy_progress",
        target_ids=["a1"],
        phase=JournalPhase.PROGRESSED,
        temp_path="movies-hd/A.mkv.part",
        related_event_id="s1",
    )
    data = serialize_journal_bytes([entry])
    [decoded] = [
        TypeAdapter(JournalEntry).validate_json(line) for line in data.split(b"\n") if line
    ]
    assert decoded == entry
    assert isinstance(decoded, ProgressedJournalEntry)
    assert decoded.related_event_id == "s1"


def test_committed_phase_round_trip() -> None:
    entry = CommittedJournalEntry(
        schema_version=JOURNAL_SCHEMA_VERSION,
        event_id="c1",
        scenario_id="sc",
        run_id=_RUN_ID,
        logical_time_ns=9_000_000_000,
        action="slow_copy_commit",
        target_ids=["a1"],
        phase=JournalPhase.COMMITTED,
        related_event_id="s1",
    )
    data = serialize_journal_bytes([entry])
    [decoded] = [
        TypeAdapter(JournalEntry).validate_json(line) for line in data.split(b"\n") if line
    ]
    assert decoded == entry
    assert isinstance(decoded, CommittedJournalEntry)


def test_aborted_phase_round_trip() -> None:
    entry = AbortedJournalEntry(
        schema_version=JOURNAL_SCHEMA_VERSION,
        event_id="x1",
        scenario_id="sc",
        run_id=_RUN_ID,
        logical_time_ns=9_000_000_000,
        action="slow_copy_abort",
        target_ids=["a1"],
        phase=JournalPhase.ABORTED,
        related_event_id="s1",
    )
    data = serialize_journal_bytes([entry])
    [decoded] = [
        TypeAdapter(JournalEntry).validate_json(line) for line in data.split(b"\n") if line
    ]
    assert decoded == entry
    assert isinstance(decoded, AbortedJournalEntry)


def test_serialization_is_deterministic_byte_identity() -> None:
    entries = [_atomic("e1"), _atomic("e2", 2_000_000_000)]
    a = serialize_journal_bytes(entries)
    b = serialize_journal_bytes(entries)
    assert a == b


def test_none_fields_are_excluded() -> None:
    entry = _atomic()
    assert entry.wall_clock_time is None
    data = serialize_journal_bytes([entry])
    # exclude_none=True must keep optional unset fields out of the line.
    assert b"wall_clock_time" not in data
