"""Materializer package — synthesis, subprocess wrappers, run orchestrator.

Public re-exports.
"""

from __future__ import annotations

from chaos_librarian.materializer.capabilities import (
    assert_capable_for_static_materialize,
    detect_capabilities,
)
from chaos_librarian.materializer.errors import (
    CapabilityGateError,
    ContainmentViolationError,
    FilesystemActionError,
    MaterializationError,
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

__all__ = [
    "CapabilityGateError",
    "ContainmentViolationError",
    "FilesystemActionError",
    "MaterializationError",
    "MaterializeArtifacts",
    "MediaActionError",
    "ProbeParseError",
    "ScenarioValidationError",
    "TimelineUnsupportedError",
    "ToolFailedError",
    "UnsupportedMaterializationError",
    "assert_capable_for_static_materialize",
    "detect_capabilities",
    "materialize_scenario",
]
