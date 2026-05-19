"""Journal entry schema (one JSONL line per timeline event).

The journal is append-only and is the source of truth for the oracle.
The multi-phase fields (``phase``, ``temp_path``, ``related_event_id``)
are present from V1 so adding multi-phase mutations later does not force
a schema version bump.
The journal entry type is a discriminated union on ``phase`` so impossible
combinations (e.g. ``committed`` without ``related_event_id``, ``atomic`` with
``temp_path``) are rejected by Pydantic AND by the exported JSON Schema's
``oneOf``. See docs/specs/chaos-librarian-design.md "Oracle Journal" and
"Mutation Model".
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class JournalPhase(enum.StrEnum):
    """Mutation lifecycle phase.

    ``atomic`` is the default for single-event actions; the other values
    describe multi-phase mutations (e.g. slow-copy).
    """

    ATOMIC = "atomic"
    STARTED = "started"
    PROGRESSED = "progressed"
    COMMITTED = "committed"
    ABORTED = "aborted"


class _JournalEntryBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    event_id: str
    scenario_id: str
    run_id: uuid.UUID
    logical_time_ns: int
    wall_clock_time: datetime | None = None  # omitted in plan-only mode
    action: str
    target_ids: list[str] = Field(default_factory=list)
    input_version_ids: list[str] = Field(default_factory=list)
    output_version_ids: list[str] = Field(default_factory=list)
    location_ids: list[str] = Field(default_factory=list)
    state_delta: dict[str, object] = Field(default_factory=dict)
    toolchain: dict[str, str] | None = None


class AtomicJournalEntry(_JournalEntryBase):
    """Single-event mutation. No ``temp_path``, no ``related_event_id``."""

    phase: Literal[JournalPhase.ATOMIC] = JournalPhase.ATOMIC


class StartedJournalEntry(_JournalEntryBase):
    """First event of a multi-phase mutation. Requires ``temp_path``."""

    phase: Literal[JournalPhase.STARTED]
    temp_path: str


class ProgressedJournalEntry(_JournalEntryBase):
    """Intermediate event of a multi-phase mutation."""

    phase: Literal[JournalPhase.PROGRESSED]
    temp_path: str
    related_event_id: str


class CommittedJournalEntry(_JournalEntryBase):
    """Successful terminal event of a multi-phase mutation."""

    phase: Literal[JournalPhase.COMMITTED]
    related_event_id: str
    # No temp_path: the staged file has been renamed to its final path.


class AbortedJournalEntry(_JournalEntryBase):
    """Failed terminal event of a multi-phase mutation."""

    phase: Literal[JournalPhase.ABORTED]
    related_event_id: str
    # No temp_path: staging artifact lifecycle is described by related_event_id.


JournalEntry = Annotated[
    AtomicJournalEntry
    | StartedJournalEntry
    | ProgressedJournalEntry
    | CommittedJournalEntry
    | AbortedJournalEntry,
    Field(discriminator="phase"),
]
