# Integration

Chaos Librarian emits neutral oracle artifacts. It does not know the consumer
application database schema, ingest policy, or watcher implementation.

Consumers export `observed-state.json` using the observed-state contract, then
pass that export to `compare`.

## Scanner and Prober Final-State Flow

Create or replay a fixture, let the application scan it, export observed state,
then compare final state:

```bash
uv run chaos-librarian compare run-dir observed-state.json --mode final-state --json
```

Use this mode for scanner and prober tests that only need the expected current
library state.

## Watcher Identity-History Flow

Run a step or wall-clock fixture while the application watches the filesystem,
export observed state with lifecycle evidence, then compare identity history:

```bash
uv run chaos-librarian compare run-dir observed-state.json --mode identity-history --json
```

Use this mode when durable identity across moves, renames, deletes, and restores
matters.

## Compare Exit Codes

- Exit `0` means the consumer output matches the oracle.
- Exit `6` means comparison completed and found divergence.
- Exit `1` means the adapter input is invalid or cannot be read.
- Exit `7` means the run directory failed sentinel or containment checks.
