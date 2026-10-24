# Bounded adversarial track dispositions

## Authority and outcome

Issue #245 under #244, scope identity `q245-ebe67ffd`, freezes this slice.
Authority: [approved scope](https://github.com/randomparity/chaos-librarian/issues/245#issuecomment-6390345272).
On 2026-10-24 the operator approved nullable default/forced fields on audio and
subtitle tracks, MKV video with up to eight audio and eight embedded UTF-8 SRT
tracks, SD at most 30 seconds, rejection before publication, and legacy omission behavior.
Full-spec, M, fixed design denominator 250; baseline `5a581f4`.
This design extends phase-A synthesis; it adds no mutation framework or selection policy.
Decision record: [ADR 0014](../../adr/0014-static-track-dispositions.md).

Success means real encoded output demonstrates multiple defaults, zero defaults,
and default+forced together in both audio and embedded subtitle streams; the
scenario/replay retain intent and the manifest retains probed facts. The existing
generic comparison detects changed audio and subtitle flags in observed state.

Exclusions and owners remain unchanged: misleading metadata → #246; structural
truncation/targeting → #247; seeded scheduling, aggregate corpus, cross-family
budgets and combined CI → #248; selection/precedence/repair/recovery policy → consumer
maintainers; exhaustive formats/codecs and a general mutation framework → future
operator-authorized work outside #244. No owned deferrals.

## Global Constraints

Python >=3.13; existing dependencies only; no toolchain floor changes.
Use existing argv-only subprocesses, containment checks, synthesis owners and replay format.
Preserve absolute imports, frozen extra-forbid scenario models and bare Final version constants.
No new CLI command or timeline action. Plans stay private and are never committed.
Host architecture does not define supported targets; retain the orchestrator's attunement targets.

## Contract and bounded matrix

Add `default: bool | None = None` and `forced: bool | None = None` to
AudioTrack and SubtitleTrack. Null and omitted mean unspecified, not false intent.
A feature asset has at least one non-null disposition or an embedded subtitle.
Existing assets without either trigger retain their existing builder behavior.
Explicit true/false is authoritative and must be confirmed after encoding.

Opt-in is asset-wide: for a feature asset, both
flags must be explicit booleans on every audio and embedded subtitle track in that
asset. Reject partial fields and mixed explicit/omitted tracks with an actionable
message naming the missing field. Sidecars remain unflagged. This strict policy
was approved by the orchestrator's operator decision relay on 2026-10-24 after
confirming that an explicit subtitle disposition changes unflagged audio defaults.
Write complete dispositions for each declared stream: true flags joined with `+`,
an empty set `0`, plus audio `comment` for commentary roles. No null is coerced to
false intent. Newly supported embedded subtitles require complete flags as well.
Existing all-omitted assets without embedded tracks retain their original behavior.
Post-encode intent checks apply to the complete explicit feature track set.

Supported feature assets are movie/episode MKV, H.264, `resolution=sd`, finite
`0 < duration_seconds <= 30`, existing generated video sources, 0–8 audio tracks
(AAC, existing source/channel/sample-rate matrix), and 0–8 embedded subtitle tracks
(`codec=srt`, `source=generated_srt`, `encoding=utf8`, `timing_profile=normal`).
At least one explicit flag or embedded track is required to enter this route.
Existing sidecars may coexist without dispositions and keep their previous recipes.
Reject disposition fields on sidecars or burned subtitles, even when false.
Reject non-null audio sample_format in this feature (the video builder does not
honor it), mux profiles, embedded chapters/cover art, mp4 placement, imported or
content-linked feature assets, and non-null vfr/field/color/HDR/resolution-sequence
video options. Flags on audio-only, MP4 or WebM assets are unsupported.
Reject phase-B reencode_video, reencode_audio, remux_container, embed_subtitle and
extract_subtitle, edit_metadata and write_invalid_duration_metadata targeting a
feature asset before phase A; these paths have no
approved preservation contract. Other existing timeline behavior is unchanged.
These are slice matrix limits under the delegated scope, not new epic exclusions.

Semantic validation reports E_MATERIALIZE_UNSUPPORTED at the offending field;
materializer preflight independently enforces the same matrix before allocating
or publishing a run. Typed direct callers receive UnsupportedMaterializationError.
Pass the complete Asset from run_setup._preflight_assets to typed preflight so
duration, content links and asset-level options are available before allocation.
Reuse the matrix evaluator for raw validation, typed preflight and direct synthesis.
Keep structural boolean validation in the scenario model and materialization
matrix constraints in validation/preflight rather than rejecting plan-only authoring.

## Data flow and ownership

Extend existing ffmpeg.build_command with subtitle declarations and resolved inputs;
explicitly map one stream per generated input in declaration order. Use output
stream-type indices for metadata/dispositions. No language-based selection or
track deduplication: two embedded tracks may share a language.
Synthesis renders each embedded SRT with existing subtitle_payload_bytes into its
TemporaryDirectory using numeric filenames, then supplies FFmpegInput objects.
Add `-c:s srt`, per-stream language, and disposition arguments. Do not route these
through timeline embedding. write_sidecars must filter mode=sidecar before naming,
skipping, writing or hashing. Existing engine/path sidecar filtering remains.

Generate finite inputs and set an output duration limit for this feature. Avoid
`-shortest` for this route: short subtitle cues must not cut the audio/video short.
Retain existing behavior in the legacy builder branch. Feature output uses
`-fs 67108864`; size >= this threshold is a failure even if FFmpeg returns zero.
The limit can overshoot by an encoder/mux packet; it is a stop threshold, not an
exact filesystem quota. Normal supported inputs remain far below it. Nothing at
or beyond the threshold is accepted or included in a completed manifest.

The existing shared subprocess boundary gets an optional combined captured-output
budget. Feature encode and probe calls set 1,048,576 bytes; legacy callers retain
their defaults. Drain both pipes incrementally in fixed-size chunks, enforce the
existing timeout, and kill/reap on budget excess. Keep the last 2 KiB of stderr and
an explicit output-limit diagnostic; never truncate a probe JSON payload and parse
it as success. Do not use quiet logging as a claimed byte bound. No shell is used.
A bounded branch can use standard-library Popen/selectors on the project's Unix
hosts; if attunement declares Windows, use portable pipe readers instead.
The capture budget is a memory/output-consumption bound with one read-chunk slack,
not a promise about bytes a failed process wrote into a kernel pipe.

Probe retains default/forced for audio using the existing subtitle parsing helper;
missing/malformed flags remain null. ProbedStream comments/docs cover both kinds.
After probing a feature asset, require expected audio/subtitle counts and order,
then compare explicit requested flags against actual values; missing is a mismatch.
Mismatch, timeout, budget excess, cap attainment or parse failure stops publication
through existing materialization errors. Preserve invocation and diagnostic evidence;
clean private subtitle inputs via TemporaryDirectory on success and failure.
Partial run artifacts follow existing failed-run handling; no claim of transactional
filesystem rollback or success manifest for a failed asset is introduced.

Requested flags live in the scenario serialized into replay. Actual flags live in
ProbedMedia and are copied into the manifest by existing augmentation. Do not stamp
requested booleans into probe fields. Replay re-encodes/re-probes and checks intent;
compare normalized intent/evidence, not timestamps, private paths or cross-version
media hashes. Record existing tool/version/command evidence. No new evidence model.

Bump scenario 33→34 for author fields, manifest 10→11 for audio flag semantics,
replay-bundle 12→13 for embedded scenario/manifest semantics, asset-report 9→10 for
embedded probed-media semantics, and observed-state 4→5 for observed audio flags.
Update matching Literal declarations, emitters, fixtures, version docs and generated
schema exports together. Materialization has no new field or embedded ProbedStream;
its version stays 17. Confirm the schema dependency closure during export.

## Failure model

1. Actors/deployments: local operators and CI supply scenario YAML to installed
   ffmpeg/ffprobe on attuned project targets; tool executables are trusted, media
   metadata and tool output are untrusted. No hosted multi-tenant boundary is added.
2. Must prevent: silent default normalization, sidecar flag loss, dropped embedded
   streams, inferred intent presented as observations, unsupported combinations
   reaching publication, unbounded feature input dimensions/capture memory, and
   successful-looking replay with missing disposition evidence. These follow from
   #245 output, bounds and replay criteria and the approved field interface.
3. Accepted: media bytes vary between tool versions; installed muxers may reject
   requested flags, which is an actionable failure rather than supported output;
   process/disk failures can leave a failed run per existing recovery semantics;
   -fs has packet slack. Stream flag probing proves container metadata, not decoding.
4. Covered elsewhere: selection policy by consumers; adversarial metadata by #246;
   structural corruption by #247; combined scheduling/CI by #248; existing path
   containment and failed-run handling by repository guardrails.

## Threat model

- Added boundaries: generated private subtitle files into FFmpeg; new scenario
  flags into argv. Widened boundaries: static embedded-stream counts and captured
  encode/probe output. Local scenario authors may submit extreme inputs or labels.
- Controls: finite duration, SD, track count and closed codec/recipe matrix before
  work; numeric private filenames; existing containment; argv-only invocation;
  declaration-index maps; FFmpeg duration/size stop and timeout; incremental capture
  cap; explicit intent verification against independently parsed output.
- Language metadata uses a single argv value, never an option splice or shell;
  malformed output fails through existing ProbeParseError with bounded diagnostics.
  Errors identify operation/field/limit and retain sanitized tool evidence under
  existing public-write rules. No external downloads or executable paths are added.
- Out of scope: malicious installed binaries, OS-wide resource isolation, service
  authorization, and atomic crash recovery. This is a local tool, not a sandbox.

## Validation and delivery

The private implementation plan inventories focused tests for contracts, matrix,
argv, subtitle isolation, process limits, actual probe retention, comparison, and
real encode/replay. Real tests exercise two tracks of each kind with all-default,
no-default and default+forced, plus partial/mixed rejection and commentary. Missing required
local tools is a reported blocker, not a passing skipped acceptance criterion.
Use short media for normal tests; validate 8/9 track and 30/>30 second boundaries
without repeatedly encoding maximum-size assets. Include one real eight-stream
boundary case per type at short duration and encode/probe actual duration.
Run relevant lint/type/schema gates, contract fixture corpus and focused functional
tests; report their exit codes. New tests must fail on a controlled flag-loss fault.
Document this matrix, null semantics and replay limits in consumer/capability guidance.
No full unrelated functional suite or new combined CI workflow is part of this slice.
