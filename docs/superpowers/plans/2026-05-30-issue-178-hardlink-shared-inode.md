# Hardlink shared-inode asset (#178) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `Asset.hardlinked_to: str | None` so an author can declare that an asset's
path is a **hardlink** (shared inode, link count >= 2, byte-identical content, same full
`content_hash`) to another asset's already-materialized file, making the
`scanner/hardlink-duplicates` recipe a valid scenario. `SCENARIO_SCHEMA_VERSION` bumps
25 → 26; no other schema version changes.

**Architecture:** One flat optional field on `Asset`, gated by extending the existing
`_check_content_dedup_fields` model validator (mutually exclusive with `same_content_as`
and `hash_collision_with`; forbids the asset's own `subtitles`). The existing semantic
rule `rule_content_reference` resolves the asset-id reference by adding `"hardlinked_to"`
to its `_CONTENT_REFERENCE_FIELDS` tuple (unknown / self / forward → `E_TARGET_UNKNOWN`).
The orchestrator `materialize_assets_phase_a` gains a `hardlinked_to` short-circuit
(near-twin of `_copy_same_content_asset`) that `os.link`s the referrer's path to the
referent's already-written file: synthetic `hardlink` `ToolInvocation`, re-probe, no
`ContentSourceEvidence`. The manifest records nothing new (schema-neutral); the shared
inode is observed on disk.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, ffmpeg/ffprobe (env-gated for
materialize tests), `uv` / `ruff` / `ty`. Linux/macOS POSIX filesystem (CI:
`ubuntu-latest`).

**Spec:** `docs/superpowers/specs/2026-05-30-issue-178-hardlink-shared-inode-design.md`
**ADR:** `docs/adr/0005-hardlink-shared-inode.md`

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
| `src/chaos_librarian/contract/scenario.py` | new `Asset.hardlinked_to` field + extend `_check_content_dedup_fields`; `schema_version: Literal[26]` | Modify |
| `src/chaos_librarian/contract/__init__.py` | `SCENARIO_SCHEMA_VERSION = 26` | Modify |
| `src/chaos_librarian/validation/rules/content_reference.py` | add `"hardlinked_to"` to `_CONTENT_REFERENCE_FIELDS` | Modify |
| `src/chaos_librarian/materializer/synthesis.py` | orchestrator `os.link` short-circuit for `hardlinked_to` (`_hardlink_asset` helper, synthetic invocation, re-probe) | Modify |
| `recipes/scanner/hardlink-duplicates.yaml` | new recipe | Create |
| `recipes/README.md` | scanner table: add row | Modify |
| `tests/fixtures/scenarios/**`, `recipes/**` | bump `schema_version: 26` | Modify |
| `tests/fixtures/scenarios/invalid/*.yaml` | new invalid fixtures (refs + cross-field) | Create |
| `schemas/scenario.schema.json` | regenerated | Modify |
| `tests/**` mirroring `src/**` | unit tests | Create/Modify |

---

## Task 1: Add `Asset.hardlinked_to` + extend the model validator (no version bump yet)

> **Phase-ordering note:** the `schema_version` literal bump is deliberately NOT in this
> task. Bumping the model's `Literal[26]` while the fixtures are still at 25 would make
> `test_sample_scenarios` (which `Scenario.model_validate`s every fixture) red. Task 2
> bumps the model literal AND the fixtures in one atomic commit. This task adds only the
> new `Asset` field + validator clauses, which are backward-compatible (default `None`)
> and do not touch the `schema_version` literal.

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py` (`Asset`, ~line 420;
  `_check_content_dedup_fields`, ~line 443)
- Test: `tests/contract/test_scenario.py`

- [ ] **Step 1: Write failing contract tests.** Build `dict` payloads and call
  `Scenario.model_validate` (AGENTS.md negative-test convention — no kwargs + ignore):
  - accepts an `Asset` with `hardlinked_to: "a1"`.
  - rejects `hardlinked_to` + `same_content_as` both set (`ValueError`).
  - rejects `hardlinked_to` + `hash_collision_with` both set (`ValueError`).
  - rejects `hardlinked_to` on an asset that also declares `subtitles`.
  - a bare `Asset` (no new field) still validates (backward compat).
- [ ] **Step 2: Implement.** Add to `Asset` (after `collision_prefix_len`):
  `hardlinked_to: str | None = None`. Update the field-group comment to mention the new
  field and that it is a *hardlink* (shared inode via `os.link`), distinct from
  `same_content_as`'s byte copy. Extend `_check_content_dedup_fields`:
  - if `hardlinked_to` and `same_content_as` both set → `ValueError`.
  - if `hardlinked_to` and `hash_collision_with` both set → `ValueError`.
  - if `hardlinked_to` set and `self.subtitles` non-empty → `ValueError`.
  Keep messages parallel to the existing exclusivity messages; keep the happy path
  unindented.
- [ ] **Step 3: Verify.** New tests + full `tests/contract/`; ruff/ty/pytest green.
- [ ] **Commit:** `feat: add hardlinked_to asset field`

## Task 2: Bump model literal + all fixtures/recipes to 26 (one atomic commit)

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py` (`SCENARIO_SCHEMA_VERSION = 26`)
- Modify: `src/chaos_librarian/contract/scenario.py` (`schema_version: Literal[26]`)
- Modify: every `tests/fixtures/scenarios/**` and `recipes/**` file pinning
  `schema_version: 25` (`yaml-parse-error.yaml` left untouched — it never parses and
  pins an old version deliberately). **This includes any `schema_version: 25` literal
  embedded in test source files (e.g. the inline YAML in `tests/materializer/
  test_synthesis.py`), not only `*.yaml` fixtures.**
- Modify: `schemas/scenario.schema.json` (regenerate).

- [ ] **Step 1:** Bump `SCENARIO_SCHEMA_VERSION` and the model `Literal`.
- [ ] **Step 2:** Mass-bump fixtures/recipes/test-sources: replace `schema_version: 25`
  → `schema_version: 26` on **exactly the set `rg -l 'schema_version: 25' tests recipes`
  returns at execution time** (do not rely on a frozen count). **Post-condition:** after
  the replace, `rg -l 'schema_version: 25' tests recipes` must return **only**
  `yaml-parse-error.yaml` (the deliberately-pinned never-parses fixture) — assert this so
  no stray v25 file survives to red `test_sample_scenarios` after the literal bump. (If
  `yaml-parse-error.yaml` pins a version other than 25, the post-condition is simply that
  the command returns nothing.)
- [ ] **Step 3:** `uv run python -m chaos_librarian.schema_export --write` and stage the
  regenerated `schemas/scenario.schema.json`.
- [ ] **Step 4: Verify.** `test_sample_scenarios`, `test_invalid_corpus`,
  `test_recipe_corpus`, `schema_export --check`, ruff/ty/pytest all green.
- [ ] **Commit:** `feat: bump SCENARIO_SCHEMA_VERSION 25 -> 26`

## Task 3: Extend `rule_content_reference` to resolve `hardlinked_to`

**Files:**
- Modify: `src/chaos_librarian/validation/rules/content_reference.py`
  (`_CONTENT_REFERENCE_FIELDS` tuple + module docstring)
- Modify/Create: `tests/validation/rules/test_content_reference.py` (or wherever the
  #180 reference-rule tests live — locate with `rg -l rule_content_reference tests`)
- Create invalid fixtures under `tests/fixtures/scenarios/invalid/` (each with the
  `# expected: E_<CODE>` first-line marker required by `test_invalid_corpus`):
  - `hardlink-unknown-ref.yaml` → `# expected: E_TARGET_UNKNOWN`
  - `hardlink-self-ref.yaml` → `# expected: E_TARGET_UNKNOWN`
  - `hardlink-forward-ref.yaml` → `# expected: E_TARGET_UNKNOWN`
  - `hardlink-and-same-content.yaml` → `# expected: E_FIELD_SHAPE` (model_validator
    exclusivity; confirm code below)
  - `hardlink-with-subtitles.yaml` → `# expected: E_FIELD_SHAPE` (model_validator
    forbid-subtitles; confirm code below)

> **Confirm-before-fixture note:** the #180 cross-field fixtures
> (`content-dedup-both-set.yaml`) use `# expected: E_FIELD_SHAPE`, the code the pipeline
> maps a model_validator `ValueError` to. Confirm by reading
> `tests/fixtures/scenarios/invalid/content-dedup-both-set.yaml`'s first line (and, if in
> doubt, run one payload through `run_validation` and read back `report.issues[].code`)
> before writing the markers. Use that exact code.

- [ ] **Step 1: Write failing tests.** Run `run_validation` (or direct-call the rule)
  asserting `E_TARGET_UNKNOWN` for a `hardlinked_to`: unknown ref, self-ref,
  forward/same-position ref; and `report.ok` for a valid earlier-declared `hardlinked_to`
  ref. Assert the `loc` points at the `hardlinked_to` field. These mirror the existing
  `same_content_as` reference tests.
- [ ] **Step 2: Implement.** Add `"hardlinked_to"` to `_CONTENT_REFERENCE_FIELDS` and
  update the module docstring to name the field. No other change — the walk, the
  declared-id set, the seen-set, and the three `E_TARGET_UNKNOWN` branches already handle
  any field in the tuple uniformly.
- [ ] **Step 3: Verify.** New tests + `test_invalid_corpus` + full validation suite green.
- [ ] **Commit:** `feat: validate hardlinked_to references`

## Task 4: Orchestrator `os.link` short-circuit for `hardlinked_to`

**Files:**
- Modify: `src/chaos_librarian/materializer/synthesis.py` (`materialize_assets_phase_a`,
  ~line 155 dispatch; new `_hardlink_asset` helper next to `_copy_same_content_asset`,
  ~line 194)
- Test: `tests/materializer/test_synthesis.py`. **The link path reads a real referent
  file off disk (`os.link`) and re-probes it, so the unit test reuses the #180
  `_file_writing_fake` (writes a real file for the referent) + `monkeypatch.setattr(
  synthesis_mod, "probe_file", _probe_real_file)` seam — the exact pattern in
  `test_same_content_as_copies_referent_bytes` (`test_synthesis.py:1142`).**

> **Layer note:** the link lives in the orchestrator loop, not `materialize_one_asset`
> (whose injected signature is unchanged). The orchestrator already builds
> `rel_path_by_asset` for the `same_content_as` path; the hardlink reuses that map.

- [ ] **Step 1: Write failing tests** (no ffmpeg; reuse `_file_writing_fake` +
  `_probe_real_file`):
  - A two-asset scenario where asset B has `hardlinked_to: <A>`:
    - `B_file.stat().st_ino == A_file.stat().st_ino` and
      `B_file.stat().st_dev == A_file.stat().st_dev` (shared inode — the link-not-copy
      proof).
    - `A_file.stat().st_nlink >= 2` and `B_file.stat().st_nlink >= 2`.
    - B's written bytes equal A's; B's `MaterializedAsset.content_hash` equals A's; both
      manifest versions carry the same `content_hash`.
    - B's `MaterializedAsset.invocation_index` resolves to a real
      `phase_a.invocations[i]` whose `tool == "hardlink"` and `exit_code == 0`.
    - B contributes **no** `ContentSourceEvidence` to `phase_a.content_sources`.
    - B's `size_bytes`/`duration_seconds` equal A's (re-probe).
  - Mutation-propagation (corroborating): write new bytes to A's path and assert reading
    B's path returns them (shared inode). Keep this secondary to the `st_ino` assertion.
  - Chained hardlink (A synth, B `hardlinked_to: A`, C `hardlinked_to: B`): all three
    share one `st_ino`; `st_nlink == 3`.
  - Hardlink to a `same_content_as` duplicate (A synth, B `same_content_as: A`,
    C `hardlinked_to: B`): C shares B's `st_ino` (not A's); B's `st_nlink == 2`.
- [ ] **Step 2: Implement.**
  - In `materialize_assets_phase_a`, add a branch before the existing `same_content_as`
    branch (or as an `elif`/dispatch on whichever single link field is set — they are
    mutually exclusive per the validator): when `asset.hardlinked_to is not None`, call a
    new `_hardlink_asset(...)` and skip the `materialize(...)` synthesis call.
  - `_hardlink_asset(*, asset, out_dir, rendered_relative_path, referent_rel_path,
    invocation_index)` — a near-twin of `_copy_same_content_asset`: resolve
    `referent_path = out_dir/"library"/referent_rel_path` and `output_path =
    out_dir/"library"/rendered_relative_path`; `output_path.parent.mkdir(parents=True,
    exist_ok=True)`; measure `time.monotonic_ns()` around `os.link(referent_path,
    output_path)`; compute `content_hash` from `output_path`; `probed =
    probe_file(output_path)`; build a synthetic `ToolInvocation(tool="hardlink",
    version="n/a", command=["link", asset.hardlinked_to or "", str(output_path.relative_to(
    out_dir))], exit_code=0, duration_ns=...)`; build `MaterializedAsset` (same fields as
    the copy helper); return `MaterializeAssetResult(invocation=..., materialized_asset=...,
    probed=probed, sidecar_hashes={}, content_sources=(), prelude_invocations=())`.
  - The orchestrator threads the referrer's `MaterializedAsset.invocation_index` exactly
    as the copy/synthesis paths do (`model_copy(update={"invocation_index":
    len(phase_a.invocations)})` then append the invocation), so do **not** also set it in
    the helper differently — match `_copy_same_content_asset`'s contract precisely.
  - Add `import os` to `synthesis.py` if not already imported.
  - Keep the synthesis branch (neither link field set) byte-for-byte unchanged so the
    no-new-field path is identical (backward compat).
- [ ] **Step 3: Verify.** New tests + `tests/materializer/` + ruff/ty/pytest green.
- [ ] **Commit:** `feat: hardlink hardlinked_to asset in phase-A orchestrator`

## Task 5: Backward-compat + walker-order coverage check

**Files:**
- Test: `tests/materializer/test_synthesis.py`, `tests/materializer/test_walker_order.py`

- [ ] **Step 1: Backward-compat test (no ffmpeg).** With `hardlinked_to` unset on every
  asset, assert `materialize_assets_phase_a` takes the synthesis branch and never calls
  `os.link` (monkeypatch `synthesis_mod.os.link` — or a thin wrapper — to raise if
  called, then run a no-link scenario and assert it does not fire). This pins the
  "fields-unset assets take the identical pre-change path" acceptance criterion.
- [ ] **Step 2: Walker-order.** Confirm the #180 walker-order invariant test
  (`tests/materializer/test_walker_order.py`) still passes and that it is
  field-independent (it pins asset-id *order*, which protects `hardlinked_to`'s
  earlier-declaration rule transitively). No new walker-order test is needed; add a
  one-line comment in the existing test (or this plan note) recording that
  `hardlinked_to` also depends on it. If the existing test does not exist on the branch,
  create it per the #180 plan Task 7 shape.
- [ ] **Step 3: Verify.** Full `tests/materializer/` + ruff/ty/pytest green.
- [ ] **Commit:** `test: pin hardlinked_to backward-compat and walker order`

## Task 6: Ship the recipe

**Files:**
- Create: `recipes/scanner/hardlink-duplicates.yaml`
- Modify: `recipes/README.md` (scanner table: add row)

- [ ] **Step 1:** Author the recipe at `schema_version: 26` with the
  `# Recipe:` / `# Category: scanner` / `# Tests:` / `# Expected consumer response:` /
  `# Requires: none` header block (match the existing `recipes/scanner/*.yaml` shape —
  read one first). It declares two assets in one bundle/variant; the second sets
  `hardlinked_to: <first asset id>` and is declared **after** the first, with a matching
  `container`. The header states it materializes a real **hardlink** (shared inode, link
  count 2), distinct from `identity/same-content-duplicate`'s independent byte copy.
- [ ] **Step 2:** Add the row to `recipes/README.md`'s scanner table (path / tests /
  expected response / requires). Confirm the scanner count/threshold note (if any) still
  holds.
- [ ] **Step 3: Verify.** `tests/recipes/test_recipe_corpus.py` validates the recipe
  clean (`report.ok is True`, `report.issues == []`). Full suite + ruff/ty/pytest green.
- [ ] **Commit:** `feat: ship scanner hardlink-duplicates recipe`

## Task 7: Follow-up issues + final guardrail sweep

- [ ] **Step 1:** File the follow-up issue(s) (before the PR; reference in PR body):
  - **`EXDEV` cross-device hardlink rule:** only needed if library roots are ever mapped
    to distinct filesystems; today all assets share one `<run-dir>/library/` tree, so the
    rule would be dead (ADR 0005 Q4). 2-3 sentences + the ADR pointer.
  - **In-place-mutation timeline action on a hardlinked path:** byte-rewriting actions
    today write a new file (breaking the link); an action that mutates the shared inode
    in place is out of scope (ADR 0005 Q5). File if a recipe is identified that needs it;
    else note the decision in the PR body.
  - **`hardlinked_to` with the asset's own distinct sidecars:** v1 forbids it
    (model_validator), same as `same_content_as`. File if plausibly wanted; else note in
    the PR body.
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
| `Asset` accepts `hardlinked_to`; cross-field misuse → `E_FIELD_SHAPE` | 1 |
| unknown/self/forward `hardlinked_to` refs → `E_TARGET_UNKNOWN` | 3 |
| two linked assets share one inode (`st_ino`/`st_dev`), `st_nlink >= 2`, same full hash, synthetic `hardlink` invocation, re-probe, no evidence | 4 |
| writing through one path reflected on the other (shared inode) | 4 |
| manifest records shared hash + each path's location, no inode/link field | 4 |
| omitting `hardlinked_to` → byte-identical / same code path, no `os.link` | 5 |
| one scanner recipe ships + validates clean | 6 |
| `SCENARIO_SCHEMA_VERSION` 25→26; schema regen; fixtures/recipes bumped | 2 |
| follow-up issue(s) filed | 7 |
