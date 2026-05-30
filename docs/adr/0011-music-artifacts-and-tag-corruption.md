# 0011 — Advanced music artifacts and tag corruption

## Status

Accepted

## Context

#106 froze the music topology and deferred advanced music-library artifacts to #118:
CUE sheets, embedded lyrics, album-art sidecars and format changes, multi-track
single-file albums, and tag corruption (malformed ID3 / null bytes). Several overlap
features added since #106, so each was triaged against the existing schema before
scoping.

- #181 added authorable sidecar content (`create_sidecar` `body`/`encoding`/`media_type`)
  and `EDIT_METADATA` — album-art-as-sidecar and tag *editing* partly reuse this.
- The `malformed-media` profile already gates byte-corruption actions
  (`corrupt_container_header`, `truncate_file`, `corrupt_packet_range`,
  `write_invalid_duration_metadata`) through `REQUIRED_PROFILES_BY_ACTION`, with
  `CorruptionRecord`/`CorruptionAction` plumbing in `phase_b/corruption.py`.
- `EmbeddedCoverArt.image_format` (`CoverArtImageFormat`) is PNG-only; the cover-art
  prelude already lets ffmpeg pick the encoder from the output extension.

This is a scenario-schema change (`SCENARIO_SCHEMA_VERSION` 31 → 32) introducing a new
corruption action and a new sidecar kind, so the settled decisions are recorded with
their rejected alternatives.

## Decision

Ship three of the five capabilities in v1; defer three as follow-up issues.

1. **Tag corruption = one `corrupt_tags` action + closed `TagCorruptionFlavor` enum**
   (`null_bytes`, `malformed_frame`), gated by `malformed-media`, materialized in
   `phase_b/corruption.py` as deterministic raw-byte injection at the file head
   (container-agnostic, mirroring `corrupt_container_header`). Records
   `CorruptionRecord`/`CorruptionAction` with `metadata={"flavor": ...}`. Does **not**
   route through `ffmpeg -metadata`.
2. **CUE sheet = new `SidecarKind.CUE`** authored via the existing `create_sidecar`
   event, reusing the #181 `body` field for inline CUE text (synthesized default when
   omitted). Forbids `language` and the subtitle/poster knobs. "Sync issue" chaos via
   `update_sidecar` / `remove_sidecar`. Not corruption → no profile gate.
3. **Album-art format variety = add `jpeg` and `webp` to `CoverArtImageFormat`**
   (PNG-only today). Scenario-side selector plus a capability/validation guard for the
   chosen encoder; the prelude is already format-agnostic.

`SCENARIO_SCHEMA_VERSION` is bumped 31 → 32. `MANIFEST_SCHEMA_VERSION` stays 10 and
`MATERIALIZATION_SCHEMA_VERSION` is unchanged: tag corruption reuses the existing
`CorruptionRecord` on `ManifestVersion`, CUE reuses `ManifestSidecar` (`kind` is a free
`str`), and cover-art format is recorded in the existing content-source evidence and
asset `content_hash`. No new manifest or materialization field is required.

Deferred to GitHub issues before merge: album-art format-*change* action,
multi-track single-file album topology, embedded-lyrics phase-A asset field. The
timeline-embedded lyrics form is already expressible via `edit_metadata.fields`.

## Consequences

- `corrupt_tags` joins the `malformed-media` action set and the profile-gate single
  source; fuzz lane generation derives its required label automatically.
- CUE ships as a sidecar kind; `recipes/` gains a CUE recipe and a tag-corruption
  recipe; existing sidecar/corruption rules apply unchanged.
- Omitting every new field is byte-identical to v31 (regression-tested across movie/TV/
  podcast), so existing scenarios are unaffected beyond the mandatory `schema_version:
  32` re-pin.
- `corrupt_tags` `state_delta` keys join `_STATE_DELTA_KEYS`, enforced by
  `test_state_delta_keys_match_contract`.

## Considered & rejected

**Q1 — Scope.**
- *Rejected: ship all five.* Multi-track-single-file is a genuinely new topology and
  album-art format-change needs an extension-changing update mechanism — each deserves
  its own design cycle. Embedded lyrics is already expressible via `edit_metadata`.
- *Rejected: ship only tag corruption.* Leaves CUE and album-art (both cheap, both
  squarely in the issue) on the table.
- **Chosen: tag corruption + CUE + album-art format variety**, the three that reuse
  established machinery cleanly.

**Q2 — Tag-corruption representation.**
- *Rejected: route through `ffmpeg -metadata`.* ffmpeg sanitizes tag values — it can
  never emit null bytes or a malformed ID3 frame, the exact chaos #118 names.
- *Rejected: two actions (`corrupt_id3_null_bytes`, `corrupt_id3_malformed`).* More
  public surface, less cohesive; the shapes are identical apart from the byte pattern.
- *Rejected: extend `write_invalid_duration_metadata` to a general
  `write_invalid_metadata`.* Conflates a valid-ffmpeg-write path with a raw-byte
  corruptor.
- **Chosen: one `corrupt_tags` action + closed flavor enum**, raw-byte injection at the
  head, mirroring `corrupt_container_header`/`truncate_file`.

**Q3 — CUE modeling.**
- *Rejected: a dedicated `cue_sheet` asset field tying the CUE to track offsets.*
  Couples CUE to the deferred multi-track-single-file topology; over-scoped for v1.
- *Rejected: a new `create_cue` event.* CUE is just another sidecar kind; the existing
  `create_sidecar` + `body` already covers authored content and `update`/`remove`
  cover the sync-issue chaos.
- **Chosen: `SidecarKind.CUE` authored via `create_sidecar`**, body reused from #181.

**Q4 — Album-art format & manifest impact.**
- *Rejected: free-string image format.* Admits unsynthesizable values and pushes
  capability-gating into a string check; off-pattern vs. the closed media-field
  convention.
- *Rejected: bump `MANIFEST_SCHEMA_VERSION` for cover-art formats.* No new manifest
  field is required — the format flows into existing `content_hash`, content-source
  evidence, and (for sidecars) the `ManifestSidecar.path` extension.
- **Chosen: extend the closed `CoverArtImageFormat` enum; manifest stays v10.**

**Q5 — Profile gates.**
- **Chosen: gate `corrupt_tags` under `malformed-media`** (consistent with the other
  byte corruptors); CUE and cover-art formats are not corruption → no gate, like
  poster/nfo sidecars.
