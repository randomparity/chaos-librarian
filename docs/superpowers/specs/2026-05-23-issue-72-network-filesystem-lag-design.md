# Issue #72 - Network Filesystem Lag Profile

**Status:** design for future implementation.
**GitHub issue:** [#72](https://github.com/randomparity/chaos-librarian/issues/72)
**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md)
("Mutation Model", "Mutation Pipeline", and "Sprint 10 - Extended Profiles").
**Target implementation branch:** `feat/gh-issue-72`.

## Goal

Define the network filesystem lag profile before any lag simulator is added.

This design closes the issue by specifying:

1. The future scenario contract for opt-in lag artifacts.
2. Wall-clock timing and boundary behavior.
3. Replay and materialization evidence.
4. Watcher-facing guarantees and limits.

It does not add new scenario profile enum values, lag timeline actions,
fixtures, providers, or runtime code. The current contract still rejects unknown
`profiles` values until an implementation PR explicitly adds them.

## Context

Sprint 10 reserved a network-lag profile but intentionally shipped only the
malformed-media lane. The deferred work needs a contract before implementation
because network filesystem behavior is easy to make ambiguous: a profile name
could hide random delays, platform differences could make held handles
inconsistent, and watcher tests need to know which visibility windows are part
of the oracle.

The existing project rule still applies: scenario authors describe explicit
mutations, and chaos-librarian emits neutral evidence. The lag profile must not
predict voom-v2 policy outcomes.

## Profile Label

Future implementation should add exactly one label first:

```yaml
profiles:
  - network-fs-lag
```

The label permits lag-specific events; it never changes the behavior of existing
timeline actions by itself. A scenario with the profile but no lag events should
behave like the same scenario without the profile, aside from carrying the
profile marker in the parsed contract.

Lag events require the profile. Missing opt-in is a validation error with the
same profile-required pattern used by malformed-media corruption.

## Scenario Contract

Lag artifacts are explicit timeline actions. The first implementation should
add one pair shape rather than separate bespoke models for every artifact:

```yaml
- id: lag_rename_start
  at: 10s
  action: network_lag_start
  effect: delayed_rename
  target: asset_hd_main
  after: rename_001
  duration: 2s

- id: lag_rename_commit
  at: 12s
  action: network_lag_commit
  for: lag_rename_start
```

`network_lag_start` fields:

| Field | Meaning |
| --- | --- |
| `effect` | One of `delayed_visibility`, `delayed_rename`, or `held_handle`. |
| `target` | Asset or sidecar id whose path is affected. |
| `after` | Event id whose logical effect is being delayed or held. |
| `duration` | Duration string parsed by the existing duration grammar. |

`network_lag_commit` fields:

| Field | Meaning |
| --- | --- |
| `for` | The matching `network_lag_start` event id. |

The engine resolves the affected paths from the referenced `after` event and
the target's manifest state. Scenario authors should not duplicate path strings
inside lag events; that avoids stale paths after fixture edits and keeps
containment validation centralized in the existing path rules.

The lag pair is not an after-the-fact rollback. During preflight, the wall-clock
runner must build a lag schedule before any timed event executes. If a
`network_lag_start` references `rename_001`, the runner intercepts the real
phase-B disk effect for `rename_001` and applies the delayed watcher-visible
artifact instead. The referenced logical mutation still emits its normal journal
entry and updates the oracle at its declared time.

Supported initial effects:

- `delayed_visibility` - a logical add, restore, slow-copy commit, sidecar
  create, sidecar update, or media rewrite withholds the new visible state until
  commit. New paths remain absent; existing paths remain at their previous bytes
  and metadata.
- `delayed_rename` - a logical move, rename, archive, or move-between-roots keeps
  the old path visible and the new path absent until commit.
- `held_handle` - the materializer opens the target path for the duration and
  reports whether the host provider enforced handle semantics.

`network_lag_start` must have the same `at:` value as the referenced event and
must immediately follow that event in resolved order. The paired
`network_lag_commit` must be the next mutation against the same target. Other
events may occur during the elapsed logical time only when they target different
assets or sidecars. This keeps the first profile deterministic and avoids
inventing a general concurrent timeline model.

## Wall-Clock Behavior

The lag profile is a watcher profile. `chaos-librarian run` is the only mode
that provides watcher-facing lag guarantees.

Wall-clock execution:

1. The referenced logical mutation remains the oracle state transition.
2. Preflight links `network_lag_start` to the referenced mutation before the
   wall-clock loop starts.
3. When the referenced mutation becomes due, the runner records its journal
   entry and logical state, then applies the lag artifact instead of the normal
   immediate disk effect.
4. `network_lag_commit` removes the artifact and makes the library tree match
   the logical oracle state again.

Lag durations use logical scenario time and are scheduled through the same
`--speed` multiplier as normal timeline events. With `--speed 10x`, a `2s` lag
window should last about `200ms` of real wall time.

If the requested `run --duration` expires inside a lag window, the runner must
continue through the paired `network_lag_commit`, finalize at that replayable
boundary, and set `overran_duration=true`. It must not exit with a stale hidden
path, stale rename source, or held handle left active.

`materialize` should reject scenarios containing lag events with an unsupported
timeline error. Running a lag fixture without a watcher window would silently
remove the behavior the profile exists to test.

`plan`, `step`, and run replay may model the logical events and evidence, but
they do not guarantee live watcher visibility. Replay reproduces the recorded
final state and audit evidence without preserving original pacing.

## Replay And Evidence

Future implementation should add a `network_lag_actions` audit list to
`materialization.json`, parallel to `filesystem_actions`, `media_actions`, and
`corruption_actions`.

Each action record should include:

| Field | Meaning |
| --- | --- |
| `event_id` | The `network_lag_start` event id. |
| `commit_event_id` | The paired commit event id. |
| `effect` | `delayed_visibility`, `delayed_rename`, or `held_handle`. |
| `target_ref` | Asset or sidecar id. |
| `after_event_id` | Referenced logical mutation. |
| `logical_start_ns` | Start logical time. |
| `logical_commit_ns` | Commit logical time. |
| `requested_duration_ns` | Parsed planned lag duration. |
| `actual_duration_ns` | Measured real elapsed duration in run mode. |
| `from_path` / `to_path` | Resolved affected paths when applicable. |
| `provider` | `stdlib-local` unless a future provider is added. |
| `enforced` | Whether the provider could enforce the requested artifact. |

Replay evidence comes from the embedded scenario, journal digest, applied event
count, and the lag audit records. Do not add hidden RNG streams for lag timing.
If a future provider needs randomness, it must use the existing replay trace
contract and record the stream explicitly.

Schema-version bumps are expected for `Scenario`, `MaterializationReport`, and
any report that surfaces lag evidence. `JournalEntry` can keep the existing
phase union only if the lag pair fits the current started/committed shapes
without lossy `state_delta` dictionaries; otherwise the implementation should
bump the journal schema and make lag evidence typed.

## Watcher-Facing Guarantees

The profile guarantees only what the materializer can observe or enforce:

- During `delayed_visibility` for a new path, the final path is absent until the
  lag commit and present after the commit.
- During `delayed_visibility` for an update or rewrite, the final path remains
  visible with its previous bytes and metadata until the lag commit; after the
  commit it reflects the new logical version.
- During `delayed_rename`, the old path remains visible and the new path remains
  absent until the lag commit; after commit, the old path is absent and the new
  path is present.
- During `held_handle`, the report states whether the platform/provider enforced
  a blocking handle. Tests may assert blocking behavior only when `enforced` is
  true.

Watcher tests should compare observations against the lag action windows, not
against guessed sleep durations. The materializer should record enough evidence
for consumers to explain whether a watcher saw the stale state inside,
before, or after the expected window.

The profile does not guarantee OS notification ordering. Filesystem watchers can
coalesce, reorder, or drop low-level events. Chaos-librarian guarantees
path-state windows and records the logical oracle; consumers remain responsible
for deciding whether their watcher behavior is acceptable.

## Validation And Safety Rules

The implementation should reject:

- Lag events without `profiles: ["network-fs-lag"]`.
- Unknown `effect` values.
- Non-positive or unparseable `duration` values.
- `network_lag_commit` without a matching start.
- A start whose `at:` value differs from the referenced `after` event.
- A start that does not immediately follow the referenced `after` event in
  resolved order.
- A start that references an unknown or future `after` event.
- A start whose target does not match the referenced mutation's target.
- Any mutation against the same target while a lag pair is pending.
- Lag windows against paths outside `<run-dir>/library/`.

Cleanup must release held handles and remove private lag staging paths on both
success and failure. Interrupted runs keep the existing `in_progress` sentinel
behavior and must leave enough live journal evidence to explain where the run
stopped.

## Verification Expectations

The implementation that adds this profile should include:

- Contract tests for the profile label and the two lag event shapes.
- Validation tests for missing opt-in, bad pair references, non-positive
  durations, mismatched targets, and overlapping target mutations.
- Wall-clock integration tests proving delayed visibility and delayed rename
  path windows with short durations and high `--speed`.
- A platform-conditional held-handle test that asserts blocking only when the
  provider reports `enforced=true`.
- Replay tests proving final state and audit evidence reproduce without
  preserving original pacing.
- Docs tests that keep the profile label, watcher guarantees, and materialize
  rejection rule discoverable.

## Out Of Scope

- Adding the `network-fs-lag` enum value now.
- Adding lag timeline action models now.
- Implementing a FUSE, SMB, NFS, or cloud-sync provider.
- Introducing random background delays.
- Supporting overlapping lag windows on the same target.
- Guaranteeing low-level OS watcher event ordering.
- Changing compare semantics for observed-state reports.
