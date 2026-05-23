# Issue #71 Performance Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the performance-profile design policy so future larger
profiles have explicit size, fixture, capability, and CI limits.

**Architecture:** Keep this as a docs-and-doc-tests change. The design spec
captures the detailed future contract, the source design document gains the
canonical policy, consumer/developer docs summarize the CI rules, and docs tests
guard the policy from disappearing. Do not add scenario profile enum values,
fixtures, generator code, or workflow jobs.

**Tech Stack:** Markdown docs, pytest docs smoke tests, Python 3.13 test runner.

---

## Source Inputs

- GitHub issue: [#71](https://github.com/randomparity/chaos-librarian/issues/71)
- Design spec:
  `docs/superpowers/specs/2026-05-23-issue-71-performance-profiles-design.md`
- Source design:
  `docs/specs/chaos-librarian-design.md`
- Existing CI guidance:
  `docs/contract/integration-recipes.md`
- Existing developer testing guide:
  `docs/developer/testing.md`

## File Structure

Create:

```text
docs/superpowers/specs/2026-05-23-issue-71-performance-profiles-design.md
docs/superpowers/plans/2026-05-23-issue-71-performance-profiles.md
```

Modify:

```text
docs/specs/chaos-librarian-design.md
docs/contract/integration-recipes.md
docs/developer/testing.md
tests/docs/test_documentation.py
```

## Task 1: Source Design Policy

**Files:**

- Modify: `docs/specs/chaos-librarian-design.md`

- [x] **Step 1: Add a performance-profile policy after Media Diversity Goals**

Insert a new `## Performance Profile Policy` section immediately before
`## Mutation Model`. The section must include:

```markdown
Future larger performance profiles are reserved for opt-in scenarios. The
current contract still rejects unknown `profiles` values until a profile
implementation explicitly adds them.

Reserved labels:

- `performance-smoke`
- `performance-scale`
- `performance-stress`
```

Then include one table with the exact budget ceilings from the design spec:
assets, works, variants, bundles, sidecars, timeline events, materialized bytes,
wall-clock duration, and minimum free disk. State that MB and GB budgets use
decimal units.

- [x] **Step 2: Add capability and CI rules**

In the same section, add short subsections for capability skips and CI tiers.
They must state that missing `ffmpeg`, missing `ffprobe`, unavailable future
providers, and unselected CI tiers are the only allowed skip classes, while disk
capacity is an infrastructure precondition that must fail during setup.

- [x] **Step 3: Tie Sprint 10 back to the policy**

Change the Sprint 10 deliverable bullet from:

```markdown
- Larger performance profiles
```

to:

```markdown
- Larger performance profiles that satisfy the Performance Profile Policy
```

## Task 2: Consumer And Developer Guidance

**Files:**

- Modify: `docs/contract/integration-recipes.md`
- Modify: `docs/developer/testing.md`

- [x] **Step 1: Expand contract CI guidance**

Replace the current two-paragraph `## CI Guidance` section in
`docs/contract/integration-recipes.md` with a table for Fast, Extended, and
Stress tiers. The text must make clear that Fast CI runs no performance profiles
by default, Extended may run `performance-smoke` and `performance-scale`, and
Stress is manual for `performance-stress`.

- [x] **Step 2: Add developer testing policy**

Add a short `## Performance Profile Testing` section to
`docs/developer/testing.md`. It must point to
`docs/specs/chaos-librarian-design.md` as the budget source of truth and state
that profile changes must keep visible pytest skips for missing capabilities.

## Task 3: Documentation Regression Tests

**Files:**

- Modify: `tests/docs/test_documentation.py`

- [x] **Step 1: Add policy assertions**

Add `test_performance_profile_policy_docs_are_discoverable` with checks for the
contract CI guidance:

```python
assert "performance-smoke" in integration_recipes
assert "performance-scale" in integration_recipes
assert "performance-stress" in integration_recipes
assert "No performance profiles by default" in integration_recipes
```

Add the developer testing assertion to the same focused test:

```python
assert "Performance Profile Policy" in testing
```

- [x] **Step 2: Add source design assertions**

Read `source_design = _read(DOCS / "specs" / "chaos-librarian-design.md")` in
`test_performance_profile_policy_docs_are_discoverable`, then assert:

```python
assert "## Performance Profile Policy" in source_design
assert "Minimum free disk before run" in source_design
assert "Larger performance profiles that satisfy the Performance Profile Policy" in source_design
```

## Task 4: Verification

**Files:**

- No additional files.

- [x] **Step 1: Run docs tests**

Run:

```bash
uv run pytest tests/docs -q --no-cov
```

Expected: all docs tests pass.

- [x] **Step 2: Run format check**

Run:

```bash
uv run ruff format --check tests/docs/test_documentation.py
```

Expected: ruff reports the file would be left unchanged.

- [x] **Step 3: Run lint on edited Python test**

Run:

```bash
uv run ruff check tests/docs/test_documentation.py
```

Expected: no lint findings.
