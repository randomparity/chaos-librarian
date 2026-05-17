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

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from chaos_librarian.contract import CHAOS_LIBRARIAN_NAMESPACE_UUID


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


class ExecutionTraceEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["rng", "alloc", "materializer"]
    stream: str
    value: str
    exit_code: int | None = None  # only set on `materializer` entries


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

    execution_mode: Literal["plan_only"] = "plan_only"


class MaterializeReplayBundle(_ReplayBundleBase):
    """Replay bundle in materialize or run mode.

    ``created_at`` and ``toolchain`` are both required (non-null).
    """

    execution_mode: Literal["materialize", "run"]
    created_at: datetime
    toolchain: dict[str, str]


ReplayBundle = Annotated[
    PlanOnlyReplayBundle | MaterializeReplayBundle,
    Field(discriminator="execution_mode"),
]
