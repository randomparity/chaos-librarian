# 0005 — Author hardlinked assets that share one inode

## Status

Accepted

## Context

The scanner-resilience recipe category (#108) cannot express
`scanner/hardlink-duplicates`: the scenario schema has no inode/hardlink concept, so
every asset is an independent file (#178). A hardlink is two directory entries pointing
at **one** inode (shared `st_ino`/`st_dev`, link count > 1, in-place mutation of one path
reflected on the other) — a distinct scanner stressor from #180's `same_content_as`,
which **copies** bytes into two **independent** files (distinct inodes, link count 1, no
mutation propagation). Both produce byte-identical content and the same full
`content_hash`; only the on-disk identity differs.

The materializer writes each asset's file under `<run-dir>/library/<path>` in a single
declaration-ordered pass (`materializer/synthesis.py::materialize_assets_phase_a`), and
#180 already established the orchestrator-layer short-circuit `_copy_same_content_asset`
that resolves a referent's already-written file and produces a parallel file. The
manifest (`ManifestVersion`/`ManifestLocation`/`MaterializedAsset`) records no inode or
link count today.

This is a scenario-schema change (`SCENARIO_SCHEMA_VERSION` 25 → 26) reusing #180's
reference machinery and failure surface, so the decisions below are recorded with their
rejected alternatives to keep settled choices from reopening during review.

## Decision

Add one flat optional field `Asset.hardlinked_to: str | None`, an asset-id reference. The
materializer synthesizes the referent once and **`os.link`s** the referrer's path to the
referent's already-written file, so both paths share one inode (link count >= 2,
byte-identical content, same full `content_hash`). The model validator enforces mutual
exclusivity with `same_content_as` and `hash_collision_with`; the existing semantic rule
`rule_content_reference` resolves the reference and additionally rejects cross-root links.

1. **Hardlink = `hardlinked_to: str | None`, a parallel field — not a mode of
   `same_content_as`.** It reuses #180's reference machinery (asset-id reference,
   earlier-declaration requirement, `E_TARGET_UNKNOWN`, orchestrator short-circuit) but
   swaps `shutil.copyfile` for `os.link`. A hardlink and a content copy are different
   chaos shapes (shared inode vs independent files); a `mode` flag would muddy both the
   validator and the materializer.
2. **Materialization = `os.link` from the referent's already-written file**, in the
   orchestrator `materialize_assets_phase_a` alongside the `same_content_as`
   short-circuit (a new `_hardlink_asset` helper near-twin of `_copy_same_content_asset`).
   `materialize_one_asset`'s signature is unchanged.
3. **The manifest records nothing new about the inode/link count (schema-neutral).** The
   referrer gets its own `ManifestLocation` and the shared full `content_hash`; no inode
   number, link count, or shared-inode grouping is recorded. `MANIFEST_SCHEMA_VERSION` and
   `MATERIALIZATION_SCHEMA_VERSION` are unchanged; the only contract bump is
   `SCENARIO_SCHEMA_VERSION` 25 → 26.
4. **Reference/shape errors only.** Unknown, self, and forward references →
   `E_TARGET_UNKNOWN` (extending `rule_content_reference`). Cross-field misuse (any link
   field paired with `hardlinked_to`; `hardlinked_to` + own `subtitles`) → `E_FIELD_SHAPE`
   in the model validator. No cross-root rule: all assets share one filesystem under
   `<run-dir>/library/`, so `os.link` never raises `EXDEV` (Q4). The `os.link` always
   succeeds for a valid reference, so there is no `E_*_UNSATISFIABLE` runtime failure.

## Consequences

- One scanner recipe ships (`scanner/hardlink-duplicates`); `recipes/scanner/` grows
  4 → 5.
- A scanner under test observes the shared inode on disk (`st_ino`, `st_dev`, `st_nlink`);
  chaos-librarian records only the neutral facts (each path's location, the shared
  `content_hash`). A scanner that double-counts hardlinks, or conflates a hardlink with a
  content copy, is exercised.
- Omitting `hardlinked_to` is byte-identical to today (regression-tested): the orchestrator
  takes the unchanged synthesis branch and no `os.link` is called.
- `hardlinked_to` requires the referent declared **earlier** (single ordered materialize
  pass; `os.link` needs the referent file to already exist). Forward references rejected at
  validate time.
- `hardlinked_to` is **forbidden** on an asset declaring its own `subtitles` (v1
  limitation, same as `same_content_as`): the asset shares the referent's inode, so its own
  track/sidecar spec is ignored for bytes and the link path writes no sidecars.
- The link path reproduces every per-asset contribution synthesis makes: a **synthetic
  `ToolInvocation`** (`tool="hardlink"`, `exit_code=0`) keeps the "one invocation per asset"
  invariant and gives the referrer a real `invocation_index`; the linked file is
  **re-probed**; the link contributes **no `ContentSourceEvidence`** (a link resolves no
  synthesis source, and inventing an entry would need a new closed-enum `ContentTrackKind`
  member that drifts two versioned schemas).
- No cross-root rule: every asset materializes under one `<run-dir>/library/` tree on a
  single filesystem (`synthesis.py:144` uses the declared root only as a path-prefix
  component), so `os.link` never crosses a device and `EXDEV` cannot occur. An `EXDEV`
  rule is a filed follow-up, needed only if roots are ever mapped to distinct devices.
- Mutation propagation (write one path, the other reflects it) is an automatic consequence
  of the shared inode, tested on disk at phase A. No timeline action rewrites a hardlinked
  path in place — byte-rewriting actions (`reencode_video`, `truncate_file`, `corrupt_*`)
  write a new output file at a new version (replacing the entry, breaking the link), which
  is their real replace semantics. An in-place mutation timeline action is a filed
  follow-up if a recipe needs it.

## Considered & rejected

**Q1 — How a shared-inode hardlink is referenced.**
- *Rejected: a named-inode registry / first-class N-way link group entity*
  (`inodes: [{id, members: [...]}]`). Adds a top-level entity and a second identity
  namespace for a one-recipe feature — premature abstraction. An N-way link set is already
  expressible as a chain/fan of pairwise `hardlinked_to` references (each to an earlier
  asset), which all resolve to one inode transitively.
- *Rejected: a `mode` flag on `same_content_as`* (`same_content_as: X, mode: hardlink`).
  Conflates two semantically different shapes (shared inode vs independent copy) with
  different on-disk identity and different consumer expectations, muddying the validator and
  the materializer dispatch.
- **Chosen: `Asset.hardlinked_to: str | None`, a parallel asset-id reference** reusing
  #180's reference machinery and swapping the materialization primitive. Smallest surface,
  matches the flat-field convention, unambiguous semantics.

**Q2 — Error contract for invalid references.**
- *Rejected: a new `E_HARDLINK_*` family.* The `os.link` strategy always succeeds for a
  valid same-root, earlier-declared reference, so a dedicated runtime-failure code would be
  dead; reference errors should match #180's existing contract, not fragment it.
- *Rejected: a distinct ordering code for forward references.* `E_LIFECYCLE_INVALID` is
  contract-scoped to *timeline* execution order, but `hardlinked_to` is an
  asset-declaration field; routing it through a timeline-lifecycle code would misclassify
  it (the same reasoning ADR 0004 Q4 applied to `same_content_as`).
- **Chosen: `E_TARGET_UNKNOWN` for unknown/self/forward references** (extending
  `rule_content_reference`, single code, documented forward-ref stretch — a forward
  reference does not resolve at the point it is needed), and **`E_FIELD_SHAPE`** for
  cross-field misuse. No new code; no dead failure path.

**Q3 — What the manifest/oracle records about the inode.**
- *Rejected: record the runtime inode number* (`st_ino`) on the version/location row.
  `st_ino` is filesystem-/run-assigned and non-deterministic — it would break manifest
  byte-stability and the run/replay manifest-equality invariant, and it leaks a value the
  consumer reads from disk anyway.
- *Rejected: record a link count or a shared-inode group id.* Link count is more stable but
  still adds a versioned-schema field with no consumer contract and pre-judges the
  consumer's detection job; a synthetic group id invents an identity namespace (cf. Q1).
- **Chosen: record nothing new (schema-neutral).** The shared inode and link count are
  genuinely present on disk and observed there by the consumer (`os.stat`); the manifest
  keeps recording the neutral facts (each location, the shared `content_hash`). Matches
  #180's schema-neutral approach and AGENTS.md's neutral-oracle philosophy. Only
  `SCENARIO_SCHEMA_VERSION` bumps.

**Q4 — Cross-filesystem / cross-root hardlinks.**
- *Context:* `os.link` raises `EXDEV` across devices. But the current materializer lays
  every asset out under one `<run-dir>/library/` tree on a single filesystem
  (`synthesis.py:144` reads `roots[0].path` and uses the declared root only as a leading
  path *component*, not a device boundary), so no two assets are ever on different devices.
- *Rejected: add a cross-root rejection rule anyway* (`E_FIELD_SHAPE` when referent and
  referrer declare different roots). It would be **dead** — `os.link` cannot fail with
  `EXDEV` given the single-filesystem layout — adding validation surface, a semantic-rule
  branch, and an invalid fixture for a failure mode that cannot occur.
- *Rejected: allow it and let `os.link` fail at materialize time.* No failure exists to
  surface; this is a non-issue, not a deferred runtime crash.
- **Chosen: add no cross-root rule; document the single-filesystem layout as the supported
  assumption.** If a future change maps library roots to distinct devices, an `EXDEV`
  rejection rule becomes necessary and is a filed follow-up — not v1 scope.

**Q5 — Mutation propagation as a timeline feature.**
- *Rejected: add a timeline action that rewrites a hardlinked path in place* to demonstrate
  propagation. No existing action rewrites bytes in place (all byte-changing actions write
  a new output file at a new version, which would break the link), so this would be net-new
  timeline machinery beyond the issue's scope.
- **Chosen: treat propagation as the automatic consequence of the shared inode it is**, and
  verify it directly on disk (a phase-A test writes through one path and reads the other).
  An in-place-mutation timeline action is a filed follow-up if a recipe needs it.
