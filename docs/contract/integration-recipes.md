# Integration Recipes

These recipes describe consumer-neutral adapter usage. They intentionally avoid
application database details.

## Scanner Final-State

1. Run `chaos-librarian materialize scenario.yaml --out run-dir`.
2. Scan `run-dir/library/`.
3. Export `observed-state.json` with `observed_ref` and `current_path` for each
   observed asset.
4. Run:

```bash
chaos-librarian compare run-dir observed-state.json --mode final-state --json
```

Exit `0` means the scanner final state matches. Exit `6` means read the
divergence report.

## Prober Final-State

Use the scanner recipe, but include `content_hash` and `probed` for each asset.
The adapter compares hashes only when both sides supply them and compares probed
media only when both sides supply `probed`.

## VOOM CI Scenario Pack

The `tests/fixtures/scenarios/voom-ci/` pack gives consumer CI a stable set of
small fixtures that map to common scanner, prober, transcode policy, rescan,
and malformed-media checks. The fixtures stay consumer-neutral; VOOM-specific
exporters still own application database reads and policy assertions.

| Fixture | Consumer assertion | Command | Capability gate |
| --- | --- | --- | --- |
| `tests/fixtures/scenarios/voom-ci/static-library-baseline.yaml` | Scanner/prober final state contains H.264 MP4, H.264 MKV, audio layout, and sidecar subtitle evidence. | `materialize` then `compare --mode final-state` | `ready_for.materialize_static` |
| `tests/fixtures/scenarios/voom-ci/h264-transcode-candidate.yaml` | HEVC policy can select H.264 MP4 and MKV inputs as transcode candidates. | `materialize` then consumer policy execution | `ready_for.materialize_static` |
| `tests/fixtures/scenarios/voom-ci/hevc-noop.yaml` | The same HEVC policy treats an HEVC MKV input as already compliant. | `materialize` then consumer policy execution | `ready_for.materialize_hevc_video` |
| `tests/fixtures/scenarios/voom-ci/single-step-media-mutation.yaml` | A single deterministic reencode changes final probe/hash evidence for rescan loops. | `run --duration 2s --speed 20x` for live watchers, or `plan`/`step` for oracle-only stepping | `ready_for.materialize_media_mutations` |
| `tests/fixtures/scenarios/voom-ci/malformed-media-header.yaml` | Malformed-media handling reports stable corruption metadata and expected adapter guidance. | `materialize` then inspect `materialization.json.corruption_actions[]` | `ready_for.materialize_media_mutations` |

Check gates with:

```bash
uv run chaos-librarian capabilities --json
```

The malformed fixture opts into the `malformed-media` profile in its YAML. There
is no separate `ready_for` field for that profile.

For mutation loops, materialized `step` is plan-only and rejects `materialize`
or `run` directories with `E_STEP_UNSUPPORTED_MODE`. Use `run` when the
consumer needs live filesystem changes, and use `plan` plus `step` only when a
test needs deterministic oracle snapshots without on-disk media.

## Duplicate And Variant Pack

Use this pack when a consumer needs duplicate-candidate and variant-topology
coverage without changing the baseline first-pack fixture:

```bash
chaos-librarian materialize \
  tests/fixtures/scenarios/duplicate-variant-expanded.yaml \
  --out run-duplicate-variant-expanded \
  --json
```

Recommended exports:

- Scanner recipe: export every asset with `observed_ref` and `current_path`.
  Current paths disambiguate the same-label duplicate variants and the duplicate
  assets inside one bundle.
- Prober recipe: add `content_hash` and `probed` for each asset. Equal hashes
  are duplicate-candidate evidence, not a policy command to merge records.
- Topology recipe: add movie, variant, bundle, and asset refs when the consumer
  tracks them. A pathless topology export can surface the ambiguous
  `Synthetic Echo` and `Synthetic Pair` keys, but `current_path: null` still
  means deleted; add paths or hashes before treating the compare result as a
  clean final-state check.

## Domain Hierarchy Fixtures

Movie fixtures use `movies[*]` with an explicit layout. Use `movie_flat` when
assets should land directly below the root path, and `movie_folder` when each
movie should get its own directory.

```yaml
movies:
  - id: movie_quasar
    title: Synthetic Quasar
    layout: movie_flat
    variants: []
series: []
artists: []
```

TV fixtures use `series[*].seasons[*].episodes[*]` with explicit `layout` and
`episode_naming` values. Use `season_folders` for season directories or
`series_flat` when all episode files should live under the series directory.

```yaml
movies: []
series:
  - id: series_atlas
    title: Atlas Station
    layout: season_folders
    episode_naming: sxxexx_title
    seasons: []
artists: []
```

Music fixtures use `artists[*].albums[*].discs[*].tracks[*]` with explicit
`layout` and `track_naming` values. `artist_album_disc` creates disc folders;
`artist_album_flat` keeps tracks under the album directory.

```yaml
movies: []
series: []
artists:
  - id: artist_glass
    name: Glass Harbour
    layout: artist_album_disc
    track_naming: disc_track_number_title
    albums: []
```

Audio-only track assets are track assets with `role: primary_audio`, an audio
container such as `flac`, `mp3`, or `m4a`, no `video` key, and at least one
supported audio stream.

```yaml
schema_version: 37
scenario_id: audio-only-track
seed: 10603
duration_scale: short
library:
  roots:
    - id: music_root
      path: music
movies: []
series: []
artists:
  - id: artist_tone
    name: Tone Lab
    layout: artist_album_flat
    track_naming: track_number_title
    albums:
      - id: album_tone
        title: Calibration
        discs:
          - id: disc_tone_1
            disc_number: 1
            tracks:
              - id: track_tone_1
                track_number: 1
                title: Stereo Sweep
                variants:
                  - id: variant_tone_m4a
                    label: m4a
                    bundle:
                      id: bundle_tone_m4a
                      assets:
                        - id: asset_tone_track1
                          role: primary_audio
                          container: m4a
                          duration_seconds: 5
                          audio:
                            - source: sine
                              codec: aac
                              channels: stereo
                              language: eng
timeline: []
```

## Fuzz Profile Generation

Use fuzz profiles when a consumer needs deterministic variation without
hand-authoring every mutation:

```bash
uv run chaos-librarian generate \
  --profile fuzz-smoke \
  --seed 123 \
  --out fuzz-smoke.yaml \
  --json

uv run chaos-librarian generate \
  --profile fuzz-regression \
  --lane media-rewrite \
  --seed 457 \
  --out fuzz-regression-media-rewrite.yaml \
  --json

uv run chaos-librarian plan fuzz-smoke.yaml --out run-fuzz-smoke --json
```

The generated YAML carries `profiles: ["fuzz-smoke"]` and a `generation` block
with the profile, lane, profile version, seed, and static budget ceilings.
Timeline events are explicit after generation, so downstream commands do not use
hidden randomness. Replay never calls the generator; it reads the scenario source
stored in `replay.json`.

| Lane | Purpose |
| --- | --- |
| `smoke` | Small materialize-safe local scenario. |
| `core-fs` | Moves, renames, delete/add, archive, roots, and slow copy. |
| `media-rewrite` | Video, audio, container, and metadata rewrites. |
| `sidecar-subtitle` | Sidecar create/update/remove plus subtitle extract/embed. |
| `malformed` | Corrupt and malformed media events behind `malformed-media`. |
| `negative-oracle` | Intentional oracle mismatch events. |
| `filesystem-artifact` | Filesystem artifact events such as mtime touches. |
| `network-lag` | Run-mode lag windows for delayed visibility and rename behavior. |
| `tv-topology` | Series, season, and episode hierarchy mutations. |
| `music-topology` | Artist, album, disc, and track hierarchy mutations. |

`fuzz-smoke` is suitable for local and optional fast checks. `fuzz-regression`
is reserved for scheduled or maintainer-dispatched jobs. Regression lane lists
and seed-manifest fixtures should include `tv-topology` and `music-topology`
when validating hierarchy generation.

## Watcher Identity-History

Export either per-asset `path_history` or global `events` for observed path
mutations. Use:

```bash
chaos-librarian compare run-dir observed-state.json --mode identity-history --json
```

This mode still checks final state, then verifies durable identity through
path-affecting lifecycles such as moves, renames, slow copies, and delete/add
restores.

## Network Filesystem Lag

The `network-fs-lag` profile is for `chaos-librarian run`, not `materialize`.
Lag fixtures describe explicit lag events and produce path-state windows.
Those windows include delayed visibility, delayed rename, and held-handle
evidence in `materialization.json.network_lag_actions[]`. Consumers should
compare watcher observations to those recorded windows, not to guessed sleeps
or low-level OS notification ordering.

The catalog run fixture exercises delayed rename, delayed visibility, and
held-handle lag windows under wall-clock execution:

```bash
uv run chaos-librarian run \
  tests/fixtures/scenarios/interceptor-catalog-run.yaml \
  --out /tmp/interceptors-run \
  --duration 2s \
  --speed 10x \
  --json
```

## Daemon Churn

For daemon-style churn tests, use `chaos-librarian run` fixtures when the daemon
needs wall-clock changes. Export observed state after the daemon settles and
compare it with the same command. Run-mode journal digests ignore volatile
`wall_clock_time` during fixture validation.

## Malformed Media

Malformed-media fixtures are opt-in and label their corruption evidence in both
the manifest and materialization report:

```bash
uv run chaos-librarian materialize \
  tests/fixtures/scenarios/malformed-container-header.yaml \
  --out run-malformed-header \
  --json
```

The interceptor catalog materialize fixture exercises the static fixture's
materialize-safe `truncate_file` and `touch_mtime` path:

```bash
uv run chaos-librarian materialize \
  tests/fixtures/scenarios/interceptor-catalog.yaml \
  --out /tmp/interceptors \
  --json
```

Adapters should treat `manifest.current.json` as the oracle for identity,
location, and version lineage. `materialization.json.corruption_actions[]`
records the corruption audit trail, including byte, packet, and metadata
evidence where applicable, and whether ffprobe failed as expected or still
parsed the output.

## Negative Oracle Hash

Use `negative-oracle` fixtures to prove a consumer validates hashes rather than
trusting fixture structure alone:

```bash
uv run chaos-librarian materialize \
  tests/fixtures/scenarios/negative-oracle-hash.yaml \
  --out /tmp/negative-oracle \
  --json

uv run chaos-librarian compare \
  /tmp/negative-oracle \
  observed-state.json \
  --mode final-state \
  --json
```

The observed-state export should include the consumer's actual file hash for
the affected asset. This recipe succeeds when `compare` reports
`D_HASH_MISMATCH` and exits with divergence code `6`; a success exit would mean
the negative-oracle check did not exercise the intended mismatch.

## CI Guidance

Fast CI should run small final-state fixtures with scanner/prober exports and
fail on compare exit `1`, `6`, or `7`. No performance profiles by default run
in this tier. `fuzz-smoke` may run only in a separate selectable job.

| Tier | Trigger | Profile coverage | Recommended coverage |
| --- | --- | --- | --- |
| Fast | Pull request and `main` push | No performance profiles by default; optional `fuzz-smoke`. | Small scanner/prober final-state fixtures. |
| Extended | Scheduled nightly or maintainer dispatch | `performance-smoke`, `performance-scale`, `fuzz-smoke`, `fuzz-regression` | Identity-history watcher fixtures, slow-copy cases, delete/add restore cases, and run-mode churn fixtures. |
| Stress | Manual release-candidate dispatch | `performance-stress` | Long wall-clock runs, cleanup validation, and large-library compare recipes. |

Performance profile labels are accepted by the scenario contract. Extended and
stress jobs must keep capability skips visible in test output and must fail
during setup when the runner lacks the selected profile's required free disk.

### Bounded structural damage

Scenario v36 adds these selectors to existing malformed-media actions:

```yaml
# MP4: erase the moov box type; expected to fail probing.
- id: damage_index
  at: 1s
  action: corrupt_container_header
  target: asset_main
  region: mp4_moov
# On a separate MKV asset, region: mkv_cues erases the Cues element ID.
# On a separate MP3 asset:
- id: truncate_frames
  at: 1s
  action: truncate_file
  target: asset_audio
  boundary: mp3_after_16_frames
```

Opt into `profiles: [malformed-media]`. A structural `region` excludes non-null
`bytes`; `boundary` excludes non-null `keep_bytes`. Existing leading-byte and
absolute truncation forms remain available. These are independent recipes, not
composable damage stages on one asset.

| Selector | Supported generated input | Observed feature proof |
| --- | --- | --- |
| `mp4_moov` | H.264 MP4, `sd`, moov at start or end | Four moov type bytes zeroed; failed probe |
| `mkv_cues` | H.264 MKV, `sd`, ordinary muxing | Four Cues ID bytes zeroed; probe and linear decode succeed |
| `mp3_after_16_frames` | One mono/stereo MP3 track, 44100 Hz | Prefix through 16 complete audio frames; shorter decoded audio |

Inputs must have finite duration in (0,30] seconds; outputs are limited to 64 MiB.
Video permits at most one mono/stereo AAC track. Imports, aliases/links on the
target asset, subtitles, embedded chapters/cover art, advanced video/muxing
profiles and explicit track dispositions are unsupported. The target may have
placement/path/mtime actions, but no second byte mutation. A too-short MP3,
missing moov/Cues, malformed structural lengths, or exhausted parser/tool limits
fails explicitly. Normal static unsupported cells fail before run creation;
byte-dependent resolution failures preserve the target bytes and fail the run.

The parser visits at most 4096 boxes/Segment children. Unknown-size MKV Segment
is allowed; unknown-size children are rejected. Tool captures are capped at
1 MiB, synthesis at 60 seconds and probes at 15 seconds. No container parser
searches payloads for marker strings.

Use `run`, then `replay ... --against ...`, for same-toolchain replay evidence.
The feature tests pair healthy controls with actual changed bytes, independent
format inspection, probe results and decoding for the readable cells. MP3 Xing
metadata can still advertise the original duration after truncation: use frame
counts or decoded samples to establish the shorter prefix. `still_probeable`
alone is never a decodability assertion, and neither outcome prescribes consumer
repair or recovery policy. Tool-version changes need not produce identical bytes.


### Explicit generated adversarial consumer corpus (scenario v37)

Issue #248 combines the supported #245–#247 recipes through existing generation.
Use `generate --profile fuzz-regression --lane adversarial-media --seed 248 --out
adversarial.yaml` (keep the invocation on one shell line). The lane requires an
explicit `--lane`; the normal ten-lane regression cycle and smoke lane are unchanged.
The generation profile remains version 3. Scenario version 37 adds the allowed
lane enum; migrate scenario version 36 inputs to 37. Replay-bundle shape is unchanged.

The curated input is `tests/fixtures/scenarios/fuzz-adversarial-seed-248.yaml`.
It is byte-for-byte the seed-248 generated YAML, not a promise of identical encoded
media across tool versions. `tests/fixtures/fuzz-seeds.yaml` records its gates.
One seed and one generated scenario cover these fifteen recipe cells:

| Family | Cases |
| --- | --- |
| Flags | Two audio and two embedded UTF-8 SRT tracks with multiple defaults; no defaults; default+forced; eight of each with forced-only. First audio retains commentary. |
| Metadata | Filename/NFO/embedded-title disagreement; year 9999; exactly 4096 UTF-8 bytes of Unicode title; Unicode TAB/LF; removal of existing title/year; missing tags; eng/fra audio-label conflict. |
| Structural | MP4 moov damage at start and end; MKV Cues damage; MP3 truncation after sixteen complete frames. |

Budget: eighteen assets/variants under one movie and two music tracks, eleven
events (seven metadata/sidecar and four structural), one NFO, no random filler.
Four flag assets last 0.2 seconds; fourteen others last 2 seconds (28.8 seconds
aggregate authored duration). Video is SD H.264/AAC; MP3 is stereo 44100 Hz;
maximum eight audio and eight subtitle tracks per asset. Three distinct healthy
MP4/MKV/MP3 controls accompany damage. No flag asset is rewritten; each damaged
asset has one byte mutation. The existing regression budget stays at 22 assets,
22 variants and 80 events; no additional scheduler or codec matrix is implied.

Require ffmpeg/ffprobe >=7 and MKVToolNix >=80 for the combined real-tool corpus.
Use `capabilities --json` and the existing equipped-CI capability gate. Existing
synthesis/probe limits apply: 60 seconds synthesis, 15 seconds structural probes,
1 MiB bounded structural captures, 4096 scanned elements and 64 MiB per output
(up to 1152 MiB for eighteen assets). Inspect actual report invocation counts and
output sizes; the fixed corpus uses at most 100 recorded tool invocations per run.
Metadata has at most sixteen fields and 4096 UTF-8 bytes/value; this corpus edits
two fields at most. Feature recipe sections above define unsupported combinations.

`validate`, `materialize`, `run` and `replay --against` use their existing entry
points. `run` has a wall-clock budget, so choose time for all eleven events and
check `replay.json` has `applied_events: 11`; a short budget intentionally produces
a prefix. The equipped integration test controls the monotonic clock boundary to
avoid host-speed truncation while executing real media tools, and separately
executes materialize plus run/replay. It inspects actual flags, tags, languages,
failed MP4 probes, readable MKV and sixteen-frame MP3 output. Feature #247 owns
independent byte-target/decode proof. Do not infer decode success from probe alone.

Requested fields/regions/boundaries remain in the scenario and journal; observed
tags/flags and corruption hashes, byte spans and probe outcomes remain in the
manifest/materialization report. Empty metadata means deletion; observed absent
tags are `{}`, while `null` means unreported. Expected failed MP4 probes are neutral
intentional-corruption evidence and do not fail a successful materialization.
Equipped CI discovers `tests/integration/*_real.py` and rejects skipped tests;
no separate runner is needed. Downstream selection and recovery remain consumer policy.
