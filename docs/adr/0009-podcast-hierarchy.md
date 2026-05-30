# 0009 — Podcast library hierarchy

## Status

Accepted

## Context

The #106 hierarchy redesign shipped movie, TV (series → season → episode), and
music (artist → album → disc → track) topology and deliberately **deferred**
podcasts. Podcasts differ from TV in two ways the #106 design did not want to
force onto the episode model: episodes order by **publish time**, not by
season/episode number; and a podcast has a chaos mode the other types lack — a
*stale download*, where the source feed drops an episode but its downloaded file
lingers in the library.

The established pattern (`scenario.py`, `topology.py`, `path_rendering.py`,
`validation/rules/_common.py`) models each work-type as a **parallel top-level
tuple** (`movies` / `series` / `artists`), each a nested hierarchy ending in
`variants → bundle → assets`, with a per-asset `ParentKind`
(`movie` / `episode` / `track`) threaded through the renderer, engine state,
manifest variants, and the validation projection. Per-axis timeline actions
(`renumber_episode`, `move_*`, `swap_*`) are gated into
`HIERARCHY_TIMELINE_ACTIONS`; TV/music semantics stay scoped by action name and
`ParentKind`. The oracle is policy-neutral (AGENTS): manifests and journals
record facts, never expected outcomes. ADR 0008 set the precedent of reusing
existing error codes unless the contract genuinely differs.

## Decision

1. **Parallel top-level `podcasts` tuple, new `ParentKind`.** Add
   `podcasts: tuple[Podcast, ...]` to `Scenario` and
   `ParentKind.PODCAST_EPISODE`, mirroring `movies` / `series` / `artists`. Two
   levels only: `Podcast → PodcastEpisode`, then `variants → bundle → assets`.
   No seasons in v1.
2. **Datetime publish-time ordering.** `PodcastEpisode.published_at` is a
   required aware RFC3339 `datetime` and the first-class ordering attribute.
   Podcast episodes carry no `episode_number` / `season_number`.
3. **Date + slug + title render into the path.** A single layout
   (`PODCAST_FOLDER`) and naming recipe (`DATE_SLUG_TITLE`) render
   `<root>/<Podcast Title>/<YYYY-MM-DD> - <slug> - <Episode Title> - <label>.<ext>`.
   `published_at` keeps full datetime precision for deterministic ordering, but
   only the **date portion** renders. `slug` is a required uniqueness tiebreaker,
   cleaned through the existing `clean_display_component` sanitizer.
4. **Duplicate `published_at` allowed; rendered path must be unique.** Two
   episodes may share a `published_at`; they MUST carry distinct slugs or the
   rendered paths collide (`E_PATH_COLLISION`). No new validation code.
5. **One re-ordering mutation: `republish_episode`.** It sets `published_at`
   (and optionally `slug`) and re-renders the episode's asset paths, mirroring
   `renumber_episode`. It joins `HIERARCHY_TIMELINE_ACTIONS`, so the path-history
   projection and lifecycle hierarchy branch handle it with no further wiring.
6. **One new chaos capability: `mark_episode_stale`.** It flips the episode's
   recorded `stale` state to true at time `at` and records a neutral journal
   `state_delta` (`{"stale": true, "path": <unchanged path>}`). It does **not**
   move or remove the file, so it is not a hierarchy path mutation and stays out
   of `HIERARCHY_TIMELINE_ACTIONS`. The file lingering on disk while the source
   has dropped the episode is the whole point — distinct from `delete_file`
   (removes from disk) and `archive_file` (relocates on disk).
7. **`stale` field is recorded state; the action is primary.**
   `PodcastEpisode.stale: bool = False` records whether the episode is currently
   absent from the source feed. `mark_episode_stale` is the primary chaos
   mechanism — the transition that sets the same state the field represents, so
   "is this episode stale" has one source of truth. A born-stale declared
   episode is a valid-but-secondary case.
8. **Reuse existing error codes.** `E_HIERARCHY_INVALID` (structural /
   projection, non-episode target), `E_PATH_COLLISION` (rendered clash),
   `E_TARGET_UNKNOWN` (unknown operand). No new code.
9. **Manifest v9 → v10, scenario v29 → v30.** Manifest adds policy-neutral
   `ManifestPodcast` + `ManifestPodcastEpisode` rows (id, title, `published_at`,
   slug, naming, neutral `stale` fact), top-level `podcasts` /
   `podcast_episodes` lists, and `ParentKind.PODCAST_EPISODE` on
   `ManifestVariant`. No judgment/policy fields.

## Consequences

- A new `ParentKind` member, two scenario enums, two scenario models, two
  timeline actions, and two manifest models enter the public contract.
  `republish_episode` joins `HIERARCHY_TIMELINE_ACTIONS`; `mark_episode_stale`
  does not.
- `SCENARIO_SCHEMA_VERSION` 29 → 30 and `MANIFEST_SCHEMA_VERSION` 9 → 10 force a
  re-pin of the ~141 fixture / recipe files and a `schema_export --write`
  regen of `scenario.schema.json` and `manifest.schema.json`.
- Every existing scenario stays valid beyond the mandatory version bumps; a
  scenario with no `podcasts` and no podcast actions is byte-identical to
  pre-change behavior (empty-tuple default, `PODCAST_EPISODE` only appears when a
  podcast is declared). A regression test locks movie/TV/music in.
- The renderer, engine state, validation projection, and manifest each gain one
  podcast branch alongside the existing movie/episode/track branches; no
  existing branch changes.
- Deferred to filed follow-ups: podcast seasons; a second podcast layout/naming
  recipe; missing-episodes and duplicate-downloads podcast conveniences (already
  expressible via `delete_file` and `same_content_as` #180).

## Considered & rejected

**Q1 — Which chaos capability ships in v1.**
- *Rejected: duplicate-downloads.* Already expressible with `same_content_as`
  (#180) — a second asset with identical content under a different filename. A
  podcast-specific action would duplicate existing semantics.
- *Rejected: missing-episodes.* Already expressible with `delete_file` (the file
  is simply absent). No new semantics.
- *Rejected: ship all four.* Multiplies the schema and engine surface for
  capabilities three of which are already covered or trivially expressible.
- **Chosen: stale-download cleanup only.** The one capability with genuinely
  podcast-specific, not-already-covered semantics — the source drops an episode
  while the file lingers in place. A checkpoint confirmed no existing action
  records "source dropped this, file unchanged."

**Q2 — Topology shape.**
- *Rejected: reuse `Series/Season/Episode` with a `kind` flag.* Bleeds podcast
  semantics (publish-time ordering, staleness) into the TV episode model — the
  exact coupling #106 refused.
- *Rejected: `podcast → season → episode`.* No fixture demands podcast seasons;
  speculative (AGENTS Rule 3). Filed as a follow-up.
- **Chosen: parallel top-level `podcasts` tuple, two levels, new
  `ParentKind.PODCAST_EPISODE`,** matching the per-work-type tuple convention and
  keeping podcast semantics isolated.

**Q3 — Time-ordering representation.**
- *Rejected: reuse TV's optional `aired_on` + `DATE_TITLE`.* Couples podcasts to
  the TV episode model and loses sub-day ordering precision.
- *Rejected: a synthetic ordinal alongside `published_at`.* Reintroduces the
  episode-number concept podcasts are meant to avoid.
- **Chosen: required aware RFC3339 `datetime`** as the first-class ordering
  attribute; only the date portion renders, with `slug` as the path tiebreaker.

**Q4 — Whether the topology ships with a mutation.**
- *Rejected: topology only, no mutation.* Would land `PODCAST_EPISODE` without
  exercising it through the projection / journal / oracle path the other kinds
  use, leaving the new branch under-tested end-to-end.
- **Chosen: one `republish_episode` action** mirroring `renumber_episode`, so the
  new kind is exercised through the full timeline machinery.

**Q5 — Uniqueness contract.**
- *Rejected: forbid duplicate `published_at`.* Real feeds publish multiple
  episodes at the same timestamp; forbidding it rejects valid topology.
- **Chosen: allow duplicate `published_at`, require a distinct `slug`** so
  rendered paths stay unique; a clash is the existing `E_PATH_COLLISION`.

**Q6 — Oracle / manifest shape.**
- *Rejected: a policy field (e.g. "should_delete").* Violates the neutral-oracle
  contract — chaos-librarian does not know the consumer's expected outcome.
- **Chosen: neutral entity rows + a neutral `stale` fact,** mirroring the
  declared/projected state, consistent with the #179 precedent.

**Stale representation — new action vs. existing actions.**
- *Rejected: model stale with `delete_file`.* Removes the file from disk; stale
  cleanup is precisely the file *lingering*.
- *Rejected: model stale with `archive_file`.* Relocates the file; stale cleanup
  leaves it in place.
- **Chosen: `mark_episode_stale`,** which records a neutral feed-vs-library
  staleness fact while leaving the file untouched — semantics no existing action
  carries.
