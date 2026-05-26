# Chaos Librarian Design

## Purpose

Chaos Librarian is a separate test-tool development track for generating and
mutating synthetic media libraries. Its goal is to provide a fast, replayable,
high-signal test surface for scanners, watchers, media probes, durable identity,
bundle tracking, reconciliation, and daemon behavior in
[voom-v2](https://github.com/randomparity/voom-v2).

Testing against real personal libraries is slow, hard to reproduce, and often
does not contain the edge cases needed for regression testing. Chaos Librarian
creates those conditions intentionally.

The tool models external library activity. It does not know the application
database schema and does not decide expected media-policy outcomes. It emits a
neutral oracle journal and manifests that the application under test can compare
against its own observed state.

Most of the tool is about deterministic, reproducible mutation timelines. The
"chaos" framing applies only to opt-in fuzz and corruption profiles introduced
in later sprints; fuzz runs must still emit replay bundles.

## Selected Approach

Use a scenario-driven library simulator.

The tool has a library core plus a CLI frontend. Implementation language is
**Python 3.13**, with `uv` for environments, `ruff` for lint/format, `ty` for
type checking, and `pytest` for tests, matching the project's global standards.

The stable contract is:

- scenario file format (YAML, schema-validated)
- manifest schema (JSON)
- oracle journal schema (JSONL)
- replay bundle schema (JSON)
- validation report schema (JSON)
- materialization report schema (JSON)
- CLI commands and exit codes
- fixture directory layout

The main application consumes the outputs as JSON via the exported JSON Schema
artifacts shipped alongside the tool. It should not depend on internal
Chaos Librarian Python types, although a Python adapter convenience package is
shipped in a later sprint.

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

If required tools (FFmpeg, ffprobe, MKVToolNix) are missing or below minimum
versions, `materialize` exits non-zero with a structured diagnostic and does
not auto-downgrade to plan-only. Use `chaos-librarian plan` explicitly when
media tools are unavailable.

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

Step mode and wall-clock mode advance the same logical clock and must produce
identical journals (apart from `wall_clock_time` fields) for the same scenario
and seed.

## Time Model

Time is tracked internally as a 64-bit signed integer of nanoseconds since
scenario start (`t=0`). All durations and timestamps share this representation
in both step mode and wall-clock mode.

Scenario authoring uses duration strings parsed into nanoseconds:

| string    | meaning              |
|-----------|----------------------|
| `500ms`   | 500 milliseconds     |
| `2s`      | 2 seconds            |
| `1m30s`   | 90 seconds           |
| `0`       | t=0 (start)          |

Timeline event `at:` values are offsets from scenario start, not from the
previous event. Events with the same `at:` value are applied in declared order.

The journal records both `logical_time_ns` (integer) and, in wall-clock and
materialize modes, `wall_clock_time` (RFC 3339 string). JSON output always
includes precise integer nanoseconds for agent consumers; human-readable
output formats the same value as `1m30s250ms`.

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
chaos-librarian capabilities --json
chaos-librarian clean fixtures/run-001 --json
```

All commands must support `--json` output. Human-readable output may be added,
but JSON is the stable contract for agents and tests.

Exit codes:

| code | meaning                                                |
|------|--------------------------------------------------------|
| `0`  | success                                                |
| `1`  | generic failure                                        |
| `2`  | usage error (bad arguments)                            |
| `3`  | scenario validation failed                             |
| `4`  | required external tool missing or version too low      |
| `5`  | materialization failed (tool ran but produced an error)|
| `6`  | replay diverged from recorded execution                |
| `7`  | filesystem safety violation (containment or sentinel fail) |

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

## Filesystem Safety

Chaos Librarian writes, mutates, and deletes files inside its run directories.
Two contracts protect real user data from being touched by a misconfigured
scenario, a stray symlink, or a wrong `clean` argument.

### Run-Directory Sentinel

Every run directory created by chaos-librarian contains a top-level
`.chaos-librarian-run` JSON file. Its fields:

- `run_id` — matches the `run_id` recorded in the replay bundle
- `schema_version` — sentinel schema version (a separate integer from
  `replay-bundle.schema.json`)
- `created_by` — chaos-librarian version string
- `created_at` — RFC 3339 timestamp; **omitted in plan-only mode**

`plan`, `materialize`, `run`, and `replay` create the sentinel atomically as
part of run-directory creation. These commands refuse to write into a
pre-existing directory unless its sentinel is present and parseable; this
prevents accidental mutation of any directory the tool did not itself create.

### Path Containment

Every path that appears in a scenario — `library.roots[].path`, every
mutation `to:`, every `target:` value that resolves to a path, every sidecar
path — is resolved relative to `<run-dir>/library/`. After `realpath`-style
normalization, the resolved path MUST be a strict subpath of
`<run-dir>/library/`. The tool rejects:

- absolute paths (e.g., `/etc`, `/Users/...`)
- `..` segments that escape `library/`
- symlinks whose targets escape `library/` (resolved at access time, not
  just at scenario load)

Violations fail scenario validation when statically detectable, or fail at
event-execution time for cases like a runtime symlink target. Either way
the command exits with code `7` (see "CLI Contract").

### `clean` Refusal

`chaos-librarian clean <dir>` refuses any directory whose sentinel is
missing, malformed, or whose recorded `run_id` does not match the sentinel
on disk. V1 ships no `--force` flag; recovering from a broken sentinel
requires manual inspection.

### Materializer Boundary

External tool invocations (ffmpeg, ffprobe, mkvtoolnix) only ever receive
paths resolved under `<run-dir>/library/`. The materializer never executes
a scenario step whose resolved path violates containment, even if validation
somehow let it through; this is a defense-in-depth check against scenarios
synthesized at runtime by future profiles.

## Schema Contract

### Source Of Truth

Schemas are authored as Pydantic v2 models under
`src/chaos_librarian/contract/`. A CI job exports them to language-neutral
JSON Schema (draft 2020-12) artifacts under `schemas/*.schema.json`, which is
the public contract consumed by voom-v2 and any other external consumer. CI
fails if a committed JSON Schema artifact does not match what the current
Pydantic models would emit.

### Versioning

Every artifact carries a top-level `schema_version` field (positive integer).

- Version bumps are always breaking; there are no minor versions.
- Readers MUST reject unknown versions with exit code `3`.
- A given chaos-librarian release supports exactly one schema version per
  artifact. Multi-version compatibility shims are explicit non-goals.

### Exported Schema Artifacts

`src/chaos_librarian/schema_export.py` exports the authoritative schema set:

- `scenario.schema.json` — input scenario format
- `manifest.schema.json` — initial and current library state
- `journal.schema.json` — append-only event stream (one entry per JSONL line)
- `replay-bundle.schema.json` — see "Replay Bundle"
- `validation.schema.json` — output of `validate`
- `materialization.schema.json` — materialization diagnostics
- `run-sentinel.schema.json` — `.chaos-librarian-run` sentinel file
- `asset-report.schema.json` — per-asset report under `reports/assets/`
- `work-report.schema.json` — per-work report under `reports/works/`
- `variant-report.schema.json` — per-variant report under `reports/variants/`
- `bundle-report.schema.json` — per-bundle report under `reports/bundles/`
- `capabilities.schema.json` — output of `capabilities`
- `observed-state.schema.json` — consumer input to `compare`
- `divergence.schema.json` — output of `compare`

## Scenario Format

The scenario format is YAML, parsed with `ruamel.yaml` for line-number-aware
error reporting and validated against `scenario.schema.json`.

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
- logical time (integer nanoseconds)
- wall-clock time (RFC 3339, omitted in plan-only mode)
- action
- target IDs
- input versions
- output versions
- affected locations
- expected current state delta
- toolchain information when materialized
- `phase` (required; one of `atomic` | `started` | `progressed` | `committed`
  | `aborted`). Atomic mutations are the default for all single-event
  actions; multi-phase mutations use the other values. The journal schema
  is a discriminated union on `phase` so `temp_path` and `related_event_id`
  are required or forbidden per phase rather than free-floating optionals.
- `temp_path` (required on `started` and `progressed`; forbidden on
  `atomic`, `committed`, `aborted`)
- `related_event_id` (required on `progressed`, `committed`, `aborted`;
  forbidden on `atomic` and `started`)

Sprint 0 defines all three optional fields in `journal.schema.json` even
though only slow-copy uses them in V1. Stabilizing the shape on day one keeps
later multi-phase mutations from forcing a schema version bump.

The journal must be sufficient to reconstruct the expected state at any
logical time.

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

The manifest does not describe expected application policy outcomes. It
describes external library reality.

## Replay Bundle

The replay bundle is a single JSON file (`replay.json`) sufficient to reproduce
a run. Plan-only replays must be bit-identical; materialize replays must be
logically identical (same journal modulo `wall_clock_time` and content hashes
that depend on tool versions).

Contents (fields vary by execution mode so plan-only bundles remain
bit-identical):

- **scenario** (all modes) — verbatim copy of the source scenario YAML
  (string)
- **schema_version** (all modes) — replay-bundle schema version (integer)
- **chaos_librarian_version** (all modes) — tool version string
- **run_id** —
  - *Plan-only:* deterministic UUIDv5 derived from
    `(scenario_content_hash, resolved_seed)` under a fixed chaos-librarian
    namespace UUID. The namespace UUID is a module-level constant in
    `chaos_librarian.contract` and never changes across releases.
  - *Materialize / Run:* random UUIDv4 assigned at run start.
- **created_at** —
  - *Plan-only:* **omitted entirely** (field absent from the JSON; readers
    must treat missing-equals-omitted, not null).
  - *Materialize / Run:* RFC 3339 timestamp of run start.
- **resolved_seed** (all modes) — concrete integer seed, even when scenario
  used `seed: random`
- **execution_trace** (all modes) — ordered list of:
  - every RNG draw (stream name + drawn value)
  - every ID allocation (kind + allocated ID)
  - every materializer invocation when applicable (command line + tool
    version + exit code)
- **toolchain** (materialize only) — versions of ffmpeg, ffprobe,
  mkvtoolnix; platform string

## Reproducibility Guarantees

### Plan-Only

The replay bundle, manifests, and journal are **bit-identical** for the same
scenario + seed across runs and platforms. There are no volatile fields in
plan-only output. This is achievable because `run_id` is a deterministic
UUIDv5 derived from `(scenario_content_hash, resolved_seed)` and `created_at`
is omitted from the serialized JSON (see "Replay Bundle").

### Materialize / Run

The oracle journal and manifest are **logically identical** for the same
scenario + seed on any platform with compatible tool versions. The following
fields are volatile and MUST be excluded from any equivalence comparison:

- `created_at` and any `wall_clock_time` fields on journal entries
- `run_id` (UUIDv4 in these modes)
- content hashes and probed media facts (depend on FFmpeg / codec library
  versions; recorded as descriptive evidence, not as a contract)
- the `toolchain` block

Materialized file bytes and content hashes are descriptive, not contractual.
The manifest records the actual hash produced; replay verifies the hash
against the recorded toolchain, not against an absolute reference.

Adapters and equivalence tests MUST canonicalize artifacts by stripping
these fields before comparison. The canonicalization rule is part of the
public contract and is implemented once in `chaos_librarian.contract` so
external consumers do not re-derive it.

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

Short clips should dominate to keep tests fast. The default first scenario pack
must stay under a 50 MB total materialized size. Longer clips are opt-in for
performance and progress tests.

## Performance Profile Policy

Larger performance profiles are reserved for opt-in scenarios. The scenario
contract accepts the labels below, and validation enforces static source-fixture
ceilings for declared assets, works, variants, bundles, sidecars, and timeline
events.

Reserved labels:

- `performance-smoke`
- `performance-scale`
- `performance-stress`

Budgets are hard ceilings for checked-in profile scenarios and generated run
artifacts:

| Budget | `performance-smoke` | `performance-scale` | `performance-stress` |
| --- | ---: | ---: | ---: |
| Media assets | 40 | 250 | 1,000 |
| Works | 40 | 250 | 1,000 |
| Variants | 60 | 400 | 1,800 |
| Bundles | 8 | 50 | 200 |
| Sidecars | 120 | 750 | 3,000 |
| Timeline events | 160 | 1,200 | 6,000 |
| Materialized bytes under `library/` | 250 MB | 2 GB | 10 GB |
| Wall-clock run duration | 5 minutes | 30 minutes | 2 hours |
| Minimum free disk before run | 1 GB | 8 GB | 40 GB |

Byte budgets use decimal units: 1 MB is 1,000,000 bytes and 1 GB is
1,000,000,000 bytes.

Performance scenarios remain source fixtures, not checked-in materialized
libraries. Generated outputs stay under the caller's run directory and are
deleted by the normal cleanup workflow. Static YAML budgets are validated at
scenario-validation time; materialized-byte, wall-clock-duration, and free-disk
budgets are CI/run preconditions until profile fixtures provide run artifacts.

Performance profile tests may skip only when an explicit required capability is
missing or below the project minimum version, when a future profile-specific
provider is unavailable and reported by `chaos-librarian capabilities --json`,
or when the current CI tier has not opted into the requested profile label. A
skip must name the missing tool, provider, or profile selection. Disk capacity is
an infrastructure precondition, not a capability skip; CI jobs that opt into a
performance profile must provision the profile's minimum free disk and fail
during setup if the runner cannot satisfy it.

CI tiers:

| Tier | Trigger | Allowed profiles | Required gates |
| --- | --- | --- | --- |
| Fast | Pull request and `main` push | No performance profiles by default. | Unit tests, docs tests, schema drift, lint, type check. |
| Extended | Scheduled nightly or maintainer dispatch | `performance-smoke`, `performance-scale` | Fast gates plus materialize/run/compare recipes. |
| Stress | Manual release-candidate dispatch | `performance-stress` | Extended gates plus long wall-clock and cleanup validation. |

Fast CI may add a `performance-smoke` job only if that job is independently
selectable. `performance-scale` and `performance-stress` must never run on every
pull request.

## Fuzz Profile Generation Policy

Fuzz profile generation is opt-in and deterministic. The generator writes normal
scenario YAML with explicit timeline events; it does not add hidden runtime
mutations to `plan`, `materialize`, `run`, or `replay`.

Implemented labels:

- `fuzz-smoke`
- `fuzz-regression`

Generated scenarios carry a top-level `generation` block with the generator
name, fuzz profile, lane, profile version, concrete seed, and selected budget
ceilings. Scenario v11 metadata includes `generation.lane`; the scenario `seed`
must be a concrete integer and must match `generation.seed`. `generation.profile`
must also appear in top-level `profiles`.

`fuzz-smoke` uses the `smoke` lane. `fuzz-regression` is a deterministic lane
suite with `core-fs`, `media-rewrite`, `sidecar-subtitle`, `malformed`,
`negative-oracle`, `filesystem-artifact`, and `network-lag`. CI should shard
these lanes or explicitly select lanes instead of treating `fuzz-regression` as
one monolithic job.

Fuzz budgets are hard static ceilings per generated scenario:

| Budget | `fuzz-smoke` | `fuzz-regression` |
| --- | ---: | ---: |
| Works | 3 | 12 |
| Variants | 4 | 18 |
| Bundles | 4 | 18 |
| Media assets | 4 | 18 |
| Sidecars | 8 | 54 |
| Timeline events | 12 | 80 |
| Materialized bytes under `library/` | 75 MB | 250 MB |
| Wall-clock run duration | 2 minutes | 10 minutes |
| Minimum free disk before run | 500 MB | 1 GB |

Replay never calls the generator. A replay bundle embeds the already generated
scenario source verbatim, so replay is isolated from later generator changes.

## Network Filesystem Lag Profile Policy

Network filesystem lag scenarios are reserved for opt-in watcher fixtures. The
scenario contract accepts the profile label and validates explicit lag events
only when the label is present.

Implemented label:

- `network-fs-lag`

The profile label permits lag-specific events; it never changes existing
timeline action behavior by itself. Lag artifacts require explicit
`network_lag_start` / `network_lag_commit` events so scenario authors can see
which watcher-visible timing artifact is part of the oracle.

Initial event shape:

- `network_lag_start` fields: `effect`, `target`, `after`, and `duration`.
- `network_lag_commit` field: `for`.
- Initial effects: `delayed_visibility`, `delayed_rename`, and `held_handle`.
- The start event must share the referenced event's `at:` value and immediately
  follow that event in resolved order, so the wall-clock runner can preflight
  and intercept the referenced disk effect before it becomes visible.

The lag profile is a wall-clock watcher profile. `run` is the only mode with
live watcher-facing guarantees; `materialize` rejects lag events as unsupported
because a batch materialization cannot expose timing windows to an external
watcher. `plan`, `step`, and run replay may model the logical events and replay
evidence, but they do not guarantee live visibility.

Watcher guarantees are path-state windows, not low-level OS notification
ordering. Delayed visibility keeps new paths absent or existing paths at stale
bytes until commit. Delayed rename keeps the old path visible and the new path
absent until commit. Held-handle tests may assert blocking behavior only when
the provider reports that the host enforced the handle.

## Mutation Model

Mutations are explicit timeline actions.

Most mutations are **atomic**: a single timeline event produces a single
journal entry and an immediate state transition. The timeline is a strict
sequence; events with the same `at:` value are applied in declared order.
External observers (scanners, watchers) may interleave freely with timeline
events.

A small set of mutations are explicitly **multi-phase** — they take real
wall-clock time and expose intermediate filesystem state (temporary paths,
partial bytes) that external observers can see. Multi-phase mutations are
decomposed at the scenario level into a `*_start` event and a `*_commit`
event with stable IDs that reference each other. Each phase emits its own
journal entry. Between start and commit, the manifest records the
in-flight state: the temp path, the bytes written so far when known, and
the eventual final path.

In plan-only mode both phase events fire at their declared `at:` times and
the in-flight manifest snapshot is computed deterministically. In wall-clock
mode, the temporary file is grown over the declared `duration:` between the
two events so watchers can observe a real partial file.

Filesystem mutations:

- add file
- `slow_copy_start` — begins a slow copy. Required fields: `target`, `to:`
  (final path), `temp_path`, `duration:` (wall-clock duration string).
  Emits a journal entry with `phase: started`.
- `slow_copy_commit` — completes a slow copy. Required fields: `for:` (the
  start event's `id`). At `at:` time, atomically renames `temp_path` to the
  final path. Emits a journal entry with `phase: committed`.
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

Implemented bump-in-the-wire interceptor catalog:

- `corrupt_container_header` (`malformed-media`)
- `truncate_file` (`malformed-media`)
- `corrupt_packet_range` (`malformed-media`)
- `write_invalid_duration_metadata` (`malformed-media`)
- `touch_mtime` (`filesystem-artifacts`)
- `network_lag_start` / `network_lag_commit` with `delayed_visibility`
  (`network-fs-lag`)
- `network_lag_start` / `network_lag_commit` with `delayed_rename`
  (`network-fs-lag`)
- `network_lag_start` / `network_lag_commit` with `held_handle`
  (`network-fs-lag`)
- `wrong_oracle_hash` (`negative-oracle`)

Corruption and malformed-media scenarios are not defaults. They are explicit
opt-in profiles so early failures remain easy to interpret.
`write_invalid_duration_metadata` is tag-level corruption: it writes invalid
duration metadata without claiming that the media essence was transcoded or
packet-damaged. `wrong_oracle_hash` fixtures intentionally publish an oracle
hash that does not match the file bytes so `compare` can produce
`D_HASH_MISMATCH` evidence for consumer validation.

## Materializer Backends

The first materializer uses local command-line tools when available:

- FFmpeg / ffprobe
- MKVToolNix when needed for track and metadata operations

Minimum tool versions are recorded in the materialization report and enforced
by `capabilities`. The tool exposes capability detection:

```text
chaos-librarian capabilities --json
```

Scenarios are validated against available capabilities before materialization.
Plan-only mode does not require media tools.

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

Create one work with HD and 4K variants plus a duplicate HD encode. This
targets variant modeling and duplicate-candidate evidence without expecting
app policy outcomes.

The first-pack fixture remains `tests/fixtures/scenarios/duplicate-variant.yaml`
so the baseline scenario set stays stable. The expansion fixture
`tests/fixtures/scenarios/duplicate-variant-expanded.yaml` broadens the same
surface with three explicit cases:

- `Synthetic Echo` has two same-label `hd` variants with identical recipes,
  plus an `sd` variant. This gives adapters duplicate-candidate evidence across
  sibling variants without prescribing merge policy.
- `Synthetic Pair` has one `hd` bundle with two identical primary-video assets.
  This gives adapters duplicate-candidate evidence inside a bundle.
- `Synthetic Ladder` has distinct `1080p` and `sd` variants with supported
  materializer recipes, giving a clean non-duplicate control.

Expected adapter behavior stays neutral: current paths disambiguate the
duplicates, materialized hashes may identify duplicate candidates, and topology
alone can surface the same-label duplicate ambiguity. A topology export without
current paths is not a clean final-state check because `current_path: null`
means the consumer observed the asset as absent.

### Active Library Churn

Run timed adds, slow copy, modify, delete, move, and sidecar creation over
60 to 90 seconds. This targets daemon watching, file stability, and
reconciliation. Wall-clock scenario; lands in Sprint 8.

## Development Track

This track should run alongside the main voom-v2 implementation. Sprints are
sized to land as single PRs.

### Sprint 0 — Repo Skeleton, Schemas, CLI Contract

Contract-only sprint. No runtime behavior.

Deliverables:

- `pyproject.toml` (uv, Python 3.13, ruff, ty, pytest), pre-commit (`prek`)
  config, GitHub Actions CI, `.gitignore`, license headers
- Pydantic v2 models for scenario, journal, manifest, replay bundle,
  validation report, materialization report
- Run-directory sentinel schema (`run-sentinel.schema.json`) authored as a
  Pydantic model and exported as JSON Schema alongside the other artifacts
- Journal schema includes the multi-phase fields (`phase`, `temp_path`,
  `related_event_id`) from day one, even though no V1 mutation other than
  slow-copy uses them
- Path-resolution helper module (`chaos_librarian.contract.paths`)
  implementing the path-containment rules from "Filesystem Safety", with
  unit tests for absolute-path rejection, `..`-escape rejection, and a
  symlink-escape test fixture. Pure function plus tests; no runtime
  materialize wiring in Sprint 0.
- CI job that exports JSON Schema artifacts to `schemas/*.schema.json` and
  fails if committed artifacts diverge from current models
- CLI surface frozen as a Typer app with stub commands that print usage and
  exit non-zero with exit code `1`
- `docs/contract/` containing schema reference, fixture directory layout,
  CLI reference, replay bundle spec, time model
- 3–4 hand-authored sample scenarios under `tests/fixtures/scenarios/`

Exit criteria:

- `pytest` passes (Pydantic round-trip, sample scenario validation,
  Pydantic-to-JSON-Schema equivalence)
- `ty check` is clean
- `ruff check` and `ruff format --check` are clean
- CI is green on a fresh clone

### Sprint 1 — Scenario Parser And `validate` Command

Deliverables:

- YAML loader (`ruamel.yaml`) with line-number-aware errors
- Pydantic-based validation pipeline
- Duration string parser (`parse_duration`) shared with later sprints
- `chaos-librarian validate scenario.yaml --json` produces a validation report
  matching `validation.schema.json`

Exit criteria:

- Every sample scenario from Sprint 0 validates with exit code `0`
- A bank of malformed sample scenarios produces structured errors with exit
  code `3`

### Sprint 2 — Deterministic Core

Deliverables:

- Seeded RNG with per-stream sub-seeds so independent subsystems do not
  interfere
- ID allocator producing stable `work_id`, `variant_id`, `bundle_id`,
  `asset_id`, `version_id`, `location_id`, `sidecar_id`, `mutation_id`
- Logical clock (nanosecond integer) and duration string *formatters*
  (`format_duration_human`, `format_duration_json`). Sprint 2 consumes the
  duration parser shipped in Sprint 1.
- Property tests covering determinism guarantees

Exit criteria:

- Same seed produces identical RNG draws and ID sequences across runs
- Determinism contract is exercised in isolation; downstream sprints consume
  this module

### Sprint 3 — Plan-Only Timeline Engine And `plan` Command

Deliverables:

- Timeline event resolution (validate targets, sort by `at:`, detect ordering
  collisions)
- Plan-only execution: emits initial manifest, planned current manifest,
  planned journal, replay bundle, validation report
- `chaos-librarian plan scenario.yaml --out fixtures/run-001 --json`

Exit criteria:

- Plan-only output is bit-identical for a fixed seed across runs
- Replay of a plan-only bundle reproduces the same artifacts byte-for-byte
- First scenario pack (excluding Active Library Churn) executes successfully

### Sprint 4 — Step Mode, Inspect, Clean, Replay

Deliverables:

- `chaos-librarian step` advances N events from a prepared fixture
- `chaos-librarian inspect` reads a run directory and prints JSON
- `chaos-librarian clean` removes a run directory safely
- `chaos-librarian replay` re-runs from a replay bundle
- Per-asset, per-work, per-variant, per-bundle reports under `reports/`

Exit criteria:

- Step mode and plan mode produce identical journals for the same scenario
- Replay reproduces a prior run; divergence exits `6` with a structured diff

### Sprint 5 — Materializer Capability Detection And Simple Sources

Deliverables:

- `chaos-librarian capabilities` detects ffmpeg, ffprobe, mkvtoolnix versions
- Content sources: Mandelbrot, color bars, solid color, sine, silence,
  channel-identity tones, generated SRT
- Materializer for short valid clips without mutations

Exit criteria:

- Materialized files probe successfully with ffprobe
- Manifest includes content hashes and probed media facts
- Plan-only and materialized runs share the same logical oracle IDs

### Sprint 6 — Filesystem Mutations

Deliverables:

- Mutations: add, move, rename, delete, slow copy, archive, move between roots
- Sidecar mutations: create, remove, update
- Per-asset report includes path history

Exit criteria:

- Identity Move/Rename scenario runs end-to-end on a real directory

### Sprint 7 — Media Mutations

Deliverables:

- Mutations: container remux, video reencode, audio reencode, downmix,
  resolution downscale, codec change, bitrate change, track add/remove/reorder,
  metadata edits, default/forced flag edits, commentary edits, subtitle convert,
  subtitle embed/extract

Exit criteria:

- Version Evolution and Bundle Sidecars scenarios run end-to-end

### Sprint 8 — Wall-Clock Mode

Deliverables:

- `chaos-librarian run` with `--duration` and `--speed`
- Daemon-friendly scheduling that shares the Sprint 2 clock with step mode

Exit criteria:

- Active Library Churn scenario runs end-to-end
- Step-mode and wall-clock-mode journals are logically identical for the same
  scenario apart from `wall_clock_time` fields
- A replay bundle reproduces a wall-clock run

### Sprint 9 — Integration Harness And voom-v2 Adapter

Deliverables:

- `chaos_librarian.adapter` Python package for consumers
- Comparison report format (`divergence.schema.json`)
- Example test recipes for scanner, prober, watcher
- Daemon churn test recipe
- CI guidance for short and extended runs

Exit criteria:

- voom-v2 can compare its observed state against oracle state
- Divergence reports identify asset, mutation, and expected vs. current state
- Short runs complete quickly enough for regular development

### Sprint 10 — Extended Profiles

Deliverables (may split into multiple PRs):

- Explicit malformed-media opt-in and `corrupt_container_header`
- Public-domain / TTS content source hooks: provider registry, cache policy,
  capability reporting, and replay evidence are implemented; actual downloads
  and TTS providers remain deferred until source-specific issues.
- Larger performance profiles that satisfy the Performance Profile Policy
- Network filesystem lag profile that satisfies the Network Filesystem Lag Profile Policy
- Fuzz profile generation that satisfies the Fuzz Profile Generation Policy
- Duplicate/variant expansion pack

Exit criteria:

- Corruption remains opt-in and clearly labeled
- Every fuzz or randomized run emits a replay bundle
- Extended profiles can be excluded from fast CI

## Mitigations For Late voom-v2 Integration

The formal adapter contract lands in Sprint 9. To catch schema-shape mistakes
earlier, Sprints 1 and 3 ship internal round-trip tests that load emitted
journals and manifests through the Pydantic models and re-serialize them.
These tests do not replace voom-v2 integration; they reduce the risk that
Sprint 9 surfaces structural surprises.

## Non-Goals For V1

- Predicting application policy outcomes.
- Depending on the main application's database schema.
- Requiring TTS.
- Requiring public-domain media downloads.
- Generating corrupt media by default.
- Open-ended randomness without replay.
- Full replacement for real-world library testing.
- Byte-identical materialized files across platforms or tool versions.
- Concurrent / overlapping mutations within the timeline beyond the explicit
  multi-phase pairs (`*_start` / `*_commit`) defined in the Mutation Model.
- Mid-copy renames or other interleaved multi-phase mutations targeting the
  same asset.
- Multi-version schema compatibility within a single chaos-librarian release.

## Resolved Decisions

- Implementation language: **Python 3.13**
- Scenario file format: **YAML** (`ruamel.yaml`)
- Schema source-of-truth: **Pydantic v2** with exported JSON Schema artifacts
- Time model: nanosecond integer internal, duration-string scenario syntax,
  offsets from scenario start, shared clock across modes
- Schema versioning: monotonic integer, breaking bumps, no compatibility shims
- Replay bundle: minimal metadata plus full execution trace
- `inspect-tools` renamed to `capabilities`
- Filesystem safety: run-directory sentinel (`.chaos-librarian-run`) plus
  path containment under `<run-dir>/library/`; exit code `7` on violation
- Plan-only determinism preserved via deterministic UUIDv5 `run_id`
  (namespace UUID is a fixed constant in `chaos_librarian.contract`) and
  omitted `created_at`; bit-identical plan-only output is back on the table
- Multi-phase mutations modeled as paired `*_start` / `*_commit` events
  with a shared journal schema (`phase`, `temp_path`, `related_event_id`)
  defined in Sprint 0
- voom-v2 adapter remains at Sprint 9; the existing Sprint-1/Sprint-3
  internal Pydantic round-trip mitigation is retained without
  strengthening. Rationale: chaos-librarian is expected to reach maturity
  before voom-v2 needs it, and the tool's value as a user-behavior
  simulator does not depend on the integration timing.

## Open Decisions

- Minimum external tool versions (FFmpeg, ffprobe, MKVToolNix); decide in
  Sprint 5
- Whether MKVToolNix is required for any V1 mutation or remains optional;
  decide in Sprint 7
- Packaging and distribution strategy (PyPI vs. internal index vs. uvx-only);
  decide before Sprint 9
