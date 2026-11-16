# ty 0.0.104 migration (issue #259)

## Problem

Locking ty 0.0.104 (latest; operator decision) makes `uv run ty check src tests` report 23
diagnostics (14 errors, 9 warnings) that ty 0.0.37 did not. No ReplayBundle diagnostics appear.

## Scope

One unit. Fix each cause; ignore only where the code is deliberately ill-typed.

- `uv.lock`: ty entry only, regenerated with uv 0.11.14 (CI pin).
- `pyproject.toml`: rename rule `unresolved-import` to `import-not-found`.
- `topology.py`: `_Identified` declares a mutable `id: str`; the frozen models expose a
  read-only `id`. Declare `id` as a read-only property in the Protocol (11 errors).
- `contract/materialization.py:208`: `json_schema_extra` needs a `JsonValue`; pass
  `list(CORRUPTION_TIMELINE_ACTION_VALUES)`. A tuple and a list emit the same JSON array.
- `phase_b/media/handler.py`: ty now narrows `sidecar` on `kind`; drop the four redundant
  `cast` calls.
- `runtime/wall_clock.py:825`: annotate the `@contextmanager` as `Generator[None]`.
- `tests/validation/test_input.py:155,177`: deliberate frozen-model mutation; replace the
  unhonored `# type: ignore[misc]` with `# ty: ignore[invalid-assignment]` plus a reason.
- `tests/contract/test_materialization.py`: the `getattr` helper returns `type[BaseModel]`,
  so keyword arguments look discarded. `OracleHashAction` exists; import it and delete the
  helper (positive round-trip tests, not negative ones).
- `tests/determinism/test_trace.py:93`: rename the ignore code to `missing-attribute`.

Excluded: other #256 bumps (#256); click/ruff (#257, #258, merged); runtime and `schemas/`
changes. No ownership transition is needed.

### Failure model

1. Actors and deployments: a developer or CI job running the guardrails.
2. Invariants and assets: exported `schemas/` bytes; runtime behavior; the type gate's
   ability to catch real errors.
3. Accepted failure classes: a future ty release reintroducing diagnostics (bounded: the lock
   pins the version).
4. Covered elsewhere: schema drift, held by `schema_export --check`; behavior, held by pytest.

## Success

1. `uv run ty check src tests` exits 0 with ty 0.0.104 locked.
2. The ruff check, ruff format, pytest, and `schema_export --check` guardrails exit 0.
3. `git diff origin/main -- schemas/` is empty.
4. In `uv.lock`, only the ty package entry differs.

## Validation

- ty config, Protocol, `json_schema_extra`, casts, `Generator`, ignore comments:
  `focused-test` = `uv run ty check src tests`; red is the 23 diagnostics above; green exit 0.
- Schema bytes: `focused-test` = `uv run python -m chaos_librarian.schema_export --check`;
  red would be drift; green exit 0.
- Runtime behavior (casts removed, helper inlined): `focused-test` = pytest suite; the two
  oracle-hash round-trip tests still construct and round-trip `OracleHashAction`.
- Lock contents: `task-test-not-applicable`; no executable consumer checks lock diff shape;
  verified by reading `git diff -- uv.lock`.
