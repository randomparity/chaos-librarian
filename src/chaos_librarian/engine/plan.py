"""Plan-only orchestrator.

``run_plan`` walks a validated scenario, emits a journal + manifests +
replay bundle, and returns them as ``PlanArtifacts``. Persistence is
delegated to ``chaos_librarian.engine.writer.write_fixture``.
"""

from __future__ import annotations

from dataclasses import dataclass

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.validation import ValidationReport


@dataclass(frozen=True)
class PlanArtifacts:
    """In-memory result of a plan-only run, prior to persistence."""

    initial_manifest: Manifest
    current_manifest: Manifest
    journal: tuple[JournalEntry, ...]
    replay_bundle: PlanOnlyReplayBundle
    validation_report: ValidationReport
    sentinel: RunSentinel


def run_plan() -> PlanArtifacts:
    """Stub. Real implementation lands in Task 8."""
    raise NotImplementedError("run_plan ships in Task 8")
