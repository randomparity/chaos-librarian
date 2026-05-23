# Time Model

Time is tracked as a 64-bit signed integer of nanoseconds since scenario start
(`t=0`). All durations and timestamps share this representation across step
mode and wall-clock mode.

Duration strings:

| string  | meaning           |
|---------|-------------------|
| `500ms` | 500 milliseconds  |
| `2s`    | 2 seconds         |
| `1m30s` | 90 seconds        |
| `0`     | t=0 (start)       |

Timeline event `at:` values are offsets from scenario start, not from the
previous event. Events with the same `at:` value are applied in declared
order.

Journal entries record both `logical_time_ns` (integer) and, in wall-clock
and materialize modes, `wall_clock_time` (RFC 3339). Plan-only journals omit
`wall_clock_time`.

See [`chaos-librarian-design.md` "Time Model"](../specs/chaos-librarian-design.md).

## Profile Timing

Network lag profiles use the existing duration grammar. Lag windows use the
same logical clock as timeline events.

Lag windows are scaled by the `run --speed` multiplier in wall-clock mode. If
`run --duration` expires inside a lag window, the runner continues through the
paired commit and records `overran_duration=true`.
