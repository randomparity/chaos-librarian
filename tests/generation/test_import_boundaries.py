"""Import boundary tests for generation internals."""

from __future__ import annotations

import ast
from pathlib import Path


def test_generation_does_not_import_validation_leaf_rules() -> None:
    generation_root = Path(__file__).resolve().parents[2] / "src" / "chaos_librarian" / "generation"
    offenders: list[str] = []
    for path in sorted(generation_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if node.module.startswith("chaos_librarian.validation.rules"):
                offenders.append(str(path.relative_to(generation_root.parents[1])))

    assert offenders == []
