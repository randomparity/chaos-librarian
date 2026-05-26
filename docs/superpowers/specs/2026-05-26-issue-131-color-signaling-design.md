# Issue #131: SDR Color-Space And Range Signaling

## Context

Issue #131 asks for deterministic video fixtures that vary probe-visible SDR
color metadata. Current Scenario v14 video tracks can request VFR cadence and
interlaced field order, but they cannot request color-space or full-vs-limited
range signaling.

Local ffmpeg probes on 2026-05-26 confirmed that output-side `-colorspace` and
`-color_range` flags are reliably visible through ffprobe for both libx264 and
libx265:

- `bt709` probes as `color_space=bt709`
- BT.601 mapped to ffmpeg `smpte170m` probes as `color_space=smpte170m`
- BT.2020 mapped to ffmpeg `bt2020nc` probes as `color_space=bt2020nc`
- `limited` mapped to ffmpeg `tv` probes as `color_range=tv`
- `full` mapped to ffmpeg `pc` probes as `color_range=pc`

## Decision

Add optional `color_space` and `color_range` fields to `VideoTrack`:

```yaml
video:
  source: color_bars
  codec: h264
  resolution: sd
  color_space: bt709
  color_range: full
```

Contract values:

- `VideoColorSpace`: `bt601`, `bt709`, `bt2020`
- `VideoColorRange`: `limited`, `full`

Unset fields preserve current encoder defaults. Because this changes the
Scenario contract, bump `SCENARIO_SCHEMA_VERSION` from 14 to 15 and regenerate
`schemas/scenario.schema.json`.

## Materialization

Color signaling is output metadata, not a new lavfi source. The materializer
will:

1. Pass `video.color_space` and `video.color_range` through `VideoSourceRequest`
   so replay evidence changes when either value changes.
2. Add content-source capability markers:
   - `video:color_space:bt601`
   - `video:color_space:bt709`
   - `video:color_space:bt2020`
   - `video:color_range:limited`
   - `video:color_range:full`
3. Add ffmpeg output args in `build_command` when values are present:
   - `bt601` -> `-colorspace smpte170m`
   - `bt709` -> `-colorspace bt709`
   - `bt2020` -> `-colorspace bt2020nc`
   - `limited` -> `-color_range tv`
   - `full` -> `-color_range pc`

## Validation

Pydantic shape validation rejects unknown `color_space` and `color_range`
values before materialization. The existing media matrix continues to reject
unsupported codecs and containers. There are no additional unsupported SDR
color-space/range combinations in the current first slice.

## Out Of Scope

Do not add color primaries, transfer characteristics, mastering metadata, bit
depth changes, HDR10, or HLG. Those belong to #132 because they have different
probe expectations and codec requirements.
