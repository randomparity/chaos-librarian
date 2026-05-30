"""Corpus guard for the pre-built scenario recipe library.

WHY: recipes are user-facing scenarios shipped in the repo. They must stay valid
as the scenario schema and validation pipeline evolve. This module re-validates
every recipe in CI and enforces the per-category floor from issue #108, so a
schema change that breaks a recipe — or a dropped category — turns CI red.

When ``SCENARIO_SCHEMA_VERSION`` is bumped, every recipe's ``schema_version``
literal stops validating and ``test_recipe_validates_clean`` goes red for the
whole corpus at once. That is intentional (see
``docs/adr/0002-recipe-library-location-and-bitrot-guard.md``): update each
recipe to the new version and re-confirm it still expresses a valid scenario.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.validation import prepare_run_input, run_validation

RECIPES_DIR = Path(__file__).resolve().parents[2] / "recipes"
CATEGORIES = ("scanner", "watcher", "identity", "metadata", "sidecar", "archive")
MIN_PER_CATEGORY = 3


def _recipe_files() -> list[Path]:
    return sorted(RECIPES_DIR.rglob("*.yaml"))


def _discovered_categories() -> list[str]:
    return sorted(p.name for p in RECIPES_DIR.iterdir() if p.is_dir())


def _floored_categories() -> list[str]:
    """Every expected category plus any added on disk.

    Union so a *new* category directory cannot be shipped below the floor, and a
    *dropped* expected category fails (its glob returns nothing).
    """
    return sorted(set(CATEGORIES) | set(_discovered_categories()))


def test_recipes_directory_is_populated() -> None:
    """At least one recipe exists (guards against a renamed/empty tree)."""
    assert _recipe_files(), f"no recipes discovered under {RECIPES_DIR}"


@pytest.mark.parametrize("category", _floored_categories())
def test_category_has_minimum_recipes(category: str) -> None:
    """Each category ships at least ``MIN_PER_CATEGORY`` recipes."""
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
