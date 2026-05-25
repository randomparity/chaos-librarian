# CLI Reference

```text
chaos-librarian validate scenario.yaml --json
chaos-librarian generate --profile fuzz-smoke --seed 123 --out scenario.yaml --json
chaos-librarian plan scenario.yaml --out fixtures/run-001 --steps 3 --json
chaos-librarian materialize scenario.yaml --out fixtures/run-001 --json
chaos-librarian run scenario.yaml --out fixtures/run-001 --duration 90s --speed 10x --json
chaos-librarian step fixtures/run-001 --next 1 --json
chaos-librarian replay fixtures/run-001/replay.json --out fixtures/replay-001 --json
chaos-librarian inspect fixtures/run-001 --json
chaos-librarian capabilities --json
chaos-librarian clean fixtures/run-001 --json
chaos-librarian compare fixtures/run-001 observed-state.json --mode final-state --json
```

All commands support `--json`. Exit codes:

| code | meaning                                                       |
|------|---------------------------------------------------------------|
| `0`  | success                                                       |
| `1`  | generic failure or adapter input error                        |
| `2`  | usage error                                                   |
| `3`  | scenario validation failed                                    |
| `4`  | required external tool missing or version too low             |
| `5`  | materialization failed                                        |
| `6`  | replay or compare diverged                                    |
| `7`  | filesystem safety violation (containment or sentinel)         |

## Commands

`validate` checks a scenario and exits `3` when YAML, shape, or semantic
validation fails.

`generate` writes deterministic fuzz scenario YAML. `--profile` accepts
`fuzz-smoke` or `fuzz-regression`; `--seed` must be a non-negative integer.
`--out` must point to a new file whose parent directory already exists.

`plan` writes an oracle-only fixture. `--steps N` applies a prefix of
user-visible step units.

`materialize` writes real media files under `library/` and records
`materialization.json`.

`run` is the wall-clock materialization command; it applies the same logical
timeline as step mode over elapsed wall-clock time.

`run --duration` sets the wall-clock run length. `run --speed` scales logical
time, defaults to `1x`, and accepts multiplier values such as `10x`.

`step` advances a plan-only fixture by `--next N` user-visible step units.
Materialize and run directories are rejected with `E_STEP_UNSUPPORTED_MODE`
until materialized stepping is implemented.

`replay` reproduces a recorded plan or run replay bundle. `--against` compares
the replayed output with an existing original run directory.

`inspect` reports fixture metadata and sentinel state without mutating the run.

`capabilities` reports local ffmpeg, ffprobe, mkvmerge, and readiness status.

`clean` removes a run directory only when the sentinel validates.

`compare` validates a consumer `observed-state.json` export and emits a
`divergence.schema.json` report. It exits `6` when comparison completes and
finds differences.

See [`chaos-librarian-design.md` "CLI Contract"](../specs/chaos-librarian-design.md)
for the historical design context.
