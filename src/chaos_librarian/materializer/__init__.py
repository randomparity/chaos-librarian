"""Materializer package — synthesis, subprocess wrappers, run orchestrator.

Public re-exports.
"""

from __future__ import annotations

from chaos_librarian.materializer.errors import (
    CapabilityGateError,
    ContainmentViolationError,
    CorruptionActionError,
    FilesystemActionError,
    MaterializationError,
    MaterializationWriteError,
    MediaActionError,
    ProbeParseError,
    ScenarioValidationError,
    TimelineUnsupportedError,
    ToolFailedError,
    UnsupportedMaterializationError,
)
from chaos_librarian.materializer.run import (
    MaterializeArtifacts,
    materialize_scenario,
)
from chaos_librarian.materializer.runtime.wall_clock import (
    WallClockUsageError,
    run_wall_clock_scenario,
)
from chaos_librarian.materializer.tooling.capabilities import (
    assert_capable_for_static_materialize,
    detect_capabilities,
)

__all__ = [
    "CapabilityGateError",
    "ContainmentViolationError",
    "CorruptionActionError",
    "FilesystemActionError",
    "MaterializationError",
    "MaterializationWriteError",
    "MaterializeArtifacts",
    "MediaActionError",
    "ProbeParseError",
    "ScenarioValidationError",
    "TimelineUnsupportedError",
    "ToolFailedError",
    "UnsupportedMaterializationError",
    "WallClockUsageError",
    "assert_capable_for_static_materialize",
    "detect_capabilities",
    "materialize_scenario",
    "run_wall_clock_scenario",
]
