# Issues 98-99 Observed-State Language Design

## Goal

Make observed-state probe comparison tolerant of the ffprobe/container convention
where audio/video streams may report unknown language as either absent/null or
`und`, then document the resulting exporter contract together with sidecar hash
expectations.

## Context

Issue #99 reports that MP4 audio/video streams can carry `language: "und"` in the
Chaos oracle while a consumer's ffprobe snapshot omits language. The current
`compare_probed_media` helper compares `language` exactly for every stream kind,
so otherwise equivalent MP4 probe exports diverge with `D_PROBE_MISMATCH`.

Issue #98 asks for documentation that keeps consumer exporters from reverse
engineering these details from implementation code. The docs need to explain the
normalized language behavior and show how subtitle sidecars are represented with
library-relative paths and `content_hash`.

## Design

Add a narrow normalization helper inside `chaos_librarian.adapter.probe`.
`None` and `"und"` compare equal only for streams whose `kind` is `video` or
`audio`. All other language values stay exact, so `eng` versus `spa` still emits
a probe mismatch. Subtitle streams keep exact language comparison, including
`None` versus `"und"`, because subtitle language is user-visible assertion data.
Observed sidecars do not carry a separate `language` field, so their strictness
remains the existing exact `path`/`kind`/`content_hash` comparison; subtitle
sidecar language is represented by the path convention when applicable.

The change is deliberately local to comparison. Contract models still preserve
whatever the oracle and consumer exported, and divergence reports still display
raw expected and observed values for real mismatches.

Update `docs/contract/observed-state.md` with:

- audio/video unknown-language normalization: JSON `null`, omitted language,
  and `und` are equivalent during compare;
- subtitle streams remain strict, and sidecars remain exact by path, kind, and
  content hash;
- consumers should export observed facts rather than synthesizing container
  guesses;
- a compact asset example that includes `probed.streams[]` and a subtitle
  sidecar with `kind`, `path`, and `content_hash`.

## Testing

Add adapter unit tests for the comparison boundary:

- video/audio `None` versus `und` produces no probe differences;
- subtitle `None` versus `und` still produces a language difference;
- real audio/video mismatches such as `eng` versus `spa` still differ.
- a final-state compare report stays clean when the only probe difference is
  audio/video unknown-language spelling.

Add a docs test that asserts the observed-state contract mentions unknown
language normalization, strict subtitle handling, sidecars, and content hashes.

## Out Of Scope

Do not change schema shape or add new observed-state fields. Do not infer
application policy from stream language. Do not rewrite historical oracle data.
