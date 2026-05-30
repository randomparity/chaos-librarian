# Symlink entity + follow/reject policy (#179) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `Asset.symlink: SymlinkTarget | None` so an author can declare that an
asset's path materializes as an `os.symlink`, in one of two mutually-exclusive forms:
an **in-root** asset-id reference (`to_asset`) to another earlier-declared asset's
file, or a **library-escaping** run-dir-relative path (`to_run_dir_path`) resolving
inside the run dir but outside `library/`. This makes the dropped
`scanner/symlink-external` recipe expressible. The follow/reject expectation stays
**documentation prose only** (policy-neutral). `SCENARIO_SCHEMA_VERSION` bumps 26 → 27;
no other schema version changes.

**Architecture:** One flat optional field on `Asset` holding a frozen `SymlinkTarget`
sub-model (`to_asset` xor `to_run_dir_path`), gated by (a) the `SymlinkTarget`
model_validator (exactly-one-form → `E_FIELD_SHAPE`) and (b) extending the existing
`Asset._check_content_dedup_fields` (mutually exclusive with `same_content_as` /
`hash_collision_with` / `hardlinked_to`; forbids own `subtitles` → `E_FIELD_SHAPE`).
The existing `rule_content_reference` resolves the **nested** `symlink.to_asset`
reference (unknown / self / forward → `E_TARGET_UNKNOWN`). A new semantic rule
`rule_symlink_target_escape` classifies `symlink.to_run_dir_path` against a synthetic
run-dir root (in-library / absolute / run-dir-escape → new validate-time code
`E_SYMLINK_TARGET_ESCAPE`); `E_PATH_CONTAINMENT` and `resolve_under_library` are
untouched. The orchestrator `materialize_assets_phase_a` gains a `symlink`
short-circuit (`_symlink_asset`, sibling of `_hardlink_asset`) that checks the
resolved target exists (else fail-loud `E_MATERIALIZE_SYMLINK_TARGET_MISSING`) and
`os.symlink`s the referrer's path to a **run-dir-relative** target
(`os.path.relpath`): synthetic `symlink` `ToolInvocation`, re-probe, no
`ContentSourceEvidence`. The manifest records nothing new (schema-neutral); the link
is observed on disk via `os.path.islink` / `os.readlink`.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, ffmpeg/ffprobe (env-gated for
materialize tests; symlink materializer unit tests use the `probe_file` monkeypatch
seam, no ffmpeg), `uv` / `ruff` / `ty`. Linux/macOS POSIX filesystem (CI:
`ubuntu-latest`); `os.symlink` POSIX semantics.

**Spec:** `docs/superpowers/specs/2026-05-30-issue-179-symlink-entity-policy-design.md`
**ADR:** `docs/adr/0006-symlink-entity-policy.md`

> **Naming note (from spec-challenge iteration 2):** the validate-time code is
> `E_SYMLINK_TARGET_ESCAPE` (lives with the other validate-time `E_*` codes in
> `validation/codes.py`). The materialize-time code follows the existing
> `materializer/errors.py` convention (`E_MATERIALIZE_FS_FAILED`,
> `E_MATERIALIZE_TOOL_FAILED`, …) and is therefore named
> **`E_MATERIALIZE_SYMLINK_TARGET_MISSING`** — the spec/ADR prose uses the shorthand
> `E_SYMLINK_TARGET_MISSING`; implement it as the `E_MATERIALIZE_*`-prefixed name.

---

## Invariants (hold at every commit)

- `uv run ruff check` && `uv run ruff format --check` && `uv run ty check src tests`
  && `uv run python -m pytest -q` are all green. **Never a red commit.**
- `uv run python -m chaos_librarian.schema_export --check` passes (regen + commit in the
  same task that changes a contract model).
- The scenario `schema_version` model literal and the fixture/recipe corpus bump
  together in **one atomic commit** (Task 3) so the corpus tests are never red.

## File structure

| File | Responsibility | Action |
| --- | --- | --- |
| `src/chaos_librarian/contract/scenario.py` | new `SymlinkTarget` model + `Asset.symlink` field + extend `_check_content_dedup_fields`; `schema_version: Literal[27]` | Modify |
| `src/chaos_librarian/contract/__init__.py` | `SCENARIO_SCHEMA_VERSION = 27` | Modify |
| `src/chaos_librarian/validation/codes.py` | add `E_SYMLINK_TARGET_ESCAPE` constant | Modify |
| `src/chaos_librarian/validation/rules/content_reference.py` | resolve nested `symlink.to_asset` (extract helper) | Modify |
| `src/chaos_librarian/validation/rules/symlink_target.py` | new rule `rule_symlink_target_escape` | Create |
| `src/chaos_librarian/validation/semantic.py` | register `rule_symlink_target_escape` in `_RULES` | Modify |
| `src/chaos_librarian/materializer/errors.py` | new `SymlinkTargetMissingError` (`E_MATERIALIZE_SYMLINK_TARGET_MISSING`) | Modify |
| `src/chaos_librarian/materializer/synthesis.py` | orchestrator `os.symlink` short-circuit (`_symlink_asset` helper, existence check, relative target, synthetic invocation, re-probe) | Modify |
| `recipes/scanner/symlink-external.yaml` | new recipe (in-root form) | Create |
| `recipes/README.md` | scanner table: add row | Modify |
| `tests/fixtures/scenarios/**`, `recipes/**` | bump `schema_version: 27` | Modify |
| `tests/fixtures/scenarios/invalid/*.yaml` | new invalid fixtures (refs + cross-field + escape) | Create |
| `tests/fixtures/scenarios/*.yaml` | valid fixtures (in-root + escaping) | Create |
| `schemas/scenario.schema.json` | regenerated | Modify |
| `tests/**` mirroring `src/**` | unit tests | Create/Modify |

---

## Task 1: Add `SymlinkTarget` model + `Asset.symlink` field + extend the model validator

> **Phase-ordering note:** the `schema_version` literal bump is deliberately NOT in this
> task (it lands in Task 3 with the fixtures, atomically). This task adds only the new
> `SymlinkTarget` model + `Asset.symlink` field + validator clauses, all
> backward-compatible (default `None`).

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py` (new `SymlinkTarget` model above
  `Asset` ~line 420; `Asset.symlink` field after `hardlinked_to` ~line 445;
  `_check_content_dedup_fields` ~line 447)
- Test: `tests/contract/test_scenario.py`

- [ ] **Step 1: Write failing contract tests** (build `dict` payloads, call
  `Scenario.model_validate` — AGENTS.md negative-test convention, no kwargs + ignore):
  - accepts an `Asset` with `symlink: {to_asset: "a1"}`.
  - accepts an `Asset` with `symlink: {to_run_dir_path: "external-store/clip.mkv"}`.
  - rejects `symlink: {}` (neither form) → `ValueError`.
  - rejects `symlink: {to_asset: "a1", to_run_dir_path: "x/y"}` (both forms) →
    `ValueError`.
  - rejects `symlink` + `same_content_as` both set → `ValueError`.
  - rejects `symlink` + `hash_collision_with` both set → `ValueError`.
  - rejects `symlink` + `hardlinked_to` both set → `ValueError`.
  - rejects `symlink` on an asset that also declares `subtitles` → `ValueError`.
  - a bare `Asset` (no new field) still validates (backward compat).
- [ ] **Step 2: Implement.**
  - Add a frozen `extra="forbid"` `SymlinkTarget(BaseModel)` with `to_asset: str | None
    = None` and `to_run_dir_path: str | None = None`, plus a `model_validator(mode=
    "after")` `_exactly_one_target` raising `ValueError("symlink requires exactly one of
    to_asset / to_run_dir_path")` when `(to_asset is None) == (to_run_dir_path is None)`.
  - Add to `Asset` (after `hardlinked_to`): `symlink: SymlinkTarget | None = None`.
    Update the field-group comment to mention `symlink` (an `os.symlink` to an in-root
    asset or a library-escaping run-dir path), distinct from the byte/inode fields, and
    that all four link fields are mutually exclusive.
  - Extend `_check_content_dedup_fields`:
    - if `symlink` and `same_content_as` both set → `ValueError`.
    - if `symlink` and `hash_collision_with` both set → `ValueError`.
    - if `symlink` and `hardlinked_to` both set → `ValueError`.
    - if `symlink` set and `self.subtitles` non-empty → `ValueError`.
    Keep messages parallel to the existing exclusivity messages; happy path unindented.
- [ ] **Step 3: Verify.** New tests + full `tests/contract/`; ruff/ty/pytest green.
- [ ] **Commit:** `feat: add symlink asset field and SymlinkTarget model`

## Task 2: Add `E_SYMLINK_TARGET_ESCAPE` code + `rule_symlink_target_escape`

> **Ordering note:** this is a validate-time rule on a backward-compatible field
> (default `None`); it runs green before the version bump because no existing fixture
> declares `symlink`. The new rule and its invalid fixtures land here, but the **valid**
> escaping fixture is deferred to Task 3 (it needs `schema_version: 27`, which would red
> `test_sample_scenarios` if added before the literal bump). Invalid fixtures are also
> deferred to Task 3 for the same reason **unless** they can be authored at v26 — they
> declare `symlink`, a v27 field, so they must be at v27; therefore the invalid fixtures
> for this rule are **created in Task 3's atomic commit** alongside the bump. In Task 2
> the rule is tested by direct-calling it / `run_validation` against in-memory payloads,
> not corpus fixtures.

**Files:**
- Modify: `src/chaos_librarian/validation/codes.py` (add `E_SYMLINK_TARGET_ESCAPE:
  Final = "E_SYMLINK_TARGET_ESCAPE"`)
- Create: `src/chaos_librarian/validation/rules/symlink_target.py`
- Modify: `src/chaos_librarian/validation/semantic.py` (import + add to `_RULES`)
- Test: `tests/validation/rules/test_symlink_target.py` (locate the rule-test dir with
  `rg -l rule_content_reference tests` and mirror its location/style)

- [ ] **Step 1: Write failing tests** (direct-call the rule or `run_validation` on
  in-memory dict payloads at `schema_version: 26` — the rule reads raw mapping, so the
  payload need not be a full valid Scenario; mirror how `test_path_containment` builds
  raw payloads). Assert:
  - `to_run_dir_path: "external-store/clip.mkv"` (outside library, inside run dir) →
    **no** issue.
  - `to_run_dir_path: "library/x/y.mkv"` (inside library) → `E_SYMLINK_TARGET_ESCAPE`.
  - `to_run_dir_path: "library"` (== library dir) → `E_SYMLINK_TARGET_ESCAPE`.
  - `to_run_dir_path: "library/../library/x.mkv"` (reaches into library via `..`) →
    `E_SYMLINK_TARGET_ESCAPE`.
  - `to_run_dir_path: "../escape.mkv"` (escapes run dir) → `E_SYMLINK_TARGET_ESCAPE`.
  - `to_run_dir_path: "/abs/path"` (absolute) → `E_SYMLINK_TARGET_ESCAPE`.
  - a `symlink` with only `to_asset` set → the rule emits **nothing** (it ignores the
    in-root form; `to_asset` is `rule_content_reference`'s job).
  - assert the `loc` points at `symlink.to_run_dir_path`.
- [ ] **Step 2: Implement** `rule_symlink_target_escape(raw, line_index, collector)`:
  - Walk assets with loc (reuse `iter_assets_with_loc` from `rules._common`, as
    `rule_content_reference` does).
  - For each asset, read `asset.get("symlink")`; if it is a mapping, read
    `to_run_dir_path`. If it is not a string, `return`/skip (Pydantic owns shape; the
    `to_asset`-only case has no `to_run_dir_path`).
  - Define `R = Path("/__chaos_librarian_validate__")` (synthetic run dir) and `L = R /
    "library"`. If the value `is_absolute()` → reject. Else `resolved = (R / value).
    resolve(strict=False)`. Classify per the spec's region table:
    - `resolved == R` or `R not in resolved.parents` → reject "escapes the run-dir
      sandbox".
    - `resolved == L` or `L in resolved.parents` → reject "must be outside library/; use
      to_asset for in-root links".
    - else accept (no issue).
    Evaluate the run-dir-escape check **before** the library check (per spec). Emit
    `E_SYMLINK_TARGET_ESCAPE` via `Reporter.error(code=..., message=..., loc=(*asset_loc,
    "symlink", "to_run_dir_path"))`.
  - **Do not** call `resolve_under_library` or touch `E_PATH_CONTAINMENT` — this rule is
    self-contained against the synthetic run-dir root.
  - Register the rule in `semantic.py`'s `_RULES` (import + list entry; place near
    `rule_content_reference`).
- [ ] **Step 3: Verify.** New tests + full validation suite; ruff/ty/pytest green.
  (`schema_export --check` is unaffected — no contract model changed.)
- [ ] **Commit:** `feat: validate escaping symlink targets (E_SYMLINK_TARGET_ESCAPE)`

## Task 3: Bump model literal + fixtures/recipes to 27 + symlink corpus fixtures (atomic)

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py` (`SCENARIO_SCHEMA_VERSION = 27`)
- Modify: `src/chaos_librarian/contract/scenario.py` (`schema_version: Literal[27]`)
- Modify: every `tests/fixtures/scenarios/**` and `recipes/**` file pinning
  `schema_version: 26` (`yaml-parse-error.yaml` left untouched). **Include any
  `schema_version: 26` literal embedded in test source files (inline YAML in
  `tests/materializer/test_synthesis.py` etc.), not only `*.yaml` fixtures.**
- Modify: `src/chaos_librarian/validation/rules/content_reference.py` — resolve nested
  `symlink.to_asset` (see below; folded into this atomic commit so the new valid/invalid
  symlink fixtures pass `test_invalid_corpus`/`test_sample_scenarios` immediately).
- Create valid fixtures (first line `# expected: clean`):
  - `tests/fixtures/scenarios/symlink-in-root.yaml` — two assets, B
    `symlink: {to_asset: <A>}`, A declared first.
  - `tests/fixtures/scenarios/symlink-escaping.yaml` — one asset with
    `symlink: {to_run_dir_path: "external-store/clip.mkv"}`. (Validates clean; the
    target need not exist for validation — validation never touches disk.)
- Create invalid fixtures (first line `# expected: E_<CODE>` — confirm exact code below):
  - `symlink-unknown-ref.yaml` → `# expected: E_TARGET_UNKNOWN`
  - `symlink-self-ref.yaml` → `# expected: E_TARGET_UNKNOWN`
  - `symlink-forward-ref.yaml` → `# expected: E_TARGET_UNKNOWN`
  - `symlink-target-in-library.yaml` → `# expected: E_SYMLINK_TARGET_ESCAPE`
  - `symlink-target-library-boundary.yaml` (`to_run_dir_path: library/../library/x.mkv`
    or `library`) → `# expected: E_SYMLINK_TARGET_ESCAPE`
  - `symlink-target-run-dir-escape.yaml` (`to_run_dir_path: ../escape.mkv`) →
    `# expected: E_SYMLINK_TARGET_ESCAPE`
  - `symlink-and-same-content.yaml` → `# expected: E_FIELD_SHAPE`
  - `symlink-and-hardlinked.yaml` → `# expected: E_FIELD_SHAPE`
  - `symlink-with-subtitles.yaml` → `# expected: E_FIELD_SHAPE`
  - `symlink-both-targets.yaml` (neither/both form via `SymlinkTarget`) →
    `# expected: E_FIELD_SHAPE`
- Modify: `schemas/scenario.schema.json` (regenerate).

> **Confirm-before-fixture note:** the #178/#180 cross-field fixtures
> (`content-dedup-both-set.yaml`) use `# expected: E_FIELD_SHAPE` (the code the pipeline
> maps a model_validator `ValueError` to). Confirm by reading that fixture's first line
> (and, if in doubt, run one payload through `run_validation` and read `report.issues[].
> code`) before writing the markers. The `SymlinkTarget._exactly_one_target` validator
> also raises a `ValueError` → confirm it surfaces as `E_FIELD_SHAPE` the same way (it is
> a nested-model `model_validator`; verify the loc/code with a one-off `run_validation`
> before committing the `symlink-both-targets.yaml` marker).

- [ ] **Step 1:** Bump `SCENARIO_SCHEMA_VERSION` and the model `Literal`.
- [ ] **Step 2:** Mass-bump: replace `schema_version: 26` → `schema_version: 27` on
  **exactly the set `rg -l 'schema_version: 26' tests recipes` returns at execution
  time** (do not rely on a frozen count). **Post-condition:** after the replace,
  `rg -l 'schema_version: 26' tests recipes` returns **only** `yaml-parse-error.yaml`
  (or nothing if it pins a different version) — assert this so no stray v26 file survives
  to red `test_sample_scenarios`.
- [ ] **Step 3:** Extend `rule_content_reference` to resolve nested `symlink.to_asset`
  (see Task-3 sub-detail below), so the new ref fixtures resolve.
- [ ] **Step 4:** Author the valid + invalid symlink fixtures listed above at v27.
- [ ] **Step 5:** `uv run python -m chaos_librarian.schema_export --write`; stage the
  regenerated `schemas/scenario.schema.json`.
- [ ] **Step 6: Verify.** `test_sample_scenarios`, `test_invalid_corpus`,
  `test_recipe_corpus` (recipe ships in Task 5 — until then this asserts existing
  recipes still clean), `schema_export --check`, ruff/ty/pytest all green.
- [ ] **Commit:** `feat: bump SCENARIO_SCHEMA_VERSION 26 -> 27 and add symlink fixtures`

### Task 3 sub-detail — resolve nested `symlink.to_asset` in `rule_content_reference`

The flat `_CONTENT_REFERENCE_FIELDS` tuple drives `_check_reference(asset, field, …)`
by reading `asset.get(field)`. `symlink.to_asset` is **nested**, so it cannot be a tuple
entry. Add a minimal extraction inside `rule_content_reference`'s per-asset loop:

- After the existing `for field in _CONTENT_REFERENCE_FIELDS:` loop, read
  `symlink = asset.get("symlink")`; if it is a mapping and `symlink.get("to_asset")` is
  a string, call `_check_reference(asset=asset, asset_id=asset_id, field="symlink",
  declared_ids=..., seen_ids=..., asset_loc=asset_loc, reporter=reporter)` **but** with
  the reference value sourced from the nested field and the `loc` set to
  `(*asset_loc, "symlink", "to_asset")`.
- Cleanest implementation: generalize `_check_reference` to accept an explicit
  `reference` value and a `loc`, rather than re-reading `asset.get(field)` internally —
  then the flat fields pass `asset.get(field)` + `(*asset_loc, field)` and the nested
  symlink passes `symlink["to_asset"]` + `(*asset_loc, "symlink", "to_asset")`. Update
  the module docstring to name `symlink.to_asset`.
- Tests for this live with the Task-2/Task-3 validation tests: unknown / self / forward
  `symlink.to_asset` → `E_TARGET_UNKNOWN`, loc at `symlink.to_asset`; a valid
  earlier-declared `to_asset` → clean.

## Task 4: Orchestrator `os.symlink` short-circuit + missing-target error

**Files:**
- Modify: `src/chaos_librarian/materializer/errors.py` (new `SymlinkTargetMissingError(
  MaterializationError)` with `error_code = "E_MATERIALIZE_SYMLINK_TARGET_MISSING"`)
- Modify: `src/chaos_librarian/materializer/synthesis.py` (`materialize_assets_phase_a`
  dispatch ~line 156; new `_symlink_asset` helper next to `_hardlink_asset` ~line 258)
- Test: `tests/materializer/test_synthesis.py`. **Reuse the `_file_writing_fake` +
  `monkeypatch.setattr(synthesis_mod, "probe_file", _probe_real_file)` seam (the
  `_hardlink_asset` / `_copy_same_content_asset` test pattern) — the link resolves a real
  on-disk file and re-probes it. Escaping-target tests create the target under the test's
  own tmp run dir (`tmp_path`), never a real system path.**

> **Layer note:** the link lives in the orchestrator loop, not `materialize_one_asset`
> (injected signature unchanged). The orchestrator already builds `rel_path_by_asset`;
> the symlink reuses it for `to_asset` and uses `out_dir / to_run_dir_path` for the
> escaping form.

- [ ] **Step 1: Write failing tests** (no ffmpeg; reuse `_file_writing_fake` +
  `_probe_real_file`):
  - **in-root** (`symlink: {to_asset: <A>}`): B's path `os.path.islink(B) is True`;
    `os.readlink(B)` is a **relative** path (assert `not os.path.isabs(...)`);
    `B.stat()` (follows) equals A's bytes/size; B's `MaterializedAsset.content_hash`
    equals A's; B's `invocation_index` resolves to a `phase_a.invocations[i]` with
    `tool == "symlink"`, `exit_code == 0`; B contributes **no** `ContentSourceEvidence`;
    B re-probed (size/duration equal A's).
  - **replay portability:** after materializing the in-root scenario, copy/move the whole
    `out_dir` tree to a different absolute path (a second `tmp_path` subdir) and assert
    the relocated link still resolves to the target's bytes (relative target survives the
    move). (Use `shutil.copytree(..., symlinks=True)` so the symlink is preserved, not
    dereferenced.)
  - **escaping** (`symlink: {to_run_dir_path: "external-store/clip.mkv"}`): create
    `out_dir/external-store/clip.mkv` (real bytes) before running; assert
    `os.path.islink` true, `os.readlink` relative and pointing at the target, `stat`
    follows it, no exception.
  - **missing target:** an escaping `symlink` whose target file was **not** created →
    `materialize_assets_phase_a` raises `SymlinkTargetMissingError` (assert the type and
    `error_code == "E_MATERIALIZE_SYMLINK_TARGET_MISSING"`), not an unhandled
    `FileNotFoundError`/`ProbeParseError`.
  - **chained** (A synth, B `symlink: {to_asset: A}`, C `symlink: {to_asset: B}`): C is a
    symlink whose resolution follows transitively to A's bytes.
- [ ] **Step 2: Implement.**
  - Add `SymlinkTargetMissingError(MaterializationError)` to `materializer/errors.py`
    with `error_code = "E_MATERIALIZE_SYMLINK_TARGET_MISSING"`; constructor mirrors the
    sibling errors (`asset_id`, `field`, `payload`). Message names the asset id and the
    resolved target path.
  - In `materialize_assets_phase_a`, add a dispatch branch: when `asset.symlink is not
    None`, call `_symlink_asset(asset=asset, out_dir=out_dir, rendered_relative_path=...,
    rel_path_by_asset=rel_path_by_asset, invocation_index=invocation_index)` and skip the
    other branches (the validator guarantees only one link field is set). Place it
    alongside the `hardlinked_to` / `same_content_as` branches.
  - `_symlink_asset`: compute `link_path = out_dir/"library"/rendered_relative_path`.
    Compute the **absolute target**: if `asset.symlink.to_asset is not None` →
    `out_dir/"library"/rel_path_by_asset[asset.symlink.to_asset]`; else →
    `out_dir/asset.symlink.to_run_dir_path`. If `not target.exists()` → raise
    `SymlinkTargetMissingError`. `link_path.parent.mkdir(parents=True, exist_ok=True)`.
    `relative_target = os.path.relpath(target, link_path.parent)`. Measure
    `time.monotonic_ns()` around `os.symlink(relative_target, link_path)`. Compute
    `content_hash` from `link_path` (`open` follows). `probed = probe_file(link_path)`.
    Build synthetic `ToolInvocation(tool="symlink", version="n/a", command=["symlink",
    <to_asset or to_run_dir_path>, str(link_path.relative_to(out_dir))], exit_code=0,
    duration_ns=...)`. Build `MaterializedAsset` (same fields as the hardlink helper:
    `asset_id`, `location_path=str(link_path.relative_to(out_dir))`, `content_hash`,
    `size_bytes`, `duration_seconds`, `invocation_index`, `mp4_moov_placement`). Return
    `MaterializeAssetResult(invocation=..., materialized_asset=..., probed=probed,
    sidecar_hashes={}, content_sources=(), prelude_invocations=())`.
  - **`os.symlink` is non-overwriting (`EEXIST`) — no guard needed; do NOT add
    unlink-first logic** (same rationale as `_hardlink_asset`: phase A writes into a
    freshly-created tree, so `link_path` never pre-exists). Keep it bare.
  - The orchestrator threads `MaterializedAsset.invocation_index` exactly as the
    hardlink/copy/synthesis paths do; match `_hardlink_asset`'s contract precisely.
  - `import os` is already present in `synthesis.py` (used by `_hardlink_asset`).
  - Keep the synthesis branch (no link field set) byte-for-byte unchanged.
- [ ] **Step 3: Verify.** New tests + `tests/materializer/` + ruff/ty/pytest green.
- [ ] **Commit:** `feat: symlink the symlink asset in phase-A orchestrator`

## Task 5: Backward-compat coverage + ship the recipe

**Files:**
- Test: `tests/materializer/test_synthesis.py`
- Create: `recipes/scanner/symlink-external.yaml`
- Modify: `recipes/README.md` (scanner table: add row)

- [ ] **Step 1: Backward-compat test (no ffmpeg).** With `symlink` unset on every asset,
  assert `materialize_assets_phase_a` takes the synthesis branch and never calls
  `os.symlink` (monkeypatch `synthesis_mod.os.symlink` to raise if called, run a no-link
  scenario, assert it does not fire). Pins the "fields-unset assets take the identical
  pre-change path" acceptance criterion. (Mirror the existing `hardlinked_to`
  backward-compat test if one exists — `rg -n "os.link" tests/materializer`.)
- [ ] **Step 2: Author the recipe** at `schema_version: 27`, the **in-root** form, with
  the `# Recipe:` / `# Category: scanner` / `# Tests:` / `# Expected consumer response:`
  / `# Requires: none` header block (read an existing `recipes/scanner/*.yaml` first).
  Two assets in one bundle/variant; the second sets `symlink: {to_asset: <first asset
  id>}`, declared **after** the first, matching `container`. The header states it
  materializes a real **symlink** (in-root, points at another in-library asset's file),
  that a scanner must dedup-by-realpath rather than double-count, and documents the
  follow vs reject expectation in prose. Note in the header that the escaping
  (`to_run_dir_path`) form exists but its end-to-end materialization needs an
  out-of-library target (deferred; see the follow-up issue) — keep the shipped body
  in-root so it validates clean with no external state.
- [ ] **Step 3:** Add the row to `recipes/README.md`'s scanner table (path / tests /
  expected response / requires). Confirm any scanner count/threshold note still holds
  (`recipes/scanner/` grows 5 → 6).
- [ ] **Step 4: Verify.** `tests/recipes/test_recipe_corpus.py` validates the recipe
  clean (`report.ok is True`, `report.issues == []`). Full suite + ruff/ty/pytest green.
- [ ] **Commit:** `feat: ship scanner symlink-external recipe`

## Task 6: Follow-up issues + final guardrail sweep

- [ ] **Step 1:** File the follow-up issue(s) **before** the PR (reference in PR body;
  dedup against existing #189/#191/#192/#193 first — do not file overlaps):
  - **Dangling symlinks + user-authorable escaping-target creation:** v1 requires an
    existing target (missing → `E_MATERIALIZE_SYMLINK_TARGET_MISSING`); true dangling
    support and a materializer that *creates* an out-of-library target need nullable
    probe fields / a distinct symlink manifest record (manifest/materialization schema
    bump). 2-3 sentences + the ADR 0006 Q5 pointer + file:line at `_symlink_asset`. This
    is the single net-new follow-up; confirm it is not already covered by #189/#191/#192/
    #193 (those are sidecars-on-linked/copied assets, cross-device, and in-place mutation
    — distinct), and if any overlaps, comment there instead of filing a duplicate.
- [ ] **Step 2:** Full sweep: `uv run ruff check`, `uv run ruff format --check`,
  `uv run ty check src tests`, `uv run python -m pytest -q`,
  `uv run python -m chaos_librarian.schema_export --check`. All green, zero warnings.
- [ ] **Step 3:** `/challenge main..HEAD` loop (address findings, commit each pass, until
  approve or 5 iterations).
- [ ] **Commit (if challenge surfaces changes):** one logical change per commit.

---

## Rollback / cleanup

- Each task is an independent commit; revert the offending commit if a task fails its
  guardrails — earlier commits remain green by construction (Tasks 1, 2 are additive on a
  default-`None` field / a rule that no existing fixture triggers; Task 3 keeps the
  corpus green atomically; Tasks 4-5 are additive).
- The schema artifact + fixture mass-bump + corpus symlink fixtures live entirely in
  Task 3; reverting Task 3 reverts the version bump, the nested-ref resolver, and the
  corpus changes together (no split-brain).

## Verification matrix (acceptance ↔ task)

| Acceptance criterion | Task |
| --- | --- |
| `Asset` accepts `symlink` (`to_asset` xor `to_run_dir_path`); neither/both → `E_FIELD_SHAPE`; cross-field misuse → `E_FIELD_SHAPE` | 1 (+ corpus 3) |
| unknown/self/forward `symlink.to_asset` → `E_TARGET_UNKNOWN` | 3 (resolver) |
| `to_run_dir_path` in-library/boundary/absolute/run-dir-escape → `E_SYMLINK_TARGET_ESCAPE`; well-formed escaping validates clean, no `E_PATH_CONTAINMENT` | 2 (+ corpus 3) |
| in-root `symlink` materializes a real symlink; `stat` follows to referent; synthetic `symlink` invocation; no evidence; re-probe | 4 |
| escaping `symlink` (tmp target) materializes a real symlink; asset path contained, no `E_PATH_CONTAINMENT` | 4 |
| materialized link target is **relative**; resolves after the tree is relocated (replay-portable) | 4 |
| missing target → `E_MATERIALIZE_SYMLINK_TARGET_MISSING`, not silent skip / unhandled | 4 |
| manifest records resolved hash + each path's location, no link flag/target (schema-neutral) | 4 |
| omitting `symlink` → byte-identical / same code path, no `os.symlink` | 5 |
| one scanner recipe ships + validates clean | 5 |
| `SCENARIO_SCHEMA_VERSION` 26→27; schema regen; fixtures/recipes bumped | 3 |
| follow-up issue(s) filed/deduped | 6 |
