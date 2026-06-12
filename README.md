# Chaos Librarian

Scenario-driven synthetic media library simulator for testing scanners,
watchers, media probes, durable identity, bundle tracking, and reconciliation.

Chaos Librarian creates deterministic media-library fixtures from YAML
scenarios. It can stop at an oracle-only plan, materialize real media files,
advance mutations step by step, run wall-clock churn for daemons, and compare a
consumer export back to the neutral oracle it produced.

## Features

- Deterministic oracle fixtures: scenario YAML becomes manifests, a JSONL
  journal, replay metadata, and per-entity reports.
- Plan-only mode: validate scenario behavior without creating media files.
- Real media materialization: synthesize media with ffmpeg and probe it with
  ffprobe.
- Controlled mutation timelines: moves, renames, deletes, slow copies,
  sidecars, re-encodes, remuxes, metadata edits, subtitle operations, and
  malformed-media corruption.
- Step and wall-clock execution: choose exact assertion points for tests or
  timed churn for daemon/watch workflows.
- Consumer-neutral comparison: export observed state from an application and
  compare it with `chaos-librarian compare`.
- Schema-first contracts: checked-in JSON Schema artifacts under `schemas/`
  define the public contract.

## Requirements

- Python 3.13 or newer.
- `uv` for dependency management and local command execution.
- For plan-only workflows: no media tools are required.
- For materialize and run workflows: ffmpeg 7.0+, ffprobe 7.0+, and, for media
  mutation readiness, mkvmerge from MKVToolNix 80+.

Check local media-tool readiness:

```bash
uv run chaos-librarian capabilities --json
```

## Quick Start

```bash
uv sync

RUN_DIR="$(mktemp -d)/chaos-static-library"

uv run chaos-librarian validate tests/fixtures/scenarios/static-library.yaml --json
uv run chaos-librarian plan tests/fixtures/scenarios/static-library.yaml --out "$RUN_DIR" --json
uv run chaos-librarian inspect "$RUN_DIR" --json
```

The plan command writes a self-contained fixture directory with
`scenario.yaml`, `manifest.initial.json`, `manifest.current.json`,
`journal.jsonl`, `replay.json`, `validation.json`, per-entity reports, and the
`.chaos-librarian-run` sentinel.

## Common Workflows

| Need | Command |
|------|---------|
| Validate a scenario | `uv run chaos-librarian validate scenario.yaml --json` |
| Plan without media files | `uv run chaos-librarian plan scenario.yaml --out run-dir --json` |
| Create real media | `uv run chaos-librarian materialize scenario.yaml --out run-dir --json` |
| Run wall-clock churn | `uv run chaos-librarian run scenario.yaml --out run-dir --duration 90s --speed 10x --json` |
| Advance a step fixture | `uv run chaos-librarian step run-dir --next 1 --json` |
| Replay a recorded run | `uv run chaos-librarian replay run-dir/replay.json --out replay-dir --json` |
| Inspect a run directory | `uv run chaos-librarian inspect run-dir --json` |
| Compare consumer output | `uv run chaos-librarian compare run-dir observed-state.json --mode final-state --json` |
| Remove a run directory | `uv run chaos-librarian clean run-dir --json` |
| Visualize a run over time | `uv run python scripts/visualize_run.py run-dir` (writes a self-contained `visualize.html`) |

## Documentation

- [Documentation index](docs/README.md)
- [Installation](docs/user/installation.md)
- [Quick start](docs/user/quickstart.md)
- [Scenario authoring](docs/user/scenario-authoring.md)
- [CLI commands](docs/user/commands.md)
- [Run artifacts](docs/user/run-artifacts.md)
- [Integration guide](docs/user/integration.md)
- [Developer architecture](docs/developer/architecture.md)
- [Contract reference](docs/contract/schema-reference.md)

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Pydantic models in `src/chaos_librarian/contract/` are the schema source of
truth. After editing a contract model, regenerate checked-in schemas with:

```bash
uv run python -m chaos_librarian.schema_export --write
```
