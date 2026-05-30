# Issue #180 — Author same-content and hash-collision assets

> Status: Draft · Sprint: issue-180 · Schema impact: SCENARIO_SCHEMA_VERSION 24 → 25

## Problem

The identity recipe category (surfaced by #108) can express
identity-through-mutation (move/rename/remux) but **not content dedup**. Two chaos
shapes are inexpressible today and were dropped from #108 (see that spec's "Dropped
proposals", row `identity/hash-collision-simulation`):

1. **Same content** — author two assets whose materialized bytes are byte-identical,
   so the manifest records the **same full `content_hash`** for both. This is what a
   dedup-aware consumer must detect as a true duplicate.
2. **Truncated-hash collision** — author two assets whose recorded content hashes
   collide at a **truncated prefix** while differing at full length, to exercise a
   consumer that dedups on a shortened hash and must not treat a prefix match as a
   true duplicate.

Neither is expressible because an `Asset` has no content field: bytes are synthesized
from the track recipes plus a seed, and `asset_id` is folded into **every** synthesis
sub-seed (`materializer/content_sources.py`: `_muxing_deterministic_seed`,
`_cover_art_color`, `_chapter_title`, …). Two assets with identical specs but
different ids therefore produce **different** bytes and different hashes today —
verified, not assumed.

## Goals

- Add `Asset.same_content_as: str | None` so an author can declare that an asset's
  materialized bytes are copied verbatim from another asset, yielding an identical
  **full** `content_hash` in the manifest.
- Add `Asset.hash_collision_with: str | None` + `Asset.collision_prefix_len: int` so
  an author can declare that an asset's **recorded** content hash shares a truncated
  hex prefix with another asset's recorded hash while the on-disk bytes (and the full
  hash) differ.
- Reject reference/shape errors at validate time with existing codes
  (`E_TARGET_UNKNOWN` for unknown/self references; `E_FIELD_*`/value errors for
  cross-field exclusivity), mirroring #181's contract style.
- Preserve backward compatibility: every existing scenario and recipe stays valid
  (beyond the mandatory `schema_version: 25` bump), and an asset with all three new
  fields unset executes the **identical pre-change synthesis and manifest-stamping
  path**.

## Non-goals

- **A true on-disk sha256 prefix collision.** v1 produces an *oracle-recorded* prefix
  collision: the manifest records a colliding hash; the on-disk file's real sha256
  does **not** share the prefix. A real on-disk collision needs a nonce-grind over
  ffmpeg output (expensive, version-sensitive) and is filed as a follow-up issue. See
  [ADR 0004](../../adr/0004-same-content-hash-collision.md) Q3/Q5.
- A named content-blob registry or a general "arbitrary bytes" primitive. References
  are asset-id to asset-id (ADR 0004 Q1).
- Conflating same-content and collision into one knob (ADR 0004 Q2).
- Changing how a referenced asset is synthesized. `same_content_as` copies the
  **referent's already-materialized bytes**; it does not re-derive seeds.

## Ground truth: how content and hashes are produced

Verified against `contract/scenario.py`, `contract/manifest.py`,
`materializer/synthesis.py`, `materializer/manifest_build.py`,
`materializer/content_sources.py`, and `materializer/phase_b/oracle_hash.py` on
`main` (post-#181, schema v24).

- `materialize_assets_phase_a` (`synthesis.py`) iterates assets in **declaration
  order** (`topology.iter_asset_contexts`), calls `materialize_one_asset` per asset,
  writes the file under `<out_dir>/library/<rendered_relative_path>`, computes
  `content_hash = "sha256:" + sha256(file)`, and calls `augment_manifest`.
- `augment_manifest` (`manifest_build.py:53-57`) stamps
  `version.content_hash = materialized.content_hash` onto the single
  `ManifestVersion` whose `asset_id` matches. **This is the single chokepoint where an
  asset's recorded content hash is set.**
- `ManifestVersion.content_hash` / `ManifestSidecar.content_hash` are `str | None`
  constrained by `SHA256_URI_PATTERN = ^sha256:[0-9a-f]{64}$`. There is **no
  truncated-hash field anywhere** in the contract — truncation is the *consumer's*
  dedup behavior.
- `phase_b/oracle_hash.py::false_hash_for(seed_material, actual_hash)` already
  establishes the tested pattern of recording a manifest hash that differs from the
  real file bytes (the `wrong_oracle_hash` event). The collision strategy reuses this
  pattern, constrained to preserve a prefix.

## Design

### New fields on `Asset`

Flat optional fields on the single `Asset` model (frozen, `extra="forbid"`), matching
#181's flat-field approach and the existing `Asset` shape.

| field | type | default | meaning |
| --- | --- | --- | --- |
| `same_content_as` | `str \| None` | `None` | id of another asset whose materialized bytes are copied verbatim |
| `hash_collision_with` | `str \| None` | `None` | id of another asset whose recorded content hash this asset's recorded hash shares a prefix with |
| `collision_prefix_len` | `int \| None` | `None` | number of leading hex chars (of the 64-char digest) the two recorded hashes share; required iff `hash_collision_with` is set |

`collision_prefix_len` is bounded `Field(ge=1, le=63)`: at least one shared hex nibble,
and strictly less than 64 so the full hashes are guaranteed to **differ** (a 64-char
"prefix" would be full equality, which is `same_content_as`, not a collision).

### `model_validator` (cross-field exclusivity + companion fields)

An `Asset` `model_validator(mode="after")` enforces (raising `ValueError`, surfaced as
`E_FIELD_*`, exactly as #181's `_check_fields_match_kind`):

- `same_content_as` and `hash_collision_with` are **mutually exclusive** — an asset is
  either a true duplicate or a prefix-collision decoy, never both.
- `collision_prefix_len` is set **iff** `hash_collision_with` is set
  (`hash_collision_with=None, collision_prefix_len=5` → error; and vice-versa).

These are *shape* errors local to one asset; they need no cross-asset context, so they
live in the Pydantic validator.

### Reference resolution (semantic rule, `E_TARGET_UNKNOWN`)

A new semantic rule `rule_content_reference`
(`validation/rules/content_reference.py`, registered in `semantic._RULES`) walks every
declared asset and, for each of `same_content_as` / `hash_collision_with` that is set,
emits `E_TARGET_UNKNOWN` when:

- the referenced id is **not a declared asset id** (dangling reference), or
- the referenced id **equals the asset's own id** (self-reference — copying or
  colliding with yourself is meaningless).

`E_TARGET_UNKNOWN` is the existing code `rule_target_unknown` uses for unknown asset
references; reusing it keeps one contract for "this reference does not resolve". The
rule reuses `entity_ids_by_kind(raw)["asset"]` (the same declared-id set the timeline
target rule uses).

The loc points at the offending field: `("...asset path...", "same_content_as")` /
`(..., "hash_collision_with")`, using the same asset-path machinery
`iter_asset_contexts` / `iter_assets_with_loc` already provide in `_common.py`.

#### Declaration-order requirement

`same_content_as` copies the referent's **already-written file**, so the referent must
materialize **before** the referrer. The materializer iterates in declaration order,
so the rule additionally requires the referenced asset to be declared **earlier** than
the referrer (forward references rejected). This mirrors the existing ordered-lifecycle
rules (`slow_copy` start-before-commit). A forward or same-position reference emits
`E_TARGET_UNKNOWN` with a message naming the ordering requirement.

`hash_collision_with` shares the **same** declaration-order requirement: the colliding
hash is computed from the referent's *recorded* hash, which is only known after the
referent is stamped. Single ordered pass, no second materialize pass.

### Materialization

#### `same_content_as` — copy the referent's bytes

In `materialize_one_asset` (or a thin wrapper in `synthesis.py`), when
`asset.same_content_as` is set:

- Resolve the referent's already-written output path (the referent materialized
  earlier in the same phase-A loop). Copy its bytes to this asset's
  `rendered_relative_path` with `shutil.copyfile` (or read+write), then compute this
  asset's `content_hash` from the copied file. Because the bytes are identical, the
  full sha256 is identical → `augment_manifest` stamps the **same** `content_hash` on
  both versions. **No new manifest field, no override.**
- The asset still gets its own `ManifestLocation` / path (a duplicate is a *separate
  file* with *identical content*, which is exactly the dedup scenario).
- ffprobe still runs on the copied file (duration/size are real). The referent and
  referrer must be **probe-compatible** by construction (identical bytes ⇒ identical
  probe), so no extra capability gate is needed.
- The phase-A loop threads a `dict[str, Path]` of `asset_id -> written output path`
  (or reuses `phase_a.materialized_assets[*].location_path`) so the referent's path is
  available. The referent is guaranteed present because the rule enforces
  earlier-declaration.

No ffmpeg is invoked for the copy itself, so this path works even when ffmpeg is
unavailable **if** the referent was synthesized — but the referent's own synthesis
needs ffmpeg, so the asset pair as a whole carries the referent's normal capability
requirements. (No new gate; the referent gates itself.)

#### `hash_collision_with` — override the recorded hash to share a prefix

The asset synthesizes **normally** (its own real bytes, its own real sha256). Then, at
the `augment_manifest` chokepoint, the recorded `content_hash` is **overridden** so its
first `collision_prefix_len` hex chars equal the referent's recorded hash, while the
remaining chars differ from both the referent's hash and this asset's real hash.

A new helper `collided_hash_for(referent_hash, real_hash, prefix_len)` (next to
`false_hash_for` in `phase_b/oracle_hash.py`, or a new `manifest_collision.py`):

```
prefix  = referent_hash_hex[:prefix_len]              # shared hex prefix
suffix  = sha256(f"{real_hash}:{referent_hash}:{prefix_len}").hexdigest()[prefix_len:]
candidate = "sha256:" + prefix + suffix
# guarantee the result differs from BOTH referent_hash and real_hash at full length:
if candidate in (referent_hash, real_hash):
    suffix = sha256(f"{candidate}:fallback").hexdigest()[prefix_len:]
    candidate = "sha256:" + prefix + suffix
```

The result is a valid `sha256:[0-9a-f]{64}` URI (prefix and suffix are both hex), shares
exactly `prefix_len` leading chars with the referent's recorded hash, and is
deterministic (seeded only by the two real hashes + prefix length). Determinism is
verified by a test asserting byte-stable output across runs.

The override is applied at the **manifest stamp** point only; the on-disk file is the
asset's real synthesized bytes. This is the *oracle-recorded* collision (ADR 0004 Q3b):
a consumer that dedups on the recorded/manifest hash sees the prefix collision; a
consumer that re-hashes the file on disk does not. This limitation is documented in the
spec, ADR, recipe header, and PR body, and the on-disk nonce-grind is a filed
follow-up.

The plumbing: `materialize_assets_phase_a` records each asset's stamped
`content_hash` as it goes (in declaration order). When it reaches a
`hash_collision_with` asset, it looks up the referent's recorded hash from that map,
computes the collided hash, and stamps **that** instead of the real hash on the
asset's `ManifestVersion`. The asset's `MaterializedAsset.content_hash` (replay/audit)
records the **real** hash; only the manifest version row carries the collided hash —
matching `wrong_oracle_hash`, which records both `actual_content_hash` and
`reported_content_hash`.

### Stamped-hash bookkeeping (replay/run parity)

`stamp_phase_a_manifest` re-stamps a fresh manifest from stored phase-A metadata for
run/replay. To keep run/replay identical to materialize, the **collided** hash (not the
real one) must be what lands on the manifest version in both paths. Options resolved in
the plan: store the collided hash on the phase-A record so both `augment_manifest` and
`stamp_phase_a_manifest` stamp the same value. The plan specifies the exact field/flow;
the invariant tested is *materialize manifest == replay manifest* for a collision
scenario.

### Schema version

`SCENARIO_SCHEMA_VERSION` 24 → 25 (adding fields to a contract model is breaking per
the project's no-minor-versions rule). `Scenario.schema_version` literal updated to
`Literal[25]`. The 150 files matching `schema_version: 24` under `tests/` and `recipes/`
are bumped to `25` as one mechanical step (the corpus tests `test_sample_scenarios`,
`test_invalid_corpus`, `test_recipe_corpus` enforce the literal). The
`yaml-parse-error.yaml` fixture (pinned at an old version, expects `E_YAML_PARSE`, never
parses) is left untouched, consistent with #181.

`MANIFEST_SCHEMA_VERSION` is **not** bumped — `ManifestVersion` is unchanged (the
collided hash is a normal `content_hash` value, still a valid `sha256:` URI; the wire
shape does not change). `MATERIALIZATION_SCHEMA_VERSION` is **not** bumped unless the
plan finds a `MaterializedAsset` field is required for the stamp bookkeeping; if so the
plan calls it out and bumps it. Schema artifacts regenerated with `--write` and
committed.

## The recipes

Two new `identity/` recipes (identity grows 3 → 5, satisfying #108's ≥3 floor with
headroom):

| Recipe | Fields | Result |
| --- | --- | --- |
| `identity/same-content-duplicate.yaml` | asset B `same_content_as: <asset A id>` | B's file is byte-identical to A; both versions record the same full `content_hash` |
| `identity/hash-collision-simulation.yaml` | asset B `hash_collision_with: <A id>, collision_prefix_len: 8` | B's recorded `content_hash` shares A's first 8 hex chars; the on-disk bytes and full hashes differ |

Each ships the recipe header block (`# Recipe:` … `# Requires: none`) and is discovered
by `tests/recipes/test_recipe_corpus.py`, which asserts every recipe validates clean.
The `hash-collision-simulation` header explicitly states it is an **oracle-recorded**
prefix collision, not an on-disk sha256 collision.

## Validation rules summary

| condition | layer | code |
| --- | --- | --- |
| `same_content_as` and `hash_collision_with` both set | model_validator | `E_FIELD_*` |
| `collision_prefix_len` set without `hash_collision_with` (or vice-versa) | model_validator | `E_FIELD_*` |
| `collision_prefix_len` out of `[1, 63]` | Pydantic `Field(ge=1, le=63)` | `E_FIELD_*` |
| `same_content_as` / `hash_collision_with` references an unknown asset id | semantic rule | `E_TARGET_UNKNOWN` |
| reference equals the asset's own id (self-reference) | semantic rule | `E_TARGET_UNKNOWN` |
| reference is to a **later-declared** asset (forward ref) | semantic rule | `E_TARGET_UNKNOWN` |

## Failure modes and edge cases

- **All three fields unset** → byte-identical to today (regression test asserts the
  no-op synthesis/stamp path: same `content_hash` and same code path as pre-change).
- **`same_content_as` referent and referrer differ in container/track spec** →
  allowed; the referrer's *declared* spec is ignored for bytes (it gets the referent's
  bytes). The referrer's `container` field still governs its **path extension**; the
  copied bytes may not match that container. *Decision:* this is acceptable chaos (a
  ".mkv" file containing mp4 bytes is itself a valid dedup/identity stressor) and is
  **not** rejected — but the recipe authors a matching container to keep the recipe
  clean. A future tightening (require matching container) is a follow-up, not v1.
- **`collision_prefix_len: 63`** → the two recorded hashes differ in exactly the last
  hex char; the `candidate != referent/real` guard ensures a genuine 1-char difference.
- **Chained `same_content_as`** (C copies B, B copies A) → allowed; each copies its
  immediate referent's bytes, which transitively equals A. The earlier-declaration
  rule guarantees B is materialized before C.
- **`hash_collision_with` an asset that is itself a `same_content_as` duplicate** →
  allowed; the referent's recorded hash is whatever was stamped (the duplicated full
  hash), and the collision prefix is taken from it.
- **Schema bump** → every fixture/recipe `Literal[24]` mismatch fails the corpus tests
  until bumped to 25 (the intended forcing function).

## Acceptance criteria

- [ ] `Asset` accepts `same_content_as`, `hash_collision_with`, `collision_prefix_len`;
      cross-field misuse rejected at validate time (`E_FIELD_*`).
- [ ] Unknown / self / forward references rejected with `E_TARGET_UNKNOWN`.
- [ ] Two assets linked by `same_content_as` materialize byte-identical files and
      record the **same full** `content_hash`.
- [ ] Two assets linked by `hash_collision_with` record content hashes that share
      exactly `collision_prefix_len` leading hex chars and differ at full length; the
      collided hash is deterministic.
- [ ] Run/replay manifest equals materialize manifest for a collision scenario.
- [ ] Omitting the new fields produces byte-identical output and the same code path as
      pre-change.
- [ ] Two new `identity/` recipes ship and validate clean.
- [ ] `SCENARIO_SCHEMA_VERSION` bumped 24 → 25; schema artifact regenerated; all
      fixtures/recipes bumped.
- [ ] Follow-up issue filed for the on-disk nonce-grind collision strategy.

## Testing

- Contract: `Asset` accepts each new field; rejects each cross-field misuse with
  `E_FIELD_*`; `collision_prefix_len` bounds enforced; round-trips through
  `Scenario.model_validate`.
- Validation: invalid fixtures for unknown ref, self ref, forward ref
  (`# expected: E_TARGET_UNKNOWN`) and cross-field misuse
  (`# expected: E_FIELD_UNKNOWN` or the value-error code the model raises); valid
  fixtures for each new field.
- Materializer (env-gated ffmpeg where the referent needs synthesis; the copy and the
  hash-override logic are unit-tested without ffmpeg):
  - `same_content_as`: copied file bytes equal referent bytes; both manifest versions
    carry the same full `content_hash`.
  - `hash_collision_with`: `collided_hash_for` shares exactly `prefix_len` chars with
    the referent hash, differs from referent and real hashes at full length, is a valid
    `sha256:` URI, and is deterministic across runs.
  - The manifest version for the collision asset carries the collided hash; the
    `MaterializedAsset` carries the real hash.
- Backward-compat (no ffmpeg): with all new fields `None`, `augment_manifest` stamps
  the real `materialized.content_hash` unchanged (code-path equality, not a frozen
  hash), and the synthesis path is unchanged.
- Run/replay parity: a collision scenario's replayed manifest version hash equals the
  materialized one.
- Recipe corpus: the two new recipes validate clean (existing
  `test_recipe_corpus.py`).
