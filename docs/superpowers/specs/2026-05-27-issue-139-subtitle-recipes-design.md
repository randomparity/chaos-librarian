# Subtitle Encoding, Styling, and Timing Recipes Design

## Problem

Issue #139 asks for deterministic subtitle sidecar variants beyond the current
single `generated_srt` UTF-8 SRT payload. The current contract can only request
`source: generated_srt`, `codec: srt`, and `mode: sidecar`; materialization then
writes one simple UTF-8 text file per declared sidecar subtitle. That does not
exercise parser behavior around encodings, ASS/SSA styling syntax, overlapping
cues, out-of-range cue durations, or multiple simultaneous subtitle sidecars.

## Scope

This issue implements declared sidecar subtitle recipes only. Embedded subtitle
muxing stays out of scope, matching the GitHub issue. Timeline-created subtitle
sidecars continue to use the existing default generated SRT recipe because
`create_sidecar` and `update_sidecar` events do not currently carry recipe
fields; adding recipe-bearing timeline events is a separate contract design.
Timeline `update_sidecar` and `embed_subtitle` operations are therefore valid
only for default generated UTF-8 SRT sidecars. Validation rejects those timeline
operations when they target a declared sidecar with ASS/SSA, non-UTF-8 encoding,
or timing-chaos settings.

The implementation adds deterministic, materialize-valid sidecar outputs for:

- SRT with UTF-8, UTF-8 with BOM, UTF-16 LE with BOM, and ISO-8859-1.
- ASS and SSA styled subtitles with deterministic style, alignment, and
  positioning override tags.
- Timing profiles named `normal`, `overlap`, and `out_of_range`.

## Contract

Add explicit scenario enums:

- `SubtitleCodec`: `srt`, `ass`, `ssa`
- `SubtitleEncoding`: `utf8`, `utf8_bom`, `utf16_le`, `iso_8859_1`
- `SubtitleTimingProfile`: `normal`, `overlap`, `out_of_range`

Extend `SubtitleSource` with `styled_ass`. Keep `generated_srt` as the default
source for backward compatibility.

Change `SubtitleTrack.codec` from `str` to `SubtitleCodec` and add:

```python
encoding: SubtitleEncoding = SubtitleEncoding.UTF8
timing_profile: SubtitleTimingProfile = SubtitleTimingProfile.NORMAL
```

Scenario schema bumps from v22 to v23. No manifest, materialization,
capabilities, report, observed-state, or replay-bundle schema bump is needed:
the sidecar path and content hash already carry the observable output, and no
new non-scenario report fields are added.

## Validation Matrix

Validation and materializer preflight enforce the same recipe matrix:

| codec | source | supported encodings | timing profiles |
| --- | --- | --- | --- |
| `srt` | `generated_srt` | `utf8`, `utf8_bom`, `utf16_le`, `iso_8859_1` | all |
| `ass` | `styled_ass` | `utf8`, `utf8_bom` | all |
| `ssa` | `styled_ass` | `utf8`, `utf8_bom` | all |

Invalid combinations are materialize-unsupported errors, not silent fallback:

- `styled_ass` with `codec: srt`
- `generated_srt` with `codec: ass` or `codec: ssa`
- `iso_8859_1` or `utf16_le` for ASS/SSA
- any non-sidecar subtitle mode in static materialization
- `update_sidecar` or `embed_subtitle` targeting a declared sidecar whose
  recipe is not the default `codec: srt`, `source: generated_srt`,
  `encoding: utf8`, `timing_profile: normal`

`overlap` and `out_of_range` are intentionally parser-surprising but valid
recipes. The explicit `timing_profile` field is the opt-in gate, so they do not
need the malformed-media profile.

## Materialization

Create `src/chaos_librarian/materializer/tooling/subtitles.py` for pure subtitle
recipe rendering:

- `subtitle_payload_bytes(...)` renders and encodes a payload for one declared
  subtitle track.
- SRT rendering emits one normal cue, two overlapping cues, or one cue whose end
  time exceeds the asset duration depending on `timing_profile`.
- ASS/SSA rendering emits `[Script Info]`, `[V4+ Styles]` or `[V4 Styles]`,
  `[Events]`, deterministic style rows, and dialogue lines with positioning
  override tags.
- Encoding is applied after rendering, with BOM bytes included for
  `utf8_bom` and `utf16_le`.

`srt_payload` remains in `materializer/tooling/recipes.py` for existing callers
and tests. New declared subtitle materialization uses the new subtitle recipe
module so byte encoding is explicit and content hashes are computed from bytes,
not text.

## Paths

Declared sidecar paths should reflect the subtitle codec. Extend
`render_declared_sidecar_path(media_path, language, codec="srt")` and update
callers that know a declared `SubtitleTrack` to pass the codec. Existing callers
that do not know a codec keep the default `.srt` behavior.

Examples:

- `Movie - hd.eng.srt`
- `Movie - hd.jpn.ass`
- `Movie - hd.spa.ssa`

The existing language-based uniqueness rules remain unchanged. Multiple
simultaneous subtitles are supported through distinct languages, which is how
the current manifest and sidecar-target rules key subtitle rows.

Validation sidecar projections need to carry the declared subtitle recipe
metadata in addition to `asset_id`, `path`, `kind`, and `language`. That lets
`sidecar_target` and `timeline_lifecycle` distinguish default SRT sidecars from
recipe sidecars when validating timeline operations and hierarchy rerenders.

## Data Flow

1. Scenario parsing validates the new enum fields.
2. Raw validation rejects unsupported subtitle matrix combinations.
3. Raw validation rejects timeline `update_sidecar` / `embed_subtitle` attempts
   against non-default declared subtitle recipes.
4. Preflight repeats the matrix check before filesystem writes.
5. Phase A writes declared sidecars with `subtitle_payload_bytes(...)`.
6. The manifest sidecar row gets the rendered codec-specific path and the
   SHA-256 hash of the exact bytes written.
7. Phase B timeline-created subtitle sidecars continue to write the default
   UTF-8 generated SRT bytes.

## Tests

Add focused coverage at each layer:

- Contract tests for enum round trips, defaults, schema version v23, and
  codec-specific rendered paths.
- Validation/preflight tests for the valid matrix and invalid source/codec or
  encoding combinations.
- Pure recipe tests for UTF-8 BOM, UTF-16 LE BOM, ISO-8859-1 bytes, ASS/SSA
  style sections, overlap timing, and out-of-range timing.
- Synthesis tests proving multiple simultaneous subtitle tracks write
  codec-specific sidecars and manifest hashes are byte-based.
- Existing timeline create/update sidecar tests continue to prove default SRT
  behavior is unchanged.
- Validation tests proving `update_sidecar` and `embed_subtitle` reject declared
  non-default subtitle recipes instead of rewriting them with default SRT bytes.

## Risks

The largest compatibility risk is changing declared sidecar extensions for ASS
and SSA from the old implicit `.srt` renderer. This is intentional for new
formats and protected by defaulting the renderer argument to `srt` for existing
call sites. The second risk is contract churn: changing `SubtitleTrack.codec` to
an enum tightens validation, so all fixtures and tests must use one of the three
implemented codecs.
