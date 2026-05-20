"""Source of truth: which modules live under ``validation/rules/``.

Two sibling structural-invariant tests parametrize over the same set of
rule modules:

- ``test_rule_import_isolation.py`` — each module imports without dragging
  ``IssueCollector`` into the ``pipeline → semantic → rules`` cycle.
- ``test_rule_no_cross_imports.py`` — no rule module imports from a sibling
  rule module (cross-cutting helpers must live in ``_common``).

Before #31 both tests hardcoded the same 10-element tuple. A new rule that
updated one list but not the other would have been silently exempt from
one of the two invariants — exactly the kind of mechanical guard those
tests are meant to be. This module replaces both hardcoded tuples with a
single dynamic discovery pass.

The invariant covered is intentionally a **predicate**, not an enumeration:
"every non-underscore ``.py`` file under ``validation/rules/``." Adding a
new rule needs zero edits here; the only way to be silently exempt is to
underscore-prefix the filename (the project convention reserved for
``_common.py`` and ``__init__.py``). A future engineer naming an
experimental file ``draft_rule.py`` will see it picked up automatically.
"""

from __future__ import annotations

from pathlib import Path

RULES_DIR = Path(__file__).resolve().parents[2] / "src" / "chaos_librarian" / "validation" / "rules"

RULE_MODULES: tuple[str, ...] = tuple(
    sorted(p.stem for p in RULES_DIR.glob("*.py") if not p.stem.startswith("_"))
)

assert RULE_MODULES, (
    f"No rule modules discovered under {RULES_DIR}; "
    f"check tests/validation/rule_modules.py filter (expected non-underscore *.py files)"
)
