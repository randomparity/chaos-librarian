# Imported mutation timelines — issue #233

## Problem and authority

Issue #233 requests optional deterministic mutation timelines for real-media imports.
The operator approved the campaign exclusions on 2026-10-23; the frozen authority is
[#233 scope](https://github.com/randomparity/chaos-librarian/issues/233#issuecomment-6376138222).
This full-spec design has complexity M and fixed denominator 250 changed lines.
Implementation awaits operator approval of the public options and behavior below.

## Interface and architecture

Add `import --add-chaos`, with optional `--chaos-seed INTEGER` and
`--chaos-events INTEGER`. With the flag, omitted seed resolves to 0 and omitted
count to 12. Seeds must be nonnegative; counts must be 1..1000 inclusive. Supplying
either tuning option without the flag is usage error 2, as are invalid values.
Without the flag, retain seed 0 and the existing sidecar-only timeline unchanged.
With the flag, store the resolved chaos seed in the scenario's existing seed field.
The report and optional mapping artifact retain their existing shapes and meaning.

Extend the existing generator with a bounded imported-topology entry point in
`generation/import_timeline.py`, called by the importer emitter after its existing
sidecar destinations are resolved. It consumes the final surviving asset IDs and
containers, rendered initial paths, reserved IDs and sidecar paths. It reuses
`RngStreams`/`TraceRecorder` and existing `TimelineEvent` contract models; no new
schema, action, dependency or materializer handler is introduced. Synthetic lane
builders remain unchanged: their fixed topology/cardinality cannot represent a
single arbitrary imported asset. This is a clean extension, not an ownership move.

Use sorted asset IDs and the named `import-chaos` RNG stream. Generate exactly N
additional events, starting with a rename on a seeded asset to guarantee an
observable filesystem mutation even for N=1. Remaining events choose among
`rename_file`, `move_asset`, and `touch_mtime` and choose a surviving media asset.
Mtime offsets are positive one second. There are no deletion/addition or track
rewrites, so each asset stays placed and its copied original remains intact.
Initial sidecar events remain at 0s; mutation events occur at 1ns..Nns and retain
list order after those sidecars. The same final topology, seed and count produce
the same mutation sequence; the existing timestamp-bearing scenario ID is not
promised byte-identical across separate imports.

The importer reconstructs ID reservations from the final emitted scenario entities,
root IDs and initial sidecar/event IDs, excluding allocations for capped-out works.
Each generated event reserves an `import-chaos-NNNN` candidate, adding a numeric
suffix on collision. Reserve a directory below the library root whose name is
`import-chaos` with a numeric suffix when an initial media/sidecar path occupies
it or descends from it. Each move/rename destination uses that directory, event
ID and original container suffix; reserve generated destinations as they are
created. Both rename and move use existing asset-targeted semantics. The planner
receives imported asset IDs only, never sidecar IDs. Full validation runs through
the existing emitter report pipeline before returning success; failure rolls back
this attempt's new outputs under the existing importer publication boundary.

## Success

1. Default import preserves its current seed, timeline and report/mapping shapes.
2. Opt-in emits exactly the requested additional events after initial sidecars;
   fixed topology/seed/count yield equal sequences for one-asset and mixed movie,
   TV and music imports, including caps and duplicate-content topology.
3. Generated event IDs and media destinations avoid the supplied initial entity,
   sidecar and event reservations; the three-action allowlist cannot emit imported
   track mutations. Validation and plan accept the generated scenarios.
4. A real import with chaos validates, plans and materializes, with the first
   rename reflected in the library and copied media bytes preserved.
5. CLI help/documents explain defaults, bounds, ordering and the action subset;
   invalid combinations fail before scan/staging and preserve existing outputs.

## Failure model

- Actors and deployments: trusted local CLI operators and CI using supported
  Python platforms, scanning local libraries and writing local scenario bundles.
- Invariants/assets: original files and pre-existing outputs survive; default
  import compatibility, finite generation, deterministic sequence, unique IDs,
  contained paths and executable imported-media events matter.
- Accepted classes: process kill/power loss may leave partial outputs; hostile
  concurrent parent-directory replacement and unlink cleanup failures retain the
  existing importer boundary, not a new cross-file transaction guarantee.
- Covered elsewhere: media fidelity, copy publication and imported track-event
  restrictions belong to ADR0012 and existing import tests; mapping belongs to
  merged #234; full synthetic lane coverage remains with repository maintainers.

## Threat model

- Added boundary: operator-supplied chaos seed/count; enforce nonnegative seed,
  count 1..1000 and explicit opt-in before scanning. No new external services.
- Widened boundary: imported names/IDs become event targets and paths. Trust the
  existing topology sanitization; allocate IDs against its reservation set and
  generated paths inside an unused root child, then run full scenario validation.
- Controls: structured event models/JSON/YAML serializers, existing path containment
  and lifecycle validation, and current no-overwrite bundle publication. Filenames
  remain data; no shell execution or new disclosure beyond existing artifacts.
- Outside scope: hostile local filesystem actors and crash transactions are
  accepted above; consumer policy is owned by the application under test.

## Alternatives and validation

[ADR0013](../../adr/0013-imported-mutation-timelines.md) records the reuse boundary.
Direct synthetic fuzz-lane reuse rejects arbitrary cardinalities; generating a new
synthetic library would violate imported-topology preservation. The recommended
bounded entry point reuses deterministic primitives without synthetic-only actions.
Tests cover exact count/order/determinism, allowed actions, reservation collisions,
CLI combinations, default compatibility, caps/mixed topology (including identical
surviving topology with/without a capped work named `import-chaos-0001`), validation/plan and
one equipped real-media import/materialization. No instruction or CI changes.
