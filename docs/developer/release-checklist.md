# Release Checklist

Before merging a documentation or contract-facing change:

- Re-read documentation and code changes for stale sprint-era language.
- Run targeted tests for touched areas.
- Run `uv run pytest tests/docs -q` when also running package tests, or
  `uv run pytest tests/docs -q --no-cov` for a docs-only local check.
- Run `uv run ruff check .`.
- Run `uv run ruff format --check .`.
- Run `uv run ty check src tests`.
- Run `uv run python -m chaos_librarian.schema_export --check`.
- Run `prek run --all-files`.
- Confirm no checked-in generated files are stale.
- Confirm `README.md` and `docs/README.md` link to new public docs.
