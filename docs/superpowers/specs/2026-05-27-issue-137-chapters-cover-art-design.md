# Issue 137 Chapters And Cover Art Design

## Context

Issue #137 asks chaos-librarian to synthesize embedded chapter metadata and
embedded cover-art streams so scanners can exercise probe-visible media features
that are not ordinary audio/video tracks.

The current codebase has no asset-level scenario fields for embedded chapters or
cover art. Phase-A materialization only resolves video/audio sources, builds one
FFmpeg mux command, probes `format` and `streams`, and records content-source
evidence for video/audio recipes. Sidecar poster support exists, but it is
filesystem-level data and does not create an attached-picture stream.

Local FFmpeg checks verified:

- MP4 chapters are visible through `ffprobe -show_chapters` when mapped from an
  ffmetadata input with `-map_metadata <input> -map_chapters <input>`.
- MKV chapters are visible through the same path.
- MP4 cover art is visible as a video stream with
  `disposition.attached_pic = 1` when a PNG input is mapped with
  `-c:v:1 png -disposition:v:1 attached_pic`.
- The same single-command Matroska cover-art path did not produce
  `attached_pic = 1`, so MKV cover art is out of scope for this issue.

## Assumptions

- The GitHub issue acceptance criteria are the approved requirements for this
  autonomous cycle.
- "Deterministic from scenario seed and asset ID" means generated chapter and
  cover content must include both values in the recipe digest and in the
  deterministic generation inputs.
- A small verified support matrix is preferred over advertising broad container
  support that FFmpeg cannot prove with `ffprobe`.

## Supported Contract

`Asset` gains two optional fields:

```yaml
embedded_chapters:
  count: 3
  title_prefix: Scene
embedded_cover_art:
  source: solid_color
  image_format: png
  resolution: square_320
```

`EmbeddedChapters` fields:

- `count: int` with `1 <= count <= 20`.
- `title_prefix: str = "Chapter"` with `1 <= len <= 64`.

`EmbeddedCoverArt` fields:

- `source: CoverArtSource = "solid_color"`.
- `image_format: CoverArtImageFormat = "png"`.
- `resolution: CoverArtResolution = "square_320"`.

Only one cover-art recipe ships. This avoids phantom features while leaving the
contract explicit and probe-verifiable.

## Deterministic Generation

Chapter timestamps are evenly partitioned over `asset.duration_seconds` using
integer milliseconds. Every chapter starts at the previous chapter's end, and the
last chapter ends at the rounded asset duration. Validation rejects
`embedded_chapters.count` when the rounded duration has fewer milliseconds than
the requested chapter count, so every generated chapter has at least one
millisecond of duration. Titles are deterministic and include a stable short
suffix derived from:

```text
scenario_seed | asset_id | chapter_index | title_prefix
```

The title format is:

```text
<title_prefix> 01 <six-hex-suffix>
```

Cover art uses a deterministic solid color derived from:

```text
scenario_seed | asset_id | embedded_cover_art fields
```

The generated PNG is a 320x320 still image. The color is recorded in evidence so
consumers can diagnose drift without re-deriving the recipe.

## Validation

Validation rejects unsupported materialize combinations before subprocess work:

- `embedded_chapters` is supported only for video assets with container `mp4` or
  `mkv`.
- `embedded_cover_art` is supported only for video assets with container `mp4`.
- `embedded_chapters.count` must not exceed the rounded asset duration in
  milliseconds.
- Resolution-switch assets cannot combine chapters or cover art because they use
  a specialized MPEG-TS segment/concat flow.
- Track/audio-only assets cannot declare chapters or cover art.

All failures use `E_MATERIALIZE_UNSUPPORTED` and point at the specific asset
field (`.embedded_chapters`, `.embedded_chapters.count`, or
`.embedded_cover_art`).

## Materialization

Phase-A materialization prepares temporary metadata inputs before the main FFmpeg
command:

- Chapters are written as an ffmetadata file in a per-asset temporary directory.
- Cover art is generated as a temporary PNG by a prelude FFmpeg invocation using
  a seeded `color` lavfi input.

The main video mux command accepts optional `chapters_input` and
`cover_art_input` `FFmpegInput` values. It maps normal video/audio streams first,
then maps the cover-art input as the second output video stream. If chapters are
present, it applies `-map_metadata <chapter_input_index>` and
`-map_chapters <chapter_input_index>` after the bit-exact output flags. That
ordering is intentional: the existing bit-exact flag set contains
`-map_metadata -1`, and the chapter metadata mapping must be the final metadata
mapping option for chapter titles to survive.

Cover-art generation is recorded as a prelude invocation. Existing Phase-A
invocation indexing already adjusts the final materialized asset to the main mux
invocation after any preludes.

Resolution-switch materialization remains unchanged and rejects chapters/cover
art before writing files.

## Probe Contract

`ProbedMedia` gains:

```python
chapters: list[ProbedChapter] = Field(default_factory=list)
```

`ProbedChapter` includes:

- `index: int`
- `start_ms: int`
- `end_ms: int`
- `title: str | None`

`ProbedStream` gains:

```python
attached_pic: bool | None = None
```

`probe_file()` adds `-show_chapters`, parses chapter timestamps from ffprobe's
integer fields when possible, and records `attached_pic` from
`stream.disposition.attached_pic` for video streams. Existing subtitle stream
behavior remains unchanged.

Adapter probe comparison includes `chapters` and `attached_pic`, so consumers get
divergence reports when a scanner loses either signal.

## Evidence

`ContentTrackKind` gains `chapters` and `cover_art`.

`ContentSourceEvidence` gains optional fields:

- `chapter_count`
- `chapter_title_prefix`
- `cover_art_image_format`
- `cover_art_resolution`
- `cover_art_color`

Phase-A appends one evidence entry for chapters and one for cover art when those
features are requested. Evidence recipe digests include the scenario seed, asset
ID, recipe fields, generated titles/timestamps or generated color, and the
FFmpeg input descriptor.

## Schema Versions

This issue changes exported contracts in six places:

- `SCENARIO_SCHEMA_VERSION`: `20 -> 21`
- `MANIFEST_SCHEMA_VERSION`: `8 -> 9`
- `ASSET_REPORT_SCHEMA_VERSION`: `8 -> 9`
- `OBSERVED_STATE_SCHEMA_VERSION`: `3 -> 4`
- `MATERIALIZATION_SCHEMA_VERSION`: `13 -> 14`
- `REPLAY_BUNDLE_SCHEMA_VERSION`: `10 -> 11`

`Capabilities` does not need a version bump. Chapters and cover art use baseline
FFmpeg/ffprobe capability already required for static materialization; no new
host-probed readiness field is introduced.

All affected `schema_version: Literal[...]` annotations and checked-in JSON
Schema artifacts are regenerated in the same change.

## Tests

Contract tests cover:

- Scenario round-trip for `embedded_chapters` and `embedded_cover_art`.
- Enum rejection for unsupported cover-art recipe values.
- Schema version bumps.

Validation tests cover:

- MP4/MKV chapter declarations accepted.
- MP4 cover-art declaration accepted.
- Chapters rejected on audio-only tracks and resolution-switch assets.
- Cover art rejected on MKV/audio-only tracks and resolution-switch assets.

FFmpeg builder tests cover:

- Optional chapter metadata input is added and mapped by input index.
- Optional cover-art input is mapped as `attached_pic`.
- Non-video/audio-only paths reject chapters and cover art.

Probe tests cover:

- `probe_file()` calls `ffprobe` with `-show_chapters`.
- Chapter JSON maps to `ProbedChapter`.
- Video stream disposition maps to `attached_pic`.

Materialization tests cover:

- Chapter evidence is recorded and passed into the main mux command.
- Cover-art prelude invocation is emitted before the main mux command.
- Real FFmpeg smoke tests produce probe-visible MP4 and MKV chapters, plus an
  attached PNG picture stream in MP4.

Adapter tests cover:

- Chapter mismatches report stable field paths.
- Attached-picture mismatches report stable stream field paths.

## Out Of Scope

- Music-specific album-art semantics.
- Tag corruption.
- MKV/WebM attached-picture handling.
- More cover-art recipes.
- Timeline mutations that add, remove, or corrupt chapters/cover art.
