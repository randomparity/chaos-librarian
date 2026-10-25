# Explicit adversarial generation

## Problem and authority

Issue #248 integrates the delivered #245–#247 recipes for epic #244. The
operator approved the explicit `adversarial-media` lane under `fuzz-regression`
on 2026-10-25 and retained the campaign exclusions approved on 2026-10-24.
The frozen charter is issue #248 WORK:SCOPE token `q248-6ca932b1`.

## Architecture and scope

Extend the existing generation planner/configuration and coverage entry points.
The new lane is permitted explicitly, excluded from the canonical default cycle,
and bounded by the existing regression budget. Existing lane recipes and profile
version 3 remain unchanged. ADR 0017 records the opt-in boundary.

Use one movie with sixteen video variants and one artist with two MP3 tracks:
four flag assets; seven metadata assets; three video damage assets; two healthy
video controls; one damaged MP3 and one healthy MP3. Video is SD H.264 with AAC;
MP3 is stereo 44100 Hz. Flags use 0.2 seconds and other assets use 2 seconds.
Each damage asset receives one structural mutation. Do not add random filler.
The existing 22-asset/variant budget and 80-event limit remain unchanged.

Flag cases are two-track multiple defaults, two-track no defaults, two-track
default+forced, and eight-track forced-only, for audio and embedded UTF-8 SRT.
Preserve commentary on the first audio track. No rewriting action targets them.
Metadata cases are embedded title differing from filename and NFO, year 9999,
4096-byte Unicode title, Unicode with TAB/LF, deletion of prior title/year,
missing tags, and conflicting eng/fra audio labels. Structural cases are MP4
moov damage at start and end, MKV Cues damage, and MP3 after sixteen frames.
Healthy MP4/MKV/MP3 controls support consumer inspection and decode comparisons.

Coverage cells inspect authored flags, fields, languages and structural recipe
parameters rather than IDs or labels. Required cells reject missing cases before
YAML publication. Existing semantic validation, preflight, containment and atomic
publication stay authoritative. The scenario enum extension bumps schema version
36 to 37, regenerates schemas and migrates checked-in scenario inputs; replay
contracts embed scenario YAML and require no independent shape change.

## Success

For seed 248, one generated scenario reaches the named case set with eighteen
assets and a fixed documented event count; its checked-in YAML is the curated
corpus and matches generation bytes. Additional seeds preserve recipe coverage.
The scenario validates, materializes, runs and replays through existing APIs/CLI.
Real-tool tests inspect retained flags/tags/languages, expected failed MP4 probes,
MKV readability and MP3 frame evidence, and retained neutral journal/report data.
Feature-level decode proof remains owned by #247; integration verifies reachability
and retained properties and makes no new cross-version byte identity promise.
The equipped CI wildcard selects the integration test and its existing zero-skip
gate applies. Consumer docs name the corpus, command, budget and capability needs.

## Failure model

- Actors and deployments: trusted local operators and equipped CI running generated
  synthetic inputs with supported ffmpeg/ffprobe and MKVToolNix capabilities.
- Invariants and assets: ordinary generation remains opt-in; supported cases stay
  bounded and executable; intent and actual evidence remain distinct and replayable.
- Accepted failure classes: absent tools fail capability checks or skip locally,
  while equipped CI rejects skips; output bytes may differ across tool versions.
  Intentional MP4 probe failure is successful corruption evidence.
- Covered elsewhere: disposition synthesis/comparison #245; metadata retention
  #246; structural parsing, byte targeting and decode proof #247; downstream
  precedence/repair policy belongs to consumers; exhaustive matrices/frameworks
  require future operator authorization outside #244.

## Threat model

- Added boundaries: none. Widened boundary: trusted generated YAML includes
  additional existing recipes and authored parameters consumed by existing tools.
- Actor model: local operators control seed and selected lane; no remote tenant.
- Controls: model/semantic validation and materializer preflight before allocation;
  existing containment and atomic publication; existing 64 MiB output bound,
  60-second synthesis, 15-second bounded probe and 1 MiB capture for structural
  recipes; track maximum eight per kind and duration at most two seconds here.
- Out of scope: hostile tool binaries and arbitrary imported media, absent from
  this generated lane; downstream application policy remains consumer-owned.

## Validation

Focused tests cover opt-in/default selection, coverage sensitivity, bounded case
inventory, generation determinism, schema migration and curated-byte identity.
Real integration executes materialize plus run/replay and inspects actual bytes
through ffprobe and existing probe/report contracts. The existing standard and
equipped suites, lint, formatting, typing and schema drift gates are final checks.
No new dependency, CI action, tool floor or runner is introduced.
