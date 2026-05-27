# Issue #132: Synthetic HDR Signaling

## Context

Issue #132 asks for deterministic HDR-signaled synthetic video without imported
real media. Current Scenario v15 can request SDR color-space and range flags,
but it cannot request HDR transfer characteristics, 10-bit HEVC encoding, or
HDR10 static metadata.

Local ffmpeg probes on 2026-05-26 confirmed a small reliable surface:

- HEVC/libx265 with `yuv420p10le` is required.
- `setparams=...:format=yuv420p10le` is required for probe-visible transfer
  and primary metadata on `smptebars` sources.
- HDR10 probes as `color_transfer=smpte2084`, `color_primaries=bt2020`,
  `color_space=bt2020nc`, `color_range=tv`, and frame side data containing
  mastering display plus content light level metadata.
- HLG probes as `color_transfer=arib-std-b67`, `color_primaries=bt2020`,
  `color_space=bt2020nc`, `color_range=tv`, and does not promise static HDR10
  side data.

## Decision

Add optional `hdr_mode` to `VideoTrack`:

```yaml
video:
  source: color_bars
  codec: hevc
  resolution: sd
  hdr_mode: hdr10
```

Contract values:

- `VideoHdrMode.HDR10 = "hdr10"`
- `VideoHdrMode.HLG = "hlg"`

HDR modes are HEVC-only in this slice. `h265` and `hevc` are both accepted
because the existing codec matrix maps both to libx265. H.264 HDR signaling,
AV1, Dolby Vision, custom mastering metadata, and perceptually meaningful HDR
imagery stay out of scope.

Because this changes the Scenario contract, bump Scenario schema version 15 to
16 and regenerate `schemas/scenario.schema.json`.

## Capability Reporting

Add `ReadyFor.materialize_hdr_video` and bump capabilities schema version 3 to
4. The flag is true only when:

- ffmpeg and ffprobe meet the existing minimum versions,
- ffmpeg advertises `libx265`,
- the `setparams` filter is available,
- `ffmpeg -h encoder=libx265` advertises `yuv420p10le`.

Content-source capability markers include `video:hdr:hdr10` and
`video:hdr:hlg` only when `materialize_hdr_video` is true. If the host lacks HDR
support, `capabilities --json` still reports the builtin provider but omits
those HDR markers and sets `ready_for.materialize_hdr_video` false.

## Materialization

`VideoSourceRequest` carries `hdr_mode`, and `_request_payload` includes it so
the recipe digest changes when the mode changes.

For HDR assets, `ffmpeg.build_command` emits:

- `-vf setparams=...:format=yuv420p10le`
- `-x265-params` with BT.2020 matrix/primaries, limited range, and the selected
  transfer function
- HDR10-only `hdr10=1`, mastering display metadata, and `max-cll=1000,400`

HDR command output owns color signaling. If `hdr_mode` is set, compatible
`color_space: bt2020` and `color_range: limited` are accepted but do not add
extra SDR color args.

## Validation And Preflight

Shape validation rejects unknown `hdr_mode` values. The materialize media matrix
rejects shape-valid HDR requests before allocation when:

- `codec` is not `hevc` or `h265`,
- `color_space` is present and is not `bt2020`,
- `color_range` is present and is not `limited`,
- `field_order` or `vfr_cadence` is present.

The combination restrictions keep the first HDR slice deterministic and avoid
untested interactions with interlaced/VFR filters or contradictory SDR color
metadata.

At materialize and wall-clock run startup, a scenario containing `hdr_mode` also
checks `caps.ready_for.materialize_hdr_video`. If false, the command exits
through the existing capability gate before creating the run directory. Replay
prefix materialization uses the same helper before synthesizing HDR sources.

## Testing

Focused tests cover:

- contract enum/default/accept/reject behavior and Scenario v16,
- capabilities schema v4 and the new ready flag,
- mocked capability detection for available and unavailable HDR support,
- provider sources with and without HDR markers,
- media-matrix rejection for unsupported HDR codec/color/range/VFR/interlaced
  combinations,
- ffmpeg argv for HDR10 and HLG,
- recipe digest changes by HDR mode,
- real materialize/ffprobe fixtures for HDR10 and HLG, including HDR10 frame
  side data.
