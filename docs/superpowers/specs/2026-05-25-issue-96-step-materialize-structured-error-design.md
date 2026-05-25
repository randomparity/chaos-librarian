# Issue 96 Step Materialize Structured Error Design

## Goal

`chaos-librarian step <run-dir> --json` must never emit an unhandled Python
traceback for a valid Chaos Librarian run directory. This cycle implements the
accepted fallback behavior from issue #96: materialize and run replay bundles
are rejected with a structured CLI envelope and a documented exit code.

## Context

`step_fixture()` is a plan-only engine. It reads `replay.json` as
`PlanOnlyReplayBundle` and recomputes deterministic plan state from the embedded
scenario and existing journal. Materialize replay bundles are a different
contract branch: they include volatile toolchain fields, content-source
evidence, and `execution_mode: materialize` or `run`. Feeding those bundles into
the plan-only parser currently raises a Pydantic traceback.

Supporting real materialized stepping would require applying the next phase-B
mutation to the on-disk library, updating `manifest.current.json`,
`materialization.json`, `journal.jsonl`, `reports/`, and replay metadata while
preserving cleanup behavior for failed media/filesystem actions. That is a
separate feature-sized change and is not required to satisfy the structured
error acceptance criteria.

## Decision

Add a CLI preflight in `step` after the existing sentinel/state check and
before calling `step_fixture()`:

1. Parse `<run-dir>/replay.json` through the existing replay-bundle union
   adapter.
2. If parsing fails, emit `E_REPLAY_BUNDLE_INVALID` with exit code `1`.
3. If the parsed bundle is not `PlanOnlyReplayBundle`, emit
   `E_STEP_UNSUPPORTED_MODE` with exit code `1`.
4. If it is plan-only, continue through the existing sentinel checks and
   `step_fixture()` flow.

This keeps the engine boundary unchanged: `step_fixture()` remains explicitly
plan-only, and the CLI owns user-facing mode rejection.

## Error Contract

JSON mode writes the shared CLI error envelope to stderr:

```json
{
  "error_code": "E_STEP_UNSUPPORTED_MODE",
  "message": "step supports plan_only replay bundles only; got materialize",
  "details": {
    "execution_mode": "materialize",
    "supported_execution_mode": "plan_only"
  }
}
```

Exit code is `1`, matching the CLI reference row for unsupported command
operation and existing `E_JOURNAL_CORRUPT` step failures. Human mode uses the
same envelope renderer.

## Tests

- CLI regression: materialize `reencode-video.yaml`, run `step --json`, assert
  exit code `1`, no traceback, `stderr.error_code == E_STEP_UNSUPPORTED_MODE`,
  and structured details name `materialize`.
- CLI invalid replay regression: corrupt `replay.json` in a run dir, run
  `step --json`, assert `E_REPLAY_BUNDLE_INVALID` instead of a traceback.
- Existing plan-only step tests remain unchanged and prove the preflight does
  not alter supported plan-only stepping.

## Docs

Update CLI/user docs to state that `step` currently supports plan-only fixtures
only. Materialize/run dirs fail with `E_STEP_UNSUPPORTED_MODE` until a future
materialized stepping feature lands.
