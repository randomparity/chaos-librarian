# 0004 — Author same-content and hash-collision assets

## Status

Accepted

## Context

The identity recipe category (#108) can express identity-through-mutation but not
content dedup. There is no scenario knob to author two assets with byte-identical
content, nor to force a truncated-hash collision (`identity/hash-collision-simulation`,
dropped from #108). An `Asset` has no content field; bytes are synthesized from track
recipes plus a seed, and `asset_id` is folded into every synthesis sub-seed
(`materializer/content_sources.py`), so two assets with identical specs but different
ids produce different bytes and different hashes. The manifest records a full
`sha256:` URI in `ManifestVersion.content_hash`; there is no truncated-hash field
anywhere — truncation is the consumer's (voom-v2's) dedup behavior.

This is a scenario-schema change (`SCENARIO_SCHEMA_VERSION` 24 → 25) and reuses an
existing failure surface, so the decisions below are recorded with their rejected
alternatives to keep settled choices from reopening during review.

## Decision

Add three flat optional fields to `Asset`: `same_content_as` (full-identity copy),
`hash_collision_with` + `collision_prefix_len` (oracle-recorded prefix collision). A
model validator enforces mutual exclusivity and the prefix-len companion rule; a new
semantic rule resolves the asset-id references.

1. **Shared content = `same_content_as: str | None`, an asset-id reference.** The
   materializer synthesizes the referent once and copies its already-written bytes to
   the referrer's path, so both record the same full `content_hash`. No new manifest
   field.
2. **Collision = a separate `hash_collision_with: str | None` +
   `collision_prefix_len: int` (`ge=1, le=63`)**, distinct from `same_content_as` and
   mutually exclusive with it.
3. **Collision strategy = oracle-recorded prefix collision.** The asset synthesizes
   its own real bytes; at the manifest-stamp chokepoint the recorded `content_hash` is
   overridden to share `collision_prefix_len` leading hex chars with the referent's
   recorded hash while differing at full length. This reuses the tested
   `wrong_oracle_hash` / `false_hash_for` pattern (record a manifest hash that differs
   from the file bytes). The on-disk file's real sha256 does **not** share the prefix.
4. **Reference/shape errors only (no runtime "unsatisfiable" path).** Unknown, self,
   and forward references → `E_TARGET_UNKNOWN` (a new semantic rule). Cross-field
   misuse (both link fields set; `collision_prefix_len` without `hash_collision_with`)
   → `E_FIELD_*` in the model validator. The oracle-record strategy always succeeds, so
   there is no `E_*_UNSATISFIABLE` failure mode.

`SCENARIO_SCHEMA_VERSION` is bumped 24 → 25 and the JSON-schema artifact regenerated.
`MANIFEST_SCHEMA_VERSION` is unchanged (the collided hash is a normal valid `sha256:`
value; the wire shape is unchanged).

## Consequences

- Two identity recipes ship (`same-content-duplicate`, `hash-collision-simulation`);
  `recipes/identity/` grows 3 → 5.
- A dedup consumer that compares **recorded/manifest** hashes sees both the true
  duplicate and the prefix collision. A consumer that **re-hashes files on disk** sees
  the true duplicate but **not** the prefix collision — the v1 collision is oracle-only.
  This is documented in the spec, the `hash-collision-simulation` recipe header, and
  the PR body, and the on-disk nonce-grind is filed as a follow-up issue.
- Omitting the new fields is byte-identical to today (regression-tested): the synthesis
  and `augment_manifest` paths are unchanged when all three fields are `None`.
- `same_content_as` requires the referent to be declared **earlier** (single ordered
  materialize pass, no second pass). Forward references are rejected at validate time.
- `same_content_as` is **forbidden** on an asset that declares its own `subtitles` (v1
  limitation): the duplicate's track spec is ignored for bytes, so authoring distinct
  sidecars on it is contradictory, and the copy path writes no sidecars. Same-content
  with the asset's *own distinct* sidecars is a filed follow-up, not a v1 feature.
- The copy path reproduces every per-asset contribution synthesis makes: a **synthetic
  `ToolInvocation`** (`tool="same_content_copy"`, `exit_code=0`) keeps the "one
  invocation per asset" invariant and gives the duplicate's `MaterializedAsset` a real
  `invocation_index`; the copied file is **re-probed** (not reusing the referent's
  probe). The copy contributes **no `ContentSourceEvidence`** — a pure copy resolves no
  synthesis source, and inventing an entry would need a new closed-enum `ContentTrackKind`
  member that drifts the `materialization` and `replay-bundle` schemas; the synthetic
  `ToolInvocation` is the copy's audit record. The only contract bump in this change is
  `SCENARIO_SCHEMA_VERSION` 24 → 25; `MaterializedAsset`, `ContentSourceEvidence`,
  `ManifestVersion`, and all non-scenario schema versions are unchanged.
- The collided hash is deterministic (a pure function of the referent's recorded hash,
  the asset's real hash, and the prefix length), and is recomputed in a collision-aware
  `augment_manifest` shared by both the live materialize path and the run/replay
  `stamp_phase_a_manifest` path. So materialize, run, and replay stamp the identical
  value with no extra plumbing — the same parity mechanism `wrong_oracle_hash` relies on.
- `MaterializedAsset.content_hash` retains the **real** synthesized hash (no new field,
  no `MATERIALIZATION_SCHEMA_VERSION` bump); the manifest version row carries the
  **collided** hash. Unlike `wrong_oracle_hash`'s `OracleHashAction` (which records both
  `actual` and `reported` hashes), the asset-field collision keeps no per-event
  `reported`-vs-`actual` record — the real hash is in `MaterializedAsset`, the collided
  hash is in the manifest, and that asymmetry is the accepted contract.

## Considered & rejected

**Q1 — How shared/identical content is referenced.**
- *Rejected: a named content-blob registry* (`content_blobs: [{id, recipe}]` that
  assets reference by `content_ref`). Adds a whole top-level entity and a second
  identity namespace for a niche need — premature abstraction for a two-recipe feature.
- *Rejected: reuse/extend the #70 content-source-hook machinery.* That system is built
  for external/public-domain/TTS sources; overloading it for in-scenario asset dedup
  conflates two concerns and complicates the provider registry.
- **Chosen: `Asset.same_content_as: str | None`, an asset-id reference**, copying the
  referent's materialized bytes. Smallest surface, matches the flat-field convention,
  no new entity, unambiguous semantics.

**Q2 — Collision as a separate knob vs a mode of same-content.**
- *Rejected: one mechanism with a `mode` selecting full-identity vs prefix-collision.*
  Full-identity ("true duplicate") and prefix-collision ("looks-duplicate under
  truncation") are semantically different chaos shapes with different validation,
  different manifest effects (one stamps an identical real hash, the other overrides
  with a synthetic hash), and different consumer expectations. Conflating them muddies
  the validator and the oracle records.
- **Chosen: a separate, explicit `hash_collision_with` + `collision_prefix_len`**,
  mutually exclusive with `same_content_as`.

**Q3 — Strategy to force a truncated-hash collision.**
- *Rejected: on-disk nonce grind.* Append/embed a deterministic nonce and increment
  until the file's real sha256 has the target prefix. Honest (the file truly has the
  prefix) but exponential in prefix length, requires re-muxing per attempt, is
  ffmpeg-version-sensitive, and needs a hard cap + an `E_*_UNSATISFIABLE` failure path.
  Filed as a follow-up for if/when a consumer is confirmed to re-hash on disk.
- *Rejected: truncate-then-pad of identical content.* sha256 is a full-file digest, so
  perturbing the tail flips the whole digest — it cannot preserve a prefix. Does not
  work for sha256.
- **Chosen: oracle-recorded prefix collision** — override the recorded manifest hash to
  share the prefix while the on-disk bytes (and real hash) differ. Deterministic,
  instant, ffmpeg-version-independent, reuses the tested `false_hash_for` pattern, and
  targets exactly the artifact (the recorded oracle hash) a dedup consumer compares.
  Limitation (oracle-only, not on-disk) documented everywhere it surfaces.

**Q4 — Error contract for invalid collision requests.**
- *Rejected: a new `E_HASH_COLLISION_UNSATISFIABLE` code.* The oracle-record strategy
  (Q3) always succeeds, so there is no unsatisfiable runtime case; a dedicated code
  would be dead. Reference errors should match the existing unknown-reference contract,
  not fragment it.
- *Rejected: everything in the model_validator* (so even unknown/forward references are
  `E_FIELD_*`). Cross-asset reference resolution needs the declared-id set and
  declaration order — that is semantic-rule territory, not a single-model shape check;
  and it diverges from `rule_target_unknown`'s `E_TARGET_UNKNOWN`.
- *Rejected: a distinct ordering code for forward references* (e.g. reuse
  `E_LIFECYCLE_INVALID` or mint a `same_content`-specific timing code, mirroring
  `slow_copy`'s dedicated `E_SLOW_COPY_TIMING`). `E_SLOW_COPY_TIMING` is
  slow-copy-specific; `E_LIFECYCLE_INVALID` is contract-scoped to *timeline* execution
  order ("reject timelines that can't execute"), but `same_content_as` /
  `hash_collision_with` are asset-declaration fields, not timeline events — routing them
  through a timeline-lifecycle code would misclassify them and couple an asset rule to a
  timeline simulator. A new ordering code would fragment a single-purpose rule.
- **Chosen: `E_TARGET_UNKNOWN` (semantic rule) for unknown, self, AND forward/
  same-position references — with a forward-ref message that names the ordering
  requirement; `E_FIELD_*`/value errors (model_validator) for cross-field exclusivity.**
  A forward reference does not resolve *at the point it is needed* (the referent is not
  yet materialized), so `E_TARGET_UNKNOWN` ("this reference does not resolve") is a
  defensible, documented stretch that keeps the new rule single-code and the contract
  surface minimal. No new code; no dead failure path.

**Q5 — What the consumer (voom-v2) dedups against — on-disk file sha256 or the
recorded manifest hash.**
- *Context:* voom-v2's behavior is not visible from this repo. If it re-hashes files on
  disk, only an on-disk grind (Q3a) exercises its dedup; if it trusts the manifest
  hash, the oracle-record collision (Q3b) is exact and far cheaper.
- *Rejected: block on confirming voom-v2's behavior.* Stalls a self-contained schema
  change on an external dependency.
- *Rejected: build the expensive on-disk grind now to cover both.* Over-engineers
  ahead of a confirmed need (premature) and adds an ffmpeg-version-sensitive,
  capped-failure surface.
- **Chosen: ship the cheap oracle-recorded collision now** (matching AGENTS.md's
  neutral-oracle philosophy — chaos-librarian emits oracle records, not app state) and
  **file the on-disk grind as a follow-up** to be implemented if voom-v2 is confirmed
  to re-hash on disk.
