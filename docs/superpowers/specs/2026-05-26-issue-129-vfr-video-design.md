# Issue 129 VFR Video Recipe Design

## Goal

Add deterministic variable-frame-rate video fixtures while preserving the current
constant-frame-rate behavior for scenarios that do not opt in.

## Scope

Issue #129 adds one optional field to `VideoTrack`:

```yaml
video:
  source: color_bars
  codec: h264
  resolution: hd
  vfr_cadence: 24_to_30
```

`vfr_cadence` is omitted for the existing CFR behavior. Supported values are
`24_to_30`, `30_to_60`, and `24_30_60`. Unknown values fail during scenario
validation before any materialize run directory is allocated.

## Architecture

The scenario contract gains a `VideoVfrCadence` enum and an optional
`VideoTrack.vfr_cadence`. This changes the scenario schema, so
`SCENARIO_SCHEMA_VERSION` moves from 12 to 13 and checked-in schemas/fixtures are
regenerated.

Phase-A synthesis keeps the existing content-source provider. When
`vfr_cadence` is absent, `resolve_video_source()` calls the existing video recipe
with the existing 24 fps request. When `vfr_cadence` is present, the provider
calls the same source recipe at a deterministic 120 fps base rate and appends a
lavfi `select` filter that preserves source PTS while selecting frame intervals:

| Cadence | Segment plan |
| --- | --- |
| `24_to_30` | first half selects every 5th 120 fps frame, second half every 4th |
| `30_to_60` | first half selects every 4th 120 fps frame, second half every 2nd |
| `24_30_60` | thirds select every 5th, 4th, then 2nd frame |

The output remains a single lavfi input, so `ffmpeg.build_command()` does not need
multi-video-input support. The existing codec/container matrix still applies.

## Evidence And Capabilities

The content-source recipe digest includes the selected cadence by adding
`vfr_cadence` to the video request payload. The generated lavfi input also
differs, giving replay comparison two deterministic drift signals.

`capabilities --json` continues to use the existing content-source provider shape
and adds these source markers:

- `video:vfr:24_to_30`
- `video:vfr:30_to_60`
- `video:vfr:24_30_60`

This avoids a capabilities schema bump while making VFR support visible to agents
and CI jobs that inspect provider sources.

## Validation

Pydantic shape validation rejects unknown cadence strings through the enum. The
materialize media matrix continues to reject unsupported containers, codecs, and
resolutions. VFR does not introduce additional codec/container exclusions in this
slice because the implementation stays inside the existing lavfi + encoder path
for `mkv` and `mp4`.

## Testing

Contract tests cover enum values, default omission, invalid cadence rejection, and
schema version 13. Content-source tests verify that VFR changes the recipe digest
and capabilities source list. Recipe tests verify the generated lavfi select
filters for each supported cadence.

Integration tests materialize one fixture per supported cadence and run ffprobe
against packet PTS values. Each VFR file must expose more than one packet interval,
which proves it is not a plain CFR file. The integration test is skipped under
the same ffmpeg/ffprobe gate as the existing real materialize tests.

## Out Of Scope

This issue does not add interlacing, SDR/HDR color signaling, mid-stream
resolution changes, audio recipe changes, container muxing profiles, embedded
chapters, cover art, or subtitle recipe variants.
