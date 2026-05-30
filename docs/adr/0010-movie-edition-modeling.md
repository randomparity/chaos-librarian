# 0010 — Movie release/edition modeling

## Status

Accepted

## Context

The #106 hierarchy redesign shipped movie, TV, and music topology and
deliberately **deferred** movie releases/editions. Real movie libraries
distinguish *editions* of one film — theatrical cut, director's cut, extended,
unrated — and media scanners (Plex, Jellyfin) key on a `{edition-...}` filename
token to keep those editions as separate items inside a single movie folder.
chaos-librarian could not author an edition, so it could not generate this
real-world fixture shape.

The established pattern models each work-type as a parallel top-level tuple
(`movies` / `series` / `artists` / `podcasts`), each a nested hierarchy ending in
`variants → bundle → assets`, with a per-asset `ParentKind` threaded through
`scenario.py`, `path_rendering.py`, `topology.py`, the raw-dict validation walker
in `validation/rules/_common.py`, engine state, and the manifest. A movie
`Variant.label` today is a free-form resolution/encoding tag (`hd`, `uhd`,
`1080p`); the renderer puts it into the filename
(`<root>/<Title> - <label>.<ext>`). There is no edition concept and no
`{edition-...}` rendering today. ADR 0008/0009 set the precedent of reusing
existing error codes and keeping the oracle policy-neutral.

The defining question is architectural: does an edition deserve a first-class
hierarchy layer, or is it an attribute of the existing variant?

## Decision

1. **Edition as an optional `Variant` attribute (Option A).** Add
   `edition: EditionKind | None = None` to `Variant`. No new hierarchy layer, no
   new `ParentKind`, no movie-shape migration. A movie carrying several editions
   declares several variants (a theatrical 1080p and a director's-cut 1080p are
   sibling variants under one movie).
2. **Closed `EditionKind` enum.** `theatrical / directors_cut / extended /
   unrated`. No free-form escape hatch in v1. An unknown value is a Pydantic enum
   error at parse time, not a semantic rule. Regional/free-form editions are a
   filed follow-up.
3. **Filename-stem `{edition-...}` token.** The edition renders as a Plex/Jellyfin
   `{edition-<Title Case Name>}` suffix on the filename stem, appended after the
   variant-label / multi-asset-role suffix and before the extension, e.g.
   `Orbit - 1080p {edition-Director's Cut}.mkv`. An explicit enum → display-name
   table owns the title-casing (so `directors_cut` renders the apostrophe). No
   per-edition subfolder.
4. **No edition timeline action in v1.** Renames/moves stay expressible through
   existing asset/variant actions. A first-class `relabel_edition` is a filed
   follow-up. The `HierarchyProjection` and `HIERARCHY_TIMELINE_ACTIONS` are
   untouched.
5. **Reuse `E_PATH_COLLISION`.** The edition token is part of the stem, so it
   becomes part of variant identity for collision purposes: two editions at the
   same resolution render distinct paths and do not collide; two variants with
   the same (label, edition) still collide exactly as today. The existing
   `rule_rendered_path_collisions` compares full rendered paths and needs no rule
   change. No new error code.
6. **No new `ParentKind`.** `edition` is structurally valid on any variant but
   only the `MOVIE` render branch emits the token in v1; under other parents the
   field is a no-op (matching how optional asset knobs already behave).
   Restricting it to movie variants would add a parent-aware validation rule with
   no v1 payoff.
7. **No manifest change; `MANIFEST_SCHEMA_VERSION` stays 10.** The edition only
   changes the rendered path string, already recorded per-asset in
   `ManifestLocation.path`. The rendered path *is* the neutral fact; adding
   `edition` to `ManifestVariant` would force a manifest bump for no new
   information.
8. **`SCENARIO_SCHEMA_VERSION` 30 → 31.** The field is additive and optional, but
   every model hardcodes the `Literal` and every fixture pins the version, so the
   bump + `schema_export --write` regen of `scenario.schema.json` + a re-pin of
   the ~144 fixture/recipe files are required.

## Consequences

- One scenario enum (`EditionKind`) and one optional `Variant` field enter the
  public contract. No new model, no new top-level tuple, no new `ParentKind`, no
  new timeline action, no manifest model.
- `path_rendering.py` gains an `edition` field on `RenderableAssetContext`, an
  enum → display-name table, and an edition-suffix step in the movie `_filename`
  path; `topology.py` and the raw-dict walker thread the field through. The
  episode/track/podcast render branches are unchanged.
- `SCENARIO_SCHEMA_VERSION` 30 → 31 forces a re-pin of the ~144 fixture/recipe
  files and a `schema_export --write` regen of `scenario.schema.json` only.
- Every existing scenario stays valid beyond the version re-pin; a no-edition
  variant is byte-identical to its pre-change form (path, manifest, journal). A
  regression test locks movie (no-edition) / TV / music / podcast in.
- Deferred to filed follow-ups: regional/free-form editions; a `relabel_edition`
  action; the Option-B first-class multi-variant-edition layer.

## Considered & rejected

**Q-core — how editions are modeled.**
- *Rejected: Option B — first-class `movie → edition → variants → bundles →
  assets` layer (new edition entity, edition-level `ParentKind`).* Migrates the
  established movie shape: every existing `movies[*].variants` becomes
  `movies[*].editions[*].variants`, breaking every movie scenario/fixture/recipe
  and doubling the ~2271-line raw-dict validation walker plus the typed walker,
  manifest rows, and engine seeding. Its sole advantage — one edition owning
  multiple variants (HD + 4K of the same cut) and edition-scoped chaos — has no
  demand signal in any fixture; speculative surface (AGENTS Rule 3). Backward
  compatibility is the load-bearing requirement here, and B sacrifices it.
- *Rejected: Option C — optional edition grouping layer (`Movie.variants` stays;
  add optional `Movie.editions` grouping variants by an `edition_id`).* Provides
  two ways to express the same edition (a `variant.edition` attribute vs. an
  `editions` grouping), which is exactly the dual-format / migration-path the
  project's "replace, don't deprecate — no dual config formats" rule forbids.
  Ambiguous rendering precedence and the most complex validation of the three.
- **Chosen: Option A — edition as an optional `Variant` attribute.** Matches how
  editions actually appear on disk (sibling files in one movie folder
  distinguished by a `{edition-...}` token), keeps every existing movie scenario
  valid unchanged, and avoids both the shape migration (B) and the dual-format
  trap (C). The multi-variant-edition capability B offers is filed as a follow-up
  for when a scenario needs it.

**Edition kinds — enumerated vs free-form.**
- *Rejected: a free-form `edition_label` string (or an `edition_label` escape
  hatch alongside the enum) in v1.* Every other recipe axis in the contract is a
  closed enum; a free-form label invites arbitrary tokens the renderer and any
  consumer must then sanitize and reconcile, and an escape hatch reintroduces the
  dual-format ambiguity. Regional editions (which want a structured region code,
  not a free string) are better served by a dedicated follow-up.
- **Chosen: a closed `EditionKind` enum** of the four common cuts. Unknown values
  fail at parse time; regional/free-form editions are a filed follow-up.

**Path rendering — token placement.**
- *Rejected: a per-edition subfolder
  (`<root>/<Title>/<Title> {edition-...}/<file>`).* Not the convention Plex or
  Jellyfin use for editions of one movie, and it fragments a single movie's files
  across sibling folders, diverging from the `movie_flat` / `movie_folder` shapes
  the project already ships.
- **Chosen: a filename-stem `{edition-...}` suffix**, the convention scanners key
  on, appended after the label/role suffix and before the extension.

**Edition timeline action.**
- *Rejected: ship a `relabel_edition` action in v1.* An edition under Option A is
  just part of a variant's identity; relabeling or moving an edition's files is
  already expressible via existing asset/variant actions, and a first-class
  edition action only earns its keep under Option B's multi-variant editions.
  Speculative for v1 (AGENTS Rule 3).
- **Chosen: no edition action in v1**, filed as a follow-up tied to the Option-B
  capability.

**Oracle/manifest shape.**
- *Rejected: record `edition` on `ManifestVariant` (a new neutral fact).* Forces
  `MANIFEST_SCHEMA_VERSION` 10 → 11 to carry information already recoverable from
  `ManifestLocation.path` (the rendered path contains the `{edition-...}` token).
- **Chosen: no manifest change.** The rendered path is the neutral fact;
  `MANIFEST_SCHEMA_VERSION` stays 10.
