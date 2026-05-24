# Testing

Use targeted commands while developing, then run the broader checks before
committing.

```bash
uv run pytest
uv run pytest tests/cli/test_plan.py -q --no-cov
uv run pytest tests/validation/rules/test_timeline_lifecycle.py -q --no-cov
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
prek run --all-files
```

The test tree mirrors `src/chaos_librarian/` where practical. Contract tests
cover Pydantic models and schema export. Validation tests cover shape and
semantic errors. CLI tests protect command behavior and exit codes. Materializer
tests cover command builders, content sources, persistence, and real-tool paths.

The repository enables a global coverage gate in pytest addopts. Use `--no-cov`
for subset checks whose purpose is fast behavioral feedback; use the full
`uv run pytest` suite before merging when coverage should be enforced.

Real-tool integration tests may skip when required media tools are not
available. Skipped tests must remain visible in pytest output; do not hide skips
or report a skipped integration path as passing coverage.

Docs-only smoke tests live under `tests/docs/`. Run them with `--no-cov` when
you are not also executing the full package test suite:

```bash
uv run pytest tests/docs -q --no-cov
```

## Performance Profile Testing

`docs/specs/chaos-librarian-design.md` is the source of truth for the
Performance Profile Policy: reserved labels, fixture budgets, capability skip
rules, and CI tiers. Changes that add or alter performance profiles must update
that policy and keep the docs tests green.

Performance profile tests must leave missing capabilities visible as pytest
skips. Disk capacity is not a skip reason after a CI tier opts into a profile;
the job should fail during setup with a clear message when the runner cannot
meet the profile's free-disk precondition.

## Network Filesystem Lag Profile Testing

`docs/specs/chaos-librarian-design.md` is the source of truth for the network
filesystem lag profile policy. Tests for this profile should assert path-state
windows, not low-level OS watcher notification ordering.

Lag profile tests should prove that `materialize` rejects lag events as
unsupported and that `run` records the delayed visibility, delayed rename, or
held-handle evidence needed by consumers. Held-handle tests may assert blocking
behavior only when provider evidence says the behavior is enforced on the host.

## Fuzz Profile Generation Testing

`docs/specs/chaos-librarian-design.md` is the source of truth for the Fuzz
Profile Generation Policy: profile labels, static budgets, generation metadata,
and replay guarantees.

Generator tests must prove byte-identical output for the same profile and seed,
different YAML for different seeds, and schema-valid generated scenarios. Replay
tests should assert that replay uses the serialized scenario from `replay.json`;
it must not call the generator.
