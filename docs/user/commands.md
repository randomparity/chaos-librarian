# Commands

This page summarizes task-oriented CLI usage. The stable contract details and
exit-code meanings live in [the CLI reference](../contract/cli-reference.md).

## `validate SCENARIO [--json]`

Validate a scenario without writing a fixture:

```bash
uv run chaos-librarian validate scenario.yaml --json
```

Use `validate` while authoring YAML or when CI needs a fast contract check.

## `generate --profile PROFILE [--lane LANE] [--count N] --seed SEED --out OUT [--json]`

Generate deterministic fuzz scenario YAML:

```bash
uv run chaos-librarian generate \
  --profile fuzz-smoke \
  --seed 123 \
  --out fuzz-smoke.yaml \
  --json

uv run chaos-librarian generate \
  --profile fuzz-regression \
  --lane core-fs \
  --seed 456 \
  --out fuzz-regression-core-fs.yaml \
  --json
```

Use `generate` when a test needs bounded randomized coverage. The output is
ordinary scenario YAML with explicit timeline events and generation metadata.
`--lane` defaults to `smoke` for `fuzz-smoke`; `fuzz-regression` requires an
explicit lane such as `core-fs`.

Generate a batch into a directory with `--count N` (default `1`). With
`--count 1`, `--out` is a new file (as above). With `--count > 1`, `--out` must
be an existing directory and each scenario is written as `<scenario_id>.yaml`:

```bash
# 9 fuzz-regression scenarios, one per lane, seeds 42..50
uv run chaos-librarian generate --profile fuzz-regression --count 9 --seed 42 --out ./generated/

# 20 fuzz-smoke scenarios, seeds 42..61
uv run chaos-librarian generate --profile fuzz-smoke --count 20 --seed 42 --out ./generated/
```

Item `i` uses `seed + i`. For `fuzz-regression` without `--lane`, lanes cycle the
canonical order; with `--lane L`, all items use lane `L`. Output is deterministic
for a given `(profile, seed, count, lane)`. On any failure the batch removes the
files it wrote so the command can be re-run.

## `plan SCENARIO --out RUN_DIR [--steps N] [--json]`

Create an oracle fixture without media files:

```bash
uv run chaos-librarian plan scenario.yaml --out run-dir --json
uv run chaos-librarian plan scenario.yaml --out run-dir --steps 3 --json
```

`--steps N` applies the first N user-visible step units. Adjacent
`slow_copy_start` and `slow_copy_commit` events count as one step.

## `materialize SCENARIO --out RUN_DIR [--json]`

Create a fixture with real files under `library/`:

```bash
uv run chaos-librarian materialize scenario.yaml --out run-dir --json
```

Run `capabilities` first on machines that may not have ffmpeg, ffprobe, or
mkvmerge installed.

## `run SCENARIO --out RUN_DIR --duration DURATION [--speed MULTIPLIER] [--json]`

Create a materialized fixture and apply timeline changes over elapsed wall time:

```bash
uv run chaos-librarian run scenario.yaml --out run-dir --duration 90s --speed 10x --json
```

Use `run` when the application under test needs to observe filesystem churn
while it happens.

## `step RUN_DIR [--next N] [--json]`

Advance a plan-only fixture by one or more step units:

```bash
uv run chaos-librarian step run-dir --next 1 --json
```

`step` updates mutable oracle files and appends new journal entries.
Materialize and run directories are rejected with `E_STEP_UNSUPPORTED_MODE`
until materialized stepping is implemented.

## `replay BUNDLE --out RUN_DIR [--against ORIGINAL_RUN_DIR] [--json]`

Replay a recorded plan-only or wall-clock run bundle:

```bash
uv run chaos-librarian replay run-dir/replay.json --out replay-dir --json
uv run chaos-librarian replay run-dir/replay.json --out replay-dir --against run-dir --json
```

Use `--against` when checking that a replay matches an existing run directory.
Materialize-mode replay is not implemented in this CLI build.

## `inspect RUN_DIR [--json]`

Inspect a run directory and sentinel:

```bash
uv run chaos-librarian inspect run-dir --json
```

`inspect` reports run metadata and fixture state without mutating the run.

## `capabilities [--json]`

Check local external tool readiness:

```bash
uv run chaos-librarian capabilities --json
```

Read `ready_for.materialize_static`,
`ready_for.materialize_filesystem_mutations`, and
`ready_for.materialize_media_mutations` before enabling media-heavy jobs.

## `clean RUN_DIR [--json]`

Remove a protected run directory:

```bash
uv run chaos-librarian clean run-dir --json
```

`clean` requires `.chaos-librarian-run` so it cannot remove arbitrary
directories by accident.

## `compare RUN_DIR OBSERVED --mode final-state|identity-history [--json]`

Compare consumer-observed state to the neutral oracle:

```bash
uv run chaos-librarian compare run-dir observed-state.json --mode final-state --json
uv run chaos-librarian compare run-dir observed-state.json --mode identity-history --json
```

`final-state` checks the expected current state. `identity-history` also checks
path history or global observed events.

## Exit Codes

| code | meaning |
|------|---------|
| `0` | success |
| `1` | generic failure or adapter input error |
| `2` | usage error |
| `3` | scenario validation failed |
| `4` | required external tool missing or version too low |
| `5` | materialization failed |
| `6` | replay or compare diverged |
| `7` | filesystem safety violation, containment failure, or sentinel failure |
