# Materializer

`detect_capabilities` checks ffmpeg, ffprobe, and mkvmerge and derives readiness
flags for static media generation, filesystem mutations, and media mutations.

Static materialization requires ffmpeg and ffprobe. Full media mutation
readiness also requires mkvmerge because some timeline effects need container
tooling beyond ffmpeg synthesis.

`content_sources.py` maps scenario source names to deterministic content-source
providers. ffmpeg recipe helpers turn `mandelbrot`, `color_bars`,
`solid_color`, `sine`, `silence`, and `channel_tones` into repeatable media
inputs. `noise` validates but is not materialize-ready.

`materialize_scenario` shares the validation and timeline planning path with
plan mode. After capability checks, phase A writes declared media and sidecars,
probes output, hashes bytes, and stamps manifest metadata.

Phase B applies timeline effects that require real files:

- Filesystem actions such as move, rename, delete, add, archive, and slow copy.
- Media actions such as re-encode, remux, metadata edit, and subtitle changes.
- Sidecar byte updates.
- Malformed-media corruption actions.

Wall-clock mode shares validation and timeline semantics with materialize. It
publishes a baseline run directory, schedules due events by logical time scaled
by `--speed`, appends wall-clock journal rows, and finalizes a run replay bundle
for the applied prefix.
