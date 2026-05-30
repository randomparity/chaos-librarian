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
- `EmbeddedCoverArt.image_format` (`CoverArtImageFormat`) is PNG-only, but embedded cover
  art is an mp4-video-only feature (`rule_materialize_media_matrix` rejects it on audio
  tracks). The `create_sidecar` poster path (PNG only, format implied by the author's
  `to:` extension) is the artifact that attaches to any asset including music tracks.

This is a scenario-schema change (`SCENARIO_SCHEMA_VERSION` 31 → 32) introducing a new
corruption action and a new sidecar kind, so the settled decisions are recorded with
their rejected alternatives.

## Decision

Ship three of the five capabilities in v1; defer three as follow-up issues.

1. **Tag corruption = one `corrupt_tags` action + closed `TagCorruptionFlavor` enum**
   (`null_bytes`, `malformed_frame`), gated by `malformed-media`, materialized in
   `phase_b/corruption.py` as deterministic **in-place** head-byte overwrite (no length
   change), container-agnostic, mirroring `corrupt_container_header`. `null_bytes` fills
   the first `bytes` head bytes with `0x00` (new `zero_range` helper); `malformed_frame`
   overwrites them with a fixed invalid ID3v2 header pattern (new `malformed_id3_header`
   helper). Neither reuses `overwrite_range` (sha256 fill) and neither prepends/grows the
   file. Records `CorruptionRecord`/`CorruptionAction` with `metadata={"flavor": ...}`.
   Does **not** route through `ffmpeg -metadata` (it sanitizes).
2. **CUE sheet = new `SidecarKind.CUE`** authored via the existing `create_sidecar`
   event, reusing the #181 `body` field for inline CUE text (synthesized default when
   omitted). Forbids `language` and the subtitle/poster knobs. "Sync issue" chaos via
   `update_sidecar` / `remove_sidecar`. Not corruption → no profile gate.
3. **Album-art format variety = a poster-sidecar `image_format` selector** (new
   `PosterImageFormat` StrEnum `{png, jpeg, webp}` on the poster path of
   `CreateSidecarEvent`). A poster sidecar attaches to any asset, including a music
   track, so this delivers album-art-as-sidecar format variety for music. `image_format`
   is the single source of truth for the synthesized format (selects the ffmpeg `-c:v`
   encoder); the author's `to:` still owns the on-disk path, and a static semantic rule
   requires the `to:` extension to agree with `image_format` (`E_MATERIALIZE_UNSUPPORTED`
   on mismatch) so the recorded `ManifestSidecar.path` extension stays honest about the
   bytes. Encoder availability (`mjpeg`/`libwebp`) is a materialize-time concern (ffmpeg
   nonzero exit through the existing tool-failure path, mirroring `libx265`), not a
   validate-time error. `png` is the default and byte-identical to today. A dedicated
   enum (not `CoverArtImageFormat`) keeps the standalone poster sidecar's format contract
   independent of the embedded-cover-art evidence/validation surface.

`SCENARIO_SCHEMA_VERSION` is bumped 31 → 32. `MANIFEST_SCHEMA_VERSION` stays 10 and
`MATERIALIZATION_SCHEMA_VERSION` is unchanged: tag corruption reuses the existing
`CorruptionRecord` on `ManifestVersion`, CUE reuses `ManifestSidecar` (`kind` is a free
`str`), and the poster format is reflected in the existing `ManifestSidecar.path`
(extension) and `content_hash` (bytes). No new manifest or materialization field is
required.

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
- *Rejected: prepend a real ID3v2 header (grow the file).* Shifts every downstream byte
  offset and breaks the in-place overwrite model the existing corruptors use; harder to
  make deterministic and to length-guard.
- **Chosen: one `corrupt_tags` action + closed flavor enum**, deterministic in-place
  head-byte overwrite (new `zero_range` / `malformed_id3_header` helpers — not
  `overwrite_range`, whose sha256 fill is never zero), mirroring
  `corrupt_container_header`.

**Q3 — CUE modeling.**
- *Rejected: a dedicated `cue_sheet` asset field tying the CUE to track offsets.*
  Couples CUE to the deferred multi-track-single-file topology; over-scoped for v1.
- *Rejected: a new `create_cue` event.* CUE is just another sidecar kind; the existing
  `create_sidecar` + `body` already covers authored content and `update`/`remove`
  cover the sync-issue chaos.
- **Chosen: `SidecarKind.CUE` authored via `create_sidecar`**, body reused from #181.

**Q4 — Album-art format mechanism & manifest impact.**
- *Rejected (B): extend `EmbeddedCoverArt`/`CoverArtImageFormat`.* Embedded cover art is
  an attached-picture stream, not a sidecar; `rule_materialize_media_matrix` gates it to
  mp4 **video** assets and rejects it on track/audio assets, so it serves no music
  library and does not match #118's "album-art **sidecar**" wording. Lifting that gate to
  attach a picture stream to audio is a materially larger blast radius (matrix rule +
  audio-only synthesis path) for the wrong artifact.
- *Rejected (C): keep extending `CoverArtImageFormat` for mp4 video cover art and rename
  the capability.* Smallest code, but adds nothing to music libraries — it does not serve
  the issue.
- *Rejected: free-string image format.* Admits unsynthesizable values and pushes
  capability-gating into a string check; off-pattern vs. the closed media-field
  convention.
- *Rejected: overload `CoverArtImageFormat` for the poster sidecar.* Couples the
  standalone poster's format contract to the embedded-cover-art evidence/validation
  surface and forces it to track future embedded-only enum additions.
- *Rejected: bump `MANIFEST_SCHEMA_VERSION` for the poster format.* No new manifest field
  is required — the format flows into the existing `ManifestSidecar.path` (extension) and
  `content_hash` (bytes).
- **Chosen (A): a poster-sidecar `image_format` selector with a dedicated
  `PosterImageFormat` enum**, capability-guarded; manifest stays v10.

**Q5 — Profile gates.**
- **Chosen: gate `corrupt_tags` under `malformed-media`** (consistent with the other
  byte corruptors); CUE and poster image formats are not corruption → no gate, like
  poster/nfo sidecars.
