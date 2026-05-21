# Sprint 8 - Wall-Clock Mode

**Status:** design, pending implementation plan.
**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md)
("Sprint 8 - Wall-Clock Mode", "Wall-Clock Mode", "Time Model", and
"Mutation Model").
**Predecessor:** Sprint 7 (`feat/sprint-7`, merged on `main`) extended the
phase-B materializer to execute media mutations through the same journal walk
as filesystem mutations.
**Target branch:** `feat/sprint-8`.

## Goal

Implement `chaos-librarian run` as the wall-clock execution mode for watcher,
daemon, and reconciliation tests.

Sprint 8 is a scheduler-and-dispatch sprint, not a second engine. The runner
uses the same validation pipeline, scenario model, resolved timeline, plan
engine, journal entries, and phase-B disk effect handlers that `materialize`
already uses. The new behavior is that journal entries execute when their
logical time becomes due under a wall-clock timer and `--speed`.

Exit criteria:

- `chaos-librarian run scenario.yaml --out run-001 --duration 90s --speed 10x`
  executes real filesystem and media changes over wall-clock time.
- Active Library Churn exists as a first-pack scenario and runs end-to-end.
- Step/plan and wall-clock journals are logically identical except
  `wall_clock_time`.
- A wall-clock replay bundle reproduces the final logical state without
  preserving original pacing.

## Decisions Resolved In Brainstorming

1. **Implementation approach.** Use a wall-clock scheduler over the existing
   phase-B materializer dispatch. Do not build a separate wall-clock engine.

2. **`--duration` semantics.** `--duration` is real wall-clock runtime. With
   `--duration 90s --speed 10x`, the process remains active for about 90 real
   seconds and can advance up to about 900 seconds of logical scenario time.

3. **Early timeline completion.** If every due event has executed before
   `--duration` expires, `run` stays alive and idle until the requested
   wall-clock duration elapses. Scripts can rely on the command's runtime as an
   orchestration boundary.

4. **Deadline overrun.** If the wall-clock deadline passes while an event is
   in progress, finish that in-flight event, then finalize. Do not abort
   halfway through ffmpeg or filesystem mutation work.

5. **Slow-copy visibility.** Wall-clock `slow_copy` exposes a temp file that
   grows between `slow_copy_start` and `slow_copy_commit`, but emits no
   progress journal entries. The only logical journal entries remain the
   existing start and commit records.

6. **Live artifacts.** Append `journal.jsonl` incrementally as entries execute.
   Write `manifest.current.json`, `replay.json`, reports, and
   `materialization.json` only during finalization.

7. **Replay pacing.** Replay of a wall-clock run reproduces the final logical
   state and files. It does not preserve original wall-clock pacing.

8. **Interruption.** An interrupted run leaves the sentinel at
   `state=in_progress` with any live journal entries already appended. It does
   not write a partial replay bundle or pretend to be complete.

9. **`add_file` meaning.** `add_file` is reappearance/restoration of the same
   declared asset after an earlier timeline event made it disappear. It does
   not create a new work, variant, bundle, asset, or version.

## Scope

### In Scope

- Implement `chaos-librarian run`.
- Parse and validate `--duration` and `--speed`.
- Execute due journal entries over wall-clock time.
- Fill `wall_clock_time` on executed journal entries.
- Keep the process alive until `--duration` elapses.
- Preserve live `journal.jsonl` evidence during the run.
- Add wall-clock-specific slow-copy partial growth.
- Add materialized `add_file` restoration after prior disappearance.
- Emit run timing fields in `materialization.json`.
- Emit replay bundles with `execution_mode: "run"`.
- Add Active Library Churn fixture.
- Add outcome-oriented replay support for wall-clock bundles.

### Out Of Scope

- Progress journal entries for slow copy.
- General "new asset discovered" semantics for `add_file`.
- Concurrent or overlapping mutations beyond already-modeled slow-copy pairs.
- Preserving original wall-clock pacing during replay.
- Renaming `materialization.json`.
- Changing the scenario schema.
- Implementing the deferred Sprint 7 media mutations.

## Architecture

Add a wall-clock runner module that composes the existing engine and
materializer layers:

```text
src/chaos_librarian/materializer/
  wall_clock.py           # run_wall_clock_scenario(...) orchestration
  scheduler.py            # speed parsing, due-event calculation, sleeps
  run.py                  # batch materialize remains here
  dispatch.py             # shared journal-entry dispatch helper, if needed
```

The exact helper-module names can change in the implementation plan, but the
ownership boundary should stay stable:

- The engine stays pure and filesystem-free.
- `run_plan` remains the source of logical artifacts.
- The journal remains the boundary between planned state and real disk effects.
- Materializer code owns real files, ffmpeg, hashes, probes, and reports.
- The wall-clock layer owns time, sleeping, liveness, and deadline behavior.

Batch `materialize` and wall-clock `run` should reuse the same stdlib/media
dispatch code. If current helpers are batch-only, factor a small internal
dispatcher rather than duplicating per-action behavior.

## Runtime Flow

```text
chaos-librarian run scenario.yaml --out fixtures/run-001 --duration 90s --speed 10x
  cli.commands.run
    prepare_run_input
    run_validation                                  # exit 3 on validation failure
    preflight_timeline + capability checks          # exit 4/5 on unsupported tools/actions
    run_plan(..., steps_limit=None)                 # full logical journal + manifests
    begin run-dir with sentinel state=in_progress
    phase A synthesize declared assets and sidecars
    start monotonic wall-clock timer
    while elapsed < requested_duration or event in progress:
      logical_now_ns = elapsed_wall_ns * speed_multiplier
      execute all due journal entries in order
      append each executed journal entry to journal.jsonl
      sleep until next due event or deadline
    finalize metadata and reports
    replace sentinel with state=complete
```

The scheduler executes entries by journal order, not by querying mutable world
state. Event paths and action inputs still come from `entry.state_delta`, which
preserves Sprint 7's "journal is the truth source" rule.

Wall-clock journal entries are copied from the precomputed plan journal with
`wall_clock_time` filled at execution time. No other logical field should be
changed by the scheduler. This keeps step/plan and wall-clock journals directly
comparable after stripping `wall_clock_time`.

## CLI Semantics

`run` keeps the frozen CLI shape:

```text
chaos-librarian run scenario.yaml --out fixtures/run-001 --duration 90s --speed 10x --json
```

`--duration`:

- Required.
- Parsed with the existing duration grammar.
- Means wall-clock runtime, not scenario logical duration.
- Must be greater than zero.

`--speed`:

- Optional, default `1x`.
- String form: positive integer or decimal multiplier followed by `x`.
- Examples: `1x`, `2x`, `10x`, `0.5x`.
- Reject zero, negative, missing suffix, and unparsable values as usage errors
  with exit code 2.

`--json` success output should be a small summary, not the full report:

```json
{
  "ok": true,
  "run_id": "<uuid>",
  "scenario_id": "active-library-churn",
  "out": "/absolute/path/to/run-001",
  "execution_mode": "run",
  "requested_duration_ns": 90000000000,
  "actual_duration_ns": 90123456789,
  "speed_multiplier": "10",
  "applied_events": 12,
  "overran_duration": false,
  "materialization_report_path": "/absolute/path/to/run-001/materialization.json",
  "replay_bundle_path": "/absolute/path/to/run-001/replay.json"
}
```

`speed_multiplier` is serialized as a string so `0.5x`, `1x`, and `10x` round
trip without float formatting ambiguity.

## Slow Copy

Batch `materialize` keeps Sprint 6 behavior: `slow_copy_start` writes the full
temp file immediately, and `slow_copy_commit` promotes it.

Wall-clock `run` uses a separate slow-copy session:

- `slow_copy_start` opens or initializes the temp path and records source path,
  destination path, total bytes, start logical time, and commit logical time.
- While wall time advances, the runner grows the temp file toward the source
  bytes according to logical progress between start and commit.
- `slow_copy_commit` ensures the temp file contains the full source bytes, then
  performs the same atomic promotion as batch materialize.
- No `progressed` journal entries are emitted.

This design gives watchers a real partial file to observe without adding a new
logical journal surface.

File growth is driven by scheduler ticks before sleeps. Sprint 8 does not use a
background thread/task for slow-copy growth; that keeps interrupt and cleanup
semantics single-threaded.

## `add_file` Restoration

`add_file` means an already-declared asset reappears after disappearance.

Valid lifecycle:

```text
delete_file(asset_a) -> add_file(asset_a, to="new/path.mkv")
```

Invalid lifecycle remains:

```text
add_file(asset_a) while asset_a is already placed
move_asset(asset_a) -> add_file(asset_a)
rename_file(asset_a) -> add_file(asset_a)
archive_file(asset_a) -> add_file(asset_a)
move_between_roots(asset_a) -> add_file(asset_a)
```

Materialized behavior:

- `delete_file` captures the removed file's bytes and metadata in a run-local
  restoration cache before unlinking.
- `add_file` writes those same bytes to `event.to`.
- The restored file keeps the same asset identity.
- The engine's existing behavior allocates a new location and records
  `state_delta["added_path"]`.
- `add_file` does not allocate a new version by itself.

The restoration cache is in-memory and scoped to one `run` or `materialize`
execution. Replay from `replay.json` can reproduce the same bytes because phase
A synthesis is deterministic for the same scenario and resolved seed.

## Artifact Writes

The run directory is published immediately with an in-progress sentinel because
watchers need a real library tree during execution:

```text
run/
  .chaos-librarian-run        # state=in_progress until successful finalize
  library/
  journal.jsonl               # live append
```

Files written at finalization:

- `scenario.yaml`
- `manifest.initial.json`
- `manifest.current.json`
- `validation.json`
- `materialization.json`
- `replay.json`
- `reports/...`
- final `.chaos-librarian-run` with `state=complete`

`journal.jsonl` is the only required live oracle artifact. If finalization
fails after the journal has live entries, the sentinel must remain
`in_progress` so `inspect` and `clean` do not mistake the run for complete.

## Contract Changes

No scenario schema change.

No journal schema change. `wall_clock_time` already exists on journal entries
and remains omitted in plan-only output.

Replay bundle schema does not need a version bump because the existing
`MaterializeReplayBundle` already allows `execution_mode: "run"`. The run
replay bundle should use:

- `execution_mode: "run"`
- random materialized `run_id`
- `created_at`
- `toolchain`
- `applied_events` equal to the executed raw journal-entry count
- `journal_digest` over the executed logical journal bytes after omitting
  `wall_clock_time`

Materialization report should bump from v4 to v5 to add wall-clock run timing
fields:

```python
requested_duration_ns: int | None = None
actual_duration_ns: int | None = None
speed_multiplier: str | None = None
overran_duration: bool = False
execution_mode: MaterializationExecutionMode = MaterializationExecutionMode.MATERIALIZE
```

These fields are nullable/defaulted so batch `materialize` can keep using the
same report model. Add a local `MaterializationExecutionMode(enum.StrEnum)` in
`contract/materialization.py` with `MATERIALIZE = "materialize"` and
`RUN = "run"`, then regenerate `schemas/materialization.schema.json`.

## Replay

Wall-clock replay is outcome-oriented:

- Read a `ReplayBundle` whose `execution_mode` is `"run"`.
- Validate the embedded scenario.
- Recompute the logical plan with the recorded resolved seed.
- Verify `applied_events` and `journal_digest`.
- Materialize the final logical state as quickly as possible.
- Do not sleep according to original event times.
- Do not recreate partial slow-copy visibility.

This satisfies the Sprint 8 replay exit criterion without turning replay into
a second timed-run mode.

## Failure And Interrupt Semantics

Normal completion:

- All due events are executed.
- The process idles if the timeline drained before `--duration`.
- Final metadata is written.
- Sentinel flips to `complete`.

Deadline while handler is running:

- Finish the handler.
- Finalize after it completes.
- Set `overran_duration=true` when actual wall-clock runtime exceeds the
  requested duration.

Validation, capability, unsupported timeline, filesystem, and media failures:

- Reuse `materialize` exit-code mapping and structured error envelopes.
- For caught phase-B failures, preserve the existing cleanup behavior:
  failure metadata is written where supported, and the partial library is not
  silently trusted.

Interrupt or unhandled crash:

- Leave sentinel `state=in_progress`.
- Leave any live `journal.jsonl` entries already appended.
- Do not write `replay.json`, final manifests, reports, or a success report for
  a partial run.

## Active Library Churn Fixture

Add `tests/fixtures/scenarios/active-library-churn.yaml`.

It should run in 60 to 90 seconds at `1x`, and much faster under higher speeds
for development tests. It should include:

- timed move or rename
- slow copy with observable partial temp file
- sidecar create or update
- delete followed by `add_file` restoration
- one lightweight media mutation already supported by Sprint 7

The fixture should stay small enough for regular development. It should not
depend on long clips, public media downloads, or corrupt media profiles.

## Testing

Layer 1 - scheduler/unit tests:

- duration parsing uses the existing duration grammar
- speed parsing accepts `1x`, `10x`, and `0.5x`
- speed parsing rejects zero, negative, missing suffix, and garbage
- due-event calculation maps wall elapsed to logical time
- timeline-drained runs idle until duration
- in-flight event overrun finalizes after handler completion

Layer 2 - materializer tests:

- `delete_file` then `add_file` restores identical bytes at the new path
- `add_file` without prior disappearance remains rejected
- wall-clock slow copy grows temp bytes before commit
- slow copy emits only start and commit journal entries
- live journal append happens as entries execute

Layer 3 - CLI tests:

- `run --json` emits the stable summary
- validation failures exit 3
- missing/low tools exit 4
- unsupported actions exit 5
- filesystem safety violations exit 7
- interrupted run leaves sentinel `in_progress`

Layer 4 - integration tests:

- Active Library Churn runs end-to-end
- final journal matches plan/step logical journal after stripping
  `wall_clock_time`
- wall-clock replay reproduces final logical state without timing
- watcher-style test can observe a partial slow-copy temp file

Verification before merge:

```text
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
prek run --all-files
```

## Alternatives Rejected

### Repeated Step Advancement

Rejected because current step mode is plan-only, and step boundaries collapse
adjacent `slow_copy_start` / `slow_copy_commit` into one unit. That conflicts
with wall-clock partial-growth visibility.

### Separate Wall-Clock Engine

Rejected because it duplicates engine semantics and makes plan, step,
materialize, and run drift likely. Sprint 8's key contract is that wall-clock
journals remain logically identical to the planned journal.

### Replay With Original Timing

Rejected because watcher timing belongs to `run`. Replay should be a fast
forensic reproduction path for final state and logical artifacts.

## Open Decisions

None. The implementation plan may choose exact helper names, but the behavior
above is fixed for Sprint 8.
