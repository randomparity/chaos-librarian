# Issue 135 Audio Layouts And Roles Design

## Context

Issue #135 is still present after the #134 audio-noise work. The scenario
contract supports `mono`, `stereo`, `2.1`, `5.1`, and `7.1`, but not `4.0`,
`LCR`, or `6.1`. `AudioTrack` has `language` but no author-facing role, and
the FFmpeg builder does not write audio role or title metadata.

This change extends the existing static media materializer. It does not add a
new provider, timeline action, free-form title field, or codec family.

## Contract

`AudioChannelLayout` gains:

- `4.0`
- `lcr`
- `6.1`

The author-facing `lcr` value maps to FFmpeg and ffprobe layout `3.0`
(`FL+FR+FC`). The enum member name is `LCR`; the wire value stays lowercase to
match the existing YAML style.

`AudioTrack` gains:

```python
role: AudioTrackRole = AudioTrackRole.MAIN
```

`AudioTrackRole` values:

- `main`
- `commentary`
- `alternate`

The default preserves existing fixtures and generated scenarios. Pydantic's enum
validation is the unsupported-value gate for both new channel layouts and roles.

## Materializer

Audio source recipes must produce the declared channel layout before muxing.
This is required because `-ac 3` turns LCR into `2.1`; relying on channel count
alone loses the author's intent.

The source recipe layer will expose:

- `AUDIO_FFMPEG_CHANNEL_LAYOUT_BY_NAME`
- `AUDIO_CHANNEL_ORDER_BY_NAME`

`sine` and `noise` will duplicate their mono source into the requested layout
with `pan=<layout>|<channel>=c0|...`. `silence` will pass the mapped layout to
`anullsrc`. `channel_tones` will use FFmpeg's `join` filter so each generated
tone lands in a specific channel.

The FFmpeg builder will emit per-audio-stream metadata in declaration order:

```text
-metadata:s:a:<index> language=<track.language>
-metadata:s:a:<index> title=<role-derived title>
-metadata:s:a:<index> handler_name=<role-derived title>
-metadata:s:a:<index> role=<track.role>
```

Role-derived titles:

- `main` -> `Main Audio`
- `commentary` -> `Commentary`
- `alternate` -> `Alternate Audio`

For commentary tracks the builder also emits:

```text
-disposition:a:<index> comment
```

MP4 keeps `language` and `handler_name`, but drops custom `role` and `title`
tags in local FFmpeg probes. MKV keeps `language`, `title`, and `ROLE`. Tests
will assert role/title metadata on MKV and only rely on language/order for MP4.

## Probe And Oracle Data

`ProbedStream` gains optional fields:

```python
channel_layout: str | None = None
title: str | None = None
role: str | None = None
```

The probe parser reads `channel_layout`, case-insensitive `role` tags, and
`title`. For audio streams only, `handler_name` is a fallback for `title` so MP4
audio titles survive as `SoundHandler` replacements without stamping
`VideoHandler` onto video streams. Adapter probe comparison includes these
fields so consumers can detect missing or wrong stream metadata.

`ContentSourceEvidence.track_index` already records generated audio track
indexes. New tests will assert a multi-audio fixture emits one evidence record
per declared audio track with indexes `0, 1, 2`.

## Schema Versions

The change updates schema-bearing contracts affected by the new fields:

- `SCENARIO_SCHEMA_VERSION`: `18 -> 19`
- `MANIFEST_SCHEMA_VERSION`: `7 -> 8`
- `ASSET_REPORT_SCHEMA_VERSION`: `7 -> 8`
- `OBSERVED_STATE_SCHEMA_VERSION`: `2 -> 3`

No replay-bundle or materialization schema bump is needed because
`ContentSourceEvidence` is not changing shape.

## Tests

Focused tests will cover:

- Scenario enum acceptance for `4.0`, `lcr`, and `6.1`.
- Scenario rejection of unknown role and channel-layout values.
- FFmpeg command metadata args for multiple audio streams.
- Recipe layout emission for `sine`, `noise`, `silence`, and `channel_tones`.
- Probe parsing for `channel_layout`, `title`, `handler_name`, and `ROLE`.
- Adapter probe comparison for channel layout, title, and role mismatches.
- A real MKV materialization fixture with three audio streams:
  - `4.0` main English
  - `lcr` commentary English
  - `stereo` alternate Spanish
- A real FLAC materialization fixture for `6.1`, because AAC in MKV/MP4 can
  encode seven channels while ffprobe omits `channel_layout`.

Final verification will run schema export, lint, format check, type check, and
the full pytest suite.
