"""Tests for the journal entry schema."""

from __future__ import annotations

import uuid

import pytest
from pydantic import TypeAdapter, ValidationError

from chaos_librarian.contract import JOURNAL_SCHEMA_VERSION
from chaos_librarian.contract.journal import (
    AbortedJournalEntry,  # noqa: F401  -- verifies public re-export of aborted entry type
    AtomicJournalEntry,
    CommittedJournalEntry,
    JournalEntry,
    JournalPhase,
    ProgressedJournalEntry,  # noqa: F401  -- verifies public re-export of progressed entry type
    StartedJournalEntry,
)


def _atomic_entry() -> AtomicJournalEntry:
    return AtomicJournalEntry(
        schema_version=JOURNAL_SCHEMA_VERSION,
        event_id="e1",
        scenario_id="s1",
        run_id=uuid.uuid4(),
        logical_time_ns=2_000_000_000,
        action="move_asset",
        target_ids=["a1"],
    )


def _base_fields(event_id: str = "e1") -> dict[str, object]:
    return {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "event_id": event_id,
        "scenario_id": "sc",
        "run_id": str(uuid.uuid4()),
        "logical_time_ns": 2_000_000_000,
        "action": "x",
    }


def test_atomic_entry_roundtrip() -> None:
    e = _atomic_entry()
    loaded = TypeAdapter(JournalEntry).validate_json(e.model_dump_json())
    assert loaded == e


def test_start_phase_with_temp_path() -> None:
    e = StartedJournalEntry(
        schema_version=JOURNAL_SCHEMA_VERSION,
        event_id="s1",
        scenario_id="sc",
        run_id=uuid.uuid4(),
        logical_time_ns=6_000_000_000,
        action="slow_copy_start",
        target_ids=["a1"],
        phase=JournalPhase.STARTED,
        temp_path="movies-hd/A.mkv.part",
    )
    loaded = TypeAdapter(JournalEntry).validate_json(e.model_dump_json())
    assert loaded.phase is JournalPhase.STARTED
    assert loaded.temp_path == "movies-hd/A.mkv.part"


def test_commit_phase_references_start() -> None:
    e = CommittedJournalEntry(
        schema_version=JOURNAL_SCHEMA_VERSION,
        event_id="c1",
        scenario_id="sc",
        run_id=uuid.uuid4(),
        logical_time_ns=9_000_000_000,
        action="slow_copy_commit",
        target_ids=["a1"],
        phase=JournalPhase.COMMITTED,
        related_event_id="s1",
    )
    loaded = TypeAdapter(JournalEntry).validate_json(e.model_dump_json())
    assert loaded.phase is JournalPhase.COMMITTED
    assert loaded.related_event_id == "s1"


def test_rejects_unknown_phase() -> None:
    bad = _atomic_entry().model_dump(mode="json")
    bad["phase"] = "halfway"
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(bad)


def test_wall_clock_time_optional() -> None:
    e = _atomic_entry()
    assert e.wall_clock_time is None


def test_atomic_entry_rejects_temp_path() -> None:
    bad = _atomic_entry().model_dump(mode="json")
    bad["temp_path"] = "x"
    with pytest.raises(ValidationError):
        # Validate via the union so the discriminator is respected.
        TypeAdapter(JournalEntry).validate_python(bad)


def test_started_entry_requires_temp_path() -> None:
    base = {**_base_fields("s1"), "phase": "started"}
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(base)


def test_progressed_entry_requires_both_temp_path_and_related_event_id() -> None:
    base = {**_base_fields("p1"), "phase": "progressed"}
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(base)
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python({**base, "temp_path": "x"})
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python({**base, "related_event_id": "s1"})


def test_committed_entry_requires_related_event_id() -> None:
    base = {**_base_fields("c1"), "phase": "committed"}
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(base)


def test_committed_entry_rejects_temp_path() -> None:
    base = {
        **_base_fields("c1"),
        "phase": "committed",
        "related_event_id": "s1",
        "temp_path": "x",  # forbidden on committed
    }
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(base)


def test_aborted_entry_requires_related_event_id() -> None:
    base = {**_base_fields("a1"), "phase": "aborted"}
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(base)


def test_aborted_entry_rejects_temp_path() -> None:
    base = {
        **_base_fields("a1"),
        "phase": "aborted",
        "related_event_id": "s1",
        "temp_path": "x",  # forbidden on aborted
    }
    with pytest.raises(ValidationError):
        TypeAdapter(JournalEntry).validate_python(base)
