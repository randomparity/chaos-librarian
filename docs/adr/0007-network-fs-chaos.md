# 0007 — Network-filesystem chaos beyond latency

## Status

Accepted

## Context

chaos-librarian models one network-filesystem failure mode: latency, via
`network_lag_start` / `network_lag_commit` gated by `network-fs-lag`. Issue #111 adds
seven failure modes media-library consumers hit on NAS/SMB/NFS shares:
`change_permissions` (EACCES), `simulate_quota_exceeded` (ENOSPC), `toggle_readonly`,
`simulate_stale_handle` (ESTALE), `unmount_path`/`remount_path` (availability), and
`acquire_lock`/`release_lock` (EAGAIN/EBUSY). They are gated by a new
`network-fs-chaos` profile.

Several of these conditions are **kernel-level** — ESTALE, ENOSPC, EAGAIN from a
foreign lock holder, and a real unmount cannot be produced on a local ext4 / APFS run
tree without root, loopback mounts, or FUSE, which CI does not have. The issue itself
says to "simulate error responses in the prober/adapter layer where actual
filesystem-level simulation is impractical." Permissions, by contrast, are genuinely
reproducible with `os.chmod`. This split, plus the policy-neutral oracle constraint
(AGENTS.md: the tool "does NOT know the application's expected policy outcomes") and
the safety of real chmod on the run tree, drive the seven decisions below. The lag
model is the structural template throughout: paired start/commit events, a single
profile gate, wall-clock-only realization, a typed neutral report record with an
`enforced` flag.

## Decision

1. **Realization is balanced.** `change_permissions` and `toggle_readonly` perform a
   **real `os.chmod`** confined to `<run-dir>/library/`; the four kernel-level
   conditions are **recorded-only neutral conditions** (`enforced=False`), following
   the lag `held_handle` precedent.
2. **The oracle records a typed neutral fact.** A new `NetworkFsChaosAction` list on
   `MaterializationReport` carries `event_id`, `action`, `target_ref`, `condition`
   (errno/condition name), `enforced`, and the paired open id — never an expected
   consumer verdict.
3. **Targets are mixed-granularity.** Quota / stale-handle / lock target a single
   asset id; permissions / readonly / unmount accept an asset id or a library-relative
   subtree path (resolved through `resolve_under_library`).
4. **Profile + wall-clock-only.** Add `NETWORK_FS_CHAOS` to `ProfileName`; add all
   seven actions to the single-source `REQUIRED_PROFILES_BY_ACTION`; realize only in
   the wall-clock runner. No generation/fuzz-lane integration in v1.
5. **Composition.** Single-shot conditions impose no window; the paired
   acquire/release and unmount/remount impose a window forbidding other same-target
   mutations between open and close (`E_LIFECYCLE_INVALID`). No lag⇄chaos rules in v1.
6. **Safety.** Real chmod is confined to `<run-dir>/library/`, the original mode is
   captured in session state, and it is always restored at finalize and on the failure
   path (try/finally), so the run tree is always cleanable.
7. **Paired-event contract.** `release_lock.for` references `acquire_lock.id`;
   `remount_path.for` references `unmount_path.id` — by event id, reusing
   `index_start_commit_events` + `report_unpaired_start`; unknown / unpaired /
   close-before-open → `E_LIFECYCLE_INVALID`.

Schema impact: `SCENARIO_SCHEMA_VERSION` 27 → 28 (new event variants) and
`MATERIALIZATION_SCHEMA_VERSION` 15 → 16 (new report list). No new validation codes.

## Consequences

- Seven `TimelineActionName` members + seven event variants enter the scenario schema.
  Two recipes ship under `watcher/`.
- `change_permissions` / `toggle_readonly` are observable on disk
  (`os.stat().st_mode`) **and** recorded (`enforced=True`); the four kernel-level
  conditions are observable only via the report record (`enforced=False`), which the
  consumer's adapter interprets.
- Every existing scenario stays valid beyond the mandatory `schema_version: 28` bump; a
  timeline with none of the new actions is byte-identical to pre-change, and the report's
  `network_fs_chaos_actions` is `[]`.
- The run tree is always cleanable: real chmod is confined to `library/`, never the
  run-dir root, and is restored at finalize and on failure.
- Static `materialize` rejects all seven with the existing
  `E_MATERIALIZE_TIMELINE_UNSUPPORTED`; only the wall-clock runner realizes them.
- Two schema artifacts regenerate (`scenario.schema.json`,
  `materialization.schema.json`); `manifest` / `journal` / `replay-bundle` are
  unchanged.
- Deferred to filed follow-ups: generation/fuzz-lane emission of these actions;
  lag⇄chaos cross-interaction validation; recursive `toggle_readonly` over a subtree's
  files; real ENOSPC/ESTALE/EAGAIN/unmount via loopback/FUSE.

## Considered & rejected

**Q1 — Per-action realization: real filesystem op vs recorded-only condition.**
- *Rejected: make every action a recorded-only condition (no real chmod).* Loses the
  one faithfully-reproducible effect (`os.chmod` really does produce EACCES on the run
  tree), making `change_permissions` weaker than it can be for no safety gain.
- *Rejected: make every action a real filesystem op* — real `fcntl.flock`, `chmod 000`
  as a stand-in for unmount, a loopback ENOSPC mount. A self-held `flock` in the same
  process is not the EAGAIN a foreign holder produces; `chmod 000`-as-unmount conflates
  with `change_permissions` and produces EACCES, not the "path gone" semantics of
  unmount; loopback/FUSE need root CI does not have.
- **Chosen: balanced.** Real `os.chmod` for `change_permissions` / `toggle_readonly`
  (`enforced=True`); recorded-only neutral conditions for ENOSPC / ESTALE / EAGAIN /
  unavailable (`enforced=False`), exactly the lag `held_handle` precedent and the
  issue's "simulate in the prober/adapter layer where actual filesystem-level
  simulation is impractical."

**Q2 — Target granularity (subtree vs single asset).**
- *Rejected: every action targets a single asset id.* Loses the "a subtree becomes
  unavailable / read-only" stressor — the whole point of `unmount_path` /
  `toggle_readonly` on a directory.
- *Rejected: every action targets a subtree path.* `simulate_stale_handle` /
  `acquire_lock` are inherently per-file (a stale handle / advisory lock is on one
  file), so a path-only model is wrong for them.
- **Chosen: mixed.** Quota / stale-handle / lock → single asset id (validated by
  `rule_target_unknown`, `E_TARGET_UNKNOWN`); permissions / readonly / unmount → asset
  id **or** library-relative subtree path (containment via `resolve_under_library`,
  `E_PATH_CONTAINMENT` on escape). Asset ids never contain `/`, so a path target is any
  `target` not in the declared asset set — unambiguous.

**Q3 — Oracle representation for simulated (non-FS) conditions.**
- *Rejected: extend / reuse `NetworkLagAction`.* Overloads a lag-specific record and
  its `effect` enum (delayed-visibility/rename/held-handle) with unrelated errno
  conditions.
- *Rejected: record nothing in the report; rely on the journal `state_delta` only.* The
  materialization report is the audit surface consumers read; a simulated condition
  leaves nothing on disk, so omitting it from the report makes it invisible. Lag set the
  precedent of a typed action list on the report.
- *Rejected: a manifest field / per-asset injected-error state.* The manifest records
  current library state, not transient injected conditions; adding an injected-error
  field there bumps the manifest schema for a transient fact and pre-judges the
  consumer (which asset "is" in error is the consumer's call).
- **Chosen: a typed `NetworkFsChaosAction` list on `MaterializationReport`** (twin of
  `NetworkLagAction`) recording neutral facts only — condition, target, enforced,
  paired ids — never an expected verdict. Bumps `MATERIALIZATION_SCHEMA_VERSION`.

**Q4 — Profile wiring + which run modes realize these.**
- *Rejected: realize in static `materialize` too.* Static materialize applies the full
  timeline instantly with no wall-clock window; a lock/unmount *window* is meaningless
  without time, and lag already establishes wall-clock-only as the home for
  time-shaped network effects.
- *Rejected: add a fuzz lane + generation emission in v1.* The issue does not ask for
  generation; adding it widens scope and risks emitting under-tested action
  combinations. Filed as a follow-up.
- **Chosen: add `NETWORK_FS_CHAOS` to `ProfileName`; add all seven to the single-source
  `REQUIRED_PROFILES_BY_ACTION` (generation derives gated labels from it);** realize
  only in the wall-clock runner; static `materialize` rejects them. No generation change
  ships.

**Q5 — Composition with existing windows / mutations on the same target.**
- *Rejected: full windowing for all seven* (treat every action as opening a window).
  Single-shot errno injections (`change_permissions`, quota, stale-handle) have no
  natural close event; forcing a window is artificial.
- *Rejected: no windowing at all* (allow any mutation during a lock/unmount). A mutation
  on a locked/unmounted asset is exactly the un-executable nonsense the lag window guard
  rejects; allowing it would let authors write scenarios whose meaning is undefined.
- **Chosen: single-shot conditions impose no window; the paired acquire/release and
  unmount/remount impose a window forbidding other same-target mutations between open
  and close (`E_LIFECYCLE_INVALID`), mirroring lag's `_check_same_target_window`.** No
  lag⇄chaos cross-interaction rules in v1 (filed follow-up if a real need surfaces).

**Q6 — Safety / teardown for real chmod and readonly toggles.**
- *Rejected: never restore (let cleanup force-chmod the whole tree).* A `chmod 000` on a
  directory can make the tree itself un-listable; relying on a blanket post-run
  force-chmod is fragile and hides the modeled effect from anything inspecting the tree
  mid-run.
- *Rejected: never do real directory chmod — simulate `toggle_readonly` / `unmount` too,
  real chmod only on a single file.* Safer but loses the real read-only-subtree effect
  on a directory, which is genuinely reproducible and is the modeled stressor.
- **Chosen: real chmod confined to `<run-dir>/library/` (never the run-dir root); the
  original `st_mode` captured in session state and always restored at finalize and on
  the failure path (try/finally), mirroring how lag / slow-copy sessions drain in
  `_finish_active_*`.** The run tree is always cleanable.

**Q7 — Paired-event contract (acquire/release; unmount/remount).**
- *Rejected: match `remount_path` to its `unmount_path` by path string.* Non-deterministic
  if two unmounts share a path/prefix and brittle against path normalization; the lag /
  slow-copy precedent references the open by **event id**.
- *Rejected: a free-standing `release_lock` / `remount_path` with no reference.* Loses
  the ability to validate pairing, ordering, and the same-target window.
- **Chosen: `release_lock.for` references `acquire_lock.id`; `remount_path.for`
  references `unmount_path.id` — by event id, reusing `index_start_commit_events` +
  `report_unpaired_start`; unknown ref / unpaired / close-before-open →
  `E_LIFECYCLE_INVALID`,** exactly like `network_lag_commit` → `network_lag_start`.
