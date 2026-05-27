# Issue 133 Resolution-Switching Video Design

## Goal

Add one deterministic materialize-supported video recipe that emits a valid file whose
single video stream changes resolution over time. The recipe is intentionally narrow:
H.264 video in an MPEG-TS container, switching from `sd` to `hd`.

## Context

Issue #133 asks for a mid-stream resolution change without expanding the normal
`resolution` enum. A direct FFmpeg `concat` filter cannot join differently sized raw
video streams; the filter rejects mismatched frame dimensions. A reliable local probe is:

1. Encode a short `640x480` H.264 MPEG-TS segment.
2. Encode a short `1280x720` H.264 MPEG-TS segment.
3. Concatenate both segments with FFmpeg's concat demuxer and `-c copy`.

`ffprobe -show_entries frame=width,height` then reports both `640x480` and `1280x720`
from the output stream.

## Contract

Add `VideoResolutionSequence` with one value:

- `sd_to_hd`

Add `VideoTrack.resolution_sequence: VideoResolutionSequence | None = None`.
`resolution` remains required by the current contract and must equal the first segment
resolution (`sd`) when `resolution_sequence: sd_to_hd` is set. This keeps the existing
static-resolution field meaningful while the separate sequence field requests the
dynamic recipe.

Because `VideoTrack` changes, bump `SCENARIO_SCHEMA_VERSION` to 17 and regenerate
`schemas/scenario.schema.json`.

## Supported Combination

The first recipe supports exactly:

- `container: ts`
- `video.codec: h264`
- `video.source: color_bars`
- `video.resolution: sd`
- `video.resolution_sequence: sd_to_hd`
- no audio tracks
- no subtitle tracks
- no `vfr_cadence`, `field_order`, `color_space`, `color_range`, or `hdr_mode`

This avoids conflating resolution switching with VFR, interlacing, SDR color signaling,
HDR signaling, audio concat, or subtitle handling. Those combinations should fail
semantic validation before materialization.

## Capabilities

Add `ReadyFor.materialize_resolution_switch_video` and bump
`CAPABILITIES_SCHEMA_VERSION` to 5. Capability detection should report true only when:

- FFmpeg and FFprobe meet the current minimum versions.
- FFmpeg advertises the `libx264` encoder.

The built-in content-source provider should advertise
`video:resolution_sequence:sd_to_hd` only when the capability is true.

Materialize, wall-clock run, and run replay should gate scenarios that request
`resolution_sequence` before run directory allocation. The gate should raise
`CapabilityGateError` with `field="ready_for.materialize_resolution_switch_video"`.

## Materialization

Normal video synthesis stays unchanged. `materialize_one_asset` should branch only when
`asset.video.resolution_sequence is not None`.

The resolution-switch branch should:

1. Create a temporary work directory under the rendered asset's output directory.
2. Resolve content-source evidence once using a `VideoSourceRequest` that includes
   `resolution_sequence`.
3. Generate one MPEG-TS segment per resolution in the sequence with `libx264`.
4. Write a concat-demuxer list file.
5. Run FFmpeg with `-f concat -safe 0 -i <list> -c copy` to produce the final `.ts`.
6. Probe and hash the final output exactly like normal synthesis.

`MaterializationReport.invocations` should retain every successful FFmpeg command in
order. `MaterializedAsset.invocation_index` should point at the final concat command.

## Replay Evidence

Extend `VideoSourceRequest`, `ContentSourceEvidence`, and the content-source recipe
digest payload with `resolution_sequence`. This makes replay evidence explicitly record
the selected sequence and makes the digest change when the selected sequence changes.

Because `ContentSourceEvidence` is embedded in materialization reports and run replay
bundles, bump `MATERIALIZATION_SCHEMA_VERSION` to 11 and `REPLAY_BUNDLE_SCHEMA_VERSION`
to 9, then regenerate the matching schemas.

## Tests

Add tests for:

- Scenario v17 contract accepts and rejects `resolution_sequence` values.
- Capabilities v5 includes `materialize_resolution_switch_video` and the content-source
  marker only when available.
- Semantic validation accepts the exact supported combination and rejects unsupported
  container, codec, source, audio, subtitle, and incompatible video modes.
- Materialize/run/replay entry points reject `resolution_sequence` when the capability
  flag is false.
- FFmpeg command builders produce deterministic segment and concat commands.
- Content-source evidence records `resolution_sequence`, and the recipe digest changes
  when `resolution_sequence` changes.
- A real FFmpeg integration test materializes the fixture and asserts ffprobe frame
  metadata includes both `640x480` and `1280x720`.

## Non-Goals

- No general resolution enum expansion.
- No arbitrary resolution list in the first implementation.
- No support for MP4 or MKV resolution-switch outputs.
- No audio, subtitles, VFR, interlacing, color signaling, or HDR signaling combined with
  resolution switching.
