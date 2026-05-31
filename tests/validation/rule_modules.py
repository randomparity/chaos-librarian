"""Source of truth: which modules under ``validation/rules/`` are rules.

The structural-invariant tests share this discovery logic:

- ``test_rule_import_isolation.py`` — every rule-package module imports
  cleanly from the pipeline entrypoint.
- ``test_rule_no_cross_imports.py`` — semantic rule modules may import shared
  helper modules, but may not import sibling semantic rule modules.

Before #31 both tests hardcoded the same 10-element tuple. A new rule that
updated one list but not the other would have been silently exempt from one
of the two invariants — exactly the kind of mechanical guard those tests are
meant to be. This module keeps the dynamic discovery pass, with an explicit
shared-helper allowlist for modules that are not semantic rules.

The rule invariant covered is intentionally a **predicate**, not an
enumeration: "every non-underscore ``.py`` file under ``validation/rules/``
unless it is one of the shared helper modules." Adding a new rule needs zero
edits here; adding a new shared helper is an architectural change and must
name the helper here.
"""

from __future__ import annotations

from pathlib import Path

RULES_DIR = Path(__file__).resolve().parents[2] / "src" / "chaos_librarian" / "validation" / "rules"

SHARED_HELPER_MODULES: frozenset[str] = frozenset(
    {
        "hierarchy_projection",
        "hierarchy_walkers",
        "raw_helpers",
        "sidecar_projection",
    }
)

RULE_MODULES: tuple[str, ...] = tuple(
    sorted(
        p.stem
        for p in RULES_DIR.glob("*.py")
        if not p.stem.startswith("_") and p.stem not in SHARED_HELPER_MODULES
    )
)

RULE_PACKAGE_MODULES: tuple[str, ...] = tuple(
    sorted(p.stem for p in RULES_DIR.glob("*.py") if not p.stem.startswith("_"))
)

assert RULE_MODULES, (
    f"No rule modules discovered under {RULES_DIR}; "
    f"check tests/validation/rule_modules.py filter (expected non-underscore *.py files)"
)
