# Scenario Authoring

A scenario is YAML that describes a synthetic media library, deterministic
inputs, and optional timeline mutations. The current scenario contract uses
`schema_version: 32`.

## Top-Level Shape

Required keys:

- `schema_version: 32`
- `scenario_id`
- `seed`
- `duration_scale`
- `library`
- `movies`
- `series`
- `artists`
- `timeline`

Optional keys:

- `profiles`

`seed` is an integer or `random`. `duration_scale` selects fixture timing scale.
`profiles` enables opt-in behavior that should be explicit in a fixture.

## Library Roots

`library.roots[*].path` values are authoring paths. At run time, every scenario
path resolves under `<run-dir>/library/`; containment validation rejects paths
that escape that directory after normalization or symlink resolution.

## Media Hierarchy

The scenario contract models movies, TV, and music as first-class branches.

Movie topology:

```text
movies -> variants -> bundle -> assets
```

TV topology:

```text
series -> seasons -> episodes -> variants -> bundle -> assets
```

Music topology:

```text
artists -> albums -> discs -> tracks -> variants -> bundle -> assets
```

Movies choose a `layout`, such as `movie_flat` or `movie_folder`. Series choose
a `layout` and `episode_naming`, then group episodes under seasons. Artists
choose a `layout` and `track_naming`, then group tracks under albums and discs.
Every playable movie, episode, and track owns one or more variants. Each variant
owns one bundle, and each bundle owns one or more assets. Assets define media
containers, duration, role, and track sources.

## Track Sources

Materialize-ready video source values:

- `mandelbrot`
- `color_bars`
- `solid_color`

`noise` is reserved in the schema for future synthesis support. Current
semantic validation rejects it with `E_MATERIALIZE_UNSUPPORTED`.

Materialize-ready video codecs are `h264`, `hevc`, and `h265`. The `hevc`
and `h265` aliases both require `ready_for.materialize_hevc_video`.
Materialize-ready video resolutions are `sd`, `hd`, and `1080p`.

Audio source values:

- `sine`
- `silence`
- `channel_tones`

Subtitle source values:

- `generated_srt`

## Minimal Scenario

This is a compact form of `tests/fixtures/scenarios/static-library.yaml`:

```yaml
schema_version: 32
scenario_id: static-library
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies:
  - id: w_movie
    title: Static Library Smoke Test
    layout: movie_flat
    variants:
      - id: va_hd
        label: hd
        bundle:
          id: b_hd
          assets:
            - id: a_hd_main
              role: main
              container: mkv
              duration_seconds: 2.0
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
series: []
artists: []
timeline: []
```

## Mutation Example

This pattern from `tests/fixtures/scenarios/delete-add-restore.yaml` deletes an
asset and later restores it at an explicit path:

```yaml
timeline:
  - id: delete_001
    at: 1s
    action: delete_file
    target: asset_main
  - id: add_001
    at: 2s
    action: add_file
    target: asset_main
    to: movies-hd/Orbit.mkv
```

## Timeline Actions

| action | required fields |
|--------|-----------------|
| `move_asset` | `target`, `to` |
| `rename_file` | `target`, `to` |
| `delete_file` | `target` |
| `add_file` | `target`, `to` |
| `reencode_video` | `target`, `resolution`, `codec` |
| `reencode_audio` | `target`, `from_channels`, `to_channels` |
| `create_sidecar` | `target`, `to`; `kind` defaults to `subtitle` (`subtitle`/`poster`/`nfo`/`cue`); `language` required for subtitle; `body` for `nfo`/`cue`; poster-only `media_type` and `image_format` (`png`/`jpeg`/`webp`, must match the `to:` extension) |
| `slow_copy_start` | `target`, `to`, `temp_path`, `duration` |
| `slow_copy_commit` | `for` |
| `archive_file` | `target` |
| `move_between_roots` | `target`, `from_root_id`, `to_root_id` |
| `remux_container` | `target`, `to_container` |
| `edit_metadata` | `target`, `fields` |
| `embed_subtitle` | `target`, `sidecar_path` |
| `extract_subtitle` | `target`, `to`, `language` |
| `remove_sidecar` | `target`, `sidecar_path` |
| `update_sidecar` | `target`, `sidecar_path` |
| `corrupt_container_header` | `target`; optional `bytes` defaults to `64` |
| `truncate_file` | `target`, `keep_bytes` |
| `corrupt_packet_range` | `target`, `packet_start`; optional `stream`, `packet_count` |
| `write_invalid_duration_metadata` | `target`; optional `value` |
| `corrupt_tags` | `target`, `flavor` (`null_bytes` / `malformed_frame`); optional `bytes` defaults to `64` |
| `touch_mtime` | `target`, `offset` |
| `wrong_oracle_hash` | `target` |
| `network_lag_start` | `effect`, `target`, `after`, `duration` |
| `network_lag_commit` | `for` |
| `change_permissions` | `target` (asset id or library path), `mode` (octal, e.g. `000`) |
| `simulate_quota_exceeded` | `target` (asset id) |
| `toggle_readonly` | `target` (asset id or library path), `mode` (`readonly`/`readwrite`) |
| `simulate_stale_handle` | `target` (asset id) |
| `unmount_path` | `target` (asset id or library path) |
| `remount_path` | `for` (the `unmount_path` event id) |
| `acquire_lock` | `target` (asset id), `lock_type` (`shared`/`exclusive`) |
| `release_lock` | `for` (the `acquire_lock` event id) |
| `renumber_episode` | `target`, `episode_number`; optional `absolute_number` |
| `move_episode_to_season` | `target`, `to_season`, `episode_number`; optional `absolute_number` |
| `rename_season` | `target`, `title` |
| `renumber_disc` | `target`, `disc_number` |
| `move_track_to_disc` | `target`, `to_disc`, `track_number` |
| `swap_episode_numbers` | `target`, `with_episode` (two same-season episodes exchange `episode_number`) |
| `swap_disc_numbers` | `target`, `with_disc` (two same-album discs exchange `disc_number`) |
| `swap_track_numbers` | `target`, `with_track` (two same-disc tracks exchange `track_number`) |
| `republish_episode` | `target` (podcast episode), `published_at` (UTC); optional `slug` — re-renders the episode's path and clears `stale` |
| `mark_episode_stale` | `target` (podcast episode) — records that the source feed dropped the episode while its file lingers on disk; the path is unchanged |

The `swap_*` actions are the sanctioned way to exchange two siblings' numbering:
a plain `renumber_*` into a number a sibling already holds is rejected
(`E_HIERARCHY_INVALID`), because the hierarchy engine does not perform implicit
swaps. A `swap_*` exchanges both numbers atomically — the two entities must be
distinct and share the same parent.

Timeline events are ordered by logical time and declaration order. Lifecycle
validation rejects operations that the engine cannot execute, such as adding an
already placed asset, moving a deleted asset, or committing an unpaired slow
copy.

## Profiles

Supported profile labels are:

- `malformed-media`
- `performance-smoke`
- `performance-scale`
- `performance-stress`
- `network-fs-lag`
- `network-fs-chaos`
- `filesystem-artifacts`
- `negative-oracle`

`corrupt_container_header` requires explicit opt-in:

```yaml
profiles:
  - malformed-media
```

Without the `malformed-media` profile, container-header corruption scenarios
fail validation. The other byte corruptors — `truncate_file`,
`corrupt_packet_range`, `write_invalid_duration_metadata`, and `corrupt_tags`
(malformed ID3 / null bytes in a tag region) — require the same opt-in.

Network filesystem lag events also require explicit opt-in:

```yaml
profiles:
  - network-fs-lag
```

`network_lag_start` uses `effect`, `target`, `after`, and `duration`.
`network_lag_commit` uses `for`. The start event must share the referenced
event's `at:` value and immediately follow it in declaration order.

The broader network-filesystem chaos actions require the `network-fs-chaos`
profile:

```yaml
profiles:
  - network-fs-chaos
```

`change_permissions` and `toggle_readonly` apply a real `chmod` under the run's
`library/` tree (restored when the run ends); `simulate_quota_exceeded`,
`simulate_stale_handle`, `acquire_lock`/`release_lock`, and
`unmount_path`/`remount_path` record neutral injected conditions
(`ENOSPC`/`ESTALE`/`EAGAIN`/unavailable) that a consumer's adapter interprets.
`release_lock` references its `acquire_lock` event id via `for`, and
`remount_path` references its `unmount_path` event id via `for`; the close event
must not precede its open in declaration order or in logical time.
