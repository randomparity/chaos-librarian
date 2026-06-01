"""Import boundary tests for materializer internals."""

from __future__ import annotations

import ast
from pathlib import Path


def test_materializer_internals_import_engine_plan_directly() -> None:
    materializer_root = (
        Path(__file__).resolve().parents[2] / "src" / "chaos_librarian" / "materializer"
    )
    offenders: list[str] = []
    for path in sorted(materializer_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "chaos_librarian.engine":
                offenders.append(str(path.relative_to(materializer_root.parents[1])))

    assert offenders == []


def test_phase_a_content_does_not_import_phase_b_effects() -> None:
    materializer_root = (
        Path(__file__).resolve().parents[2] / "src" / "chaos_librarian" / "materializer"
    )
    content_root = materializer_root / "content"
    offenders: list[str] = []
    for path in sorted(content_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and node.module.startswith("chaos_librarian.materializer.phase_b")
            ):
                offenders.append(str(path.relative_to(materializer_root.parents[1])))

    assert offenders == []
