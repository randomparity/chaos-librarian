# 0006 — Author symlink assets (in-root and library-escaping)

## Status

Accepted

## Context

The scanner-resilience recipe category (#108) cannot express
`scanner/symlink-external`: the scenario schema has no symlink concept, and the one
shape that recipe needs — a link whose **target escapes the library root** — is
exactly what `E_PATH_CONTAINMENT` forbids for every authored path (#179). A symlink
is a directory entry that **points at another path** rather than holding bytes; a
scanner must decide whether to **follow** it (treat the target as the asset) or
**reject/skip** it (refuse to leave the scanned root). Two sub-shapes stress that
decision: an **in-root** link (points at another in-library asset) and a
**library-escaping** link (points outside `library/`).

The three prior reference fields — `same_content_as` (#180, `shutil.copyfile`),
`hardlinked_to` (#178, `os.link`), `hash_collision_with` (#180) — are all asset-id
references to an earlier asset whose real file already exists, and all produce a
**regular file** whose target is inside `library/` and always present. A symlink
differs on two axes none of them touch: the materialized object **is a symlink**
(`os.path.islink`), and its target **may point outside the library root** — the
entire point of `scanner/symlink-external`.

The materializer writes each asset under `<run-dir>/library/<path>` in a single
declaration-ordered pass (`materializer/synthesis.py::materialize_assets_phase_a`);
`out_dir` is the run dir and `out_dir/library` is the library root
(`run.py:188`). #178 established the orchestrator-layer short-circuit
`_hardlink_asset` (twin of `_copy_same_content_asset`) that resolves a referent's
already-written file and produces a parallel on-disk object. The manifest records no
link/inode/target field today.

This is a scenario-schema change (`SCENARIO_SCHEMA_VERSION` 26 → 27) reusing the
prior fields' reference machinery and failure surface, with two genuinely new
decisions (escaping-target containment, follow/reject policy), so the choices are
recorded with rejected alternatives to keep settled questions from reopening.

## Decision

Add one flat optional field `Asset.symlink: SymlinkTarget | None`, where
`SymlinkTarget` carries exactly one of `to_asset` (an in-root asset-id reference) or
`to_run_dir_path` (a library-escaping relative path resolving inside the run dir but
outside `library/`). The materializer `os.symlink`s the referrer's path to the
resolved target in a new `_symlink_asset` orchestrator helper. The follow/reject
expectation is **documentation prose only** — not machine-encoded. The manifest
records nothing link-specific. Containment of the escaping target is enforced by a
new rule mapping run-dir escapes to a new code `E_SYMLINK_TARGET_ESCAPE`, leaving
`E_PATH_CONTAINMENT` and `resolve_under_library` untouched.

1. **Symlink = `symlink: SymlinkTarget | None`, a parallel field** reusing the prior
   fields' reference machinery (asset-id reference for `to_asset`,
   earlier-declaration requirement, `E_TARGET_UNKNOWN`, orchestrator short-circuit,
   synthetic ToolInvocation) and swapping the primitive to `os.symlink`. The link is
   created with a **run-dir-relative** target (`os.path.relpath` against the link's own
   parent) so no absolute run-specific path is written to disk and the materialized
   tree is portable / replay-stable. The materializer **checks the resolved target
   exists** before linking and fails loud with a new `MaterializationError`
   (`E_SYMLINK_TARGET_MISSING`) if not.
2. **Two named target forms** (`to_asset` xor `to_run_dir_path`), not a `kind` enum or
   a single overloaded string: in-root is an id, escaping is a path; they are
   structurally different and validate differently.
3. **Policy-neutral.** No `symlink_expected_policy` field, no `D_SYMLINK_POLICY`
   divergence code. chaos-librarian records only neutral on-disk facts; the consumer
   observes `os.path.islink` + the link target and applies its own follow/reject
   policy. Follow/reject lives in recipe-doc prose, like every #108 recipe.
4. **Escaping targets are sandboxed to the run dir.** A `to_run_dir_path` must resolve
   inside `<run-dir>/` and outside `library/`; an in-library, absolute, or
   run-dir-escaping target is rejected with `E_SYMLINK_TARGET_ESCAPE`. A link to a
   host path is never materialized.
5. **`E_PATH_CONTAINMENT` is unchanged.** The asset's own rendered path still flows
   through the renderer + path-safety rules and stays contained; the symlink target is
   a separate field never fed to `resolve_under_library`.
6. **Schema-neutral manifest.** The referrer gets its own `ManifestLocation` and the
   resolved target's `content_hash`; no link flag, target, or realpath is recorded.
   Only `SCENARIO_SCHEMA_VERSION` 26 → 27 bumps; manifest / materialization /
   replay-bundle versions are unchanged.
7. **Dangling deferred.** v1 requires the target to exist at materialize time (so the
   link can be probed like every other asset). Dangling links are a filed follow-up.
8. **Reference/shape errors reuse existing codes.** Unknown/self/forward `to_asset`
   → `E_TARGET_UNKNOWN`; cross-field misuse (`symlink` + any link field;
   `symlink` + own `subtitles`; neither/both target forms) → `E_FIELD_SHAPE`. The
   run-dir-escape check introduces the validate-time code `E_SYMLINK_TARGET_ESCAPE`,
   and the materialize-time existence check introduces `E_SYMLINK_TARGET_MISSING` (a
   `MaterializationError`, fail-loud rather than silent-skip).

## Consequences

- One scanner recipe ships (`scanner/symlink-external`, the in-root form);
  `recipes/scanner/` grows 5 → 6.
- A scanner under test observes the link on disk (`os.path.islink`, `os.readlink`,
  `os.stat` vs `os.lstat`); chaos-librarian records only neutral facts (the link's own
  location, the resolved target's `content_hash`). A scanner that follows an escaping
  link out of its root, or double-counts an in-root link by realpath, is exercised.
- Omitting `symlink` is byte-identical to today (regression-tested): the orchestrator
  takes the unchanged synthesis branch and no `os.symlink` is called.
- `symlink.to_asset` requires the referent declared **earlier** (single ordered pass;
  `os.symlink`'s v1 target must already exist). Forward references rejected at
  validate time with `E_TARGET_UNKNOWN`.
- `symlink` is **forbidden** on an asset declaring its own `subtitles` (v1 limitation,
  same as the prior three): the asset materializes a link, so its own track/sidecar
  spec is ignored and the link path writes no sidecars.
- The link path reproduces every per-asset synthesis contribution: a synthetic
  `symlink` `ToolInvocation` keeps the "one invocation per asset" invariant and gives
  the referrer a real `invocation_index`; the resolved target is re-probed; the link
  contributes no `ContentSourceEvidence`.
- Two new codes enter the public set (additive, non-breaking): validate-time
  `E_SYMLINK_TARGET_ESCAPE` and materialize-time `E_SYMLINK_TARGET_MISSING`. They are
  the only contract surface that genuinely differs from the prior fields.
- **Replay holds schema-neutrally and portably.** A pure replay re-runs materialization
  into a fresh run dir; `_symlink_asset` re-runs `os.symlink` there, reconstructing the
  link from the scenario `symlink` field alone — the same property #178 relies on for
  `os.link`. Because the on-disk target is **run-dir-relative**, the link is identical
  regardless of the absolute run-dir path and resolves after the tree is moved/replayed.
- Dangling links, user-authored escaping-target creation, and machine-encoded
  follow/reject policy are out of v1 scope; dangling / target-authoring is a filed
  follow-up. A missing target at materialize time is the loud
  `E_SYMLINK_TARGET_MISSING`, not a successfully-materialized dangling link.

## Considered & rejected

**Q1 — Whether to machine-encode the consumer's follow/reject expectation.**
- *Rejected: a `symlink_expected_policy: follow|reject` field recorded as a
  materialization audit row* (precedent: `wrong_oracle_hash`). It would be the first
  "expected consumer outcome" baked into the neutral tool, directly contradicting
  AGENTS.md ("does NOT know the application's expected policy outcomes") and the #108
  non-goal ("expected-response text is documentation only").
- *Rejected: a `D_SYMLINK_POLICY` divergence code* in the compare layer — bakes the
  policy judgment even deeper into the neutral tool.
- **Chosen: policy-neutral.** Record only on-disk facts (the link, its target, its
  nature); the consumer observes them and applies its own policy. Follow/reject lives
  in recipe-doc prose. Consistent with the architecture and every other recipe.

**Q2 — How an escaping target is authored without weakening `E_PATH_CONTAINMENT`.**
- *Rejected: a relaxation flag (`allow_escape: true`) on the existing path machinery.*
  Widens the blast radius of the security-critical `resolve_under_library` helper for
  one feature; a bug in the flag path weakens containment for ordinary paths.
- *Rejected: a separate top-level symlink entity with its own path field.* Adds a
  second identity namespace for a one-recipe feature (cf. Q7).
- **Chosen: a dedicated `symlink` field whose target is structurally outside the
  containment-checked set.** The asset path still flows through the unchanged
  renderer + path-safety rules; the target is never passed to `resolve_under_library`.
  `E_PATH_CONTAINMENT` stays byte-for-byte unchanged.

**Q3 — What an escaping target may point at.**
- *Rejected: any absolute/host path the author writes.* A chaos tool materializing a
  link to `/etc/passwd` (followed by a consumer) is a real footgun.
- *Rejected: only `../`-relative targets capped to the library parent.* More awkward
  to author than a run-dir-relative path and offers no extra safety.
- **Chosen: the target must resolve inside the run dir, outside `library/`** ("external
  to the library root, internal to the sandbox"). Expresses "target outside the
  scanned root" — the actual stressor — while the sandbox boundary stays the run dir.

**Q4 — Error contract for the escaping-target check.**
- *Rejected: reuse `E_PATH_CONTAINMENT`.* Escaping the library is the **intended**
  chaos here, so reusing the "escapes library" code would misclassify a valid recipe
  as a containment violation and there'd be no way to distinguish the legal escape
  from the illegal run-dir escape.
- *Rejected: a whole `E_SYMLINK_*` family.* Only two genuinely new failure modes exist
  (validate-time run-dir escape; materialize-time missing target); the rest reuse the
  prior fields' codes, so a broad family would be mostly dead.
- **Chosen: reuse `E_TARGET_UNKNOWN` (unknown/self/forward `to_asset`) and
  `E_FIELD_SHAPE` (cross-field / target-form misuse); add `E_SYMLINK_TARGET_ESCAPE`**
  (validate-time) for an in-library / absolute / run-dir-escaping `to_run_dir_path`,
  **and `E_SYMLINK_TARGET_MISSING`** (materialize-time `MaterializationError`) for a
  resolved target absent on disk — fail-loud rather than silent-skip.

**Q5 — Dangling symlinks (target absent).**
- *Rejected: support dangling in v1.* A dangling link has no bytes to `probe_file`, so
  it cannot carry the `content_hash`/`size`/`duration` every `MaterializedAsset` has;
  supporting it forces nullable probe fields or a distinct symlink manifest record — a
  manifest/materialization schema bump beyond the scenario bump, contradicting the
  schema-neutral goal (Q6).
- **Chosen: defer dangling.** v1 requires an existing target so the link probes like
  any asset; a target absent at materialize time is the loud `E_SYMLINK_TARGET_MISSING`
  (not a successfully-materialized dangling link). True dangling support, and a
  user-authorable escaping target the materializer *creates*, are a filed follow-up
  (nullable-probe / symlink manifest record / target authoring).

**Q6 — What the manifest records about the link.**
- *Rejected: record the link target / resolved realpath* on the location row. The
  on-disk link target is already run-dir-relative; recording a target in the manifest
  would add a versioned-schema field with no consumer contract and leak a value the
  consumer reads from disk anyway (cf. #178's inode reasoning).
- *Rejected: record an `is_symlink` boolean.* Adds a versioned-schema field with no
  consumer contract and pre-judges the consumer's detection job.
- **Chosen: record nothing new (schema-neutral).** The link-ness and target are
  genuinely on disk (`os.path.islink`, `os.readlink`) and observed there; the manifest
  keeps the neutral facts (the link's location, the resolved target's `content_hash`).
  Matches #178/#180. Only `SCENARIO_SCHEMA_VERSION` bumps. Replay reconstructs the link
  from the scenario field (confirmed above).

**Q7 — Field shape: sub-model with two named forms vs `kind` enum vs raw string.**
- *Rejected: a single `symlink_target: str` + a `symlink_kind: in_root|escaping` enum.*
  Overloads one string to mean an asset-id in one mode and a path in the other; the
  validator must branch on the enum to decide which namespace the string lives in.
- *Rejected: a first-class N-way symlink registry.* Premature abstraction for a
  one-recipe feature (cf. #178 Q1).
- **Chosen: a `SymlinkTarget` sub-model with `to_asset` xor `to_run_dir_path`.** Each
  form has its own type and validation path (id-reference vs run-dir path); "exactly
  one of two named fields" mirrors `hash_collision_with` + `collision_prefix_len` and
  reads unambiguously.
