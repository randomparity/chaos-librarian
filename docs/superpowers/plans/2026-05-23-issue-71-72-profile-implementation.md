# Issue #71/#72 Profile Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the performance profile labels and the first
`network-fs-lag` runtime profile cut defined by issues #71 and #72.

**Architecture:** Keep performance profiles as contract labels plus source
budget validation; they do not change runtime behavior. Implement
`network-fs-lag` as explicit scenario events that plan into started/committed
journal entries and are only live in `run`; batch `materialize` rejects them as
unsupported. Runtime lag evidence lives in `materialization.json` beside the
existing filesystem/media/corruption audit streams.

**Tech Stack:** Python 3.13, Pydantic v2 contracts, existing semantic validation
pipeline, existing wall-clock materializer scheduler.

---

## Scope

This branch implements the first runtime cut, not generators or CI jobs.

In scope:

- Add profile labels: `performance-smoke`, `performance-scale`,
  `performance-stress`, and `network-fs-lag`.
- Add static performance budget validation for source-fixture counts.
- Add `network_lag_start` / `network_lag_commit` scenario events.
- Add semantic validation for lag opt-in, pairing, timing, referenced event
  adjacency, target match, and overlapping same-target mutations.
- Plan lag events into journal entries with state-delta evidence.
- Add `network_lag_actions` to `MaterializationReport`.
- Reject lag events in `materialize`.
- Support delayed rename path-state windows in `run`.
- Support held-handle audit evidence in `run` without promising host blocking
  unless the provider reports it.
- Regenerate JSON Schema artifacts and update contract docs.

Out of scope:

- FUSE/SMB/NFS/cloud-sync providers.
- Random background lag.
- Performance fixture generation.
- CI workflow jobs for performance profiles.
- Overlapping lag windows on the same target.

## File Structure

Modify:

- `src/chaos_librarian/contract/__init__.py`
- `src/chaos_librarian/contract/profiles.py`
- `src/chaos_librarian/contract/scenario.py`
- `src/chaos_librarian/contract/materialization.py`
- `src/chaos_librarian/engine/events.py`
- `src/chaos_librarian/engine/resolution.py`
- `src/chaos_librarian/materializer/actions.py`
- `src/chaos_librarian/materializer/preflight.py`
- `src/chaos_librarian/materializer/wall_clock.py`
- `src/chaos_librarian/materializer/persistence/reports.py`
- `src/chaos_librarian/validation/codes.py`
- `src/chaos_librarian/validation/semantic.py`
- `src/chaos_librarian/validation/rules/profile_opt_in.py`
- New validation rule modules only if existing files become too broad.
- Existing contract, validation, materializer, docs, and schema tests.
- `schemas/*.schema.json` via `schema_export --write`.

## Task 1: Contract Profile Labels

- [x] Add failing contract tests showing all new profile labels parse through
  `Scenario.model_validate` and unknown labels still fail.
- [x] Add `ProfileName.PERFORMANCE_SMOKE`, `PERFORMANCE_SCALE`,
  `PERFORMANCE_STRESS`, and `NETWORK_FS_LAG`.
- [x] Bump `SCENARIO_SCHEMA_VERSION` and `Scenario.schema_version` from `7` to
  `8`; update fixtures and contract-version tests.
- [x] Regenerate schemas and run:
  `uv run pytest tests/contract/test_scenario.py tests/contract/test_schema_export.py -q --no-cov`.

## Task 2: Performance Budget Validation

- [x] Add `E_PROFILE_BUDGET_EXCEEDED`.
- [x] Add tests for scenarios that exceed `performance-smoke` asset and timeline
  ceilings and for a scenario that stays within the ceilings.
- [x] Implement static count budgets for assets, works, variants, bundles,
  sidecars, and timeline events. Skip materialized-byte, wall-clock-duration,
  and free-disk budgets until profile fixtures exist because those require run
  artifacts or CI infrastructure.
- [x] Run:
  `uv run pytest tests/validation/rules/test_profile_budgets.py -q --no-cov`.

## Task 3: Network Lag Contract And Validation

- [ ] Add failing contract tests for `network_lag_start` and
  `network_lag_commit`.
- [ ] Add `NetworkLagEffect`, `NetworkLagStartEvent`, and
  `NetworkLagCommitEvent` to the timeline union.
- [ ] Add profile opt-in tests: lag events require `network-fs-lag`.
- [ ] Add lag semantic tests for unknown starts, bad timing, non-adjacent start,
  target mismatch, and same-target mutation inside a pending lag window.
- [ ] Implement lag validation with existing reporter patterns.
- [ ] Run:
  `uv run pytest tests/contract/test_scenario.py tests/validation/rules/test_profile_opt_in.py tests/validation/rules/test_network_lag.py -q --no-cov`.

## Task 4: Planning And Audit Contract

- [ ] Add engine tests showing lag start emits `phase=started`, lag commit emits
  `phase=committed`, and both carry effect/after/path timing evidence.
- [ ] Implement plan-only handlers that do not alter logical manifest state
  beyond the referenced mutation; lag entries are evidence around the referenced
  disk effect.
- [ ] Add `NetworkLagAction` to `MaterializationReport` and
  `network_lag_actions: list[NetworkLagAction]`.
- [ ] Bump `MATERIALIZATION_SCHEMA_VERSION` and
  `MaterializationReport.schema_version` from `7` to `8`; update tests.
- [ ] Run:
  `uv run pytest tests/engine/test_events_network_lag.py tests/contract/test_materialization.py -q --no-cov`.

## Task 5: Runtime Behavior

- [ ] Add preflight tests proving `materialize` rejects lag events as
  unsupported while `run` accepts them.
- [ ] Implement delayed rename in wall-clock run by intercepting the referenced
  filesystem action and applying the real rename at lag commit.
- [ ] Implement held-handle audit rows with `enforced=false` for the stdlib-local
  provider.
- [ ] Add wall-clock tests for delayed rename path windows, timeout overrun
  through lag commit, and held-handle audit evidence.
- [ ] Run:
  `uv run pytest tests/materializer/test_wall_clock.py tests/materializer/test_preflight.py -q --no-cov`.

## Task 6: Docs, Schemas, And Gates

- [ ] Update docs from "future/rejects" language to implemented contract
  language where the branch changes behavior.
- [ ] Regenerate schemas with
  `uv run python -m chaos_librarian.schema_export --write`.
- [ ] Run focused gates:
  `uv run pytest tests/contract tests/validation/rules tests/materializer/test_wall_clock.py -q --no-cov`.
- [ ] Run full merge gates:
  `uv run ruff check .`,
  `uv run ruff format --check .`,
  `uv run ty check src tests`,
  `uv run python -m chaos_librarian.schema_export --check`,
  and `prek run --all-files`.
