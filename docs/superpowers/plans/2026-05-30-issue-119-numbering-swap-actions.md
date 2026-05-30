# Explicit numbering swap actions (#119) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:test-driven-development
> task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Write the failing test
> first, then the implementation, in every task.

**Goal:** Add three hierarchy timeline actions — `swap_episode_numbers`,
`swap_disc_numbers`, `swap_track_numbers` — that atomically exchange the number field of
two **same-parent** sibling entities (episodes in one season, discs in one album, tracks
on one disc). A swap is the sanctioned way to do what an implicit-swap-via-`renumber_*`
is forbidden from doing. `SCENARIO_SCHEMA_VERSION` bumps 28 → 29; only
`schemas/scenario.schema.json` regenerates.

**Architecture:** Three `TimelineActionName` members + three `TimelineEvent` variants
(`SwapEpisodeNumbersEvent` with `target`+`with_episode`, `SwapDiscNumbersEvent` with
`target`+`with_disc`, `SwapTrackNumbersEvent` with `target`+`with_track`), each carrying
only the two operand ids plus inherited `id`/`at`. The three actions join
`HIERARCHY_TIMELINE_ACTIONS` so path-history projection, the lifecycle hierarchy branch,
and `is_hierarchy_action` pick them up automatically. Validation reuses existing rules
and codes: `rule_target_unknown` resolves `target` + `with_*` against their kind's
disjoint id set (`E_TARGET_UNKNOWN`, incl. wrong-kind ids); `rule_hierarchy_timeline`
consults a new `HierarchyProjection.swap_validity` query (self-swap / not-same-parent →
`E_HIERARCHY_INVALID`) before `apply`, then the existing post-mutation duplicate check
runs as defense-in-depth; `rule_timeline_lifecycle` dispatches through the existing
hierarchy branch (`E_LIFECYCLE_INVALID` on pending slow_copy). `HierarchyProjection.apply`
gains a swap branch that exchanges the two number fields and re-renders both paths
(emitting crossed `path_moves`), no-opping the exchange when `swap_validity != OK`. The
engine adds three handlers mirroring `_handle_renumber_episode` — look up both entities,
`model_copy(update=...)` each number field, emit one `_hierarchy_entry` with crossed
`path_moves`. The materializer needs **no new code**: crossed `path_moves` flow through
the existing two-phase temp-path dance in `_hierarchy_moves`, locked in by a regression
test.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, `uv` / `ruff` / `ty`. No ffmpeg needed
(validation + projection + path-history tests; the materializer test drives
`_plan_hierarchy_moves` against plain files).

**Spec:** `docs/superpowers/specs/2026-05-30-issue-119-numbering-swap-actions-design.md`
**ADR:** `docs/adr/0008-numbering-swap-actions.md`

> **Naming note:** every failure reuses an existing validation code — no new code.
> Unknown / wrong-kind `target` or `with_*` → `E_TARGET_UNKNOWN`; self-swap /
> not-same-parent / projected-duplicate → `E_HIERARCHY_INVALID`; pending-slow-copy /
> open-window interaction → `E_LIFECYCLE_INVALID`.

---

## Invariants (hold at every commit)

- `uv run ruff check` && `uv run ruff format --check` && `uv run ty check src tests`
  && `uv run python -m pytest -q` are all green. **Never a red commit.**
- `uv run python -m chaos_librarian.schema_export --check` passes (regen + commit in the
  same task that changes a contract model).
- The schema model, the `schema_version` literal, and the regenerated
  `schemas/scenario.schema.json` change together in **one** task/commit.
- Hierarchy actions are **not** profile-gated (existing `renumber_*`/`move_*` aren't);
  swap actions add nothing to `REQUIRED_PROFILES_BY_ACTION`.
- No new error code, no manifest/journal/replay-bundle/materialization schema change.

---

## Task 1 — Schema: three swap event variants + version bump 28 → 29

Single atomic task (model + version literal + regenerated artifact must move together).

- [ ] **Test first** (`tests/contract/test_scenario.py`): each swap event round-trips
  through `Scenario.model_validate` with `schema_version: 29`; a payload with an extra
  field is rejected (`extra="forbid"`); a payload missing the `with_*` operand is
  rejected (required field). Assert the discriminator routes each `action` string to its
  variant.
- [ ] Add to `TimelineActionName`: `SWAP_EPISODE_NUMBERS = "swap_episode_numbers"`,
  `SWAP_DISC_NUMBERS = "swap_disc_numbers"`, `SWAP_TRACK_NUMBERS = "swap_track_numbers"`.
- [ ] Add the three members to `HIERARCHY_TIMELINE_ACTIONS`.
- [ ] Add three `_TimelineEventBase` subclasses with `Literal[...]` discriminator and the
  two operand fields (`target: str` + `with_episode`/`with_disc`/`with_track: str`). No
  number fields. Add each to the `TimelineEvent` union.
- [ ] Bump `SCENARIO_SCHEMA_VERSION` 28 → 29 in `contract/__init__.py` and the
  `Scenario.schema_version: Literal[29]`.
- [ ] **Mass-bump every existing `schema_version: 28` → 29 in this same commit.**
  `Scenario.schema_version` is a hard `Literal[29]` with no version-tolerance shim, and
  `test_sample_scenarios.py` + the invalid corpus run every fixture through
  `Scenario.model_validate`; leaving any fixture at `28` makes `pytest -q` **red at this
  commit**. Update every `schema_version: 28` string across `tests/fixtures/` and
  `recipes/` (`rg -l "schema_version: 28"`) plus any in-repo docs/examples. No semantic
  change to those scenarios. (New swap fixtures/recipes are added later in Task 6; only
  the version-string bump of *existing* files happens here.)
- [ ] `uv run python -m chaos_librarian.schema_export --write`; commit the regenerated
  `schemas/scenario.schema.json` in this task.
- [ ] **Guardrails green (incl. `test_sample_scenarios.py` + `test_invalid_corpus.py` +
  drift gate); commit.** `feat: add numbering swap event variants (schema v29)`

## Task 2 — Validation: target/with_* resolution + swap_validity + projection branch

- [ ] **Test first** (`tests/validation/rules/test_hierarchy_rules.py` +
  `test_target_unknown` location):
  - unknown `target` → `E_TARGET_UNKNOWN`; unknown `with_*` → `E_TARGET_UNKNOWN`;
  - `with_*` naming a **wrong-kind** declared id (season id in `with_episode`) →
    `E_TARGET_UNKNOWN` (not `E_HIERARCHY_INVALID`);
  - self-swap `target == with_*` → `E_HIERARCHY_INVALID`, asserted independently (no
    duplicate present, so only the explicit guard can catch it);
  - different-parent pair (both valid, different season/album/disc) →
    `E_HIERARCHY_INVALID`;
  - **defense-in-depth, projection-direct:** construct a `HierarchyProjection`, seed a
    duplicate number into the affected group's projection state, call `apply` on an `OK`
    swap, and assert `_check_hierarchy_mutation_numbers` reports `E_HIERARCHY_INVALID`
    (exercised through the projection, not a statically-rejected fixture).
- [ ] `target_unknown.py`: add the three swap actions to
  `_HIERARCHY_TARGET_KIND_BY_ACTION` (kind = episode/disc/track) and add `with_*` cases
  to `_check_destination_reference` via `_check_field_reference` (kind = its own).
- [ ] `_common.py` `HierarchyProjection`: add `swap_validity(event) -> SwapValidity`
  (enum `OK`/`SELF_SWAP`/`NOT_SAME_PARENT`/`MISSING`) reading both ids without mutation;
  add a swap branch to `apply` (and `affected_asset_ids`) that exchanges the two number
  fields and re-renders both paths, **no-opping the exchange when `swap_validity != OK`**.
  Same-parent = same `season_id` (episodes) / `album_id` (discs) / `disc_id` (tracks).
- [ ] `hierarchy.py` `rule_hierarchy_timeline`: before `apply`, for swap actions call
  `swap_validity`; on `SELF_SWAP`/`NOT_SAME_PARENT` emit `E_HIERARCHY_INVALID` with the
  specific message and skip `apply`; on `OK`/`MISSING` proceed as today.
- [ ] **Guardrails green; commit.** `feat: validate numbering swap operands and siblinghood`

## Task 3 — Engine: three swap handlers + manifest exchange

- [ ] **Test first** (`tests/engine/test_events.py` or equivalent): a swap of two
  same-parent episodes leaves each `ManifestEpisode.episode_number` holding the other's;
  the emitted `AtomicJournalEntry.state_delta` carries crossed `path_moves`
  (A.from==B.to, B.from==A.to) and `metadata` for both number fields;
  `target_ids == [a, b, *asset_ids]`. Same coverage for disc and track.
- [ ] `events.py`: add `_handle_swap_episode_numbers` / `_handle_swap_disc_numbers` /
  `_handle_swap_track_numbers`, each mirroring `_handle_renumber_episode`: capture both
  entities' asset ids + before-paths, `model_copy(update={number_field: other_number})`
  on both entities, build `metadata` for both, emit one `_hierarchy_entry` whose
  `asset_ids` is the union of both entities' assets. Register in `_HANDLERS`.
- [ ] **`_hierarchy_entry` entity-B threading — single committed approach:** add an
  optional `extra_hierarchy_target_ids: tuple[str, ...] = ()` parameter to
  `_hierarchy_entry` and build `target_ids=[hierarchy_target_id, *extra_hierarchy_target_ids,
  *asset_ids]`. The three swap handlers pass entity B's id there; existing callers pass
  nothing (behavior unchanged). The Task-3 test asserts the full
  `target_ids == [a, b, *asset_ids]` shape, so a dropped entity-B id fails the test.
  (B's *asset* ids are already in the union; only B's *entity* id needs this.)
- [ ] Engine trusts validated input (mirrors existing hierarchy handlers; no re-guard).
- [ ] **Guardrails green; commit.** `feat: engine handlers for numbering swaps`

## Task 4 — Materializer regression test (no new code)

- [ ] **Test first** (`tests/materializer/phase_b/test_filesystem.py`): drive the real
  `_plan_hierarchy_moves` + the two-phase `source.replace(temp)` / `temp.replace(dest)`
  execution with mutually-crossed moves (A.from==B.to, B.from==A.to) on two real files
  under a temp library root. Hard assertions that prove the crossing actually happened
  (not a false green): (1) **pre-swap A's bytes != B's bytes** (distinct sentinels);
  (2) post-swap A holds B's old bytes and B holds A's old bytes (exact exchange); (3) the
  directory listing equals exactly the two final names — **no `.chaos-hierarchy-*` temp
  residue**. This locks the spec's "no new materializer code" claim.
- [ ] No production change expected. If the test fails, that IS new materializer work —
  stop and surface it.
- [ ] **Guardrails green; commit.** `test: lock collision-free crossed hierarchy moves`

## Task 5 — Path-history, lifecycle, and implicit-vs-explicit coverage

- [ ] **Test first**:
  - **path-history** (`tests/engine/test_path_history.py` or via `derive_path_history`):
    after a swap, asset A's history has one entry `from=A_old`, `to=A_new (==B_old)`; B's
    has `from=B_old`, `to=B_new (==A_old)`.
  - **lifecycle** (`tests/validation/.../test_timeline_lifecycle*`): a swap touching an
    asset with a pending `slow_copy` → `E_LIFECYCLE_INVALID`.
  - **implicit-vs-explicit** (one test): the `renumber_episode`-into-a-duplicate case
    still emits `E_HIERARCHY_INVALID`, while the equivalent `swap_episode_numbers`
    validates clean.
- [ ] No production change expected beyond Tasks 1–3 (these are the wiring assertions).
- [ ] **Guardrails green; commit.** `test: path-history, lifecycle, implicit-vs-explicit swaps`

## Task 6 — New swap corpus + recipe + docs

> The mass-bump of *existing* `schema_version: 28 → 29` fixtures/recipes happened in
> Task 1 (same commit as the literal). This task adds only the *new* swap files and docs.

- [ ] Add valid swap fixtures per axis under `tests/fixtures/scenarios/`
  (`swap-episode-numbers.yaml`, `swap-disc-numbers.yaml`, `swap-track-numbers.yaml`),
  each `schema_version: 29`, exercised by `test_sample_scenarios.py`.
- [ ] Add invalid fixtures under `tests/fixtures/scenarios/invalid/` with the
  `# expected: E_...` first-line marker for the **statically-reachable** cases: self-swap
  (`E_HIERARCHY_INVALID`) and a different-parent swap (`E_HIERARCHY_INVALID`). (No
  still-duplicate fixture — `rule_hierarchy_invariants` rejects a pre-existing duplicate
  before the timeline replays; that path is covered projection-direct in Task 2.)
- [ ] Add one or more recipe(s) under `recipes/` demonstrating an explicit swap (mirror
  an existing hierarchy recipe; honor the recipe bit-rot guard / ADR 0002).
- [ ] Update user-facing docs if the timeline-action list is enumerated anywhere
  (`docs/contract/`); add the three swap actions.
- [ ] **Guardrails green** including `test_invalid_corpus.py` + `test_sample_scenarios.py`
  + schema drift gate; **commit.** `feat: swap fixtures, recipes, and schema v29 bump`

## Task 7 — Adversarial review of the diff

- [ ] `/challenge main..HEAD`; apply `superpowers:receiving-code-review` to each finding;
  fix defensible ones; commit one logical change per pass. Repeat until approve or 5
  iterations.

## Task 8 — Follow-up issue + PR

- [ ] File the range-rebalance follow-up issue (dedup against
  #186/#188/#189/#191/#192/#193/#195/#197/#198/#199/#200/#201); reference in the PR body.
- [ ] `gh pr create` against main; body = plain factual diff description, ending
  `Closes #119`. `gh pr checks --watch` to green (ffmpeg/integration skips expected).

---

## Rollback / cleanup

- Each task is one commit; revert is per-commit.
- The schema bump (Task 1) is the only externally-visible contract change; reverting it
  reverts the regenerated artifact in the same commit.
- No external-service or destructive operations; the materializer test uses a temp dir.

## Verification gates (definition of done)

- All eight tasks' tests pass; guardrails green at every commit.
- `schema_export --check` passes; only `scenario.schema.json` changed.
- Existing sample + invalid corpus pass post-bump.
- The materializer regression test proves crossed moves are collision-free.
- `/challenge main..HEAD` returns approve (or 5-iteration cap with all defensible
  findings addressed).
