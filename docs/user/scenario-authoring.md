# Scenario Authoring

A scenario is YAML that describes a synthetic media library, deterministic
inputs, and optional timeline mutations. The current scenario contract uses
`schema_version: 8`.

## Top-Level Shape

Required keys:

- `schema_version: 8`
- `scenario_id`
- `seed`
- `duration_scale`
- `library`
- `works`
- `timeline`

Optional keys:

- `profiles`

`seed` is an integer or `random`. `duration_scale` selects fixture timing scale.
`profiles` enables opt-in behavior that should be explicit in a fixture.

## Library Roots

`library.roots[*].path` values are authoring paths. At run time, every scenario
path resolves under `<run-dir>/library/`; containment validation rejects paths
that escape that directory after normalization or symlink resolution.

## Work Topology

The object hierarchy is:

```text
works -> variants -> bundle -> assets
```

Each work owns one or more variants. Each variant owns one bundle. Each bundle
owns one or more assets. Assets define media containers, duration, role, and
track sources.

## Track Sources

Video source values:

- `mandelbrot`
- `color_bars`
- `solid_color`
- `noise`

Audio source values:

- `sine`
- `silence`
- `channel_tones`

Subtitle source values:

- `generated_srt`

`noise` validates as a scenario source but is not materialize-ready. Use it only
for plan-only fixtures until materializer support exists.

## Minimal Scenario

This is a compact form of `tests/fixtures/scenarios/static-library.yaml`:

```yaml
schema_version: 8
scenario_id: static-library
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
works:
  - id: w_movie
    title: Static Library Smoke Test
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
| `create_sidecar` | `target`, `to`; `language` required for subtitle sidecars; `kind` defaults to `subtitle` |
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

`corrupt_container_header` requires explicit opt-in:

```yaml
profiles:
  - malformed-media
```

Without the `malformed-media` profile, malformed-media corruption scenarios fail
validation.

Network filesystem lag events also require explicit opt-in:

```yaml
profiles:
  - network-fs-lag
```

`network_lag_start` uses `effect`, `target`, `after`, and `duration`.
`network_lag_commit` uses `for`. The start event must share the referenced
event's `at:` value and immediately follow it in declaration order.
