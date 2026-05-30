# Network filesystem chaos beyond latency (#111) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add seven `network-fs-chaos`-gated timeline actions —
`change_permissions`, `simulate_quota_exceeded`, `toggle_readonly`,
`simulate_stale_handle`, `unmount_path`/`remount_path`,
`acquire_lock`/`release_lock` — that inject network-filesystem failure conditions
during a wall-clock run. `change_permissions` / `toggle_readonly` perform a real
`os.chmod` (restored at teardown); the four kernel-level conditions are recorded-only
neutral facts (`enforced=False`). Every injected condition is recorded as a neutral
`NetworkFsChaosAction` on the materialization report. `SCENARIO_SCHEMA_VERSION` bumps
27 → 28 and `MATERIALIZATION_SCHEMA_VERSION` bumps 15 → 16.

**Architecture:** Seven `TimelineActionName` members + seven event variants on the
`TimelineEvent` union (`ChangePermissionsEvent`, `SimulateQuotaExceededEvent`,
`ToggleReadonlyEvent`, `SimulateStaleHandleEvent`, `UnmountPathEvent`,
`RemountPathEvent`, `AcquireLockEvent`, `ReleaseLockEvent`). The pair closes
(`remount_path`, `release_lock`) carry only `for_` (`for` in YAML) referencing the
open's id, via the `AliasChoices` split-alias convention. Gating flows through the
single-source `REQUIRED_PROFILES_BY_ACTION` (so `rule_profile_opt_in` and generation
both derive from it). The engine emits atomic entries for single-shot actions and
started/committed pairs for the windowed actions, holding open windows in new
`WorldState.pending_locks` / `pending_unmounts` dicts. A new pairing rule
(`rule_network_fs_chaos_pairing`) validates the close→open reference, cardinality,
declaration-order, the `open.at <= close.at` monotonic guard (prevents a resolved-order
inversion that would `KeyError` the engine pop), and the same-target-window mutation
guard — reusing `index_start_commit_events` / `report_unpaired_start` /
`_check_same_target_window`. A new target rule (`rule_network_fs_chaos_target`) checks
the path-or-asset targets via `resolve_under_library` (`E_PATH_CONTAINMENT`); the
asset-only actions join `_ASSET_TARGET_ACTIONS` (`E_TARGET_UNKNOWN`). The wall-clock
runner gets explicit `_execute_entry` branches; `change_permissions` / `toggle_readonly`
chmod under `<run-dir>/library/`, capture the original `st_mode` in a
`NetworkFsChaosSession`, and restore it at finalize and on the Phase-B failure path
(try/finally). All seven append a `NetworkFsChaosAction` to the report.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, `uv` / `ruff` / `ty`. Linux/macOS
POSIX (`os.chmod` semantics; CI `ubuntu-latest`). Wall-clock chaos tests need no ffmpeg
(reuse the existing wall-clock test seams); they assert `os.stat().st_mode` and the
report records.

**Spec:** `docs/superpowers/specs/2026-05-30-issue-111-network-fs-chaos-design.md`
**ADR:** `docs/adr/0007-network-fs-chaos.md`

> **Naming note:** every failure reuses an existing validation code — no new code is
> introduced. Profile gate `E_PROFILE_REQUIRED`; octal-mode shape (Pydantic)
> `E_FIELD_SHAPE`; asset-only unknown target `E_TARGET_UNKNOWN`; path-target escape
> `E_PATH_CONTAINMENT`; pairing/window/monotonic `E_LIFECYCLE_INVALID`; static
> materialize rejection `E_MATERIALIZE_TIMELINE_UNSUPPORTED`
> (`TimelineUnsupportedError`).

---

## Invariants (hold at every commit)

- `uv run ruff check` && `uv run ruff format --check` && `uv run ty check src tests`
  && `uv run python -m pytest -q` are all green. **Never a red commit.**
- `uv run python -m chaos_librarian.schema_export --check` passes (regen + commit in the
  same task that changes a contract model).
- The scenario `schema_version` literal + the materialization `schema_version` literal
  + the fixture/recipe corpus bump land **together in one atomic commit** (Task 2) so
  the corpus tests are never red.
- Real `os.chmod` is confined to `<run-dir>/library/`; the run-dir root is never
  chmod'd; every captured mode is restored at finalize and on the failure path.

## File structure

New files:
- `src/chaos_librarian/validation/rules/network_fs_chaos.py` — `rule_network_fs_chaos_target` + `rule_network_fs_chaos_pairing`
- `tests/contract/test_network_fs_chaos.py` — event-variant + `NetworkFsChaosAction` contract tests
- `tests/validation/rules/test_network_fs_chaos.py` — gate / target / pairing rule tests
- `tests/materializer/test_wall_clock_network_fs_chaos.py` — realization + teardown + replay tests
- `tests/fixtures/scenarios/network-fs-chaos-*.yaml` (valid) + `tests/fixtures/scenarios/invalid/network-fs-chaos-*.yaml` (`# expected:` markers)
- `recipes/watcher/permission-denied-midscan.yaml`, `recipes/watcher/lock-conflict.yaml`

Modified files:
- `src/chaos_librarian/contract/scenario.py` — enums, event classes, union, `schema_version` literal
- `src/chaos_librarian/contract/profiles.py` — `ProfileName.NETWORK_FS_CHAOS`
- `src/chaos_librarian/contract/materialization.py` — `NetworkFsChaosAction`, report field + literal
- `src/chaos_librarian/contract/__init__.py` — `SCENARIO_SCHEMA_VERSION` 28, `MATERIALIZATION_SCHEMA_VERSION` 16
- `src/chaos_librarian/validation/rules/profile_opt_in.py` — seven `REQUIRED_PROFILES_BY_ACTION` rows
- `src/chaos_librarian/validation/rules/target_unknown.py` — three asset-only actions into `_ASSET_TARGET_ACTIONS`
- `src/chaos_librarian/validation/semantic.py` — register the two new rules
- `src/chaos_librarian/materializer/actions.py` — `NETWORK_FS_CHAOS_ACTIONS` frozenset
- `src/chaos_librarian/materializer/preflight.py` — `allow_network_fs_chaos` parameter
- `src/chaos_librarian/materializer/wall_clock.py` — `_execute_entry` branches, sessions, teardown
- `src/chaos_librarian/materializer/replay.py` — pass `allow_network_fs_chaos=True`
- `src/chaos_librarian/engine/state.py` — `pending_locks`, `pending_unmounts`
- `src/chaos_librarian/engine/events.py` — seven handlers + handler-table rows
- `schemas/scenario.schema.json`, `schemas/materialization.schema.json` — regenerated
- every `tests/fixtures/scenarios/**` + `recipes/**` `schema_version: 27` → `28`

---

## Task 1 — Schema: enums, event variants, profile, report record (RED → GREEN)

Pure contract change; no version bump yet (so the corpus stays green until Task 2).

- [ ] **Test first** (`tests/contract/test_network_fs_chaos.py`): each of the eight
  event classes round-trips through its own `model_validate` (build the event dict,
  validate, assert fields); `change_permissions.mode` rejects `"abc"`, `"99"`,
  `"12345"`, accepts `"000"`/`"644"`/`"4644"`; `remount_path`/`release_lock` accept both
  `for` and `for_` keys; `ToggleReadonlyEvent.mode` rejects a non-`readonly`/`readwrite`
  value; `AcquireLockEvent.lock_type` rejects a bad value; `NetworkFsChaosAction`
  round-trips and rejects an `extra` field. (These tests build event dicts directly, not
  a full `Scenario` — the `schema_version` mismatch is avoided until Task 2.)
- [ ] **Implement** in `contract/scenario.py`: add `ReadonlyState`, `LockType`,
  `NetworkFsChaosCondition` StrEnums; add the seven `TimelineActionName` members; add the
  eight event classes (one per action; `change_permissions`/`toggle_readonly`/`unmount`
  take `target: str`; quota/stale/lock take `target: str`; lock adds `lock_type`;
  `change_permissions` adds `mode: str` with a `@field_validator` enforcing
  `^[0-7]{3,4}$`; `toggle_readonly` adds `mode: ReadonlyState`; `remount_path` /
  `release_lock` carry only `for_` via `AliasChoices("for_", "for")`). Add all eight to
  the `TimelineEvent` union.
- [ ] **Implement** in `contract/profiles.py`: `ProfileName.NETWORK_FS_CHAOS = "network-fs-chaos"`.
- [ ] **Implement** in `contract/materialization.py`: `NetworkFsChaosAction`
  (`extra="forbid"`, fields per spec "Report record"); add
  `network_fs_chaos_actions: list[NetworkFsChaosAction] = Field(default_factory=list)`
  to `MaterializationReport`. (Leave the report `schema_version` literal for Task 2.)
- [ ] **Verify:** `uv run ty check src tests`, `uv run ruff check`, `pytest tests/contract/test_network_fs_chaos.py -q` green.
- [ ] **Commit:** `feat: add network-fs-chaos event variants and report record`

## Task 2 — Version bumps + corpus mass-bump (atomic, RED → GREEN)

- [ ] **Implement:** `contract/__init__.py` `SCENARIO_SCHEMA_VERSION` 27 → 28,
  `MATERIALIZATION_SCHEMA_VERSION` 15 → 16; `Scenario.schema_version: Literal[28]`;
  `MaterializationReport.schema_version: Literal[16]`.
- [ ] **Mass-bump** every `schema_version: 27` → `28` under `tests/fixtures/scenarios/**`
  and `recipes/**` in one step (leave `yaml-parse-error.yaml` untouched — it never
  parses). Verify with `rg -l "schema_version: 27" tests recipes` returning only the
  intentional exception(s).
- [ ] **Regenerate:** `uv run python -m chaos_librarian.schema_export --write`; confirm
  only `scenario.schema.json` and `materialization.schema.json` changed.
- [ ] **Verify:** full `pytest -q`, `schema_export --check`, `ty`, `ruff` green.
- [ ] **Commit:** `feat: bump scenario v28 / materialization v16 for network-fs-chaos`

## Task 3 — Profile gate + target validation (RED → GREEN)

- [ ] **Test first** (`tests/validation/rules/test_network_fs_chaos.py` + invalid
  fixtures): for each new action, a fixture **without** `network-fs-chaos` →
  `E_PROFILE_REQUIRED`; **with** it → clean. Assert each new action's required profile
  **against the live `REQUIRED_PROFILES_BY_ACTION`** (import the map; do not hardcode).
  Unknown asset target on `simulate_quota_exceeded` / `simulate_stale_handle` /
  `acquire_lock` → `E_TARGET_UNKNOWN`. A `change_permissions`/`toggle_readonly`/`unmount`
  with an escaping path target (`../../etc`) → `E_PATH_CONTAINMENT`; with a declared
  asset id → clean; with a well-formed library-relative subtree path → clean.
- [ ] **Implement:** add the seven rows to `REQUIRED_PROFILES_BY_ACTION`
  (`profile_opt_in.py`). Add quota/stale/lock to `_ASSET_TARGET_ACTIONS`
  (`target_unknown.py`). New `rule_network_fs_chaos_target` in
  `validation/rules/network_fs_chaos.py`: for the three path-or-asset actions, if
  `target` is not a declared asset id, resolve it through `resolve_under_library`
  against a synthetic run dir; an escape → `E_PATH_CONTAINMENT`. Register the rule in
  `semantic.py` `_RULES`.
- [ ] **Verify + commit:** `feat: gate network-fs-chaos actions and validate targets`

## Task 4 — Pairing + window validation (RED → GREEN)

- [ ] **Test first**: `release_lock.for` / `remount_path.for` referencing an unknown
  open → `E_LIFECYCLE_INVALID`; an open with zero or >1 matching close →
  `E_LIFECYCLE_INVALID`; a close before its open in declaration order →
  `E_LIFECYCLE_INVALID`; a close whose `at` is earlier than its open's `at` (e.g.
  `acquire at=10s, release at=1s`) → `E_LIFECYCLE_INVALID` (the resolved-order-inversion
  guard); another mutation on the same target between open and close →
  `E_LIFECYCLE_INVALID`; a well-formed `acquire`/`release` and `unmount`/`remount`
  window → clean; a zero-width window (`open.at == close.at`) → clean.
- [ ] **Implement** `rule_network_fs_chaos_pairing` in `network_fs_chaos.py`: reuse
  `index_start_commit_events` (twice — locks and unmounts), `report_unpaired_start`, and
  a `_check_same_target_window` twin; add the `open.at_ns <= close.at_ns` check (parse
  via `try_parse_duration`). Register in `semantic.py`.
- [ ] **Verify + commit:** `feat: validate network-fs-chaos open/close pairing`

## Task 5 — Engine handlers (RED → GREEN)

- [ ] **Test first** (engine-level): a single-shot action emits one `AtomicJournalEntry`
  with the neutral `state_delta` (target_ref, condition, mode where relevant); an
  `acquire_lock` emits a `StartedJournalEntry` and a `release_lock` emits a
  `CommittedJournalEntry` with `related_event_id` = the acquire id; same for
  `unmount`/`remount`; the open is held in `pending_locks`/`pending_unmounts` and popped
  on close.
- [ ] **Implement:** `engine/state.py` adds `pending_locks` / `pending_unmounts` dicts;
  `engine/events.py` adds seven handlers (single-shot via `_new_atomic_entry`; paired
  open via `StartedJournalEntry` + record; paired close via `pop` + `CommittedJournalEntry`)
  and the handler-table rows. `state_delta` carries only neutral facts; location ids via
  `_location_ids_for_target` when the target is a known asset.
- [ ] **Verify + commit:** `feat: engine handlers for network-fs-chaos actions`

## Task 6 — Wall-clock realization + teardown (RED → GREEN)

- [ ] **Test first** (`tests/materializer/test_wall_clock_network_fs_chaos.py`, no ffmpeg):
  - `change_permissions` to `000` on an asset: `os.stat().st_mode & 0o777 == 0` during
    the run; restored to the captured original at finalize;
    `NetworkFsChaosAction(enforced=True, condition=eacces, mode="000")` recorded.
  - `toggle_readonly readonly` clears the write bits; `readwrite` restores them; restored
    at finalize.
  - each of quota/stale/lock+release/unmount+remount records `enforced=False` with the
    right `condition`; the paired close records the open id and the open's target.
  - **failure-path restore:** inject a Phase-B failure after a `change_permissions` and
    assert the mode is restored (try/finally) so the run dir is removable.
  - **replay parity:** re-run the same scenario; identical journal + report records.
  - a chaos scenario that passes validation never raises an engine `KeyError`.
- [ ] **Implement:** `actions.py` `NETWORK_FS_CHAOS_ACTIONS`; `preflight.py`
  `allow_network_fs_chaos` parameter widening the supported set; `replay.py` passes it
  `True`; `wall_clock.py` adds the explicit `_execute_entry` branches, a
  `NetworkFsChaosSession` on `_DispatchState`, the chmod/record logic, and the
  restore-at-finalize + restore-on-failure try/finally.
- [ ] **Verify + commit:** `feat: realize network-fs-chaos in the wall-clock runner`

## Task 7 — Preflight rejection in static materialize (RED → GREEN)

- [ ] **Test first:** static `materialize` of a scenario with each new action raises
  `TimelineUnsupportedError` (`E_MATERIALIZE_TIMELINE_UNSUPPORTED`) — no run-dir
  allocation. (Confirms `allow_network_fs_chaos` defaults `False` in the static path.)
- [ ] **Implement:** verify the static-materialize call site passes neither
  `allow_*` flag (likely no code change beyond Task 6; the test is the guard).
- [ ] **Verify + commit:** `test: static materialize rejects network-fs-chaos actions`

## Task 8 — Recipes + valid-fixture corpus + backward-compat (RED → GREEN)

- [ ] **Test first:** the two recipes are discovered by
  `tests/recipes/test_recipe_corpus.py` and validate clean; a valid asset-target and a
  subtree-path-target chaos fixture validate clean; a scenario with **none** of the new
  actions produces a report whose `network_fs_chaos_actions == []` and a byte-identical
  tree (backward-compat).
- [ ] **Implement:** write `recipes/watcher/permission-denied-midscan.yaml` and
  `recipes/watcher/lock-conflict.yaml` with the `# Recipe:` / `# Requires: none` header
  and the `network-fs-chaos` profile; add the valid fixtures.
- [ ] **Verify + commit:** `feat: ship network-fs-chaos recipes and corpus fixtures`

## Task 9 — Follow-up issues + docs sweep

- [ ] File the deferred follow-ups (dedup against #186/#188/#189/#191/#192/#193/#195
  first): (a) fuzz-lane / generation emission of network-fs-chaos actions; (b) lag⇄chaos
  cross-interaction validation; (c) recursive `toggle_readonly` over a subtree's files;
  (d) finer shared-vs-exclusive lock-window semantics; (e) real ENOSPC/ESTALE/EAGAIN/
  unmount via loopback/FUSE. Reference them in the PR body.
- [ ] Update any contract docs under `docs/contract/` that enumerate timeline actions or
  profiles, if such an enumeration exists (grep first; do not invent).
- [ ] **Verify + commit** any doc changes: `docs: note network-fs-chaos actions in contract docs`

## Rollback / cleanup

- Each task is one green commit; revert is per-task. Tasks 1–2 are the schema
  foundation; reverting Task 2 alone would leave the corpus red, so Tasks 1+2 revert
  together if the schema direction is abandoned.
- No external state, no migrations: the only "migration" is the fixture/recipe
  `schema_version` bump, fully contained in Task 2.
- Real-FS safety is the only runtime cleanup concern, fully handled by the
  restore-at-finalize + restore-on-failure try/finally (Task 6); a test asserts the run
  dir is removable after a Phase-B failure following a `change_permissions`.

## Verification gates (final, before PR)

- [ ] `uv run ruff check` + `uv run ruff format --check`
- [ ] `uv run ty check src tests`
- [ ] `uv run python -m pytest -q`
- [ ] `uv run python -m chaos_librarian.schema_export --check`
- [ ] `rg -l "schema_version: 27" tests recipes` returns only the intentional exception(s)
- [ ] every spec acceptance-criteria checkbox has a backing test
