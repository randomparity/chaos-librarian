"""Structural invariant: semantic rule modules cannot import sibling rules.

WHY: Rule modules depend on each other only through ``semantic.py``'s
``_RULES`` registry — never through direct ``from
chaos_librarian.validation.rules.<other_rule> import …`` edges.
Cross-cutting validation helpers live in the shared helper modules listed in
``tests.validation.rule_modules.SHARED_HELPER_MODULES``.

``test_rule_import_isolation.py`` proves every rule package module imports
cleanly from the pipeline entrypoint. This test proves the orthogonal
invariant: no rule module imports from a sibling semantic rule module.
Together they lock the structural goal of the #22 split: semantic rule
files are siblings, and shared helpers are the only intra-subpackage import
targets.
"""

from __future__ import annotations

import ast

import pytest

from tests.validation.rule_modules import RULE_MODULES as _RULE_MODULES
from tests.validation.rule_modules import RULES_DIR as _RULES_DIR

_RULES_PACKAGE_PREFIX = "chaos_librarian.validation.rules."
_SIBLING_PREFIXES: frozenset[str] = frozenset(
    f"{_RULES_PACKAGE_PREFIX}{name}" for name in _RULE_MODULES
)


@pytest.mark.parametrize("module_name", _RULE_MODULES)
def test_rule_module_does_not_import_from_sibling(module_name: str) -> None:
    """No ``rules/<rule>.py`` may import from another ``rules/<sibling>.py``.

    Catches both Python import forms:

    - ``from chaos_librarian.validation.rules.<sibling> import X`` (``ast.ImportFrom``)
    - ``import chaos_librarian.validation.rules.<sibling>`` (``ast.Import``)

    Aliased forms (``... as foo``) are caught too because the AST's
    ``module``/``names[*].name`` fields carry the original module path.
    """
    source = (_RULES_DIR / f"{module_name}.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename=f"{module_name}.py")

    offenders: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module is not None and node.module in _SIBLING_PREFIXES:
                offenders.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in _SIBLING_PREFIXES:
                    offenders.append((node.lineno, alias.name))

    assert not offenders, (
        f"{module_name}.py imports from sibling rule module(s) "
        f"(cross-cutting helpers must live in shared helper modules): {offenders!r}"
    )
