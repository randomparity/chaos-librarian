# Architecture

Chaos Librarian is organized around a schema-first fixture pipeline. The public
contract models live at the edge; validation, deterministic planning,
materialization, and adapter comparison consume those models.

## Module Map

- `contract/`: Pydantic source of truth for public schemas, including scenario,
  manifest, journal, replay bundle, reports, capabilities, observed state, and
  divergence contracts.
- `validation/`: YAML input preparation, shape validation, semantic rules, and
  stable validation reports.
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
