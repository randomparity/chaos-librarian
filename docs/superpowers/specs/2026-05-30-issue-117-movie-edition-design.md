# Issue #117 — Movie release/edition modeling

## Problem

Movie release/edition modeling was deferred from the #106 hierarchy redesign,
which intentionally kept movies as `movies → variants → bundles → assets`. Real
movie libraries distinguish *editions* of the same film — theatrical cut,
director's cut, extended, unrated — and media scanners (Plex, Jellyfin) key on a
`{edition-...}` filename token to keep those editions as separate, identifiable
items in one movie folder. chaos-librarian cannot currently author an edition,
so it cannot generate this real-world fixture shape.

#117 must decide whether editions deserve a first-class hierarchy layer or can
remain a variant attribute, then implement the chosen model end-to-end: schema,
path rendering, validation, manifest/oracle impact, and backward compatibility.

## Scope (resolved decisions)

The architecture decision and its companions were resolved at a design
checkpoint. The full decision set, with rejected alternatives, lives in
[ADR 0010](../../adr/0010-movie-edition-modeling.md). Summary:

- **Q-core — model:** edition is an **optional attribute on `Variant`**, not a
  new hierarchy layer. Add `edition: EditionKind | None = None`. No new
  `ParentKind`, no movie-shape migration, no manifest bump. (Options B
  "first-class `movie → edition → variants` layer" and C "optional grouping
  layer" rejected — see ADR.)
- **Edition kinds:** a **closed `EditionKind` StrEnum**:
  `theatrical / directors_cut / extended / unrated`. No free-form escape hatch
  in v1; regional/free-form editions are a filed follow-up.
- **Path rendering:** the edition renders as a Plex/Jellyfin
  `{edition-<Title Case Name>}` suffix on the **filename stem**. No per-edition
  subfolder.
- **Edition timeline action:** **deferred**. No `relabel_edition` in v1; renames
  and moves stay expressible through existing asset/variant actions. Filed as a
  follow-up.
- **Validation:** **reuse existing codes.** Edition becomes part of variant
  identity for collision purposes; two variants that render to the same path
  (same resolution label + same edition) are `E_PATH_COLLISION`. No new code.
- **Oracle/manifest:** **no new rows, no manifest bump.** The edition only
  changes the rendered path string, already recorded per-asset in
  `ManifestLocation.path`. `MANIFEST_SCHEMA_VERSION` stays at **10**.
- **Schema:** `SCENARIO_SCHEMA_VERSION` **30 → 31** (the field is additive and
  optional, but every model hardcodes the `Literal` and every fixture pins the
  version, so the bump + artifact regen + fixture re-pin are required).

## Topology and schema

`contract/scenario.py` gains one enum and one optional field. No new model, no
new top-level tuple, no new `ParentKind`:

```text
EditionKind(StrEnum):
    THEATRICAL    = "theatrical"
    DIRECTORS_CUT = "directors_cut"
    EXTENDED      = "extended"
    UNRATED       = "unrated"

Variant(id, label, edition: EditionKind | None = None, bundle: Bundle)
```

`Scenario` bumps `SCENARIO_SCHEMA_VERSION` 30 → 31. `Variant.edition` defaults to
`None`, so a variant with no edition is byte-identical to its pre-change form on
the wire.

`edition` lives on `Variant`, not on `Movie`, because a movie can carry several
editions side by side (a theatrical 1080p and a director's-cut 1080p are
separate variants under one movie). The field is valid for **every** parent kind
the variant can hang under (movie/episode/track/podcast_episode) at the type
level, but only the movie path renders the token in v1; under non-movie parents
the field is structurally accepted but the renderer ignores it (it is not part
of the TV/music/podcast naming recipe). Restricting the field to movie variants
would require a parent-aware validation rule with no behavioral payoff for v1;
the no-op-elsewhere choice matches how optional asset knobs already behave.

## Path rendering

`path_rendering.py` renders the edition token into the **filename stem** for the
`MOVIE` parent kind. `RenderableAssetContext` gains
`edition: EditionKind | None = None`. The movie filename becomes:

```text
movie_flat:   <root>/<Title> - <label>[ - <role>] {edition-<Name>}.<container>
movie_folder: <root>/<Title>/<Title> - <label>[ - <role>] {edition-<Name>}.<container>
```

Example: `Orbit - 1080p {edition-Director's Cut}.mkv`.

The edition token is appended **after** the variant-label / multi-asset-role
suffix and **before** the extension, matching the Plex/Jellyfin convention where
the `{edition-...}` token is the last stem component. The token name is the
edition's **display name in title case** (`directors_cut` →
`Director's Cut`, `theatrical` → `Theatrical`, `extended` → `Extended`,
`unrated` → `Unrated`). The mapping from enum member to display name is an
explicit table in `path_rendering.py` (not derived by string munging — `directors_cut`
must render the apostrophe), so a new enum member fails loudly until a display
name is added.

When `edition` is `None`, the stem is unchanged from today, so existing movie
paths are byte-identical.

The display name is passed through `clean_display_component`, identical to the
title and label, so it cannot inject path syntax. The braces `{` `}` and the
literal `edition-` prefix are added after sanitization; the sanitizer permits
braces in display components today (it only strips control chars, collapses
whitespace, and replaces slashes — verified against `clean_display_component`),
so the token shape is stable. `_filename` gains the edition-suffix step; the
episode/track/podcast stems are untouched.

### Sidecar paths inherit the edition-suffixed stem

`render_declared_sidecar_path` derives a sidecar's path from the media path by
splitting off the final extension and writing `<media stem>.<language>.<codec>`.
For an edition variant the media filename is
`Orbit - 1080p {edition-Director's Cut}.mkv`, so the inherited stem is
`Orbit - 1080p {edition-Director's Cut}` and the declared sidecar renders to
`Orbit - 1080p {edition-Director's Cut}.en.srt` — beside its edition's media
file, which is correct: the sidecar must track the edition it belongs to. This
falls out of the existing media-stem-derived sidecar convention with **no
sidecar code change**, because the edition token is already in the media stem
before the sidecar path is derived. `create_sidecar`, `embed_subtitle`, and
`extract_subtitle` likewise build off the (now edition-suffixed) media path with
no change. A test asserts a declared subtitle sidecar for an edition variant
renders next to the edition media file.

## Validation

Reuse existing error codes only (ADR 0008 / 0009 precedent):

- `E_PATH_COLLISION` — two variants under one movie that render to the same path.
  Because the edition token is part of the stem, a theatrical 1080p and a
  director's-cut 1080p render to **distinct** paths and do **not** collide; two
  variants with the **same** label and **same** edition (or both `None`) still
  collide exactly as today. The existing `rule_rendered_path_collisions` already
  compares full rendered paths, so it picks this up with **no rule change** once
  the raw-walker renderer in `validation/rules/_common.py` threads `edition`
  into its `RenderableAssetContext`.
- No structural edition rule is needed: `EditionKind` is a closed enum, so an
  unknown value is a Pydantic enum error at parse time (the shape-validation
  layer), not a semantic rule. There is no cross-entity reference, no numbering,
  and no ordering to validate.

The closed-enum decision means the *only* validation surface is the existing
path-collision rule already exercised by movie variants. If implementation
surfaces a genuinely new uniqueness rule (e.g. "a movie may not declare two
variants with the same (label, edition) pair" as a distinct code from
path-collision), that is a new contract decision and stops for sign-off; the
current design asserts the path-collision rule is sufficient because identical
(label, edition) pairs already render identical paths.

**Edition affects paths, not entity identity.** Entity identity stays driven by
ids: `rule_id_duplicate` rejects duplicate variant/bundle/asset ids regardless
of edition, and the edition does **not** disambiguate ids. The edition only
changes the rendered path string. The valid two-edition fixture therefore uses
distinct variant, bundle, and asset ids for the two editions (only their
rendered paths differ by the edition token); reusing an id across editions is
the existing `E_*_DUPLICATE`, unrelated to the edition.

## Validation projection

`validation/rules/_common.py` builds a parallel raw-dict `RenderableAssetContext`
for movie assets (`_movie_renderable_context` / the movie branch of the asset
context walker). That builder gains an `edition` read from the raw variant
mapping (`_enum(EditionKind, variant.get("edition"))`, tolerating `None`). No new
projection state, no new `apply` branch — there is no edition timeline action, so
the `HierarchyProjection` is untouched.

## Engine and materializer

- `topology.py` `RenderableAssetContext` construction in
  `renderable_asset_context` threads `context.variant.edition` through. No walker
  change (the edition rides on the already-walked `Variant`).
- `engine/state.py` seeds initial locations through the shared renderer, so movie
  variants with an edition get the edition-suffixed initial path automatically.
  No new manifest row, no new dispatch entry.
- The materializer realizes movie assets through the same
  `iter_asset_contexts → renderable_asset_context → render_asset_path → synthesis`
  pipeline, so an edition variant materializes to its edition-suffixed path with
  no materializer change.

## Oracle / manifest

`contract/manifest.py` is **unchanged**; `MANIFEST_SCHEMA_VERSION` stays at
**10**. The edition is recovered from the rendered path string already carried by
`ManifestLocation.path` (and `ManifestVersion`/initial-location seeding), so no
new neutral fact is added. Adding `edition` to `ManifestVariant` would be a
manifest schema change requiring a bump; the rendered path *is* the neutral fact,
consistent with the no-manifest-bump decision.

## Backward compatibility

This property is load-bearing and is asserted by a regression test. Every
existing scenario stays valid beyond the mandatory `schema_version: 31` re-pin:

- `Variant.edition` defaults to `None`; a variant with no edition serializes and
  renders byte-identically to its pre-change form.
- No movie-shape migration: `movies[*].variants[*]` keeps its structure.
- No new `ParentKind`, no new top-level tuple, no manifest change, no new
  timeline action — TV, music, and podcast topology are untouched.

A regression test asserts that a movie scenario **with no editions** plus the
existing TV/music/podcast fixtures render the same paths and produce
structurally and content-identical manifests and journals as before, modulo any
embedded `schema_version` value the version bump necessarily changes. (No
golden manifest/journal artifact pins the scenario version as a literal JSON
file in the corpus; fixtures are scenario YAMLs re-pinned to 31, and
manifests/journals are computed in-test.)

## Schema artifacts and fixtures

`schema_export --write` regenerates `scenario.schema.json` (the only schema that
changes — `Variant` gains an optional `edition` enum field). The manifest schema
is unchanged. The ~144 fixture / recipe files pinning `schema_version: 30` re-pin
to `31`. New movie-edition fixtures join the corpus:

- one valid scenario declaring a movie with two editions (theatrical + director's
  cut at the same resolution) that render to distinct paths;
- one invalid scenario where two variants share the same (label, edition) and
  collide → `# expected: E_PATH_COLLISION`.

## Testing

- A movie variant with `edition: directors_cut` validates and materializes to
  `<root>/<Title> - <label> {edition-Director's Cut}.<ext>` (flat) and the
  `movie_folder` equivalent.
- Each `EditionKind` member renders its correct title-case token
  (`theatrical`/`directors_cut`/`extended`/`unrated`), including the apostrophe
  in `Director's Cut`.
- A movie with two editions at the same resolution label renders **distinct**
  paths and validates clean.
- Two variants with the same (label, edition) — or both edition `None` and same
  label — render the same path → `E_PATH_COLLISION` (edge/error path).
- A variant with `edition: None` renders the pre-change path (no token), and the
  multi-asset role suffix still precedes the edition token when both are present.
- A declared subtitle sidecar for an edition variant renders next to the edition
  media file (the sidecar stem inherits the `{edition-...}` token).
- Backward-compat regression: an existing no-edition movie scenario plus the
  TV/music/podcast fixtures produce unchanged rendered paths, manifests, and
  journals at `schema_version: 31`.
- The v30 → 31 bump is asserted; `MANIFEST_SCHEMA_VERSION` stays 10 (asserted).
- An unknown `edition` string fails Pydantic enum validation at parse time.

## Deferred follow-ups (filed before merge)

- Regional / free-form editions (an open `edition_label` escape hatch and/or a
  `regional` edition concept with a region code).
- A first-class `relabel_edition` timeline action.
- The Option-B capability: a first-class `movie → edition → variants` layer for
  multi-variant editions (one edition owning both HD and 4K variants), enabling
  edition-scoped moves — to be reconsidered if a real scenario needs it.
