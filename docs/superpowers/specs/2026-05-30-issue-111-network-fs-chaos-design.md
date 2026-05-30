# Issue #111 — Network filesystem chaos beyond latency

> Status: Draft · Sprint: issue-111 · Schema impact: SCENARIO_SCHEMA_VERSION 27 → 28,
> MATERIALIZATION_SCHEMA_VERSION 15 → 16

## Problem

chaos-librarian models exactly one network-filesystem failure mode today:
**latency**, via `network_lag_start` / `network_lag_commit` (delayed visibility,
delayed rename, held handle), gated by the `network-fs-lag` profile. Real network
filesystems (NFS, SMB, CIFS, FUSE) fail in many other ways that a media-library
consumer must survive: a file's permissions change mid-scan (EACCES), a write hits a
quota (ENOSPC), a subtree flips read-only, an NFS handle goes stale (ESTALE), a mount
disappears and reappears, an advisory lock blocks a writer (EAGAIN/EBUSY). The
timeline engine cannot express any of these.

## Proposal (issue #111)

Add seven timeline actions, gated by a **new `network-fs-chaos` profile**, that
inject these conditions during a wall-clock run:

| action | issue scope | effect modeled |
| --- | --- | --- |
| `change_permissions` | file or directory | EACCES (mode change mid-scan) |
| `simulate_quota_exceeded` | root or path | ENOSPC on writes |
| `toggle_readonly` | root or path | read-only / read-write flip on a subtree |
| `simulate_stale_handle` | specific asset | NFS ESTALE on an asset |
| `unmount_path` / `remount_path` | library root or subdirectory | path unavailable, then restored |
| `acquire_lock` / `release_lock` | specific asset | advisory lock → EAGAIN/EBUSY |

`release_lock` references its `acquire_lock` by event id; `remount_path` references
its `unmount_path` by event id (the paired-event pattern `network_lag_commit`
established).

## The load-bearing decisions (ADR 0007)

Seven decisions were settled before any code (full rationale and rejected
alternatives in [ADR 0007](../../adr/0007-network-fs-chaos.md)). They are summarized
here because every section below depends on them.

1. **Realization model — balanced (real where the OS permits, simulate the rest).**
   `change_permissions` and `toggle_readonly` perform a **real `os.chmod`** on the
   target inside `<run-dir>/library/`; the four kernel-level conditions
   (`simulate_quota_exceeded`/ENOSPC, `simulate_stale_handle`/ESTALE,
   `acquire_lock`+`release_lock`/EAGAIN, `unmount_path`+`remount_path`/availability)
   are **recorded-only neutral conditions** with no real filesystem effect. This
   mirrors the existing lag precedent where `held_handle` records with
   `enforced=False`: a condition that cannot be faithfully produced on a local ext4 /
   APFS tree is recorded as an injected fact for the consumer's adapter to interpret,
   exactly the issue's "simulated in the prober/adapter layer where actual
   filesystem-level simulation is impractical."
2. **Oracle representation — one typed report record.** A new
   `NetworkFsChaosAction` list on `MaterializationReport` records neutral facts only:
   `event_id`, `action`, `target_ref`, the injected condition (`errno`/condition
   name), `enforced: bool`, and the paired acquire/unmount id for the paired actions.
   **No expected consumer verdict** (policy-neutral, per the #179 precedent).
3. **Target granularity — mixed.** `simulate_quota_exceeded`,
   `simulate_stale_handle`, `acquire_lock`/`release_lock` target a **single asset id**;
   `change_permissions`, `toggle_readonly`, `unmount_path`/`remount_path` accept
   **either an asset id or a library-relative subtree path** resolved through the same
   `resolve_under_library` containment machinery.
4. **Profile + run modes.** Add `NETWORK_FS_CHAOS = "network-fs-chaos"` to
   `ProfileName`; add all seven actions to the single-source
   `REQUIRED_PROFILES_BY_ACTION`. Realize **only in the wall-clock runner** (extend the
   gated set in `preflight_timeline`); static `materialize` rejects them, exactly like
   lag. No fuzz-lane / generation integration in v1 (filed follow-up).
5. **Composition.** Single-shot conditions (`change_permissions`,
   `simulate_quota_exceeded`, `simulate_stale_handle`) impose **no open window**. The
   paired `acquire_lock`/`release_lock` and `unmount_path`/`remount_path` impose a
   window and **forbid other same-target mutations between the open and close events**
   (`E_LIFECYCLE_INVALID`), mirroring lag's `_check_same_target_window`. No lag+chaos
   cross-interaction rules in v1 (filed follow-up if needed).
6. **Safety / teardown.** Real `os.chmod` is confined to `<run-dir>/library/` (never
   the run-dir root). The original mode is captured in session state and **always
   restored at run finalize and on the failure path** (try/finally), mirroring how
   slow-copy / lag sessions drain in `_finish_active_*`, so the run tree is always
   cleanable.
7. **Paired-event contract.** `release_lock.for` references an `acquire_lock.id`;
   `remount_path.for` references an `unmount_path.id` — reference by **event id**, not
   path string, reusing `index_start_commit_events` + `report_unpaired_start`.
   Unknown ref / unpaired / close-before-open → `E_LIFECYCLE_INVALID`.

### Pairing timing contract (which lag invariants carry over)

The chaos pairs are **looser** than lag, deliberately. Lag's start carries an `after`
(immediate-predecessor) reference, shares the `after` event's `at`, and requires
`commit.at == start.at + duration` (`validation/rules/network_lag.py:183-298`). A
chaos open (`acquire_lock` / `unmount_path`) has **no `after` reference and no
`duration`**, so those three lag invariants do **not** apply. The contract that *does*
carry over, stated precisely:

- **Pairing is by event id**, exactly one close per open (`report_unpaired_start`).
- **The close must follow the open in timeline list order** (`close.idx > open.idx`),
  the same index-based ordering lag's `_check_same_target_window` uses — the
  same-target-window walk scans `timeline[open.idx + 1 : close.idx]` by list index, so
  a close that precedes its open in the list is `E_LIFECYCLE_INVALID`.
- **No `at` relationship is enforced between open and close.** A zero-width window
  (`open.at == close.at`) is **legal** — a lock can be acquired and released at the
  same logical instant; the engine still emits the started/committed pair and the
  runner records both. (Lag forbids this only because its duration arithmetic demands
  `commit.at > start.at`; chaos has no duration.)
- **`at` need not be monotonic across the window**, but the close's list position must
  be after the open's; the resolved timeline already sorts by `at` then by declaration
  order, so an author who wants the window to span time orders the events accordingly.

This looseness is intentional: a lock/unmount window is defined by its open/close
*events*, not by a wall-clock duration the author must pre-compute.

## Policy-neutrality (the constraint that shapes the oracle)

AGENTS.md: chaos-librarian "does NOT know the application's expected policy outcomes —
it emits neutral oracle journals and manifests." Unlike a symlink (whose link-ness is
observable on disk), a simulated ESTALE/ENOSPC/EAGAIN/unavailable condition leaves
**nothing on disk** for the consumer to observe — so it must be recorded somewhere or
it is invisible. The decision (ADR 0007 Q3) is to record it as a **typed neutral
fact** (`NetworkFsChaosAction`): what condition was injected, on what target, when,
and whether it was really enforced on disk (`enforced`). The record carries **no**
expected consumer response; the consumer's adapter reads the injected condition and
applies its own policy. A real `change_permissions` is additionally observable on disk
(`os.stat().st_mode`), so its record is the audit twin of the on-disk fact, not the
only evidence.

## Goals

- Add seven `TimelineActionName` members and seven discriminated-union event variants
  following the existing `id` / `at` / `action` + action-specific-field pattern.
- Gate all seven behind `network-fs-chaos` through the single-source
  `REQUIRED_PROFILES_BY_ACTION` (generation derives gated labels from it).
- Realize them only in the wall-clock runner: `change_permissions` /
  `toggle_readonly` do a real `os.chmod` (restored at teardown); the four kernel-level
  conditions record a neutral `NetworkFsChaosAction` with `enforced=False`.
- Record every injected condition as a `NetworkFsChaosAction` on the materialization
  report — neutral facts only, no expected verdict.
- Validate the paired actions (`release_lock`→`acquire_lock`,
  `remount_path`→`unmount_path`) exactly like `network_lag_commit`→`network_lag_start`
  (`E_LIFECYCLE_INVALID`), including a same-target-window mutation guard.
- Resolve subtree-path targets through `resolve_under_library` so they stay contained;
  asset-id targets validate against the declared asset set (`E_TARGET_UNKNOWN`).
- Bump `SCENARIO_SCHEMA_VERSION` 27 → 28 and `MATERIALIZATION_SCHEMA_VERSION` 15 → 16;
  regenerate both schema artifacts; mass-bump every fixture/recipe to `28`.
- Preserve backward compatibility: every existing scenario stays valid beyond the
  mandatory `schema_version: 28` bump; a timeline with none of the new actions
  executes the identical pre-change path.

## Non-goals

- **Real ENOSPC / ESTALE / EAGAIN / unmount.** These are kernel-level and cannot be
  produced on a local ext4 / APFS tree without root, loopback mounts, or FUSE — out of
  scope; recorded as neutral conditions instead (ADR 0007 Q1). No real `fcntl.flock`
  (a self-held lock in the same process is not the EAGAIN a foreign holder produces)
  and no `chmod 000`-as-unmount (it conflates with `change_permissions`).
- **Encoding the expected consumer response.** Documentation prose only; the
  `NetworkFsChaosAction` record carries neutral facts, never a verdict (ADR 0007 Q3).
- **Generation / fuzz-lane integration.** v1 ships authoring + realization +
  validation + recipes only; emitting these actions from the fuzz generator is a filed
  follow-up (ADR 0007 Q4).
- **Lag ⇄ chaos cross-interaction rules.** A chaos window and a lag window on the same
  target in v1 are validated independently; a combined rule is a filed follow-up if a
  real need surfaces (ADR 0007 Q5).
- **Static `materialize` support.** Like lag, these realize only under the wall-clock
  runner; static `materialize` rejects them with the existing
  `E_MATERIALIZE_TIMELINE_UNSUPPORTED` preflight path (ADR 0007 Q4).

## Ground truth (verified on branch base, schema v27)

Verified against `contract/scenario.py`, `contract/materialization.py`,
`contract/profiles.py`, `validation/rules/profile_opt_in.py`,
`validation/rules/network_lag.py`, `validation/rules/_common.py`,
`validation/rules/target_unknown.py`, `validation/semantic.py`,
`materializer/preflight.py`, `materializer/actions.py`, `materializer/wall_clock.py`,
`engine/events.py`, `engine/state.py`, and `contract/paths.py`.

- **Lag template.** `NetworkLagStartEvent` / `NetworkLagCommitEvent` are the
  paired-event template: the start carries the action-specific fields; the commit
  carries only `for_` (`for` in YAML) referencing the start id. Validation
  (`rule_network_lag`, `E_LIFECYCLE_INVALID`) uses `index_start_commit_events` +
  `report_unpaired_start` for pairing and `_check_same_target_window` for the
  open-window mutation guard. Realization is wall-clock-only:
  `preflight_timeline(allow_network_lag=True)` widens `SUPPORTED_S10_ACTIONS` with
  `NETWORK_LAG_ACTIONS`; static `materialize` (default `allow_network_lag=False`)
  rejects lag with `TimelineUnsupportedError`.
- **Lag report record.** `NetworkLagAction` is a flat `extra="forbid"` model on
  `MaterializationReport.network_lag_actions`. The `enforced: bool` field is already
  `False` for `held_handle` — the precedent for "recorded but not realized."
- **Engine pairing state.** `WorldState.pending_network_lags: dict[str, dict]` holds an
  open lag keyed by start id; the commit pops it. The engine emits a `StartedJournalEntry`
  for the start and a `CommittedJournalEntry` (with `related_event_id`) for the commit.
- **Profile single source.** `REQUIRED_PROFILES_BY_ACTION` (action value → profile
  label) in `profile_opt_in.py` is the single source; `rule_profile_opt_in` rejects a
  gated action whose profile is absent with `E_PROFILE_REQUIRED`. Generation derives
  its declared gated labels from this map.
- **Containment.** `contract/paths.py` `resolve_under_library` resolves a
  library-relative path under `<run-dir>/library/`, rejecting escapes with
  `E_PATH_CONTAINMENT`. Asset rendered paths flow through it already.
- **Target validation.** `rule_target_unknown` validates `target` as an asset id for
  the actions listed in `_ASSET_TARGET_ACTIONS`. A path-or-asset target needs distinct
  handling (see "Target validation").

## Design

### New `TimelineActionName` members and event variants

Seven members added to `TimelineActionName` (StrEnum) and seven event classes added to
the `TimelineEvent` discriminated union, each extending `_TimelineEventBase`
(`id`, `at`, frozen, `extra="forbid"`, `populate_by_name=True`).

```python
class FilesystemPermissionMode(enum.StrEnum):
    """Octal permission string accepted by change_permissions."""
    # value-validated as a 3- or 4-digit octal string by a field validator,
    # not an enum of fixed modes — authors need "000"/"444"/"644"/"755" freely.

class ReadonlyState(enum.StrEnum):
    READONLY = "readonly"
    READWRITE = "readwrite"

class LockType(enum.StrEnum):
    SHARED = "shared"
    EXCLUSIVE = "exclusive"

class NetworkFsChaosCondition(enum.StrEnum):
    """The neutral errno/condition a chaos action injects (recorded fact)."""
    EACCES = "eacces"
    ENOSPC = "enospc"
    ESTALE = "estale"
    EAGAIN = "eagain"
    UNAVAILABLE = "unavailable"
```

`change_permissions.mode` is a string validated to match `^[0-7]{3,4}$` (a field
validator, so authors can pass any octal mode the issue names — "000", "444", "644").
`mode` is **not** an enum: the issue treats it as a free permission string.

| event class | action | fields beyond `id`/`at` |
| --- | --- | --- |
| `ChangePermissionsEvent` | `change_permissions` | `target: str` (asset id or subtree path), `mode: str` (octal) |
| `SimulateQuotaExceededEvent` | `simulate_quota_exceeded` | `target: str` (asset id) |
| `ToggleReadonlyEvent` | `toggle_readonly` | `target: str` (asset id or subtree path), `mode: ReadonlyState` |
| `SimulateStaleHandleEvent` | `simulate_stale_handle` | `target: str` (asset id) |
| `UnmountPathEvent` | `unmount_path` | `target: str` (asset id or subtree path) |
| `RemountPathEvent` | `remount_path` | `for_: str` (references the `unmount_path` id; `for` in YAML) |
| `AcquireLockEvent` | `acquire_lock` | `target: str` (asset id), `lock_type: LockType` |
| `ReleaseLockEvent` | `release_lock` | `for_: str` (references the `acquire_lock` id; `for` in YAML) |

`RemountPathEvent` and `ReleaseLockEvent` carry only the `for_` reference (like
`NetworkLagCommitEvent` / `SlowCopyCommitEvent`), using the
`AliasChoices("for_", "for")` split-alias convention so the Python field is `for_`
and the YAML key is `for`.

`Scenario.schema_version` literal updates `Literal[27]` → `Literal[28]`.

### Distinguishing asset-id targets from subtree-path targets

`simulate_quota_exceeded`, `simulate_stale_handle`, `acquire_lock` always name a
**declared asset id** — they join `_ASSET_TARGET_ACTIONS` so `rule_target_unknown`
checks them (`E_TARGET_UNKNOWN` for an unknown id).

`change_permissions`, `toggle_readonly`, `unmount_path` accept **either** form. The
disambiguation rule (mirrors how the engine treats `target`): if `target` matches a
declared asset id, it is an asset target; otherwise it is treated as a
library-relative subtree path and must resolve under `<run-dir>/library/`. A new
semantic rule `rule_network_fs_chaos_target` checks the path form: a `target` that is
neither a declared asset id nor a containable library-relative path is rejected with
`E_PATH_CONTAINMENT` (path escapes library) — reusing the established containment code,
since the asset's own rendered paths already produce it. (A bare unknown string that is
also not path-shaped resolves as a relative path under `library/` and is accepted as a
subtree that may not yet exist on disk — these are *subtree* targets, so requiring
on-disk existence at validate time is wrong; the materializer's real-chmod path
handles a missing subtree by recording the condition with `enforced=False`, never an
unhandled error.)

> Design note resolved during challenge: an asset-id-shaped string that collides with a
> real subtree path cannot occur because asset ids never contain `/`; a path target is
> any `target` not in the declared asset set. This keeps the two forms unambiguous.

### Profile gate (single source)

`ProfileName` gains `NETWORK_FS_CHAOS = "network-fs-chaos"`.
`REQUIRED_PROFILES_BY_ACTION` gains seven rows mapping each new action value to
`ProfileName.NETWORK_FS_CHAOS.value`. `rule_profile_opt_in` already iterates that map;
no rule change is needed. Generation derives gated labels from the same map, so a
generated scenario cannot drift out of sync — but v1 does not emit these actions
(non-goal), so no generation change ships.

### Engine handlers (journal + pairing state)

`WorldState` gains `pending_locks: dict[str, dict[str, object]]` and
`pending_unmounts: dict[str, dict[str, object]]` (twins of `pending_network_lags`),
each keyed by the open event's id.

- **Single-shot actions** (`change_permissions`, `simulate_quota_exceeded`,
  `toggle_readonly`, `simulate_stale_handle`) emit one `AtomicJournalEntry` recording
  the neutral `state_delta`: `target_ref`, the resolved condition, and (for
  `change_permissions`) `mode` / (for `toggle_readonly`) `mode`.
- **Paired open actions** (`acquire_lock`, `unmount_path`) emit a `StartedJournalEntry`
  and record the open in `pending_locks` / `pending_unmounts`.
- **Paired close actions** (`release_lock`, `remount_path`) pop the matching open and
  emit a `CommittedJournalEntry` with `related_event_id = for_`.

The `state_delta` carries only neutral facts; nothing app-policy-shaped. Location ids
are attached via the existing `_location_ids_for_target` when the target is a known
asset (a subtree-path target has no location id, like a lag on a non-asset target).

### Wall-clock realization

`preflight_timeline` widens its supported set with a new
`NETWORK_FS_CHAOS_ACTIONS` frozenset. A **new** `allow_network_fs_chaos: bool = False`
parameter is threaded (parallel to the existing `allow_network_lag`), not an overload
of `allow_network_lag`: the two families are independently gated, and conflating them
would let a `network-fs-lag`-only call accept chaos actions. The two wall-clock call
sites (`wall_clock.py:191`, `replay.py:143`) pass `allow_network_fs_chaos=True`
alongside `allow_network_lag=True`; the static-`materialize` call site passes neither,
so static `materialize` rejects the new actions with `TimelineUnsupportedError`
(`E_MATERIALIZE_TIMELINE_UNSUPPORTED`), exactly like lag.

**Routing.** All seven actions get **explicit branches** in `_execute_entry`
(`wall_clock.py:518`), not the `dispatch_phase_b_entry` fall-through. The four
single-shot conditions are `AtomicJournalEntry`s but are routed by their own branch
(so `dispatch_phase_b_entry` / the phase-B dispatcher never sees a chaos action and
needs no change), and the paired actions follow the lag `STARTED`/`COMMITTED` routing.
The branches:

- `change_permissions` / `toggle_readonly` → a **real `os.chmod`** on the resolved
  target under `<run-dir>/library/`. Before mutating, the original `st_mode` is
  captured into a `NetworkFsChaosSession` stored on `_DispatchState` (keyed by event
  id) so it can be restored. `toggle_readonly` clears (`readonly`) or restores
  (`readwrite`) the owner/group/other **write** bits; `change_permissions` sets the
  exact octal mode. A `NetworkFsChaosAction` is appended with `enforced=True` and
  condition `EACCES`; `toggle_readonly` additionally sets the dedicated
  `readonly_state` field (the field already committed in the report-record schema
  below — there is no `metadata` alternative).
- The four kernel-level conditions → **no filesystem op**; append a
  `NetworkFsChaosAction` with `enforced=False` and the matching condition
  (`ENOSPC` / `ESTALE` / `EAGAIN` / `UNAVAILABLE`). For the paired actions
  (`acquire_lock`/`unmount_path`), the open branch records the open in
  `pending_locks` / `pending_unmounts`, and the close branch (`release_lock` /
  `remount_path`) finalizes the `NetworkFsChaosAction` with both the open and close
  event ids and the open's target (mirroring `_wall_clock_network_lag_commit`).

**Teardown safety (ADR 0007 Q6).** Every captured original mode is restored at run
finalize (`_finalize_wall_clock_run`) **and** on the Phase-B failure path
(`_finalize_wall_clock_phase_b_failure`), in a try/finally that runs even if a later
event raises. Restoration re-`chmod`s each touched path back to its captured
`st_mode`, so the run tree is always writable/cleanable. All chmod targets resolve under
`<run-dir>/library/`; the run-dir root is never chmod'd.

### Report record

```python
class NetworkFsChaosAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str
    action: TimelineActionName            # which chaos action
    target_ref: str                       # asset id or subtree path
    condition: NetworkFsChaosCondition    # eacces / enospc / estale / eagain / unavailable
    enforced: bool                        # True iff a real os.chmod was applied
    mode: str | None = None               # octal mode for change_permissions
    readonly_state: ReadonlyState | None = None   # for toggle_readonly
    lock_type: LockType | None = None     # for acquire_lock
    related_event_id: str | None = None   # release→acquire / remount→unmount close id
    related_target_ref: str | None = None # the paired open's target, for the close record
```

`MaterializationReport` gains `network_fs_chaos_actions: list[NetworkFsChaosAction] =
Field(default_factory=list)` and bumps `MATERIALIZATION_SCHEMA_VERSION` 15 → 16
(`Literal[15]` → `Literal[16]`). The list is empty for every existing scenario, so the
field is additive on the wire (a new optional list).

**`lock_type` is a neutral recorded fact only.** Because the lock is recorded-only
(`enforced=False`), `shared` vs `exclusive` has no chaos-librarian-realized effect; it
is recorded for the consumer's adapter to interpret. The same-target-window guard
(below) treats both identically in v1 — it forbids any other mutation on the target
between `acquire_lock` and `release_lock` regardless of lock type. This intentionally
over-restricts a `shared` lock (a real shared lock would permit concurrent readers),
but a chaos *window* models an exclusive hold for v1; finer shared-vs-exclusive window
semantics are a filed follow-up. The consumer — not chaos-librarian — decides what a
`shared` lock means for its own behavior.

### Validation rules summary

| condition | layer | code |
| --- | --- | --- |
| any new action without `network-fs-chaos` profile | `rule_profile_opt_in` (existing) | `E_PROFILE_REQUIRED` |
| `change_permissions.mode` not octal `^[0-7]{3,4}$` | Pydantic field validator | (Pydantic value error → `E_FIELD_SHAPE`) |
| `simulate_quota_exceeded` / `simulate_stale_handle` / `acquire_lock` target not a declared asset | `rule_target_unknown` (existing, extended) | `E_TARGET_UNKNOWN` |
| `change_permissions` / `toggle_readonly` / `unmount_path` target neither asset nor containable library path | `rule_network_fs_chaos_target` (new) | `E_PATH_CONTAINMENT` |
| `release_lock.for` references unknown `acquire_lock` | `rule_network_fs_chaos_pairing` (new) | `E_LIFECYCLE_INVALID` |
| `remount_path.for` references unknown `unmount_path` | `rule_network_fs_chaos_pairing` (new) | `E_LIFECYCLE_INVALID` |
| `acquire_lock` / `unmount_path` with zero or >1 matching close | pairing rule | `E_LIFECYCLE_INVALID` |
| close (`release_lock` / `remount_path`) before its open | pairing rule | `E_LIFECYCLE_INVALID` |
| another same-target mutation between open and close | pairing rule (`_check_same_target_window` twin) | `E_LIFECYCLE_INVALID` |
| new action under static `materialize` | `preflight_timeline` | `E_MATERIALIZE_TIMELINE_UNSUPPORTED` |

No new validation **codes** are introduced — every failure reuses an existing code,
matching the issue's intent and the #179 reuse posture.

### Schema version

`SCENARIO_SCHEMA_VERSION` 27 → 28 (adding event variants to the union is a breaking
schema change per the no-minor-versions rule). `MATERIALIZATION_SCHEMA_VERSION` 15 → 16
(new optional list field on the report). Both literals updated; both schema artifacts
regenerated with `--write` and committed. Every fixture/recipe matching
`schema_version: 27` under `tests/` and `recipes/` is bumped to `28` as one mechanical
step (corpus tests enforce the literal). The `yaml-parse-error.yaml` fixture (pinned at
an old version, never parses) is left untouched, consistent with #178/#179/#180/#181.

`MANIFEST_SCHEMA_VERSION`, `JOURNAL_SCHEMA_VERSION`, and
`REPLAY_BUNDLE_SCHEMA_VERSION` are **not** bumped: the journal entries reuse the
existing atomic/started/committed phases, and the manifest records nothing chaos-specific
(the conditions live in the materialization report).

## Determinism / replay

The seven actions are deterministic functions of the scenario: the engine emits the
same journal entries every time, and the wall-clock runner applies the same chmod /
records the same conditions. A pure replay re-runs the wall-clock dispatch into a fresh
run dir, re-applying the chmod and re-recording the conditions from the scenario alone —
no manifest record is consulted. The `journal_digest` (sha256 of the serialized
journal with `wall_clock_time` nulled) is unaffected by the new entries' content beyond
their deterministic `state_delta`, so replay parity holds. Restored modes mean the
final on-disk tree is identical regardless of whether a `change_permissions` ran.

## The recipes

Network-fs recipes live under a category aligned with the existing `watcher/` /
`scanner/` taxonomy. v1 ships **two** recipes (validation-only, no ffmpeg, no
materialize step in the corpus — validation is the CI contract):

| recipe | shape | expected consumer response (prose only) |
| --- | --- | --- |
| `watcher/permission-denied-midscan.yaml` | `change_permissions` mode `000` on an asset mid-timeline | scanner surfaces EACCES, does not crash; recovers when mode restored |
| `watcher/lock-conflict.yaml` | `acquire_lock` (exclusive) … `release_lock` window on an asset | writer retries/backs off on EAGAIN; proceeds after release |

Each ships the `# Recipe:` header block with `# Requires: none` (validation needs no
ffmpeg) and is discovered by `tests/recipes/test_recipe_corpus.py`. Both validate clean
with the `network-fs-chaos` profile declared.

## Failure modes and edge cases

- **No new actions present** → byte-identical to today; the wall-clock dispatch takes
  no new branch, no `os.chmod`, the report's `network_fs_chaos_actions` is `[]`.
- **`change_permissions` to `000` then nothing restores it** → the runner restores the
  captured original mode at finalize regardless, so the tree is cleanable; the
  recipe/test does not need an explicit restore event.
- **`toggle_readonly readonly` on a subtree directory** → real chmod clears write bits
  on that directory; restored at teardown. Files under it are not recursively chmod'd in
  v1 (the directory's own write bit is the modeled effect; a recursive variant is a
  follow-up if needed) — stated plainly, decided in the plan.
- **Subtree-path target that does not exist on disk at run time** → recorded with
  `enforced=False` (nothing to chmod); never an unhandled error. Validation only
  requires containment, not existence (a subtree may be created later by an `add_file`).
- **`release_lock` with no matching `acquire_lock`** → `E_LIFECYCLE_INVALID`.
- **`remount_path` before its `unmount_path`** → `E_LIFECYCLE_INVALID`.
- **Another mutation on the locked/unmounted asset inside the window** →
  `E_LIFECYCLE_INVALID` (same-target-window guard).
- **A chaos action and a lag window overlap on one target** → validated independently in
  v1 (no combined rule); filed follow-up.
- **Static `materialize` of a chaos scenario** → rejected at preflight with
  `E_MATERIALIZE_TIMELINE_UNSUPPORTED` (no run-dir allocation), exactly like lag.
- **Cross-platform** → CI is `ubuntu-latest`; `os.chmod` has standard POSIX semantics on
  ext4/tmpfs. Same Linux-CI / Linux-macOS-dev posture as #178's `os.link`.
- **Schema bump** → every fixture/recipe `Literal[27]` mismatch fails the corpus tests
  until bumped to 28 (the intended forcing function).

## Acceptance criteria

- [ ] Seven new `TimelineActionName` members + seven event variants accepted by
      `Scenario.model_validate`; `change_permissions.mode` non-octal rejected.
- [ ] Each new action without `network-fs-chaos` rejected with `E_PROFILE_REQUIRED`;
      accepted with it — asserted against the live `REQUIRED_PROFILES_BY_ACTION`.
- [ ] `simulate_quota_exceeded` / `simulate_stale_handle` / `acquire_lock` with an
      unknown asset target rejected with `E_TARGET_UNKNOWN`.
- [ ] `change_permissions` / `toggle_readonly` / `unmount_path` with an asset-id target
      accepted; with a containable library path accepted; with an escaping path rejected
      with `E_PATH_CONTAINMENT`.
- [ ] `release_lock`→`acquire_lock` and `remount_path`→`unmount_path` pairing validated:
      unknown ref / unpaired / close-before-open / same-target-window-mutation →
      `E_LIFECYCLE_INVALID`.
- [ ] Wall-clock `change_permissions` produces the expected `os.stat().st_mode` on the
      target; `toggle_readonly readonly` clears the write bits; both are restored to the
      captured original mode at finalize and on the failure path (tree is cleanable).
- [ ] Wall-clock `simulate_quota_exceeded` / `simulate_stale_handle` / `acquire_lock`+
      `release_lock` / `unmount_path`+`remount_path` each append a `NetworkFsChaosAction`
      with the right `condition` and `enforced=False`; the paired close records the open
      id.
- [ ] Static `materialize` rejects each new action with
      `E_MATERIALIZE_TIMELINE_UNSUPPORTED`.
- [ ] Replay of a chaos scenario reproduces the same journal + report records.
- [ ] `SCENARIO_SCHEMA_VERSION` 27 → 28 and `MATERIALIZATION_SCHEMA_VERSION` 15 → 16;
      both artifacts regenerated; all fixtures/recipes bumped.
- [ ] Omitting all new actions is byte-identical to pre-change.
- [ ] Two new recipes ship and validate clean.

## Testing

- **Contract**: each event variant round-trips through `Scenario.model_validate`;
  `change_permissions.mode` octal validator rejects `"abc"`, `"99"`, `"12345"`; the
  paired close variants accept `for`/`for_`; `NetworkFsChaosAction` round-trips and
  rejects `extra` fields.
- **Validation (invalid fixtures, `# expected: E_*` markers)**: each new action without
  profile (`E_PROFILE_REQUIRED`); unknown asset target on the three asset-only actions
  (`E_TARGET_UNKNOWN`); escaping path on the three path-or-asset actions
  (`E_PATH_CONTAINMENT`); `release_lock`/`remount_path` unknown ref, unpaired,
  close-before-open, and same-target-window mutation (`E_LIFECYCLE_INVALID`).
- **Validation (valid fixtures)**: an asset-target and a subtree-path-target chaos
  scenario; a full `acquire`/`release` and `unmount`/`remount` window.
- **Profile gate**: assert each new action's required profile **against the live
  `REQUIRED_PROFILES_BY_ACTION`** (not a hardcoded copy), so the single-source guarantee
  is tested.
- **Wall-clock (no ffmpeg; reuse the existing wall-clock test seams)**:
  - `change_permissions`: target's `st_mode` equals the requested octal during the run;
    restored to the captured original at finalize; `NetworkFsChaosAction(enforced=True,
    condition=eacces, mode=...)` recorded.
  - `toggle_readonly readonly` clears write bits; `readwrite` restores them; restored at
    finalize.
  - each kernel-level condition records `enforced=False` with the right `condition`;
    paired close records the open id and the open's target.
  - **failure-path restore**: inject a Phase-B failure after a `change_permissions` and
    assert the mode is still restored (try/finally), so the run dir is cleanable.
  - replay parity: re-run the same scenario and assert identical journal + report
    records.
- **Preflight**: static `materialize` raises `TimelineUnsupportedError`
  (`E_MATERIALIZE_TIMELINE_UNSUPPORTED`) for each new action.
- **Backward-compat**: a scenario with none of the new actions produces a report whose
  `network_fs_chaos_actions == []` and a byte-identical tree.
- **Recipe corpus**: the two new recipes validate clean.
