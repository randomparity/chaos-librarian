# Podcast Library Hierarchy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a podcast library hierarchy (`podcasts → episode`) with datetime publish ordering, a `republish_episode` re-order action, and a `mark_episode_stale` chaos action, without disturbing movie/TV/music topology.

**Architecture:** Mirror the established per-work-type pattern across every layer: a parallel top-level `podcasts` tuple on `Scenario`, a new `ParentKind.PODCAST_EPISODE` threaded through the renderer, topology walker, validation projection, engine state, and manifest. Reuse existing error codes and the hierarchy re-render machinery. Scenario schema v29→30, manifest v9→10.

**Tech Stack:** Python 3.13, Pydantic v2, `uv`, `ruff`, `ty`, `pytest`. Schema source-of-truth is the Pydantic models; `schema_export --write` regenerates `schemas/*.json`.

**Reference docs:** spec `docs/superpowers/specs/2026-05-30-issue-116-podcast-hierarchy-design.md`; ADR `docs/adr/0009-podcast-hierarchy.md`; conventions in `AGENTS.md` ("Project-specific conventions").

**Guardrail gate (run before EVERY commit, must be clean):**
```bash
uv run ruff check . && uv run ruff format --check . \
  && uv run ty check src tests \
  && uv run python -m chaos_librarian.schema_export --check \
  && uv run python -m pytest -q --no-cov tests/contract tests/validation
```
(Full `uv run python -m pytest` once at the end of each task group.)

**Convention reminders (from AGENTS.md — violating these fails CI):**
- Enums: `class X(enum.StrEnum):`.
- Every BaseModel: `model_config = ConfigDict(extra="forbid")` (hierarchy models also `frozen=True`).
- `schema_version` is hardcoded `Literal[N]`, never `Literal[CONST]`.
- Negative tests: build a `dict` and call `Model.model_validate(payload)`; never construct invalid models with `# type: ignore`.
- Absolute imports only.
- After editing any `contract/` model: `schema_export --write` and commit the artifact in the same change.

---

## Task 1: Scenario contract — podcast models and enums

**Files:**
- Modify: `src/chaos_librarian/contract/domain.py` (add `ParentKind.PODCAST_EPISODE`)
- Modify: `src/chaos_librarian/contract/scenario.py` (enums + models + `Scenario.podcasts`, version bump)
- Modify: `src/chaos_librarian/contract/__init__.py:16` (`SCENARIO_SCHEMA_VERSION` 29→30)
- Test: `tests/contract/test_scenario.py`

- [ ] **Step 1: Write failing tests for the new podcast models**

Add to `tests/contract/test_scenario.py`:

```python
def test_podcast_episode_requires_utc_published_at_passes_with_z():
    from datetime import datetime, timezone
    from chaos_librarian.contract.scenario import PodcastEpisode, Variant

    # Reuse an existing helper that builds a minimal Variant; if the test
    # module has `_variant()` use it, else build inline like other tests.
    ep = PodcastEpisode.model_validate(
        {
            "id": "pe1",
            "title": "Pilot",
            "published_at": "2026-05-01T00:00:00Z",
            "slug": "pilot",
            "variants": [_minimal_variant_payload()],
        }
    )
    assert ep.published_at == datetime(2026, 5, 1, tzinfo=timezone.utc)
    assert ep.stale is False


def test_podcast_episode_published_at_naive_rejected():
    import pytest
    from pydantic import ValidationError
    from chaos_librarian.contract.scenario import PodcastEpisode

    with pytest.raises(ValidationError):
        PodcastEpisode.model_validate(
            {
                "id": "pe1",
                "title": "Pilot",
                "published_at": "2026-05-01T00:00:00",  # naive, no offset
                "slug": "pilot",
                "variants": [_minimal_variant_payload()],
            }
        )
```

Add a module-level `_minimal_variant_payload()` helper near the top of the test file if one does not already exist, matching the existing `Variant`/`Bundle`/`Asset` shape used elsewhere in `test_scenario.py` (copy from an existing movie-variant test in that file).

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/contract/test_scenario.py -k podcast -q --no-cov`
Expected: FAIL (`PodcastEpisode` not importable).

- [ ] **Step 3: Add `ParentKind.PODCAST_EPISODE`**

In `src/chaos_librarian/contract/domain.py`:

```python
class ParentKind(enum.StrEnum):
    """Playable/listenable parent kinds for variants and assets."""

    MOVIE = "movie"
    EPISODE = "episode"
    TRACK = "track"
    PODCAST_EPISODE = "podcast_episode"
```

- [ ] **Step 4: Add podcast enums and models in `scenario.py`**

Add `from datetime import datetime` to the existing `datetime` import line (it currently imports `date`). After the `Artist` model block (around line 634) add:

```python
class PodcastLayout(enum.StrEnum):
    PODCAST_FOLDER = "podcast_folder"


class PodcastEpisodeNaming(enum.StrEnum):
    DATE_SLUG_TITLE = "date_slug_title"


class PodcastEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    published_at: datetime
    slug: str = Field(min_length=1)
    stale: bool = False
    variants: tuple[Variant, ...]

    @model_validator(mode="after")
    def _require_utc(self) -> PodcastEpisode:
        offset = self.published_at.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("published_at must be a UTC datetime (Z / +00:00)")
        return self


class Podcast(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    layout: PodcastLayout
    episode_naming: PodcastEpisodeNaming
    episodes: tuple[PodcastEpisode, ...]
```

- [ ] **Step 5: Add `podcasts` to `Scenario` and bump the version literal**

In `Scenario` (around line 1109): change `schema_version: Literal[29]` to `schema_version: Literal[30]` and add after `artists: tuple[Artist, ...]`:

```python
    podcasts: tuple[Podcast, ...] = Field(default_factory=tuple)
```

In `src/chaos_librarian/contract/__init__.py:16`: `SCENARIO_SCHEMA_VERSION: Final = 30`.

- [ ] **Step 6: Re-pin scenario fixtures and recipes (29 → 30) in the SAME commit**

The version bump invalidates every fixture pinned at 29 — including the ones
`tests/contract/test_sample_scenarios.py` globs and loads. To keep the guardrail
gate green at this commit, re-pin in the same change:

```bash
grep -rl "schema_version: 29" tests/fixtures recipes \
  | xargs sed -i '' 's/schema_version: 29/schema_version: 30/'
```
(macOS `sed -i ''`.) The new podcast scenario fixtures land in Task 8; only the
re-pin happens here.

- [ ] **Step 7: Regenerate the scenario schema artifact**

Run: `uv run python -m chaos_librarian.schema_export --write`
(`scenario.schema.json` changes — the manifest artifact regenerates in Task 4.)

- [ ] **Step 8: Run the guardrail gate (now green)**

Run: `uv run python -m pytest tests/contract tests/validation -q --no-cov` plus
`uv run python -m chaos_librarian.schema_export --check`.
Expected: PASS — fixtures re-pinned, scenario schema regenerated. (Manifest is
still v9 here; that bumps in Task 4. Full suite runs at the end of Task 4.)

- [ ] **Step 9: Commit**

```bash
git add src/chaos_librarian/contract/domain.py src/chaos_librarian/contract/scenario.py \
        src/chaos_librarian/contract/__init__.py tests/contract/test_scenario.py \
        schemas/scenario.schema.json tests/fixtures recipes
git commit -m "feat: add podcast scenario models and PODCAST_EPISODE kind"
```
(Commit body trailer: `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>`.)

---

## Task 2: Path rendering — PODCAST_EPISODE branch

**Files:**
- Modify: `src/chaos_librarian/path_rendering.py`
- Test: `tests/test_path_rendering.py` (match the existing path-rendering test module name; if it differs, use the module that tests `render_asset_path`)

- [ ] **Step 1: Write the failing render test**

Add to the path-rendering test module:

```python
def test_render_podcast_episode_path():
    from datetime import datetime, timezone
    from chaos_librarian.contract.domain import ParentKind
    from chaos_librarian.contract.scenario import PodcastLayout, PodcastEpisodeNaming
    from chaos_librarian.path_rendering import RenderableAssetContext, render_asset_path

    ctx = RenderableAssetContext(
        parent_kind=ParentKind.PODCAST_EPISODE,
        root_path="library/podcasts",
        layout=PodcastLayout.PODCAST_FOLDER,
        naming=PodcastEpisodeNaming.DATE_SLUG_TITLE,
        podcast_title="The Daily",
        published_at=datetime(2026, 5, 1, 9, 30, tzinfo=timezone.utc),
        episode_slug="ep-001",
        episode_title="First Show",
        variant_label="default",
        asset_role="primary",
        asset_container="mp3",
        bundle_asset_count=1,
    )
    assert render_asset_path(ctx) == (
        "library/podcasts/The Daily/2026-05-01 - ep-001 - First Show - default.mp3"
    )
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest <path-rendering test module> -k podcast -q --no-cov`
Expected: FAIL (`RenderableAssetContext` has no `podcast_title`).

- [ ] **Step 3: Extend `RenderableAssetContext`**

In `src/chaos_librarian/path_rendering.py`: add `from datetime import datetime` to the `datetime` import. In `RenderableAssetContext` (after `track_title`), add three optional fields (kw_only defaults, before the required tail):

```python
    podcast_title: str | None = None
    published_at: datetime | None = None
    episode_slug: str | None = None
```

Add `PodcastLayout` / `PodcastEpisodeNaming` to the `scenario` import. Widen the `layout` annotation to `MovieLayout | SeriesLayout | ArtistLayout | PodcastLayout` and `naming` to `EpisodeNaming | TrackNaming | PodcastEpisodeNaming | None`.

- [ ] **Step 4: Add the render branch**

In `render_asset_path`, add before the `else` clause:

```python
    elif ctx.parent_kind is ParentKind.PODCAST_EPISODE:
        parts = _podcast_parts(root, ctx)
```

Add the helpers:

```python
def _podcast_parts(root: str, ctx: RenderableAssetContext) -> tuple[str, ...]:
    if not isinstance(ctx.layout, PodcastLayout):
        raise ValueError("podcast context requires PodcastLayout")
    podcast = clean_display_component(_required(ctx.podcast_title, "podcast_title"))
    stem = _podcast_stem(ctx)
    filename = _filename(stem, ctx)
    if ctx.layout is PodcastLayout.PODCAST_FOLDER:
        return (root, podcast, filename)
    raise ValueError(f"unsupported podcast layout: {ctx.layout}")


def _podcast_stem(ctx: RenderableAssetContext) -> str:
    title = clean_display_component(_required(ctx.episode_title, "episode_title"))
    slug = clean_display_component(_required(ctx.episode_slug, "episode_slug"))
    published_at = _required(ctx.published_at, "published_at")
    if ctx.naming is PodcastEpisodeNaming.DATE_SLUG_TITLE:
        date_str = published_at.astimezone(timezone.utc).date().isoformat()
        return f"{date_str} - {slug} - {title}"
    raise ValueError("podcast context requires PodcastEpisodeNaming")
```

Add `from datetime import datetime, timezone` (timezone needed for `astimezone`). `episode_title` already exists as a field; reuse it for the episode title.

- [ ] **Step 5: Run to verify pass + full path-rendering module**

Run: `uv run python -m pytest <path-rendering test module> -q --no-cov`
Expected: PASS (existing movie/TV/music render tests still pass — no existing branch changed).

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/path_rendering.py <path-rendering test module>
git commit -m "feat: render podcast episode media paths"
```

---

## Task 3: Topology walker — podcast asset contexts

**Files:**
- Modify: `src/chaos_librarian/topology.py`
- Test: `tests/test_topology.py` (or the module testing `iter_asset_contexts`)

- [ ] **Step 1: Write the failing walker test**

```python
def test_iter_asset_contexts_includes_podcast_episodes():
    from chaos_librarian.contract.domain import ParentKind
    from chaos_librarian.topology import iter_asset_contexts
    scenario = _scenario_with_one_podcast()  # build via Scenario.model_validate
    kinds = {c.parent_kind for c in iter_asset_contexts(scenario)}
    assert ParentKind.PODCAST_EPISODE in kinds
```

Build `_scenario_with_one_podcast()` as a helper that constructs a minimal valid `Scenario` (one podcast, one episode, one variant/bundle/asset) via `Scenario.model_validate`, reusing the library/root shape from existing topology tests.

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/test_topology.py -k podcast -q --no-cov`
Expected: FAIL (no podcast contexts yielded).

- [ ] **Step 3: Extend `AssetContext` and the walker**

In `src/chaos_librarian/topology.py`: import `Podcast, PodcastEpisode` from `scenario`. Add to the `AssetContext` dataclass (after `track`):

```python
    podcast: Podcast | None
    podcast_episode: PodcastEpisode | None
```

Add these to `_asset_context(...)` signature (kw default `None`) and the constructor call. Add a `"podcast"`/`"podcast_episode"` entry to `_TARGET_GETTERS`. Add the walker and wire it into `iter_asset_contexts`:

```python
def _podcast_episode_asset_contexts(scenario: Scenario) -> Iterator[AssetContext]:
    for podcast in scenario.podcasts:
        for episode in podcast.episodes:
            for variant in episode.variants:
                bundle = variant.bundle
                for asset in bundle.assets:
                    yield _asset_context(
                        parent_kind=ParentKind.PODCAST_EPISODE,
                        parent_id=episode.id,
                        podcast=podcast,
                        podcast_episode=episode,
                        variant=variant,
                        bundle=bundle,
                        asset=asset,
                    )
```

Append `yield from _podcast_episode_asset_contexts(scenario)` in `iter_asset_contexts`.

- [ ] **Step 4: Extend `renderable_asset_context` and `_layout_for_context`**

In `renderable_asset_context`, add the three podcast fields to the `RenderableAssetContext(...)` call:

```python
        podcast_title=context.podcast.title if context.podcast is not None else None,
        published_at=(
            context.podcast_episode.published_at
            if context.podcast_episode is not None
            else None
        ),
        episode_slug=(
            context.podcast_episode.slug if context.podcast_episode is not None else None
        ),
```

The episode title path field is `episode_title`; set it from `podcast_episode.title` when `podcast_episode is not None` (extend the existing `episode_title=` expression to fall back to the podcast episode).

In `_layout_for_context`, add before the `raise`:

```python
    if context.podcast is not None:
        return context.podcast.layout
```

Widen its return type to include `PodcastLayout`. In `_naming_for_context`, add:

```python
    if context.podcast is not None:
        return context.podcast.episode_naming
```

and widen the return type. Import `PodcastLayout`, `PodcastEpisodeNaming`.

- [ ] **Step 5: Run to verify pass**

Run: `uv run python -m pytest tests/test_topology.py -q --no-cov`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/topology.py tests/test_topology.py
git commit -m "feat: walk podcast episode asset contexts"
```

---

## Task 4: Engine state — seed podcast initial locations and manifest rows

**Files:**
- Modify: `src/chaos_librarian/contract/manifest.py` (`ManifestPodcast`, `ManifestPodcastEpisode`, `Manifest` lists, version bump)
- Modify: `src/chaos_librarian/contract/__init__.py:17` (`MANIFEST_SCHEMA_VERSION` 9→10)
- Modify: `src/chaos_librarian/engine/state.py` (seed podcast rows + locations, helpers)
- Test: `tests/contract/test_manifest.py`, `tests/engine/test_state.py` (match existing engine test module)

- [ ] **Step 1: Write failing manifest model test**

Add to `tests/contract/test_manifest.py`:

```python
def test_manifest_carries_podcast_rows():
    from chaos_librarian.contract.manifest import Manifest
    payload = _empty_manifest_payload()  # existing helper or build minimal v10 dict
    payload["schema_version"] = 10
    payload["podcasts"] = [
        {"id": "p1", "title": "The Daily", "layout": "podcast_folder",
         "episode_naming": "date_slug_title"}
    ]
    payload["podcast_episodes"] = [
        {"id": "pe1", "podcast_id": "p1", "title": "Pilot",
         "published_at": "2026-05-01T00:00:00Z", "slug": "pilot", "stale": False}
    ]
    m = Manifest.model_validate(payload)
    assert m.podcasts[0].id == "p1"
    assert m.podcast_episodes[0].stale is False
```

If no `_empty_manifest_payload()` exists, build the minimal v10 dict inline with every required top-level list (`movies`, `series`, `seasons`, `episodes`, `artists`, `albums`, `discs`, `tracks`, `podcasts`, `podcast_episodes`, `variants`, `bundles`, `assets`, `versions`, `locations`) — copy from an existing manifest test.

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/contract/test_manifest.py -k podcast -q --no-cov`
Expected: FAIL.

- [ ] **Step 3: Add manifest models and bump version**

In `src/chaos_librarian/contract/manifest.py`, after `ManifestTrack`:

```python
class ManifestPodcast(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    layout: str
    episode_naming: str


class ManifestPodcastEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    podcast_id: str
    title: str
    published_at: datetime
    slug: str
    stale: bool = False
```

Add `from datetime import datetime` if not present (file already imports `date`). In `Manifest`: bump `schema_version: Literal[9]` → `Literal[10]`, and add after `tracks`:

```python
    podcasts: list[ManifestPodcast] = Field(default_factory=list)
    podcast_episodes: list[ManifestPodcastEpisode] = Field(default_factory=list)
```

In `src/chaos_librarian/contract/__init__.py:17`: `MANIFEST_SCHEMA_VERSION: Final = 10`.

- [ ] **Step 4: Write failing engine seeding test**

Add to the engine state test module:

```python
def test_initial_state_seeds_podcast_episode_location_and_rows():
    from chaos_librarian.engine.state import build_initial_state
    from chaos_librarian.determinism.ids import IdAllocator
    from chaos_librarian.determinism.trace import TraceRecorder
    scenario = _scenario_with_one_podcast()  # one podcast/episode/asset
    manifest = build_initial_state(scenario, IdAllocator(TraceRecorder())).to_manifest()
    assert manifest.podcasts[0].id == "p1"
    assert manifest.podcast_episodes[0].id == "pe1"
    # the asset has a rendered location under the podcast folder
    assert any("/The Daily/" in loc.path for loc in manifest.locations)
```

The real signature is `build_initial_state(scenario, ids)` (`state.py:376`) and
the manifest accessor is `.to_manifest()` (`state.py:355`); copy the exact
`IdAllocator(TraceRecorder())` construction from existing engine tests (e.g.
`tests/engine/test_events_filesystem.py:214`) — adjust the import paths to match
that file's imports if they differ from the names above.

- [ ] **Step 5: Run to verify failure**

Run: `uv run python -m pytest <engine state module> -k podcast -q --no-cov`
Expected: FAIL.

- [ ] **Step 6: Seed podcast rows + variant/bundle/locations in `engine/state.py`**

Add `ManifestPodcast`, `ManifestPodcastEpisode` to the manifest imports. Add `podcasts`/`podcast_episodes` dicts to `WorldState` (mirroring `series`/`seasons`). In the initial-state seeding (the function that walks `scenario.series`/`scenario.artists`, around line 412+), add a podcast walk that:
- records `ManifestPodcast(id, title, layout=podcast.layout.value, episode_naming=podcast.episode_naming.value)`,
- records `ManifestPodcastEpisode(id, podcast_id, title, published_at, slug, stale)`,
- calls `_seed_variant_bundle_rows(state, variant, ParentKind.PODCAST_EPISODE, episode.id)` for each variant.

Add `state.podcasts` / `state.podcast_episodes` to the `Manifest(` construction at line 357 (`podcasts=list(state.podcasts.values())`, `podcast_episodes=list(state.podcast_episodes.values())`). Add a `asset_ids_for_podcast_episode` helper mirroring `asset_ids_for_episode` (uses `_asset_ids_for_parent(ParentKind.PODCAST_EPISODE, episode_id)`). The initial-location seeding (around line 533) uses `render_asset_path(renderable_asset_context(context, primary_root_path))`, which handles podcast contexts after Task 3 — the walk just needs to feed the contexts in.

**Critical — add the `PODCAST_EPISODE` branch to `WorldState.renderable_context_for_asset` (`state.py:255-319`).** This method, NOT `_hierarchy_entry`, is where per-`parent_kind` rendering branches live (it branches `MOVIE`/`EPISODE`/`TRACK`). `render_path_for_asset` (`state.py:241`) and `_hierarchy_entry`'s re-render both delegate here, so without a podcast branch every podcast path render raises. Mirror the `EPISODE`/`TRACK` branches:

```python
        if variant.parent_kind is ParentKind.PODCAST_EPISODE:
            episode = self.podcast_episodes[variant.parent_id]
            podcast = self.podcasts[episode.podcast_id]
            return RenderableAssetContext(
                parent_kind=ParentKind.PODCAST_EPISODE,
                root_path=root_path,
                layout=PodcastLayout(podcast.layout),
                naming=PodcastEpisodeNaming(podcast.episode_naming),
                podcast_title=podcast.title,
                published_at=episode.published_at,
                episode_slug=episode.slug,
                episode_title=episode.title,
                variant_label=variant.label,
                asset_role=asset.role,
                asset_container=asset.container,
                bundle_asset_count=bundle_asset_count,
            )
```

(The movie/TV/music fields default to `None` via `RenderableAssetContext`'s kw_only defaults, so they need not be spelled out — but match the existing branches' explicit-`None` style if the file's convention requires it; `ty` will flag any missing required field.) Import `PodcastLayout`, `PodcastEpisodeNaming`. Note `ManifestPodcastEpisode.podcast_id` makes the episode→podcast lookup direct.

- [ ] **Step 7: Run engine + manifest tests**

Run: `uv run python -m pytest tests/contract/test_manifest.py <engine state module> -k podcast -q --no-cov`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/contract/manifest.py src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/engine/state.py tests/contract/test_manifest.py <engine state test>
git commit -m "feat: seed podcast manifest rows and initial locations"
```

---

## Task 5: Timeline actions — republish_episode and mark_episode_stale (contract)

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py` (enum members, event variants, union, `HIERARCHY_TIMELINE_ACTIONS`)
- Test: `tests/contract/test_scenario.py`

- [ ] **Step 1: Write failing event-variant tests**

```python
def test_republish_episode_event_roundtrips():
    from chaos_librarian.contract.scenario import TimelineEvent
    from pydantic import TypeAdapter
    ev = TypeAdapter(TimelineEvent).validate_python(
        {"id": "t1", "at": "PT1H", "action": "republish_episode",
         "target": "pe1", "published_at": "2026-06-01T00:00:00Z", "slug": "new-slug"}
    )
    assert ev.action == "republish_episode"


def test_mark_episode_stale_event_roundtrips():
    from chaos_librarian.contract.scenario import TimelineEvent
    from pydantic import TypeAdapter
    ev = TypeAdapter(TimelineEvent).validate_python(
        {"id": "t2", "at": "PT2H", "action": "mark_episode_stale", "target": "pe1"}
    )
    assert ev.action == "mark_episode_stale"
```

Use the `at` duration format the existing timeline tests use (copy an existing timeline-event test's `at` value).

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest tests/contract/test_scenario.py -k "republish or mark_episode" -q --no-cov`
Expected: FAIL (unknown action discriminator).

- [ ] **Step 3: Add enum members**

In `TimelineActionName` (after `SWAP_TRACK_NUMBERS`):

```python
    REPUBLISH_EPISODE = "republish_episode"
    MARK_EPISODE_STALE = "mark_episode_stale"
```

Add `TimelineActionName.REPUBLISH_EPISODE` to the `HIERARCHY_TIMELINE_ACTIONS` frozenset. Do NOT add `MARK_EPISODE_STALE` (it is not a path mutation).

- [ ] **Step 4: Add event variants and extend the union**

After `SwapTrackNumbersEvent` (around line 988):

```python
class RepublishEpisodeEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.REPUBLISH_EPISODE] = TimelineActionName.REPUBLISH_EPISODE
    target: str
    published_at: datetime
    slug: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _require_utc(self) -> RepublishEpisodeEvent:
        offset = self.published_at.utcoffset()
        if offset is None or offset.total_seconds() != 0:
            raise ValueError("published_at must be a UTC datetime (Z / +00:00)")
        return self


class MarkEpisodeStaleEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.MARK_EPISODE_STALE] = TimelineActionName.MARK_EPISODE_STALE
    target: str
```

Add both to the `TimelineEvent` union (before the closing `Field(discriminator="action")`).

- [ ] **Step 5: Run to verify pass**

Run: `uv run python -m pytest tests/contract/test_scenario.py -k "republish or mark_episode" -q --no-cov`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/contract/scenario.py tests/contract/test_scenario.py
git commit -m "feat: add republish_episode and mark_episode_stale events"
```

---

## Task 6: Validation projection + rules

**Files:**
- Modify: `src/chaos_librarian/validation/rules/_common.py` (projection podcast state + render branch + apply + namespaces + `entity_ids_by_kind`)
- Modify: `src/chaos_librarian/validation/rules/hierarchy.py` (`_check_podcasts`; map non-episode target → `E_HIERARCHY_INVALID`)
- Modify: `src/chaos_librarian/validation/rules/target_unknown.py` (`_HIERARCHY_TARGET_KIND_BY_ACTION` entries)
- Test: `tests/validation/test_*` + invalid fixtures (Task 8)

- [ ] **Step 1: Write failing validation tests**

Add to the validation rules test module (match the module that exercises `validate_scenario`/the pipeline on dicts):

```python
def test_republish_collision_reports_path_collision():
    report = _validate(_podcast_scenario_with_republish_collision())
    assert "E_PATH_COLLISION" in {i.code for i in report.issues}


def test_podcast_action_on_tv_episode_target_unknown():
    report = _validate(_scenario_republish_targeting_tv_episode())
    assert "E_TARGET_UNKNOWN" in {i.code for i in report.issues}


def test_mark_episode_stale_after_delete_lifecycle_invalid():
    report = _validate(_scenario_stale_after_full_delete())
    assert "E_LIFECYCLE_INVALID" in {i.code for i in report.issues}
```

Build the `_*` scenario helpers as raw dicts (or `Scenario` dumped to dict) per the negative-test convention.

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest <validation rules test module> -k "podcast or republish or stale" -q --no-cov`
Expected: FAIL.

- [ ] **Step 3: Add podcast namespaces + entity-id walk in `_common.py`**

Add `NS_PODCAST_ID = "podcast_id"` and `NS_PODCAST_EPISODE_ID = "podcast_episode_id"` `Final` constants (and to `__all__`). Add a `_iter_podcast_entity_ids(raw)` walker (mirror `_iter_artist_entity_ids`) yielding the podcast id and each episode id with their `_Loc`, and append `yield from _iter_podcast_entity_ids(raw)` in `iter_entity_ids`. Add `"podcast"` and `"podcast_episode"` keys (empty sets) to the `entity_ids_by_kind` dict. Add a `_iter_podcast_episode_asset_contexts(raw)` raw walker (mirror `_iter_track_asset_contexts`) and append it in `iter_asset_contexts`. Extend `RawAssetContext` with `podcast`/`podcast_loc`/`podcast_episode`/`podcast_episode_loc` and set them in the new walker. Extend `renderable_context_for` with a `PODCAST_EPISODE` branch building a `RenderableAssetContext` from the raw podcast/episode fields (mirror `_track_renderable_context`).

- [ ] **Step 4: Add projection state + apply + render branch in `_common.py`**

Add `_PodcastState`/`_PodcastEpisodeState` dataclasses (episode carries `id`, `podcast_id`, `published_at`, `slug`, `title`, `stale`, `asset_ids`). Add `self.podcasts`/`self.podcast_episodes` dicts to `HierarchyProjection.__init__` and a `_seed_podcasts(raw)` call. In `_seed_assets`, attach asset ids to podcast episodes (add `elif context.parent_id in self.podcast_episodes:`). Add `render_asset_path` PODCAST_EPISODE branch (`if tail.parent_id in self.podcast_episodes: return self._render_podcast_asset(...)`) building the renderer context from projection state. In `apply`, add:

```python
        elif action == TimelineActionName.REPUBLISH_EPISODE:
            self._apply_republish_episode(event)  # returns nothing path-structural;
            # path re-render handled by _refresh_paths via affected asset ids
```

Add `_apply_republish_episode` (set `published_at`, `slug` if present, clear `stale`) and extend `affected_asset_ids`/`_single_target_affected_asset_ids` so `REPUBLISH_EPISODE` returns the episode's asset ids. `MARK_EPISODE_STALE` is not a hierarchy action, so the projection's `apply` is never called for it; the lifecycle rule handles staleness directly (Step 6).

- [ ] **Step 5: Add `_check_podcasts` to `hierarchy.py`**

In `rule_hierarchy_invariants`, call a new `_check_podcasts(raw, reporter)` that walks `raw["podcasts"]` and, for each episode, attempts the slug/title render and reports `E_HIERARCHY_INVALID` if a component cannot render (mirror `_check_episode_naming`'s structure). Duplicate `published_at` is allowed — do not report it. In `rule_hierarchy_timeline`/`rule_media_action_compatible_with_parent` add a guard: a `republish_episode`/`mark_episode_stale` whose target resolves to a non-podcast-episode entity reports `E_HIERARCHY_INVALID` (mirror the swap not-same-kind handling). Rendered-path collisions are already caught by the existing `rule_rendered_path_collisions` (initial) and `_check_hierarchy_path_collisions` (post-republish) since the projection now renders podcast paths.

- [ ] **Step 6: Lifecycle rule for mark_episode_stale**

In `src/chaos_librarian/validation/rules/timeline_lifecycle.py`, add handling for `mark_episode_stale`: track per-episode stale state and live-location state; emit `E_LIFECYCLE_INVALID` when (a) the targeted episode has no live location remaining (all assets deleted), or (b) the episode is already stale. Use the existing per-asset deleted-tracking the rule already maintains to determine "no live location."

- [ ] **Step 7: Add target-kind mapping**

In `target_unknown.py`, add to `_HIERARCHY_TARGET_KIND_BY_ACTION`:

```python
    TimelineActionName.REPUBLISH_EPISODE: "podcast_episode",
    TimelineActionName.MARK_EPISODE_STALE: "podcast_episode",
```

- [ ] **Step 8: Run validation tests**

Run: `uv run python -m pytest <validation rules test module> -k "podcast or republish or stale" tests/validation -q --no-cov`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/chaos_librarian/validation/ <validation tests>
git commit -m "feat: validate podcast hierarchy and timeline actions"
```

---

## Task 7: Engine handlers — republish_episode and mark_episode_stale

**Files:**
- Modify: `src/chaos_librarian/engine/state.py` (`asset_ids_for_podcast_episode` if not added in Task 4; `podcast_episodes` accessor)
- Modify: `src/chaos_librarian/engine/events.py` (two handlers + dispatch entries)
- Test: engine events test module

- [ ] **Step 1: Write failing handler tests**

```python
def test_republish_episode_rerenders_path_and_clears_stale():
    journal, manifest = _run_engine(_scenario_with_podcast_and_republish())
    ep = next(e for e in manifest.podcast_episodes if e.id == "pe1")
    assert ep.stale is False
    assert any("2026-06-01" in loc.path for loc in manifest.locations)


def test_mark_episode_stale_records_neutral_delta_and_keeps_path():
    journal, manifest = _run_engine(_scenario_with_podcast_and_mark_stale())
    ep = next(e for e in manifest.podcast_episodes if e.id == "pe1")
    assert ep.stale is True
    stale_entries = [e for e in journal if getattr(e, "action", None) == "mark_episode_stale"]
    assert stale_entries and stale_entries[0].state_delta.get("stale") is True
```

Use the existing "run engine → (journal, manifest)" helper the other engine tests use.

- [ ] **Step 2: Run to verify failure**

Run: `uv run python -m pytest <engine events module> -k "republish or stale" -q --no-cov`
Expected: FAIL (no handler registered → unhandled action raises).

- [ ] **Step 3: Add handlers in `events.py`**

Mirror `_handle_renumber_episode` for republish:

```python
def _handle_republish_episode(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, RepublishEpisodeEvent)
    asset_ids = state.asset_ids_for_podcast_episode(event.target)
    previous = state.podcast_episodes[event.target]
    before = _capture_rendered_paths(state, asset_ids)
    updates: dict[str, object] = {"published_at": event.published_at, "stale": False}
    if event.slug is not None:
        updates["slug"] = event.slug
    state.podcast_episodes[event.target] = previous.model_copy(update=updates)
    metadata = _metadata_delta(previous, state.podcast_episodes[event.target], tuple(updates))
    return (
        _hierarchy_entry(
            state=state,
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.REPUBLISH_EPISODE,
            hierarchy_target_id=event.target,
            asset_ids=asset_ids,
            before_paths=before,
            metadata=metadata,
        ),
    )
```

Mark-stale handler (atomic entry, path unchanged):

```python
def _handle_mark_episode_stale(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    ctx: EngineEventContext,
) -> tuple[JournalEntry, ...]:
    del ids
    event = _checked_event(resolved, MarkEpisodeStaleEvent)
    asset_ids = state.asset_ids_for_podcast_episode(event.target)
    previous = state.podcast_episodes[event.target]
    state.podcast_episodes[event.target] = previous.model_copy(update={"stale": True})
    paths = [state.locations[state.location_id_for_asset(a)].path for a in asset_ids]
    return (
        _new_atomic_entry(
            resolved=resolved,
            ctx=ctx,
            action=TimelineActionName.MARK_EPISODE_STALE,
            target_ids=[event.target],
            location_ids=[state.location_id_for_asset(a) for a in asset_ids],
            state_delta={"stale": True, "paths": paths},
        ),
    )
```

`_hierarchy_entry` needs **no change**: it does not branch on entity kind — it calls `state.render_path_for_asset(asset_id)`, which delegates to `WorldState.renderable_context_for_asset`. The `PODCAST_EPISODE` branch added there in Task 4 already makes podcast path re-render work, so `republish_episode`'s `_hierarchy_entry` call renders correctly. Just import `RepublishEpisodeEvent`, `MarkEpisodeStaleEvent` and register both handlers in the dispatch table. (If Task 4's `renderable_context_for_asset` branch was somehow missed, `republish_episode` raises here — add it in `state.py:255-319`, not in `_hierarchy_entry`.)

- [ ] **Step 4: Run handler tests**

Run: `uv run python -m pytest <engine events module> -k "republish or stale" -q --no-cov`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/engine/ <engine tests>
git commit -m "feat: engine handlers for republish_episode and mark_episode_stale"
```

---

## Task 8: New podcast fixtures + manifest re-pin

> Scenario fixtures/recipes were already re-pinned 29→30 and
> `scenario.schema.json` regenerated in Task 1; the manifest artifact and
> manifest version constant were bumped in Task 4. This task adds the podcast
> fixtures and fixes any remaining manifest-v9 test data.

**Files:**
- Regenerate: `schemas/manifest.schema.json` and any report schema embedding the manifest (if not already current from Task 4)
- Modify: manifest test data still constructing v9 manifests (`9` → `10`)
- Create: `tests/fixtures/scenarios/podcast_basic.yaml` (valid) + invalid fixtures

- [ ] **Step 1: Confirm schema artifacts are current**

Run: `uv run python -m chaos_librarian.schema_export --write`
Then: `git status --short schemas/` (manifest + report schemas should already be
current from Task 4; this is a no-op guard. If anything changes, Task 4 missed a
regen — stage it here.)

- [ ] **Step 2: Re-pin remaining manifest test data (9 → 10)**

Manifest fixtures are not in the scenario corpus; they live in test data that
constructs full manifests. Search `tests` for literal `schema_version=9` and
`"schema_version": 9`, and fix the ones that are **manifests** (not other
contracts — `journal`, `replay-bundle`, etc. keep their own versions):

```bash
grep -rln "schema_version.*9" tests/contract/test_manifest.py tests/contract/test_reports.py \
  tests/contract/test_replay_bundle.py tests/contract/test_run_sentinel.py \
  tests/contract/test_capabilities.py
```
Bump only the manifest `schema_version` to 10 in each (the v9→10 covered in
Task 4 for `test_manifest.py`; the others embed a manifest and need the same
bump).

- [ ] **Step 3: Add the valid podcast fixture**

Create `tests/fixtures/scenarios/podcast_basic.yaml` — a complete scenario at `schema_version: 30` with one library root, one podcast (one episode, one variant/bundle/asset), and a timeline exercising `republish_episode` then `mark_episode_stale` on a second episode. Model it on an existing TV fixture (`series_*`-style) for the library/variant/bundle/asset shape.

- [ ] **Step 4: Add invalid fixtures with `# expected:` markers**

Create under `tests/fixtures/scenarios/invalid/`:
- `podcast_path_collision.yaml` — first line `# expected: E_PATH_COLLISION`; two episodes, same `published_at`, same `slug`.
- `podcast_republish_unknown_target.yaml` — `# expected: E_TARGET_UNKNOWN`; `republish_episode` targeting a non-existent id.
- `podcast_naive_published_at.yaml` — verify whether the naive datetime is a Pydantic shape error or `E_HIERARCHY_INVALID`; place under invalid corpus only if it surfaces as a validation code (a Pydantic `extra/type` rejection belongs in a `test_scenario.py` unit test instead, already covered in Task 1/5). If the UTC check is the scenario-level `model_validator`, it raises at parse, so cover it as a model unit test, not an invalid-corpus fixture.

- [ ] **Step 5: Run the full suite**

Run: `uv run python -m pytest -q --no-cov`
Expected: PASS (the sample-scenario corpus loads `podcast_basic.yaml`; the invalid corpus asserts the markers).

- [ ] **Step 6: Run the full guardrail gate**

Run the full guardrail gate command from the header (including `schema_export --check`).
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add schemas/ tests/fixtures/ recipes/ tests/
git commit -m "chore: regen schemas and re-pin fixtures for podcast hierarchy"
```

---

## Task 9: Regression + cross-cutting coverage

**Files:**
- Test: a new `tests/test_podcast_regression.py` (or add to an existing topology/regression module)

- [ ] **Step 1: Write the movie/TV/music-unchanged regression test**

```python
def test_existing_topology_paths_unchanged_by_podcast_support():
    # Validate + initial-state a movie/TV/music scenario and assert rendered
    # paths, manifest entity rows, and the journal match a frozen expectation
    # captured from an existing fixture. The new podcast field defaults empty,
    # so a podcast-free scenario must be byte-identical.
    scenario = _load_fixture("series_season_folders.yaml")  # an existing TV fixture
    manifest = build_initial_state(scenario, IdAllocator(TraceRecorder())).to_manifest()
    assert manifest.podcasts == []
    assert manifest.podcast_episodes == []
    # rendered episode path matches the known TV shape
    assert any("/Season 01/" in loc.path for loc in manifest.locations)
```

Use the real `build_initial_state(scenario, ids)` arity (`state.py:376`) with
`IdAllocator(TraceRecorder())`, matching existing engine tests; `_load_fixture`
should load and `Scenario.model_validate` an existing TV fixture name that
actually exists in `tests/fixtures/scenarios/` (verify the filename first).

- [ ] **Step 2: Run to verify pass**

Run: `uv run python -m pytest tests/test_podcast_regression.py -q --no-cov`
Expected: PASS.

- [ ] **Step 3: Add the materialize-topology test (no ffmpeg needed for path assertions)**

Add a test that materializes `podcast_basic.yaml` in plan-only / dry path-assertion mode (mirror how existing materializer unit tests assert rendered relative paths without invoking ffmpeg) and asserts the on-disk relative path equals `<root>/<Podcast>/<date> - <slug> - <title> - <label>.<ext>`.

- [ ] **Step 4: Run full suite + full guardrail gate**

Run: `uv run python -m pytest -q --no-cov` then the full guardrail gate.
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: lock movie/TV/music topology unchanged by podcast support"
```

---

## Self-review checklist (run after implementing)

- Spec coverage: topology (T1,3), datetime UTC ordering + render (T1,2), republish (T5,7), mark_stale + lifecycle (T5,6,7), validation codes + namespaces (T6), manifest v10 (T4), schema regen + re-pin (T8), backward-compat regression (T9). All covered.
- No new error code introduced (T6 reuses E_HIERARCHY_INVALID / E_PATH_COLLISION / E_TARGET_UNKNOWN / E_LIFECYCLE_INVALID).
- `mark_episode_stale` is NOT in `HIERARCHY_TIMELINE_ACTIONS`; `republish_episode` IS.
- `schema_version` literals hardcoded (`Literal[30]`, `Literal[10]`); constants bumped in `__init__.py`.
