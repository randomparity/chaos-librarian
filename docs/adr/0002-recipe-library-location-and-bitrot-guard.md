# 0002 — Recipe library location and bit-rot guard

> Status: Accepted

## Context

Issue #108 ships a curated library of ready-to-run scenario recipes so new users
get value without authoring scenarios from scratch. Two decisions shape how the
recipes live in the repo: **where** they sit, and **how** they are kept valid as
the scenario schema and validation pipeline evolve.

The repo already has a fixture corpus at `tests/fixtures/scenarios/` whose valid
files are required to validate clean (`tests/validation/test_invalid_corpus.py`
asserts `report.ok` for each; `tests/contract/test_sample_scenarios.py` loads
each with a non-recursive `glob`). Recipes are a different audience — end users,
not the test suite — and are grouped into category subdirectories.

## Decision

1. Recipes live at the repo root in `recipes/<category>/<name>.yaml`, with a
   `recipes/README.md` index. This is a user-facing, discoverable location,
   matching the issue's stated layout.
2. A dedicated test, `tests/recipes/test_recipe_corpus.py`, discovers recipes
   recursively (`rglob`) under the repo-root `recipes/`, and for each asserts it
   validates clean via the public validation API —
   `run_validation(prepare_run_input(path))` with `report.ok is True` and
   `report.issues == []` (the same entrypoint the `validate` CLI uses). The test
   also asserts non-empty discovery and the per-category ≥3 floor.
3. Version currency is enforced *through* the validate-clean guard rather than a
   separate assertion. Recipes pin `schema_version: 23`; because the model field
   is `Literal[23]`, the next `SCENARIO_SCHEMA_VERSION` bump makes every recipe
   fail validation, turning the corpus test red and forcing a deliberate update.

## Consequences

- Recipes are guarded against silent rot: a schema or validation change that
  breaks a recipe turns CI red with the offending file and its issue codes.
- "Update recipes when the schema changes" is enforced automatically by the
  `Literal` schema-version mismatch — no second assertion, no per-file
  equality-pin churn beyond the version bump every fixture already takes.
- The recipes are pure YAML; no Pydantic model or `schemas/*.json` artifact
  changes, so the schema drift gate is unaffected.
- A new top-level `recipes/` directory is part of the repo's public surface;
  renames/removals later are user-visible.

## Considered & rejected

- **Put recipes under `tests/fixtures/scenarios/`.** Rejected: that corpus is a
  test artifact, not a user-facing library, and its loader uses non-recursive
  `glob`. Co-locating user recipes there muddies the test corpus and hides them
  from users.
- **Validate recipes with a CI shell loop calling `chaos-librarian validate`.**
  Rejected: a pytest corpus test is consistent with the existing fixture tests,
  runs in the same `uv run pytest` job, gives per-file IDs and issue codes on
  failure, and tests the validation function directly rather than spawning
  subprocesses.
- **Add an explicit `schema_version == SCENARIO_SCHEMA_VERSION` assertion.**
  Rejected: redundant. The `Literal[23]` field already fails validation on a
  stale version, so the validate-clean guard covers currency; a second assertion
  only adds a parallel failure mode replicated across ~19 files.
- **Do not pin the schema version at all.** Rejected: recipes must declare a
  concrete `schema_version` to parse, and pinning to the current value is what
  makes the bump-time forcing function work.
- **Generate recipes programmatically via `generate`.** Rejected: recipes are
  hand-curated, human-readable teaching examples; generated output is neither
  curated nor self-documenting.
