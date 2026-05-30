# Issue #119 — Explicit numbering swap actions for hierarchy moves

> Status: Draft · Sprint: issue-119 · Schema impact: SCENARIO_SCHEMA_VERSION 28 → 29

## Problem

The #106 hierarchy redesign deliberately **rejects** a move/renumber whose projected
result would leave two siblings sharing an `episode_number` / `disc_number` /
`track_number`. `rule_hierarchy_timeline` replays each hierarchy action against a
projection and emits `E_HIERARCHY_INVALID` when a season/album/disc ends with a
duplicate number (`validation/rules/hierarchy.py:175-243`). It does **not** perform an
implicit swap: an author who wants episode 1 and episode 2 to exchange numbers cannot
express it with `renumber_episode`, because the intermediate state where both hold the
same number is rejected.

That rejection was intentional — implicit swaps hide author intent and make path
history ambiguous. #119 is the sanctioned follow-up: add **explicit** swap actions, now
that base hierarchy mutation semantics (`renumber_*`, `move_*`, `rename_season`) are
proven, with clear path-history and lifecycle behavior for both swapped entities.

## Proposal (issue #119)

Add three timeline actions, one per numbering axis, that exchange the number field of
two **same-parent** sibling entities in a single atomic event:

| action | exchanges | operands |
| --- | --- | --- |
| `swap_episode_numbers` | `episode_number` of two episodes in one season | `target` + `with_episode` |
| `swap_disc_numbers` | `disc_number` of two discs in one album | `target` + `with_disc` |
| `swap_track_numbers` | `track_number` of two tracks on one disc | `target` + `with_track` |

A swap is the sanctioned way to do what an implicit-swap-via-`renumber_*` is forbidden
from doing: both entities exchange their number atomically, so no intermediate
duplicate state exists and both rendered paths cross cleanly.

`absolute_number` (episodes) is **not** swapped — the swap exchanges only the axis the
action names (`episode_number`). `absolute_number` is an independent metadata field an
author renumbers explicitly via `renumber_episode` if desired; folding it into the swap
would conflate two distinct identifiers.

## The load-bearing decisions (ADR 0008)

Five decisions were settled before any code (full rationale and rejected alternatives
in [ADR 0008](../../adr/0008-numbering-swap-actions.md)). They are summarized here
because every section below depends on them.

1. **Action shape — single pairwise swap, one action per axis.** Three actions
   (`swap_episode_numbers` / `swap_disc_numbers` / `swap_track_numbers`), mirroring the
   one-action-per-axis pattern of `renumber_episode` / `renumber_disc` /
   `move_track_to_disc`. No range-rebalance action in v1 (speculative, no fixture
   demand; filed as a follow-up).
2. **Same-parent only.** The two entities MUST share the same parent (same season for
   episodes, same album for discs, same disc for tracks). Cross-parent exchange stays
   expressible as two `move_*` events; bundling it into a swap would conflate a number
   exchange with a relocation and muddy the path history.
3. **Exchange numbers, re-render.** The engine swaps the number field on each entity via
   `model_copy(update=...)` and lets the existing `_hierarchy_entry` renderer recompute
   both rendered paths — identical mechanism to `renumber_*`. The renderer emits the two
   crossed `path_moves` (A's new path is B's old path and vice versa) and the existing
   `sidecar_moves` machinery moves each side's renderer-derived subtitle sidecar
   alongside its media file.
4. **Failure contract — reuse existing codes.** No new error code.
   - Unknown `target` or `with_*` entity id → `E_TARGET_UNKNOWN`.
   - `target` and `with_*` not the same entity kind, or not sharing a parent, or naming
     the same entity twice, or a projected result that would *still* leave a duplicate
     number anywhere in the affected sibling group → `E_HIERARCHY_INVALID` (the same code
     the post-mutation duplicate check already emits).
   - Swap touching an asset with a pending `slow_copy` or inside an open window →
     `E_LIFECYCLE_INVALID` (exactly like every other hierarchy action via
     `_lifecycle_check_hierarchy_action`).
5. **Operand shape — `target` + `with_*`.** `target` names entity A; a `with_*`
   companion field names entity B, mirroring how `move_episode_to_season.to_season` and
   `move_track_to_disc.to_disc` name the second operand. Keeps `rule_target_unknown`
   reuse trivial (it already resolves `target`; the `with_*` field is added to the same
   per-action target-field map).

## Materialization — no new code

The materializer **already** realizes any hierarchy mutation's `path_moves` through a
collision-free two-phase temp-path dance in
`materializer/phase_b/filesystem.py::_hierarchy_moves`:

```
for plan in planned: plan.source.replace(plan.temp)      # everything to a temp name
for plan in planned: plan.temp.replace(plan.destination) # temp names to final names
```

`_plan_hierarchy_moves` already tolerates a destination that is also another move's
source (the `destination.exists() and destination not in source_paths` guard does *not*
fire when the destination is itself a source). A swap emits exactly that mutual-crossing
shape: A.from == B.to and B.from == A.to.

A standalone probe against the real `_plan_hierarchy_moves` + execution confirmed a
mutual-crossing swap of two files completes correctly (`A` ends with `B`'s old bytes and
vice versa) with no collision and no leftover temp file. The build phase locks this in
with a regression test that drives the real planner with crossed moves, so the
"materializer needs no new code" claim is falsifiable and guarded, not asserted.

## Schema changes (`contract/scenario.py`)

- Add three members to `TimelineActionName`: `SWAP_EPISODE_NUMBERS = "swap_episode_numbers"`,
  `SWAP_DISC_NUMBERS = "swap_disc_numbers"`, `SWAP_TRACK_NUMBERS = "swap_track_numbers"`.
- Add the three members to `HIERARCHY_TIMELINE_ACTIONS` (so path-history projection,
  the lifecycle hierarchy branch, and `is_hierarchy_action` pick them up with no further
  wiring).
- Add three event variants to the `TimelineEvent` discriminated union:
  - `SwapEpisodeNumbersEvent(target: str, with_episode: str)`
  - `SwapDiscNumbersEvent(target: str, with_disc: str)`
  - `SwapTrackNumbersEvent(target: str, with_track: str)`
  Each carries only the two operand fields plus the inherited `id` / `at`; no number
  arguments (the numbers come from the two entities being swapped).
- Bump `Scenario.schema_version` literal and `SCENARIO_SCHEMA_VERSION` 28 → 29.
- Regenerate `schemas/scenario.schema.json` (`--write`). No other schema artifact
  changes: manifest / journal / replay-bundle / materialization are unchanged because a
  swap reuses the existing hierarchy `state_delta` shape.

## Validation

A swap is a hierarchy action, so it flows through the existing hierarchy rules with
small additions:

1. **`rule_target_unknown`** — extend the per-action target-field map so both `target`
   and the axis-specific `with_*` field are resolved against the declared entity pool.
   Unknown id → `E_TARGET_UNKNOWN` (existing message/behavior).
2. **`rule_hierarchy_timeline`** (`HierarchyProjection.apply`) — add a swap branch that:
   - looks up both entities; if either is missing, the projection no-ops (target-unknown
     already reported the missing id) and emits nothing new here;
   - if the two ids are equal, or the entities do not share a parent, emits
     `E_HIERARCHY_INVALID` ("swap requires two distinct same-parent <kind>s");
   - otherwise exchanges the two number fields and returns the affected
     season/album/disc id so the existing `_check_hierarchy_mutation_numbers` runs the
     post-mutation duplicate check unchanged. A well-formed pairwise swap of two distinct
     same-parent siblings can never produce a duplicate, but a malformed scenario (e.g. a
     third sibling already holding one of the swapped numbers) is caught by that existing
     check — reusing it rather than re-deriving the invariant.
   - `affected_asset_ids` returns the union of both entities' assets so the existing
     path-collision and rendered-path checks cover both sides.
3. **`rule_timeline_lifecycle`** — the swap is dispatched through the existing
   `is_hierarchy_action` branch (`_lifecycle_check_hierarchy_action`), which already
   rejects a hierarchy action touching an asset with a pending slow_copy
   (`E_LIFECYCLE_INVALID`) and projects sidecar moves. Adding the three actions to
   `HIERARCHY_TIMELINE_ACTIONS` is the only wiring needed.

The previously-forbidden implicit-swap-via-`renumber_*` case **stays rejected**: a
`renumber_episode` that sets episode 1's number to 2 while episode 2 still holds 2 still
trips `_check_projected_episode_numbers` → `E_HIERARCHY_INVALID`. The explicit
`swap_episode_numbers` is the accepted alternative. A build-phase test asserts both
halves of this in one place.

## Path history and lifecycle semantics

- **Path history** — `engine/path_history.py::_hierarchy_path_entries` already projects
  a hierarchy entry's `path_moves` into one `PathHistoryEntry` per affected asset. After
  a swap, asset A's `path_history` shows `from_path = A_old`, `to_path = A_new (== B_old)`
  and asset B's shows `from_path = B_old`, `to_path = B_new (== A_old)` — each side's
  history reflects the swap cleanly from its own perspective, with no cross-references.
- **Lifecycle** — a swap is an atomic hierarchy event. Both entities' assets must be
  placed (the projection only renders managed, located assets); an asset with a pending
  slow_copy on either side rejects with `E_LIFECYCLE_INVALID` exactly as `renumber_*`
  does. No new open window is introduced — a swap is single-shot, like every other
  hierarchy mutation.

## Oracle / manifest record (policy-neutral)

A swap reuses the existing `_hierarchy_entry` path: one `AtomicJournalEntry` whose
`state_delta` carries `metadata` (the before/after of each entity's number field),
`path_moves` (the two crossed moves), `sidecar_moves`, and `skipped_deleted_asset_ids`.
`target_ids` is `[entity_a_id, entity_b_id, *asset_ids]`. The manifest is updated by
`model_copy(update=...)` on both entities. **No expected consumer verdict** is recorded —
the journal states only what changed (policy-neutral, per AGENTS.md and the #179
precedent). No manifest schema change: a swap is two number-field updates the manifest
already represents.

## Backward compatibility

- Every existing scenario stays valid beyond the mandatory `schema_version: 29` bump. A
  timeline with none of the three new actions is byte-identical to its pre-change
  behavior: the new union variants are reachable only via the new discriminator values,
  and `HierarchyProjection.apply` / the lifecycle dispatch fall through to existing
  branches for every other action.
- Fixtures/recipes carrying `schema_version: 28` are mass-bumped to `29` (no semantic
  change). The invalid-fixture corpus gains swap-specific cases; existing invalid
  fixtures are unaffected.
- Only `schemas/scenario.schema.json` regenerates.

## Test plan (TDD)

Behavior-first, edges and errors included:

1. **Schema round-trip** — each of the three swap events parses through
   `Scenario.model_validate` and rejects unknown fields / missing operand
   (`extra="forbid"` + required field).
2. **Valid same-parent swap exchanges numbers and paths** — a two-episode season swap
   leaves the two episodes with each other's `episode_number`; the projection's rendered
   paths are crossed; both `path_history` projections reflect the swap (one entry each,
   crossed from/to). Same for discs and tracks.
3. **Crossed path_moves survive the real materializer** — drive the real
   `_plan_hierarchy_moves` + two-phase execution with mutually-crossed moves and assert
   the on-disk bytes are exchanged with no leftover temp file (locks the "no new
   materializer code" claim).
4. **Reject still-duplicate** — a swap that, combined with a third sibling already
   holding a swapped number, leaves a duplicate → `E_HIERARCHY_INVALID`.
5. **Reject non-sibling / same-id / unknown** — different-parent pair →
   `E_HIERARCHY_INVALID`; `target == with_*` → `E_HIERARCHY_INVALID`; unknown `target`
   or `with_*` → `E_TARGET_UNKNOWN`.
6. **Implicit-swap still rejected, explicit accepted** — one test asserts the
   `renumber_episode`-into-a-duplicate case still emits `E_HIERARCHY_INVALID` while the
   equivalent `swap_episode_numbers` validates clean.
7. **Existing scenarios still valid** — the sample-scenario corpus and invalid corpus
   pass after the bump.
8. **Lifecycle interaction** — a swap on an asset with a pending `slow_copy` →
   `E_LIFECYCLE_INVALID`; a fields-unset timeline (no swap) takes the identical
   pre-change projection path (covered by the unchanged existing corpus).
9. **Corpus fixtures** — a valid swap fixture per axis under
   `tests/fixtures/scenarios/`, and invalid fixtures (`# expected: E_...` marker) for the
   non-sibling and still-duplicate cases.

## Out of scope (filed follow-up)

- An explicit **range-rebalance / renumber-range** action that reassigns an ordered
  numbering across a whole sibling group in one event. No fixture demands it in v1;
  pairwise swap is the minimal primitive that inverts the forbidden implicit swap. Filed
  as a tracked follow-up and referenced in the PR.
