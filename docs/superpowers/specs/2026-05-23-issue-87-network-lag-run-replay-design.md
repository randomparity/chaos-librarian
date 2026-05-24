# Issue 87 Network Lag Run Replay Design

## Goal

Wall-clock `run` bundles that include `network_lag_start` /
`network_lag_commit` entries must replay successfully through
`chaos-librarian replay` and produce a completed run-mode fixture.

## Root Cause

`run_wall_clock_scenario()` calls `preflight_timeline(..., allow_network_lag=True)`,
but `materializer.replay._materialize_verified_run_prefix()` calls
`preflight_timeline(scenario)` with the default `allow_network_lag=False`.
Replay rejects the same scenario that `run` accepted.

If replay only changes preflight, phase-B dispatch then reaches
`network_lag_start` and fails because ordinary phase-B dispatch does not support
network-lag audit entries. Run replay needs to consume the audit entries and
write matching materialization evidence.

## Options

1. Teach run replay to allow network-lag preflight and handle lag entries in
   its prefix phase-B loop. This keeps replay fast and final-state focused while
   preserving `network_lag_actions` evidence.
2. Reuse the wall-clock dispatcher directly. This duplicates timing behavior
   but makes run replay slow and couples replay to sleeps and deadlines.
3. Reject network-lag bundles earlier with a documented non-replayable error.
   This preserves current behavior, but contradicts the run-mode replay surface.

Option 1 is the design choice.

## Design

Run replay will call `preflight_timeline(scenario, allow_network_lag=True)`.

`PhaseBState` will gain `network_lag_actions: list[NetworkLagAction]` so replay
can carry network-lag audit evidence through both success and failure metadata.

`materializer.replay._apply_prefix_phase_b()` will handle three classes of
journal entries:

- `network_lag_start`: remember the started entry by event id and do not pass it
  to ordinary phase-B dispatch.
- `network_lag_commit`: find the matching start entry, append a
  `NetworkLagAction`, and do not pass the commit entry to ordinary phase-B
  dispatch.
- Any other action: dispatch through the existing phase-B dispatcher.

Run replay does not need wall-clock sleeps. It applies the wrapped filesystem
action at its journal position, then records lag evidence at commit. The final
library state matches the source run, and the evidence uses the same logical
fields as wall-clock mode: effect, target, after event id, logical start/commit,
requested duration, from/to paths, provider, and enforced flag.

The replay-generated `actual_duration_ns` will be `None` because no wall-clock
duration is enforced during fast replay.

`compare_run_replay()` will include `network_lag_actions` in normalized
`materialization.json` comparisons, dropping `actual_duration_ns` so a source
wall-clock run and fast replay can differ in elapsed wall time without masking
logical evidence drift.

## Tests

Add a materializer replay regression test with a small `network-fs-lag` scenario:
`rename_file`, `network_lag_start`, and `network_lag_commit`. Build a run replay
bundle for all three events, replay it with the fake materializer, and assert:

- The final renamed file exists.
- `materialization_report.network_lag_actions` contains the delayed-rename
  evidence.
- `materialization.json` serializes the network-lag evidence.
- `compare_run_replay()` detects network-lag evidence differences and ignores
  only `actual_duration_ns` drift.

Run the focused replay and preflight tests, then ruff, ty, and schema drift
checks before opening the PR.
