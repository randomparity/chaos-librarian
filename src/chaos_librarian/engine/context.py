"""Engine event context shared by timeline handlers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class EngineEventContext:
    run_id: uuid.UUID
    scenario_id: str
    resolved_seed: int
