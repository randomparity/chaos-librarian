# Issue #179 — Author symlink assets (in-root and library-escaping)

> Status: Draft · Sprint: issue-179 · Schema impact: SCENARIO_SCHEMA_VERSION 26 → 27

## Problem

The scanner-resilience recipe category (surfaced by #108) cannot express
`scanner/symlink-external` because the scenario schema has no symlink concept and,
worse, the one shape the recipe needs — a link whose **target escapes the library
root** — is exactly what `E_PATH_CONTAINMENT` forbids for every authored path. This
shape was dropped from #108 (see that spec's "Dropped proposals", row
`scanner/symlink-external`: "Paths outside a library root are rejected by
`E_PATH_CONTAINMENT`").

A symlink is a chaos shape a scanner must handle: a directory entry that is a
**pointer to another path**, not a file with its own bytes. A scanner must decide
whether to **follow** it (treat the target as the asset) or **reject/skip** it
(refuse to leave the library root). Two sub-shapes stress that decision:

- **in-root symlink** — points at another materialized asset inside `library/`. A
  scanner that follows it sees a duplicate of an in-library file; one that dedups by
  realpath must not double-count it.
- **library-escaping symlink** — points outside `library/` (to a sibling path under
  the run dir). A scanner with a containment policy must refuse to follow it out of
  the scanned root; one that blindly follows leaks outside its boundary.

## Relationship to the three existing reference fields (critical distinction)

`same_content_as` (#180), `hash_collision_with` (#180), and `hardlinked_to` (#178)
are all **asset-id references to an earlier asset whose real file already exists**,
and all produce a **real file** at the referrer's path:

| field | primitive | on-disk object at referrer path | target may escape `library/`? | target may be absent? |
| --- | --- | --- | --- | --- |
| `same_content_as` | `shutil.copyfile` | independent regular file | no | no |
| `hardlinked_to` | `os.link` | second dir-entry, shared inode | no | no |
| `symlink` (this issue) | `os.symlink` | a **symlink** (`os.path.islink` true) | **yes (in-root vs escaping)** | deferred (v1: target exists) |

A symlink differs fundamentally on two axes the prior three never touch:

1. **The materialized object is not a regular file — it is a symlink.** `os.stat`
   follows it; `os.lstat`/`os.path.islink` reveals it. The consumer's job is to
   detect the link and apply a follow/reject policy.
2. **The target may point outside the library root.** This is the entire point of
   `scanner/symlink-external`, and it collides head-on with `E_PATH_CONTAINMENT`.

**Decision: `symlink` is a fourth, parallel concept** that reuses the
reference-resolution machinery (asset-id reference, earlier-declaration requirement,
`E_TARGET_UNKNOWN`, orchestrator short-circuit, synthetic ToolInvocation,
schema-neutral manifest) but (a) swaps the primitive to `os.symlink`, (b) adds a
second target form for the escaping case, and (c) introduces exactly one new error
code for the one place the contract genuinely differs. Rationale and rejected
alternatives: [ADR 0006](../../adr/0006-symlink-entity-policy.md).

## Policy-neutrality decision (the load-bearing constraint)

chaos-librarian is **policy-neutral**: AGENTS.md states it "does NOT know the
application's expected policy outcomes — it emits neutral oracle journals and
manifests." The #108 spec lists "Encoding the consumer's expected policy outcome in
machine-readable form" as an explicit **non-goal** ("expected-response text is
documentation only").

**The follow/reject expectation is therefore NOT machine-encoded.** There is no
`symlink_expected_policy` field and no `D_SYMLINK_POLICY` divergence code. v1 records
only **neutral on-disk facts**: the entry is a symlink, its target, and its nature
(in-root vs escaping). The expected follow/reject behavior lives in the recipe's
header-doc prose ("Expected consumer response: …"), exactly like every other #108
recipe. The consumer-under-test observes `os.path.islink` + the link target on disk
and applies its own policy; chaos-librarian does not pre-judge it. (ADR 0006 Q1.)

## Goals

- Add a `symlink` authoring knob on `Asset` so an author can declare that an asset's
  path materializes as an `os.symlink`, in one of two mutually-exclusive forms:
  - **`to_asset: <asset-id>`** — an in-root link to another **earlier-declared**
    asset's already-materialized file (target resolves inside `library/`).
  - **`to_run_dir_path: <relative path>`** — a library-escaping link whose target
    resolves **inside the run dir but outside `library/`** ("external to the library
    root, internal to the sandbox").
- Materialize the link with `os.symlink(target, link_path)` from a new orchestrator
  helper `_symlink_asset` (a sibling of `_copy_same_content_asset` /
  `_hardlink_asset`), in the single declaration-ordered pass.
- Keep `E_PATH_CONTAINMENT` and the path-safety helpers **byte-for-byte unchanged**:
  the asset's own path still flows through the normal renderer + containment check
  and stays contained; the symlink **target** is never fed to
  `resolve_under_library`. (ADR 0006 Q2.)
- Constrain an escaping target to resolve **within the run dir** (outside `library/`,
  inside `<run-dir>/`); a target escaping the run dir is rejected with the new
  `E_SYMLINK_TARGET_ESCAPE` code so a recipe can never materialize a link to a host
  path. (ADR 0006 Q3, Q4.)
- Record **nothing new** in the manifest/oracle: the symlink-ness is observed on disk
  via `os.path.islink` + the on-disk link target, exactly as #178's shared inode is
  observed via `st_ino`. `MANIFEST_SCHEMA_VERSION` / `MATERIALIZATION_SCHEMA_VERSION`
  / `REPLAY_BUNDLE_SCHEMA_VERSION` stay put; only `SCENARIO_SCHEMA_VERSION` bumps
  26 → 27. (ADR 0006 Q6.)
- Reject reference/shape errors at validate time with the established codes:
  `E_TARGET_UNKNOWN` for unknown/self/forward `to_asset` references (mirroring
  #178/#180), `E_FIELD_SHAPE` for cross-field misuse, and the one new
  `E_SYMLINK_TARGET_ESCAPE` for a `to_run_dir_path` that escapes the run dir.
- Make `symlink` **mutually exclusive** with `same_content_as`, `hash_collision_with`,
  and `hardlinked_to` on the same asset, and forbidden on an asset declaring its own
  `subtitles` (mirroring the prior three).
- Preserve backward compatibility: every existing scenario/recipe stays valid (beyond
  the mandatory `schema_version: 27` bump), and an asset with `symlink` unset executes
  the **identical pre-change** synthesis/copy/link/stamp path.

## Non-goals

- **Dangling symlinks (target absent) and user-authored escaping-target creation.** A
  dangling link has no bytes to `probe_file`, so it cannot get the
  `content_hash`/`size`/`duration` every `MaterializedAsset` carries today; supporting
  it forces nullable probe fields or a distinct symlink manifest record — a
  manifest/materialization schema bump beyond the scenario bump. v1 ships only links
  whose target **exists** at materialize time, enforced by the materialize-time
  existence check (`E_SYMLINK_TARGET_MISSING`, fail loud — see Materialization). A
  fully user-authorable escaping target that nothing pre-creates (i.e. a recipe that
  declares an escaping `to_run_dir_path` and expects the materializer to create the
  target) depends on the same target-authoring / dangling work and is deferred to the
  filed follow-up. (ADR 0006 Q5.)
- **Machine-encoding the follow/reject expectation.** Out of scope by the
  policy-neutrality decision above; documentation prose only. (ADR 0006 Q1.)
- **Links to host paths (targets escaping the run dir).** Forbidden by
  `E_SYMLINK_TARGET_ESCAPE`; the sandbox boundary is the run dir. (ADR 0006 Q3.)
- **A first-class symlink entity / N-way link registry.** A symlink is one optional
  field on `Asset`, matching the flat-field convention of the prior three. (ADR 0006
  Q7.)
- **Absolute-path targets.** `to_run_dir_path` is a relative path interpreted under
  the run dir; absolute targets are rejected (they would escape the sandbox or be
  non-deterministic). In-root targets are expressed as an asset-id, never a raw path.
- **Recording the link target in the manifest.** The manifest records the referrer's
  normal location and a re-probe of the resolved target; the link-ness and the
  (run-dir-relative) target are observed on disk via `os.path.islink` / `os.readlink`.
  Recording the target would add a versioned-schema field with no consumer contract
  (cf. #178's inode reasoning).

## Ground truth: how assets are written, how identity is recorded, where containment runs

Verified against `contract/scenario.py`, `contract/manifest.py`,
`contract/materialization.py`, `contract/paths.py`, `materializer/synthesis.py`,
`materializer/manifest_build.py`, `materializer/run.py`,
`validation/rules/content_reference.py`, `validation/rules/path_containment.py`, and
`validation/rules/asset_path_safety.py` on the branch base (post-#178, schema v26).

- `materialize_assets_phase_a` (`synthesis.py:132`) iterates assets in **declaration
  order** (`iter_asset_contexts`), threading an `asset_id -> rendered_relative_path`
  map (`rel_path_by_asset`) across the loop. It dispatches on the single set
  reference field: `hardlinked_to` → `_hardlink_asset`, `same_content_as` →
  `_copy_same_content_asset`, else the injected `materialize_one_asset`. It then
  appends one `ToolInvocation`, one `MaterializedAsset`, and calls `augment_manifest`.
- `_hardlink_asset` (`synthesis.py:258`) is the exact template for the symlink path:
  it resolves the referent's already-written file at `out_dir / "library" /
  referent_rel_path`, performs the filesystem op, computes `content_hash` from the
  resulting file, **re-probes** it, and returns a `MaterializeAssetResult` with a
  synthetic `ToolInvocation`, empty `sidecar_hashes`, and empty `content_sources`.
- `out_dir` **is the run dir**; `out_dir / "library"` is the library root
  (`run.py:188` passes `library_root = ctx.out_dir / "library"`). So an escaping
  target resolves under `out_dir` but outside `out_dir / "library"`.
- The asset's own path is **rendered** from `id` / `role` / `container` / hierarchy
  (`render_asset_path`) and checked by `rule_asset_id_container_safe`
  (`asset_path_safety.py`); it never carries a free-form escaping path. So the asset
  path is **naturally contained** and needs no change — only the new target field
  could escape, and it is a separate field never fed to `resolve_under_library`.
- `rule_content_reference` (`content_reference.py`) walks assets in declaration order
  and emits `E_TARGET_UNKNOWN` for unknown/self/forward references, driven by
  `_CONTENT_REFERENCE_FIELDS = ("same_content_as", "hash_collision_with",
  "hardlinked_to")`. The in-root `symlink.to_asset` reference plugs into the same
  resolver (see "Reference resolution").
- `augment_manifest` (`manifest_build.py:21`) stamps `version.content_hash` and the
  asset's rows. **No row records link-ness or a target today**, and this change adds
  none.

## Design

### New field on `Asset`: a `symlink` sub-model

One flat optional field on the single frozen `extra="forbid"` `Asset` model, holding
a small frozen `extra="forbid"` sub-model with two mutually-exclusive target forms:

```python
class SymlinkTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    to_asset: str | None = None          # in-root: id of an earlier-declared asset
    to_run_dir_path: str | None = None   # escaping: relative path under the run dir

    @model_validator(mode="after")
    def _exactly_one_target(self) -> SymlinkTarget:
        if (self.to_asset is None) == (self.to_run_dir_path is None):
            raise ValueError("symlink requires exactly one of to_asset / to_run_dir_path")
        return self
```

`Asset` gains `symlink: SymlinkTarget | None = None`.

**Why a sub-model with two named forms, not a single string + a `kind` enum or a raw
path** (ADR 0006 Q7):

- The in-root case is an **asset-id reference** (resolves to that asset's rendered
  path), reusing `E_TARGET_UNKNOWN` and the earlier-declaration requirement verbatim.
  A raw-path form there would re-derive the asset's rendered path and duplicate
  path-rendering logic.
- The escaping case is a **path** (there is no asset at the target), so it cannot be
  an asset-id. A single string field cannot cleanly carry both an id and a path.
- "Exactly one of two named fields" is the same shape `hash_collision_with` +
  `collision_prefix_len` already use; it reads unambiguously and the
  `SymlinkTarget._exactly_one_target` validator localizes the shape rule.

### `Asset` model_validator (cross-field exclusivity)

The existing `Asset._check_content_dedup_fields` (`scenario.py:447`) is extended.
New rules (each raising `ValueError`, surfaced as `E_FIELD_SHAPE`, exactly as the
existing exclusivity checks):

- `symlink` is **mutually exclusive** with each of `same_content_as`,
  `hash_collision_with`, `hardlinked_to` (an asset is a symlink, a copy, a hardlink,
  or a collision decoy — never two at once).
- `symlink` is **forbidden** on an asset declaring its own `subtitles` (same reasoning
  the prior three apply: the asset materializes a link, not synthesized bytes, so its
  own track/sidecar spec is ignored and the link path writes no sidecars).

These are shape errors local to one asset, so they live in the Pydantic validator and
surface as `E_FIELD_SHAPE`.

### Reference resolution for `symlink.to_asset` (semantic rule, `E_TARGET_UNKNOWN`)

The in-root reference is resolved by extending `rule_content_reference`. Because the
reference is **nested** (`symlink.to_asset`, not a flat `asset[field]`), the rule
reads the nested value rather than adding `"symlink"` to the flat
`_CONTENT_REFERENCE_FIELDS` tuple. A small extraction (`_symlink_to_asset(asset)`)
yields the nested id (or `None`), and the existing `_check_reference` machinery emits
`E_TARGET_UNKNOWN` when the referenced id is:

- **not a declared asset id** (dangling reference),
- **the asset's own id** (self-reference — symlinking to yourself is meaningless), or
- **declared later** than the referrer (forward / same-position reference).

The earlier-declaration requirement is load-bearing and identical to the prior three:
`os.symlink`'s target file must **already exist** on disk (v1 requires an existing
target), which it does only if the referent materialized earlier in the single
declaration-ordered pass. Reusing `E_TARGET_UNKNOWN` for the forward case is the same
documented stretch #178/#180 established (ADR 0004 Q4 / ADR 0005 Q2).

`symlink.to_run_dir_path` is **not** an asset reference and is not resolved here; its
containment is a separate rule (next).

### Escaping-target containment (new semantic rule, `E_SYMLINK_TARGET_ESCAPE`)

A new rule `rule_symlink_target_escape` (in
`validation/rules/symlink_target.py`) checks every `symlink.to_run_dir_path`:

**Exact region predicate.** Let `R = <synthetic-run-dir>` and `L = R / "library"`.
The rule resolves `resolved = (R / to_run_dir_path).resolve(strict=False)` (which
collapses any `..` and `.` segments) and classifies it into exactly one region:

| region of `resolved` | predicate | outcome |
| --- | --- | --- |
| outside the run dir | `R != resolved` and `R not in resolved.parents` (or `to_run_dir_path` is absolute) | **reject** — "symlink target escapes the run-dir sandbox" |
| equal to the run dir | `resolved == R` | **reject** — "symlink target must be a path under the run dir" |
| inside `library/` or equal to it | `resolved == L` or `L in resolved.parents` | **reject** — "escaping symlink target must be outside library/; use to_asset for in-root links" |
| strict subpath of run dir, not under `library/` | otherwise | **accept** |

Equivalently: **ACCEPT iff** `resolved` is a strict subpath of `R` **AND NOT** (`resolved
== L` **OR** `L in resolved.parents`); otherwise **REJECT** with
`E_SYMLINK_TARGET_ESCAPE` and the region-specific message above. The strict-subpath
check (`resolved != R`, `R in resolved.parents`) is evaluated **before** the
`library/` check so that an absolute path or a `..`-escape is classified as a
sandbox escape rather than mis-reported as a library-boundary error. A path that
resolves **exactly to** `library` (e.g. `library` or `library/`) and a path that
resolves into `library` via `..` traversal (e.g. `library/../library/x`) are both
caught by the `library/` predicate. An absolute `to_run_dir_path` is rejected up front
(it cannot be a relative path under the run dir).

This is the one place the contract genuinely differs from `E_PATH_CONTAINMENT`:
escaping the **library** is the intended chaos (so it must *not* be
`E_PATH_CONTAINMENT`), but escaping the **run dir** must still fail. The rule reuses
the structural primitives of `resolve_under_library` against the run-dir root (a new
small helper `resolve_under_run_dir` in `contract/paths.py`, or an inline resolution
in the rule) but maps failures to `E_SYMLINK_TARGET_ESCAPE`, leaving
`E_PATH_CONTAINMENT` and `resolve_under_library` untouched.

`E_PATH_CONTAINMENT` and the existing path-safety rules are **not modified**: the
asset's own rendered path still passes through them unchanged.

### Materialization — `os.symlink` from the orchestrator layer

Handled in `materialize_assets_phase_a` alongside the `same_content_as` /
`hardlinked_to` short-circuits, **not** in `materialize_one_asset` (which has no
visibility into previously-materialized assets or the run dir layout). When
`asset.symlink is not None`, a new `_symlink_asset` helper (a near-twin of
`_hardlink_asset`):

- Computes the **link path** at `out_dir / "library" / rendered_relative_path`.
- Computes the **absolute target** (for resolution / probe / existence check):
  - `to_asset` → `out_dir / "library" / rel_path_by_asset[to_asset]` (the referent's
    already-written file).
  - `to_run_dir_path` → `out_dir / to_run_dir_path` (a path under the run dir,
    outside `library/`).
- **Existence check (fail loud).** If the absolute target does not exist on disk
  (`Path.exists()` is false — note this follows the path, so it is false for an absent
  final component), raise a `SymlinkTargetMissingError` (a new
  `MaterializationError` subclass; `error_code = "E_SYMLINK_TARGET_MISSING"`) whose
  message names the asset id and the resolved target. The orchestrator routes it
  through the existing `MaterializationFailure` path exactly like other
  `MaterializationError`s — **never** a silent skip or an unhandled exception. For an
  in-root `to_asset`, the referent materialized earlier in the same pass so the target
  always exists; the check is the meaningful guard for the escaping form whose target
  is created by an out-of-band step (a recipe/test that writes the target first). This
  is the v1 stand-in until target-authoring / dangling support lands (see Non-goals
  and the filed follow-up).
- Creates the link's parent dirs, then creates the link with a **run-dir-relative
  target**: `relative_target = os.path.relpath(absolute_target, link_path.parent)`,
  then `os.symlink(relative_target, link_path)`. The on-disk link therefore stores a
  **relative** path (e.g. `../../external-store/clip.mkv`), so the materialized tree is
  portable: moving or replaying it into a different run dir keeps the link valid.
  `os.symlink` is non-overwriting and phase A writes into a freshly-created tree, so
  `link_path` never pre-exists.
- Computes the referrer's `content_hash` from the **resolved** linked file (`open(
  link_path)` follows the link), and **re-probes** the resolved target for
  `size_bytes`/`duration_seconds` (honest, mirrors `_hardlink_asset`). The existence
  check above guarantees the open/probe succeed.
- Returns a `MaterializeAssetResult` with:
  - a synthetic `ToolInvocation` (`tool="symlink"`, `version="n/a"`,
    `command=["symlink", <target descriptor>, <link rel path>]`, `exit_code=0`,
    `duration_ns` measured around `os.symlink`), keeping the "one invocation per
    asset" invariant and giving the referrer a real `invocation_index`;
  - empty `sidecar_hashes` (the asset declares no subtitles — forbidden above);
  - empty `content_sources` (a link resolves no synthesis source — keeps the change
    schema-neutral, no new `ContentTrackKind` member);
  - empty `prelude_invocations`.

The referrer still gets its **own** `ManifestLocation` / path: a symlink is a separate
directory entry, which is exactly the scanner stressor. `MaterializedAsset` records
the referrer's `content_hash` (the resolved target's bytes) and `location_path` (the
link's own path), nothing link-specific.

The short-circuits are mutually exclusive per the validator, so the orchestrator
dispatches on whichever single field is set; the unset path is byte-for-byte the
pre-change synthesis call.

### What the manifest/oracle records (decision: nothing new — schema-neutral)

The manifest records the referrer's normal `ManifestVersion` (resolved-target
`content_hash`) and `ManifestLocation` (its own path). It records **no** link flag,
**no** target, **no** realpath. Rationale (ADR 0006 Q6):

- **Determinism / neutrality.** The on-disk link stores a **run-dir-relative** target
  (see Materialization), so it carries no absolute run-specific path, but recording a
  link target in the manifest at all would still add a versioned-schema field with no
  consumer contract. The link-ness and the link target are **fully observable on disk**
  via `os.path.islink` + `os.readlink` (which returns the relative target), which is
  what the consumer inspects.
- **Schema-neutral, like #178/#180.** Only `SCENARIO_SCHEMA_VERSION` 26 → 27 bumps.

### Replay reconstruction (schema-neutral consequence — confirmed)

A pure replay re-runs materialization into a fresh run dir. `_symlink_asset` re-runs
`os.symlink` into that fresh dir, exactly as `_hardlink_asset` re-runs `os.link` and
`_copy_same_content_asset` re-runs `shutil.copyfile`. The symlink is reconstructed
from the scenario alone (the `symlink` field), not from any manifest record — the same
property #178 relies on for the shared inode. **Confirmed: the schema-neutral choice
holds for symlinks because the link is reproducible from the scenario field.** Because
the on-disk link target is computed run-dir-relative (`os.path.relpath` against the
link's own parent), the link is identical regardless of the absolute run-dir location
and resolves correctly after the tree is moved or replayed into a different run dir —
so replay is genuinely run-dir-portable and byte-stable.

### Schema version

`SCENARIO_SCHEMA_VERSION` 26 → 27 (adding a field to a contract model is breaking per
the project's no-minor-versions rule). `Scenario.schema_version` literal updated to
`Literal[27]`. Every fixture/recipe matching `schema_version: 26` under `tests/` and
`recipes/` is bumped to `27` as one mechanical step (the corpus tests enforce the
literal). The `yaml-parse-error.yaml` fixture (pinned at an old version, expects
`E_YAML_PARSE`, never parses) is left untouched, consistent with #178/#180/#181.

`MANIFEST_SCHEMA_VERSION`, `MATERIALIZATION_SCHEMA_VERSION`, and
`REPLAY_BUNDLE_SCHEMA_VERSION` are **not** bumped. Schema artifacts regenerated with
`--write` and committed.

## The recipe

One new `scanner/` recipe (scanner-resilience category):

| Recipe | Field | Result |
| --- | --- | --- |
| `scanner/symlink-external.yaml` | asset B `symlink: {to_asset: <asset A id>}` | B's path is a symlink to A's in-library file — an **in-root** link a scanner must dedup-by-realpath, not double-count |

**Why the shipped recipe is the in-root form, not the escaping form:** every #108
recipe must `validate` clean **with no materialize step** (validation is the CI
contract; #108 explicitly scopes materialize out). An in-root `to_asset` recipe
validates clean with zero external state. An escaping `to_run_dir_path` recipe also
**validates** clean (the run-dir containment rule passes for a well-formed relative
target), but it only *materializes* meaningfully when a target file exists under the
run dir — which is a materialize-time concern the recipe corpus does not exercise.
Shipping the in-root recipe keeps the recipe genuinely runnable end-to-end; the
escaping form is exercised by the materializer tests (which create the target under a
tmp run dir). The recipe header documents both follow/reject expectations in prose.
(Note: the recipe filename keeps the issue's `symlink-external` name; the v1 shipped
body is the in-root variant — the header makes this explicit.)

**v1 limitation (stated plainly).** The escaping form is validate-exercised (it
validates clean) and materializer-test-exercised (tests pre-create the target under a
tmp run dir). A fully user-authorable escaping recipe that materializes end-to-end
needs the materializer to *create* the out-of-library target, which is the same
target-authoring / dangling capability deferred to the follow-up issue. Until then, a
`materialize` of an escaping scenario whose target nothing created fails loud with
`E_SYMLINK_TARGET_MISSING` (not a silent skip) — so the limitation is visible, not
latent.

The recipe ships the header block (`# Recipe:` … `# Requires: none` — validation needs
no ffmpeg) and is discovered by `tests/recipes/test_recipe_corpus.py`.

## Validation rules summary

| condition | layer | code |
| --- | --- | --- |
| `symlink` set with neither / both of `to_asset` / `to_run_dir_path` | SymlinkTarget validator | `E_FIELD_SHAPE` |
| `symlink` and any of `same_content_as` / `hash_collision_with` / `hardlinked_to` both set | Asset model_validator | `E_FIELD_SHAPE` |
| `symlink` set on an asset declaring its own `subtitles` | Asset model_validator | `E_FIELD_SHAPE` |
| `symlink.to_asset` references an unknown asset id | semantic rule | `E_TARGET_UNKNOWN` |
| `symlink.to_asset` references the asset's own id (self-ref) | semantic rule | `E_TARGET_UNKNOWN` |
| `symlink.to_asset` references a later-declared asset (forward ref) | semantic rule | `E_TARGET_UNKNOWN` |
| `symlink.to_run_dir_path` resolves inside `library/` (should use `to_asset`) | semantic rule | `E_SYMLINK_TARGET_ESCAPE` |
| `symlink.to_run_dir_path` is absolute or escapes the run dir | semantic rule | `E_SYMLINK_TARGET_ESCAPE` |

Plus one **materialize-time** failure (not a validate-time code; routed through the
`MaterializationFailure` path like other `MaterializationError`s):

| condition | layer | code |
| --- | --- | --- |
| the resolved symlink target does not exist on disk at materialize time | materializer (`_symlink_asset`) | `E_SYMLINK_TARGET_MISSING` |

## Failure modes and edge cases

- **`symlink` unset** → byte-identical to today (regression test: same code path and
  output as pre-change; the orchestrator's unset branch is the pre-change synthesis
  call).
- **In-root `to_asset` whose container/track spec differs from the referent** →
  allowed; the referrer materializes a link, its own spec is ignored for bytes (same
  decision the prior three made). The recipe authors a matching container to stay
  clean.
- **Escaping `to_run_dir_path` pointing just outside `library/`** (e.g.
  `external-store/clip.mkv`) → allowed and is the `scanner/symlink-external` shape.
  The materializer test creates that target under the tmp run dir before
  materializing.
- **Escaping target inside `library/`** → rejected (`E_SYMLINK_TARGET_ESCAPE`): use
  `to_asset`. Keeps the two forms non-overlapping.
- **Escaping target escaping the run dir / absolute** → rejected
  (`E_SYMLINK_TARGET_ESCAPE`): the sandbox boundary is the run dir; never a host path.
- **Missing target at materialize time** → the resolved target does not exist on disk
  when `_symlink_asset` runs → fails loud with `E_SYMLINK_TARGET_MISSING` (a
  `MaterializationError` subclass routed through `MaterializationFailure`), message
  naming the asset id and the resolved target. Never a silent skip or an unhandled
  exception.
- **Dangling target (authored absent target)** → out of scope (v1 requires an existing
  target; a missing one is the loud `E_SYMLINK_TARGET_MISSING` above, not a
  successfully-materialized dangling link); filed follow-up for true dangling support.
- **Chained symlink** (`symlink.to_asset` → an asset that is itself a symlink) →
  allowed; `os.symlink` against the earlier asset's link path produces a link to a
  link, which `os.stat`/`open` follow transitively. The earlier-declaration rule
  guarantees ordering. Tested.
- **`symlink.to_asset` → a `same_content_as` / `hardlinked_to` asset** → allowed; the
  referent is a real on-disk file. The link points at it.
- **Schema bump** → every fixture/recipe `Literal[26]` mismatch fails the corpus tests
  until bumped to 27 (the intended forcing function).
- **Cross-platform note** → CI runs on `ubuntu-latest`; `os.symlink` provides standard
  POSIX symlink semantics on ext4/tmpfs. On Windows, `os.symlink` requires privilege;
  the project targets Linux CI and Linux/macOS dev (same supported-assumption posture
  as #178's `os.link`). Out of scope for non-POSIX.

## Acceptance criteria

- [ ] `Asset` accepts `symlink` with `to_asset` xor `to_run_dir_path`; neither/both
      rejected (`E_FIELD_SHAPE`); cross-field misuse rejected (`E_FIELD_SHAPE`):
      `symlink` + any link field, and `symlink` + own `subtitles`.
- [ ] Unknown / self / forward `symlink.to_asset` references rejected with
      `E_TARGET_UNKNOWN`.
- [ ] `symlink.to_run_dir_path` inside `library/`, absolute, or escaping the run dir
      rejected with `E_SYMLINK_TARGET_ESCAPE`; a well-formed escaping relative target
      validates clean (no `E_PATH_CONTAINMENT` false-positive on it or on the asset
      path).
- [ ] An in-root `symlink` materializes a real symlink (`os.path.islink` true) at the
      referrer's path pointing at the referent's in-library file; `os.stat` follows it
      to the referent's bytes; the referrer's `MaterializedAsset` carries an
      `invocation_index` resolving to a synthetic `symlink` `ToolInvocation`, contributes
      no `ContentSourceEvidence`, and is re-probed.
- [ ] An escaping `symlink` (target created under a tmp run dir, outside `library/`)
      materializes a real symlink pointing at that out-of-library target; the asset
      path itself is contained and raises no `E_PATH_CONTAINMENT`.
- [ ] The materialized link stores a **relative** target: `os.readlink(link)` returns
      a relative path (not absolute), and the link still resolves to the target's bytes
      after the entire run-dir tree is relocated to a different absolute path
      (replay-portability).
- [ ] A `symlink` whose resolved target is absent at materialize time fails with
      `E_SYMLINK_TARGET_MISSING` (a `MaterializationError`), not a silent skip or an
      unhandled exception.
- [ ] The manifest records the resolved target's `content_hash` and the link's own
      `ManifestLocation`, and records **no** link flag / target (schema-neutral).
- [ ] Omitting `symlink` produces byte-identical output and the same code path as
      pre-change.
- [ ] One new `scanner/` recipe ships and validates clean.
- [ ] `SCENARIO_SCHEMA_VERSION` bumped 26 → 27; schema artifact regenerated; all
      fixtures/recipes bumped.

## Testing

- Contract: `Asset` accepts `symlink`; `SymlinkTarget` rejects neither/both forms
  (`E_FIELD_SHAPE`); `symlink` + each link field and `symlink` + own `subtitles`
  rejected (`E_FIELD_SHAPE`); round-trips through `Scenario.model_validate`.
- Validation: invalid fixtures for unknown/self/forward `to_asset`
  (`# expected: E_TARGET_UNKNOWN`), `to_run_dir_path` inside-library, the
  `library/`-boundary case (a target resolving **exactly to** `library` and one
  reaching into `library` via `..`, e.g. `library/../library/x`), absolute, and
  run-dir-escape (all `# expected: E_SYMLINK_TARGET_ESCAPE`), cross-field misuse
  (`# expected: E_FIELD_SHAPE`); valid fixtures for an in-root `to_asset` and a
  well-formed escaping `to_run_dir_path`.
- Materializer (unit, no ffmpeg — reuses the #178/#180 `_file_writing_fake` +
  `monkeypatch` seam so the referent fake writes a real file the link resolves off
  disk; escaping-target tests write the target under the test's **tmp run dir**, never
  a real system path):
  - in-root `to_asset`: the referrer path is a symlink (`os.path.islink`); `os.stat`
    follows it to the referent's bytes; `os.readlink` returns a **relative** path that
    resolves to the referent's in-library file; the referrer's `content_hash` equals
    the referent's; the referrer's `MaterializedAsset.invocation_index` resolves to a
    `phase_a.invocations[i]` whose `tool == "symlink"`; no `ContentSourceEvidence`;
    re-probed (size/duration equal the referent's).
  - escaping `to_run_dir_path`: target file created under the tmp run dir outside
    `library/`; the referrer path is a symlink whose `os.readlink` is **relative** and
    points at that target; `os.stat` follows it; no `E_PATH_CONTAINMENT` raised.
  - replay portability: after materializing an in-root link, move the whole run-dir
    tree to a different absolute path and assert the link still resolves to the
    target's bytes (proving the relative target is run-dir-portable).
  - missing target: a `symlink` whose resolved target is absent raises
    `E_SYMLINK_TARGET_MISSING` (assert the `MaterializationError` type / `error_code`),
    not an unhandled exception or a silent skip.
  - chained symlink (`to_asset` → a symlink asset): the second link follows
    transitively to real bytes.
- Backward-compat (no ffmpeg): with `symlink` unset, the orchestrator takes the
  pre-change synthesis branch (code-path equality), no `os.symlink` is called.
- Recipe corpus: the new `scanner/symlink-external.yaml` validates clean.
