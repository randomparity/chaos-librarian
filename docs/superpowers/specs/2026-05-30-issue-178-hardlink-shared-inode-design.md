# Issue #178 — Author hardlinked assets that share one inode

> Status: Draft · Sprint: issue-178 · Schema impact: SCENARIO_SCHEMA_VERSION 25 → 26

## Problem

The scanner-resilience recipe category (surfaced by #108) cannot express
`scanner/hardlink-duplicates` because the scenario schema has no inode/hardlink
concept — every asset is an independent file. This shape was dropped from #108 (see
that spec's "Dropped proposals", row `scanner/hardlink-duplicates`: "No inode/hardlink
concept in the schema").

A hardlink is a chaos shape a scanner must handle correctly: two directory entries
that point at **one** inode. Detecting that two paths are the *same* file (not two
copies) — via `st_ino` + `st_dev` and link count > 1 — is distinct from detecting that
two *independent* files have identical content. A scanner that double-counts hardlinks,
or that mistakes a hardlink for a true duplicate (or vice-versa), is exactly what this
recipe stresses.

## Relationship to #180's `same_content_as` (critical distinction)

#180 shipped `same_content_as`, which **copies bytes**: the materializer runs
`shutil.copyfile`, producing two **independent** files that happen to be byte-identical.
They have **different inodes**, each has link count 1, and mutating one path's bytes does
**not** affect the other. That is "true content duplicate" — a dedup-on-content stressor.

A **hardlink** is fundamentally different:

| property | `same_content_as` (copy) | `hardlinked_to` (this issue) |
| --- | --- | --- |
| primitive | `shutil.copyfile` | `os.link` |
| inodes | two distinct `st_ino` | one shared `st_ino` (and `st_dev`) |
| link count | 1 each | >= 2 on each path |
| mutate one path | other path unchanged | other path's bytes change too |
| full `content_hash` | identical (identical bytes) | identical (literally the same bytes) |
| what it stresses | content-dedup detection | same-inode / link-count detection |

Both record the **same full `content_hash`** in the manifest (the bytes are identical in
both cases), so the recorded-hash wire shape is unchanged. The difference is purely
on-disk identity (inode sharing + link count), which a scanner observes via
`os.stat`, not via the manifest.

**Decision: `hardlinked_to` is a third, parallel field, not a mode of
`same_content_as`.** It reuses the same *reference machinery* (asset-id reference,
earlier-declaration requirement, `E_TARGET_UNKNOWN` contract, orchestrator
short-circuit) but swaps the materialization primitive (`os.link` instead of
`shutil.copyfile`). Rationale and rejected alternatives: [ADR 0005](../../adr/0005-hardlink-shared-inode.md).

## Goals

- Add `Asset.hardlinked_to: str | None` so an author can declare that an asset's path is
  a **hardlink** to another asset's already-materialized file: one shared inode, link
  count >= 2, byte-identical content, same full `content_hash`.
- Materialize the link with `os.link(referent_file, referrer_path)` from the referent's
  already-written file (mirroring `same_content_as`'s orchestrator-layer short-circuit,
  one ordered pass).
- Record **nothing new** in the manifest/oracle about the inode or link count
  (schema-neutral; the manifest stays at MANIFEST_SCHEMA_VERSION 9). The shared-inode
  property is observed on-disk via `st_ino`/`st_dev`/`st_nlink`, which is what the
  consumer-under-test inspects and what the tests assert.
- Reject reference/shape errors at validate time with existing codes: `E_TARGET_UNKNOWN`
  for unknown/self/forward references (mirroring #180), `E_FIELD_SHAPE` for cross-field
  misuse (the model-validator code #180 uses).
- Make `hardlinked_to` **mutually exclusive** with both `same_content_as` and
  `hash_collision_with` on the same asset.
- Preserve backward compatibility: every existing scenario/recipe stays valid (beyond the
  mandatory `schema_version: 26` bump), and an asset with `hardlinked_to` unset executes
  the **identical pre-change** synthesis/copy/stamp path.

## Non-goals

- **Hardlinking across filesystems / library roots.** `os.link` cannot span devices
  (`EXDEV`). v1 forbids `hardlinked_to` when referent and referrer resolve to different
  library roots (validate-time `E_FIELD_SHAPE`); a cross-device link is not a hardlink.
  See ADR 0005 Q4.
- **Symlinks.** A symlink is a distinct entity (a path that points at another path, not a
  shared inode) and was dropped separately (`scanner/symlink-external`). Out of scope.
- **A named-inode registry or N-way link groups as a first-class entity.** References are
  asset-id to asset-id; an N-way hardlink set is authored as a chain/fan of pairwise
  `hardlinked_to` references (each pointing at an earlier asset), which all resolve to one
  inode transitively (ADR 0005 Q1).
- **Recording the runtime inode number in the manifest.** Inode numbers are
  filesystem-/run-specific and non-deterministic; recording one would break manifest
  determinism and run/replay equality (ADR 0005 Q3).
- **Mutation-propagation timeline actions.** No timeline action today rewrites an asset's
  bytes in place on one of two hardlinked paths; the mutate-one-reflects-on-the-other
  property is a *consequence of the shared inode* the tests verify directly on disk, not a
  new timeline event. See "Mutation propagation" below.

## Ground truth: how assets are written and how identity is recorded

Verified against `contract/scenario.py`, `contract/manifest.py`,
`contract/materialization.py`, `materializer/synthesis.py`,
`materializer/manifest_build.py`, and `validation/rules/content_reference.py` on the
branch base (post-#180, schema v25).

- `materialize_assets_phase_a` (`synthesis.py:131`) iterates assets in **declaration
  order** (`topology.iter_asset_contexts`), threading an
  `asset_id -> rendered_relative_path` map across the loop. For each asset it either
  short-circuits a `same_content_as` copy (`_copy_same_content_asset`,
  `synthesis.py:194`) or calls the injected `materialize_one_asset`. It then appends one
  `ToolInvocation`, one `MaterializedAsset`, and (for synthesis) `content_sources`, and
  calls `augment_manifest`.
- `_copy_same_content_asset` is the exact template for the hardlink path: it resolves the
  referent's already-written file at `out_dir / "library" / referent_rel_path`, performs
  the filesystem op, computes `content_hash` from the resulting file, **re-probes** it,
  and returns a `MaterializeAssetResult` with a synthetic `ToolInvocation`, empty
  `sidecar_hashes`, and empty `content_sources`.
- `augment_manifest` (`manifest_build.py:21`) stamps `version.content_hash` and the
  asset's `ManifestVersion`/`ManifestLocation`/`ManifestSidecar` rows. **No row records
  an inode or link count today**, and this change adds none.
- `MaterializedAsset` (`materialization.py:92`) records `location_path`, `content_hash`,
  `size_bytes`, `duration_seconds`, `invocation_index`, `mp4_moov_placement`. **No
  inode/link field; none added.**
- The reference resolver `rule_content_reference`
  (`validation/rules/content_reference.py`) already walks assets in declaration order and
  emits `E_TARGET_UNKNOWN` for unknown/self/forward references, driven by a tuple
  `_CONTENT_REFERENCE_FIELDS = ("same_content_as", "hash_collision_with")`. Adding
  `"hardlinked_to"` to that tuple extends the rule with zero new branching.

## Design

### New field on `Asset`

One flat optional field on the single frozen `extra="forbid"` `Asset` model, matching the
`same_content_as` shape:

| field | type | default | meaning |
| --- | --- | --- | --- |
| `hardlinked_to` | `str \| None` | `None` | id of another asset whose already-materialized file this asset's path is hardlinked to (one shared inode) |

No companion field is needed (unlike `hash_collision_with` + `collision_prefix_len`): a
hardlink is fully specified by the referent.

### `model_validator` (cross-field exclusivity)

The existing `Asset._check_content_dedup_fields` model validator
(`scenario.py:443`) is extended. New rules (each raising `ValueError`, surfaced as
`E_FIELD_SHAPE`, exactly as the existing exclusivity checks):

- `hardlinked_to` is **mutually exclusive** with `same_content_as` (an asset is either a
  copy or a hardlink, never both).
- `hardlinked_to` is **mutually exclusive** with `hash_collision_with` (a hardlink shares
  the referent's bytes and full hash; it cannot also be a prefix-collision decoy with its
  own divergent bytes).
- `hardlinked_to` is **forbidden** on an asset that declares its own `subtitles` (same
  reasoning #180 applies to `same_content_as`: the asset's track/sidecar spec is ignored
  for bytes because it shares the referent's inode, so authoring distinct sidecars on it
  is contradictory, and the link path writes no sidecars).

These are shape errors local to one asset (no cross-asset context), so they live in the
Pydantic validator and surface as `E_FIELD_SHAPE` (the established `same_content_as`
code).

### Cross-root exclusivity (semantic rule)

`os.link` cannot cross devices. Library roots may map to different filesystems, so a
`hardlinked_to` reference whose referent lives under a **different library root** than the
referrer is rejected at validate time. This needs cross-asset context (each asset's
resolved root), so it lives in the semantic rule, not the model validator. It surfaces as
`E_FIELD_SHAPE` (a structural misuse of the field, not an unresolved reference). See the
"Reference resolution" subsection for where this check is added.

*Within a single root*, the standard same-filesystem assumption holds (every asset under
one root materializes into one `<run-dir>/library/<root>/…` subtree on one filesystem).

### Reference resolution (semantic rule, `E_TARGET_UNKNOWN`)

`hardlinked_to` is added to `_CONTENT_REFERENCE_FIELDS` in
`validation/rules/content_reference.py`, so the existing `rule_content_reference` emits
`E_TARGET_UNKNOWN` for `hardlinked_to` when the referenced id is:

- **not a declared asset id** (dangling reference),
- **the asset's own id** (self-reference — hardlinking to yourself is meaningless), or
- **declared later** than the referrer (forward / same-position reference).

The earlier-declaration requirement is load-bearing and identical to `same_content_as`'s:
`os.link` needs the referent's file to **already exist** on disk, which it does only if
the referent materialized earlier in the single declaration-ordered pass. Reusing
`E_TARGET_UNKNOWN` for the forward case is the same documented stretch #180 established
(ADR 0004 Q4 / ADR 0005 Q2): a forward reference does not resolve *at the point it is
needed*.

The cross-root check (above) is added to the same rule as a separate `E_FIELD_SHAPE`
branch, guarded so it only runs for `hardlinked_to` and only when the reference otherwise
resolves (it needs a real referent to compare roots against). The per-asset root is
derived from the asset's owning root in the raw walk; the rule already has the raw scenario
and the asset loc.

### Walker-order coupling invariant

#180 added an invariant test pinning the validator's `iter_asset_contexts` id order to the
materializer's `topology.iter_asset_contexts` order, because both `hardlinked_to` and
`same_content_as` depend on the two walkers agreeing on declaration order. That test
already covers `hardlinked_to` (it pins the *order*, which is field-independent). No new
walker-order test is required; the existing one transitively protects this feature, and
the spec notes the dependency.

### Materialization — `os.link` from the referent's file (orchestrator layer)

Handled in the orchestrator `materialize_assets_phase_a`, alongside the existing
`same_content_as` short-circuit, **not** in the injected `materialize_one_asset` (which
has no visibility into previously-materialized assets). When `asset.hardlinked_to` is set,
a new `_hardlink_asset` helper (a near-twin of `_copy_same_content_asset`):

- Resolves the referent's already-written file at
  `out_dir / "library" / rel_path_by_asset[asset.hardlinked_to]` and the referrer's
  destination at `out_dir / "library" / rendered_relative_path`.
- Creates parent dirs, then `os.link(referent_path, output_path)` (the link, not a copy).
- Computes the referrer's `content_hash` from the linked file (identical bytes ⇒ identical
  full sha256 ⇒ `augment_manifest` stamps the **same** `content_hash` on both versions —
  **no new manifest field**).
- **Re-probes** the linked file for `size_bytes` / `duration_seconds` (identical bytes ⇒
  identical probe; honest, and mirrors `_copy_same_content_asset`).
- Returns a `MaterializeAssetResult` with:
  - a synthetic `ToolInvocation` (`tool="hardlink"`, `version="n/a"`,
    `command=["link", <referent asset_id>, <referrer rel path>]`, `exit_code=0`,
    `duration_ns` measured around the `os.link`) so the "one invocation per asset"
    invariant holds and the referrer's `MaterializedAsset.invocation_index` resolves to a
    real entry;
  - empty `sidecar_hashes` (the asset declares no subtitles — forbidden above);
  - empty `content_sources` (a link resolves no synthesis source, exactly as the copy
    does — keeps the change schema-neutral, no `ContentTrackKind` enum member);
  - empty `prelude_invocations`.

The referrer still gets its **own** `ManifestLocation` / path: a hardlink is a *separate
directory entry* pointing at a *shared inode*, which is exactly the scanner stressor.

The two short-circuits (`same_content_as`, `hardlinked_to`) are mutually exclusive per the
validator, so the orchestrator dispatches on whichever single field is set; the unset path
is byte-for-byte the pre-change synthesis call.

### What the manifest/oracle records (decision: nothing new — schema-neutral)

The manifest records the referrer's normal `ManifestVersion` (with the shared full
`content_hash`) and `ManifestLocation` (its own path). It records **no** inode number, link
count, or shared-inode grouping. Rationale (ADR 0005 Q3):

- **Determinism.** `st_ino` is filesystem-/run-assigned and non-deterministic; recording it
  would break manifest byte-stability and the run/replay manifest-equality invariant #180
  established. Link count is more stable but still adds a field with no consumer contract.
- **Neutral-oracle philosophy** (AGENTS.md). chaos-librarian emits neutral oracle records;
  the *consumer under test* is responsible for observing on-disk identity (`st_ino`,
  `st_nlink`) and deciding policy. Recording our own link-count "answer" pre-judges the
  consumer's job.
- **Schema-neutral, like #180.** No `MANIFEST_SCHEMA_VERSION` /
  `MATERIALIZATION_SCHEMA_VERSION` bump. The only contract change is
  `SCENARIO_SCHEMA_VERSION` 25 → 26 for the new input field.

The shared-inode fact is **fully observable on disk** (the materialized files genuinely
share an inode and carry link count >= 2), which is what the consumer inspects and what the
materializer tests assert (`st_ino` equality, `st_nlink >= 2`).

### Mutation propagation

The "mutate one path, the other reflects it" property is an *automatic consequence* of the
shared inode — no propagation code is needed. The spec does **not** add a timeline action
that rewrites bytes on one of two linked paths. Surveying the timeline actions
(`scenario.py` `TimelineActionName`): byte-rewriting actions (`reencode_video`,
`remux_container`, `truncate_file`, `corrupt_*`) all materialize a **new output file** at a
new version path (phase B writes a fresh file and records a new version), so they replace
the directory entry rather than rewriting the shared inode in place — meaning a phase-B
mutation of one path does **not** propagate to the hardlinked twin (it breaks the link by
writing a new file). This is the real replace semantics of those actions and is **not** a
v1 propagation feature.

What v1 *does* guarantee and test: at **phase-A materialization**, the two paths share one
inode; writing through the shared inode at the byte level (verified by a direct
`open(path_a, "wb")` in the test, simulating an in-place mutation) is reflected on the twin.
A timeline action that rewrites a hardlinked path **in place** (preserving the inode) is a
filed follow-up if a recipe needs it (ADR 0005 Q5).

### Schema version

`SCENARIO_SCHEMA_VERSION` 25 → 26 (adding a field to a contract model is breaking per the
project's no-minor-versions rule). `Scenario.schema_version` literal updated to
`Literal[26]`. Every fixture/recipe matching `schema_version: 25` under `tests/` and
`recipes/` is bumped to `26` as one mechanical step (the corpus tests
`test_sample_scenarios`, `test_invalid_corpus`, `test_recipe_corpus` enforce the literal).
The `yaml-parse-error.yaml` fixture (pinned at an old version, expects `E_YAML_PARSE`,
never parses) is left untouched, consistent with #180/#181.

`MANIFEST_SCHEMA_VERSION` and `MATERIALIZATION_SCHEMA_VERSION` are **not** bumped (no
manifest/materialization field added). Schema artifacts regenerated with `--write` and
committed.

## The recipe

One new `scanner/` recipe (scanner-resilience category):

| Recipe | Field | Result |
| --- | --- | --- |
| `scanner/hardlink-duplicates.yaml` | asset B `hardlinked_to: <asset A id>` | B's path is a hardlink to A's file: one shared inode, link count 2, byte-identical content, same full `content_hash` |

Ships the recipe header block (`# Recipe:` … `# Requires: none` — validation needs no
ffmpeg) and is discovered by `tests/recipes/test_recipe_corpus.py`, which asserts every
recipe validates clean. The header states it materializes a real hardlink (shared inode),
distinct from `same-content-duplicate`'s independent byte copy.

## Validation rules summary

| condition | layer | code |
| --- | --- | --- |
| `hardlinked_to` and `same_content_as` both set | model_validator | `E_FIELD_SHAPE` |
| `hardlinked_to` and `hash_collision_with` both set | model_validator | `E_FIELD_SHAPE` |
| `hardlinked_to` set on an asset declaring its own `subtitles` | model_validator | `E_FIELD_SHAPE` |
| `hardlinked_to` references an unknown asset id | semantic rule | `E_TARGET_UNKNOWN` |
| `hardlinked_to` references the asset's own id (self-ref) | semantic rule | `E_TARGET_UNKNOWN` |
| `hardlinked_to` references a later-declared asset (forward ref) | semantic rule | `E_TARGET_UNKNOWN` |
| `hardlinked_to` referent is under a different library root | semantic rule | `E_FIELD_SHAPE` |

## Failure modes and edge cases

- **`hardlinked_to` unset** → byte-identical to today (regression test: same code path and
  output as pre-change; the orchestrator's unset branch is the pre-change synthesis call).
- **`hardlinked_to` referent and referrer differ in container/track spec** → allowed; the
  referrer's declared spec is ignored for bytes (it shares the referent's inode). The
  referrer's `container` still governs its **path extension**, which may not match the
  linked bytes. Accepted chaos (same decision #180 made for `same_content_as`); the recipe
  authors a matching container to stay clean.
- **Chained `hardlinked_to`** (C → B → A, each declared earlier) → allowed; `os.link`
  against C's referent B, which is itself linked to A, yields **one shared inode**
  transitively (link count 3). The earlier-declaration rule guarantees ordering. Tested.
- **`hardlinked_to` an asset that is itself a `same_content_as` duplicate** → allowed; the
  referent is a real on-disk file (an independent copy), and the hardlink shares *that*
  file's inode. The duplicate's inode is distinct from its own referent's inode (copy), but
  the hardlink to the duplicate shares the duplicate's inode. Link count on the duplicate's
  file becomes 2. Tested.
- **Cross-root reference** → rejected (`E_FIELD_SHAPE`); `os.link` would raise `EXDEV` at
  materialize time, so it is rejected at validate time instead.
- **Schema bump** → every fixture/recipe `Literal[25]` mismatch fails the corpus tests
  until bumped to 26 (the intended forcing function).
- **Cross-platform note** → CI runs on `ubuntu-latest`; `os.link` provides standard POSIX
  hardlink semantics on the ext4/tmpfs filesystems used. The supported assumption is a
  POSIX filesystem with hardlink support and `st_nlink` tracking; Windows/exotic FS are out
  of scope (the project targets Linux CI and Linux/macOS dev).

## Acceptance criteria

- [ ] `Asset` accepts `hardlinked_to`; cross-field misuse rejected at validate time
      (`E_FIELD_SHAPE`): both link fields set (either combination), and `hardlinked_to` on
      an asset declaring its own `subtitles`.
- [ ] Unknown / self / forward `hardlinked_to` references rejected with `E_TARGET_UNKNOWN`.
- [ ] Cross-root `hardlinked_to` reference rejected with `E_FIELD_SHAPE`.
- [ ] Two assets linked by `hardlinked_to` materialize files that **share one inode**
      (equal `st_ino`, equal `st_dev`) with **link count >= 2**, byte-identical content, and
      the **same full** `content_hash`; the referrer's `MaterializedAsset` carries an
      `invocation_index` resolving to a synthetic `hardlink` `ToolInvocation`, and the link
      contributes no `ContentSourceEvidence`.
- [ ] Writing bytes through one linked path is reflected when reading the other (shared
      inode), verified on disk.
- [ ] The manifest records the shared full `content_hash` and each path's own
      `ManifestLocation`, and records **no** inode/link-count field (schema-neutral).
- [ ] Omitting `hardlinked_to` produces byte-identical output and the same code path as
      pre-change.
- [ ] One new `scanner/` recipe ships and validates clean.
- [ ] `SCENARIO_SCHEMA_VERSION` bumped 25 → 26; schema artifact regenerated; all
      fixtures/recipes bumped.

## Testing

- Contract: `Asset` accepts `hardlinked_to`; rejects each cross-field misuse with
  `E_FIELD_SHAPE` (both combinations of link-field pairs; `hardlinked_to` + own
  `subtitles`); round-trips through `Scenario.model_validate`.
- Validation: invalid fixtures for unknown ref, self ref, forward ref
  (`# expected: E_TARGET_UNKNOWN`), cross-field misuse and cross-root ref
  (`# expected: E_FIELD_SHAPE`); a valid fixture exercising `hardlinked_to`.
- Materializer (unit, no ffmpeg — reuses the #180 `_file_writing_fake` +
  `monkeypatch` seam so the referent fake writes a real file the link reads off disk):
  - `hardlinked_to`: `st_ino` of the two materialized files is equal; `st_nlink >= 2` on
    both; the referrer's bytes equal the referent's; both manifest versions carry the same
    full `content_hash`; the referrer's `MaterializedAsset.invocation_index` resolves to a
    `phase_a.invocations[i]` whose `tool == "hardlink"`; the link contributes no
    `ContentSourceEvidence`; the linked file is re-probed (size/duration equal the
    referent's).
  - Mutation propagation: writing new bytes through one path's fd is observed when reading
    the other path (shared inode), asserted on disk.
  - Chained hardlink (C → B → A): all three share one inode; link count 3.
  - `hardlinked_to` → a `same_content_as` duplicate: link shares the *duplicate's* inode;
    link count on the duplicate's file is 2.
- Backward-compat (no ffmpeg): with `hardlinked_to` unset, the orchestrator takes the
  pre-change synthesis branch (code-path equality), no `os.link` is called.
- Recipe corpus: the new `scanner/hardlink-duplicates.yaml` validates clean (existing
  `test_recipe_corpus.py`).
