"""Engine event context shared by timeline handlers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass(slots=True)
class EngineEventContext:
    run_id: uuid.UUID
    scenario_id: str
    resolved_seed: int

    # Runtime-only windows keyed by start/open event id. They are intentionally
    # outside WorldState because they are execution bookkeeping, not manifest
    # state.
    pending_slow_copies: dict[str, tuple[str, str]] = field(default_factory=dict)
    previous_event_delta: tuple[str, dict[str, object]] | None = None
    pending_network_lags: dict[str, dict[str, object]] = field(default_factory=dict)
    pending_locks: dict[str, dict[str, object]] = field(default_factory=dict)
    pending_unmounts: dict[str, dict[str, object]] = field(default_factory=dict)
