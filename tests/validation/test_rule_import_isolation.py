"""Smoke test: every rule module imports without pulling ``pipeline.IssueCollector``.

WHY: ``validation/pipeline.py`` imports ``run_semantic_pass`` from
``validation/semantic.py`` BEFORE ``IssueCollector`` is defined
(``pipeline.py:38`` precedes the dataclass at ``pipeline.py:42``). The
chain ``pipeline → semantic → rules/<rule>`` therefore cannot afford
any rule module to import ``IssueCollector`` at runtime — doing so
would cycle and raise ``ImportError`` during package initialization.

This test forces each rule module to be loaded in isolation. If a future
rule grows a runtime ``from chaos_librarian.validation.pipeline import
IssueCollector`` at module scope, the import fails here with a clear
``ImportError`` traceback pointing at the offending module — long before
a confused developer hits the same failure from `pytest --collect-only`.
"""

from __future__ import annotations

import importlib

import pytest

RULE_MODULES = [
    "asset_path_safety",
    "duration_syntax",
    "id_duplicate",
    "path_containment",
    "path_duplicate",
    "sidecar_language",
    "slow_copy",
    "target_unknown",
    "timeline_lifecycle",
    "timeline_order",
]


@pytest.mark.parametrize("module_name", RULE_MODULES)
def test_rule_module_imports_without_pipeline(module_name: str) -> None:
    """Each rule module must import cleanly without triggering the cycle."""
    importlib.import_module(f"chaos_librarian.validation.rules.{module_name}")
