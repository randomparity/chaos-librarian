# Issue 106 Media Hierarchies Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the pre-release `works -> variants -> bundle -> assets`
contract with first-class movie, TV, and music hierarchies across schema,
validation, plan/materialize output, adapter comparison, generation, and docs.

**Architecture:** Treat this as a breaking contract replacement, not a
compatibility migration. Add one shared typed topology walker and one shared
layout/path renderer first, then migrate each subsystem to those helpers so
scenario validation, plan-only state, materialize phase A, and hierarchy
timeline actions render identical paths. Keep `Variant`, `Bundle`, and `Asset`
as the reusable delivery tail under explicit `movie`, `episode`, and `track`
leaf branches; do not introduce a replacement `Work` abstraction.

**Tech Stack:** Python 3.13, Pydantic v2, Typer, ruamel.yaml, pytest,
Hypothesis, ruff, ty, FFmpeg/ffprobe materializer, checked-in JSON Schema
artifacts.

---

## Source Spec

Implement the approved design in
`docs/superpowers/specs/2026-05-26-issue-106-media-hierarchies-design.md`.

Target implementation branch from the spec:
`feat/issue-106-media-hierarchies`.

The repository is currently on `feat/fuzz-generation-suite` at planning time.
Before implementation, switch to or create the target branch/worktree. Do not
start code work for this issue on the current branch.

## Scope Check

This issue spans multiple independently testable subsystems:

- Public scenario, manifest, report, observed-state, replay, and schema export
  contracts.
- Shared topology walking and layout rendering.
- Semantic validation and lifecycle simulation.
- Plan-only engine state, reports, path history, and hierarchy event handlers.
- Materialize support for audio-only assets and hierarchy path moves.
- Adapter fixture loading, observed-state validation, matching, and comparison.
- Fuzz generation, sample fixtures, and public docs.

Do not implement this as one large PR. Use this parent plan to write and execute
the child plans below in order. Each child plan should be saved under
`docs/superpowers/plans/2026-05-26-issue-106-<slice>.md` and must expand the
steps into full TDD tasks before code is touched.

Recommended child implementation plans:

1. `issue-106-contract-renderer`: contracts, schema constants, topology walker,
   and path renderer.
2. `issue-106-validation`: raw walkers, domain validation, target resolution,
   path collision checks, and media action compatibility.
3. `issue-106-engine-reports`: initial state, hierarchy actions, journals,
   reports, writer, step/replay, and path/version history.
4. `issue-106-materializer`: audio-only synthesis/preflight and hierarchy path
   moves in phase B.
5. `issue-106-adapter-compare`: observed-state v2, fixture loader, topology
   indexes, matching keys, and compare tests.
6. `issue-106-generation-docs`: generation lanes, fixtures, schema export,
   docs, and final drift gates.

Each child slice must leave the repo in a coherent, testable state. For this
plan, "coherent" means the repository imports and type-checks against the new
public symbols after the slice's expected failures are fixed; it is not enough
for only the slice-local tests to pass. The first slice may intentionally remove
old `works` fixtures after updating the tests and schemas in that slice, but it
must also update direct import sites for removed symbols such as `Work`,
`ManifestWork`, `work_id`, and `WorkReport`. No compatibility shim is allowed.

Every child plan must end with its focused tests plus:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
```

Contract-touching child plans must also run
`uv run python -m chaos_librarian.schema_export --check`.

## Contract Version Targets

- `SCENARIO_SCHEMA_VERSION`: `12`
- `MANIFEST_SCHEMA_VERSION`: `7`
- `REPLAY_BUNDLE_SCHEMA_VERSION`: `7`
- `OBSERVED_STATE_SCHEMA_VERSION`: `2`
- `ASSET_REPORT_SCHEMA_VERSION`: `7`
- `VARIANT_REPORT_SCHEMA_VERSION`: `2`
- Domain report schema versions: new `MOVIE_REPORT_SCHEMA_VERSION`,
  `SERIES_REPORT_SCHEMA_VERSION`, `SEASON_REPORT_SCHEMA_VERSION`,
  `EPISODE_REPORT_SCHEMA_VERSION`, `ARTIST_REPORT_SCHEMA_VERSION`,
  `ALBUM_REPORT_SCHEMA_VERSION`, `DISC_REPORT_SCHEMA_VERSION`, and
  `TRACK_REPORT_SCHEMA_VERSION`, all starting at `1`.
- `ScenarioGeneration.profile_version`: bump from `2` to `3` because generated
  scenario metadata and budgets change shape.
- Remove `WORK_REPORT_SCHEMA_VERSION` and `schemas/work-report.schema.json`.
- Keep `BUNDLE_REPORT_SCHEMA_VERSION` at `1` unless implementation changes the
  bundle report shape.
- Keep `MATERIALIZATION_SCHEMA_VERSION`, `CAPABILITIES_SCHEMA_VERSION`, and
  `DIVERGENCE_SCHEMA_VERSION` unchanged unless their payloads gain fields.

Schema regeneration is required after each contract child slice:

```bash
uv run python -m chaos_librarian.schema_export --write
uv run python -m chaos_librarian.schema_export --check
```

## File Structure

Create:

- `src/chaos_librarian/contract/domain.py`
  - Shared contract enum `ParentKind` with `movie`, `episode`, and `track`.
  - No imports from `chaos_librarian.topology`; contract modules must not depend
    on runtime walkers.
- `src/chaos_librarian/topology.py`
  - Typed scenario walkers for `movie`, `episode`, and `track` leaves.
  - Current-state render contexts for plan/materialize hierarchy mutations.
  - Parent/child lookup indexes used by engine, materializer, reports, and
    adapter tests.
  - No compatibility `Work` abstraction.
- `src/chaos_librarian/path_rendering.py`
  - Display component normalization.
  - Movie, TV, and music layout rendering.
  - Derived sidecar path rendering.
  - Root-prefix replacement for `move_between_roots`.
- `tests/contract/test_hierarchy_path_rendering.py`
  - Contract-level renderer tests.
- `tests/validation/rules/test_hierarchy_rules.py`
  - Semantic hierarchy validation tests.
- `tests/engine/test_events_hierarchy.py`
  - Plan-only hierarchy action tests.
- `tests/materializer/test_audio_only.py`
  - Audio-only preflight, argv, and synthesis tests.
- `tests/materializer/test_hierarchy_moves.py`
  - Phase-B hierarchy path move tests.
- New fixture files under `tests/fixtures/scenarios/`:
  - `movie-folder-layout.yaml`
  - `tv-season-folders.yaml`
  - `music-artist-album-disc.yaml`
  - `hierarchy-renumber-episode.yaml`
  - `hierarchy-move-track.yaml`

Modify:

- `src/chaos_librarian/contract/__init__.py`
- `src/chaos_librarian/contract/scenario.py`
- `src/chaos_librarian/contract/manifest.py`
- `src/chaos_librarian/contract/reports.py`
- `src/chaos_librarian/contract/observed_state.py`
- `src/chaos_librarian/contract/profiles.py`
- `src/chaos_librarian/contract/paths.py`
- `src/chaos_librarian/schema_export.py`
- `src/chaos_librarian/validation/codes.py`
- `src/chaos_librarian/validation/rules/_common.py`
- `src/chaos_librarian/validation/rules/id_duplicate.py`
- `src/chaos_librarian/validation/rules/target_unknown.py`
- `src/chaos_librarian/validation/rules/path_containment.py`
- `src/chaos_librarian/validation/rules/asset_path_safety.py`
- `src/chaos_librarian/validation/rules/materialize_media_matrix.py`
- `src/chaos_librarian/validation/rules/profile_budgets.py`
- `src/chaos_librarian/validation/rules/slow_copy.py`
- `src/chaos_librarian/validation/rules/timeline_lifecycle.py`
- `src/chaos_librarian/validation/rules/sidecar_target.py`
- `src/chaos_librarian/validation/rules/extract_track_unknown.py`
- `src/chaos_librarian/validation/semantic.py`
- `src/chaos_librarian/engine/state.py`
- `src/chaos_librarian/engine/events.py`
- `src/chaos_librarian/engine/path_history.py`
- `src/chaos_librarian/engine/reports.py`
- `src/chaos_librarian/engine/writer.py`
- `src/chaos_librarian/adapter/fixture.py`
- `src/chaos_librarian/adapter/index.py`
- `src/chaos_librarian/adapter/compare.py`
- `src/chaos_librarian/adapter/history.py`
- `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- `src/chaos_librarian/materializer/preflight.py`
- `src/chaos_librarian/materializer/synthesis.py`
- `src/chaos_librarian/materializer/manifest_build.py`
- `src/chaos_librarian/materializer/actions.py`
- `src/chaos_librarian/materializer/phase_b/__init__.py`
- `src/chaos_librarian/materializer/phase_b/filesystem.py`
- `src/chaos_librarian/materializer/phase_b/media.py`
- `src/chaos_librarian/materializer/persistence/writer.py`
- `src/chaos_librarian/materializer/persistence/reports.py`
- `src/chaos_librarian/generation_lanes.py`
- `src/chaos_librarian/generation_planner.py`
- `src/chaos_librarian/generation.py`
- `tests/support/adapter.py`
- Existing contract, validation, engine, materializer, adapter, generation,
  sample-scenario, and CLI tests that still construct `works`.
- `docs/contract/*.md`
- `docs/specs/chaos-librarian-design.md`
- `schemas/*.schema.json`

Delete:

- `schemas/work-report.schema.json`
- Work report model and tests once domain reports exist.
- Any `works`-only fixture that cannot be converted to `movies`, `series`, or
  `artists` without changing its intent.

## Data Model Shape

Add these scenario model families in `contract/scenario.py`:

```python
class MovieLayout(enum.StrEnum):
    MOVIE_FLAT = "movie_flat"
    MOVIE_FOLDER = "movie_folder"


class SeriesLayout(enum.StrEnum):
    SEASON_FOLDERS = "season_folders"
    SERIES_FLAT = "series_flat"


class EpisodeNaming(enum.StrEnum):
    SXXEXX_TITLE = "sxxexx_title"
    ONE_XX_TITLE = "one_xx_title"
    ABSOLUTE_3_DIGIT_TITLE = "absolute_3_digit_title"
    DATE_TITLE = "date_title"


class ArtistLayout(enum.StrEnum):
    ARTIST_ALBUM_DISC = "artist_album_disc"
    ARTIST_ALBUM_FLAT = "artist_album_flat"


class TrackNaming(enum.StrEnum):
    TRACK_NUMBER_TITLE = "track_number_title"
    DISC_TRACK_NUMBER_TITLE = "disc_track_number_title"
```

Use tuple-backed frozen Pydantic models matching current scenario conventions:

```python
class Movie(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    layout: MovieLayout
    variants: tuple[Variant, ...]


class Series(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    layout: SeriesLayout
    episode_naming: EpisodeNaming
    seasons: tuple[Season, ...]


class Season(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    season_number: int = Field(ge=0)
    title: str
    episodes: tuple[Episode, ...]


class Episode(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    episode_number: int = Field(ge=1)
    title: str
    aired_on: date | None = None
    absolute_number: int | None = Field(default=None, ge=1)
    variants: tuple[Variant, ...]


class Artist(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    name: str
    layout: ArtistLayout
    track_naming: TrackNaming
    albums: tuple[Album, ...]


class Album(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    title: str
    release_year: int | None = None
    discs: tuple[Disc, ...]


class Disc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    disc_number: int = Field(ge=1)
    tracks: tuple[Track, ...]


class Track(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str
    track_number: int = Field(ge=1)
    title: str
    performers: tuple[str, ...] = Field(default_factory=tuple)
    variants: tuple[Variant, ...]
```

`Scenario` becomes:

```python
class Scenario(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True, frozen=True)

    schema_version: Literal[12]
    scenario_id: str
    seed: int | Literal["random"]
    duration_scale: DurationScale
    profiles: tuple[ProfileName, ...] = Field(default_factory=tuple)
    generation: ScenarioGeneration | None = None
    library: Library
    movies: tuple[Movie, ...]
    series: tuple[Series, ...]
    artists: tuple[Artist, ...]
    timeline: tuple[TimelineEvent, ...]
```

Add hierarchy timeline events to `TimelineActionName`, the discriminated union,
and `_STATE_DELTA_KEYS`:

```python
class RenumberEpisodeEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.RENUMBER_EPISODE] = (
        TimelineActionName.RENUMBER_EPISODE
    )
    target: str
    episode_number: int = Field(ge=1)
    absolute_number: int | None = Field(default=None, ge=1)


class MoveEpisodeToSeasonEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.MOVE_EPISODE_TO_SEASON] = (
        TimelineActionName.MOVE_EPISODE_TO_SEASON
    )
    target: str
    to_season: str
    episode_number: int = Field(ge=1)
    absolute_number: int | None = Field(default=None, ge=1)


class RenameSeasonEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.RENAME_SEASON] = TimelineActionName.RENAME_SEASON
    target: str
    title: str


class RenumberDiscEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.RENUMBER_DISC] = TimelineActionName.RENUMBER_DISC
    target: str
    disc_number: int = Field(ge=1)


class MoveTrackToDiscEvent(_TimelineEventBase):
    action: Literal[TimelineActionName.MOVE_TRACK_TO_DISC] = (
        TimelineActionName.MOVE_TRACK_TO_DISC
    )
    target: str
    to_disc: str
    track_number: int = Field(ge=1)
```

## Shared Topology And Rendering

The first child plan must create typed helpers before any subsystem-specific
rewrite. The rest of the implementation should import these helpers rather
than walking the scenario tree ad hoc.

`ParentKind` must live in `chaos_librarian.contract.domain` so manifest,
reports, observed-state, and topology helpers share one contract enum without
contract modules importing runtime walkers.

```python
class ParentKind(enum.StrEnum):
    MOVIE = "movie"
    EPISODE = "episode"
    TRACK = "track"
```

`topology.py` should import `ParentKind` from that module and expose:

```python
@dataclass(frozen=True, slots=True)
class AssetContext:
    parent_kind: ParentKind
    parent_id: str
    movie: Movie | None
    series: Series | None
    season: Season | None
    episode: Episode | None
    artist: Artist | None
    album: Album | None
    disc: Disc | None
    track: Track | None
    variant: Variant
    bundle: Bundle
    asset: Asset
    bundle_asset_count: int
```

Minimum public helpers:

```python
def iter_asset_contexts(scenario: Scenario) -> Iterator[AssetContext]:
    """Yield every playable/listenable asset context in declaration order."""


def asset_contexts_by_id(scenario: Scenario) -> dict[str, AssetContext]:
    """Return `asset_id -> AssetContext` for every declared asset."""


def asset_ids_under_target(
    scenario: Scenario, *, target_kind: str, target_id: str
) -> tuple[str, ...]:
    """Return initially declared asset ids under a target in manifest order."""
```

Scenario contexts are not enough for hierarchy events because prior hierarchy
actions mutate season, episode, disc, and track metadata. Define this renderer
input shape in `path_rendering.py` so both immutable scenario walkers and
mutable `WorldState` can build it:

```python
@dataclass(frozen=True, slots=True)
class RenderableAssetContext:
    parent_kind: ParentKind
    root_path: str
    layout: MovieLayout | SeriesLayout | ArtistLayout
    naming: EpisodeNaming | TrackNaming | None
    movie_title: str | None
    series_title: str | None
    season_number: int | None
    episode_number: int | None
    episode_title: str | None
    aired_on: date | None
    absolute_number: int | None
    artist_name: str | None
    album_title: str | None
    disc_number: int | None
    track_number: int | None
    track_title: str | None
    variant_label: str
    asset_role: str
    asset_container: str
    bundle_asset_count: int
```

`path_rendering.py` should expose:

```python
def clean_display_component(value: str) -> str:
    """Normalize one display-derived path component or raise ValueError."""


def render_asset_path(ctx: RenderableAssetContext) -> str:
    """Render the media file path for one asset context."""


def render_declared_sidecar_path(media_path: str, language: str) -> str:
    """Render the declared sidecar path next to the media stem."""


def replace_root_prefix(path: str, *, from_root: str, to_root: str) -> str:
    """Replace only the library root prefix of a rendered media path."""
```

Renderer tests must pin every contract recipe, not just one happy path. At
minimum, include these exact expectations:

```python
assert clean_display_component("  A / B\t C  ") == "A - B C"
assert render_asset_path(movie_flat_ctx) == "Movies/Orbit - 1080p.mkv"
assert render_asset_path(movie_folder_ctx) == "Movies/Orbit/Orbit - 1080p.mkv"
assert render_asset_path(tv_sxxexx_ctx) == (
    "TV/Starline/Season 01/Starline - S01E01 - Pilot - 1080p.mkv"
)
assert render_asset_path(tv_one_xx_ctx) == (
    "TV/Starline/Starline - 1x01 - Pilot - 1080p.mkv"
)
assert render_asset_path(tv_absolute_ctx) == (
    "TV/Starline/Starline - 007 - Signal - 1080p.mkv"
)
assert render_asset_path(tv_date_ctx) == (
    "TV/Starline/Starline - 2024-05-01 - Pilot - 1080p.mkv"
)
assert render_asset_path(track_disc_ctx) == (
    "Music/North Index/Winter Index/Disc 01/01 - Opening - lossless.flac"
)
assert render_asset_path(track_flat_ctx) == (
    "Music/North Index/Winter Index/01-01 - Opening - lossless.flac"
)
assert render_asset_path(multi_asset_ctx) == (
    "Movies/Orbit/Orbit - 1080p - feature.mkv"
)
```

The renderer must reject empty components, `.`, `..`, absolute syntax, Windows
drive prefixes, empty path segments, and parent segments. It must not lowercase,
transliterate, or slugify.

## Child Plan 1: Contract And Renderer

**Files:**
- Create: `src/chaos_librarian/contract/domain.py`
- Create: `src/chaos_librarian/topology.py`
- Create: `src/chaos_librarian/path_rendering.py`
- Create: `tests/contract/test_hierarchy_path_rendering.py`
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/contract/manifest.py`
- Modify: `src/chaos_librarian/contract/reports.py`
- Modify: `src/chaos_librarian/contract/observed_state.py`
- Modify: `src/chaos_librarian/contract/profiles.py`
- Modify: `src/chaos_librarian/schema_export.py`
- Modify: contract tests and `schemas/`

- [ ] **Step 1: Write failing contract tests for scenario v12**

Add tests that validate a movie-only, TV-only, and music-only payload with
required top-level `movies`, `series`, and `artists` collections, and assert
payloads with `works` now raise `ValidationError`.

The TV payload must include a `season_number: 0` specials season so the contract
test catches any accidental `ge=1` implementation.

Run:

```bash
uv run pytest tests/contract/test_scenario.py -q --no-cov
```

Expected: fail because `Scenario` still requires `works`.

- [ ] **Step 2: Write failing renderer tests**

Create `tests/contract/test_hierarchy_path_rendering.py` with direct model
payloads for movie, TV, and music contexts. Include collision-sensitive
multi-asset bundle coverage where the rendered path appends ` - {asset.role}`.
Cover all six layout values and every `episode_naming` / `track_naming` value
listed in the renderer examples above.

Run:

```bash
uv run pytest tests/contract/test_hierarchy_path_rendering.py -q --no-cov
```

Expected: import failure for `chaos_librarian.path_rendering`.

- [ ] **Step 3: Replace scenario contract**

Remove `Work`, add the domain models, add hierarchy timeline event classes, set
`Scenario.schema_version: Literal[12]`, and update
`ScenarioGeneration.profile_version` to `Literal[3]`. Create
`contract/domain.py` with `ParentKind`; do not import `chaos_librarian.topology`
from any `contract/*` module. Update generation budgets to:

```python
class GenerationBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    movies: int = Field(ge=0)
    series: int = Field(ge=0)
    seasons: int = Field(ge=0)
    episodes: int = Field(ge=0)
    artists: int = Field(ge=0)
    albums: int = Field(ge=0)
    discs: int = Field(ge=0)
    tracks: int = Field(ge=0)
    variants: int = Field(ge=0)
    bundles: int = Field(ge=0)
    assets: int = Field(ge=0)
    sidecars: int = Field(ge=0)
    timeline_events: int = Field(ge=0)
```

- [ ] **Step 4: Replace manifest and report contracts**

Manifest v7 must contain normalized domain lists:

```text
movies, series, seasons, episodes, artists, albums, discs, tracks,
variants, bundles, assets, versions, locations, sidecars
```

Pin the manifest row fields in tests:

```text
ManifestMovie: id, title, layout
ManifestSeries: id, title, layout, episode_naming
ManifestSeason: id, series_id, season_number, title
ManifestEpisode: id, season_id, episode_number, title, aired_on, absolute_number
ManifestArtist: id, name, layout, track_naming
ManifestAlbum: id, artist_id, title, release_year
ManifestDisc: id, album_id, disc_number
ManifestTrack: id, disc_id, track_number, title, performers
```

`ManifestVariant` must replace `work_id` with:

```python
parent_kind: ParentKind
parent_id: str
```

Import `ParentKind` from `chaos_librarian.contract.domain`; do not define a
second enum in `manifest.py`, `reports.py`, or `observed_state.py`.

Reports must remove `WorkReport`, add the eight domain report models, add
`parent_kind` and `parent_id` to `VariantReport`, and add nullable topology
fields to `AssetReport`.

Pin domain report fields in tests:

```text
MovieReport: movie_id, title, variant_ids, asset_ids
SeriesReport: series_id, title, season_ids, episode_ids, asset_ids
SeasonReport: season_id, series_id, season_number, title, episode_ids, asset_ids
EpisodeReport: episode_id, season_id, episode_number, title, aired_on,
  absolute_number, variant_ids, asset_ids
ArtistReport: artist_id, name, album_ids, track_ids, asset_ids
AlbumReport: album_id, artist_id, title, release_year, disc_ids, track_ids,
  asset_ids
DiscReport: disc_id, album_id, disc_number, track_ids, asset_ids
TrackReport: track_id, disc_id, track_number, title, performers, variant_ids,
  asset_ids
AssetReport topology fields: parent_kind, parent_id, movie_id, series_id,
  season_id, episode_id, artist_id, album_id, disc_id, track_id, variant_id,
  bundle_id
```

- [ ] **Step 5: Replace observed-state contract**

Observed-state v2 must remove observed works and add observed domain rows.
`ObservedVariant` must use `parent_kind` and `parent_ref`. `ObservedAsset`
must remove `work_ref` and keep `variant_ref` / `bundle_ref`.

Pin observed row fields and validators in tests:

```text
ObservedMovie: observed_ref, title
ObservedSeries: observed_ref, title
ObservedSeason: observed_ref, series_ref, season_number, title
ObservedEpisode: observed_ref, season_ref, episode_number, title, aired_on,
  absolute_number
ObservedArtist: observed_ref, name
ObservedAlbum: observed_ref, artist_ref, title, release_year
ObservedDisc: observed_ref, album_ref, disc_number
ObservedTrack: observed_ref, disc_ref, track_number, title, performers
```

Observed-state validation must reject duplicate domain refs and parent refs that
do not resolve within the same payload.

- [ ] **Step 6: Export schemas**

Update `schema_export.MODELS` to remove `work-report.schema.json` and add the
eight domain report schemas.

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
uv run pytest tests/contract/test_schema_export.py -q --no-cov
```

Expected: pass after schema artifacts are regenerated.

- [ ] **Step 7: Prove removed contract symbols are not stranded**

Search for old public contract symbols and update every import or field access
that would make the repository unimportable. Valid remaining matches are limited
to migration notes in this plan, the source spec, and changelog-style docs.

Run:

```bash
rg -n "Scenario\\.works|ManifestWork|WorkReport|WORK_REPORT_SCHEMA_VERSION|work_id" src tests
uv run ty check src tests
```

Expected: the search returns no live source/test references to removed symbols,
and `ty` exits `0`.

## Child Plan 2: Validation

**Files:**
- Create: `tests/validation/rules/test_hierarchy_rules.py`
- Modify: `src/chaos_librarian/validation/codes.py`
- Modify: `src/chaos_librarian/validation/rules/_common.py`
- Modify: all rule modules that currently call `iter_global_namespaces`,
  `iter_asset_ids`, `iter_assets_with_loc`, `asset_containers`, or
  `iter_declared_sidecars`.

- [ ] **Step 1: Extend raw walkers**

Replace the `works[*].variants[*]...` walker with explicit branches for:

```text
movies[*].variants[*].bundle.assets[*]
series[*].seasons[*].episodes[*].variants[*].bundle.assets[*]
artists[*].albums[*].discs[*].tracks[*].variants[*].bundle.assets[*]
```

Return loc tuples that point at the exact YAML branch, for example:

```python
("series", s_idx, "seasons", season_idx, "episodes", ep_idx, "variants", v_idx, "bundle", "assets", a_idx)
```

- [ ] **Step 2: Add hierarchy validation codes**

Add:

```python
E_HIERARCHY_INVALID: Final = "E_HIERARCHY_INVALID"
E_PATH_COLLISION: Final = "E_PATH_COLLISION"
```

Use `E_LIFECYCLE_INVALID` for in-flight slow-copy rejection under mutated
hierarchy entities.

- [ ] **Step 3: Write hierarchy semantic tests**

Pin these behaviors:

- duplicate IDs across roots, domain entities, variants, bundles, assets, and
  timeline events.
- `season_number: 0` accepted for specials, and negative season numbers rejected.
- duplicate episode numbers in one season.
- duplicate disc numbers in one album.
- duplicate track numbers in one disc.
- `date_title` without `aired_on`.
- `absolute_3_digit_title` without positive `absolute_number`.
- rendered initial path collision.
- hierarchy action targeting the wrong entity kind.
- hierarchy action producing a rendered path collision.
- hierarchy action under an in-flight slow copy.
- `reencode_video`, subtitle actions, and video-only corruption actions against
  audio-only track assets.

Run:

```bash
uv run pytest tests/validation/rules/test_hierarchy_rules.py -q --no-cov
```

Expected: fail before rules are implemented.

- [ ] **Step 4: Update materialize media matrix validation**

Allow the first-slice audio-only matrix only for track assets:

```text
flac + flac
mp3 + mp3
m4a + aac
```

Reject video/subtitle streams on track assets in this slice. Reject audio-only
assets under movies and TV. Reject video-capable `mkv`/`mp4` movie/TV assets
without a video track.

- [ ] **Step 5: Update path containment and collisions**

Use `render_asset_path()` for initial asset paths and hierarchy action
simulation. Validation must maintain a mutable topology snapshot while replaying
timeline actions so a second hierarchy action renders from the metadata changed
by the first. `move_between_roots` must replace only the root prefix and keep the
domain suffix unchanged.

## Child Plan 3: Engine State, Events, Reports

**Files:**
- Create: `tests/engine/test_events_hierarchy.py`
- Modify: `src/chaos_librarian/engine/state.py`
- Modify: `src/chaos_librarian/engine/events.py`
- Modify: `src/chaos_librarian/engine/path_history.py`
- Modify: `src/chaos_librarian/engine/reports.py`
- Modify: `src/chaos_librarian/engine/writer.py`
- Modify: `tests/engine/conftest.py`
- Modify: engine tests that construct `works`.

- [ ] **Step 1: Rebuild initial state from topology helpers**

`build_initial_state()` must populate domain manifest lists and render initial
locations with `render_asset_path()`. It should track declared renderer-derived
sidecars internally:

```python
_derived_sidecar_ids: set[str] = field(default_factory=set)
```

Declared sidecar paths should be `render_declared_sidecar_path(media_path,
language)`.

- [ ] **Step 2: Add hierarchy metadata mutation support**

`WorldState` needs normalized domain dictionaries and parent indexes. Add helper
methods that return affected current asset locations and derived sidecars for a
hierarchy target. These helpers must build `RenderableAssetContext` from current
`WorldState` metadata, not from the original immutable `Scenario`, so sequential
hierarchy actions render from the latest metadata.

- [ ] **Step 3: Add hierarchy event handlers**

Each hierarchy action emits one atomic journal entry. `target_ids` order must
be:

```text
[hierarchy_target_id, *affected_asset_ids_in_manifest_order]
```

`state_delta` must include:

```python
{
    "metadata": {"field": {"before": old_value, "after": new_value}},
    "path_moves": [
        {
            "asset_id": asset_id,
            "location_id": location_id,
            "from_path": old_path,
            "to_path": new_path,
        },
    ],
    "sidecar_moves": [
        {
            "sidecar_id": sidecar_id,
            "asset_id": asset_id,
            "from_path": old_path,
            "to_path": new_path,
        },
    ],
    "skipped_deleted_asset_ids": ["asset_deleted_example"],
}
```

Add tests for these edge cases:

- a deleted asset under the hierarchy target records `skipped_deleted_asset_ids`
  and does not get a location move.
- a later `add_file` for that deleted asset keeps its explicit `to` path instead
  of rerendering through the hierarchy recipe.
- renderer-derived declared sidecars move with media paths, while
  timeline-created sidecars with explicit paths stay put.

- [ ] **Step 4: Project hierarchy path history**

`derive_path_history()` must read `path_moves` and emit one `PathHistoryEntry`
per affected asset for hierarchy actions.

- [ ] **Step 5: Emit domain reports**

`ReportSet` must replace `works` with:

```text
movies, series, seasons, episodes, artists, albums, discs, tracks
```

Update `engine.writer` and materialize writer report directories to write:

```text
reports/movies/
reports/series/
reports/seasons/
reports/episodes/
reports/artists/
reports/albums/
reports/discs/
reports/tracks/
reports/assets/
reports/variants/
reports/bundles/
```

## Child Plan 4: Materializer

**Files:**
- Create: `tests/materializer/test_audio_only.py`
- Create: `tests/materializer/test_hierarchy_moves.py`
- Modify: `src/chaos_librarian/media_matrix.py`
- Modify: `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Modify: `src/chaos_librarian/materializer/manifest_build.py`
- Modify: `src/chaos_librarian/materializer/actions.py`
- Modify: `src/chaos_librarian/materializer/phase_b/__init__.py`
- Modify: `src/chaos_librarian/materializer/phase_b/filesystem.py`
- Modify: materializer tests and fixtures.

- [ ] **Step 1: Add audio-only preflight tests**

Pin accepted cells:

```text
flac/flac, mp3/mp3, m4a/aac
```

Pin rejected cells:

```text
track with video
track with subtitles
track with unsupported container/codec
movie or episode without video
```

- [ ] **Step 2: Allow audio-only ffmpeg argv**

Change `build_command()` to accept `video: VideoTrack | None` and
`video_input: FFmpegInput | None`. Audio-only argv must map only audio inputs,
avoid `-c:v`, and still include `BITEXACT_FLAGS`.

- [ ] **Step 3: Write phase A at rendered paths**

`materialize_assets_phase_a()` should iterate `AssetContext` objects and pass
each context through the `RenderableAssetContext` adapter before passing the
rendered path into `materialize_one_asset()` instead of deriving
`<root>/<asset_id>.<container>`.

- [ ] **Step 4: Add hierarchy phase-B filesystem handler**

Add hierarchy actions to the supported materialize action set. Implement a
single handler that reads `path_moves` and `sidecar_moves`, validates all
destinations are either free or part of the same move set, stages all sources to
temporary sibling paths, and then moves temps to final destinations.

Tests must cover an outside destination collision, an in-set path swap that
requires temporary siblings, a renderer-derived sidecar move, and an explicit
timeline-created sidecar that remains at its explicit path.

If any move fails, raise `FilesystemActionError`; the existing failure path
must write failure metadata and must not write a successful sentinel.

## Child Plan 5: Adapter Compare

**Files:**
- Modify: `src/chaos_librarian/adapter/fixture.py`
- Modify: `src/chaos_librarian/adapter/index.py`
- Modify: `src/chaos_librarian/adapter/compare.py`
- Modify: `src/chaos_librarian/adapter/history.py`
- Modify: `tests/support/adapter.py`
- Modify: `tests/contract/test_observed_state.py`
- Modify: adapter and CLI compare tests.

- [ ] **Step 1: Load domain reports**

`OracleReports` must carry domain report maps and must validate each present
report directory exactly against the initial manifest IDs.

- [ ] **Step 2: Build domain topology views**

Replace `work_title|variant_label|member_count` with domain-specific keys:

```text
movie:<title>|<variant_label>|<member_count>
episode:<series>|<season>|<episode>|<episode_title>|<variant_label>
track:<artist>|<album>|<disc>|<track>|<track_title>|<variant_label>
```

Keep topology matching as a fallback after paths and hashes.

- [ ] **Step 3: Compare observed topology v2**

Observed variants use `parent_kind` and `parent_ref`. Topology comparison
should compare the domain key for matched assets and keep the current
`D_TOPOLOGY_MISMATCH` finding unless a new divergence field is necessary.

## Child Plan 6: Generation, Fixtures, Docs, Final Gates

**Files:**
- Modify: `src/chaos_librarian/contract/profiles.py`
- Modify: `src/chaos_librarian/generation_lanes.py`
- Modify: `src/chaos_librarian/generation_planner.py`
- Modify: `src/chaos_librarian/generation.py`
- Modify: generation tests and seed manifest.
- Modify: all sample scenarios in `tests/fixtures/scenarios/`.
- Modify: `docs/contract/*.md`
- Modify: `docs/specs/chaos-librarian-design.md`

- [ ] **Step 1: Add topology lanes**

Add these members to the existing `FuzzLaneName` enum; do not replace the
existing lane members:

```python
TV_TOPOLOGY = "tv-topology"
MUSIC_TOPOLOGY = "music-topology"
```

Add lane configs with required coverage cells for at least one hierarchy
mutation plus ordinary file/media mutation coverage.

- [ ] **Step 2: Emit explicit hierarchy YAML**

Generation output must include explicit `layout`, `episode_naming`, and
`track_naming` fields. `ScenarioGeneration.profile_version` must be `3`, and
the generated budget payload must use the domain budget fields from Child Plan
1. Replay must continue to embed generated scenario YAML and must not call the
generator.

- [ ] **Step 3: Convert static fixtures**

Convert existing `works` fixtures into `movies` unless the fixture's intent is
specifically TV or music. Use movie layouts explicitly; do not leave implicit
defaults.

- [ ] **Step 4: Update docs**

Update public docs for:

- schema reference, including removed `work-report`.
- manifest initial-state paths.
- observed-state v2 topology refs.
- fixture layout report directories.
- integration recipes for movies, TV, music, and audio-only track assets.

- [ ] **Step 5: Final verification**

Run:

```bash
uv run pytest tests/contract -q
uv run pytest tests/validation -q
uv run pytest tests/engine -q
uv run pytest tests/materializer -q
uv run pytest tests/cli -q
uv run pytest tests/test_generation.py tests/test_generation_properties.py -q
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Expected: all commands exit `0` with no warnings.

## Open Decisions To Settle Before Child Plan 1

- Whether to create a single `E_HIERARCHY_INVALID` validation code for numbering
  and recipe metadata errors, or separate codes per failure class. The parent
  recommendation is one code to keep the consumer-facing taxonomy small.
- Whether `performers` on `Track` is required or defaults to an empty tuple. The
  parent recommendation is default empty tuple because compilation support is
  optional in this slice.
- Whether `BundleReport` needs a schema bump. The parent recommendation is no
  bump unless implementation changes its fields.
- Whether `DivergenceReport` needs domain-specific refs. The parent
  recommendation is no bump for this slice; put domain-key detail inside
  existing `expected` and `observed` payloads.

## Self-Review Checklist

- The old `works` source contract is removed, not accepted in parallel.
- The renderer is the only place that derives initial domain paths.
- Validation, plan-only, materialize phase A, and hierarchy event handlers all
  call the same renderer.
- Audio-only support is limited to tracks and the specified first-slice matrix.
- Hierarchy actions mutate metadata and current rendered paths atomically.
- Materialize hierarchy moves preflight the complete move set before touching
  disk.
- Domain reports and observed-state refs are normalized, not nested.
- Generated scenarios are explicit and deterministic.
- All schema artifacts are regenerated in the same change as their model edits.
