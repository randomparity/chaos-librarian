# Issue 134 Audio Noise And Sample-Format Recipes Design

## Goal

Add deterministic audio recipe controls for noise color, sample rate, and
probe-verifiable sample format while keeping the first implementation inside a small
materialize-valid matrix.

## Current State

Audio tracks currently support `sine`, `silence`, and `channel_tones`. All built-in
recipes emit 48 kHz inputs, and the scenario contract has no way to request a sample
rate, noise color, or sample format. Audio-only materialization supports `flac`, `mp3`,
and `m4a`; video-backed audio supports AAC. Content-source evidence records the source
and channel layout indirectly through the digest payload, but not the user-selected
audio parameters.

Local FFmpeg checks show:

- `anoisesrc` supports deterministic `white`, `pink`, and `brown` noise with a seed.
- AAC preserves 8000, 22050, 44100, 48000, 88200, and 96000 Hz.
- MP3 silently resamples 88200 and 96000 Hz to 48000 Hz, so those rates must be
  rejected for `mp3`.
- WAV PCM reports `pcm_s16le/s16`, `pcm_s24le/s32` with 24 raw bits, and
  `pcm_f32le/flt` reliably through ffprobe.
- FLAC reports 16-bit and 24-bit reliably; 32-bit float is not a FLAC output.

## Contract

Add these author-facing fields to `AudioTrack`:

- `source: AudioSource = AudioSource.SINE`, extended with `NOISE = "noise"`.
- `noise_color: AudioNoiseColor | None = None`, values `white`, `pink`, `brown`.
- `sample_rate: Literal[8000, 22050, 44100, 48000, 88200, 96000] = 48000`.
- `sample_format: AudioSampleFormat | None = None`, values `s16`, `s24`, `flt`.

`noise_color` is required when `source: noise` and forbidden for non-noise sources.
`sample_format` stays optional so existing fixtures keep their historical encoder
defaults. Because `AudioTrack` changes, bump `SCENARIO_SCHEMA_VERSION` to 18 and
regenerate `schemas/scenario.schema.json`.

## Supported Matrix

Noise sources are supported anywhere the existing audio source can be materialized.
Sample-rate support is codec-dependent:

- `aac`, `flac`, and WAV PCM codecs support all six listed rates.
- `mp3` supports 8000, 22050, 44100, and 48000 Hz only.

Sample-format support is intentionally limited to outputs where ffprobe reports the
selected format or bit depth:

- `container: flac`, `codec: flac`: `sample_format: s16` or `s24`.
- `container: wav`, `codec: pcm_s16le`: `sample_format: s16`.
- `container: wav`, `codec: pcm_s24le`: `sample_format: s24`.
- `container: wav`, `codec: pcm_f32le`: `sample_format: flt`.

`sample_format` is rejected for AAC and MP3 because those encoders do not preserve the
requested author-facing format in a probe-verifiable way. WAV is added as an audio-only
container because it is the smallest reliable way to cover 32-bit float.

## Validation

Semantic validation should reject unsupported combinations before materialization:

- `source: noise` without `noise_color`
- `noise_color` on any non-noise source
- sample rates outside the codec matrix, especially MP3 at 88200 or 96000 Hz
- `sample_format` on AAC or MP3
- FLAC `sample_format: flt`
- WAV codec/sample-format mismatches

Validation should report `E_MATERIALIZE_UNSUPPORTED` at the most specific offending
field. Shape validation handles non-enum `audio.source`, `noise_color`, `sample_rate`,
and `sample_format` values introduced by the Pydantic contract.

## Materialization

Audio recipe functions should accept `sample_rate`, `sample_format`, and
`noise_color`. The lavfi source should use the requested sample rate. When
`sample_format` is set, the recipe input should add an `aformat` filter using the
corresponding FFmpeg sample format (`s16`, `s32` for author-facing `s24`, `flt`).

FFmpeg output arguments should be generated per audio stream:

- `-c:a:<index> <encoder>`
- `-ar:a:<index> <sample_rate>`
- `-sample_fmt:a:<index> <ffmpeg_sample_fmt>` only when `sample_format` is set

Audio-only WAV uses the declared PCM codec directly. Existing AAC, FLAC, MP3, and video
recipes keep their behavior when the new fields are omitted.

## Capabilities And Evidence

Add `ReadyFor.materialize_audio_recipes` and bump `CAPABILITIES_SCHEMA_VERSION` to 6.
The flag is true when FFmpeg and FFprobe meet minimum versions and FFmpeg advertises the
`anoisesrc` filter.

The built-in content-source provider should advertise `audio:noise` and the new audio
modifier markers only when the audio recipe capability is available:

- `audio:noise`
- `audio:noise:white`, `audio:noise:pink`, `audio:noise:brown`
- `audio:sample_rate:<rate>` for each supported rate
- `audio:sample_format:s16`, `audio:sample_format:s24`, `audio:sample_format:flt`

Extend `AudioSourceRequest`, `ContentSourceEvidence`, and the recipe digest payload with
`noise_color`, `sample_rate`, and `sample_format`. Because `ContentSourceEvidence` is
embedded in materialization reports and replay bundles, bump
`MATERIALIZATION_SCHEMA_VERSION` to 12 and `REPLAY_BUNDLE_SCHEMA_VERSION` to 10, then
regenerate the matching schemas.

Materialize, wall-clock run, and run replay should gate scenarios that request
`source: noise` before run directory allocation when
`ready_for.materialize_audio_recipes` is false. Sample-rate and sample-format requests
do not need this gate; they are covered by the static FFmpeg/FFprobe gate plus the
validation matrix.

## Tests

Add tests for:

- Scenario v18 accepts the new audio fields, preserves defaults, and rejects invalid
  `noise_color` pairings.
- Content-source evidence records `noise_color`, `sample_rate`, and `sample_format`,
  and the digest changes when each parameter changes.
- Capabilities v6 includes `materialize_audio_recipes` and the provider markers only
  when `anoisesrc` is available.
- Materialize/run/replay entry points reject `source: noise` when
  `materialize_audio_recipes` is false.
- Semantic validation accepts representative valid AAC, FLAC, MP3, and WAV cells and
  rejects unsupported rate/format combinations.
- FFmpeg command builders emit per-stream `-ar` and `-sample_fmt` arguments.
- A real FFmpeg integration test materializes representative files and asserts raw
  ffprobe metadata for sample rate, codec, sample format, or bit depth.
- Schema export has no drift after version bumps.

## Non-Goals

- No commentary roles or expanded channel layouts; issue #135 owns that work.
- No arbitrary sample rates outside the six accepted values.
- No sample-format guarantees for AAC or MP3.
- No manifest `ProbedStream` schema expansion; integration tests can inspect raw
  ffprobe metadata for sample format and bit depth.
