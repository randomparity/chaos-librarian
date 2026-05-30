"""Every shipped recipe under ``recipes/`` must validate clean.

WHY: the recipe library is only useful if every file is a runnable scenario.
This corpus test is the bit-rot guard — when the scenario schema or validation
pipeline changes, a recipe that stops validating turns CI red with the offending
file and its issue codes, exactly as ``chaos-librarian validate`` would. It is
the enforcement behind issue #108's "all recipes pass validate in CI" and
"updated when schema changes" acceptance criteria. Because every recipe pins
``schema_version: 23`` (a ``Literal`` on the model), the next version bump fails
this test on its own, forcing a deliberate recipe update.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.validation import prepare_run_input, run_validation

RECIPES_DIR = Path(__file__).resolve().parents[2] / "recipes"

# The six failure-pattern categories from issue #108. Each must ship at least
# MIN_PER_CATEGORY recipes; the count assertion makes that floor a tested
# contract rather than a documented hope.
CATEGORIES = ("scanner", "watcher", "identity", "metadata", "sidecar", "archive")
MIN_PER_CATEGORY = 3


def _recipe_files() -> list[Path]:
    return sorted(RECIPES_DIR.rglob("*.yaml"))


def test_recipes_directory_is_populated() -> None:
    """Discovery must find recipes — guards against a silent pass.

    WHY: a parametrized validate test over an empty file list would collect zero
    cases and report success. This explicit non-empty assertion makes an empty
    or mis-resolved ``recipes/`` a hard failure instead.
    """
    assert _recipe_files(), f"no recipes discovered under {RECIPES_DIR}"


@pytest.mark.parametrize("category", CATEGORIES)
def test_category_has_minimum_recipes(category: str) -> None:
    """Each category ships at least MIN_PER_CATEGORY recipes (issue #108 floor)."""
    files = sorted((RECIPES_DIR / category).glob("*.yaml"))
    assert len(files) >= MIN_PER_CATEGORY, (
        f"category {category!r} has {len(files)} recipes, need >= {MIN_PER_CATEGORY}"
    )


@pytest.mark.parametrize(
    "path",
    _recipe_files(),
    ids=lambda p: str(p.relative_to(RECIPES_DIR)),
)
def test_recipe_validates_clean(path: Path) -> None:
    """Each recipe passes ``validate`` with no issues (the bit-rot guard).

    WHY: this is the same entrypoint the ``validate`` CLI runs. If a shipped
    recipe stops validating, either it drifted from the schema or a new rule has
    a false positive — either way the change that broke it must be reconsidered.
    """
    report = run_validation(prepare_run_input(path))
    assert report.ok is True, (
        f"{path}: expected ok=True, got issues {[i.code for i in report.issues]}"
    )
    assert report.issues == []
