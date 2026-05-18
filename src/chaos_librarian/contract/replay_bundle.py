"""Replay bundle schema.

A single JSON file (``replay.json``) sufficient to reproduce a run. Plan-only
bundles are bit-identical for the same scenario + seed; materialize bundles
are logically identical modulo volatile fields. ``ReplayBundle`` is a
discriminated union on ``execution_mode`` so the mode-split contract
(created_at / toolchain required iff materialize/run; forbidden iff plan_only)
is enforced by Pydantic AND exported as ``oneOf`` in JSON Schema. See
docs/specs/chaos-librarian-design.md "Replay Bundle" and "Reproducibility
Guarantees".
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from chaos_librarian.contract import CHAOS_LIBRARIAN_NAMESPACE_UUID


class ExecutionTraceKind(enum.StrEnum):
    """Discriminator for ``ExecutionTraceEntry`` variants."""

    RNG = "rng"
    ALLOC = "alloc"
    MATERIALIZER = "materializer"


class ExecutionMode(enum.StrEnum):
    """Discriminator for ``ReplayBundle`` variants."""

    PLAN_ONLY = "plan_only"
    MATERIALIZE = "materialize"
    RUN = "run"


def compute_plan_only_run_id(scenario_content_hash: str, resolved_seed: int) -> uuid.UUID:
    """Derive the deterministic UUIDv5 ``run_id`` for plan-only mode.

    Args:
        scenario_content_hash: Hex digest of the scenario YAML bytes
            (sha256 recommended; this function does not enforce the algorithm).
        resolved_seed: Concrete integer seed for the run.

    Returns:
        UUIDv5 under ``CHAOS_LIBRARIAN_NAMESPACE_UUID``.
    """
    return uuid.uuid5(CHAOS_LIBRARIAN_NAMESPACE_UUID, f"{scenario_content_hash}:{resolved_seed}")


class _TraceBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stream: str
    value: str


class RngTraceEntry(_TraceBase):
    """Trace entry for an RNG draw. No ``exit_code``."""

    kind: Literal[ExecutionTraceKind.RNG]


class AllocTraceEntry(_TraceBase):
    """Trace entry for an identifier/seed allocation. No ``exit_code``."""

    kind: Literal[ExecutionTraceKind.ALLOC]


class MaterializerTraceEntry(_TraceBase):
    """Trace entry for a materializer subprocess. ``exit_code`` is required."""

    kind: Literal[ExecutionTraceKind.MATERIALIZER]
    exit_code: int


ExecutionTraceEntry = Annotated[
    RngTraceEntry | AllocTraceEntry | MaterializerTraceEntry,
    Field(discriminator="kind"),
]


class _ReplayBundleBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    chaos_librarian_version: str
    scenario: str  # verbatim YAML
    run_id: uuid.UUID
    resolved_seed: int
    execution_trace: list[ExecutionTraceEntry] = Field(default_factory=list)


class PlanOnlyReplayBundle(_ReplayBundleBase):
    """Replay bundle in plan-only mode. No ``created_at`` or ``toolchain``."""

    execution_mode: Literal[ExecutionMode.PLAN_ONLY] = ExecutionMode.PLAN_ONLY


class MaterializeReplayBundle(_ReplayBundleBase):
    """Replay bundle in materialize or run mode.

    ``created_at`` and ``toolchain`` are both required (non-null).
    """

    execution_mode: Literal[ExecutionMode.MATERIALIZE, ExecutionMode.RUN]
    created_at: datetime
    toolchain: dict[str, str]


ReplayBundle = Annotated[
    PlanOnlyReplayBundle | MaterializeReplayBundle,
    Field(discriminator="execution_mode"),
]
