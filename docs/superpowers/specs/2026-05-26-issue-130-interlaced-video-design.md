# Issue #130: Interlaced Video Recipe Support

## Context

Issue #130 asks for deterministic interlaced video recipes with explicit
top-field-first and bottom-field-first authoring. Current Scenario v13 video
tracks can choose source, codec, resolution, and optional VFR cadence, but all
materialized video is progressive.

Local ffmpeg probes on 2026-05-26 confirmed that h264 and hevc outputs report
interlaced field order when the lavfi source is generated at double rate,
wrapped with `tinterlace`, marked with `setfield`, and encoded with the matching
codec parameter:

- h264 + Matroska: `field_order=tb` / `bt`
- hevc + Matroska: `field_order=tb` / `bt`
- h264 + MP4: `field_order=tt` / `bb`
- hevc + MP4: `field_order=tb` / `bt`

The implementation will assert interlaced output using Matroska in real
integration tests so the expected probe values stay stable.

## Decision

Add optional `field_order` to `VideoTrack`:

```yaml
video:
  source: color_bars
  codec: h264
  resolution: sd
  field_order: top_field_first
```

Contract values:

- `top_field_first`
- `bottom_field_first`

Unset remains progressive and preserves existing scenario behavior.

Because this changes the Scenario contract, bump `SCENARIO_SCHEMA_VERSION` from
13 to 14 and regenerate `schemas/scenario.schema.json`.

## Materialization

Extend `VideoSourceRequest` with `field_order`. The builtin lavfi provider will:

1. Generate interlaced requests at `fps * 2`.
2. Append `tinterlace=mode=interleave_top,setfield=tff` for
   `top_field_first`.
3. Append `tinterlace=mode=interleave_bottom,setfield=bff` for
   `bottom_field_first`.
4. Preserve the existing VFR wrapping behavior for VFR-only requests.
5. Fail loudly if both `field_order` and `vfr_cadence` are set, matching the
   semantic validation rule and preventing undefined timing behavior in direct
   provider calls.

The ffmpeg argv builder will add codec-specific output parameters when
`field_order` is present:

- h264/libx264: `-x264-params tff=1` or `bff=1`
- h265/hevc/libx265: `-x265-params interlace=tff` or `interlace=bff`

The recipe digest payload will include `field_order`, so replay evidence changes
when the field order changes.

## Validation

Pydantic shape validation rejects unknown `field_order` values. Semantic
materialize validation will reject:

- `field_order` combined with `vfr_cadence`; VFR/interlaced timing composition is
  out of scope for #130.
- Any future codec or container outside the explicit interlaced support matrix.
  For the current media matrix, all existing video codecs (`h264`, `h265`,
  `hevc`) and containers (`mkv`, `mp4`) are supported.

## Capabilities

Expose interlaced recipe support as content-source capability markers:

- `video:interlaced:top_field_first`
- `video:interlaced:bottom_field_first`

These sit beside existing `video:*` and `video:vfr:*` markers.

## Acceptance Tests

- Contract tests for enum values, default progressive behavior, accepted field
  orders, rejected unknown values, and Scenario v14 constant.
- Schema export drift test after regeneration.
- Media matrix test for a clean interlaced video scenario.
- Media matrix test rejecting `field_order` + `vfr_cadence`.
- Content-source tests for double-rate input, tinterlace/setfield filters,
  capability markers, and digest differences by field order.
- FFmpeg argv tests for h264 and hevc interlace parameters.
- Real materialize integration tests for both field orders using ffprobe
  `stream.field_order`.

## Out Of Scope

No VFR/interlaced combination, HDR/color metadata, mid-stream resolution
switching, deinterlacing, or intentionally malformed interlace signaling.
