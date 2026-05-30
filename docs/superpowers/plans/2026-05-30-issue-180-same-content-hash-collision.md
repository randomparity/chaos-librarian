# Same-content / hash-collision assets (#180) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `Asset.same_content_as` (byte-identical duplicate → same full
`content_hash`) and `Asset.hash_collision_with` + `Asset.collision_prefix_len`
(oracle-recorded truncated-hash collision) so the `identity/same-content-duplicate` and
`identity/hash-collision-simulation` recipes become valid scenarios.
`SCENARIO_SCHEMA_VERSION` bumps 24 → 25; no other schema version changes.

**Architecture:** Three flat optional fields on `Asset` gated by a `model_validator`
(mutual exclusivity; `collision_prefix_len` iff `hash_collision_with`; `same_content_as`
forbids own `subtitles`). A new semantic rule `rule_content_reference` resolves the
asset-id references (unknown / self / forward → `E_TARGET_UNKNOWN`). The orchestrator
`materialize_assets_phase_a` short-circuits synthesis for a `same_content_as` asset and
copies the referent's already-written bytes (synthetic `same_content_copy`
`ToolInvocation`, re-probe, no `ContentSourceEvidence`). A collision-aware
`augment_manifest` recomputes a prefix-sharing recorded hash via a new pure helper
`collided_hash_for`, mirroring `wrong_oracle_hash`'s run/replay-stable parity.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, ffmpeg/ffprobe (env-gated for
materialize tests), `uv` / `ruff` / `ty`.

**Spec:** `docs/superpowers/specs/2026-05-30-issue-180-same-content-hash-collision-design.md`
**ADR:** `docs/adr/0004-same-content-hash-collision.md`

---

## Invariants (hold at every commit)

- `uv run ruff check` && `uv run ruff format --check` && `uv run ty check src tests`
  && `uv run python -m pytest -q` are all green. **Never a red commit.**
- `uv run python -m chaos_librarian.schema_export --check` passes (regen + commit in the
  same task that changes a contract model).
- The scenario `schema_version` model literal and the fixture/recipe corpus bump
  together in **one atomic commit** (Task 2) so the corpus tests are never red.

## File structure

| File | Responsibility | Action |
| --- | --- | --- |
| `src/chaos_librarian/contract/scenario.py` | three new `Asset` fields + `model_validator`; `schema_version: Literal[25]` | Modify |
| `src/chaos_librarian/contract/__init__.py` | `SCENARIO_SCHEMA_VERSION = 25` | Modify |
| `src/chaos_librarian/validation/rules/content_reference.py` | new semantic rule (asset-id refs: unknown/self/forward → `E_TARGET_UNKNOWN`) | Create |
| `src/chaos_librarian/validation/semantic.py` | register `rule_content_reference` | Modify |
| `src/chaos_librarian/materializer/phase_b/oracle_hash.py` | `collided_hash_for` pure helper next to `false_hash_for` | Modify |
| `src/chaos_librarian/materializer/manifest_build.py` | collision-aware `augment_manifest` (override recorded hash when `hash_collision_with` set) | Modify |
| `src/chaos_librarian/materializer/synthesis.py` | orchestrator copy short-circuit for `same_content_as` (synthetic invocation, re-probe) | Modify |
| `recipes/identity/same-content-duplicate.yaml`, `recipes/identity/hash-collision-simulation.yaml` | two new recipes | Create |
| `tests/fixtures/scenarios/**`, `recipes/**` | bump `schema_version: 25` (150 files) | Modify |
| `tests/fixtures/scenarios/invalid/*.yaml` | new invalid fixtures (refs + cross-field) | Create |
| `schemas/scenario.schema.json` | regenerated | Modify |
| `tests/**` mirroring `src/**` | unit + integration tests | Create/Modify |

---

## Task 1: Add the three `Asset` fields + `model_validator` (no version bump yet)

> **Phase-ordering note:** the `schema_version` literal bump is deliberately NOT in this
> task. Bumping the model's `Literal[25]` while the 150 fixtures are still at 24 would
> make `test_sample_scenarios` (which `Scenario.model_validate`s every fixture) red.
> Task 2 bumps the model literal AND the fixtures in one atomic commit. This task adds
> only the new `Asset` fields + validator, which are backward-compatible (all default
> `None`) and do not touch the `schema_version` literal.

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py` (`Asset`, ~line 420)
- Test: `tests/contract/test_scenario.py`

- [ ] **Step 1: Write failing contract tests.** In `tests/contract/test_scenario.py`,
  build `dict` payloads and call `Scenario.model_validate` (per AGENTS.md negative-test
  convention — no kwargs + `# type: ignore`):
  - accepts an `Asset` with `same_content_as: "a1"`.
  - accepts an `Asset` with `hash_collision_with: "a1", collision_prefix_len: 8`.
  - rejects `same_content_as` + `hash_collision_with` both set (`ValueError`).
  - rejects `hash_collision_with` set with `collision_prefix_len` unset, and vice-versa.
  - rejects `collision_prefix_len` 0 and 64 (`Field(ge=1, le=63)`).
  - rejects `same_content_as` on an asset that also declares `subtitles`.
  - a bare `Asset` (no new fields) still validates (backward compat).
- [ ] **Step 2: Implement.** Add to `Asset` (after `subtitles`):
  ```python
  same_content_as: str | None = None
  hash_collision_with: str | None = None
  collision_prefix_len: int | None = Field(default=None, ge=1, le=63)
  ```
  Add a `model_validator(mode="after")` `_check_content_dedup_fields` raising `ValueError`
  for: both link fields set; `collision_prefix_len` set xor `hash_collision_with` set;
  `same_content_as` set with non-empty `subtitles`. Keep the happy path unindented
  (`let...else`-style early returns where natural).
- [ ] **Step 3: Verify.** Run the new tests + full `tests/contract/`; ruff/ty/pytest green.
- [ ] **Commit:** `feat: add same_content_as/hash_collision asset fields`

## Task 2: Bump model literal + all fixtures/recipes to 25 (one atomic commit)

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py` (`SCENARIO_SCHEMA_VERSION = 25`)
- Modify: `src/chaos_librarian/contract/scenario.py` (`schema_version: Literal[25]`)
- Modify: every `tests/fixtures/scenarios/**` and `recipes/**` file pinning
  `schema_version: 24` (150 files; `yaml-parse-error.yaml` left untouched — it never
  parses and pins an old version deliberately).
- Modify: `schemas/scenario.schema.json` (regenerate).

- [ ] **Step 1:** Bump `SCENARIO_SCHEMA_VERSION` and the model `Literal`.
- [ ] **Step 2:** Mass-bump fixtures/recipes: replace `schema_version: 24` →
  `schema_version: 25` on **exactly the set `rg -l 'schema_version: 24' tests recipes`
  returns at execution time** (do not rely on a frozen count). **Post-condition:** after
  the replace, `rg -l 'schema_version: 24' tests recipes` must return **only**
  `yaml-parse-error.yaml` (the deliberately-pinned never-parses fixture) — assert this so
  no stray v24 file survives to red `test_sample_scenarios` after the literal bump.
- [ ] **Step 3:** `uv run python -m chaos_librarian.schema_export --write` and stage the
  regenerated `schemas/scenario.schema.json`.
- [ ] **Step 4: Verify.** `test_sample_scenarios`, `test_invalid_corpus`,
  `test_recipe_corpus`, `schema_export --check`, ruff/ty/pytest all green.
- [ ] **Commit:** `feat: bump SCENARIO_SCHEMA_VERSION 24 -> 25`

## Task 3: New semantic rule `rule_content_reference` (asset-id refs)

**Files:**
- Create: `src/chaos_librarian/validation/rules/content_reference.py`
- Modify: `src/chaos_librarian/validation/semantic.py` (register in `_RULES`)
- Create: `tests/validation/rules/test_content_reference.py` (or extend existing)
- Create invalid fixtures under `tests/fixtures/scenarios/invalid/` (each with the
  `# expected: E_<CODE>` first-line marker required by `test_invalid_corpus`):
  - `same-content-unknown-ref.yaml` → `# expected: E_TARGET_UNKNOWN`
  - `same-content-self-ref.yaml` → `# expected: E_TARGET_UNKNOWN`
  - `same-content-forward-ref.yaml` → `# expected: E_TARGET_UNKNOWN`
  - `hash-collision-unknown-ref.yaml` → `# expected: E_TARGET_UNKNOWN`
  - `content-dedup-both-set.yaml` → `# expected: E_FIELD_UNKNOWN` (model_validator
    value-error surfacing code — confirm the exact code the pipeline maps `ValueError`
    to and match it; mirror #181's `create-sidecar-*` invalid fixtures).

> **Confirm-before-fixture note:** before writing the `# expected:` markers for the
> model_validator cases, run one payload through the real validation pipeline in a test
> and read back `report.issues[].code` to learn the exact code a `model_validator`
> `ValueError` surfaces as (the #181 cross-kind fixtures are the precedent). Use that
> exact code in the marker so `test_invalid_corpus` passes. This avoids guessing
> `E_FIELD_UNKNOWN` vs another field code.

- [ ] **Step 1: Write failing tests.** Direct-call the rule (or run `run_validation`)
  asserting `E_TARGET_UNKNOWN` for: unknown ref, self-ref, forward/same-position ref;
  and `report.ok` for a valid earlier-declared ref. Assert the `loc` points at the
  offending field (`(..., "same_content_as")` / `(..., "hash_collision_with")`).
- [ ] **Step 2: Implement** `rule_content_reference(raw, line_index, collector)`:
  walk `iter_assets_with_loc(raw)` building a running set of *already-seen* asset ids in
  declaration order. For each asset, for each set `same_content_as` /
  `hash_collision_with` (read from the raw mapping):
  - if the referenced id is not in `entity_ids_by_kind(raw)["asset"]` → `E_TARGET_UNKNOWN`
    ("...references unknown asset 'X'").
  - elif the referenced id == this asset's own id → `E_TARGET_UNKNOWN` ("...must not
    reference itself").
  - elif the referenced id is not in the *already-seen* set (forward/same-position) →
    `E_TARGET_UNKNOWN` ("... must reference an earlier-declared asset").
  Then add this asset's id to the already-seen set. Use `Reporter` + the `_common`
  helpers (`iter_assets_with_loc`, `entity_ids_by_kind`) exactly as `rule_target_unknown`
  does. Skip non-string field values (Pydantic owns shape).
- [ ] **Step 3:** Register `rule_content_reference` in `semantic._RULES` (after
  `rule_target_unknown`, before lifecycle).
- [ ] **Step 4: Verify.** New tests + `test_invalid_corpus` + full validation suite green.
- [ ] **Commit:** `feat: validate same_content_as/hash_collision references`

## Task 4: `collided_hash_for` pure helper

**Files:**
- Modify: `src/chaos_librarian/materializer/phase_b/oracle_hash.py` (next to `false_hash_for`)
- Test: `tests/materializer/phase_b/test_oracle_hash.py` (or sibling)

- [ ] **Step 1: Write failing tests.** For representative `(referent_hash, real_hash,
  prefix_len)` triples (prefix_len 1, 8, 63), assert the result:
  - matches `SHA256_URI_PATTERN` (`^sha256:[0-9a-f]{64}$`).
  - shares exactly `prefix_len` leading **hex** chars with the referent digest (compare
    on the `sha256:`-stripped 64-char hex of both).
  - differs from both `referent_hash` and `real_hash` at full length.
  - is byte-stable across two calls (determinism).
  - Include a triple that forces the `candidate in (referent_hash, real_hash)` fallback
    branch (construct `real_hash` so the first candidate equals it) and assert the
    fallback still satisfies all the above.
- [ ] **Step 2: Implement** `collided_hash_for(referent_hash: str, real_hash: str,
  prefix_len: int) -> str`. **Define `referent_hash_hex` as the `sha256:`-stripped
  64-char digest** (carry spec-challenge-4 nit 1): `referent_hash_hex =
  referent_hash.removeprefix("sha256:")`. Then:
  ```python
  prefix = referent_hash_hex[:prefix_len]
  suffix = hashlib.sha256(f"{real_hash}:{referent_hash}:{prefix_len}".encode()).hexdigest()[prefix_len:]
  candidate = f"sha256:{prefix}{suffix}"
  if candidate in (referent_hash, real_hash):
      suffix = hashlib.sha256(f"{candidate}:fallback".encode()).hexdigest()[prefix_len:]
      candidate = f"sha256:{prefix}{suffix}"
  return candidate
  ```
  Assert (or rely on the test) that the result matches `SHA256_URI_PATTERN`. Google-style
  docstring noting it is a pure, deterministic prefix-preserving collision.
- [ ] **Step 3: Verify.** New tests + ruff/ty/pytest green.
- [ ] **Commit:** `feat: add collided_hash_for prefix-collision helper`

## Task 5: Collision-aware `augment_manifest`

**Files:**
- Modify: `src/chaos_librarian/materializer/manifest_build.py` (`augment_manifest`)
- Test: `tests/materializer/test_manifest_build.py`

> **Parity note:** `augment_manifest` is called by both `materialize_assets_phase_a`
> (live) and `stamp_phase_a_manifest` (run/replay), both iterating in declaration order
> against an accumulating manifest. Recomputing the collided hash *here* (not in the
> orchestrator) is what makes run == replay == materialize for free — the same property
> `wrong_oracle_hash` relies on. Do NOT compute it in `materialize_assets_phase_a`.

- [ ] **Step 1: Write failing tests** (no ffmpeg — construct a `Manifest` + `Asset` in
  memory):
  - With `asset.hash_collision_with` unset, `augment_manifest` stamps
    `materialized.content_hash` unchanged (backward-compat / no-op branch).
  - With `asset.hash_collision_with = "ref"` and the referent's `ManifestVersion`
    already carrying a known `content_hash`, the collision asset's version gets
    `collided_hash_for(referent_hash, materialized.content_hash, prefix_len)` — shares
    the prefix, differs at full length.
- [ ] **Step 2: Implement.** In `augment_manifest`, after locating the asset's version
  row, before stamping: if `asset.hash_collision_with` is not None, find the referent's
  version (`asset_id == asset.hash_collision_with`) and read its `content_hash`; if
  present, stamp `collided_hash_for(referent_hash, materialized.content_hash,
  asset.collision_prefix_len)`; else stamp `materialized.content_hash` (defensive — the
  validator guarantees the referent is earlier/stamped, so this branch is unreachable in
  practice). Keep the existing sidecar loop unchanged.
- [ ] **Step 3: Verify.** New tests + existing `test_manifest_build` + ruff/ty/pytest green.
- [ ] **Commit:** `feat: stamp collided content_hash in augment_manifest`

## Task 6: Orchestrator copy short-circuit for `same_content_as`

**Files:**
- Modify: `src/chaos_librarian/materializer/synthesis.py` (`materialize_assets_phase_a`)
- Test: `tests/materializer/test_synthesis.py`. **The copy path reads a real referent
  file off disk (`shutil.copyfile`) and runs real ffprobe (`probe_file`), so the unit
  test must (a) inject a fake `materialize_asset` that *writes a real file* to
  `out_dir/"library"/<rendered_relative_path>` for the referent — the existing
  `_fake_materialize_one_asset` writes none — and (b) monkeypatch `synthesis.probe_file`
  (the same seam used at `test_synthesis.py:258/362/442`). Then the copy runs ffmpeg-free
  and the byte-identity / same-hash assertions are exercised on the real copied bytes the
  fake wrote.**

> **Layer note:** the copy lives in the orchestrator loop, not `materialize_one_asset`
> (whose injected signature is unchanged). The orchestrator already computes each asset's
> `rendered_relative_path` and knows `out_dir`; thread an `asset_id ->
> rendered_relative_path` map across the loop.

- [ ] **Step 1: Write failing tests.**
  - A two-asset scenario where asset B has `same_content_as: <A>`: B's written file
    bytes equal A's; B's `MaterializedAsset.content_hash` equals A's; both manifest
    versions carry the same `content_hash`.
  - B's `MaterializedAsset.invocation_index` resolves to a real `phase_a.invocations[i]`
    whose `tool == "same_content_copy"` and `exit_code == 0`.
  - B contributes **no** `ContentSourceEvidence` to `phase_a.content_sources`.
  - B's `probed`/`size_bytes`/`duration_seconds` equal A's (re-probe, not reuse).
- [ ] **Step 2: Implement.** In the `materialize_assets_phase_a` loop:
  - Build `rel_path_by_asset: dict[str, str]` mapping each asset id to its
    `rendered_relative_path` as the loop computes it (the referent is earlier, so its
    entry exists by the time the referrer is reached).
  - When `asset.same_content_as` is set, **skip** the `materialize(...)` call. Instead:
    resolve `referent_rel = rel_path_by_asset[asset.same_content_as]`; copy
    `out_dir/"library"/referent_rel` → `out_dir/"library"/<referrer rendered_relative_path>`
    via `shutil.copyfile` (mkdir parents); compute `content_hash` from the copied file
    (`"sha256:" + sha256(file)`); re-probe the copied file (`probe_file`); append a
    synthetic `ToolInvocation(tool="same_content_copy", version="n/a", command=[...
    referent id, dest path], exit_code=0, duration_ns=<measured>)` to
    `phase_a.invocations`; build a `MaterializedAsset` with
    `invocation_index=len(phase_a.invocations)` (post-append, matching the synthesis
    path), `location_path`, the copied `content_hash`, probed size/duration; append it to
    `phase_a.materialized_assets`; record `probed_by_asset`, `sidecar_hashes_by_asset` = {}
    (empty — forbid-subtitles rule guarantees no sidecars); add **no** `content_sources`.
    Then call `augment_manifest` exactly as the synthesis branch does (so the same full
    `content_hash` is stamped, and any `hash_collision_with` on the duplicate — disallowed
    by mutual-exclusivity, so N/A — would route normally).
  - Keep the synthesis branch (non-`same_content_as`) byte-for-byte unchanged so the
    no-new-fields path is identical (backward compat).
  - Extract the copy into a small `_copy_same_content_asset(...)` helper to keep
    `materialize_assets_phase_a` under the 100-line / complexity-8 limits.
- [ ] **Step 3: Verify.** New tests + `tests/materializer/` + ruff/ty/pytest green.
- [ ] **Commit:** `feat: copy same_content_as bytes in phase-A orchestrator`

## Task 7: Walker-order coupling invariant test

**Files:**
- Create/Modify: `tests/materializer/test_walker_order.py` (or extend a topology test)

- [ ] **Step 1: Write the test.** For a representative multi-tree scenario fixture (≥1
  movie, ≥1 episode, ≥1 track asset — reuse or add a fixture), assert
  `[c.asset["id"] for c in validation_common.iter_asset_contexts(raw)] ==
  [c.asset.id for c in topology.iter_asset_contexts(scenario)]`. Document in the test why
  (the copy/collision correctness depends on the two walkers staying in lockstep).
- [ ] **Step 2: Verify** the test passes on current code (it should — both walk
  movies→episodes→tracks today) and fails if either walker is reordered.
- [ ] **Commit:** `test: pin validation/materializer asset-walker order`

## Task 8: End-to-end materialize + run/replay parity tests

**Files:**
- Test: `tests/materializer/` (env-gated where real ffmpeg/ffprobe is needed)

- [ ] **Step 1: same_content_as end-to-end (env-gated ffmpeg).** Materialize a two-asset
  scenario; assert the two library files are byte-identical and both manifest versions
  carry the same `content_hash`.
- [ ] **Step 2: hash_collision_with end-to-end (env-gated ffmpeg).** Materialize;
  assert the collision asset's manifest `content_hash` shares exactly
  `collision_prefix_len` hex chars with the referent's and differs at full length; the
  on-disk file's real sha256 does **not** share the prefix (oracle-only); the
  `MaterializedAsset.content_hash` is the real on-disk hash.
- [ ] **Step 3: run/replay parity.** For a `hash_collision_with` scenario, assert the
  replayed manifest equals the materialized manifest (full equality incl. the collided
  `content_hash`). Mirror an existing run/replay parity test's harness.
- [ ] **Step 4: cross-feature interaction (locks the one combination the spec permits).**
  A three-asset scenario: A synthesized; B `same_content_as: A` (B's recorded hash = A's
  copied full hash); C `hash_collision_with: B, collision_prefix_len: 8`. Assert C's
  recorded `content_hash` shares exactly 8 hex chars with **B's copied hash** and differs
  at full length — so a collision referencing a duplicate reads the duplicate's stamped
  (copied) hash, as the spec's edge-case section states. (Can be a `augment_manifest`-
  level test if a full ffmpeg run is undesirable.)
- [ ] **Commit:** `test: same-content and collision materialize/replay`

## Task 9: Ship the two recipes

**Files:**
- Create: `recipes/identity/same-content-duplicate.yaml`,
  `recipes/identity/hash-collision-simulation.yaml`
- Modify: `recipes/README.md` (identity table: add both rows)

- [ ] **Step 1:** Author each recipe at `schema_version: 25` with the
  `# Recipe:` / `# Category: identity` / `# Tests:` / `# Expected consumer response:` /
  `# Requires: none` header block (per #108 recipe shape). The
  `hash-collision-simulation` header explicitly states it is an **oracle-recorded**
  prefix collision, not an on-disk sha256 collision. Each declares two assets; the
  duplicate/decoy references the first by id and is declared **after** it.
- [ ] **Step 2:** Add both rows to `recipes/README.md`'s identity table (path / tests /
  expected response / requires).
- [ ] **Step 3: Verify.** `tests/recipes/test_recipe_corpus.py` validates both clean
  (`report.ok is True`, `report.issues == []`); identity still ≥3. Full suite +
  ruff/ty/pytest green.
- [ ] **Commit:** `feat: ship same-content and hash-collision recipes`

## Task 10: Follow-up issues + final guardrail sweep

- [ ] **Step 1:** File the follow-up issue(s) (before the PR; reference in PR body):
  - **Real on-disk nonce-grind collision strategy (Q3a):** title + 2-3 sentences
    pointing at ADR 0004 Q3/Q5 and the oracle-only limitation; surfaced by #180.
  - **`same_content_as` with the asset's own distinct sidecars:** judge plausibility;
    if plausible, file (v1 forbids it — `model_validator`); else note the decision in the
    PR body.
- [ ] **Step 2:** Full sweep: `uv run ruff check`, `uv run ruff format --check`,
  `uv run ty check src tests`, `uv run python -m pytest -q`,
  `uv run python -m chaos_librarian.schema_export --check`. All green, zero warnings.
- [ ] **Step 3:** `/challenge main..HEAD` loop (address findings, commit each pass, until
  approve or 5 iterations).
- [ ] **Commit (if challenge surfaces changes):** one logical change per commit.

---

## Rollback / cleanup

- Each task is an independent commit; revert the offending commit if a task fails its
  guardrails — earlier commits remain green by construction (Task 2 keeps the corpus
  green; every other task is additive/backward-compatible).
- The schema artifact and fixture mass-bump live entirely in Task 2; reverting Task 2
  also reverts the version bump and corpus changes together (no split-brain).

## Verification matrix (acceptance ↔ task)

| Acceptance criterion | Task |
| --- | --- |
| `Asset` accepts new fields; cross-field misuse → `E_FIELD_*` | 1 |
| unknown/self/forward refs → `E_TARGET_UNKNOWN` | 3 |
| `same_content_as` byte-identical + same full hash + synthetic invocation + re-probe + no evidence | 6, 8 |
| `hash_collision_with` shares exactly `prefix_len`, differs full length, deterministic | 4, 5, 8 |
| run/replay manifest == materialize manifest (collision) | 8 |
| walker-order pinned | 7 |
| omitting new fields → byte-identical / same code path | 1, 6 |
| two recipes ship + validate clean | 9 |
| `SCENARIO_SCHEMA_VERSION` 24→25; schema regen; fixtures/recipes bumped | 2 |
| follow-up issue(s) filed | 10 |
