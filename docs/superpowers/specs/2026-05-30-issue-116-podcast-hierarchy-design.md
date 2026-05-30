# Issue #116 — Podcast library hierarchy

## Problem

Podcast support was deferred from the #106 hierarchy redesign so the first
breaking contract could prove movie, TV, and music topology. Podcasts organize
episodes by publish time, not by season/episode number, and have a chaos mode
the other types lack: a *stale download* — an episode the source feed dropped
but whose file lingers in the library. The #106 design deliberately kept those
semantics out of the TV episode model; this change adds a dedicated podcast
hierarchy without disturbing movie/TV/music.

## Scope (resolved decisions)

This change ships the podcast topology, datetime-based ordering, one re-ordering
mutation, and one new chaos capability (stale-download cleanup). The full
decision set:

- **Q1 — chaos capability:** ship **stale-download cleanup only**.
  Duplicate-downloads is already expressible with `same_content_as` (#180);
  missing-episodes with `delete_file`. Stale cleanup (file lingers after the
  source drops the episode) is the one capability with no existing equivalent.
- **Q2 — topology:** new parallel top-level `podcasts: tuple[Podcast, ...]` on
  `Scenario`, new `ParentKind.PODCAST_EPISODE`, two levels (podcast → episode),
  `variants → bundle → assets` underneath exactly like the other types. No
  seasons (filed as a follow-up).
- **Q3 — time ordering:** required `published_at` as an aware RFC3339 datetime,
  the first-class ordering attribute. No `episode_number`/`season_number` on
  podcast episodes.
- **Q4 — mutation:** ship one `republish_episode` action that sets
  `published_at` (and may set `slug`) and re-renders the path, mirroring
  `renumber_episode`, so `PODCAST_EPISODE` is exercised end-to-end through the
  projection / journal / oracle path.
- **Q5 — uniqueness:** duplicate `published_at` is allowed within a podcast, but
  the rendered path must stay unique via a required `slug` tiebreaker. A
  rendered-path clash is `E_PATH_COLLISION`.
- **Q6 — oracle/manifest:** manifest v9 → v10 adds policy-neutral
  `ManifestPodcast` + `ManifestPodcastEpisode` rows (id, title, `published_at`,
  naming, neutral `stale` fact) + top-level lists + `ParentKind.PODCAST_EPISODE`
  on `ManifestVariant`. No judgment/policy fields.

## Topology and schema

New models in `contract/scenario.py`:

```text
PodcastLayout(StrEnum):       PODCAST_FOLDER = "podcast_folder"
PodcastEpisodeNaming(StrEnum): DATE_SLUG_TITLE = "date_slug_title"

Podcast(id, title, layout: PodcastLayout,
        episode_naming: PodcastEpisodeNaming,
        episodes: tuple[PodcastEpisode, ...])

PodcastEpisode(id, title, published_at: datetime, slug: str,
               stale: bool = False, variants: tuple[Variant, ...])
```

`Scenario` gains `podcasts: tuple[Podcast, ...]` and bumps
`SCENARIO_SCHEMA_VERSION` 29 → 30. `ParentKind.PODCAST_EPISODE = "podcast_episode"`.

A single layout (`PODCAST_FOLDER`) and a single naming recipe
(`DATE_SLUG_TITLE`) ship in v1. A second layout / naming recipe is speculative
surface (AGENTS Rule 3) and is filed as a follow-up.

`published_at` is a full aware RFC3339 datetime so two same-day episodes order
deterministically. Only the **date portion** (`YYYY-MM-DD`), the `slug`, and the
title render into the path. `slug` is the uniqueness tiebreaker; two episodes
sharing a `published_at` MUST carry distinct slugs or the rendered paths collide
(`E_PATH_COLLISION`).

`slug` is cleaned through the existing `clean_display_component` path-component
sanitizer (same as titles/labels), so it cannot inject path syntax.

## Path rendering

`path_rendering.py` `RenderableAssetContext` gains `podcast_title`,
`published_at: datetime | None`, and `episode_slug`. The `PODCAST_EPISODE`
branch renders:

```text
<root>/<Podcast Title>/<YYYY-MM-DD> - <slug> - <Episode Title> - <variant label>[ - <role>].<container>
```

mirroring the movie-folder shape (`<root>/<title>/<filename>`). The stem is
`"<date> - <slug> - <title>"`. The variant-label / multi-asset role suffix and
container extension reuse the shared `_filename` helper, identical to
movie/TV/music.

## The stale field vs. the action — one source of truth

`PodcastEpisode.stale: bool = False` is *recorded state*: whether the episode is
currently absent from the source feed. `mark_episode_stale` is the *primary
chaos mechanism* — the timeline transition that flips a present episode to stale
at time `at` while the file stays exactly where it is on disk.

The two are not redundant: the action sets the same state the field represents,
so "is this episode stale" has one meaning. A born-stale declared episode
(`stale: true` at declaration) is a valid-but-secondary case — the library
starts with a lingering file whose source already dropped it. The manifest
mirrors whichever state holds after the timeline runs.

`mark_episode_stale` records a neutral journal `state_delta`
(`{"stale": true, "path": <unchanged current path>}`) — a fact, not a policy.
chaos-librarian never asserts the file *should* be removed; the consumer
(voom-v2) decides. The file location is unchanged, distinguishing it from
`delete_file` (removes from disk) and `archive_file` (relocates on disk).

## Timeline actions

Two new `TimelineActionName` members and `TimelineEvent` variants:

- `republish_episode` — `target` (episode id), `published_at: datetime`,
  optional `slug: str`. Sets the episode's `published_at` (and `slug` when
  given) and re-renders its asset paths, mirroring `renumber_episode`. Joins
  `HIERARCHY_TIMELINE_ACTIONS` so the path-history projection and lifecycle
  hierarchy branch pick it up with no further wiring.
- `mark_episode_stale` — `target` (episode id). Flips the episode's recorded
  `stale` state to true. Does **not** move or remove the file; it is *not* a
  hierarchy path mutation, so it stays out of `HIERARCHY_TIMELINE_ACTIONS`.

## Validation

Reuse existing error codes only (ADR 0008 / #179 precedent):

- `E_HIERARCHY_INVALID` — structural / projection problems (e.g. a
  `republish_episode` whose target is not a podcast episode, a `slug` that
  cannot render).
- `E_PATH_COLLISION` — two episodes (declared, or after `republish_episode`)
  whose rendered initial/projected paths clash.
- `E_TARGET_UNKNOWN` — `republish_episode` / `mark_episode_stale` target id that
  resolves to nothing.

`mark_episode_stale` needs no genuinely new error code: an unknown target is
`E_TARGET_UNKNOWN`; a target that is not a podcast episode is
`E_HIERARCHY_INVALID`. No new code is introduced.

The hierarchy invariant rule (`rule_hierarchy_invariants`) gains a
`_check_podcasts` walker that validates each podcast's episode `slug`s render
and reports per-episode naming gaps the same way `_check_series` /
`_check_artists` do. Duplicate `published_at` is allowed; only the rendered path
must stay unique (caught by `rule_rendered_path_collisions`).

## Validation projection

`validation/rules/_common.py` `HierarchyProjection` gains podcast/episode state
(`_PodcastState`, `_PodcastEpisodeState`) seeded alongside series/artist state,
a `render_asset_path` branch for `PODCAST_EPISODE`, and `apply` handling for
`republish_episode` (re-render) so projected path collisions and unrenderable
paths are caught exactly like `renumber_episode`. `mark_episode_stale` is a
non-path mutation: the projection records the stale flag but emits no
`path_changes`.

## Engine and materializer

- `topology.py` gains a `_podcast_episode_asset_contexts` walker, podcast/episode
  fields on `AssetContext`, and the `PODCAST_EPISODE` branch in
  `renderable_asset_context` / `_layout_for_context`.
- `engine/state.py` seeds podcast variant/bundle rows under
  `ParentKind.PODCAST_EPISODE` and renders initial locations through the shared
  renderer. The `republish_episode` and `mark_episode_stale` handlers join the
  engine dispatch table; `republish_episode` reuses the hierarchy
  re-render/path-history machinery, `mark_episode_stale` emits one atomic
  journal entry with the neutral `stale` delta.
- The materializer realizes podcast assets through the same
  `iter_asset_contexts` → `render_asset_path` → synthesis pipeline; a stale
  episode's file is materialized normally (the point is that it lingers).

## Oracle / manifest

`contract/manifest.py` bumps `MANIFEST_SCHEMA_VERSION` 9 → 10 and adds:

```text
ManifestPodcast(id, title, layout, episode_naming)
ManifestPodcastEpisode(id, podcast_id, title, published_at, slug, stale)
```

plus top-level `podcasts` / `podcast_episodes` lists on `Manifest` and
`ParentKind.PODCAST_EPISODE` on `ManifestVariant`. All fields are neutral facts;
no policy / judgment fields.

## Backward compatibility

Every existing scenario stays valid beyond the mandatory `schema_version: 30`
bump and the manifest `schema_version: 10` bump. A scenario with no `podcasts`
and no podcast timeline actions is byte-identical to pre-change behavior — the
new top-level field defaults to an empty tuple, and `PODCAST_EPISODE` only
appears when a podcast is declared. A regression test asserts movie/TV/music
rendered paths, manifests, and journals are unchanged.

## Schema artifacts and fixtures

`schema_export --write` regenerates `scenario.schema.json` and
`manifest.schema.json` (and any report schema embedding the manifest). The
~141 fixture / recipe files pinning `schema_version: 29` re-pin to `30`; manifest
fixtures re-pin `9` → `10`. New podcast fixtures (one valid, plus invalid
fixtures for the path-collision and bad-target cases) join the corpus with the
`# expected: E_<CODE>` marker convention.

## Testing

- A podcast scenario validates and materializes to the expected on-disk
  topology (`<root>/<Podcast>/<date> - <slug> - <title> - <label>.<ext>`).
- Date ordering: two same-`published_at` episodes with distinct slugs render
  distinct paths; same slug → `E_PATH_COLLISION`.
- `republish_episode` re-renders the path and records path history; a
  `republish_episode` that creates a collision → `E_PATH_COLLISION`.
- `mark_episode_stale` records the neutral `stale` delta, leaves the path
  unchanged, and the manifest episode row reflects `stale: true`. Born-stale
  declared episode round-trips.
- Edge/error: unknown target → `E_TARGET_UNKNOWN`; non-podcast-episode target
  for a podcast action → `E_HIERARCHY_INVALID`.
- Regression: movie/TV/music topology unchanged (paths, manifest, journal).
- Existing scenarios stay valid at v30; the v29→30 / v9→10 bumps are asserted.

## Deferred follow-ups (filed before merge)

- Podcast seasons (`podcast → season → episode`).
- A second podcast layout / naming recipe.
- Missing-episodes podcast convenience (already expressible via `delete_file`).
- Duplicate-downloads podcast convenience (largely `same_content_as`, #180).
