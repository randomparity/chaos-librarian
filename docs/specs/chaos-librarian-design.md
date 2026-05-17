# Chaos Librarian Design

## Purpose

Chaos Librarian is a separate test-tool development track for generating and
mutating synthetic media libraries. Its goal is to provide a fast, replayable,
high-signal test surface for scanners, watchers, media probes, durable identity,
bundle tracking, reconciliation, and daemon behavior.

Testing against real personal libraries is slow, hard to reproduce, and often
does not contain the edge cases needed for regression testing. Chaos Librarian
creates those conditions intentionally.

The tool models external library activity. It does not know the application
database schema and does not decide expected media-policy outcomes. It emits a
neutral oracle journal and manifests that the application under test can compare
against its own observed state.

## Selected Approach

Use a scenario-driven library simulator.

The tool has a library core plus a CLI frontend. The implementation language is
not fixed by this spec. Python is a strong early candidate because it is quick
to iterate and has mature orchestration, YAML, subprocess, and media-adjacent
libraries. Rust remains a valid future option if shared binaries or workspace
integration become more valuable.

The stable contract is:

- scenario file format
- manifest schema
- oracle journal schema
- CLI commands
- exit codes
- fixture directory layout

The main application consumes the outputs. It should not depend on internal
Chaos Librarian types or implementation language.

## Design Principles

- Deterministic replay comes first.
- Open-ended fuzzing can be added later, but fuzz runs must emit replay bundles.
- The tool models user-visible library activity, not project internals.
- Plan-only mode validates scenario design before real media is generated.
- Materialize mode creates real media files using available tools.
- Step-driven execution is the default for automated tests.
- Wall-clock execution supports daemon/watch/reconciliation soak tests.
- Generated media is valid but diverse in V1.
- Corruption and malformed media are follow-on profiles.
- Content sources are pluggable.
- Mutations are explicit scenario events, not hidden background randomness.
- The oracle is neutral and app-independent.

## Relationship To Synthetic Providers

Synthetic providers exercise the control-plane worker protocol without real
media files. Chaos Librarian exercises real filesystem and media-library
conditions.

Synthetic providers answer:

> Does the scheduler, worker protocol, lease model, and provider contract work?

Chaos Librarian answers:

> Does the application correctly observe and reconcile a changing media library?

Both are needed. Synthetic providers are faster and isolate control-plane logic.
Chaos Librarian is closer to real user activity.

## Execution Modes

### Plan-Only Mode

Plan-only mode validates a scenario and writes the oracle outputs without
creating media files.

Outputs:

- parsed scenario copy
- replay bundle
- initial manifest
- planned current manifest
- planned journal
- validation report

Uses:

- quick TDD
- scenario review
- schema tests
- agent-driven fixture authoring

### Materialize Mode

Materialize mode creates real files using available tools. It uses the same
scenario model as plan-only mode.

Outputs:

- generated library directory
- initial manifest
- current manifest
- append-only journal
- per-asset reports
- materialization diagnostics
- replay bundle

Uses:

- integration tests
- media probe tests
- scanner and watcher tests
- daemon churn tests

### Step Mode

Step mode applies timeline events only when the test asks for the next step.

Example:

```text
chaos-librarian step fixtures/run-001 --next --json
```

Step mode is deterministic and preferred for automated tests that need precise
assertion points.

### Wall-Clock Mode

Wall-clock mode applies timeline events over time.

Example:

```text
chaos-librarian run scenario.yaml --out fixtures/run-001 --duration 90s --speed 10x --json
```

Wall-clock mode is useful for daemon, watcher, and reconciliation tests.

The journal records both logical time and wall-clock time.

## CLI Contract

Initial commands:

```text
chaos-librarian validate scenario.yaml --json
chaos-librarian plan scenario.yaml --out fixtures/run-001 --json
chaos-librarian materialize scenario.yaml --out fixtures/run-001 --json
chaos-librarian run scenario.yaml --out fixtures/run-001 --duration 90s --json
chaos-librarian step fixtures/run-001 --next --json
chaos-librarian replay fixtures/run-001/replay.json --out fixtures/replay-001 --json
chaos-librarian inspect fixtures/run-001 --json
chaos-librarian clean fixtures/run-001 --json
```

All commands must support JSON output. Human-readable output can be added, but
JSON is the stable contract for agents and tests.

## Fixture Directory Layout

Each run writes a self-contained fixture directory:

```text
run/
  scenario.yaml
  replay.json
  manifest.initial.json
  manifest.current.json
  journal.jsonl
  validation.json
  materialization.json
  reports/
    assets/
      asset_001.json
    works/
      work_001.json
    variants/
      variant_001.json
    bundles/
      bundle_001.json
  library/
    movies-hd/
    movies-4k/
    archive/
    staging/
```

`journal.jsonl` is the append-only truth stream. `manifest.current.json` is a
derived convenience snapshot. Reports are derived artifacts for humans and
agents.

## Scenario Format

The scenario format should be a compact YAML or TOML document. YAML is a good
default for readability, but the spec does not require a final choice yet.

Example shape:

```yaml
schema_version: 1
scenario_id: identity-move-rename
seed: 42
duration_scale: short

library:
  roots:
    - id: movies_hd
      path: movies-hd
    - id: movies_4k
      path: movies-4k

works:
  - id: work_blazar
    title: "Synthetic Blazar"
    variants:
      - id: variant_hd
        label: hd
        bundle:
          id: bundle_hd
          assets:
            - id: asset_hd_main
              role: primary_video
              container: mkv
              duration_seconds: 12
              video:
                source: mandelbrot
                codec: h264
                resolution: 1080p
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
              subtitles:
                - codec: srt
                  language: eng
                  mode: sidecar

timeline:
  - id: move_001
    at: 2s
    action: move_asset
    target: asset_hd_main
    to: movies-hd/Synthetic Blazar (HD).mkv
  - id: reencode_001
    at: 5s
    action: reencode_video
    target: asset_hd_main
    resolution: sd
    codec: h264
  - id: downmix_001
    at: 7s
    action: reencode_audio
    target: asset_hd_main
    from_channels: "5.1"
    to_channels: stereo
```

Scenario IDs are stable within a scenario. They become the oracle frame of
reference.

## Oracle IDs

Chaos Librarian assigns stable IDs:

- `work_id`
- `variant_id`
- `bundle_id`
- `asset_id`
- `version_id`
- `location_id`
- `sidecar_id`
- `mutation_id`

These are not application IDs. They are ground-truth references for test
adapters.

Example divergence report:

```text
expected oracle asset_001 to map to one app file_asset_uid
observed two app file_asset_uids after mutation move_004
```

## Oracle Journal

The oracle journal is append-only JSONL. Each event records:

- event ID
- scenario ID
- run ID
- logical time
- wall-clock time
- action
- target IDs
- input versions
- output versions
- affected locations
- expected current state delta
- toolchain information when materialized

The journal should be enough to reconstruct the expected state at any logical
time.

## Manifest Model

The manifest describes current expected library state. It includes:

- works
- variants
- bundles
- assets
- versions
- locations
- tracks
- sidecars
- hashes when materialized
- media facts when known
- mutation history references

The manifest does not describe expected application policy outcomes. It describes
external library reality.

## Reports

Per-file reports should show:

- initial state
- version history
- path history
- track history
- sidecar history
- mutation history
- current state

Example:

```text
asset_ref: asset_001
initial:
  path: movies-hd/A.mkv
  container: mkv
  tracks: [...]
history:
  - t=0s created
  - t=4s moved path
  - t=8s video reencoded 1080p -> sd
  - t=12s audio downmixed 5.1 -> stereo
  - t=16s subtitle sidecar added
current:
  path: movies-sd/A.mkv
  versions: [...]
  sidecars: [...]
```

## Content Sources

V1 content sources should be fast and deterministic.

Video:

- Mandelbrot
- test pattern
- color bars
- solid color
- noise

Audio:

- sine wave
- silence
- pink noise
- channel identity tones
- simple speech-marker tones

Subtitle:

- generated SRT
- generated ASS
- empty subtitle fixture
- simple malformed subtitle fixture for validation-only scenarios

Metadata:

- generated titles
- generated languages
- generated external IDs
- generated NFO
- generated poster fixtures

Later content sources:

- public-domain clips
- sampled fixture clips
- frame fingerprint fixtures
- TTS
- public-domain speech
- multilingual phrase packs
- real subtitle corpus
- translated subtitles
- TVDB/Radarr-style exports
- malformed real-world metadata fixtures

Each source receives a seed and recipe and returns generated content plus facts
for the oracle journal.

## Media Diversity Goals

Generated corpora should cover:

- short durations by default
- varied but valid durations
- multiple containers: MKV, MP4, WebM, and later AVI
- multiple video codecs when tools support them
- multiple audio codecs when tools support them
- multiple subtitle codecs and sidecar modes
- multi-audio files
- multi-subtitle files
- default and forced subtitle flags
- commentary labels
- missing or ambiguous language tags
- duplicate track titles
- container metadata
- sidecar metadata
- primary media plus bundle sidecars

Short clips should dominate to keep tests fast. Longer clips can be opt-in for
performance and progress tests.

## Mutation Model

Mutations are explicit timeline actions.

Filesystem mutations:

- add file
- slow copy file
- move file
- rename file
- delete file
- archive file
- move between roots
- create sidecar
- remove sidecar
- update sidecar

Media mutations:

- remux container
- reencode video
- reencode audio
- downscale resolution, such as 1080p to SD
- downmix audio, such as 5.1 to stereo
- change codec
- change bitrate
- add track
- remove track
- reorder tracks
- edit language metadata
- edit default/forced flags
- edit commentary labels
- convert subtitle format
- embed sidecar subtitle
- extract embedded subtitle to sidecar

Identity and variant mutations:

- create duplicate asset
- create HD and 4K variants for the same work
- replace a primary video with a better version
- add fallback variant
- move variant to a different root

Each mutation updates the oracle journal and current manifest.

## Mutation Pipeline

The mutation pipeline should be extensible:

```text
base recipe
  -> content source
  -> containerizer
  -> metadata mutator
  -> track mutator
  -> location mutator
  -> optional interceptors
  -> oracle journal
```

Future bump-in-the-wire interceptors:

- truncate file during copy
- corrupt container header
- corrupt one stream packet range
- write invalid duration metadata
- remove sidecar after event
- delay rename commit
- hold file open
- alter mtime without changing content
- simulate network filesystem lag
- produce intentionally wrong oracle hash for negative adapter tests

Corruption and malformed-media scenarios are not V1 defaults. They should be
explicit profiles so early failures remain easy to interpret.

## Materializer Backends

The first materializer should use local command-line tools when available:

- FFmpeg / ffprobe
- MKVToolNix when needed for track and metadata operations

The tool should expose capability detection:

```text
chaos-librarian inspect-tools --json
```

Scenarios should be validated against available capabilities before
materialization. Plan-only mode should not require media tools.

## First Scenario Pack

### Identity Move/Rename

Create a small library, move files between roots, rename files, and preserve
content. This targets durable identity and path reconciliation.

### Version Evolution

Create a 1080p file, reencode to SD, downmix audio, and update metadata. This
targets file-version history and media snapshot changes.

### Bundle Sidecars

Create primary video plus external subtitles, poster, and NFO. Rename or move
them together. This targets bundle membership and sidecar reconciliation.

### Duplicate/Variant

Create one work with HD and 4K variants plus a duplicate HD encode. This targets
variant modeling and duplicate-candidate evidence without expecting app policy
outcomes.

### Active Library Churn

Run timed adds, slow copy, modify, delete, move, and sidecar creation over 60 to
90 seconds. This targets daemon watching, file stability, and reconciliation.

## Development Track

This track should run alongside the main control-plane implementation.

### CL Sprint 0: Scenario Contract

Deliverables:

- scenario schema draft
- oracle journal schema
- manifest schema
- fixture directory layout
- CLI command contract
- plan-only validator
- sample first scenario pack in plan-only mode

Exit criteria:

- Scenarios validate without media tools.
- Plan-only output is deterministic for a fixed seed.
- Replaying a plan-only scenario produces identical manifests and journal.

### CL Sprint 1: Core Library And CLI

Deliverables:

- library core
- CLI frontend
- deterministic RNG and ID allocation
- scenario parser
- timeline engine
- step mode
- inspect command
- clean command
- JSON output and exit codes

Exit criteria:

- Tests can advance scenario steps manually.
- The oracle journal records each step.
- Per-asset reports are generated from journal state.

### CL Sprint 2: Real Media Materialization

Deliverables:

- tool capability detection
- FFmpeg materializer for simple valid clips
- ffprobe-based fact verification
- video sources: Mandelbrot or test pattern, color bars, solid color
- audio sources: sine, silence, channel identity tones
- generated SRT sidecars
- materialization diagnostics

Exit criteria:

- Materialized files probe successfully.
- Manifests include hashes and probed facts.
- Plan-only and materialized runs share the same logical oracle IDs.

### CL Sprint 3: Mutation Materialization

Deliverables:

- move/rename/delete/slow-copy mutations
- container remux mutation
- video reencode mutation
- audio reencode/downmix mutation
- metadata edit mutation
- sidecar add/remove/update mutation
- wall-clock run mode

Exit criteria:

- The first scenario pack can run against a real directory.
- Step and wall-clock modes produce equivalent logical journals for the same
  scenario.
- A replay bundle reproduces the same mutation sequence.

### CL Sprint 4: Integration Harness

Deliverables:

- adapter contract for applications under test
- comparison report format
- examples for scanner/prober/watcher tests
- daemon churn test recipe
- CI guidance for short and extended runs

Exit criteria:

- A test adapter can compare app-observed state against oracle state.
- Divergence reports identify asset, mutation, and expected/current state.
- Short runs complete quickly enough for regular development.

### CL Sprint 5: Extended Profiles

Deliverables:

- corruption interceptor framework
- malformed-media profiles
- public-domain/TTS content source hooks
- larger performance profiles
- network filesystem lag profile
- duplicate/variant expansion pack

Exit criteria:

- Corruption remains opt-in.
- Every fuzz or randomized run emits a replay bundle.
- Extended profiles can be excluded from fast CI.

## Non-Goals For V1

- Predicting application policy outcomes.
- Depending on the main application's database schema.
- Requiring TTS.
- Requiring public-domain media downloads.
- Generating corrupt media by default.
- Open-ended randomness without replay.
- Full replacement for real-world library testing.

## Open Decisions For Implementation Planning

- Final implementation language.
- YAML versus TOML for scenario files.
- Exact JSON schemas.
- Minimum external tool versions.
- Whether materialized media should use only FFmpeg in early versions or also
  require MKVToolNix.
- Packaging and distribution strategy.

