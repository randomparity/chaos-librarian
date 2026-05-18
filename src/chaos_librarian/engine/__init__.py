"""Sprint 3 plan-only engine — public surface.

Downstream callers (CLI, tests) import from this package; the submodules
are implementation detail.
"""

from __future__ import annotations

from chaos_librarian.engine.plan import (
    PlanArtifacts,
    ReplayIntegrityError,
    replay_plan_bundle,
    run_plan,
)
from chaos_librarian.engine.reports import ReportSet, build_report_set
from chaos_librarian.engine.step import (
    JournalCorruptError,
    ScenarioTamperedError,
    SentinelInvalidError,
    StepResult,
    step_fixture,
)

__all__ = [
    "JournalCorruptError",
    "PlanArtifacts",
    "ReplayIntegrityError",
    "ReportSet",
    "ScenarioTamperedError",
    "SentinelInvalidError",
    "StepResult",
    "build_report_set",
    "replay_plan_bundle",
    "run_plan",
    "step_fixture",
]
