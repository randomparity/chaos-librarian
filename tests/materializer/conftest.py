"""Shared helpers for materializer-level tests.

The ``_atomic_entry`` and ``_committed_entry`` factories below build
fully-validated ``JournalEntry`` instances from a tiny keyword call so
phase-B dispatcher tests can stage their inputs without restating the
boilerplate (``schema_version``, ``scenario_id``, ``run_id``, etc.) at
every call site.
"""

from __future__ import annotations

import uuid
from typing import Any, Final

from pydantic import TypeAdapter

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.scenario import TimelineActionName

_JOURNAL_ENTRY_ADAPTER: Final[TypeAdapter[JournalEntry]] = TypeAdapter(JournalEntry)
_RUN_ID: Final[uuid.UUID] = uuid.UUID("1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01")


def _atomic_entry(
    *,
    event_id: str,
    action: TimelineActionName,
    target: str,
    state_delta: dict[str, Any],
    logical_time_ns: int = 1,
) -> JournalEntry:
    """Build a typed ``AtomicJournalEntry`` for dispatcher tests."""
    payload: dict[str, Any] = {
        "schema_version": 1,
        "event_id": event_id,
        "scenario_id": "sc_test",
        "run_id": str(_RUN_ID),
        "logical_time_ns": logical_time_ns,
        "action": action.value,
        "target_ids": [target],
        "input_version_ids": [],
        "output_version_ids": [],
        "location_ids": [],
        "state_delta": state_delta,
        "phase": "atomic",
    }
    return _JOURNAL_ENTRY_ADAPTER.validate_python(payload)


def _started_entry(
    *,
    event_id: str,
    target: str,
    temp_path: str,
    state_delta: dict[str, Any],
    logical_time_ns: int = 1,
) -> JournalEntry:
    """Build a typed ``StartedJournalEntry`` for dispatcher tests."""
    payload: dict[str, Any] = {
        "schema_version": 1,
        "event_id": event_id,
        "scenario_id": "sc_test",
        "run_id": str(_RUN_ID),
        "logical_time_ns": logical_time_ns,
        "action": TimelineActionName.SLOW_COPY_START.value,
        "target_ids": [target],
        "input_version_ids": [],
        "output_version_ids": [],
        "location_ids": [],
        "state_delta": state_delta,
        "phase": "started",
        "temp_path": temp_path,
    }
    return _JOURNAL_ENTRY_ADAPTER.validate_python(payload)


def _committed_entry(
    *,
    event_id: str,
    target: str,
    related_event_id: str,
    state_delta: dict[str, Any],
    logical_time_ns: int = 2,
) -> JournalEntry:
    """Build a typed ``CommittedJournalEntry`` for dispatcher tests."""
    payload: dict[str, Any] = {
        "schema_version": 1,
        "event_id": event_id,
        "scenario_id": "sc_test",
        "run_id": str(_RUN_ID),
        "logical_time_ns": logical_time_ns,
        "action": TimelineActionName.SLOW_COPY_COMMIT.value,
        "target_ids": [target],
        "input_version_ids": [],
        "output_version_ids": [],
        "location_ids": [],
        "state_delta": state_delta,
        "phase": "committed",
        "related_event_id": related_event_id,
    }
    return _JOURNAL_ENTRY_ADAPTER.validate_python(payload)
