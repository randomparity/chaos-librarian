"""Import-boundary tests for wall-clock finalization."""

from __future__ import annotations

import ast
from pathlib import Path

from chaos_librarian.materializer.runtime import wall_clock


def test_wall_clock_uses_persistence_finalize_boundary() -> None:
    """WHY: wall-clock execution should not rebuild persistence metadata inline."""
    source = Path(wall_clock.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    forbidden = {
        "build_metadata",
        "build_report",
        "build_reports",
        "cleanup_failed_phase_b_run",
        "finalize_materialize_run",
        "phase_b_failure_outcome",
        "phase_b_failure_record",
    }
    imports = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    assert forbidden.isdisjoint(imports)
