# Validation Pipeline

`prepare_run_input` reads scenario bytes, preserves the source path or label,
parses YAML, computes the scenario content hash, and returns a `RunInput`.
`RunInput` caches the parsed frozen `Scenario` after shape validation so later
pipeline stages operate on the same scenario bytes.

`run_validation` applies three layers:

1. Top-level input guard for YAML parse and document shape failures.
2. Pydantic shape validation that maps field errors to stable `E_*` codes.
3. Semantic validation rules over the parsed scenario.

Shape validation maps Pydantic errors to stable codes such as
`E_FIELD_MISSING`, `E_FIELD_UNKNOWN`, `E_FIELD_LITERAL`, and `E_FIELD_TYPE`.
Stable issue ordering keeps reports deterministic.

Semantic validation rules live under `validation/rules/`. New rules should be
small modules with focused tests under `tests/validation/rules/`; keep shared
helpers in focused sibling modules such as
`validation/rules/core/raw_helpers.py`,
`validation/rules/hierarchy/walkers.py`,
`validation/rules/hierarchy/projection.py`,
`validation/rules/hierarchy/rendering_projection.py`, and
`validation/rules/sidecar/projection.py` only when multiple rules use them.

Invalid fixtures under `tests/fixtures/scenarios/invalid/` must start with:

```text
# expected: E_<CODE>
```

`tests/validation/test_invalid_corpus.py` reads that marker and asserts the
validation report carries the same code.

Lifecycle checks reject event ordering that the engine cannot execute, such as
`add_file` on a placed asset, operations after delete, unpaired slow-copy
events, double slow-copy starts, and mutations while a slow copy is active.
