# Architecture

Chaos Librarian is organized around a schema-first fixture pipeline. The public
contract models live at the edge; validation, deterministic planning,
materialization, and adapter comparison consume those models.

## Module Map

- `contract/`: Pydantic source of truth for public schemas, including scenario,
  manifest, journal, replay bundle, reports, capabilities, observed state, and
  divergence contracts.
- `validation/`: YAML input preparation, shape validation, semantic rules, and
  stable validation reports. `validation/scenario_io.py` owns YAML parsing and
  line/column indexing for validation and CLI error reporting.
- `determinism/`: seed resolution, RNG streams, clock helpers, ID allocation,
  and execution trace recording.
- `generation/`: deterministic fuzz scenario generation, lane coverage
  vocabulary, and profile/lane-specific payload planning.
- `engine/`: plan-only timeline resolution, event handling, journal generation,
  reports, replay verification, step mode, and fixture writing.
- `materializer/`: capability gate, content sources, ffmpeg synthesis, phase-B
  filesystem/media/corruption effects, persistence, and wall-clock runner.
- `adapter/`: fixture loader, observed-state loader, matching, comparison, and
  divergence report construction.
- `cli/`: Typer app and command modules.

## Shared Root Utilities

The package root contains shared utilities that are intentionally outside the
major workflow packages because they are consumed across several of them:

- `clock.py`: duration parsing and time conversions used by validation,
  planning, materialization, and scheduling.
- `errors.py`: project-owned base exception types for domain errors that cross
  package boundaries.
- `media_matrix.py`: supported media codec/container matrix shared by validation,
  capability gates, generation, and materializer tooling.
- `path_rendering.py`: deterministic library-path rendering for typed topology
  contexts and validation projections.
- `topology.py`: typed manifest/scenario traversal helpers used by engine,
  materializer, adapter, and tests.
- `schema_export.py`: developer/CI schema export entrypoint; it reads contract
  models and writes checked-in JSON Schema artifacts.

## Data Flow

```text
scenario.yaml
  -> prepare_run_input
  -> run_validation
  -> resolve_timeline
  -> run_plan or materialize_scenario or run_wall_clock_scenario
  -> fixture directory
  -> compare against observed-state.json
```

Plan mode stops after oracle artifacts are written. Materialize mode uses the
same validation and plan semantics, then writes media files and applies effects.
Run mode applies the same logical timeline over elapsed wall-clock time for
watcher workflows.

Replay mode starts from `replay.json`, prepares the embedded scenario with
`prepare_replay_input_from_bytes`, and then passes the prepared input to the
plan-only or materialize replay verifier.
