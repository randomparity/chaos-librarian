"""Tests for chaos_librarian.engine.plan (skeleton first; behavior in Task 8)."""

from __future__ import annotations

from chaos_librarian.engine import PlanArtifacts


def test_plan_artifacts_is_importable() -> None:
    """The public surface exposes PlanArtifacts.

    WHY: downstream tasks construct PlanArtifacts; if the surface drifts,
    every later import in this sprint breaks at once.
    """
    assert PlanArtifacts is not None
