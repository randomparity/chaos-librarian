# Run Artifacts

Every run directory is intended to be self-contained and replayable. Files are
written under the selected output directory.

## Sentinel

`.chaos-librarian-run` marks the directory as a Chaos Librarian run. Commands
that mutate or remove run directories, including `clean`, require the sentinel
to prevent accidental operations on unrelated paths.

## Source and Replay

`scenario.yaml` is the stored source scenario used for the run.

`replay.json` records enough deterministic metadata to reproduce the run mode,
seed, applied events, and execution trace.
`replay` currently supports plan-only and wall-clock run bundles; materialize
mode records replay metadata but materialize-mode replay is not implemented in
this CLI build.

## Manifests

`manifest.initial.json` is the expected library state before timeline events.

`manifest.current.json` is the expected final or current library state after
the applied events for that run.

## Journal

`journal.jsonl` is the append-only oracle event stream. Each line is a JSON
journal entry with action, phase, logical time, and event identifiers.

## Reports

`validation.json` records validation outcome.

`materialization.json` exists for media-producing `materialize` and `run`
outputs.

The `reports/` tree contains per-entity projections:

- `reports/assets`
- `reports/works`
- `reports/variants`
- `reports/bundles`

These reports are useful when a consumer test wants one entity projection
instead of the whole manifest.

## Library Files

`library/` contains real files for `materialize` and `run` outputs. Plan-only
runs do not create media files.
