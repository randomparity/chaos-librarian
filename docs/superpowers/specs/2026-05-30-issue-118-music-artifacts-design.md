# Issue #118 — Advanced music artifacts and tag corruption (v1)

## Status

Design — approved scope (Option B). Three capabilities ship in v1; three defer.

## Problem

#106 froze the music topology (artist → album → disc → track → variant → bundle →
asset) and deferred a set of advanced music-library artifacts. #118 asks for follow-up
coverage of CUE sheets, embedded lyrics, album-art sidecars and format changes,
multi-track single-file albums, and tag corruption (malformed ID3 / null bytes).

Several of these overlap features added since #106. Each was triaged against the
existing schema before scoping.

## Capability triage

| Capability | Triage | v1 |
| --- | --- | --- |
| Tag corruption (malformed ID3 / null bytes) | New action; reuses the `malformed-media` profile gate + `CorruptionRecord`/`CorruptionAction` plumbing | **Ship** |
| CUE sheet sidecar | New `SidecarKind.CUE`; reuses the #181 `create_sidecar` + `body` machinery | **Ship** |
| Album-art format variety (jpeg/webp) | Small extension to the PNG-only cover-art format enum | **Ship** |
| Album-art format *change* over time (JPG→WebP) | `update_sidecar` cannot change a sidecar's format/extension today; larger question | Defer → issue |
| Multi-track single-file album | Genuinely new topology (one asset spanning multiple tracks) | Defer → issue |
| Embedded lyrics | `edit_metadata.fields` already maps `lyrics=...` to `ffmpeg -metadata` (timeline-embedded form already expressible); a phase-A `embedded_lyrics` asset field is new | Defer → issue (document `edit_metadata` covers the timeline form) |

## Decisions (Q1–Q5)

### Q1 — Scope: ship three capabilities (Option B)

Tag corruption, CUE sheet sidecar, album-art format variety. Defer the three rows
above as GitHub issues before merge.

### Q2 — Tag corruption: one `corrupt_tags` action + closed flavor enum

A single profile-gated timeline action `corrupt_tags`, gated by `malformed-media`,
materialized in `phase_b/corruption.py` alongside the existing corruptors. It writes
**deterministic raw bytes at the file head** (container-agnostic, like
`corrupt_container_header`) — it does **not** route through `ffmpeg -metadata`, which
sanitizes values and could never produce null bytes or a malformed frame.

A closed `TagCorruptionFlavor` StrEnum selects the corruption shape:

- `null_bytes` — overwrite a leading byte run with `0x00`, modelling embedded null
  bytes in an ID3 text frame.
- `malformed_frame` — prepend/overwrite the head with a syntactically invalid ID3v2
  frame header (`ID3` magic + deterministic-but-invalid size/flags bytes), modelling a
  malformed ID3 tag.

The action records a `CorruptionRecord` (profile `malformed-media`, `corruptor`
`tag_corruption_v1`, `seed_material`, `metadata={"flavor": ...}`) on the new version,
and a `CorruptionAction` from the materializer, exactly mirroring `truncate_file`. The
corrupted output is probed; `probe_outcome` records whether ffprobe still reads it.

`CorruptTagsEvent` shape: `target: str`, `flavor: TagCorruptionFlavor`,
`bytes: int = Field(default=64, ge=1, le=4096)` (count of head bytes affected, matching
`corrupt_container_header`'s knob).

### Q3 — CUE sheet: new `SidecarKind.CUE`, authored via `create_sidecar`

Add `SidecarKind.CUE`. CUE sidecars are authored through the existing
`create_sidecar` event:

- `body` (the #181 inline-content field) holds an authored CUE sheet verbatim;
  `None` synthesizes a minimal deterministic default CUE.
- Like poster/NFO, a CUE sidecar **forbids `language`** and the subtitle-only knobs
  (`codec`/`source`/`encoding`) and `media_type`. The existing
  `CreateSidecarEvent.model_validator` is extended so `body` is valid for `nfo` **and**
  `cue` (today body is nfo-only).
- "CUE sync issue" chaos uses the existing `update_sidecar` / `remove_sidecar` on the
  CUE sidecar — no new event.
- Not corruption → **no profile gate** (like poster/nfo).

Materialization: `_apply_create_sidecar` gains a `cue` branch writing
`cue_payload(...)` bytes (authored `body` verbatim, else a synthesized default). The
`regenerate_sidecar` dispatch (`update_sidecar`) gains the same `cue` branch.
`LiveSidecar` already carries `body`, so update regenerates faithfully.

### Q4 — Album-art format variety: scenario-side only, manifest stays v10

Extend `CoverArtImageFormat` (`png` only today) to add `jpeg` and `webp`. This enum
drives `EmbeddedCoverArt.image_format` (cover art embedded in the audio container). The
cover-art prelude already writes `cover.{image_format.value}` and lets ffmpeg select the
encoder from the extension, so the only synthesis change is allowing the two new values
(plus a validation/capability check that the encoder is available).

**Manifest verification (Q4 gate):** the embedded cover-art bytes are recorded in the
asset's existing `content_hash`, and the format is recorded in the existing
`ContentSourceEvidence.cover_art_image_format` replay evidence — both already present.
A poster/album-art **sidecar** records via `ManifestSidecar`, whose `kind` and `path`
(carrying the author-chosen extension) and `content_hash` are already present. **No new
manifest or materialization field is required → `MANIFEST_SCHEMA_VERSION` stays 10 and
`MATERIALIZATION_SCHEMA_VERSION` is unchanged.** Confirmed against
`contract/manifest.py` and `contract/content_sources.py`.

### Q5 — Profile gates

`corrupt_tags` → add to `REQUIRED_PROFILES_BY_ACTION` mapped to `malformed-media` (the
single source of truth; fuzz lane generation derives gated labels from it). CUE
sidecar and cover-art formats are not corruption → no gate.

## Schema impact

`SCENARIO_SCHEMA_VERSION` 31 → 32. New surface:

- `TagCorruptionFlavor` StrEnum (`null_bytes`, `malformed_frame`).
- `TimelineActionName.CORRUPT_TAGS` + `CorruptTagsEvent` (added to the `TimelineEvent`
  union and the discriminator).
- `SidecarKind.CUE`.
- `CoverArtImageFormat.JPEG`, `CoverArtImageFormat.WEBP`.
- `REQUIRED_PROFILES_BY_ACTION[corrupt_tags] = malformed-media`.

No other `*_SCHEMA_VERSION` changes (manifest, materialization, journal, replay,
reports unchanged — verified Q4).

JSON-schema artifacts regenerated with `--write`. All fixtures and recipes mass re-pin
`schema_version: 31` → `32`.

## Validation + error contract (reuse existing codes)

- `corrupt_tags` without `malformed-media` → `E_PROFILE_REQUIRED` (existing
  `rule_profile_opt_in`, driven by the mapping).
- `corrupt_tags` / CUE `create_sidecar` with an unknown `target` → `E_TARGET_UNKNOWN`
  (existing `rule_target_unknown`; `corrupt_tags` added to its asset-target set).
- Cross-kind field misuse on a CUE sidecar (e.g. `language` on `cue`) →
  `E_FIELD_*` from the extended `CreateSidecarEvent.model_validator`.
- `corrupt_tags` lifecycle (target must be a live, materialized asset; cannot follow a
  delete) → existing `E_LIFECYCLE_INVALID` via `timeline_lifecycle` (added to the
  corruption action sets) and `hierarchy` resolution.
- Pydantic shape errors (bad `flavor`, `bytes` out of range) → `E_FIELD_SHAPE`.

No new validation code unless a gap surfaces during TDD; if one does, surface it.

## Materialization

- `corrupt_tags`: new `_apply_corrupt_tags` handler in `phase_b/corruption.py`, added to
  `_HANDLERS` and `supports_corruption_action`. Reuses `overwrite_range` (null_bytes:
  zero fill; malformed_frame: deterministic invalid ID3v2 header bytes via a new
  byte-builder in `corruption_bytes.py`). Atomic temp-sibling write + `_finalize`,
  probe, `CorruptionAction` with `metadata={"flavor": ...}`.
- CUE sidecar: `cue_payload(...)` in `phase_b/sidecar_bytes.py` (pure Python), wired into
  `_apply_create_sidecar` and `regenerate_sidecar`.
- Cover-art formats: `_run_cover_art_prelude` is format-agnostic already; the change is
  enum-level plus a capability/validation guard for the chosen encoder.

## Policy-neutral oracle / manifest impact

`corrupt_tags` records a `CorruptionRecord` on the new `ManifestVersion` (profile,
corruptor, seed_material, flavor metadata, probe outcome via the materialization
report) — the oracle states *what corruption was applied and whether the output still
probes*, never a policy verdict. CUE sidecars record a `ManifestSidecar` row
(`kind=cue`, path, content_hash). Cover-art format records the format in the existing
content-source evidence. Manifest version unchanged.

## Backward compatibility

Existing music/movie/TV/podcast scenarios stay valid after the mandatory
`schema_version: 32` re-pin. Omitting every new field is byte-identical to v31 output.
A regression test asserts a representative movie, TV, and podcast scenario materialize
to byte-identical manifests/content vs. the v31 baseline (other than the version
literal). `CoverArtImageFormat.PNG` remains the default, so existing embedded-cover-art
assets are unchanged.

## Deferred → GitHub issues (filed before merge, deduped vs backlog)

1. Album-art format-**change** action (existing sidecar JPG→WebP via an
   extension-changing update).
2. Multi-track single-file album topology.
3. Embedded-lyrics phase-A asset field (timeline form covered by `edit_metadata`).

## Considered & rejected (captured in ADR 0011)

- Tag corruption via `ffmpeg -metadata` (sanitizes; can't produce null bytes /
  malformed frames).
- Two separate tag-corruption actions instead of one + flavor enum (more surface, less
  cohesive).
- A dedicated `cue_sheet` asset field tying CUE to track offsets (couples to the
  deferred multi-track-single-file topology; over-scoped).
- Free-string image format (admits unsynthesizable values; off-pattern vs. the closed
  media-field convention).
- Bumping the manifest version for cover-art formats (no new field required — Q4).
