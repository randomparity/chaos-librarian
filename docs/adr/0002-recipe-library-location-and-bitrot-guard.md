# 0002 — Recipe library location and bit-rot guard

> Status: Accepted

## Context

Issue #108 ships a curated library of ready-to-run scenario recipes so new users
get value without authoring scenarios from scratch. Two decisions shape how the
recipes live in the repo: **where** they sit, and **how** they are kept valid as
the scenario schema and validation pipeline evolve.

The repo already has a fixture corpus at `tests/fixtures/scenarios/` whose valid
files are required to validate clean (`tests/contract/test_sample_scenarios.py`,
non-recursive `glob`). Recipes are a different audience — end users, not the test
suite — and are grouped into category subdirectories.

## Decision

1. Recipes live at the repo root in `recipes/<category>/<name>.yaml`, with a
   `recipes/README.md` index. This is a user-facing, discoverable location,
   matching the issue's stated layout.
2. A dedicated test, `tests/recipes/test_recipe_corpus.py`, discovers recipes
   recursively (`rglob`), and for each asserts it parses, pins to the current
   `SCENARIO_SCHEMA_VERSION`, and validates clean via `validate_scenario_file`.
   The test also asserts non-empty discovery and the per-category ≥3 floor.
3. The schema-version pin is asserted (not merely present), so bumping
   `SCENARIO_SCHEMA_VERSION` without updating recipes fails CI.

## Consequences

- Recipes are guarded against silent rot: a schema or validation change that
  breaks a recipe turns CI red with the offending file and findings.
- The version pin converts "update recipes when the schema changes" from a
  documented hope into an enforced gate.
- The recipes are pure YAML; no Pydantic model or `schemas/*.json` artifact
  changes, so the schema drift gate is unaffected.
- A new top-level `recipes/` directory is part of the repo's public surface;
  renames/removals later are user-visible.

## Considered & rejected

- **Put recipes under `tests/fixtures/scenarios/`.** Rejected: that corpus is a
  test artifact ("add fixtures sparingly"), not a user-facing library, and its
  validating test uses non-recursive `glob`. Co-locating user recipes there
  muddies the test corpus and hides them from users.
- **Validate recipes with a CI shell loop calling `chaos-librarian validate`.**
  Rejected: a pytest corpus test is consistent with the existing fixture tests,
  runs in the same `uv run pytest` job, gives per-file IDs and findings on
  failure, and tests the handler directly rather than spawning subprocesses.
- **Do not pin/enforce schema version (rely on validate alone).** Rejected: a
  future schema that stays backward-compatible could let recipes drift to an old
  version unnoticed; the explicit pin assertion makes version currency a tested
  contract and satisfies the issue's "version-pinned and updated when schema
  changes" criterion.
- **Generate recipes programmatically via `generate`.** Rejected: recipes are
  hand-curated, human-readable teaching examples; generated output is neither
  curated nor self-documenting.
