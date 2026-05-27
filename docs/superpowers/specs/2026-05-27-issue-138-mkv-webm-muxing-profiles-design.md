# Issue 138 Design: MKV/WebM Cue and Cluster Muxing Profiles

## Context

Issue #138 asks for a small, materialize-valid way to vary Matroska parser
surfaces: cue presence, cue density, and cluster sizing. Current static
materialization writes MKV through FFmpeg's default Matroska muxer settings and
does not support WebM as a static video container.

The supported implementation should stay contract-first and avoid general
container expansion. WebM support exists only to exercise the same muxing
profiles against a WebM-compliant file.

## Approaches Considered

1. FFmpeg-only muxer options.
   FFmpeg exposes `reserve_index_space`, `cues_to_front`, and cluster-size/time
   options. This is small, but it does not expose cue absence or cue density
   well enough to satisfy the issue.

2. mkvmerge remux for requested muxing profiles.
   FFmpeg still synthesizes the elementary media streams. When a profile is
   requested, mkvmerge remuxes the temporary FFmpeg output into the final
   MKV/WebM with explicit cue and cluster options. This directly covers cue
   absence, cue density, and cluster sizing while keeping the default path
   unchanged.

3. Broad WebM support with new audio and video matrices.
   This would add VP9/Opus combinations and wider validation. It solves WebM
   generally, but exceeds the issue scope.

Chosen approach: option 2, with only the minimal WebM matrix cell needed for
profile coverage.

## Contract

Add `Asset.matroska_muxing_profile: MatroskaMuxingProfile | None`.

Supported profile values:

- `no_cues`: final file has no cue/index data.
- `dense_cues`: final file requests cue entries for all video frames.
- `short_clusters`: final file limits clusters to `250ms`.

The field is valid only for video assets with `container: mkv` or
`container: webm`. Omitted field preserves the current default FFmpeg muxer
behavior.

Schema version bumps:

- `scenario`: v22, because assets gain a new request field.
- `capabilities`: v7, because readiness gains profile/WebM-specific signals.
- `materialization`: v15 and `replay-bundle`: v12, because content-source
  evidence records the selected muxing profile.

No manifest, report, observed-state, or divergence schema bump is needed because
the probe-visible media shape is unchanged.

## Validation Matrix

MKV profile assets:

- `container: mkv`
- existing supported video codecs remain valid: `h264`, `h265`, `hevc`
- existing audio rules remain valid
- `matroska_muxing_profile` cannot be combined with
  `video.resolution_sequence`

WebM profile assets:

- `container: webm`
- `matroska_muxing_profile` is required
- `video.codec: vp9`
- no audio streams
- no subtitle tracks
- no HDR, color signaling, interlaced, VFR, or resolution-switch video options

WebM without a muxing profile is rejected. That keeps the WebM work limited to
the issue's parser-profile surface instead of creating a general WebM output
mode.

Audio-only track assets reject `matroska_muxing_profile`.

## Capabilities

Add readiness fields:

- `ready_for.materialize_matroska_muxing_profiles`: true when FFmpeg, FFprobe,
  and mkvmerge meet minimum versions.
- `ready_for.materialize_webm_video`: true when FFmpeg and FFprobe meet minimum
  versions and FFmpeg advertises `libvpx-vp9`.

Materialize gates:

- any asset with `matroska_muxing_profile` requires
  `materialize_matroska_muxing_profiles`
- any asset with `container: webm` requires `materialize_webm_video`

The existing `mkvtoolnix` `ToolStatus` remains the source of the concrete
mkvmerge path/version.

## Materialization

Default assets continue to write directly through FFmpeg.

When `matroska_muxing_profile` is set:

1. FFmpeg writes the usual media output to a temporary sibling file.
2. mkvmerge remuxes that temporary file to the final asset path.
3. The FFmpeg invocation is recorded as a prelude invocation.
4. The mkvmerge invocation is the materialized asset's `invocation_index`
   because it creates the final bytes.
5. Probe and hashing run against the final mkvmerge output.

mkvmerge command options:

- common: `--quiet`, `--deterministic <derived-seed>`, `--no-date`,
  `--disable-track-statistics-tags`
- WebM output: `--webm`
- `no_cues`: `--no-cues`
- `dense_cues`: `--cues 0:all`
- `short_clusters`: `--cluster-length 250ms`

The deterministic seed is derived from the resolved run seed, asset id,
container, and muxing profile so repeated runs are byte-stable without reusing
the same mkvmerge random seed across distinct assets.

`dense_cues` uses `--cues 0:all` because the existing FFmpeg builder maps the
primary video stream first for every video asset. The mkvmerge command builder
must keep that invariant local by documenting that track id `0` is the video
track in its own tests; if a future builder changes stream order, the mkvmerge
test fails before cue density silently applies to the wrong track.

## Replay Evidence

Add `ContentTrackKind.MUXING` and muxing-profile evidence fields:

- `matroska_muxing_profile`
- `container`

The evidence provider is `builtin-mkvmerge`, source is the profile value, and
the recipe digest includes the profile, container, asset id, resolved seed, and
derived mkvmerge seed. Changing the profile changes materialization and replay
evidence.

## Tests

Contract tests:

- scenario accepts all profile enum values
- schema-version constants reflect v22/v15/v12/v7 bumps
- materialization/replay content-source evidence round-trips muxing profile
- capabilities v7 round-trips new readiness fields

Validation tests:

- MKV accepts all profiles
- WebM accepts VP9 video-only profiles
- profile rejects MP4 and audio-only track assets
- WebM rejects H264/AAC/subtitles/HDR/interlaced/VFR/color signaling
- resolution-switch rejects muxing profile

Command/unit tests:

- FFmpeg builder accepts WebM VP9 without unused x264/x265 preset flags
- mkvmerge command builder emits expected common/profile-specific args
- synthesis threads FFmpeg prelude, mkvmerge final invocation, and muxing
  evidence
- capability gates reject missing mkvmerge or missing VP9 encoder

Real smoke tests:

- skip when FFmpeg/FFprobe/mkvmerge/mkvinfo are unavailable
- materialize MKV `no_cues`, `dense_cues`, and `short_clusters`
- materialize WebM VP9 `short_clusters`
- parse `mkvinfo --all` output with concrete markers:
  - `no_cues`: no `+ Cues` element and no `(KaxCues)` seek entry
  - `dense_cues`: more than one `+ Cue point` for a one-second 24 fps file
  - `short_clusters`: more than one top-level `+ Cluster` for a one-second file

## Out of Scope

- General WebM audio support, including Opus/Vorbis recipes.
- MP4 muxing options.
- Timeline events that mutate muxing profiles after initial materialization.
- Persisting cue/cluster details in manifest or observed-state contracts.
