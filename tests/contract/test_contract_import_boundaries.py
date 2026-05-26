"""Import boundary tests for public contract modules."""

from __future__ import annotations

import ast
from pathlib import Path

CONTRACT_DIR = Path(__file__).resolve().parents[2] / "src" / "chaos_librarian" / "contract"


def test_contract_modules_do_not_import_runtime_topology_helpers() -> None:
    offenders: list[str] = []
    for path in sorted(CONTRACT_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "chaos_librarian.topology":
                        offenders.append(f"{path.name}:{node.lineno}")
            if isinstance(node, ast.ImportFrom):
                if node.module == "chaos_librarian.topology":
                    offenders.append(f"{path.name}:{node.lineno}")
                if node.module == "chaos_librarian":
                    for alias in node.names:
                        if alias.name == "topology":
                            offenders.append(f"{path.name}:{node.lineno}")

    assert offenders == []
