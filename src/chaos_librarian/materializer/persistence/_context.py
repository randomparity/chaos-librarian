"""Per-run dataclasses shared by ``run.py``, ``finalize.py``, and the package.

Lives in its own module so ``finalize.py`` can import ``RunContext`` without
re-introducing the ``run.py → finalize.py → run.py`` cycle that would
otherwise form when the orchestrator and the finalize helpers depend on
each other.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from chaos_librarian.contract.capabilities import Capabilities
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.materialization import (
    CorruptionAction,
    FilesystemAction,
    MaterializationReport,
    MediaAction,
    NetworkFsChaosAction,
    NetworkLagAction,
    OracleHashAction,
)
from chaos_librarian.contract.replay_bundle import MaterializeReplayBundle
from chaos_librarian.engine.plan import PlanArtifacts
from chaos_librarian.validation import RunInput

__all__ = ["MaterializeArtifacts", "ReportActions", "RunContext"]


@dataclass(frozen=True, slots=True)
class MaterializeArtifacts:
    """Return value of ``materialize_scenario``."""

    current_manifest: Manifest
    materialization_report: MaterializationReport
    replay_bundle: MaterializeReplayBundle


@dataclass(frozen=True, slots=True)
class ReportActions:
    """Phase-B action families recorded into ``MaterializationReport``."""

    filesystem: list[FilesystemAction] = field(default_factory=list)
    media: list[MediaAction] = field(default_factory=list)
    corruption: list[CorruptionAction] = field(default_factory=list)
    oracle_hash: list[OracleHashAction] = field(default_factory=list)
    network_lag: list[NetworkLagAction] = field(default_factory=list)
    network_fs_chaos: list[NetworkFsChaosAction] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RunContext:
    """Per-run invariants set once at the top of ``materialize_scenario``.

    Threaded through synthesis/finalize/cleanup so each helper depends
    on a single immutable object instead of repeating the same 7-9
    kwargs (issue #12). The validation report lives on
    ``plan_artifacts.validation_report`` — no separate field here.
    """

    run_input: RunInput
    out_dir: Path
    run_id: uuid.UUID
    started_at: datetime
    caps: Capabilities
    plan_artifacts: PlanArtifacts
