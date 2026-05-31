"""Smoke test: every validation rule package module imports cleanly.

WHY: validation rules are leaf modules. The pipeline imports semantic.py,
which imports the rule registry, so rule modules must keep their runtime
dependencies limited to shared helpers and neutral contracts. This catches
new module-scope dependencies that would cycle during package initialization.
"""

from __future__ import annotations

import importlib

import pytest

from tests.validation.rule_modules import RULE_PACKAGE_MODULES


@pytest.mark.parametrize("module_name", RULE_PACKAGE_MODULES)
def test_rule_module_imports_without_pipeline(module_name: str) -> None:
    """Each rule module must import cleanly without triggering the cycle."""
    importlib.import_module(f"chaos_librarian.validation.rules.{module_name}")
