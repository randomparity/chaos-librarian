"""Structural invariant: ``validation/rules/<rule>.py`` cannot import from
a sibling rule module. Cross-cutting helpers must live in ``_common``.

WHY: After #27 lifted the cross-rule helpers (``iter_asset_ids``,
``iter_global_namespaces``, ``iter_assets_with_loc``, ``try_parse_duration``,
and the ``NS_*`` namespace constants) into ``validation/rules/_common.py``,
the rule modules depend on each other only through ``semantic.py``'s
``_RULES`` registry — never through direct
``from chaos_librarian.validation.rules.<other_rule> import …`` edges.

``test_rule_import_isolation.py`` proves no rule module drags
``IssueCollector`` into the ``pipeline → semantic → rules`` chain. This
test proves the orthogonal invariant: no rule module imports from a
sibling rule module. Together they lock the structural goal of the #22
split: rule files are siblings, and ``_common`` is the only intra-
subpackage import target.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_RULES_DIR = _REPO_ROOT / "src" / "chaos_librarian" / "validation" / "rules"

# Sibling rule modules — every ``rules/`` file that defines an ``E_*`` rule.
# Keep alphabetized; mirrors ``test_rule_import_isolation.RULE_MODULES``.
_RULE_MODULES: tuple[str, ...] = (
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
)

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
        f"(cross-cutting helpers must live in _common): {offenders!r}"
    )
