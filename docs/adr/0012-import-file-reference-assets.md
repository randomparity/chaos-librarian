# ADR 0012: Import assets materialize by copying scenario-bundled originals

## Status

Accepted

## Context

Issue #105 asks for an `import` command that scans an existing media library and
produces a scenario YAML whose materialized output reproduces the probed media
properties. Today every asset is synthesized through the FFmpeg lavfi matrix
(`media_matrix.py`); the contract has no way to say "this asset is that file".
Two hard boundaries shape any solution:

- **Containment** (`contract/paths.py`, design spec "Filesystem Safety"): every
  scenario path must resolve strictly under `<run-dir>/library/`. Nothing today
  references a file outside the run dir; the only sanctioned escape
  (`SymlinkTarget.to_run_dir_path`) is still run-dir-scoped.
- **The synthesis matrix** (`rule_materialize_media_matrix`,
  `E_MATERIALIZE_UNSUPPORTED`): declared codecs, containers, resolutions, and
  sample rates are limited to what lavfi can synthesize. Real libraries carry
  mpeg2 rips, 4K video, odd sample rates, and stream layouts no enum here
  describes.

The manifest oracle records `probed` from the *actual* probe of the materialized
file (`materialize_one_asset` → `probe_file`), not from declared tracks, so
expected-vs-observed comparison never depended on restating properties in YAML.

## Decision

Import is **snapshot-based**. `chaos-librarian import` copies each probed
original into a content-addressed media bundle beside the emitted scenario
(`<out-dir>/media/<sha256>.<container>`) and the scenario references those
copies:

- `Asset` gains `import_source: ImportSource | None` (`ImportSource.path` is a
  scenario-dir-relative path with safe components, resolving to a strict
  subpath of the scenario's directory). Mutually exclusive with the four
  existing link fields.
- An import asset declares **no synthesis tracks** (`video=None`,
  `audio=()`, `subtitles=()`) and no synthesis knobs (`mp4_moov_placement`,
  `matroska_muxing_profile`, `embedded_chapters`, `embedded_cover_art`). The
  probed properties — codecs, resolution, stream layout, chapters, cover art —
  are preserved by construction, because the materialized bytes *are* the
  original bytes. The required `container` and `duration_seconds` fields are
  populated from the probe and the bundle extension; they are recorded
  metadata only — materialization and oracle comparison read the actual
  copied bytes, never these declarations.
- Phase A dispatches import assets to a copy path modeled on
  `_copy_same_content_asset`: resolve the bundle path (containment-checked
  against the scenario dir), `shutil.copyfile` into the library, sha256,
  `probe_file`, `ContentSourceEvidence(provider="import-file")`.
- Detected sidecars: `.srt`/`.ass`/`.ssa` become `create_sidecar(subtitle)`
  events carrying the original text in `body` (body is widened to subtitle
  kind); `.nfo`/`.cue` use the existing `body` support; posters are
  represented as synthesized `create_sidecar(poster)` events (detected and
  represented, not byte-exact). The default timeline therefore contains
  sidecar-creation events only — no media mutations.
- Timeline events `reencode_video`, `reencode_audio`, `remux_container`,
  `embed_subtitle`, and `extract_subtitle` are rejected on import assets
  (`E_MATERIALIZE_UNSUPPORTED`). judgment: their handlers and validation
  rules were built and tested against synthesized assets whose declared
  tracks speak the matrix vocabulary; import assets declare none, so these
  events are unvalidated territory (mechanically some handlers would run,
  but no validation rule grounds them on a declaration-free asset).
  This is a closed classification: every other timeline action operates on
  existing bytes without consulting track declarations and remains allowed.
  Widening the rejected set is future work.
- `SCENARIO_SCHEMA_VERSION` bumps 32 → 33; `schemas/scenario.schema.json` is
  regenerated; the new `import` command is added to `docs/contract/cli-reference.md`.

## Consequences

- Storage: a scenario bundle duplicates the imported bytes, and a
  materialized run copies the bundle into `<run-dir>/library/`, so an
  imported corpus exists roughly three times (originals + bundle + library).
  A scenario directory is self-contained and replayable on any machine;
  `--max-duration-s`, `--max-works`, and `--mode sample|dedup` bound bundle
  size at import time.
- Fidelity is exact, not "within tolerance": duration, codecs, resolution, and
  stream layout match the original bit-for-bit. The existing 0.05 s duration
  tolerance in `adapter/probe.py` still applies to post-materialization probes.
- Import assets need no media-matrix coverage: `rule_materialize_media_matrix`
  early-returns for import assets (skipping its must-declare-video and audio
  cardinality checks, which would otherwise reject a track-less asset), and
  gains only the declared-track-event rejection above.
- A scenario referencing a moved/deleted bundle fails at materialize time with
  a missing-input error, like any unreadable input.
- The `import` keyword cannot name a Python module; the CLI command module is
  `cli/commands/import_media.py` registering the `import` command name.

## Considered & rejected

- **Do nothing (synthesis-only, no import command).** excluded by the frozen
  issue #105 outcome, which requires the import command; synthesis-only
  cannot reproduce the probed properties of real files at all.
- **Reference originals in place (absolute or external paths).** verified:
  `contract/paths.py` `resolve_under_library` and the design spec's Filesystem
  Safety section require strict library containment, and no scenario field may
  reference outside the run dir (`rule_symlink_target_escape` is the only
  sanctioned escape and is run-dir-scoped). In-place references would also
  make scenarios non-portable and let an untrusted YAML read arbitrary files.
- **Map probed properties onto the nearest synthesizable profile.** verified:
  `media_matrix.py` supports video `{h264, h265/hevc, vp9}` across containers
  `{mkv, mp4, webm}`, audio `{aac, flac, mp3, pcm_s16le, pcm_s24le,
  pcm_f32le}`, resolutions `sd|hd|1080p`, and sample rates
  `{8000, 22050, 44100, 48000, 88200, 96000}`; a 4K HEVC file or a 32 kHz
  track has no representation, so acceptance criterion 3 (materialized output
  matches probed properties) fails for exactly the quirky files the issue
  exists to test.
- **Stage originals inside the run dir** (following the `to_run_dir_path`
  precedent). judgment: forces a two-step contract where the user must place a
  generated bundle inside `--out` before `materialize` runs; a scenario-dir
  bundle keeps the flow one-command and the anchor for path validation is the
  scenario file's own directory.
- **Declare per-track `file_ref` source enum members on import assets.**
  judgment: restates properties the bytes already carry, creating a second
  source of truth that can drift from reality and re-opening every
  matrix/enum constraint (channel layouts, sample rates, subtitle codecs) the
  snapshot design exists to avoid.
- **Stage the bundle as hardlinks or symlinks instead of copies** (machinery
  precedent: `_hardlink_asset`, ADR 0005). verified: `os.link` fails with
  `EXDEV` across filesystems (POSIX), and the run dir is chosen at
  materialize time, so same-filesystem staging cannot be guaranteed; a
  hardlink bundle also cannot be moved between machines, which scenario
  bundles (circulating fixtures) must survive. judgment: copies always work
  at the cost of disk.
