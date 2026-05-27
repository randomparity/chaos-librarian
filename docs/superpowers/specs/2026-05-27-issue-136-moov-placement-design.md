# Issue 136 MP4 Moov Placement Design

## Context

Issue #136 asks for MP4 `moov` atom placement coverage so scenario authors can
exercise parser differences between MP4s whose metadata atom is at the start or
at the end of the file. The current code supports MP4 static materialization and
remuxing, but there is no scenario field, FFmpeg flag, validation rule, or
materialization evidence for `moov` placement.

## Chosen Approach

Add a narrow asset-level field:

```yaml
mp4_moov_placement: moov_at_start | moov_at_end
```

The field belongs on `Asset` because `moov` placement is a container muxing
choice, not a video or audio source property. It is optional and defaults to
`None`, preserving existing scenario behavior and output for all assets that do
not request the new option.

The contract uses a new `Mp4MoovPlacement` enum with values `moov_at_start` and
`moov_at_end`. The project uses snake_case values elsewhere, so the wire values
stay consistent with existing scenario enums while still naming the two issue
variants explicitly.

## Materialization Behavior

For MP4 static materialization:

- `moov_at_start` adds FFmpeg output args `-movflags +faststart`.
- `moov_at_end` emits no `-movflags` override because FFmpeg's normal MP4 muxer
  output writes `mdat` before the final `moov` atom.

The FFmpeg builder rejects `mp4_moov_placement` when the resolved output
container is not `mp4`. This mirrors the validation rule and protects direct
builder callers in tests.

Resolution-switch assets are not MP4 and must reject the field through the same
non-MP4 validation path.

## Validation

Shape validation rejects unsupported placement values through the enum. Semantic
validation adds one rule to `materialize_media_matrix`: if
`mp4_moov_placement` is present and `container != "mp4"`, emit
`E_MATERIALIZE_UNSUPPORTED` at the asset field location.

## Evidence

Record the selected placement on `MaterializedAsset` as
`mp4_moov_placement: Mp4MoovPlacement | None`. This is materialization evidence,
not content-source evidence, because the source recipes are unchanged and the
choice affects only final container muxing. `materialization.schema.json` bumps
from v12 to v13.

`replay.json` does not need a schema bump. It embeds the scenario YAML and the
FFmpeg invocation trace, and does not carry `MaterializedAsset` rows.

## Schema Versions

- `SCENARIO_SCHEMA_VERSION`: 19 -> 20
- `MATERIALIZATION_SCHEMA_VERSION`: 12 -> 13

No manifest, asset-report, observed-state, or replay-bundle schema version bump
is needed because none of those contracts gains a new field.

## Verification

Tests will verify behavior without comparing full file bytes:

- Contract tests assert enum values, field round-trip, and unsupported value
  rejection.
- Validation tests assert non-MP4 placement requests produce
  `E_MATERIALIZE_UNSUPPORTED`.
- FFmpeg builder tests assert `moov_at_start` adds `-movflags +faststart`,
  `moov_at_end` does not, and non-MP4 placement raises before subprocess work.
- Integration tests materialize two MP4 assets, scan top-level MP4 atoms, and
  assert `moov < mdat` for start placement and `mdat < moov` for end placement.
- Materialization tests assert `materialization.json` records the selected
  placement for both assets.
