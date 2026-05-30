# 0008 — Explicit numbering swap actions for hierarchy moves

## Status

Accepted

## Context

The #106 hierarchy redesign deliberately **rejects** a move/renumber whose projected
result would leave two siblings sharing an `episode_number` / `disc_number` /
`track_number`: `rule_hierarchy_timeline` replays each action against a projection and
emits `E_HIERARCHY_INVALID` on a post-mutation duplicate
(`validation/rules/hierarchy.py`). It does **not** perform an implicit swap, so an
author cannot make two siblings exchange numbers — the intermediate state where both
hold the same number is rejected. That rejection was intentional: implicit swaps hide
author intent and make path history ambiguous.

Issue #119 is the sanctioned follow-up: add **explicit** swap actions now that the base
hierarchy mutations (`renumber_*`, `move_*`, `rename_season`) are proven, with clear
path-history and lifecycle behavior for both swapped entities.

Two pieces of existing machinery shape the decisions below:

- **Materialization is already collision-free.**
  `materializer/phase_b/filesystem.py::_hierarchy_moves` realizes any hierarchy
  mutation's `path_moves` through a two-phase temp-path dance (everything to a temp
  name, then temp names to final names). `_plan_hierarchy_moves` already tolerates a
  destination that is also another move's source. A probe against the real planner +
  execution confirmed a mutually-crossing swap (A.from == B.to, B.from == A.to) of two
  files completes correctly with no collision and no leftover temp file. So a swap needs
  **no new materializer code** — only the engine emitting crossed `path_moves`. A
  regression test locks this in.
- **Path history and the oracle journal are already policy-neutral and per-asset.**
  `engine/path_history.py` projects a hierarchy entry's `path_moves` into one
  `PathHistoryEntry` per affected asset; `_hierarchy_entry` records a neutral
  `state_delta` (metadata / path_moves / sidecar_moves). Both are reusable as-is.

The existing one-action-per-axis pattern (`renumber_episode` / `renumber_disc` /
`move_track_to_disc`) and the `target` + `to_*`/`with_*` operand convention
(`move_episode_to_season.to_season`, `move_track_to_disc.to_disc`) are the structural
templates throughout.

## Decision

1. **Single pairwise swap, one action per axis.** Add `swap_episode_numbers`,
   `swap_disc_numbers`, `swap_track_numbers` to `TimelineActionName` and as three
   `TimelineEvent` variants. Each exchanges the number field of two sibling entities. No
   range-rebalance action in v1.
2. **Same-parent only.** The two entities MUST share the same parent (season / album /
   disc). Cross-parent exchange stays expressible as two `move_*` events.
3. **Exchange numbers, re-render.** The engine swaps the number field on each entity via
   `model_copy(update=...)` and lets the existing `_hierarchy_entry` renderer recompute
   both paths, emitting the two crossed `path_moves` and moving each side's
   renderer-derived sidecar. Identical mechanism to `renumber_*`. `absolute_number` is
   not swapped — only the named axis (`episode_number` / `disc_number` / `track_number`).
4. **Reuse existing error codes — no new code.** Unknown `target` / `with_*` →
   `E_TARGET_UNKNOWN`; not-same-kind / not-same-parent / same-id-twice / would-still-leave
   a duplicate → `E_HIERARCHY_INVALID` (the existing post-mutation duplicate check);
   pending-slow-copy / open-window interaction → `E_LIFECYCLE_INVALID` (existing
   hierarchy lifecycle branch).
5. **Operand shape — `target` + `with_*`.** `target` names entity A; `with_episode` /
   `with_disc` / `with_track` names entity B, mirroring the `to_*` operand convention.
   The `with_*` field joins the same per-action target-field map `rule_target_unknown`
   already reads.

Schema impact: `SCENARIO_SCHEMA_VERSION` 28 → 29 (three new event variants). Only
`schemas/scenario.schema.json` regenerates; manifest / journal / replay-bundle /
materialization are unchanged because a swap reuses the existing hierarchy `state_delta`
shape and number-field manifest updates.

## Consequences

- Three `TimelineActionName` members + three event variants enter the scenario schema,
  and join `HIERARCHY_TIMELINE_ACTIONS` (path-history projection, lifecycle hierarchy
  branch, and `is_hierarchy_action` pick them up with no further wiring).
- Each swap is one atomic `AtomicJournalEntry`; after a swap, asset A's `path_history`
  shows its old→new (== B's old) path and B's shows its old→new (== A's old) path — each
  side clean from its own perspective.
- The previously-forbidden implicit-swap-via-`renumber_*` stays rejected
  (`E_HIERARCHY_INVALID`); the explicit swap is the accepted alternative.
- Every existing scenario stays valid beyond the mandatory `schema_version: 29` bump; a
  timeline with none of the three actions is byte-identical to pre-change behavior.
- No new materializer code: crossed `path_moves` flow through the existing two-phase
  temp dance, guarded by a regression test.
- Deferred to a filed follow-up: an explicit range-rebalance / renumber-range action
  reassigning an ordered numbering across a whole sibling group.

## Considered & rejected

**Q1 — Action shape: single pairwise swap vs range-rebalance vs both.**
- *Rejected: a `rebalance_*` action giving an explicit new ordered numbering for a set
  of siblings.* No fixture demands it; it is a speculative generalization (AGENTS Rule 3,
  no-speculative-features). Pairwise swap is the minimal primitive that directly inverts
  the forbidden implicit swap.
- *Rejected: ship both.* Doubles the schema surface and the validation/engine paths for a
  capability only one of which is needed now.
- **Chosen: single pairwise swap, one action per axis** (`swap_episode_numbers` /
  `swap_disc_numbers` / `swap_track_numbers`), mirroring `renumber_episode` /
  `renumber_disc` / `move_track_to_disc`. Range-rebalance filed as a follow-up.

**Q2 — Same-parent only vs cross-parent exchange.**
- *Rejected: allow the two entities to live under different parents and exchange both
  parent and number.* That is two independent `move_*` operations and is already
  expressible; bundling relocation into a swap conflates a number exchange with a move
  and muddies each side's path history.
- **Chosen: same-parent only.** The case #106 forbade was a same-sibling-group duplicate;
  a same-parent swap is a pure number exchange with clean, symmetric path history.

**Q3 — Exchange numbers (re-render) vs exchange full rendered paths directly.**
- *Rejected: record the two rendered paths and swap them directly.* Bypasses the
  renderer, so it diverges from how every other hierarchy handler computes paths and
  would need bespoke handling for unmanaged / `add_file`-pathed assets and sidecars.
- **Chosen: exchange the number field and re-render.** Matches every existing hierarchy
  handler (`model_copy(update=...)` then `_hierarchy_entry` re-renders), so crossed
  `path_moves`, sidecar moves, and unmanaged-asset rules all come for free.

**Q4 — Failure contract: reuse existing codes vs a new `E_SWAP_INVALID`.**
- *Rejected: add a dedicated `E_SWAP_INVALID`.* The contract is genuinely identical to
  existing hierarchy semantics — a swap referencing two non-sibling entities, or one that
  leaves a duplicate, is exactly the `E_HIERARCHY_INVALID` condition the post-mutation
  check already emits; an unknown operand id is exactly `E_TARGET_UNKNOWN`. The #179 /
  #111 precedent is "define new codes only if the contract differs."
- **Chosen: reuse `E_TARGET_UNKNOWN` (unknown operand), `E_HIERARCHY_INVALID`
  (not-sibling / same-id / still-duplicate / shape), `E_LIFECYCLE_INVALID`
  (pending-slow-copy / open window).** No new code.

**Q5 — Operand field shape: `target` + `with_*` vs a two-element list.**
- *Rejected: a two-element list field naming both entities.* Breaks the `target`-centric
  convention every timeline event follows and would need special handling in
  `rule_target_unknown`'s per-action target-field map and in the JSONPath formatter.
- **Chosen: `target` (entity A) + a `with_*` companion (entity B),** mirroring
  `move_episode_to_season.to_season` / `move_track_to_disc.to_disc`. `rule_target_unknown`
  resolves both by adding `with_*` to the existing per-action map.
