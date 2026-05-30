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
| Album-art format variety (jpeg/webp) | New poster-sidecar `image_format` selector; reuses the #181 `create_sidecar` poster path (attaches to any asset, including music tracks) | **Ship** |
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

- `null_bytes` — overwrite the first `bytes` head bytes with `0x00`, modelling embedded
  null bytes in an ID3 text frame. This needs a **new zero-fill helper** in
  `corruption_bytes.py` (e.g. `zero_range`); `overwrite_range` cannot do it — it fills
  with `replacement_bytes`, which is sha256-derived and never zero.
- `malformed_frame` — overwrite the head **in place** (no length change) with a fixed,
  deterministic, syntactically invalid ID3v2 header byte pattern: the `ID3` magic
  (`0x49 0x44 0x33`), a bogus version (`0xFF 0xFF`), a flags byte, and a deliberately
  invalid (non-syndsafe) size field, padded/truncated to the requested `bytes` length.
  This is a **new fixed-pattern helper** in `corruption_bytes.py` (e.g.
  `malformed_id3_header(byte_count)`); it does not prepend or grow the file, so all
  downstream offsets are unchanged.

In both flavors the `bytes` knob is the count of in-place head bytes the corruptor
writes; the file size is unchanged. `corruption_bytes` already rejects a range longer
than the file (`overwrite_range` raises `ValueError`); the new helpers apply the same
length guard so a file shorter than `bytes` is a clear materialization error rather than
silent partial corruption.

The action records a `CorruptionRecord` (profile `malformed-media`, `corruptor`
`tag_corruption_v1`, `seed_material`, `metadata={"flavor": ...}`) on the new version,
and a `CorruptionAction` from the materializer, mirroring `corrupt_container_header`
(byte-overwrite at the head, no ffmpeg). The corrupted output is probed; `probe_outcome`
records whether ffprobe still reads it.

`CorruptTagsEvent` shape: `target: str`, `flavor: TagCorruptionFlavor`,
`bytes: int = Field(default=64, ge=1, le=4096)` (count of in-place head bytes affected,
matching `corrupt_container_header`'s knob).

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

### Q4 — Album-art format variety: poster-sidecar selector, manifest stays v10

Album art for music is delivered as a **poster sidecar**, not embedded cover art.
`EmbeddedCoverArt`/`CoverArtImageFormat` is validation-gated to mp4 **video** assets
(`rule_materialize_media_matrix._check_video_embedded_metadata`) and rejected outright
on track/audio assets (`_check_track_asset`), so it cannot serve a music library. A
poster sidecar via `create_sidecar(kind=poster)` attaches to **any** asset, including a
music track, and is the music-relevant reading of #118's "album-art sidecar."

Add a new `image_format` field to the poster path of `CreateSidecarEvent`, typed as a
dedicated **`PosterImageFormat` StrEnum (`png`, `jpeg`, `webp`)** (see enum rationale
below). `None`/`png` keeps today's behavior (a 400x600 single-color PNG). `jpeg`/`webp`
synthesize the same color frame in that format. The selector drives both the synthesized
bytes (the ffmpeg argv's pixel/codec choice) and the deterministic rendered extension on
the sidecar `path` — the materializer derives the encoder/extension from `image_format`
rather than relying on implicit ffmpeg extension inference from the author's `to:`.

`image_format` is poster-only (forbidden on subtitle/nfo/cue, enforced in the extended
`CreateSidecarEvent.model_validator`). It is incompatible with `media_type=video`
(image format applies only to image posters); the validator rejects the combination.

**Capability guard:** `jpeg`/`webp` require their ffmpeg encoders (`mjpeg`, `libwebp`).
A validation/materialization guard checks availability via the existing
`_ffmpeg_encoder_available` (`materializer/tooling/capabilities.py`) and surfaces
`E_MATERIALIZE_UNSUPPORTED` when the encoder is absent, mirroring how the subtitle
recipe matrix and HEVC paths gate on synthesis capability. `png` needs no guard.

**Enum rationale (no conflation):** a poster sidecar is a standalone image file; embedded
cover art is an attached-picture stream muxed into an mp4 and carries its own validation
surface and `ContentSourceEvidence.cover_art_image_format` replay field. Reusing
`CoverArtImageFormat` would couple the poster's format contract to the embedded-only
evidence/validation surface and force the poster to track future embedded-only enum
additions. A dedicated `PosterImageFormat` keeps the two artifacts' format contracts
independent. The two enums happen to share `png`/`jpeg`/`webp` token spellings today;
that is incidental, not a shared concept.

**Manifest verification (Q4 gate):** a poster sidecar records via `ManifestSidecar`,
whose `kind`, `path` (carrying the format-derived extension), and `content_hash` are all
already present. The format selection only changes the synthesized bytes (recorded in
the existing `content_hash`) and the rendered extension (recorded in the existing
`path`). **No new manifest or materialization field is required →
`MANIFEST_SCHEMA_VERSION` stays 10 and `MATERIALIZATION_SCHEMA_VERSION` is unchanged.**
Confirmed against `contract/manifest.py`.

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
- `PosterImageFormat` StrEnum (`png`, `jpeg`, `webp`) + `CreateSidecarEvent.image_format`
  (poster-only).
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
  `_HANDLERS` and `supports_corruption_action`. Two new pure helpers in
  `corruption_bytes.py`: `zero_range` (null_bytes flavor — fixed `0x00` fill, same
  length guard as `overwrite_range`) and `malformed_id3_header` (malformed_frame flavor —
  fixed invalid ID3v2 header pattern, in-place, length-guarded). Atomic temp-sibling
  write + `_finalize`, probe, `CorruptionAction` with `metadata={"flavor": ...}`.
- CUE sidecar: `cue_payload(...)` in `phase_b/sidecar_bytes.py` (pure Python), wired into
  `_apply_create_sidecar` and `regenerate_sidecar`.
- Poster `image_format`: `poster_ffmpeg_argv` gains an `image_format` parameter selecting
  the encoder/pixel-format and output extension (`png`/`jpeg`/`webp`); the create-sidecar
  and update-sidecar paths thread it through, and `LiveSidecar` carries it for faithful
  regeneration. Capability guard via `_ffmpeg_encoder_available` (`mjpeg`/`libwebp`).

## Policy-neutral oracle / manifest impact

`corrupt_tags` records a `CorruptionRecord` on the new `ManifestVersion` (profile,
corruptor, seed_material, flavor metadata, probe outcome via the materialization
report) — the oracle states *what corruption was applied and whether the output still
probes*, never a policy verdict. CUE sidecars record a `ManifestSidecar` row
(`kind=cue`, path, content_hash). A poster sidecar's `image_format` is reflected in the
existing `ManifestSidecar.path` (format-derived extension) and `content_hash` (synthesized
bytes). Manifest version unchanged.

## Backward compatibility

Existing music/movie/TV/podcast scenarios stay valid after the mandatory
`schema_version: 32` re-pin. Omitting every new field is byte-identical to v31 output.
A regression test asserts a representative movie, TV, and podcast scenario materialize
to byte-identical manifests/content vs. the v31 baseline (other than the version
literal). Poster `image_format` defaults to `png` (omitted = today's behavior), so
existing poster sidecars are byte-identical; `EmbeddedCoverArt`/`CoverArtImageFormat`
(mp4 video cover art) is untouched by this change.

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
- Album-art format via `EmbeddedCoverArt`/`CoverArtImageFormat` (embedded, not a sidecar;
  validation-gated to mp4 video and rejected on audio tracks, so it serves no music
  library — it's the wrong artifact for #118's "album-art sidecar").
- Free-string image format (admits unsynthesizable values; off-pattern vs. the closed
  media-field convention).
- Overloading `CoverArtImageFormat` for the poster sidecar (couples the poster's format
  contract to the embedded-cover-art evidence/validation surface; a dedicated
  `PosterImageFormat` keeps the two artifacts independent).
- Bumping the manifest version for poster image format (no new field required — Q4).
