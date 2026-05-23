# Issue #72 Network Filesystem Lag Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish the network filesystem lag profile design so future runtime
support has explicit scenario, wall-clock, replay, and watcher contracts.

**Architecture:** Keep this as a docs-and-doc-tests change. The issue design
spec captures the detailed future contract, the source design document gains
the canonical policy, consumer/developer docs summarize watcher-facing rules,
and docs tests guard the policy from disappearing. Do not add scenario profile
enum values, event models, fixtures, providers, or runtime code.

**Tech Stack:** Markdown docs, pytest docs smoke tests, Python 3.13 test runner.

---

## Source Inputs

- GitHub issue: [#72](https://github.com/randomparity/chaos-librarian/issues/72)
- Design spec:
  `docs/superpowers/specs/2026-05-23-issue-72-network-filesystem-lag-design.md`
- Source design:
  `docs/specs/chaos-librarian-design.md`
- Existing watcher guidance:
  `docs/contract/integration-recipes.md`
- Existing time contract:
  `docs/contract/time-model.md`
- Existing developer testing guide:
  `docs/developer/testing.md`

## File Structure

Create:

```text
docs/superpowers/specs/2026-05-23-issue-72-network-filesystem-lag-design.md
docs/superpowers/plans/2026-05-23-issue-72-network-filesystem-lag.md
```

Modify:

```text
docs/specs/chaos-librarian-design.md
docs/contract/integration-recipes.md
docs/contract/time-model.md
docs/developer/testing.md
tests/docs/test_documentation.py
```

## Task 1: Documentation Regression Test

**Files:**

- Modify: `tests/docs/test_documentation.py`

- [x] **Step 1: Add a failing discoverability test**

Add `test_network_filesystem_lag_profile_policy_docs_are_discoverable` after
`test_performance_profile_policy_docs_are_discoverable`:

```python
def test_network_filesystem_lag_profile_policy_docs_are_discoverable() -> None:
    source_design = _read(DOCS / "specs" / "chaos-librarian-design.md")
    integration_recipes = _read(DOCS / "contract" / "integration-recipes.md")
    time_model = _read(DOCS / "contract" / "time-model.md")
    testing = _read(DOCS / "developer" / "testing.md")

    assert "## Network Filesystem Lag Profile Policy" in source_design
    assert "`network-fs-lag`" in source_design
    assert (
        "Network filesystem lag profile that satisfies "
        "the Network Filesystem Lag Profile Policy"
        in source_design
    )
    assert "Network Filesystem Lag" in integration_recipes
    assert "path-state windows" in integration_recipes
    assert "Lag windows use the same logical clock" in time_model
    assert "Network Filesystem Lag Profile Testing" in testing
```

- [x] **Step 2: Run the focused docs test and verify it fails**

Run:

```bash
uv run pytest tests/docs/test_documentation.py::test_network_filesystem_lag_profile_policy_docs_are_discoverable -q --no-cov
```

Expected: fail because the source docs do not yet contain the network lag
policy strings.

## Task 2: Source Design Policy

**Files:**

- Modify: `docs/specs/chaos-librarian-design.md`

- [x] **Step 1: Add a network filesystem lag policy before Mutation Model**

Insert a new `## Network Filesystem Lag Profile Policy` section immediately
before `## Mutation Model`. The section must state:

```markdown
Future network filesystem lag scenarios are reserved for opt-in watcher
fixtures. The current contract still rejects `network-fs-lag` until a profile
implementation explicitly adds it.

Reserved label:

- `network-fs-lag`
```

The section must also state that the profile label never changes existing
timeline action behavior by itself; lag artifacts require explicit
`network_lag_start` / `network_lag_commit` events.

- [x] **Step 2: Add contract bullets for scenario shape and watcher guarantees**

In the same section, add bullets covering:

```markdown
- `network_lag_start` fields: `effect`, `target`, `after`, and `duration`.
- `network_lag_commit` field: `for`.
- Initial effects: `delayed_visibility`, `delayed_rename`, and `held_handle`.
- The start event must share the referenced event's `at:` value and immediately
  follow that event in resolved order.
- `run` is the only mode with live watcher-facing guarantees.
- `materialize` rejects lag events as unsupported.
- Watcher guarantees are path-state windows, not OS notification ordering.
```

- [x] **Step 3: Tie Sprint 10 back to the policy**

Change the Sprint 10 deliverable bullet from:

```markdown
- Network filesystem lag profile
```

to:

```markdown
- Network filesystem lag profile that satisfies the Network Filesystem Lag
  Profile Policy
```

## Task 3: Consumer And Developer Guidance

**Files:**

- Modify: `docs/contract/integration-recipes.md`
- Modify: `docs/contract/time-model.md`
- Modify: `docs/developer/testing.md`

- [x] **Step 1: Add watcher recipe guidance**

Add a `## Network Filesystem Lag` section after `## Watcher Identity-History`
in `docs/contract/integration-recipes.md`. It must state:

```markdown
The future `network-fs-lag` profile is for `chaos-librarian run`, not
`materialize`. Lag fixtures describe explicit lag events and produce
path-state windows such as delayed visibility, delayed rename, and held-handle
evidence. Consumers should compare watcher observations to those recorded
windows, not to guessed sleeps or low-level OS notification ordering.
```

- [x] **Step 2: Add time-model guidance**

Append a short `## Profile Timing` section to `docs/contract/time-model.md`:

```markdown
Future lag profiles use the same logical clock and duration grammar. Lag
windows use the same logical clock as timeline events and are scaled by the
`run --speed` multiplier in wall-clock mode. If `run --duration` expires inside
a lag window, the runner continues through the paired commit and records
`overran_duration=true`.
```

- [x] **Step 3: Add developer testing policy**

Append a `## Network Filesystem Lag Profile Testing` section to
`docs/developer/testing.md`. It must point to
`docs/specs/chaos-librarian-design.md` as the policy source of truth and state
that future tests should assert path-state windows, materialize rejection, and
held-handle blocking only when provider evidence says the behavior is enforced.

## Task 4: Verification

**Files:**

- No additional files.

- [x] **Step 1: Run the focused docs test**

Run:

```bash
uv run pytest tests/docs/test_documentation.py::test_network_filesystem_lag_profile_policy_docs_are_discoverable -q --no-cov
```

Expected: pass.

- [x] **Step 2: Run all docs tests**

Run:

```bash
uv run pytest tests/docs -q --no-cov
```

Expected: all docs tests pass.

- [x] **Step 3: Run format check**

Run:

```bash
uv run ruff format --check tests/docs/test_documentation.py
```

Expected: ruff reports the file would be left unchanged.

- [x] **Step 4: Run lint on edited Python test**

Run:

```bash
uv run ruff check tests/docs/test_documentation.py
```

Expected: no lint findings.
