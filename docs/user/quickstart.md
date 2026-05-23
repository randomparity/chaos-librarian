# Quick Start

## Plan-Only Fixture

```bash
uv sync
RUN_DIR="$(mktemp -d)/chaos-static-library"
uv run chaos-librarian validate tests/fixtures/scenarios/static-library.yaml --json
uv run chaos-librarian plan tests/fixtures/scenarios/static-library.yaml --out "$RUN_DIR" --json
uv run chaos-librarian inspect "$RUN_DIR" --json
```

Open `manifest.current.json` to see the expected final library state and
`journal.jsonl` to see the oracle event stream.

## Materialized Fixture

```bash
uv run chaos-librarian capabilities --json
MEDIA_RUN_DIR="$(mktemp -d)/chaos-materialized-static"
uv run chaos-librarian materialize tests/fixtures/scenarios/static-library.yaml --out "$MEDIA_RUN_DIR" --json
```

The `library/` directory contains generated media files. The manifest versions
include hashes and probed media facts when probing succeeds.

## Wall-Clock Fixture

```bash
CHURN_RUN_DIR="$(mktemp -d)/chaos-active-library-churn"
uv run chaos-librarian run tests/fixtures/scenarios/active-library-churn.yaml --out "$CHURN_RUN_DIR" --duration 30s --speed 10x --json
```

Use wall-clock mode when the application under test watches the filesystem over
time.

## Cleanup

```bash
uv run chaos-librarian clean "$RUN_DIR" --json
```

`clean` only removes directories protected by `.chaos-librarian-run`.
