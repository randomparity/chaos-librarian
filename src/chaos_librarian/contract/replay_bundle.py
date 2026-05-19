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
from chaos_librarian.contract.materialization import ToolchainInfo


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

    # v4: scenario contract bumped to v3 (CreateSidecarEvent.language is
    # now required). The bundle's embedded ``scenario`` field carries a
    # scenario v3 YAML; replaying a v3 replay bundle against this code
    # would fail at re-validation. The version bump lets consumers detect
    # the incompatibility cleanly instead of running into the embedded
    # validation error later.
    schema_version: Literal[4]
    chaos_librarian_version: str
    scenario: str  # verbatim YAML
    run_id: uuid.UUID
    resolved_seed: int
    applied_events: int = Field(ge=0)
    journal_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_trace: list[ExecutionTraceEntry] = Field(default_factory=list)


class PlanOnlyReplayBundle(_ReplayBundleBase):
    """Replay bundle in plan-only mode. No ``created_at`` or ``toolchain``."""

    execution_mode: Literal[ExecutionMode.PLAN_ONLY] = ExecutionMode.PLAN_ONLY


class MaterializeReplayBundle(_ReplayBundleBase):
    """Replay bundle in materialize or run mode.

    ``applied_events`` is currently pinned to 0 because materialize only
    accepts empty timelines; the base class constraint will widen again
    when timeline-mutating materialize modes ship. ``created_at`` and
    ``toolchain`` are both required (non-null).
    """

    execution_mode: Literal[ExecutionMode.MATERIALIZE, ExecutionMode.RUN]
    applied_events: Literal[0] = 0
    created_at: datetime
    toolchain: ToolchainInfo


ReplayBundle = Annotated[
    PlanOnlyReplayBundle | MaterializeReplayBundle,
    Field(discriminator="execution_mode"),
]
