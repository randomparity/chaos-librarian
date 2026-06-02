"""Import-boundary tests for the plan-engine event dispatcher."""

from __future__ import annotations

import ast
from pathlib import Path


def test_engine_events_keeps_handler_implementations_in_family_modules() -> None:
    events_path = Path("src/chaos_librarian/engine/events.py")
    tree = ast.parse(events_path.read_text(encoding="utf-8"))
    handler_defs = [
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_handle_")
    ]

    assert handler_defs == []
