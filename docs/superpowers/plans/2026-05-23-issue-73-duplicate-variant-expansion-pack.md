# Issue 73 Duplicate Variant Expansion Pack Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the issue #73 duplicate/variant expansion pack without changing
the existing first-pack `duplicate-variant.yaml` fixture.

**Architecture:** The pack is a source scenario fixture plus contract docs and
focused adapter tests. No schema, engine, or adapter matching semantics change;
the existing oracle manifest, reports, and adapter indexes already expose the
needed path, hash, and topology evidence.

**Tech Stack:** Python 3.13, Pydantic v2 contracts, Typer CLI, pytest, existing
Chaos Librarian plan/materialize/adapter modules.

---

## Files

- Create: `tests/fixtures/scenarios/duplicate-variant-expanded.yaml`
- Create: `tests/contract/test_duplicate_variant_expansion_pack.py`
- Modify: `docs/specs/chaos-librarian-design.md`
- Modify: `docs/contract/integration-recipes.md`
- Modify: `tests/docs/test_documentation.py`

## Task 1: Pin The Desired Pack Behavior

- [ ] **Step 1: Add a failing contract test**

Create `tests/contract/test_duplicate_variant_expansion_pack.py` with tests
that load `duplicate-variant-expanded.yaml`, assert the three intended works,
and run `preflight_asset` on every asset so the pack remains materializer
compatible.

- [ ] **Step 2: Verify the test fails before the fixture exists**

Run:

```bash
uv run pytest tests/contract/test_duplicate_variant_expansion_pack.py -q --no-cov
```

Expected: fail with `FileNotFoundError` for
`tests/fixtures/scenarios/duplicate-variant-expanded.yaml`.

## Task 2: Add The Expansion Fixture

- [ ] **Step 1: Create the source scenario**

Create `tests/fixtures/scenarios/duplicate-variant-expanded.yaml` with:

- `Synthetic Echo`: two same-label `hd` variants with identical recipes, plus
  one `sd` control variant.
- `Synthetic Pair`: one `hd` bundle containing two identical primary-video
  assets.
- `Synthetic Ladder`: distinct `1080p` and `sd` variants with supported
  materializer recipes.

- [ ] **Step 2: Run the pack tests**

Run:

```bash
uv run pytest tests/contract/test_duplicate_variant_expansion_pack.py -q --no-cov
```

Expected: all tests pass. The topology-only recipe test must report
`D_MATCH_AMBIGUOUS` for `Synthetic Echo|hd|1` and `Synthetic Pair|hd|2`.

## Task 3: Document Adapter Recipes

- [ ] **Step 1: Update source design**

Update the `Duplicate/Variant` section in
`docs/specs/chaos-librarian-design.md` to point at
`duplicate-variant-expanded.yaml` and describe the expected path, hash, and
topology evidence.

- [ ] **Step 2: Update contract recipes**

Add `Duplicate And Variant Pack` to `docs/contract/integration-recipes.md`.
State that scanner exports should include `current_path`, prober exports should
add `content_hash` and `probed`, and topology-only exports are intentionally
ambiguous for the duplicate cases.

- [ ] **Step 3: Add docs smoke coverage**

Extend `tests/docs/test_documentation.py` to assert the new fixture and recipe
section are discoverable.

- [ ] **Step 4: Run docs smoke coverage**

Run:

```bash
uv run pytest tests/docs/test_documentation.py::test_duplicate_variant_expansion_pack_docs_are_discoverable -q --no-cov
```

Expected: pass.

## Task 4: Verification

- [ ] **Step 1: Run focused behavior tests**

Run:

```bash
uv run pytest tests/contract/test_duplicate_variant_expansion_pack.py -q --no-cov
uv run pytest tests/contract/test_sample_scenarios.py -q --no-cov
uv run pytest tests/docs/test_documentation.py -q --no-cov
```

Expected: all pass.

- [ ] **Step 2: Run static checks**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Expected: every command exits `0` with no warnings.
