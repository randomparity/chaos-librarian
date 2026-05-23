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
