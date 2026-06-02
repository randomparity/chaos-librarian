"""Plan-only engine — public surface.

Downstream callers (CLI, tests) import from this package; the submodules
are implementation detail.
"""

from __future__ import annotations

from chaos_librarian.engine.diff import (
    FixtureDiff,
    FixtureFileDiff,
    compare_fixtures,
    compare_run_replay,
)
from chaos_librarian.engine.plan import (
    PlanArtifacts,
    ReplayIntegrityError,
    replay_plan_bundle,
    run_plan,
)
from chaos_librarian.engine.reports import ReportSet, build_report_set
from chaos_librarian.engine.resolution import resolve_timeline, step_boundaries
from chaos_librarian.engine.step import (
    JournalCorruptError,
    ScenarioTamperedError,
    SentinelInvalidError,
    StepResult,
    step_fixture,
    verify_sentinel,
)
from chaos_librarian.engine.writer import append_step, write_fixture

__all__ = [
    "FixtureDiff",
    "FixtureFileDiff",
    "JournalCorruptError",
    "PlanArtifacts",
    "ReplayIntegrityError",
    "ReportSet",
    "ScenarioTamperedError",
    "SentinelInvalidError",
    "StepResult",
    "append_step",
    "build_report_set",
    "compare_fixtures",
    "compare_run_replay",
    "replay_plan_bundle",
    "resolve_timeline",
    "run_plan",
    "step_boundaries",
    "step_fixture",
    "verify_sentinel",
    "write_fixture",
]
