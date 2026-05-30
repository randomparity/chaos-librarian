# 0003 — Authorable sidecar encoding and body content

## Status

Accepted

## Context

The `create_sidecar` timeline event (`contract/scenario.py`) synthesizes a fixed
shape per `kind`: a UTF-8 SRT (subtitle), a fixed-template NFO, or a PNG poster. The
author cannot control the byte encoding, the NFO body, or the poster's media type, so
three chaos recipes surfaced by #108 are inexpressible: `wrong-encoding`,
`nfo-xml-injection`, and `poster-is-video` (see the #108 spec "Dropped proposals").

The declared-subtitle path (`asset.subtitles[*]`) already exposes
`codec`/`source`/`encoding` and rejects unsynthesizable combos (notably
`ass`+`utf16_le`) via `E_MATERIALIZE_UNSUPPORTED` in `rule_materialize_media_matrix`.
The timeline event has none of that surface. Issue #181 brings authorable content to
the timeline event and makes the deferred `ass`+`utf16_le` rejection a live contract.

This is a scenario-schema change (`SCENARIO_SCHEMA_VERSION` 23 → 24) and introduces a
new failure surface, so the decisions below are recorded with their rejected
alternatives to keep settled choices from reopening.

## Decision

Add five flat optional fields to `CreateSidecarEvent`, each scoped to one `kind`, with
a model validator that forbids cross-kind misuse and a new semantic rule that rejects
unsynthesizable subtitle combos.

1. **Subtitle knobs = full `codec` + `source` + `encoding` trio**, mirroring
   `SubtitleTrack`. Defaults (`None`) resolve to `srt` / `generated_srt` / `utf8`.
2. **NFO body = an inline `body: str` field** (`min_length=1`). The materializer
   writes those exact UTF-8 bytes; `None` keeps the current template.
3. **Poster media type = a closed `SidecarMediaType` StrEnum `{image, video}`**.
   `None`/`image` keeps the PNG; `video` writes a small deterministic video at the
   poster path.
4. **Invalid-combo failure contract = `E_MATERIALIZE_UNSUPPORTED` raised by a new
   semantic rule** (`rule_create_sidecar_content`), reusing the existing subtitle
   recipe matrix, so an authored `ass`+`utf16_le` raises the same code as the declared
   path. Cross-kind *shape* misuse (a field on the wrong kind) stays in the Pydantic
   `model_validator` as `E_FIELD_*`.
5. **Field placement = flat fields on the single `CreateSidecarEvent`** with an
   extended `model_validator` that *forbids* cross-kind misuse (no discriminated
   sub-union).

`SCENARIO_SCHEMA_VERSION` is bumped 23 → 24 and the JSON-schema artifact regenerated.
`ManifestSidecar` and `MaterializationReport`/`MediaAction` are unchanged, so their
versions are not bumped; `LiveSidecar` (in-memory) is widened to carry the new fields
so `update_sidecar` regenerates faithfully.

## Consequences

- The three recipes ship and validate clean; `recipes/sidecar/` grows 3 → 6.
- Authors get one consistent `E_MATERIALIZE_UNSUPPORTED` for `ass`+`utf16_le`
  regardless of whether the subtitle is declared or timeline-authored.
- Omitting the new fields is byte-identical to today (regression-tested), so existing
  scenarios and recipes are unaffected beyond the mandatory `schema_version: 24` bump.
- v1 timeline subtitle synthesis covers only the SRT recipe; ASS/SSA *codecs* on the
  timeline event are rejected at validate time as `E_MATERIALIZE_UNSUPPORTED` (no
  phantom capability). Timeline ASS synthesis is filed as a follow-up issue.
- `state_delta` and `_STATE_DELTA_KEYS` for `create_sidecar` gain the five fields,
  enforced by `test_state_delta_keys_match_contract`.

## Considered & rejected

**Q1 — Subtitle knob scope.**
- *Rejected: `encoding`-only* (codec/source implicit). All four SRT encodings are
  valid, so an encoding-only knob could never exercise the `ass`+`utf16_le` rejection
  the issue is about — it would leave that contract unreachable from the timeline.
- **Chosen: full `codec`+`source`+`encoding` trio**, making the rejection a live,
  testable timeline contract and matching `SubtitleTrack`.

**Q2 — NFO body source.**
- *Rejected: file reference* (path to an on-disk payload). Adds a second artifact per
  recipe and a path-containment surface; contradicts the self-contained,
  single-file, reviewable scenario ethos (ADR 0002).
- *Rejected: closed enum of named injection payloads* (`xxe`, `billion_laughs`, …).
  Cannot express the arbitrary payloads the `nfo-xml-injection` recipe name implies.
- **Chosen: inline `body: str`** — bit-exact, reviewable in one file, deterministic.

**Q3 — Poster media-type representation.**
- *Rejected: free-string `media_type`* (arbitrary MIME/container). Admits
  unsynthesizable values and pushes capability-gating into a string check.
- *Rejected: boolean `mismatched: true`*. Single-purpose; cannot grow to other
  mismatch shapes; off-pattern for the codebase's closed-set media fields.
- **Chosen: closed `SidecarMediaType` StrEnum `{image, video}`** — matches the
  "only values materialize can synthesize, validated by a closed set" convention.

**Q4 — Invalid-combo failure contract.**
- *Rejected: a new code `E_SIDECAR_CONTENT_INVALID`*. Fragments the contract — an
  author hitting `ass`+`utf16_le` should see one code regardless of where they wrote it.
- *Rejected: everything in the Pydantic model_validator* (so even `ass`+`utf16_le` is
  `E_FIELD_*`). Misclassifies a synthesis-capability limit as a shape error and
  diverges from the declared path's `E_MATERIALIZE_UNSUPPORTED`.
- **Chosen: reuse `E_MATERIALIZE_UNSUPPORTED` in a new semantic rule**, with cross-kind
  shape misuse staying in the model_validator as `E_FIELD_*`.

**Q5 — Field placement & exclusivity.**
- *Rejected: split `CreateSidecarEvent` into a discriminated sub-union on `kind`*
  (separate Subtitle/Poster/Nfo event classes). A larger, riskier refactor of a frozen
  public event that changes the JSON-schema shape more than necessary.
- *Rejected: silently ignore cross-kind fields* (e.g. accept `encoding` on an NFO and
  drop it). Violates the `extra="forbid"` ethos and hides authoring mistakes.
- **Chosen: flat optional fields + an extended model_validator that forbids cross-kind
  misuse**, keeping the `action` discriminator and JSON-schema shape minimal.
