# Issue 106 Media Hierarchies Design

**Status:** approved design for implementation planning.
**Target implementation branch:** `feat/issue-106-media-hierarchies`.
**Source context:** GitHub issue #106 and 2026-05-26 design discussion.

## Goal

Replace the movie-centric `work -> variant -> bundle -> asset` contract with
first-class media-library hierarchies for movies, TV series, and music.

The project is pre-release, so this design chooses the long-term architecture
over compatibility. The old `works` root is removed instead of duplicated or
shimmed. Existing file, media, sidecar, corruption, and network-lag mutations
remain asset-targeted unless the mutation is explicitly about hierarchy
metadata.

## Decisions

- Replace `Scenario.works` with required top-level `movies`, `series`, and
  `artists` collections.
- Keep `variants -> bundle -> assets` as the reusable delivery tail under the
  playable/listenable leaf entity.
- Keep scenario authoring nested, but normalize manifest, reports, and observed
  state into first-class entity lists with parent IDs.
- Make layout and naming recipes part of the scenario contract, not hidden
  generator behavior.
- Add a small set of hierarchy-targeted timeline actions now.
- Hierarchy actions update both oracle metadata and current filesystem paths
  through the active layout recipe.
- Defer podcasts, movie releases/editions, advanced music artifacts, and
  automatic numbering swaps to separate issues.

## Current State

The current public scenario shape is:

```text
works -> variants -> bundle -> assets
```

`Work` only carries `id`, `title`, and `variants`. Initial locations are
synthesized with:

```text
<library.roots[0].path>/<asset.id>.<asset.container>
```

That path convention works for compact movie fixtures, but it cannot represent
scanner-facing TV or music layouts such as season folders, episode numbering,
artist/album/disc folders, or track numbering. Consumers also cannot compare
domain topology directly because manifest and observed-state contracts only
know about works, variants, bundles, and assets.

## Scenario Contract

Scenario v12 removes `works` and adds three required top-level collections:

```yaml
movies: []
series: []
artists: []
```

Empty collections are valid so a TV-only scenario can set `movies: []` and
`artists: []`.

### Movies

Movie scenarios stay intentionally simple:

```text
movies -> variants -> bundle -> assets
```

Example:

```yaml
movies:
  - id: movie_orbit
    title: Orbit
    layout: movie_flat
    variants:
      - id: variant_1080p
        label: 1080p
        bundle:
          id: bundle_1080p
          assets: []
```

Initial movie layout enum values:

| value | path intent |
| --- | --- |
| `movie_flat` | Put movie assets directly under the primary root. |
| `movie_folder` | Put movie assets under a title folder. |

Do not add a movie release or edition layer in this slice. That is tracked in
[#117](https://github.com/randomparity/chaos-librarian/issues/117).

### TV Series

TV scenarios model series, seasons, and episodes directly:

```text
series -> seasons -> episodes -> variants -> bundle -> assets
```

Example:

```yaml
series:
  - id: series_starline
    title: Starline
    layout: season_folders
    episode_naming: sxxexx_title
    seasons:
      - id: season_starline_01
        season_number: 1
        title: Season 1
        episodes:
          - id: episode_starline_s01e01
            episode_number: 1
            title: Pilot
            aired_on: 2024-05-01
            variants: []
```

Initial TV layout enum values:

| field | values |
| --- | --- |
| `layout` | `season_folders`, `series_flat` |
| `episode_naming` | `sxxexx_title`, `one_xx_title`, `absolute_3_digit_title`, `date_title` |

`season_number: 0` is allowed and means specials. Normal seasons use positive
season numbers. `episode_number` is always positive. `date_title` requires
`aired_on`. `absolute_3_digit_title` requires `absolute_number` on each episode
that uses the recipe; do not infer absolute numbers from season ordering.

### Music

Music scenarios model artist, album, disc, and track directly:

```text
artists -> albums -> discs -> tracks -> variants -> bundle -> assets
```

Example:

```yaml
artists:
  - id: artist_north
    name: North Index
    layout: artist_album_disc
    track_naming: track_number_title
    albums:
      - id: album_winter
        title: Winter Index
        release_year: 2024
        discs:
          - id: disc_winter_01
            disc_number: 1
            tracks:
              - id: track_winter_01_01
                track_number: 1
                title: Opening
                performers:
                  - North Index
                variants: []
```

Initial music layout enum values:

| field | values |
| --- | --- |
| `layout` | `artist_album_disc`, `artist_album_flat` |
| `track_naming` | `track_number_title`, `disc_track_number_title` |

`disc_number` and `track_number` are positive integers. Compilation albums can
be represented by an artist named `Various Artists` plus per-track
`performers`. Richer music artifacts are deferred to
[#118](https://github.com/randomparity/chaos-librarian/issues/118).

## Reusable Tail

`Variant`, `Bundle`, and `Asset` remain the reusable media-delivery tail. Their
contract can keep the existing names, but their parents change:

```text
movie | episode | track -> variants -> bundle -> assets
```

The implementation should avoid a new `Work` abstraction. If shared code needs
to walk playable/listenable leaf entities, use a small local iterator or typed
helper with explicit `movie`, `episode`, and `track` branches.

Music requires audio-only materialization. `Asset.video` is already optional in
the scenario contract, but the materializer currently rejects video-less assets.
This enhancement must extend materialize/preflight support for audio-only assets
and expand the media matrix for the selected first-slice music containers and
audio codecs. Existing video assets remain valid under movie and TV scenarios.
Track assets in this first slice must omit `video`.

First-slice audio-only support is limited to this matrix:

| container | audio codec | stream constraints |
| --- | --- | --- |
| `flac` | `flac` | One audio stream; no video or subtitle streams. |
| `mp3` | `mp3` | One audio stream; no video or subtitle streams. |
| `m4a` | `aac` | One audio stream; no video or subtitle streams. |

Movie and TV assets keep the existing `mkv`/`mp4` video-capable matrix. The
validation layer must reject unsupported track containers/codecs before planning,
and materialize preflight must run the same matrix before run-directory
allocation.

## Layout And Path Rendering

The initial path convention moves from a global asset-id template to a
domain-aware renderer. The renderer receives:

- library root path
- domain entity metadata
- layout and naming recipe
- variant label
- bundle member context
- asset role, id, and container

The renderer returns a relative POSIX path under `<run-dir>/library/`. The same
renderer must be used by validation, plan-only state, materialize phase A, and
hierarchy timeline handlers.

All initial paths start under the primary library root
`scenario.library.roots[0].path`. `move_between_roots` swaps only the root path
prefix and keeps the rendered domain path suffix unchanged.

Path components are rendered from display metadata as follows:

- Strip leading and trailing whitespace.
- Collapse internal whitespace runs to one space.
- Replace `/`, `\`, and NUL with `-`.
- Reject empty components and components equal to `.` or `..`.

The renderer does not lowercase, transliterate, or otherwise slugify display
text. Validation rejects any rendered path with empty segments, dot segments,
parent segments, absolute-path syntax, Windows drive prefixes, or collisions.

Canonical first-slice templates before extension:

Line wraps in this list are for Markdown only; adjacent template fragments
concatenate without spaces.

- `movie_flat`:
  `{root}/{movie_title} - {variant_label}{member_suffix}`
- `movie_folder`:
  `{root}/{movie_title}/{movie_title} - {variant_label}{member_suffix}`
- `season_folders`:
  `{root}/{series_title}/Season {season_number:02d}/`
  `{episode_stem} - {variant_label}{member_suffix}`
- `series_flat`:
  `{root}/{series_title}/{episode_stem} - {variant_label}{member_suffix}`
- `artist_album_disc`:
  `{root}/{artist_name}/{album_title}/Disc {disc_number:02d}/`
  `{track_stem} - {variant_label}{member_suffix}`
- `artist_album_flat`:
  `{root}/{artist_name}/{album_title}/`
  `{track_stem} - {variant_label}{member_suffix}`

`episode_stem` is selected by `episode_naming`:

| recipe | stem |
| --- | --- |
| `sxxexx_title` | `{series_title} - S{season_number:02d}E{episode_number:02d} - {episode_title}` |
| `one_xx_title` | `{series_title} - {season_number}x{episode_number:02d} - {episode_title}` |
| `absolute_3_digit_title` | `{series_title} - {absolute_number:03d} - {episode_title}` |
| `date_title` | `{series_title} - {aired_on} - {episode_title}` |

`track_stem` is selected by `track_naming`:

| recipe | stem |
| --- | --- |
| `track_number_title` | `{track_number:02d} - {track_title}` |
| `disc_track_number_title` | `{disc_number:02d}-{track_number:02d} - {track_title}` |

`member_suffix` is empty when a bundle has one asset. When a bundle has multiple
assets, it is ` - {asset.role}`. The renderer includes the variant label and
bundle-member role; if a scenario still renders duplicate paths, validation
fails. The renderer never invents extra suffixes after the scenario has
validated. The file extension is always `.{asset.container}`.

Derived paths must be deterministic and collision-checked. If two declared
assets render to the same path, validation fails before planning. The renderer
does not silently overwrite or invent non-contract suffixes after validation.

Declared sidecars should derive from the media asset stem and stay near the
asset when the layout recipe implies colocated sidecars. Existing explicit
timeline sidecar paths remain explicit scenario paths.

## Manifest And Reports

Manifest v7 removes `works` and adds normalized domain lists:

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
versions
locations
sidecars
```

Domain manifest rows expose the metadata needed for topology comparison and path
history:

- `ManifestMovie`: `id`, `title`, `layout`
- `ManifestSeries`: `id`, `title`, `layout`, `episode_naming`
- `ManifestSeason`: `id`, `series_id`, `season_number`, `title`
- `ManifestEpisode`: `id`, `season_id`, `episode_number`, `title`, `aired_on`,
  `absolute_number`
- `ManifestArtist`: `id`, `name`, `layout`, `track_naming`
- `ManifestAlbum`: `id`, `artist_id`, `title`, `release_year`
- `ManifestDisc`: `id`, `album_id`, `disc_number`
- `ManifestTrack`: `id`, `disc_id`, `track_number`, `title`, `performers`

Parent relationships are represented by IDs:

- `ManifestSeason.series_id`
- `ManifestEpisode.season_id`
- `ManifestAlbum.artist_id`
- `ManifestDisc.album_id`
- `ManifestTrack.disc_id`
- `ManifestVariant.parent_kind`
- `ManifestVariant.parent_id`
- `ManifestBundle.variant_id`
- `ManifestAsset.bundle_id`

`ManifestVariant.parent_kind` is a closed enum with `movie`, `episode`, and
`track`.

Reports replace `work-report` with domain reports:

```text
movie-report
series-report
season-report
episode-report
artist-report
album-report
disc-report
track-report
```

Emit them under `reports/movies/`, `reports/series/`, `reports/seasons/`,
`reports/episodes/`, `reports/artists/`, `reports/albums/`, `reports/discs/`,
and `reports/tracks/`. Keep `reports/assets/`, `reports/variants/`, and
`reports/bundles/`.

Domain reports expose the entity's display metadata, direct parent ID, direct
child IDs, and transitive `asset_ids`:

- `movie-report`: `movie_id`, `title`, `variant_ids`, `asset_ids`
- `series-report`: `series_id`, `title`, `season_ids`, `episode_ids`,
  `asset_ids`
- `season-report`: `season_id`, `series_id`, `season_number`, `title`,
  `episode_ids`, `asset_ids`
- `episode-report`: `episode_id`, `season_id`, `episode_number`, `title`,
  `aired_on`, `absolute_number`, `variant_ids`, `asset_ids`
- `artist-report`: `artist_id`, `name`, `album_ids`, `track_ids`, `asset_ids`
- `album-report`: `album_id`, `artist_id`, `title`, `release_year`, `disc_ids`,
  `track_ids`, `asset_ids`
- `disc-report`: `disc_id`, `album_id`, `disc_number`, `track_ids`,
  `asset_ids`
- `track-report`: `track_id`, `disc_id`, `track_number`, `title`, `performers`,
  `variant_ids`, `asset_ids`

`variant-report` and `bundle-report` stay, but `variant-report` gains
`parent_kind` and `parent_id`. `asset-report` stays focused on asset history,
but it gains these topology fields so consumers can trace an asset without
loading every report:

- `parent_kind`: `movie`, `episode`, or `track`
- `parent_id`
- `movie_id`
- `series_id`
- `season_id`
- `episode_id`
- `artist_id`
- `album_id`
- `disc_id`
- `track_id`
- `variant_id`
- `bundle_id`

Only fields that apply to the asset's domain are populated; the others are
`null`.

## Observed State And Compare

Observed-state v2 mirrors the normalized domain model. Remove observed works and
add observed movies, series, seasons, episodes, artists, albums, discs, and
tracks. Observed variants reference `parent_kind` and `parent_ref`; observed
assets keep bundle/variant references and no longer carry `work_ref`.

Observed domain rows use consumer-local refs and optional metadata:

- `ObservedMovie`: `observed_ref`, `title`
- `ObservedSeries`: `observed_ref`, `title`
- `ObservedSeason`: `observed_ref`, `series_ref`, `season_number`, `title`
- `ObservedEpisode`: `observed_ref`, `season_ref`, `episode_number`, `title`,
  `aired_on`, `absolute_number`
- `ObservedArtist`: `observed_ref`, `name`
- `ObservedAlbum`: `observed_ref`, `artist_ref`, `title`, `release_year`
- `ObservedDisc`: `observed_ref`, `album_ref`, `disc_number`
- `ObservedTrack`: `observed_ref`, `disc_ref`, `track_number`, `title`,
  `performers`

All domain refs are unique within one observed-state payload. Optional metadata
can be omitted when an adapter cannot extract it, but refs and parent refs must
be present for every observed domain row the adapter emits.

Adapter matching should continue to use paths, hashes, probed media facts, and
topology. The topology key should be replaced with domain-specific keys, for
example:

- movie title plus variant label and bundle member count
- series title, season number, episode number, episode title, variant label
- artist name, album title, disc number, track number, track title, variant label

Comparison output can keep the existing divergence shape unless new
domain-specific fields are required by implementation. If divergence payloads
need first-class domain refs, bump `divergence.schema_version` and document the
new fields.

## Timeline Actions

Existing file and media timeline actions remain asset-targeted:

```text
move_asset
rename_file
delete_file
add_file
reencode_video
reencode_audio
create_sidecar
slow_copy_start
slow_copy_commit
archive_file
move_between_roots
remux_container
edit_metadata
embed_subtitle
extract_subtitle
remove_sidecar
update_sidecar
corrupt_container_header
truncate_file
corrupt_packet_range
write_invalid_duration_metadata
touch_mtime
wrong_oracle_hash
network_lag_start
network_lag_commit
```

Add hierarchy-targeted actions:

| action | target kind | fields |
| --- | --- | --- |
| `renumber_episode` | episode | `episode_number`; `absolute_number` when required |
| `move_episode_to_season` | episode | `to_season`, `episode_number`; optional `absolute_number` |
| `rename_season` | season | `title` |
| `renumber_disc` | disc | `disc_number` |
| `move_track_to_disc` | track | `to_disc`, `track_number` |

Each hierarchy action changes the named metadata and any rendered paths that
depend on that metadata.

Hierarchy actions are atomic journal events. `target_ids` must contain the
hierarchy target ID first, followed by affected asset IDs in manifest asset
order. `state_delta` must include:

- `metadata`: the before/after metadata fields changed by the action
- `path_moves`: `asset_id`, `location_id`, `from_path`, and `to_path` for each
  moved media asset
- `sidecar_moves`: `sidecar_id`, `asset_id`, `from_path`, and `to_path` for each
  moved derived sidecar
- `skipped_deleted_asset_ids`: deleted assets that got metadata updates but no
  current location move

The journal schema can stay v1 if no shape changes are needed because `action`
is already a string and `state_delta` is already open.

## Path Semantics For Hierarchy Actions

Hierarchy actions mutate normalized metadata and move every currently placed
asset under the affected hierarchy node to its newly rendered path. Declared
sidecars with renderer-derived paths move with their media asset and get
`sidecar_moves` entries. Timeline-created sidecars with explicit `to` paths stay
at their explicit paths unless a sidecar-specific timeline action targets them.

Plan-only state updates all affected manifest locations in one logical event.
Materialize mode must compute the complete move set before touching disk, reject
any destination that is occupied by an asset or sidecar outside the move set,
and use temporary sibling paths for moves that would otherwise collide within
the set. If any filesystem move fails, materialize reports the failure and does
not write a successful sentinel. The journal entry still stays atomic because
the oracle records only executable plans; partial materialize failure is
represented by the materialization report and sentinel state, not by extra
journal phases.

Example:

```yaml
- id: ev_renumber
  at: 5s
  action: renumber_episode
  target: episode_starline_s01e03
  episode_number: 2
```

Before:

```text
TV/Starline/Season 01/Starline - S01E03 - Missing Signal.mkv
```

After:

```text
TV/Starline/Season 01/Starline - S01E02 - Missing Signal.mkv
```

Deleted assets under the hierarchy target get metadata updates but no current
location move. When a later `add_file` restores that asset, the explicit `to`
path remains authoritative for that file action. Slow copies in flight under a
hierarchy target are rejected by lifecycle validation for this slice.

Duplicate numbering in the destination scope is rejected. Do not implement
implicit swapping. Explicit swap and rebalance actions are tracked in
[#119](https://github.com/randomparity/chaos-librarian/issues/119).

## Validation

Validation should add domain-specific rules:

- IDs are globally unique across roots, domain entities, variants, bundles,
  assets, and timeline events.
- Required top-level collections are present.
- `season_number` is `>= 0`; `0` is specials.
- `episode_number`, `disc_number`, and `track_number` are positive integers.
- `absolute_3_digit_title` requires positive `absolute_number`.
- Episode numbers are unique within a season.
- Disc numbers are unique within an album.
- Track numbers are unique within a disc.
- Layout and naming enum values are closed.
- Naming recipes have the metadata they need, such as `aired_on` for
  `date_title`.
- Derived initial paths are relative, contained under the library root, and
  unique.
- Hierarchy actions must leave derived current paths relative, contained, and
  unique after the action applies.
- Hierarchy timeline targets resolve to the correct entity kind.
- Hierarchy actions reject lifecycle states the engine cannot execute, including
  in-flight slow copies under the mutated entity.
- Music materialization validation rejects unsupported audio-only containers,
  codecs, and source combinations with the existing materialize error path.
- Media actions that require a video or subtitle stream reject audio-only track
  assets during validation. File-level actions and audio-compatible media actions
  remain valid for track assets.

Use structure-aware walkers for the new nested scenario shape. Do not preserve a
parallel `works` walker for compatibility.

## Generation

Add deterministic generation lanes for topology coverage:

```text
tv-topology
music-topology
```

The lanes emit explicit scenario YAML with layout and naming fields. They should
include at least one hierarchy-targeted mutation and enough file/media mutations
to prove the new path renderer composes with existing actions.

Generated replay bundles still embed the generated scenario YAML. Replay never
calls the generator.

`ScenarioGeneration.budgets` must replace the single `works` budget with
domain-specific budgets for movies, series, seasons, episodes, artists, albums,
discs, and tracks. Existing variant, bundle, asset, sidecar, and timeline-event
budgets remain. `ScenarioGeneration.profile_version` must bump because generated
scenario metadata changes shape.

## Contract Versioning

Expected version bumps:

| artifact | reason |
| --- | --- |
| scenario | `works` removed; `movies`, `series`, and `artists` added. |
| manifest | Domain entity lists replace `works`; variants get new parent shape. |
| replay bundle | Embedded scenario shape changes; consumers should detect incompatibility early. |
| observed state | Observed works replaced with normalized domain entities. |
| reports | New domain report schemas; `work-report` removed. |
| materialization | If audio-only materialized asset evidence needs new fields. |
| capabilities | Only if implementation adds a new public readiness flag. |
| divergence | Only if comparison output needs new domain-specific fields. |

The exact integer values must be assigned from the current constants during
implementation. At the time of this design, scenario is v11 and manifest is v6.

## Testing

Required test coverage:

- Contract shape tests for movie, TV, and music scenarios.
- Rejection of old `works`.
- JSON Schema export drift for every changed artifact.
- Initial path derivation for every first-slice layout and naming recipe.
- Derived path containment and duplicate-path rejection.
- `absolute_3_digit_title` rejection when `absolute_number` is missing.
- Hierarchy actions updating metadata and current paths.
- Hierarchy actions rejecting destination paths occupied outside the move set and
  safely handling in-set path move ordering.
- Hierarchy journal entries using the required `target_ids`, `path_moves`,
  `sidecar_moves`, and `skipped_deleted_asset_ids` shapes.
- Declared sidecars moving with renderer-derived media paths, while explicit
  timeline-created sidecars stay at explicit paths.
- Rejection of invalid hierarchy action targets and invalid lifecycle states.
- Music audio-only preflight and materialization.
- Rejection of unsupported track containers/codecs and video-bearing track
  assets.
- Rejection of video/subtitle-only media actions on audio-only track assets.
- Materialize path parity: files land where the plan-only manifest says they
  land.
- Report and observed-state schema tests for every new domain entity and asset
  topology reference.
- Adapter comparison using normalized movie, TV, and music topology.
- Generated `tv-topology` and `music-topology` lane determinism and coverage.

## Out Of Scope

- Podcast hierarchy and cleanup/download behavior:
  [#116](https://github.com/randomparity/chaos-librarian/issues/116).
- Movie release and edition hierarchy:
  [#117](https://github.com/randomparity/chaos-librarian/issues/117).
- CUE sheets, embedded lyrics, album-art format changes, multi-track single-file
  albums, and malformed music tag recipes:
  [#118](https://github.com/randomparity/chaos-librarian/issues/118).
- Automatic numbering swaps or rebalancing:
  [#119](https://github.com/randomparity/chaos-librarian/issues/119).
- Backward compatibility for `works`. This is intentionally rejected, not
  deferred.

## Acceptance Criteria

- Scenario authoring uses `movies`, `series`, and `artists`; `works` is gone.
- Plan-only manifests and reports expose normalized domain hierarchy.
- Initial plan/materialize paths are rendered from domain layout recipes.
- Hierarchy actions mutate metadata and current paths.
- TV and music generated lanes exist and validate deterministically.
- Existing file-level and audio-compatible mutation behavior still works under
  movie, episode, and track parents.
