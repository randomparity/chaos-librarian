# Issue 88 Slow Copy Idle Growth Design

## Goal

Wall-clock slow-copy temp files must visibly grow during the idle interval
between `slow_copy_start` and `slow_copy_commit`, so consumers polling the
library tree can observe progressive copy growth before the final promote.

## Root Cause

`wall_clock._run_timed_phase()` grows active slow copies once at the top of each
scheduler loop. When no journal event is due, it sleeps until the next event or
the run deadline. For a slow copy, the next event is often the commit, so the
temp file stays at the start size throughout the idle sleep and jumps directly
to the completed file at commit.

## Options

1. Add a fixed internal slow-copy poll tick while active slow copies exist. This
   keeps the current scheduler shape and updates temp-file sizes during idle
   waits without adding configuration.
2. Spawn a background updater thread per active copy. This would mimic real
   asynchronous copy behavior, but adds concurrency and cleanup risk.
3. Increase writes in `_wall_clock_slow_copy_start()` only. This can create one
   partial file but cannot show progressive growth across later scans.

Option 1 is the design choice.

## Design

Add an internal constant in `materializer.wall_clock`, for example
`_SLOW_COPY_POLL_INTERVAL_NS = 1_000_000_000`, representing a one-second wall
clock tick.

In `_run_timed_phase()`, when `due_count == 0`, compute the existing next wake
time, then cap it to `now_ns + _SLOW_COPY_POLL_INTERVAL_NS` while
`state.slow_copies` is non-empty. The next loop iteration already calls
`_grow_active_slow_copies()` before deciding whether an event is due, so the
temp file advances on each tick.

The cap must never move wake time past the next event or run deadline. Existing
speed handling remains unchanged because `_grow_active_slow_copies()` receives
the logical time derived from elapsed wall time and the configured speed.

## Tests

Add a wall-clock regression test using `slow-copy-materialize.yaml` with the
fake clock and fake static materializer. Spy on `_grow_active_slow_copies()`,
record temp-file sizes while the run progresses through a full slow copy, and
assert that at least two distinct partial sizes are observed before commit.

Run focused wall-clock tests, then ruff, ty, schema drift, and a real
`slow-copy-materialize` polling repro before opening the PR.
