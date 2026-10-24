# ADR 0014: Static bounded track dispositions

## Status

Proposed for #245, 2026-10-24.

## Context

The approved #245 interface requests audio/subtitle default and forced flags and
real evidence of ambiguous selection metadata. Existing phase-A synthesis owns
initial bytes; timeline embedding owns later mutations.

## Decision

Extend phase-A synthesis and the existing FFmpeg builder for a bounded MKV/H.264,
AAC and generated SRT matrix. Store nullable intent on track declarations, retain
actual audio/subtitle flags in ProbedMedia, and fail before successful publication
when explicit flags do not survive encoding. Keep stream selection policy outside
the producer. An asset opting into dispositions requires both flags on each audio and embedded
subtitle track; partial/mixed declarations fail preflight. Entirely unspecified
legacy assets keep existing FFmpeg behavior. Apply bounded capture through the existing subprocess owner.

## Consequences

Embedded subtitle generation uses private numeric inputs and never creates public
sidecars. Unsupported combinations fail early. Consumers distinguish requested
intent from probed facts; replay proves flag evidence, not cross-toolchain bytes.
Existing all-omitted scenarios retain their muxing behavior. This slice does not
promise preservation through track-changing timeline operations.

## Considered & rejected

- Reuse timeline embedding for initial tracks. judgment: moves phase-A ownership
  across the timeline boundary and introduces ordering/evidence complications.
- Add a separate adversarial fixture framework. judgment: existing track models,
  synthesis and comparison already provide the required ownership boundaries.
- Normalize to one default. judgment: contradicts the approved ambiguous-output goal.
- Enable arbitrary codec/container combinations. judgment: expands verification
  beyond the bounded interface and turns tool-specific normalization into promises.

- Inherit omitted flags after opt-in. judgment: reproducing muxer auto-selection
  would create another policy owner; strict complete declarations keep intent explicit.
