# Issue #112 - Track live sidecar metadata during phase-B materialize

**Status:** design for implementation.
**GitHub issue:** [#112](https://github.com/randomparity/chaos-librarian/issues/112)
**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md)
("Sprint 7 - Media phase-B").
**Target implementation branch:** `feat/live-sidecar-metadata-112`.

## Goal

Make phase-B `update_sidecar` resolve a sidecar's `(kind, language, asset_id)`
metadata from state that reflects the journal order it is replaying, instead of
only from the final manifest. This lets a valid timeline that creates, updates,
then later embeds or removes the same sidecar materialize without a spurious
`E_MATERIALIZE_MEDIA_FAILED`.

This design does not change any contract model, schema artifact, or journal
shape. It is a materializer-internal change.

## Context

`make_phase_b_state` builds the `update_sidecar` metadata lookup with
`_sidecar_lookup_from(manifest)` in
`src/chaos_librarian/materializer/phase_b/__init__.py`, where `manifest` is
`plan_artifacts.current_manifest` — the manifest **after the whole journal
window has been applied** (`engine/plan.py`: `current_manifest =
initial_state.to_manifest()`).

`_apply_update_sidecar` in
`src/chaos_librarian/materializer/phase_b/media.py` calls
`ctx.sidecar_lookup(sidecar_id)` and raises a `MediaActionError`
(`update_sidecar: sidecar_id ... not in manifest`) when the lookup returns
`None`.

A timeline `create_sidecar(S) → update_sidecar(S) → embed_subtitle(S)` (or
`remove_sidecar(S)`) drops `S` from the final manifest, because the engine's
`embed_subtitle` / `remove_sidecar` handlers remove the row from
`state.sidecars`. The journal still carries the `update_sidecar(S)` entry, and
phase-B walks the journal in order, so when `update_sidecar(S)` runs the lookup
against the **final** manifest already fails. The fuzz-generation branch worked
around this by not generating that sequence; this issue removes the limitation.

The metadata `update_sidecar` actually needs is small and stable:

- `kind` — selects the byte renderer (`regenerate_sidecar`).
- `language` — required for subtitle sidecars; `None` for poster / NFO.
- `asset_id` — resolves `asset.duration_seconds` from `scenario_assets`.

Both inputs that can supply this metadata are available before
`update_sidecar(S)` runs:

1. Sidecars present at the **start** of the phase-B window. These live in the
   per-window `initial_manifest` (`engine/plan.py`: `current_manifest ==
   initial_manifest` when the journal is empty). This covers declared
   subtitles seeded by `build_initial_state` that have no `create_sidecar`
   journal entry, including a declared-subtitle → update → remove sequence.
2. Sidecars created mid-walk by a journal entry. Two engine handlers
   allocate a fresh `sidecar_id` and add a row to `state.sidecars`:
   - `create_sidecar` — `state_delta` carries `sidecar_id`, `kind`,
     `language`; `target_ids[0]` is the asset id.
   - `extract_subtitle` — `state_delta` carries `sidecar_id`, `language`
     (kind is always `subtitle`); `target_ids[0]` is the asset id. This is
     also a live creation source: an `extract_subtitle(S) → update_sidecar(S)
     → remove_sidecar(S)` sequence drops `S` from the final manifest exactly
     like the create case.

   The creating entry always precedes any `update_sidecar` on the same
   sidecar in journal order (lifecycle validation rejects
   update-before-create).

## Decision

Add a **live sidecar registry** to `MediaPhaseBContext`: a
`dict[str, LiveSidecar]` keyed by `sidecar_id`, where `LiveSidecar` carries
`(kind, language, asset_id)`.

- `make_media_phase_b_context` seeds the registry from the **per-window
  initial** manifest sidecars (a new `initial_sidecars` argument). This is the
  metadata of every sidecar that exists when the phase-B walk begins.
- `_apply_create_sidecar` and `_apply_extract_subtitle` record the created
  sidecar's metadata into the registry as they are dispatched, so later entries
  in the same walk can resolve it even if it never survives to the final
  manifest.
- `_apply_update_sidecar` resolves metadata from the live registry. The
  previous final-manifest `sidecar_lookup` is removed: the registry is a strict
  superset of what the final-manifest lookup could resolve, so keeping both
  would be dead code.

`make_phase_b_state` gains an `initial_manifest` parameter and forwards its
sidecars to the media context. The three call sites
(`run.py`, `replay.py`, `wall_clock.py`) already hold the matching
per-window `PlanArtifacts` and pass `artifacts.initial_manifest`.

The failure contract is unchanged: when neither the seed nor a prior
`create_sidecar` supplies the sidecar (a genuinely corrupt journal that updates
a sidecar that never existed), `_apply_update_sidecar` still raises
`MediaActionError` with `E_MATERIALIZE_MEDIA_FAILED`.

## Why not keep the final-manifest lookup as a fallback

The live registry resolves every sidecar the final-manifest lookup could
resolve (a surviving sidecar is in the final manifest *and* was either seeded
from the initial manifest or created during the walk) plus the ones it could
not (created-or-declared, then removed). A retained fallback would never fire,
so it would be dead code — removed per the project's "replace, don't deprecate"
rule.

## Why not thread the final manifest only and reconstruct live state

`update_sidecar` runs mid-walk; reconstructing the live set would mean
re-deriving engine state inside the materializer, duplicating
`state.sidecars` lifecycle logic. Seeding from `initial_manifest` plus
observing `create_sidecar` dispatches reuses the journal the materializer is
already walking and adds no engine coupling.

## Test plan

Behavior tests in `tests/materializer/`:

- create → update → remove same sidecar: `update_sidecar` succeeds, bytes are
  regenerated, and the removed sidecar is absent from the final manifest.
- create → update → embed same sidecar: `update_sidecar` succeeds before the
  embed consumes the sidecar.
- declared subtitle → update → remove: resolves from the initial-manifest seed
  with no `create_sidecar` entry.
- extract → update → remove same sidecar: resolves from the `extract_subtitle`
  registry write, with the sidecar absent from the final manifest.
- double update on a created sidecar: both updates resolve; second update sees
  the registry entry from create.
- update of a sidecar that was never created or seeded: still raises
  `MediaActionError` (corrupt-journal guard preserved).

## Out of scope

- No contract / schema / journal changes.
- No change to `embed_subtitle` or `remove_sidecar` handlers, and no change to
  `extract_subtitle` beyond adding its registry write.
