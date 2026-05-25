# Issues 94-95 HEVC And Validation Design

## Goal

Make static materialize media support explicit at validation time and add
first-class HEVC/H.265 synthesis for small deterministic CI fixtures.

## Context

Issue #94 reports that `validate` accepts static media values that
`materialize` later rejects, such as unsupported video resolutions and codecs.
Issue #95 asks for HEVC/H.265 synthesis so consumers can author no-op policy
fixtures without rewriting generated media outside Chaos Librarian.

The two issues conflict if implemented separately: #94 would reject `hevc`
until #95 lands, while #95 makes `hevc` part of the materialize matrix. This
cycle treats them as one matrix update.

## Design

Centralize the static media synthesis matrix in a neutral
`chaos_librarian.media_matrix` module so both validation and materializer code
can import it without creating a validation -> materializer dependency cycle.
The supported static video codec values become `h264`, `hevc`, and `h265`,
where `hevc` and `h265` both encode with FFmpeg `libx265`. Supported
resolutions remain `sd`, `hd`, and `1080p`; supported containers remain `mkv`
and `mp4`; supported video sources are the currently materializable built-in
sources; supported audio remains `aac`.

Add a validation semantic rule that walks declared assets and emits
`E_MATERIALIZE_UNSUPPORTED` errors on unsupported static materialize fields.
The rule reports locations at the same scenario fields materialize would have
reported, such as `video.source`, `video.resolution`, `video.codec`,
`audio[0].codec`, or `container`. To keep the shipped valid fixture corpus
clean, update plan-only fixtures that currently carry old unsupported
materialize values.

Expose HEVC readiness through capabilities by adding
`ready_for.materialize_hevc_video`. This bumps `capabilities.schema.json` to v3.
Capability detection checks whether the selected FFmpeg exposes `libx265`.
Materialize still requires baseline FFmpeg and ffprobe readiness, and HEVC
scenarios fail before run-dir allocation with a capability-gate error when
`libx265` is absent.

## Testing

Add validation tests and invalid fixtures for unsupported static media fields:

- `video.resolution: small` emits `E_MATERIALIZE_UNSUPPORTED` at the video
  resolution field;
- an unsupported codec such as `av1` emits `E_MATERIALIZE_UNSUPPORTED` at the
  video codec field;
- unsupported `video.source: noise` emits `E_MATERIALIZE_UNSUPPORTED` at the
  video source field;
- a valid HEVC MKV SD asset validates cleanly.

Add FFmpeg builder tests proving `hevc` and `h265` map to `libx265`.

Add capabilities tests proving `materialize_hevc_video` is true when `libx265`
is listed by FFmpeg encoders and false when it is absent. Update the
capabilities contract tests and exported schema for v3.

Add an integration test for the real-tool path that materializes an HEVC MKV SD
fixture when `ready_for.materialize_hevc_video` is true, then asserts the
manifest's probed video stream reports HEVC.

## Out Of Scope

Do not add application policy expectations. Do not add new content sources. Do
not add support for HEVC timeline re-encode as a separate feature; this cycle is
limited to declared static media synthesis.
