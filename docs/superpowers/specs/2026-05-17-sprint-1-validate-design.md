# Sprint 1 — Scenario Parser and `validate` Command

Status: design accepted, implementation plan pending.
Branch: `feat/sprint-1`.
Related: [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md) §"Sprint 1".

## Purpose

Sprint 1 turns the `chaos-librarian validate` stub into a real command. The goal
is a complete static-validation surface for scenario YAML files: load with
line-aware errors, structurally validate via Pydantic, run cross-cutting
semantic checks, and emit a `ValidationReport` matching
`schemas/validation.schema.json`. The command writes nothing to disk; it
exists to give scenario authors and downstream sprints a fast, comprehensive
"is this scenario well-formed?" check.

## Scope

### In Sprint 1

- YAML loader with per-node line/column tracking
- Duration-string parser (`"500ms"`, `"2s"`, `"1m30s"`, `"0"` → `i64` ns)
- Pydantic shape validation, with `pydantic.ValidationError` mapped to
  `ValidationIssue`s carrying precise line/column/JSONPath
- Semantic validation pass: cross-references, duplicate IDs, slow-copy
  pairing, path containment, timeline ordering, duration semantics
- `validate scenario.yaml [--json]` wired to the pipeline; exit `0` on success,
  exit `3` on any error-severity issue
- Malformed-scenario fixture corpus and parameterized tests
- Targeted docs reconciliation (Sprint 1/Sprint 2 reshuffle in the design doc;
  CLI reference; CLAUDE.md project-state line)

### Out of Sprint 1 (deferred)

- Writing run-directory artifacts (manifest, journal, replay bundle) —
  Sprint 3 (`plan`)
- Symlink resolution against a real library root — `plan`/`materialize` only
- Capabilities detection — Sprint 5
- Logical clock, RNG, ID allocator — Sprint 2
- Duration *formatters* (`format_duration_human`, `format_duration_json`) —
  Sprint 2 (paired with the logical clock)
- Configurable strictness flags (`--strict`, severity tuning) — none in V1

### Cross-sprint reshuffle

The duration parser, originally scoped to Sprint 2, moves into Sprint 1
because `validate` needs full `at:` and `duration:` semantic validation
to meet its exit criteria. Sprint 2 retains RNG + ID allocator + logical
clock + duration formatters. This is reflected in the docs reconciliation
list below.

## Architecture

```text
src/chaos_librarian/
  scenario_io.py            # YAML round-trip loader + LineIndex
  clock.py                  # parse_duration()
  validation/
    __init__.py             # public: run_validation(scenario_path) -> ValidationReport
    pipeline.py             # orchestrator + IssueCollector
    shape.py                # Pydantic pass; ValidationError -> ValidationIssue
    semantic.py             # cross-cutting rules
    codes.py                # stable error-code constants and Pydantic->code map
```

Each module is independently testable. The pipeline holds a single
`IssueCollector`; passes are functions that append to it.

## Component Contracts

### `scenario_io.py`

```python
class ScenarioLoadError(Exception): ...

@dataclass(frozen=True)
class LineIndex:
    def lookup(self, loc: tuple[str | int, ...]) -> tuple[int, int] | None: ...

def load_scenario(path: Path) -> tuple[dict, LineIndex]: ...
```

- Uses `ruamel.yaml.YAML(typ="rt")` for line-tracking
- Walks the parsed `CommentedMap`/`CommentedSeq` tree once, flattening positions
  into a `LineIndex` keyed by path tuples (e.g., `("timeline", 3, "target")`)
- Line numbers are 1-based (editor convention) even though ruamel reports 0-based
- Returns a plain `dict` + `LineIndex`; downstream passes never touch ruamel types
- On `YAMLError`, raises `ScenarioLoadError` carrying line/col so the caller
  can emit a single `E_YAML_PARSE` issue

### `clock.py`

```python
class DurationParseError(ValueError):
    raw: str
    reason: str

def parse_duration(raw: str) -> int: ...  # returns nanoseconds
```

Grammar (matches design spec §"Time Model"):

- `"0"` → `0`
- Otherwise: `<int><unit>` segments, units strictly descending, no spaces
- Units: `h`, `m`, `s`, `ms`, `us`, `ns`
- Rejects: empty, negative, fractional, unknown unit, duplicate unit,
  units out of order, sums that overflow `i64` ns

One anchored regex with optional groups; bare `"0"` short-circuits. After
matching, at least one captured group must be non-`None`.

### `validation/pipeline.py`

```python
def run_validation(scenario_path: Path) -> ValidationReport: ...

class IssueCollector:
    def add(
        self,
        code: str,
        severity: ValidationSeverity,
        message: str,
        loc: tuple[str | int, ...],
        line_index: LineIndex,
    ) -> None: ...
```

Flow:

1. `load_scenario(path)`; on `ScenarioLoadError`, emit one `E_YAML_PARSE` issue,
   set `ok=False`, return early.
2. `run_shape_pass(raw, line_index, collector)` — emits zero or more issues;
   returns `Scenario | None`.
3. `run_semantic_pass(raw, line_index, collector)` — runs unconditionally, even
   if step 2 produced issues. Each rule guards its own preconditions and skips
   silently when the sub-tree it needs is malformed (Pydantic already flagged
   the structural issue).
4. Assemble `ValidationReport`:
   - `scenario_id`: `raw_data["scenario_id"]` if it's a string, else `"<unknown>"`
   - `ok`: `True` iff zero `severity=ERROR` issues
   - `issues`: collector's list sorted by `(line or 0, column or 0, code)` for
     stable output

Exit codes are the CLI's responsibility:

- `report.ok` → exit `0`
- `not report.ok` → exit `3`

Path-containment violations during `validate` are ERROR issues, not exit-`7`
events. Exit `7` is reserved for runtime fs-safety violations during
`plan`/`materialize`/`run`/`replay`. `validate` writes nothing and therefore
cannot trigger exit `7`.

### `validation/shape.py`

```python
def run_shape_pass(
    raw_data: dict,
    line_index: LineIndex,
    collector: IssueCollector,
) -> Scenario | None: ...
```

On `pydantic.ValidationError`, for each entry of
`e.errors(include_url=False, include_context=True)`:

- Map `error["type"]` → stable code via `codes.PYDANTIC_TO_CODE`. Unmapped
  types fall through to `E_FIELD_SHAPE` with the original `type` included
  in the message (lets us discover gaps without breaking the public code set).
- Format `error["loc"]` as a JSONPath via `codes.format_jsonpath`. Strip
  discriminator-tag segments from the loc (Pydantic inserts the resolved
  `action:` value for union errors, e.g., `"slow_copy_commit"`, which is not
  a YAML key).
- Resolve line/column via `LineIndex.lookup(loc)`. If exact lookup misses,
  walk up the tuple (strip last segment, retry) until a hit; whole-file
  fallback is `(1, 0)`.

### `validation/semantic.py`

```python
def run_semantic_pass(
    raw_data: dict,
    line_index: LineIndex,
    collector: IssueCollector,
) -> None: ...
```

Rules (run in this fixed order):

| # | Code                        | Rule                                                                                                                                                |
|---|-----------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------|
| 1 | `E_ID_DUPLICATE`            | No duplicate IDs within a scope. Scopes: timeline events; library roots; works; variants under a work; bundles under a variant; assets under a bundle |
| 2 | `E_PATH_DUPLICATE`          | No two `library.roots` share the same `path`                                                                                                        |
| 3 | `E_DURATION_SYNTAX`         | Every `timeline[*].at` and `slow_copy_start.duration` parses via `clock.parse_duration`                                                              |
| 4 | `E_TARGET_UNKNOWN`          | Every `timeline[*].target` resolves to an `asset.id` defined in `works[*].variants[*].bundle.assets[*]`                                              |
| 5 | `E_SLOW_COPY_UNPAIRED`      | Every `slow_copy_commit.for` references an existing `slow_copy_start.id`; every start has exactly one matching commit; `at_commit > at_start`        |
| 6 | `E_PATH_CONTAINMENT`        | Every `library.roots[*].path`, `to:`, `temp_path:` passes `paths.resolve_under_library` against a synthetic library root                             |
| 7 | `E_TIMELINE_ORDER`          | Timeline `at:` values are non-decreasing (ties allowed; same-`at` events apply in declared order)                                                    |

Rule 6 uses a synthetic absolute library root (e.g.,
`Path("/__chaos_librarian_validate__/library")`) because no run directory
exists during `validate`. The containment helper's structural checks
(absolute-path rejection, `..` escape, empty-path rejection) do not depend
on the root existing. Symlink-target resolution is intentionally a no-op
during `validate`; runtime symlink validation belongs to `plan`/`materialize`.

Rule structure (template):

```python
def rule_duration_syntax(raw, line_index, collector) -> None:
    timeline = raw.get("timeline")
    if not isinstance(timeline, list):
        return
    for idx, event in enumerate(timeline):
        if not isinstance(event, dict):
            continue
        at = event.get("at")
        if not isinstance(at, str):
            continue
        try:
            parse_duration(at)
        except DurationParseError as e:
            collector.add(
                code="E_DURATION_SYNTAX",
                severity=ValidationSeverity.ERROR,
                message=f"invalid duration {at!r}: {e.reason}",
                loc=("timeline", idx, "at"),
                line_index=line_index,
            )
```

Every rule has the same shape: guard preconditions (Pydantic owns the
"the field exists and is the right type" issue), then check semantics.

### `validation/codes.py`

- `PYDANTIC_TO_CODE: dict[str, str]` — closed mapping from Pydantic error
  `type` strings to chaos-librarian error codes
- `format_jsonpath(loc) -> str` — `('timeline', 3, 'target')` →
  `'$.timeline[3].target'`; discriminator tags stripped
- Constants for every `E_*` code referenced above

### CLI wiring (`cli/app.py`)

Replace the `_stub("validate")` body:

```python
@app.command()
def validate(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Validate a scenario file."""
    report = run_validation(scenario)
    if json_output:
        typer.echo(report.model_dump_json(by_alias=True, exclude_none=True))
    else:
        _render_human(report)
    if not report.ok:
        raise typer.Exit(code=3)
```

`_render_human` lives in `cli/app.py` (private helper). Format:

```text
scenario: identity-move-rename
status: FAIL (3 issues)

ERROR  E_DURATION_SYNTAX    timeline[3].at        line 42:14   invalid duration '2 s': unexpected space
ERROR  E_TARGET_UNKNOWN     timeline[5].target    line 47:14   target 'asset_4k_main' not defined
WARN   E_PATH_DUPLICATE     library.roots[1].path line 12:11   root path 'movies-hd' already used by roots[0]
```

Tab-aligned columns. Severity colorized only when `sys.stdout.isatty()`.
JSON output is the stable contract; human format may change.

## Error Code Reference (Sprint 1 set)

| Code                       | Severity | Source pass | Description                                            |
|----------------------------|----------|-------------|--------------------------------------------------------|
| `E_YAML_PARSE`             | ERROR    | loader      | YAML failed to parse                                   |
| `E_FIELD_MISSING`          | ERROR    | shape       | Required field absent                                  |
| `E_FIELD_UNKNOWN`          | ERROR    | shape       | Unknown field (`extra="forbid"`)                       |
| `E_FIELD_LITERAL`          | ERROR    | shape       | Value outside `Literal[...]` choices                   |
| `E_FIELD_TYPE`             | ERROR    | shape       | Wrong type (str expected, int got, etc.)               |
| `E_FIELD_SHAPE`            | ERROR    | shape       | Catch-all for unmapped Pydantic error types            |
| `E_TIMELINE_ACTION_UNKNOWN`| ERROR    | shape       | `action:` value doesn't match any discriminated variant |
| `E_DURATION_SYNTAX`        | ERROR    | semantic    | Duration string failed to parse                        |
| `E_ID_DUPLICATE`           | ERROR    | semantic    | Duplicate ID within a scope                            |
| `E_TARGET_UNKNOWN`         | ERROR    | semantic    | Timeline event references a non-existent asset ID      |
| `E_SLOW_COPY_UNPAIRED`     | ERROR    | semantic    | slow_copy_start/commit pairing violated                 |
| `E_PATH_CONTAINMENT`       | ERROR    | semantic    | Scenario path violates library containment rules       |
| `E_PATH_DUPLICATE`         | WARNING  | semantic    | Two library roots resolve to the same path (see note below) |
| `E_TIMELINE_ORDER`         | ERROR    | semantic    | Timeline `at:` values not non-decreasing               |

Codes are stable strings. Adding new codes is allowed in later sprints;
renaming or removing a code is breaking.

**Note on `E_PATH_DUPLICATE` severity.** Duplicate library *root IDs* are an
ERROR (`E_ID_DUPLICATE`) because IDs are oracle keys — collisions would
ambiguate the journal. Duplicate library *root paths* with distinct IDs are
a WARNING: it's almost always a user mistake but technically lets a scenario
alias the same directory under two ID namespaces, which is well-defined.
Warnings do not flip `report.ok`, so `validate` still exits `0`; the warning
appears in the report.

## Dependencies

No new third-party dependencies. `ruamel.yaml>=0.18`, `pydantic>=2.10`, and
`typer>=0.13` are already declared in `pyproject.toml` from Sprint 0.

## Test Strategy

```text
tests/
  validation/
    __init__.py
    test_pipeline.py            # orchestrator, accumulation, scenario_id fallback
    test_shape.py               # Pydantic mapping, loc-walk, discriminator stripping
    test_semantic.py            # one test class per rule
    test_invalid_corpus.py      # parametrized over tests/fixtures/scenarios/invalid/
  test_scenario_io.py           # ruamel loader, LineIndex lookups
  test_clock.py                 # parse_duration: valid cases + every rejection mode
  cli/
    test_validate.py            # exit codes, --json shape, stdout text format
```

Fixture corpus:

```text
tests/fixtures/scenarios/
  identity-move-rename.yaml          # existing, valid
  version-evolution.yaml             # existing, valid
  bundle-sidecars.yaml               # existing, valid
  slow-copy.yaml                     # existing, valid
  invalid/
    yaml-parse-error.yaml            # E_YAML_PARSE
    missing-required-field.yaml      # E_FIELD_MISSING
    unknown-field.yaml               # E_FIELD_UNKNOWN
    unknown-action.yaml              # E_TIMELINE_ACTION_UNKNOWN
    bad-duration.yaml                # E_DURATION_SYNTAX
    duplicate-asset-id.yaml          # E_ID_DUPLICATE
    target-unknown.yaml              # E_TARGET_UNKNOWN
    slow-copy-unpaired.yaml          # E_SLOW_COPY_UNPAIRED
    path-escape.yaml                 # E_PATH_CONTAINMENT (`..` segment)
    timeline-out-of-order.yaml       # E_TIMELINE_ORDER
```

- Each invalid fixture is the smallest reproducer for one error code and
  carries a top-of-file YAML comment naming the expected code.
- `test_invalid_corpus.py` parametrizes over the directory; the assertion is
  "report contains at least one issue with the expected code AND `ok=False`".
  Smallest-reproducer + at-least-one keeps the suite robust as the code set
  grows.
- A separate test runs every valid fixture through `run_validation()` and
  asserts `ok=True` with zero issues — the Sprint 1 exit-criteria smoke test.

Tests follow CLAUDE.md Rule 9: each rule test names the WHY in its docstring
(e.g., "duplicate asset IDs would cause oracle ID collisions during plan").

## Docs Reconciliation

In the same PR:

- `docs/specs/chaos-librarian-design.md` §"Sprint 1": add "duration string
  parser" to deliverables.
- `docs/specs/chaos-librarian-design.md` §"Sprint 2": replace "duration
  string parser" with "duration string *formatters*"; clarify Sprint 2
  consumes the Sprint 1 parser.
- `docs/contract/cli-reference.md`: drop the "Sprint 0 ships every command
  as a stub" footnote (footnote stays accurate for the eight remaining
  stubs; reword to "every command except `validate` ships as a stub").
- `CLAUDE.md` §"Project state": update the sentence about CLI stubs to
  reflect `validate` is now real.

No schema changes. `schemas/validation.schema.json` already supports the
issue shape this sprint produces.

## Exit Criteria

The PR is mergeable when:

- `uv run pytest` passes — every new test file green, all 4 valid fixtures
  validate, every invalid fixture produces the expected error code
- `uv run ty check src tests` clean
- `uv run ruff check . && uv run ruff format --check .` clean
- `uv run python -m chaos_librarian.schema_export --check` clean
- `uv run chaos-librarian validate tests/fixtures/scenarios/identity-move-rename.yaml --json`
  exits `0` and emits a `ValidationReport` with `ok: true`, zero issues
- `uv run chaos-librarian validate tests/fixtures/scenarios/invalid/bad-duration.yaml --json`
  exits `3` and emits a report with `ok: false` and at least one
  `E_DURATION_SYNTAX` issue carrying a non-null `line`
- CI green on `feat/sprint-1`

## Non-Goals

- No write side-effects of any kind during `validate`
- No symlink resolution against a real filesystem root
- No `--strict` / severity-tuning flags
- No human-output stability guarantee (JSON is the contract; text format
  may evolve)
- No Pydantic version pin beyond what `pyproject.toml` already declares
- No expansion of the timeline event set (the nine `action:` variants
  shipped in Sprint 0 are the full V1 set)
