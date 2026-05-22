"""Parametrized lock for ``_STATE_DELTA_KEYS``.

For every action in the engine state-delta contract, exercises the handler
on a minimal scenario and asserts the emitted ``state_delta`` is a superset
of the contract. Locks the surface against silent drift when future sprints
add or rename keys.
"""

from __future__ import annotations

import uuid

import pytest

from chaos_librarian.contract.journal import JournalPhase
from chaos_librarian.contract.scenario import TimelineActionName
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import _STATE_DELTA_KEYS, apply_event
from tests.engine.conftest import _minimal_scenario_for_action


@pytest.mark.parametrize("action", sorted(_STATE_DELTA_KEYS, key=lambda a: a.value))
def test_state_delta_keys_match_contract(action: TimelineActionName) -> None:
    """Every handler's emitted state_delta is a superset of _STATE_DELTA_KEYS[action]."""
    _scenario, state, resolved_event = _minimal_scenario_for_action(action)
    entries = apply_event(
        state=state,
        resolved=resolved_event,
        ids=IdAllocator(TraceRecorder()),
        run_id=uuid.UUID("1d4f7e6c-4e2e-4f1c-9a4c-7d2a9c8e0f01"),
        scenario_id="sc_test",
    )
    # Walk all emitted entries: slow_copy_start emits a Started entry whose
    # state_delta carries the start-time fields, slow_copy_commit emits a
    # Committed entry, and every other action emits a single Atomic entry.
    matching_phases = {
        TimelineActionName.SLOW_COPY_START: JournalPhase.STARTED,
        TimelineActionName.SLOW_COPY_COMMIT: JournalPhase.COMMITTED,
    }
    expected_phase = matching_phases.get(action, JournalPhase.ATOMIC)
    for entry in entries:
        if entry.phase is expected_phase:
            assert set(entry.state_delta.keys()) >= _STATE_DELTA_KEYS[action]
