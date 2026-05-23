"""Parametrized lock for ``_STATE_DELTA_KEYS``.

For every action in the engine state-delta contract, exercises the handler
on a minimal scenario and asserts the emitted ``state_delta`` is a superset
of the contract. Locks the surface against silent drift when future sprints
add or rename keys.
"""

from __future__ import annotations

import inspect

import pytest

from chaos_librarian.contract.journal import JournalPhase
from chaos_librarian.contract.scenario import RenameFileEvent, TimelineActionName
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import _STATE_DELTA_KEYS, apply_event
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.errors import ChaosLibrarianValueError
from tests.engine.conftest import _engine_event_context, _minimal_scenario_for_action


def test_apply_event_uses_engine_event_context_signature() -> None:
    assert list(inspect.signature(apply_event).parameters) == [
        "state",
        "resolved",
        "ids",
        "ctx",
    ]


def test_apply_event_rejects_mismatched_event_model() -> None:
    _scenario, state, _resolved_event = _minimal_scenario_for_action(TimelineActionName.MOVE_ASSET)
    event = RenameFileEvent(
        id="ev",
        at="0ns",
        target="asset_hd_main",
        to="movies-hd/renamed.mkv",
    ).model_copy(update={"action": TimelineActionName.MOVE_ASSET})

    with pytest.raises(ChaosLibrarianValueError, match="move_asset"):
        apply_event(
            state=state,
            resolved=ResolvedEvent(at_ns=1, declared_index=0, event=event),
            ids=IdAllocator(TraceRecorder()),
            ctx=_engine_event_context(),
        )


def test_corruption_state_delta_contract_keys() -> None:
    assert _STATE_DELTA_KEYS[TimelineActionName.CORRUPT_CONTAINER_HEADER] == frozenset(
        {
            "input_path",
            "output_path",
            "profile",
            "corruptor",
            "byte_start",
            "byte_count",
            "seed_material",
        }
    )


@pytest.mark.parametrize("action", sorted(_STATE_DELTA_KEYS, key=lambda a: a.value))
def test_state_delta_keys_match_contract(action: TimelineActionName) -> None:
    """Every handler's emitted state_delta is a superset of _STATE_DELTA_KEYS[action]."""
    _scenario, state, resolved_event = _minimal_scenario_for_action(action)
    entries = apply_event(
        state=state,
        resolved=resolved_event,
        ids=IdAllocator(TraceRecorder()),
        ctx=_engine_event_context(),
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
