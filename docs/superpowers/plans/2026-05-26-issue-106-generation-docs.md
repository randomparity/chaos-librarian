# Issue 106 Generation Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish Issue 106 by teaching fuzz generation to emit TV and music
hierarchies, refreshing the checked-in fixtures, and updating the public docs to
describe the schema v12 hierarchy contract.

**Architecture:** Keep generated scenarios explicit. The generator should write
the same domain fields humans write: movie `layout`, series `layout` plus
`episode_naming`, and artist `layout` plus `track_naming`. Do not add implicit
defaults or a compatibility `works` layer. Generation lanes are still lane
contracts over deterministic YAML plus required coverage cells; add topology
lanes without weakening existing lane coverage.

**Tech Stack:** Python 3.13, Pydantic v2, ruamel.yaml, pytest, Typer CLI tests,
ruff, ty.

---

## Context

The parent plan is
`docs/superpowers/plans/2026-05-26-issue-106-media-hierarchies.md`.

The contract, renderer, validation, engine/reports, materializer, and
adapter/compare slices have landed. Current remaining gaps:

- `FuzzLaneName` has no `tv-topology` or `music-topology` lanes.
- `generation_planner.plan_payload_parts()` returns only `movies` and hardcodes
  the `movies-hd` root into event paths.
- `FUZZ_GENERATION_PROFILE_VERSION` is already `3`, and generated YAML already
  uses schema v12 plus domain budget fields, but `FUZZ_REGRESSION` budgets still
  set all TV/music counts to zero.
- Static scenario fixtures are schema v12/domain-shaped, but several movie
  fixtures still use stale `work_*` movie ids.
- The checked-in sample corpus has no non-empty `series:` or `artists:` sample
  and no audio-only track sample.
- Docs still mention `work-report`, `reports/works`, observed-state v1, and
  `work_ref`/`work_id` terminology in several files.

## Files

- Modify: `src/chaos_librarian/contract/profiles.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/generation_lanes.py`
- Modify: `src/chaos_librarian/generation_planner.py`
- Modify: `src/chaos_librarian/generation.py`
- Modify: `tests/test_generation.py`
- Modify: `tests/test_generation_properties.py` only if property assumptions
  need to account for audio-only track assets.
- Modify: `tests/cli/test_generate.py`
- Modify: `tests/fixtures/fuzz-seeds.yaml`
- Modify: `tests/fixtures/scenarios/fuzz-smoke-seed-123.yaml`
- Modify: `tests/fixtures/scenarios/fuzz-regression-seed-456.yaml`
- Modify: static fixtures under `tests/fixtures/scenarios/` that still use
  stale `id: work_*` movie ids.
- Create: `tests/fixtures/scenarios/tv-season-folders.yaml`
- Create: `tests/fixtures/scenarios/music-artist-album-disc.yaml`
- Create: `tests/fixtures/scenarios/audio-only-track.yaml`
- Modify: `docs/contract/schema-reference.md`
- Modify: `docs/contract/manifest-initial-state.md`
- Modify: `docs/contract/observed-state.md`
- Modify: `docs/contract/fixture-layout.md`
- Modify: `docs/contract/integration-recipes.md`
- Modify: `docs/contract/divergence-report.md`
- Modify: `docs/specs/chaos-librarian-design.md`

JSON Schema regeneration is expected in Task 1 because `FuzzLaneName` enum
values are part of `scenario.schema.json`. Regenerate with
`uv run python -m chaos_librarian.schema_export --write` and include the
generated artifact in the same commit.

## Task 1: Add TV and Music Fuzz Lanes

**Files:**
- Modify: `src/chaos_librarian/contract/profiles.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/generation_lanes.py`
- Modify: `src/chaos_librarian/generation_planner.py`
- Modify: `src/chaos_librarian/generation.py`
- Modify: `tests/test_generation.py`
- Modify: `tests/cli/test_generate.py`
- Modify: `tests/fixtures/fuzz-seeds.yaml`

- [ ] **Step 1: Add failing generation tests**

In `tests/test_generation.py`, extend
`test_generated_lane_meets_required_coverage()` with:

```python
(FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.TV_TOPOLOGY, 463),
(FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MUSIC_TOPOLOGY, 464),
```

Add these tests below `test_generated_gated_lanes_include_required_profiles()`:

```python
def test_tv_topology_lane_emits_explicit_series_hierarchy() -> None:
    payload = _generated_payload(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.TV_TOPOLOGY,
        seed=463,
    )

    assert payload["movies"] == []
    series = cast(list[dict[str, object]], payload["series"])
    assert len(series) == 1
    assert series[0]["id"] == "series_001"
    assert series[0]["layout"] == "season_folders"
    assert series[0]["episode_naming"] == "sxxexx_title"
    seasons = cast(list[dict[str, object]], series[0]["seasons"])
    assert [season["id"] for season in seasons] == ["season_001", "season_002"]
    episodes = [
        episode
        for season in seasons
        for episode in cast(list[dict[str, object]], season["episodes"])
    ]
    assert [episode["id"] for episode in episodes] == ["episode_001", "episode_002"]

    actions = {event["action"] for event in cast(list[dict[str, object]], payload["timeline"])}
    assert {
        "renumber_episode",
        "move_episode_to_season",
        "rename_file",
        "reencode_video",
    } <= actions


def test_music_topology_lane_emits_explicit_artist_hierarchy_and_audio_only_track() -> None:
    payload = _generated_payload(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.MUSIC_TOPOLOGY,
        seed=464,
    )

    assert payload["movies"] == []
    assert payload["series"] == []
    artists = cast(list[dict[str, object]], payload["artists"])
    assert len(artists) == 1
    assert artists[0]["id"] == "artist_001"
    assert artists[0]["layout"] == "artist_album_disc"
    assert artists[0]["track_naming"] == "disc_track_number_title"
    albums = cast(list[dict[str, object]], artists[0]["albums"])
    discs = cast(list[dict[str, object]], albums[0]["discs"])
    assert [disc["id"] for disc in discs] == ["disc_001", "disc_002"]
    tracks = [
        track
        for disc in discs
        for track in cast(list[dict[str, object]], disc["tracks"])
    ]
    assert [track["id"] for track in tracks] == ["track_001", "track_002"]

    variants = cast(list[dict[str, object]], tracks[0]["variants"])
    bundle = cast(dict[str, object], variants[0]["bundle"])
    assets = cast(list[dict[str, object]], bundle["assets"])
    first_asset = assets[0]
    assert first_asset["role"] == "primary_audio"
    assert first_asset["container"] == "flac"
    assert "video" not in first_asset
    assert cast(list[dict[str, object]], first_asset["audio"])[0]["codec"] == "flac"

    actions = {event["action"] for event in cast(list[dict[str, object]], payload["timeline"])}
    assert {"renumber_disc", "move_track_to_disc", "rename_file", "reencode_audio"} <= actions
```

In `tests/cli/test_generate.py`, add a focused CLI enum smoke test:

```python
def test_generate_accepts_topology_lanes(tmp_path: Path) -> None:
    for lane in ("tv-topology", "music-topology"):
        out = tmp_path / f"{lane}.yaml"
        result = runner.invoke(
            app,
            [
                "generate",
                "--profile",
                "fuzz-regression",
                "--lane",
                lane,
                "--seed",
                "463",
                "--out",
                str(out),
            ],
        )

        assert result.exit_code == 0, result.stdout + result.stderr
        assert _load_generated(out).generation is not None
```

Run:

```bash
uv run pytest tests/test_generation.py::test_lane_configs_cover_allowed_lane_contract tests/test_generation.py::test_generated_lane_meets_required_coverage tests/test_generation.py::test_tv_topology_lane_emits_explicit_series_hierarchy tests/test_generation.py::test_music_topology_lane_emits_explicit_artist_hierarchy_and_audio_only_track tests/cli/test_generate.py::test_generate_accepts_topology_lanes -q --no-cov
```

Expected: failures for missing enum members / unsupported lanes.

- [ ] **Step 2: Add lane names and generation budgets**

In `src/chaos_librarian/contract/profiles.py`, add:

```python
TV_TOPOLOGY = "tv-topology"
MUSIC_TOPOLOGY = "music-topology"
```

to `FuzzLaneName`, and add both members to the
`FuzzProfileName.FUZZ_REGRESSION` lane set.

In `src/chaos_librarian/contract/scenario.py`, update the
`FuzzProfileName.FUZZ_REGRESSION` `GenerationBudget` to:

```python
GenerationBudget(
    movies=12,
    series=1,
    seasons=2,
    episodes=2,
    artists=1,
    albums=1,
    discs=2,
    tracks=2,
    variants=22,
    bundles=22,
    assets=22,
    sidecars=54,
    timeline_events=80,
)
```

- [ ] **Step 3: Extend lane configuration**

In `src/chaos_librarian/generation_lanes.py`, change `LaneConfig` to include
domain counts:

```python
@dataclass(frozen=True, slots=True)
class LaneConfig:
    profile: FuzzProfileName
    lane: FuzzLaneName
    profiles: tuple[ProfileName, ...]
    movies: int
    series: int
    artists: int
    timeline_events: int
    required_cells: frozenset[str]
```

Add `series=0, artists=0` to existing lane configs. Add these two configs:

```python
(FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.TV_TOPOLOGY): LaneConfig(
    profile=FuzzProfileName.FUZZ_REGRESSION,
    lane=FuzzLaneName.TV_TOPOLOGY,
    profiles=(ProfileName.FUZZ_REGRESSION,),
    movies=0,
    series=1,
    artists=0,
    timeline_events=18,
    required_cells=frozenset(
        {
            _action_cell(TimelineActionName.RENUMBER_EPISODE),
            _action_cell(TimelineActionName.MOVE_EPISODE_TO_SEASON),
            _action_cell(TimelineActionName.RENAME_FILE),
            _action_cell(TimelineActionName.REENCODE_VIDEO),
        }
    ),
),
(FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.MUSIC_TOPOLOGY): LaneConfig(
    profile=FuzzProfileName.FUZZ_REGRESSION,
    lane=FuzzLaneName.MUSIC_TOPOLOGY,
    profiles=(ProfileName.FUZZ_REGRESSION,),
    movies=0,
    series=0,
    artists=1,
    timeline_events=18,
    required_cells=frozenset(
        {
            _action_cell(TimelineActionName.RENUMBER_DISC),
            _action_cell(TimelineActionName.MOVE_TRACK_TO_DISC),
            _action_cell(TimelineActionName.RENAME_FILE),
            _action_cell(TimelineActionName.REENCODE_AUDIO),
        }
    ),
),
```

- [ ] **Step 4: Emit movie, TV, and music payload parts**

In `src/chaos_librarian/generation_planner.py`:

1. Change `PlannedAsset` so video is optional and audio codec is explicit:

```python
@dataclass(frozen=True, slots=True)
class PlannedAsset:
    asset_id: str
    container: str
    audio_codec: str
    audio_channels: str
    video_codec: str | None = None
    resolution: str | None = None
    role: str = "primary_video"
    has_declared_subtitle: bool = False
```

2. Change `plan_payload_parts()` to return library, movies, series, artists,
   and timeline:

```python
) -> tuple[
    dict[str, object],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
```

3. Keep existing movie lane output unchanged except for the new `audio_codec`
   field. For movie and TV video assets, use `audio_codec="aac"`,
   `video_codec="h264"` or `"hevc"`, and `role="primary_video"`.
4. Add `_series_payload()` that emits one series:

```yaml
id: series_001
title: fuzz-regression tv-topology Series 463
layout: season_folders
episode_naming: sxxexx_title
seasons:
  - id: season_001
    season_number: 1
    title: Season 1
    episodes:
      - id: episode_001
        episode_number: 1
        title: Pilot
        variants:
          - id: variant_series_001
            label: tv-topology
            bundle:
              id: bundle_series_001
              assets:
                - id: asset_001
                  role: primary_video
                  container: mkv
                  duration_seconds: 5
                  video:
                    source: color_bars
                    codec: h264
                    resolution: hd
                  audio:
                    - source: sine
                      codec: aac
                      channels: stereo
                      language: eng
  - id: season_002
    season_number: 2
    title: Season 2
    episodes:
      - id: episode_002
        episode_number: 1
        title: Return
        variants:
          - id: variant_series_002
            label: tv-topology
            bundle:
              id: bundle_series_002
              assets:
                - id: asset_002
                  role: primary_video
                  container: mp4
                  duration_seconds: 5
                  video:
                    source: color_bars
                    codec: h264
                    resolution: 1080p
                  audio:
                    - source: sine
                      codec: aac
                      channels: stereo
                      language: eng
```

5. Add `_artists_payload()` that emits one artist with one album, two discs,
   and two audio-only tracks. `track_asset_001` must be `container: flac`,
   `role: primary_audio`, no `video` key, and an audio track with
   `codec: flac`. `track_asset_002` may be `container: mp3` with
   `codec: mp3`.
6. Change `_asset_payload()` so it omits the `video` key when
   `asset.video_codec is None`, and uses `asset.audio_codec` for the first
   audio track.
7. Add lane handlers:

```python
elif lane is FuzzLaneName.TV_TOPOLOGY:
    _renumber_episode(planner, target="episode_001", episode_number=2)
    _move_episode_to_season(
        planner,
        target="episode_002",
        to_season="season_002",
        episode_number=2,
    )
    _rename_file(planner, assets[0])
    _reencode_video(planner, assets[0])
elif lane is FuzzLaneName.MUSIC_TOPOLOGY:
    _renumber_disc(planner, target="disc_001", disc_number=2)
    _move_track_to_disc(
        planner,
        target="track_002",
        to_disc="disc_002",
        track_number=2,
    )
    _rename_file(planner, assets[0])
    _reencode_audio(planner, assets[0])
```

Use small helper functions that append the corresponding event dictionaries.
The `target` for hierarchy events is the episode, season, disc, or track id;
the `target` for file/media events remains the asset id.

- [ ] **Step 5: Update generation payload assembly**

In `src/chaos_librarian/generation.py`, unpack the new return value:

```python
library, movies, series, artists, timeline = plan_payload_parts(
    seed=seed,
    config=config,
    rng=rng,
)
```

and write:

```python
"movies": movies,
"series": series,
"artists": artists,
```

- [ ] **Step 6: Update seed manifest**

In `tests/fixtures/fuzz-seeds.yaml`, add:

```yaml
  - lane: tv-topology
    seed: 463
    gates: [validate, plan, replay, materialize]
  - lane: music-topology
    seed: 464
    gates: [validate, plan, replay, materialize]
```

under `fuzz_regression:`.

- [ ] **Step 7: Verify and commit**

Run:

```bash
uv run pytest tests/test_generation.py tests/test_generation_properties.py tests/cli/test_generate.py tests/cli/test_generate_replay.py -q --no-cov
uv run pytest tests/contract/test_scenario.py::test_generation_budget_uses_domain_counts tests/contract/test_scenario.py::test_generation_profile_version_must_be_supported tests/contract/test_schema_export.py::test_scenario_schema_freezes_generation_profile_version tests/validation/rules/test_profile_budgets.py -q --no-cov
uv run ruff check src/chaos_librarian/contract/profiles.py src/chaos_librarian/contract/scenario.py src/chaos_librarian/generation_lanes.py src/chaos_librarian/generation_planner.py src/chaos_librarian/generation.py tests/test_generation.py tests/cli/test_generate.py
uv run ruff format --check src/chaos_librarian/contract/profiles.py src/chaos_librarian/contract/scenario.py src/chaos_librarian/generation_lanes.py src/chaos_librarian/generation_planner.py src/chaos_librarian/generation.py tests/test_generation.py tests/cli/test_generate.py
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
git diff --check
git add src/chaos_librarian/contract/profiles.py src/chaos_librarian/contract/scenario.py src/chaos_librarian/generation_lanes.py src/chaos_librarian/generation_planner.py src/chaos_librarian/generation.py tests/test_generation.py tests/cli/test_generate.py tests/fixtures/fuzz-seeds.yaml schemas
git commit -m "feat: generate hierarchy fuzz lanes"
```

## Task 2: Refresh Scenario Fixtures

**Files:**
- Modify: `tests/fixtures/scenarios/fuzz-smoke-seed-123.yaml`
- Modify: `tests/fixtures/scenarios/fuzz-regression-seed-456.yaml`
- Modify: static fixtures under `tests/fixtures/scenarios/` with stale
  `id: work_*` movie ids.
- Create: `tests/fixtures/scenarios/tv-season-folders.yaml`
- Create: `tests/fixtures/scenarios/music-artist-album-disc.yaml`
- Create: `tests/fixtures/scenarios/audio-only-track.yaml`
- Modify: `tests/test_generation.py` if the committed generated fixture list
  should include topology fixtures.

- [ ] **Step 1: Refresh committed generated fixtures**

Regenerate the two currently committed generated fixtures with the generator
from Task 1:

```bash
mkdir -p .tmp-issue-106-generation
uv run chaos-librarian generate --profile fuzz-smoke --seed 123 --lane smoke --out .tmp-issue-106-generation/fuzz-smoke-seed-123.yaml
uv run chaos-librarian generate --profile fuzz-regression --seed 456 --lane core-fs --out .tmp-issue-106-generation/fuzz-regression-seed-456.yaml
mv .tmp-issue-106-generation/fuzz-smoke-seed-123.yaml tests/fixtures/scenarios/fuzz-smoke-seed-123.yaml
mv .tmp-issue-106-generation/fuzz-regression-seed-456.yaml tests/fixtures/scenarios/fuzz-regression-seed-456.yaml
trash .tmp-issue-106-generation
```

Run:

```bash
uv run pytest tests/test_generation.py::test_committed_generated_fixtures_match_generator -q --no-cov
```

Expected: pass.

- [ ] **Step 2: Rename stale movie ids**

For sample fixtures that now live under `movies:`, replace stale movie ids that
start with `work_` with `movie_`. The known files are:

```text
tests/fixtures/scenarios/archive-file-explicit-root.yaml
tests/fixtures/scenarios/slow-copy-materialize.yaml
tests/fixtures/scenarios/sidecar-collision.yaml
tests/fixtures/scenarios/interceptor-catalog-run.yaml
tests/fixtures/scenarios/reencode-video.yaml
tests/fixtures/scenarios/sidecar-create-via-timeline.yaml
tests/fixtures/scenarios/active-library-churn.yaml
tests/fixtures/scenarios/archive-file.yaml
tests/fixtures/scenarios/malformed-container-header.yaml
tests/fixtures/scenarios/hevc-mkv.yaml
tests/fixtures/scenarios/negative-oracle-hash.yaml
tests/fixtures/scenarios/delete-add-restore.yaml
tests/fixtures/scenarios/move-between-roots.yaml
tests/fixtures/scenarios/interceptor-catalog.yaml
tests/fixtures/scenarios/invalid/corrupt-container-header-missing-profile.yaml
tests/fixtures/scenarios/invalid/corrupt-container-header-during-slow-copy.yaml
tests/fixtures/scenarios/invalid/truncate-file-missing-profile.yaml
tests/fixtures/scenarios/invalid/materialize-video-source-noise.yaml
tests/fixtures/scenarios/invalid/move-between-roots-unknown-root.yaml
tests/fixtures/scenarios/invalid/wrong-oracle-hash-missing-profile.yaml
tests/fixtures/scenarios/invalid/corrupt-container-header-after-delete.yaml
tests/fixtures/scenarios/invalid/touch-mtime-missing-profile.yaml
tests/fixtures/scenarios/invalid/materialize-video-resolution-small.yaml
tests/fixtures/scenarios/invalid/materialize-video-codec-av1.yaml
```

Use this replacement rule only on YAML id lines:

```text
    id: work_quasar  ->      id: movie_quasar
```

Do not change regression tests that intentionally verify old `work_ref` or
`work-report` rejection.

- [ ] **Step 3: Add TV, music, and audio-only samples**

Create `tests/fixtures/scenarios/tv-season-folders.yaml`:

```yaml
schema_version: 12
scenario_id: tv-season-folders
seed: 10601
duration_scale: short
library:
  roots:
    - id: tv_root
      path: tv
movies: []
series:
  - id: series_atlas
    title: Atlas Station
    layout: season_folders
    episode_naming: sxxexx_title
    seasons:
      - id: season_atlas_1
        season_number: 1
        title: Season 1
        episodes:
          - id: episode_atlas_1
            episode_number: 1
            title: First Signal
            variants:
              - id: variant_atlas_hd
                label: hd
                bundle:
                  id: bundle_atlas_hd
                  assets:
                    - id: asset_atlas_ep1
                      role: primary_video
                      container: mkv
                      duration_seconds: 5
                      video:
                        source: color_bars
                        codec: h264
                        resolution: hd
                      audio:
                        - source: sine
                          codec: aac
                          channels: stereo
                          language: eng
      - id: season_atlas_2
        season_number: 2
        title: Season 2
        episodes: []
artists: []
timeline:
  - id: ev_renumber_atlas
    at: 1s
    action: renumber_episode
    target: episode_atlas_1
    episode_number: 2
  - id: ev_move_atlas
    at: 2s
    action: move_episode_to_season
    target: episode_atlas_1
    to_season: season_atlas_2
    episode_number: 1
```

Create `tests/fixtures/scenarios/music-artist-album-disc.yaml`:

```yaml
schema_version: 12
scenario_id: music-artist-album-disc
seed: 10602
duration_scale: short
library:
  roots:
    - id: music_root
      path: music
movies: []
series: []
artists:
  - id: artist_glass
    name: Glass Harbour
    layout: artist_album_disc
    track_naming: disc_track_number_title
    albums:
      - id: album_tides
        title: Synthetic Tides
        release_year: 2026
        discs:
          - id: disc_tides_1
            disc_number: 1
            tracks:
              - id: track_tides_1
                track_number: 1
                title: Low Tide
                performers: [Glass Harbour]
                variants:
                  - id: variant_tides_flac
                    label: flac
                    bundle:
                      id: bundle_tides_flac
                      assets:
                        - id: asset_tides_track1
                          role: primary_audio
                          container: flac
                          duration_seconds: 5
                          audio:
                            - source: sine
                              codec: flac
                              channels: stereo
                              language: eng
          - id: disc_tides_2
            disc_number: 2
            tracks: []
timeline:
  - id: ev_renumber_disc
    at: 1s
    action: renumber_disc
    target: disc_tides_1
    disc_number: 2
  - id: ev_move_track
    at: 2s
    action: move_track_to_disc
    target: track_tides_1
    to_disc: disc_tides_2
    track_number: 1
```

Create `tests/fixtures/scenarios/audio-only-track.yaml`:

```yaml
schema_version: 12
scenario_id: audio-only-track
seed: 10603
duration_scale: short
library:
  roots:
    - id: music_root
      path: music
movies: []
series: []
artists:
  - id: artist_tone
    name: Tone Lab
    layout: artist_album_flat
    track_naming: track_number_title
    albums:
      - id: album_tone
        title: Calibration
        discs:
          - id: disc_tone_1
            disc_number: 1
            tracks:
              - id: track_tone_1
                track_number: 1
                title: Stereo Sweep
                variants:
                  - id: variant_tone_mp3
                    label: mp3
                    bundle:
                      id: bundle_tone_mp3
                      assets:
                        - id: asset_tone_track1
                          role: primary_audio
                          container: mp3
                          duration_seconds: 4
                          audio:
                            - source: sine
                              codec: mp3
                              channels: stereo
                              language: eng
timeline:
  - id: ev_reencode_audio
    at: 1s
    action: reencode_audio
    target: asset_tone_track1
    from_channels: stereo
    to_channels: mono
```

- [ ] **Step 4: Verify sample corpus and commit**

Run:

```bash
rg -n "^works:|id: work_" tests/fixtures/scenarios
```

Expected: no output.

Run:

```bash
uv run pytest tests/contract/test_sample_scenarios.py tests/validation/test_invalid_corpus.py tests/test_generation.py::test_committed_generated_fixtures_match_generator -q --no-cov
uv run ruff check tests/test_generation.py
uv run ruff format --check tests/test_generation.py
uv run ty check src tests
git diff --check
git add tests/fixtures/fuzz-seeds.yaml tests/fixtures/scenarios tests/test_generation.py
git commit -m "test: refresh hierarchy scenario fixtures"
```

## Task 3: Update Contract Docs

**Files:**
- Modify: `docs/contract/schema-reference.md`
- Modify: `docs/contract/manifest-initial-state.md`
- Modify: `docs/contract/observed-state.md`
- Modify: `docs/contract/fixture-layout.md`
- Modify: `docs/contract/integration-recipes.md`
- Modify: `docs/contract/divergence-report.md`
- Modify: `docs/specs/chaos-librarian-design.md`

- [ ] **Step 1: Update schema and report references**

In `docs/contract/schema-reference.md`, remove `work-report.schema.json` and
describe these checked-in schemas with current versions:

```text
scenario.schema.json: 12
manifest.schema.json: 7
journal.schema.json: 1
replay-bundle.schema.json: 7
validation.schema.json: 1
materialization.schema.json: 9
run-sentinel.schema.json: 2
capabilities.schema.json: 3
asset-report.schema.json: 7
variant-report.schema.json: 2
bundle-report.schema.json: 1
movie-report.schema.json: 1
series-report.schema.json: 1
season-report.schema.json: 1
episode-report.schema.json: 1
artist-report.schema.json: 1
album-report.schema.json: 1
disc-report.schema.json: 1
track-report.schema.json: 1
observed-state.schema.json: 2
divergence.schema.json: 1
```

In `docs/contract/fixture-layout.md`, replace `reports/works/` with the domain
report directories:

```text
reports/movies/
reports/series/
reports/seasons/
reports/episodes/
reports/artists/
reports/albums/
reports/discs/
reports/tracks/
reports/variants/
reports/bundles/
reports/assets/
```

- [ ] **Step 2: Update manifest and observed-state docs**

In `docs/contract/manifest-initial-state.md`, describe initial state as:

```text
The initial manifest is derived from the explicit domain hierarchy in the
scenario: movies[*].variants, series[*].seasons[*].episodes[*].variants, and
artists[*].albums[*].discs[*].tracks[*].variants. Initial asset paths are
rendered from the root path, the selected movie/series/artist layout, the leaf
metadata, the variant label, and the asset container.
```

In `docs/contract/observed-state.md`, update the contract to schema version 2
and replace `work_ref` examples with domain topology refs. The domain row
families are:

```text
movies
series
seasons
episodes
artists
albums
discs
tracks
variants
bundles
assets
sidecars
```

Asset rows should show `observed_ref`, `current_path`, optional hashes/size, and
links to `variant_ref`/`bundle_ref` only when the consumer can provide them. Do
not document `work_ref`.

- [ ] **Step 3: Update recipes and divergence prose**

In `docs/contract/integration-recipes.md`, add recipes for:

```text
Movie fixtures: use movies[*] with explicit movie_flat or movie_folder layout.
TV fixtures: use series[*].seasons[*].episodes[*] with explicit layout and episode_naming.
Music fixtures: use artists[*].albums[*].discs[*].tracks[*] with explicit layout and track_naming.
Audio-only track assets: use a track asset with role primary_audio, an audio container such as flac/mp3/m4a, no video key, and a supported audio codec.
Fuzz regression hierarchy lanes: include tv-topology and music-topology in lane lists and seed manifests.
```

In `docs/contract/divergence-report.md`, update `D_TOPOLOGY_MISMATCH` to say
that hierarchy topology compares movie, series, season, episode, artist, album,
disc, track, variant, bundle, and asset relationships. Do not use
`work/variant/bundle` as the topology shorthand.

- [ ] **Step 4: Update design document examples**

In `docs/specs/chaos-librarian-design.md`, update stale examples so they use:

```yaml
movies:
  - id: movie_quasar
    title: Synthetic Quasar
    layout: movie_flat
series:
  - id: series_atlas
    title: Atlas Station
    layout: season_folders
    episode_naming: sxxexx_title
artists:
  - id: artist_glass
    name: Glass Harbour
    layout: artist_album_disc
    track_naming: disc_track_number_title
```

Replace stale `work_id`, `work_ref`, and `reports/works` references with domain
terms. Keep historical issue references only where the text explicitly talks
about old rejection/regression tests.

- [ ] **Step 5: Verify docs and commit**

Run:

```bash
rg -n "work-report|reports/works|work_ref|work_id|schema_version: 1|\\bworks\\b" docs/contract docs/specs/chaos-librarian-design.md
```

Expected: no stale user-facing contract references. If the design doc includes
historical notes that intentionally mention old `works`, rewrite the note to
say the old shape is rejected by schema v12.

Run:

```bash
uv run python -m chaos_librarian.schema_export --check
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
git diff --check
git add docs/contract docs/specs/chaos-librarian-design.md
git commit -m "docs: document hierarchy generation contracts"
```

## Task 4: Final Verification

**Files:**
- No edits expected unless a gate finds a real defect.

- [ ] **Step 1: Run focused suites**

Run:

```bash
uv run pytest tests/contract -q
uv run pytest tests/validation -q
uv run pytest tests/engine -q
uv run pytest tests/materializer -q
uv run pytest tests/cli -q
uv run pytest tests/test_generation.py tests/test_generation_properties.py -q
```

Expected: all pass, no skips that hide Issue 106 coverage.

- [ ] **Step 2: Run repository gates**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
git diff --check
git status --short
```

Expected:

```text
All 21 schemas up-to-date.
```

and a clean worktree except for intentional committed history.

- [ ] **Step 3: Run stale-shape scans**

Run:

```bash
rg -n "^works:|id: work_|work-report|reports/works|work_ref|work_id" tests/fixtures/scenarios docs/contract docs/specs/chaos-librarian-design.md schemas src tests
rg -n -U "^series:\n\\s+-|^artists:\n\\s+-" tests/fixtures/scenarios
rg -n "container: (flac|mp3|m4a)|role: primary_audio|audio-only|audio_only" tests/fixtures/scenarios
```

Expected:

- First command returns only intentional negative tests that reject stale
  `work_ref`/`work-report` shapes, if any.
- Second command shows at least the TV and music fixtures added in Task 2.
- Third command shows the music/audio-only fixtures added in Task 2.

- [ ] **Step 4: Commit any gate fixes**

If final gates require edits, commit them with the smallest accurate message,
for example:

```bash
git add docs src tests schemas
git commit -m "fix: align hierarchy generation docs"
```

If no edits are needed, do not create an empty commit.

## Final Review

After Task 4 passes, dispatch a final code-review subagent over the full child
slice diff. The review should check:

- `tv-topology` and `music-topology` are available through the profile contract,
  CLI option enum, lane configs, seed manifest, and generated YAML.
- Generated TV and music payloads use explicit hierarchy layout/naming fields.
- Music generation includes audio-only track assets and materialize preflight
  gates cover them.
- Existing movie generation output remains deterministic and checked-in
  generated fixtures match the generator.
- Public docs no longer describe `work-report`, `reports/works`, observed-state
  v1, `work_ref`, or `work_id` as current contract shapes.
