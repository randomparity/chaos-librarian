# Chaos Librarian Sprint 1: `validate` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the `chaos-librarian validate` stub into a real, complete static-validation command for scenario YAML files: line-aware YAML loading, Pydantic shape validation, cross-cutting semantic rules, and a `ValidationReport` that matches `schemas/validation.schema.json`. Exit `0` on success, `3` on any error-severity issue. No filesystem side effects.

**Architecture:** Three-layer pipeline. `scenario_io.load_scenario` parses YAML once with `ruamel.yaml` for line/column tracking, returns `(raw_dict, line_index)`. `validation.pipeline.run_validation` orchestrates: load → top-level-mapping guard → shape pass (`Scenario.model_validate`) → semantic pass (a list of rule functions sharing an `IssueCollector`) → assemble report. Every error has a stable `E_*` code and (where possible) a 1-based line/column. The CLI command is a thin wrapper that maps `report.ok` to exit `0` or `3` and renders either JSON or a human-readable table.

**Tech Stack:** Python 3.13, `ruamel.yaml>=0.18` (line-tracking parser), `pydantic>=2.10` (shape validation), `typer>=0.13` (CLI), `pytest>=8` (tests). No new dependencies — all already declared in `pyproject.toml`.

**Spec:** [`docs/superpowers/specs/2026-05-17-sprint-1-validate-design.md`](../specs/2026-05-17-sprint-1-validate-design.md). Re-read it before each task — it is the source of truth for error codes, rule semantics, namespace scopes, and exit criteria.

**Project conventions** (from `CLAUDE.md` — preserve them):
- `model_config = ConfigDict(extra="forbid")` on every Pydantic class.
- Absolute imports only (ruff `flake8-tidy-imports` `ban-relative-imports = "all"`).
- Use `enum.StrEnum` (not `str, enum.Enum`).
- `Annotated[Path, typer.Argument(...)]` for Typer Path args (not `Path = typer.Argument(...)`).
- Negative-test pattern: build a `dict` payload and call `Model.model_validate(payload)` — do **not** construct invalid models via kwargs + `# type: ignore`.
- After editing any contract model, regenerate `schemas/` — but this sprint touches **no** contract models, so no regeneration step.

---

## File Structure

```
chaos-librarian/
├── src/chaos_librarian/
│   ├── clock.py                         [Task 1] duration-string parser
│   ├── scenario_io.py                   [Task 2] YAML loader + LineIndex
│   ├── validation/
│   │   ├── __init__.py                  [Task 3] public surface re-exports
│   │   ├── codes.py                     [Task 3] E_* constants, Pydantic→code map, JSONPath formatter
│   │   ├── pipeline.py                  [Task 4] IssueCollector + run_validation
│   │   ├── shape.py                     [Task 5] Pydantic pass
│   │   └── semantic.py                  [Task 6→12] rule registry + every E_* rule
│   └── cli/app.py                       [Task 13] replace validate stub + _render_human helper
├── tests/
│   ├── test_clock.py                    [Task 1]
│   ├── test_scenario_io.py              [Task 2]
│   ├── validation/
│   │   ├── __init__.py                  [Task 3]
│   │   ├── test_codes.py                [Task 3]
│   │   ├── test_pipeline.py             [Task 4]
│   │   ├── test_shape.py                [Task 5]
│   │   ├── test_semantic.py             [Task 6→12] one class per rule
│   │   └── test_invalid_corpus.py       [Task 14] parametrized over invalid/
│   ├── fixtures/scenarios/
│   │   └── invalid/                     [Task 14] 13 invalid fixtures
│   └── cli/
│       ├── test_app.py                  [Task 13] update one existing test
│       └── test_validate.py             [Task 13] new
├── docs/specs/chaos-librarian-design.md [Task 15] Sprint 1/2 reshuffle
├── docs/contract/cli-reference.md       [Task 15] drop "every command stubbed" footnote
└── CLAUDE.md                            [Task 15] project-state line
```

**Notes on layout decisions:**

- `clock.py` and `scenario_io.py` live at the package root (not inside `validation/`) because Sprint 2 reuses them outside the validation pass (the logical clock, runtime YAML loading for `plan`).
- `semantic.py` keeps every rule in one module — rules are small (10–40 lines), share helper utilities, and run as a list. Splitting per-rule files would multiply boilerplate.
- `tests/validation/` mirrors `src/chaos_librarian/validation/`. `tests/test_clock.py` and `tests/test_scenario_io.py` sit at top level because the modules they test do.
- The plan touches **no** contract models and **no** schema files; the existing `schemas/validation.schema.json` already supports the `ValidationIssue` / `ValidationReport` shapes this sprint produces.

---

## Task 1: `clock.parse_duration`

**Files:**
- Create: `src/chaos_librarian/clock.py`
- Test: `tests/test_clock.py`

Grammar (from spec §"Time Model" and Sprint 1 design):
- `"0"` → `0`
- Otherwise: `<int><unit>` segments, units strictly descending, no spaces.
- Units: `h`, `m`, `s`, `ms`, `us`, `ns`.
- Rejects: empty, negative, fractional, unknown unit, duplicate unit, units out of order, sums that overflow `i64` ns (`2**63 - 1` = `9_223_372_036_854_775_807`).

Implementation strategy: a single anchored regex with six optional named groups in canonical order (`h`, `m`, `s`, `ms`, `us`, `ns`). Bare `"0"` short-circuits. After matching, at least one captured group must be non-`None`; an empty match means the input was something like `""` and is rejected.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_clock.py
"""Tests for chaos_librarian.clock.parse_duration."""

from __future__ import annotations

import pytest

from chaos_librarian.clock import DurationParseError, parse_duration


class TestParseDurationValid:
    """Valid duration strings parse to the correct nanosecond count.

    WHY: validate and every downstream pass treats durations as i64 ns.
    """

    @pytest.mark.parametrize(
        ("raw", "expected_ns"),
        [
            ("0", 0),
            ("1ns", 1),
            ("500ns", 500),
            ("1us", 1_000),
            ("1ms", 1_000_000),
            ("500ms", 500_000_000),
            ("1s", 1_000_000_000),
            ("2s", 2_000_000_000),
            ("1m", 60_000_000_000),
            ("1m30s", 90_000_000_000),
            ("1h", 3_600_000_000_000),
            ("1h2m3s", 3_723_000_000_000),
            ("1h2m3s4ms5us6ns", 3_723_004_005_006),
        ],
    )
    def test_valid_durations(self, raw: str, expected_ns: int) -> None:
        assert parse_duration(raw) == expected_ns


class TestParseDurationRejected:
    """Each rejected form raises DurationParseError with a useful reason.

    WHY: scenario authors need to know why a duration was rejected so they
    can fix the YAML. Vague errors degrade the validate UX.
    """

    @pytest.mark.parametrize(
        ("raw", "reason_substr"),
        [
            ("", "empty"),
            (" ", "whitespace"),
            ("1", "missing unit"),
            ("s", "missing"),
            ("-1s", "negative"),
            ("1.5s", "fractional"),
            ("1y", "unknown unit"),
            ("1s1s", "duplicate unit"),
            ("1ms1s", "out of order"),
            ("1s 1ms", "whitespace"),
            ("9999999999h", "overflow"),
        ],
    )
    def test_rejected(self, raw: str, reason_substr: str) -> None:
        with pytest.raises(DurationParseError) as excinfo:
            parse_duration(raw)
        assert reason_substr in excinfo.value.reason
        assert excinfo.value.raw == raw


def test_overflow_exceeds_i64_max() -> None:
    """A duration whose total ns > 2**63 - 1 is rejected.

    WHY: silent overflow would corrupt the journal's logical_time_ns.
    """
    # 1_000_000h ≈ 3.6e18 ns. i64 max ≈ 9.22e18 ns. 10_000_000h ≈ 3.6e19 — overflows.
    with pytest.raises(DurationParseError) as excinfo:
        parse_duration("10000000h")
    assert "overflow" in excinfo.value.reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_clock.py -v`
Expected: `ImportError` / `ModuleNotFoundError: No module named 'chaos_librarian.clock'`.

- [ ] **Step 3: Implement `clock.py`**

```python
# src/chaos_librarian/clock.py
"""Duration-string parser shared by validate, plan, and run.

Grammar matches docs/specs/chaos-librarian-design.md §"Time Model":
``<int><unit>`` segments in strictly descending order, units in
``h / m / s / ms / us / ns``, bare ``"0"`` accepted, no spaces, no fractions,
no negatives. Result is i64 nanoseconds.
"""

from __future__ import annotations

import re
from typing import Final

_I64_MAX_NS: Final[int] = 2**63 - 1

# Multipliers, keyed in canonical descending order so a single regex with
# named groups also enforces unit ordering.
_UNITS_DESCENDING: Final[tuple[tuple[str, int], ...]] = (
    ("h", 3_600_000_000_000),
    ("m", 60_000_000_000),
    ("s", 1_000_000_000),
    ("ms", 1_000_000),
    ("us", 1_000),
    ("ns", 1),
)

# Canonical regex: each group is optional but they MUST appear in order.
# ``ms``/``us``/``ns`` are listed before ``s`` would otherwise match them
# because they share the ``s`` suffix — we use the longer alternatives in
# the same group instead. Anchored, no whitespace tolerated.
_DURATION_RE: Final[re.Pattern[str]] = re.compile(
    r"\A"
    r"(?:(?P<h>\d+)h)?"
    r"(?:(?P<m>\d+)m)?"
    r"(?:(?P<s>\d+)s)?"
    r"(?:(?P<ms>\d+)ms)?"
    r"(?:(?P<us>\d+)us)?"
    r"(?:(?P<ns>\d+)ns)?"
    r"\Z"
)


class DurationParseError(ValueError):
    """Raised when a duration string violates the grammar or overflows i64."""

    def __init__(self, raw: str, reason: str) -> None:
        super().__init__(f"invalid duration {raw!r}: {reason}")
        self.raw = raw
        self.reason = reason


def parse_duration(raw: str) -> int:
    """Parse a duration string into integer nanoseconds.

    Args:
        raw: Duration string like ``"500ms"``, ``"2s"``, ``"1m30s"``, ``"0"``.

    Returns:
        Non-negative integer nanoseconds (i64 range).

    Raises:
        DurationParseError: For any rejection mode (see grammar in module
            docstring). The exception's ``reason`` field carries a short
            human-readable description.
    """
    if not raw:
        raise DurationParseError(raw, "empty string")
    if raw[0] == "-":
        raise DurationParseError(raw, "negative durations not allowed")
    if any(c.isspace() for c in raw):
        raise DurationParseError(raw, "whitespace not allowed")
    if "." in raw:
        raise DurationParseError(raw, "fractional durations not allowed")
    if raw == "0":
        return 0

    match = _DURATION_RE.fullmatch(raw)
    if match is None:
        # Distinguish common failure modes for a better error message.
        if raw.isdigit():
            raise DurationParseError(raw, "missing unit suffix")
        # Catch unknown units and out-of-order/duplicate cases by re-scanning.
        _diagnose_or_raise(raw)
        raise DurationParseError(raw, "does not match duration grammar")

    groups = match.groupdict()
    if all(v is None for v in groups.values()):
        # Anchored regex can match empty string between anchors; reject.
        raise DurationParseError(raw, "missing unit suffix")

    total = 0
    for unit, multiplier in _UNITS_DESCENDING:
        captured = groups.get(unit)
        if captured is None:
            continue
        try:
            value = int(captured)
        except ValueError as e:  # pragma: no cover — regex guarantees digits
            raise DurationParseError(raw, f"non-integer segment {captured!r}") from e
        total += value * multiplier
        if total > _I64_MAX_NS:
            raise DurationParseError(raw, "overflow (exceeds i64 nanoseconds)")
    return total


def _diagnose_or_raise(raw: str) -> None:
    """Produce a precise reason for inputs the canonical regex rejects.

    Walks the input left-to-right pulling ``<int><unit>`` segments, raising
    a specific ``DurationParseError`` for unknown units, duplicates, and
    out-of-order segments.
    """
    seen_unit_indices: list[int] = []
    pos = 0
    segment_re = re.compile(r"(?P<n>\d+)(?P<u>[a-z]+)")
    valid_units = [u for u, _ in _UNITS_DESCENDING]
    while pos < len(raw):
        m = segment_re.match(raw, pos)
        if m is None:
            raise DurationParseError(raw, f"unexpected character at offset {pos}")
        unit = m.group("u")
        if unit not in valid_units:
            raise DurationParseError(raw, f"unknown unit {unit!r}")
        idx = valid_units.index(unit)
        if idx in seen_unit_indices:
            raise DurationParseError(raw, f"duplicate unit {unit!r}")
        if seen_unit_indices and idx < seen_unit_indices[-1]:
            raise DurationParseError(raw, "units out of order (must be descending)")
        seen_unit_indices.append(idx)
        pos = m.end()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_clock.py -v`
Expected: all tests pass.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/chaos_librarian/clock.py tests/test_clock.py && uv run ruff format --check src/chaos_librarian/clock.py tests/test_clock.py && uv run ty check src/chaos_librarian/clock.py tests/test_clock.py`
Expected: clean (no warnings, no errors).

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/clock.py tests/test_clock.py
git commit -m "feat(clock): add parse_duration for scenario time strings"
```

---

## Task 2: `scenario_io.load_scenario` + `LineIndex`

**Files:**
- Create: `src/chaos_librarian/scenario_io.py`
- Test: `tests/test_scenario_io.py`

`ruamel.yaml.YAML(typ="rt")` parses YAML into `CommentedMap` / `CommentedSeq` instances that carry line/column data via `.lc` attributes:
- `CommentedMap`'s `.lc.data` is `dict[key, (key_line, key_col, value_line, value_col)]`.
- `CommentedSeq`'s `.lc.data` is `dict[index, (item_line, item_col, _, _)]`. Access via `.lc.item(idx)` returns `(line, col)`.
- ruamel reports 0-based lines; we expose 1-based (editor convention).

`load_scenario` walks the tree once, building a `dict[tuple[str | int, ...], tuple[int, int]]` from path-tuple to `(line, col)`, and returns `(plain_dict, line_index)`. The plain dict is built by recursively `dict()`-ifying CommentedMaps and `list()`-ifying CommentedSeqs so downstream passes never depend on ruamel's API.

`ScenarioLoadError` wraps `ruamel.yaml.YAMLError` and carries the offending line/col when ruamel provided one.

- [ ] **Step 1: Write failing tests**

```python
# tests/test_scenario_io.py
"""Tests for chaos_librarian.scenario_io: YAML loader + LineIndex."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.scenario_io import LineIndex, ScenarioLoadError, load_scenario


def _write(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "scenario.yaml"
    path.write_text(content)
    return path


class TestLoadScenarioHappyPath:
    """Valid YAML returns a plain dict and a line-index keyed by path tuple.

    WHY: downstream validation passes must work with plain Python types and
    must be able to resolve any field back to its (line, column) for the
    final ValidationReport.
    """

    def test_returns_plain_dict_and_line_index(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            (
                "schema_version: 1\n"
                "scenario_id: t\n"
                "timeline:\n"
                "  - id: e1\n"
                "    at: 1s\n"
            ),
        )
        raw, index = load_scenario(path)
        assert isinstance(raw, dict)
        assert raw["scenario_id"] == "t"
        assert isinstance(raw["timeline"], list)
        assert raw["timeline"][0]["id"] == "e1"
        # Downstream code should see no ruamel types anywhere.
        assert type(raw).__name__ == "dict"
        assert type(raw["timeline"]).__name__ == "list"
        # Top-level keys are at known 1-based lines.
        assert index.lookup(("schema_version",)) == (1, 0)
        assert index.lookup(("scenario_id",)) == (2, 0)
        assert index.lookup(("timeline",)) == (3, 0)
        # Nested keys carry their own positions.
        assert index.lookup(("timeline", 0, "id")) == (4, 4)
        assert index.lookup(("timeline", 0, "at")) == (5, 4)

    def test_missing_path_lookup_returns_none(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "scenario_id: t\n")
        _, index = load_scenario(path)
        assert index.lookup(("nonexistent",)) is None
        assert index.lookup(("timeline", 99, "at")) is None


class TestLoadScenarioErrors:
    """YAML syntax errors are surfaced as ScenarioLoadError with line/col.

    WHY: the pipeline emits a single E_YAML_PARSE issue carrying the
    reported position; validate cannot proceed without parsed YAML.
    """

    def test_yaml_syntax_error_raises_load_error(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "key: : value\n")  # double-colon trips ruamel
        with pytest.raises(ScenarioLoadError) as excinfo:
            load_scenario(path)
        assert excinfo.value.line is not None
        assert excinfo.value.line >= 1

    def test_missing_file_raises_load_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "missing.yaml"
        with pytest.raises(ScenarioLoadError):
            load_scenario(missing)


class TestLineIndexTopLevelShape:
    """Non-mapping top-level YAML returns a non-dict raw value.

    WHY: the pipeline's step 1.5 (top-level mapping guard) needs to detect
    scalars and sequences and short-circuit before the shape pass crashes.
    """

    def test_scalar_top_level(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "42\n")
        raw, _ = load_scenario(path)
        assert raw == 42

    def test_sequence_top_level(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "- a\n- b\n")
        raw, _ = load_scenario(path)
        assert raw == ["a", "b"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_scenario_io.py -v`
Expected: `ImportError`.

- [ ] **Step 3: Implement `scenario_io.py`**

```python
# src/chaos_librarian/scenario_io.py
"""YAML loader with per-node line/column tracking.

Uses ``ruamel.yaml`` round-trip mode for position info, then walks the
parsed tree once to build a path-tuple → (line, column) index. Returns a
plain ``dict`` / ``list`` tree so downstream passes never depend on
ruamel-specific types.

Lines are exposed 1-based (editor convention) even though ruamel reports
0-based internally.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML, YAMLError
from ruamel.yaml.comments import CommentedMap, CommentedSeq

_PathPart = str | int
_PathTuple = tuple[_PathPart, ...]


class ScenarioLoadError(Exception):
    """Raised when the YAML file cannot be parsed.

    Attributes:
        line: 1-based line of the failure if ruamel reported one, else None.
        column: 0-based column of the failure if ruamel reported one, else None.
    """

    def __init__(self, message: str, line: int | None, column: int | None) -> None:
        super().__init__(message)
        self.line = line
        self.column = column


@dataclass(frozen=True)
class LineIndex:
    """Maps path tuples to ``(line, column)`` for downstream issue reporting."""

    _data: dict[_PathTuple, tuple[int, int]] = field(default_factory=dict)

    def lookup(self, loc: _PathTuple) -> tuple[int, int] | None:
        return self._data.get(loc)


def load_scenario(path: Path) -> tuple[Any, LineIndex]:
    """Parse a YAML scenario file with line tracking.

    Args:
        path: Absolute or relative path to a YAML file.

    Returns:
        ``(raw_data, line_index)``. ``raw_data`` is a plain Python tree
        (dict / list / scalars). The caller is responsible for the
        top-level-shape check (see ``validation.pipeline``).

    Raises:
        ScenarioLoadError: On any YAMLError, missing file, or unreadable file.
    """
    try:
        text = path.read_text()
    except OSError as e:
        raise ScenarioLoadError(f"cannot read {path}: {e}", line=None, column=None) from e

    yaml = YAML(typ="rt")
    try:
        loaded = yaml.load(text)
    except YAMLError as e:
        line, column = _yaml_error_position(e)
        raise ScenarioLoadError(f"YAML parse error in {path}: {e}", line, column) from e

    index_data: dict[_PathTuple, tuple[int, int]] = {}
    plain = _walk(loaded, path_so_far=(), index=index_data)
    return plain, LineIndex(_data=index_data)


def _walk(
    node: Any,
    path_so_far: _PathTuple,
    index: dict[_PathTuple, tuple[int, int]],
) -> Any:
    """Recursively convert ruamel containers to plain dict/list, recording positions."""
    if isinstance(node, CommentedMap):
        result: dict[str, Any] = {}
        lc_data = getattr(node, "lc", None)
        for key, value in node.items():
            child_path = (*path_so_far, key)
            if lc_data is not None and key in lc_data.data:
                # lc.data[key] is (key_line, key_col, value_line, value_col), 0-based.
                key_line, key_col, *_ = lc_data.data[key]
                index[child_path] = (key_line + 1, key_col)
            result[key] = _walk(value, child_path, index)
        return result
    if isinstance(node, CommentedSeq):
        result_list: list[Any] = []
        for idx, value in enumerate(node):
            child_path = (*path_so_far, idx)
            try:
                line, col = node.lc.item(idx)
                index[child_path] = (line + 1, col)
            except (AttributeError, KeyError, TypeError):
                pass
            result_list.append(_walk(value, child_path, index))
        return result_list
    return node


def _yaml_error_position(error: YAMLError) -> tuple[int | None, int | None]:
    """Extract 1-based line and 0-based column from a YAMLError if available."""
    mark = getattr(error, "problem_mark", None) or getattr(error, "context_mark", None)
    if mark is None:
        return None, None
    return mark.line + 1, mark.column
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_scenario_io.py -v`
Expected: all tests pass. (If `test_yaml_syntax_error_raises_load_error` fails because the chosen malformed input doesn't trigger a YAMLError, swap it for `"key: [\n"` which is unambiguously broken.)

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/chaos_librarian/scenario_io.py tests/test_scenario_io.py && uv run ruff format --check src/chaos_librarian/scenario_io.py tests/test_scenario_io.py && uv run ty check src/chaos_librarian/scenario_io.py tests/test_scenario_io.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/scenario_io.py tests/test_scenario_io.py
git commit -m "feat(scenario_io): add line-tracking YAML loader"
```

---

## Task 3: `validation/codes.py` + package skeleton

**Files:**
- Create: `src/chaos_librarian/validation/__init__.py`
- Create: `src/chaos_librarian/validation/codes.py`
- Create: `tests/validation/__init__.py`
- Create: `tests/validation/test_codes.py`

`codes.py` owns three concerns:
1. **Constants** for every `E_*` code (so callers don't pass string literals).
2. **`PYDANTIC_TO_CODE`**: a `dict[str, str]` mapping Pydantic v2 error `type` strings to chaos-librarian codes. Unmapped types fall through to `E_FIELD_SHAPE`.
3. **`format_jsonpath(loc)`**: convert a Pydantic-style loc tuple to a JSONPath like `$.timeline[3].target`, with discriminator tags stripped and the `for_`→`for` alias rewrite applied.

Pydantic v2 error types seen in practice for the Scenario model:
- `missing` → `E_FIELD_MISSING`
- `extra_forbidden` → `E_FIELD_UNKNOWN`
- `literal_error` → `E_FIELD_LITERAL`
- `string_type`, `int_type`, `float_type`, `bool_type`, `list_type`, `dict_type` → `E_FIELD_TYPE`
- `union_tag_invalid`, `union_tag_not_found` → `E_TIMELINE_ACTION_UNKNOWN`

Discriminator-tag values to strip from loc: the 9 action variants from `Scenario.timeline`.

Field-alias rewrites: `for_` → `for` (the `SlowCopyCommitEvent.for_` field's serialization alias).

- [ ] **Step 1: Write failing tests**

```python
# tests/validation/__init__.py
```

```python
# tests/validation/test_codes.py
"""Tests for validation.codes: constants, Pydantic map, JSONPath formatter."""

from __future__ import annotations

import pytest

from chaos_librarian.validation import codes


class TestPydanticToCode:
    """Pydantic error types map to stable chaos-librarian E_* codes.

    WHY: the public code set is a contract for downstream tooling (voom-v2,
    CI green/red dashboards). Renaming a code is a breaking change.
    """

    @pytest.mark.parametrize(
        ("pydantic_type", "expected_code"),
        [
            ("missing", "E_FIELD_MISSING"),
            ("extra_forbidden", "E_FIELD_UNKNOWN"),
            ("literal_error", "E_FIELD_LITERAL"),
            ("string_type", "E_FIELD_TYPE"),
            ("int_type", "E_FIELD_TYPE"),
            ("list_type", "E_FIELD_TYPE"),
            ("dict_type", "E_FIELD_TYPE"),
            ("union_tag_invalid", "E_TIMELINE_ACTION_UNKNOWN"),
            ("union_tag_not_found", "E_TIMELINE_ACTION_UNKNOWN"),
        ],
    )
    def test_known_pydantic_types_map(self, pydantic_type: str, expected_code: str) -> None:
        assert codes.PYDANTIC_TO_CODE[pydantic_type] == expected_code

    def test_unmapped_type_returns_none(self) -> None:
        """Unmapped types must not be in the dict (caller falls back to E_FIELD_SHAPE)."""
        assert "made_up_type" not in codes.PYDANTIC_TO_CODE


class TestFormatJSONPath:
    """Loc tuples convert to JSONPath strings, stripping discriminator tags.

    WHY: scenario authors read the path in the report to find the field;
    the discriminator tag (e.g., "slow_copy_commit") is a Pydantic
    internal, not a YAML key, and would mislead them.
    """

    def test_root_loc(self) -> None:
        assert codes.format_jsonpath(()) == "$"

    def test_simple_field(self) -> None:
        assert codes.format_jsonpath(("scenario_id",)) == "$.scenario_id"

    def test_nested(self) -> None:
        assert codes.format_jsonpath(("timeline", 3, "target")) == "$.timeline[3].target"

    def test_deep_nested(self) -> None:
        assert (
            codes.format_jsonpath(("works", 0, "variants", 1, "bundle", "assets", 2, "id"))
            == "$.works[0].variants[1].bundle.assets[2].id"
        )

    def test_discriminator_tag_stripped(self) -> None:
        """Pydantic inserts the resolved discriminator value mid-loc; strip it."""
        loc = ("timeline", 5, "slow_copy_commit", "for_")
        # tag stripped; alias for_ → for applied
        assert codes.format_jsonpath(loc) == "$.timeline[5].for"

    def test_all_discriminator_tags_stripped(self) -> None:
        for tag in (
            "move_asset",
            "rename_file",
            "delete_file",
            "add_file",
            "reencode_video",
            "reencode_audio",
            "create_sidecar",
            "slow_copy_start",
            "slow_copy_commit",
        ):
            assert codes.format_jsonpath(("timeline", 0, tag, "target")) == "$.timeline[0].target"

    def test_for_alias_rewrite_without_tag(self) -> None:
        """Even if Pydantic ever omits the tag, the for_ → for alias still applies."""
        assert codes.format_jsonpath(("timeline", 5, "for_")) == "$.timeline[5].for"


class TestCodeConstants:
    """All E_* codes referenced by the spec are defined as constants.

    WHY: rules and tests refer to constants, not string literals, so a
    code rename is a single-file change.
    """

    @pytest.mark.parametrize(
        "name",
        [
            "E_YAML_PARSE",
            "E_TOP_LEVEL_NOT_MAPPING",
            "E_FIELD_MISSING",
            "E_FIELD_UNKNOWN",
            "E_FIELD_LITERAL",
            "E_FIELD_TYPE",
            "E_FIELD_SHAPE",
            "E_TIMELINE_ACTION_UNKNOWN",
            "E_DURATION_SYNTAX",
            "E_ID_DUPLICATE",
            "E_TARGET_UNKNOWN",
            "E_SLOW_COPY_UNPAIRED",
            "E_SLOW_COPY_TIMING",
            "E_PATH_CONTAINMENT",
            "E_PATH_DUPLICATE",
            "E_TIMELINE_ORDER",
        ],
    )
    def test_constant_defined(self, name: str) -> None:
        assert getattr(codes, name) == name
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/validation/test_codes.py -v`
Expected: `ImportError` / `ModuleNotFoundError`.

- [ ] **Step 3: Create the package skeleton and `codes.py`**

`validation/__init__.py` is intentionally empty in this task — Task 4 will
populate it once `pipeline.py` exists (otherwise this task would have a
circular import). Just write the file with a one-line docstring:

```python
# src/chaos_librarian/validation/__init__.py
"""Validation pipeline package. Public surface assembled in Task 4."""
```

```python
# src/chaos_librarian/validation/codes.py
"""Stable error-code constants, Pydantic→code map, and JSONPath formatter.

Codes are part of the public contract (see
``docs/superpowers/specs/2026-05-17-sprint-1-validate-design.md``
§"Error Code Reference"). Adding new codes is allowed; renaming or
removing one is breaking.
"""

from __future__ import annotations

from typing import Final

# ---- Code constants --------------------------------------------------------

E_YAML_PARSE: Final = "E_YAML_PARSE"
E_TOP_LEVEL_NOT_MAPPING: Final = "E_TOP_LEVEL_NOT_MAPPING"
E_FIELD_MISSING: Final = "E_FIELD_MISSING"
E_FIELD_UNKNOWN: Final = "E_FIELD_UNKNOWN"
E_FIELD_LITERAL: Final = "E_FIELD_LITERAL"
E_FIELD_TYPE: Final = "E_FIELD_TYPE"
E_FIELD_SHAPE: Final = "E_FIELD_SHAPE"
E_TIMELINE_ACTION_UNKNOWN: Final = "E_TIMELINE_ACTION_UNKNOWN"
E_DURATION_SYNTAX: Final = "E_DURATION_SYNTAX"
E_ID_DUPLICATE: Final = "E_ID_DUPLICATE"
E_TARGET_UNKNOWN: Final = "E_TARGET_UNKNOWN"
E_SLOW_COPY_UNPAIRED: Final = "E_SLOW_COPY_UNPAIRED"
E_SLOW_COPY_TIMING: Final = "E_SLOW_COPY_TIMING"
E_PATH_CONTAINMENT: Final = "E_PATH_CONTAINMENT"
E_PATH_DUPLICATE: Final = "E_PATH_DUPLICATE"
E_TIMELINE_ORDER: Final = "E_TIMELINE_ORDER"


# ---- Pydantic error-type → chaos-librarian code ----------------------------

PYDANTIC_TO_CODE: Final[dict[str, str]] = {
    "missing": E_FIELD_MISSING,
    "extra_forbidden": E_FIELD_UNKNOWN,
    "literal_error": E_FIELD_LITERAL,
    # Type-shape errors: every Pydantic primitive type-check funnels to E_FIELD_TYPE.
    "string_type": E_FIELD_TYPE,
    "int_type": E_FIELD_TYPE,
    "float_type": E_FIELD_TYPE,
    "bool_type": E_FIELD_TYPE,
    "list_type": E_FIELD_TYPE,
    "dict_type": E_FIELD_TYPE,
    "model_type": E_FIELD_TYPE,
    # Discriminated-union failures on Scenario.timeline.
    "union_tag_invalid": E_TIMELINE_ACTION_UNKNOWN,
    "union_tag_not_found": E_TIMELINE_ACTION_UNKNOWN,
}


# ---- JSONPath formatting ---------------------------------------------------

# Discriminator values that Pydantic inserts mid-loc for Scenario.timeline.
# Source of truth: ``Scenario.timeline``'s discriminated union variants.
_DISCRIMINATOR_TAGS: Final[frozenset[str]] = frozenset(
    {
        "move_asset",
        "rename_file",
        "delete_file",
        "add_file",
        "reencode_video",
        "reencode_audio",
        "create_sidecar",
        "slow_copy_start",
        "slow_copy_commit",
    }
)

# Pydantic emits Python field names in loc tuples. Map them back to the
# YAML/JSON alias used in the user's scenario file.
_ALIAS_REWRITES: Final[dict[str, str]] = {
    "for_": "for",
}


def format_jsonpath(loc: tuple[str | int, ...]) -> str:
    """Convert a Pydantic-style loc tuple to a JSONPath string.

    Strips discriminator-tag segments (e.g., ``"slow_copy_commit"``) and
    rewrites Python field aliases (e.g., ``for_`` → ``for``).

    >>> format_jsonpath(("timeline", 3, "target"))
    '$.timeline[3].target'
    >>> format_jsonpath(("timeline", 5, "slow_copy_commit", "for_"))
    '$.timeline[5].for'
    """
    cleaned: list[str | int] = []
    for segment in loc:
        if isinstance(segment, str) and segment in _DISCRIMINATOR_TAGS:
            continue
        if isinstance(segment, str) and segment in _ALIAS_REWRITES:
            cleaned.append(_ALIAS_REWRITES[segment])
        else:
            cleaned.append(segment)

    if not cleaned:
        return "$"
    parts = ["$"]
    for segment in cleaned:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        else:
            parts.append(f".{segment}")
    return "".join(parts)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/validation/test_codes.py -v`
Expected: all tests pass.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/chaos_librarian/validation tests/validation && uv run ruff format --check src/chaos_librarian/validation tests/validation && uv run ty check src/chaos_librarian/validation tests/validation`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/validation/__init__.py src/chaos_librarian/validation/codes.py tests/validation/__init__.py tests/validation/test_codes.py
git commit -m "feat(validation): add codes module with E_* constants and JSONPath formatter"
```

---

## Task 4: `validation/pipeline.py` (`IssueCollector` + `run_validation`)

**Files:**
- Create: `src/chaos_librarian/validation/pipeline.py`
- Modify: `src/chaos_librarian/validation/__init__.py` (re-export public surface)
- Test: `tests/validation/test_pipeline.py`

`run_validation` orchestrates: load → top-level-mapping guard (step 1.5) → shape pass → semantic pass → assemble report. Tasks 5+ implement the shape and semantic passes — for now, register them as no-op placeholders that other tasks fill in.

`IssueCollector.add` resolves `loc` to `(line, column)` via `LineIndex.lookup`, walking up the loc tuple if the exact lookup misses. Whole-file fallback is `(1, 0)`. It pushes a `ValidationIssue` onto its internal list.

Step 1.5 (top-level mapping guard): if `raw_data` is not a dict, emit one `E_TOP_LEVEL_NOT_MAPPING` at `loc=()`, `(line, column)=(1, 0)`, set `ok=False`, return early.

- [ ] **Step 1: Write failing tests**

```python
# tests/validation/test_pipeline.py
"""Tests for run_validation orchestration and IssueCollector behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation import codes, run_validation
from chaos_librarian.validation.pipeline import IssueCollector


def _write(tmp_path: Path, content: str, name: str = "scenario.yaml") -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


class TestRunValidationLoaderErrors:
    """YAML parse failures and missing files produce E_YAML_PARSE.

    WHY: the loader is the entry point; a parse failure must surface as a
    structured issue, not a stack trace, so the CLI can exit 3 cleanly.
    """

    def test_yaml_syntax_error_short_circuits(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "key: [\n")
        report = run_validation(path)
        assert report.ok is False
        assert any(i.code == codes.E_YAML_PARSE for i in report.issues)
        assert report.scenario_id == "<unknown>"

    def test_missing_file_short_circuits(self, tmp_path: Path) -> None:
        report = run_validation(tmp_path / "missing.yaml")
        assert report.ok is False
        assert any(i.code == codes.E_YAML_PARSE for i in report.issues)


class TestRunValidationTopLevelMappingGuard:
    """Non-mapping top-level YAML produces E_TOP_LEVEL_NOT_MAPPING (step 1.5).

    WHY: the shape pass assumes raw_data is a dict. A scalar (`42`) or
    sequence (`[]`) is valid YAML and not a YAMLError, so without this
    guard validate would crash. Closes Codex review finding #3.
    """

    def test_scalar_top_level_emits_code(self, tmp_path: Path) -> None:
        report = run_validation(_write(tmp_path, "42\n"))
        assert report.ok is False
        assert any(i.code == codes.E_TOP_LEVEL_NOT_MAPPING for i in report.issues)
        # exactly one issue — the pipeline returned early
        assert len(report.issues) == 1
        assert report.issues[0].line == 1
        assert report.issues[0].column == 0
        assert report.scenario_id == "<unknown>"

    def test_sequence_top_level_emits_code(self, tmp_path: Path) -> None:
        report = run_validation(_write(tmp_path, "- a\n- b\n"))
        assert report.ok is False
        assert any(i.code == codes.E_TOP_LEVEL_NOT_MAPPING for i in report.issues)
        assert len(report.issues) == 1

    def test_empty_file_emits_code(self, tmp_path: Path) -> None:
        """Empty YAML parses to None — not a mapping."""
        report = run_validation(_write(tmp_path, ""))
        assert report.ok is False
        assert any(i.code == codes.E_TOP_LEVEL_NOT_MAPPING for i in report.issues)


class TestRunValidationHappyPath:
    """A well-formed scenario passes both shape and semantic passes.

    WHY: this is the Sprint 1 exit-criteria smoke. If a valid fixture
    starts failing, the regression is in one of those passes.
    """

    def test_minimal_valid_scenario(self, tmp_path: Path) -> None:
        # Smallest valid Scenario: one work, one variant, one bundle, one asset,
        # no timeline events (all rules guard on emptiness and skip).
        path = _write(
            tmp_path,
            "schema_version: 1\n"
            "scenario_id: minimal\n"
            "seed: 1\n"
            "duration_scale: short\n"
            "library:\n"
            "  roots:\n"
            "    - id: r\n"
            "      path: r\n"
            "works:\n"
            "  - id: w\n"
            "    title: t\n"
            "    variants:\n"
            "      - id: v\n"
            "        label: l\n"
            "        bundle:\n"
            "          id: b\n"
            "          assets:\n"
            "            - id: a\n"
            "              role: primary_video\n"
            "              container: mkv\n"
            "              duration_seconds: 1\n"
            "timeline: []\n",
        )
        report = run_validation(path)
        assert report.ok is True
        assert report.issues == []
        assert report.scenario_id == "minimal"


class TestIssueCollectorLocResolution:
    """Loc tuples resolve to (line, column) via LineIndex, with walk-up fallback.

    WHY: if Pydantic returns a deep loc but only the parent has a line
    recorded (e.g., the field value is on a separate line), walking up
    keeps us from emitting (None, None) for an issue we know about.
    """

    def test_exact_hit(self) -> None:
        index = LineIndex(_data={("timeline", 3, "at"): (42, 14)})
        collector = IssueCollector()
        collector.add(
            code=codes.E_DURATION_SYNTAX,
            severity=ValidationSeverity.ERROR,
            message="bad",
            loc=("timeline", 3, "at"),
            line_index=index,
        )
        assert collector.issues[0].line == 42
        assert collector.issues[0].column == 14

    def test_walk_up_one_level(self) -> None:
        index = LineIndex(_data={("timeline", 3): (40, 4)})
        collector = IssueCollector()
        collector.add(
            code=codes.E_DURATION_SYNTAX,
            severity=ValidationSeverity.ERROR,
            message="bad",
            loc=("timeline", 3, "at"),
            line_index=index,
        )
        assert collector.issues[0].line == 40

    def test_whole_file_fallback(self) -> None:
        index = LineIndex()  # empty
        collector = IssueCollector()
        collector.add(
            code=codes.E_YAML_PARSE,
            severity=ValidationSeverity.ERROR,
            message="bad",
            loc=(),
            line_index=index,
        )
        assert collector.issues[0].line == 1
        assert collector.issues[0].column == 0


class TestRunValidationReportSorting:
    """Issues are sorted by (line, column, code) for stable output.

    WHY: deterministic ordering keeps diffs of report JSON small and
    makes golden-output tests possible downstream.
    """

    def test_sorted_by_position(self, tmp_path: Path) -> None:
        # A scenario with two field-level errors at different lines.
        path = _write(
            tmp_path,
            "schema_version: 1\n"
            "scenario_id: dup\n"
            "seed: 1\n"
            "duration_scale: short\n"
            "library:\n"
            "  roots: []\n"  # valid: empty roots
            "works: []\n"
            "timeline:\n"
            "  - id: e1\n"
            "    at: not-a-duration\n"  # E_DURATION_SYNTAX at line 10
            "    action: delete_file\n"
            "    target: nope\n"  # E_TARGET_UNKNOWN
            "  - id: e2\n"
            "    at: also-bad\n"  # E_DURATION_SYNTAX at line 14
            "    action: delete_file\n"
            "    target: nope2\n",
        )
        report = run_validation(path)
        lines = [i.line for i in report.issues if i.line is not None]
        assert lines == sorted(lines)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/validation/test_pipeline.py -v`
Expected: `ImportError` from `from chaos_librarian.validation.pipeline import IssueCollector`.

- [ ] **Step 3: Implement `pipeline.py`**

```python
# src/chaos_librarian/validation/pipeline.py
"""Validation pipeline: orchestrator and IssueCollector.

Flow (matches the Sprint 1 design spec):

1. ``load_scenario(path)`` → if it raises ``ScenarioLoadError``, emit one
   ``E_YAML_PARSE`` issue and return early.
1.5. **Top-level shape guard.** If ``raw_data`` is not a ``dict``, emit
   ``E_TOP_LEVEL_NOT_MAPPING`` and return early. Subsequent passes assume
   a mapping and would crash on a list or scalar.
2. ``run_shape_pass`` (Pydantic ``Scenario.model_validate``) → emits zero
   or more issues; returns ``Scenario | None``.
3. ``run_semantic_pass`` → runs unconditionally, even if step 2 produced
   issues. Each rule guards its own preconditions.
4. Assemble ``ValidationReport`` with ``scenario_id`` from raw_data (else
   ``"<unknown>"``), ``ok = (no ERROR issues)``, and issues sorted by
   (line, column, code) for stable output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from chaos_librarian.contract.validation import (
    ValidationIssue,
    ValidationReport,
    ValidationSeverity,
)
from chaos_librarian.scenario_io import (
    LineIndex,
    ScenarioLoadError,
    load_scenario,
)
from chaos_librarian.validation import codes
from chaos_librarian.validation.semantic import run_semantic_pass
from chaos_librarian.validation.shape import run_shape_pass


@dataclass
class IssueCollector:
    """Accumulator passed to every pass; resolves loc → (line, column)."""

    issues: list[ValidationIssue] = field(default_factory=list)

    def add(
        self,
        *,
        code: str,
        severity: ValidationSeverity,
        message: str,
        loc: tuple[str | int, ...],
        line_index: LineIndex,
    ) -> None:
        position = _resolve_position(loc, line_index)
        self.issues.append(
            ValidationIssue(
                severity=severity,
                code=code,
                message=message,
                line=position[0],
                column=position[1],
                path=codes.format_jsonpath(loc) if loc else None,
            )
        )


def run_validation(scenario_path: Path) -> ValidationReport:
    """Run the full validation pipeline against a scenario file.

    Returns a ``ValidationReport`` regardless of outcome. ``report.ok``
    is ``True`` iff zero ERROR-severity issues accumulated.
    """
    collector = IssueCollector()

    # Step 1: load.
    try:
        raw_data, line_index = load_scenario(scenario_path)
    except ScenarioLoadError as e:
        line_index = LineIndex()
        collector.add(
            code=codes.E_YAML_PARSE,
            severity=ValidationSeverity.ERROR,
            message=str(e),
            loc=(),
            line_index=line_index,
        )
        return _assemble_report(scenario_id="<unknown>", collector=collector)

    # Step 1.5: top-level shape guard. A non-mapping top level would crash
    # the shape pass; emit a structured issue and stop here.
    if not isinstance(raw_data, dict):
        collector.add(
            code=codes.E_TOP_LEVEL_NOT_MAPPING,
            severity=ValidationSeverity.ERROR,
            message=(
                f"top-level YAML is {type(raw_data).__name__}, expected mapping"
            ),
            loc=(),
            line_index=LineIndex(),
        )
        return _assemble_report(scenario_id="<unknown>", collector=collector)

    # Step 2: shape pass.
    run_shape_pass(raw_data, line_index, collector)

    # Step 3: semantic pass (runs even if shape produced issues; rules guard).
    run_semantic_pass(raw_data, line_index, collector)

    # Step 4: assemble.
    scenario_id_raw = raw_data.get("scenario_id")
    scenario_id = scenario_id_raw if isinstance(scenario_id_raw, str) else "<unknown>"
    return _assemble_report(scenario_id=scenario_id, collector=collector)


def _assemble_report(scenario_id: str, collector: IssueCollector) -> ValidationReport:
    issues_sorted = sorted(
        collector.issues,
        key=lambda i: (i.line or 0, i.column or 0, i.code),
    )
    ok = not any(i.severity == ValidationSeverity.ERROR for i in issues_sorted)
    return ValidationReport(
        schema_version=1,
        scenario_id=scenario_id,
        ok=ok,
        issues=issues_sorted,
    )


def _resolve_position(
    loc: tuple[str | int, ...],
    line_index: LineIndex,
) -> tuple[int | None, int | None]:
    """Look up ``loc`` in the line index, walking up if the exact path misses.

    Whole-file fallback is ``(1, 0)`` so issues without precise location
    still anchor to *something* — never (None, None) once a line index
    exists.
    """
    current = loc
    while current:
        hit = line_index.lookup(current)
        if hit is not None:
            return hit
        current = current[:-1]
    # Top-level fallback.
    top = line_index.lookup(())
    if top is not None:
        return top
    return 1, 0
```

Update `__init__.py` to expose the public surface:

```python
# src/chaos_librarian/validation/__init__.py
"""Public surface for the validation pipeline."""

from __future__ import annotations

from chaos_librarian.validation.codes import format_jsonpath  # noqa: F401 — public
from chaos_librarian.validation.pipeline import IssueCollector, run_validation

__all__ = ["IssueCollector", "format_jsonpath", "run_validation"]
```

`pipeline.py` imports `run_shape_pass` and `run_semantic_pass`. They don't exist yet, so create empty placeholder modules now:

```python
# src/chaos_librarian/validation/shape.py
"""Pydantic shape-validation pass. Implemented in Task 5."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector


def run_shape_pass(
    raw_data: dict,
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> None:
    """Stub — Task 5 fills this in."""
    return None
```

```python
# src/chaos_librarian/validation/semantic.py
"""Semantic-validation pass. Rules are registered in Tasks 6–12."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector


def run_semantic_pass(
    raw_data: dict,
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> None:
    """Stub — Task 6 starts the rule registry; Tasks 7–12 add rules."""
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/validation/test_pipeline.py -v`
Expected: most tests pass. The `TestRunValidationReportSorting` test depends on Rule 3 (E_DURATION_SYNTAX) which lands in Task 8 — so it will currently produce zero semantic issues and the assertion `lines == sorted(lines)` holds vacuously. That is intentional; the test still gates against a future regression that breaks sorting.

If `TestRunValidationHappyPath::test_minimal_valid_scenario` fails because the empty `timeline: []` trips a Pydantic check, switch to `timeline:\n  []` or omit the field (it is required per the Scenario model — keep it as `timeline: []`).

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/chaos_librarian/validation tests/validation && uv run ruff format --check src/chaos_librarian/validation tests/validation && uv run ty check src/chaos_librarian/validation tests/validation`
Expected: clean. (If ty complains about `dict` without a type parameter in the stub signatures, change `dict` to `dict[str, object]` everywhere.)

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/validation/pipeline.py src/chaos_librarian/validation/__init__.py src/chaos_librarian/validation/shape.py src/chaos_librarian/validation/semantic.py tests/validation/test_pipeline.py
git commit -m "feat(validation): add pipeline orchestrator with top-level mapping guard"
```

---

## Task 5: `validation/shape.py` (Pydantic pass)

**Files:**
- Modify: `src/chaos_librarian/validation/shape.py` (replace stub)
- Test: `tests/validation/test_shape.py`

The shape pass calls `Scenario.model_validate(raw_data)`. On `pydantic.ValidationError`, each `e.errors(include_url=False, include_context=True)` entry becomes one `ValidationIssue`:

- `error["type"]` → code via `codes.PYDANTIC_TO_CODE`, fallback `E_FIELD_SHAPE` with the original type in the message.
- `error["loc"]` → JSONPath via `codes.format_jsonpath`. Loc-walk happens inside `IssueCollector.add` (Task 4 already does this).
- `error["msg"]` → issue message.

On success, the shape pass returns `Scenario | None`. The pipeline does not currently use the parsed Scenario object (the semantic pass walks `raw_data` directly to keep line-index lookup natural); it is returned anyway so a future sprint can reuse it without rerunning Pydantic.

- [ ] **Step 1: Write failing tests**

```python
# tests/validation/test_shape.py
"""Tests for validation.shape: Pydantic ValidationError → ValidationIssue."""

from __future__ import annotations

from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.shape import run_shape_pass


def _empty_index() -> LineIndex:
    return LineIndex()


class TestShapePassMissingFields:
    """Pydantic 'missing' → E_FIELD_MISSING.

    WHY: the spec freezes scenario_id, schema_version, etc. as required;
    omitting one must surface as a clear, named issue.
    """

    def test_missing_scenario_id(self) -> None:
        raw = {"schema_version": 1}  # minimal — many fields missing
        collector = IssueCollector()
        run_shape_pass(raw, _empty_index(), collector)
        codes_emitted = {i.code for i in collector.issues}
        assert codes.E_FIELD_MISSING in codes_emitted


class TestShapePassUnknownField:
    """Pydantic 'extra_forbidden' → E_FIELD_UNKNOWN.

    WHY: ConfigDict(extra="forbid") on every model catches typos that
    would otherwise silently no-op; the code surfaces that to authors.
    """

    def test_unknown_top_level_field(self) -> None:
        raw = {
            "schema_version": 1,
            "scenario_id": "t",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": []},
            "works": [],
            "timeline": [],
            "made_up_extra_field": 1,
        }
        collector = IssueCollector()
        run_shape_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_FIELD_UNKNOWN for i in collector.issues)


class TestShapePassLiteralValue:
    """Pydantic 'literal_error' → E_FIELD_LITERAL.

    WHY: duration_scale and schema_version are closed enums; an
    out-of-range value should be cleanly named.
    """

    def test_wrong_duration_scale(self) -> None:
        raw = {
            "schema_version": 1,
            "scenario_id": "t",
            "seed": 1,
            "duration_scale": "extremely_long",  # not in Literal
            "library": {"roots": []},
            "works": [],
            "timeline": [],
        }
        collector = IssueCollector()
        run_shape_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_FIELD_LITERAL for i in collector.issues)


class TestShapePassDiscriminatorTag:
    """Pydantic 'union_tag_invalid' → E_TIMELINE_ACTION_UNKNOWN.

    WHY: a typo in a timeline event's `action:` value (e.g., `move_assets`
    instead of `move_asset`) is the most common authoring mistake;
    flagging it with a specific code keeps the message readable.
    """

    def test_unknown_action(self) -> None:
        raw = {
            "schema_version": 1,
            "scenario_id": "t",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": []},
            "works": [],
            "timeline": [
                {"id": "e1", "at": "1s", "action": "bogus_action", "target": "x"},
            ],
        }
        collector = IssueCollector()
        run_shape_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_TIMELINE_ACTION_UNKNOWN for i in collector.issues)


class TestShapePassJSONPathStripping:
    """A discriminator tag in the Pydantic loc must not appear in the JSONPath.

    WHY: the discriminator tag is an internal Pydantic detail and would
    mislead an author looking for a field named "slow_copy_commit" in
    their YAML.
    """

    def test_for_alias_under_slow_copy_commit(self) -> None:
        raw = {
            "schema_version": 1,
            "scenario_id": "t",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": []},
            "works": [],
            "timeline": [
                {
                    "id": "e1",
                    "at": "1s",
                    "action": "slow_copy_commit",
                    "for": 12345,  # wrong type — for must be str
                },
            ],
        }
        collector = IssueCollector()
        run_shape_pass(raw, _empty_index(), collector)
        paths = [i.path for i in collector.issues if i.path]
        assert any("slow_copy_commit" not in p for p in paths)
        # And the alias rewrite for_ → for is applied.
        assert any(p == "$.timeline[0].for" for p in paths)


class TestShapePassNoErrorsForValidScenario:
    """A valid raw dict produces zero issues from the shape pass.

    WHY: this is the contract; downstream semantic rules can assume
    no shape-level noise was injected for valid input.
    """

    def test_valid_scenario_produces_no_issues(self) -> None:
        raw = {
            "schema_version": 1,
            "scenario_id": "t",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "r", "path": "r"}]},
            "works": [],
            "timeline": [],
        }
        collector = IssueCollector()
        run_shape_pass(raw, _empty_index(), collector)
        assert collector.issues == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/validation/test_shape.py -v`
Expected: every test fails because the Task 4 stub does nothing.

- [ ] **Step 3: Implement `shape.py`**

```python
# src/chaos_librarian/validation/shape.py
"""Pydantic shape-validation pass.

Calls ``Scenario.model_validate`` and maps each ``ValidationError`` entry
to a ``ValidationIssue`` with a stable error code, a JSONPath, and a
line/column resolved via the ``LineIndex``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import ValidationError

from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.validation import codes

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector


def run_shape_pass(
    raw_data: dict[str, object],
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> Scenario | None:
    """Validate ``raw_data`` against the Scenario model; collect any issues.

    Returns the parsed ``Scenario`` on success, ``None`` on any error.
    """
    try:
        return Scenario.model_validate(raw_data)
    except ValidationError as e:
        for entry in e.errors(include_url=False, include_context=True):
            pydantic_type = entry["type"]
            code = codes.PYDANTIC_TO_CODE.get(pydantic_type, codes.E_FIELD_SHAPE)
            if code == codes.E_FIELD_SHAPE:
                message = f"{entry['msg']} (pydantic type: {pydantic_type})"
            else:
                message = entry["msg"]
            loc = tuple(entry["loc"])
            collector.add(
                code=code,
                severity=ValidationSeverity.ERROR,
                message=message,
                loc=loc,
                line_index=line_index,
            )
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/validation/test_shape.py -v`
Expected: all tests pass.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/chaos_librarian/validation/shape.py tests/validation/test_shape.py && uv run ruff format --check src/chaos_librarian/validation/shape.py tests/validation/test_shape.py && uv run ty check src/chaos_librarian/validation/shape.py tests/validation/test_shape.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/validation/shape.py tests/validation/test_shape.py
git commit -m "feat(validation): add Pydantic shape pass with code mapping"
```

---

## Task 6: `validation/semantic.py` framework + Rule 1 (`E_ID_DUPLICATE`, globalized)

**Files:**
- Modify: `src/chaos_librarian/validation/semantic.py` (replace stub)
- Create: `tests/validation/test_semantic.py`

This task sets up the rule-registry pattern that Tasks 7–12 extend. Each rule is a plain function `(raw, line_index, collector) -> None`. `run_semantic_pass` calls them in a fixed order. Helpers shared by multiple rules live in the same module — they are not numerous enough to warrant a separate file.

Rule 1 (the globalized version, per spec):

- Scope **global within the scenario** for: variants (across all works), bundles (across all variants), assets (across all bundles).
- Scope **top-level** for: library roots, works, timeline events.
- Namespace labels used in messages: `root_id`, `work_id`, `variant_id`, `bundle_id`, `asset_id`, `timeline_id`.
- Issue message format: `"duplicate {namespace} {id!r} (first defined at {first_path})"`.

The exit-criteria test for Codex finding #1 expects the message to contain `"asset_id"`, so this string must appear verbatim for the asset namespace.

- [ ] **Step 1: Write failing tests**

```python
# tests/validation/test_semantic.py
"""Per-rule semantic tests. One class per E_* code.

Each rule test names the WHY (per CLAUDE.md Rule 9): what would break in
downstream sprints (plan, materialize, run, journal, manifest) if this
semantic rule did not exist.
"""

from __future__ import annotations

from chaos_librarian.scenario_io import LineIndex
from chaos_librarian.validation import codes
from chaos_librarian.validation.pipeline import IssueCollector
from chaos_librarian.validation.semantic import run_semantic_pass


def _empty_index() -> LineIndex:
    return LineIndex()


def _minimal_scenario(timeline: list[dict] | None = None, **overrides) -> dict:
    """Build a minimal valid-shape scenario. Overrides can add duplicates."""
    base = {
        "schema_version": 1,
        "scenario_id": "t",
        "seed": 1,
        "duration_scale": "short",
        "library": {"roots": [{"id": "r", "path": "r"}]},
        "works": [
            {
                "id": "w",
                "title": "t",
                "variants": [
                    {
                        "id": "v",
                        "label": "l",
                        "bundle": {
                            "id": "b",
                            "assets": [
                                {
                                    "id": "a",
                                    "role": "primary_video",
                                    "container": "mkv",
                                    "duration_seconds": 1,
                                }
                            ],
                        },
                    }
                ],
            }
        ],
        "timeline": timeline or [],
    }
    base.update(overrides)
    return base


class TestRule1IdDuplicateGlobalAssets:
    """Duplicate asset IDs across different bundles are an error.

    WHY: timeline `target:` references resolve against a flat asset
    namespace (see manifest.py's ManifestAsset list); two assets sharing
    an ID would make that lookup ambiguous and would collide in
    manifest.json. Closes Codex review finding #1.
    """

    def test_duplicate_asset_id_across_bundles(self) -> None:
        raw = _minimal_scenario()
        # Add a second variant whose bundle contains an asset with the same id.
        raw["works"][0]["variants"].append(
            {
                "id": "v2",
                "label": "l2",
                "bundle": {
                    "id": "b2",
                    "assets": [
                        {
                            "id": "a",  # duplicate of works[0].variants[0].bundle.assets[0].id
                            "role": "primary_video",
                            "container": "mkv",
                            "duration_seconds": 1,
                        }
                    ],
                },
            }
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        dup_issues = [i for i in collector.issues if i.code == codes.E_ID_DUPLICATE]
        assert len(dup_issues) == 1
        assert "asset_id" in dup_issues[0].message
        assert "'a'" in dup_issues[0].message

    def test_duplicate_asset_id_within_bundle(self) -> None:
        """Per-bundle duplicates still fire — global uniqueness subsumes scoped."""
        raw = _minimal_scenario()
        raw["works"][0]["variants"][0]["bundle"]["assets"].append(
            {
                "id": "a",
                "role": "secondary_video",
                "container": "mkv",
                "duration_seconds": 1,
            }
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_ID_DUPLICATE for i in collector.issues)


class TestRule1IdDuplicateGlobalVariants:
    """Duplicate variant IDs across different works are an error.

    WHY: variants are oracle keys in the manifest (one ManifestVariant per
    id); collisions would make plan/materialize ambiguous.
    """

    def test_duplicate_variant_id_across_works(self) -> None:
        raw = _minimal_scenario()
        raw["works"].append(
            {
                "id": "w2",
                "title": "t2",
                "variants": [
                    {
                        "id": "v",  # collides with works[0].variants[0].id
                        "label": "l",
                        "bundle": {"id": "b3", "assets": []},
                    }
                ],
            }
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "variant_id" in i.message
            for i in collector.issues
        )


class TestRule1IdDuplicateGlobalBundles:
    """Duplicate bundle IDs across different variants are an error.

    WHY: bundle IDs are journal keys (ManifestBundle list); collisions
    would corrupt durable identity tracking.
    """

    def test_duplicate_bundle_id_across_variants(self) -> None:
        raw = _minimal_scenario()
        raw["works"][0]["variants"].append(
            {
                "id": "v2",
                "label": "l",
                "bundle": {"id": "b", "assets": []},  # duplicate bundle id
            }
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "bundle_id" in i.message
            for i in collector.issues
        )


class TestRule1IdDuplicateTopLevel:
    """Duplicate root_id, work_id, timeline_id at the top level are errors.

    WHY: these are flat namespaces; collisions would ambiguate references
    in subsequent semantic passes.
    """

    def test_duplicate_root_id(self) -> None:
        raw = _minimal_scenario()
        raw["library"]["roots"].append({"id": "r", "path": "r2"})
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "root_id" in i.message
            for i in collector.issues
        )

    def test_duplicate_work_id(self) -> None:
        raw = _minimal_scenario()
        raw["works"].append(
            {"id": "w", "title": "t2", "variants": []},
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "work_id" in i.message
            for i in collector.issues
        )

    def test_duplicate_timeline_id(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "e1", "at": "1s", "action": "delete_file", "target": "a"},
                {"id": "e1", "at": "2s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(
            i.code == codes.E_ID_DUPLICATE and "timeline_id" in i.message
            for i in collector.issues
        )


class TestRule1IdDuplicateNoFalsePositives:
    """A valid scenario produces zero E_ID_DUPLICATE issues.

    WHY: existing valid fixtures (identity-move-rename, version-evolution,
    bundle-sidecars, slow-copy) must remain valid. A regression here
    breaks every Sprint 1 exit-criteria check.
    """

    def test_minimal_scenario_no_duplicates(self) -> None:
        collector = IssueCollector()
        run_semantic_pass(_minimal_scenario(), _empty_index(), collector)
        assert not any(i.code == codes.E_ID_DUPLICATE for i in collector.issues)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/validation/test_semantic.py -v`
Expected: every test fails (the Task 4 semantic stub does nothing).

- [ ] **Step 3: Implement the rule framework + Rule 1**

```python
# src/chaos_librarian/validation/semantic.py
"""Semantic-validation pass.

Rules are plain functions with signature ``(raw, line_index, collector) -> None``.
They are registered in ``_RULES`` and run in declared order. Each rule
guards its own preconditions: Pydantic owns "the field exists and is the
right type"; rules only check semantics on top of well-shaped sub-trees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from chaos_librarian.contract.validation import ValidationSeverity
from chaos_librarian.validation import codes

if TYPE_CHECKING:
    from chaos_librarian.scenario_io import LineIndex
    from chaos_librarian.validation.pipeline import IssueCollector


_Rule = Callable[[dict, "LineIndex", "IssueCollector"], None]


def run_semantic_pass(
    raw_data: dict,
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> None:
    """Apply every registered rule in declared order."""
    for rule in _RULES:
        rule(raw_data, line_index, collector)


# ---- Rule 1: E_ID_DUPLICATE -----------------------------------------------


def _rule_id_duplicate(
    raw: dict,
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> None:
    """Reject duplicate IDs per the namespace table in the Sprint 1 spec.

    Global namespaces (across the whole scenario): variant_id, bundle_id,
    asset_id. Top-level namespaces: root_id, work_id, timeline_id.
    """
    # --- root_id (top-level) ---
    _check_dups(
        raw=raw,
        namespace="root_id",
        path_parts=("library", "roots"),
        line_index=line_index,
        collector=collector,
    )
    # --- work_id (top-level) ---
    _check_dups(
        raw=raw,
        namespace="work_id",
        path_parts=("works",),
        line_index=line_index,
        collector=collector,
    )
    # --- timeline_id (top-level) ---
    _check_dups(
        raw=raw,
        namespace="timeline_id",
        path_parts=("timeline",),
        line_index=line_index,
        collector=collector,
    )

    # --- variant_id, bundle_id, asset_id (global across the scenario) ---
    works = raw.get("works")
    if not isinstance(works, list):
        return

    seen_variants: dict[str, tuple[str | int, ...]] = {}
    seen_bundles: dict[str, tuple[str | int, ...]] = {}
    seen_assets: dict[str, tuple[str | int, ...]] = {}
    for w_idx, work in enumerate(works):
        if not isinstance(work, dict):
            continue
        variants = work.get("variants")
        if not isinstance(variants, list):
            continue
        for v_idx, variant in enumerate(variants):
            if not isinstance(variant, dict):
                continue
            v_id = variant.get("id")
            v_loc = ("works", w_idx, "variants", v_idx, "id")
            if isinstance(v_id, str):
                _record_or_report(
                    namespace="variant_id",
                    value=v_id,
                    loc=v_loc,
                    seen=seen_variants,
                    line_index=line_index,
                    collector=collector,
                )
            bundle = variant.get("bundle")
            if not isinstance(bundle, dict):
                continue
            b_id = bundle.get("id")
            b_loc = ("works", w_idx, "variants", v_idx, "bundle", "id")
            if isinstance(b_id, str):
                _record_or_report(
                    namespace="bundle_id",
                    value=b_id,
                    loc=b_loc,
                    seen=seen_bundles,
                    line_index=line_index,
                    collector=collector,
                )
            assets = bundle.get("assets")
            if not isinstance(assets, list):
                continue
            for a_idx, asset in enumerate(assets):
                if not isinstance(asset, dict):
                    continue
                a_id = asset.get("id")
                a_loc = (
                    "works",
                    w_idx,
                    "variants",
                    v_idx,
                    "bundle",
                    "assets",
                    a_idx,
                    "id",
                )
                if isinstance(a_id, str):
                    _record_or_report(
                        namespace="asset_id",
                        value=a_id,
                        loc=a_loc,
                        seen=seen_assets,
                        line_index=line_index,
                        collector=collector,
                    )


def _check_dups(
    *,
    raw: dict,
    namespace: str,
    path_parts: tuple[str, ...],
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> None:
    """Top-level duplicate-id check: walk one list field and report collisions."""
    node: object = raw
    for part in path_parts:
        if not isinstance(node, dict):
            return
        node = node.get(part)
    if not isinstance(node, list):
        return
    seen: dict[str, tuple[str | int, ...]] = {}
    for idx, item in enumerate(node):
        if not isinstance(item, dict):
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str):
            continue
        loc = (*path_parts, idx, "id")
        _record_or_report(
            namespace=namespace,
            value=item_id,
            loc=loc,
            seen=seen,
            line_index=line_index,
            collector=collector,
        )


def _record_or_report(
    *,
    namespace: str,
    value: str,
    loc: tuple[str | int, ...],
    seen: dict[str, tuple[str | int, ...]],
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> None:
    if value in seen:
        first_path = codes.format_jsonpath(seen[value])
        collector.add(
            code=codes.E_ID_DUPLICATE,
            severity=ValidationSeverity.ERROR,
            message=f"duplicate {namespace} {value!r} (first defined at {first_path})",
            loc=loc,
            line_index=line_index,
        )
    else:
        seen[value] = loc


# ---- Registry (Tasks 7–12 add more rules here) ----------------------------


_RULES: list[_Rule] = [
    _rule_id_duplicate,
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/validation/test_semantic.py -v`
Expected: all `TestRule1*` tests pass.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/chaos_librarian/validation/semantic.py tests/validation/test_semantic.py && uv run ruff format --check src/chaos_librarian/validation/semantic.py tests/validation/test_semantic.py && uv run ty check src/chaos_librarian/validation/semantic.py tests/validation/test_semantic.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/validation/semantic.py tests/validation/test_semantic.py
git commit -m "feat(validation): add semantic rule framework + Rule 1 (E_ID_DUPLICATE globalized)"
```

---

## Task 7: Rule 2 (`E_PATH_DUPLICATE`)

**Files:**
- Modify: `src/chaos_librarian/validation/semantic.py` (add rule + register)
- Modify: `tests/validation/test_semantic.py` (append class)

Rule 2: no two `library.roots` share the same `path`. **WARNING** severity (per spec); does not flip `report.ok`.

- [ ] **Step 1: Write failing test**

Append to `tests/validation/test_semantic.py`:

```python
class TestRule2PathDuplicate:
    """Two library roots sharing the same path emit a WARNING, not an ERROR.

    WHY: duplicate paths under distinct IDs are well-defined (alias) but
    almost always a typo; flagging without flipping ok lets validate
    still pass on legitimate aliases.
    """

    def test_warning_severity_no_exit_flip(self) -> None:
        raw = _minimal_scenario()
        raw["library"]["roots"].append({"id": "r2", "path": "r"})  # same path
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        warnings = [i for i in collector.issues if i.code == codes.E_PATH_DUPLICATE]
        assert len(warnings) == 1
        assert warnings[0].severity.value == "warning"

    def test_distinct_paths_no_warning(self) -> None:
        raw = _minimal_scenario()
        raw["library"]["roots"].append({"id": "r2", "path": "r2"})
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_PATH_DUPLICATE for i in collector.issues)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/validation/test_semantic.py::TestRule2PathDuplicate -v`
Expected: `test_warning_severity_no_exit_flip` fails (no warning emitted).

- [ ] **Step 3: Implement Rule 2**

Append to `src/chaos_librarian/validation/semantic.py` (above `_RULES`):

```python
# ---- Rule 2: E_PATH_DUPLICATE ---------------------------------------------


def _rule_path_duplicate(
    raw: dict,
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> None:
    """Warn on two library roots with the same ``path`` (distinct IDs).

    WARNING severity — does not flip ``report.ok``. Authors who genuinely
    want to alias a directory under two ID namespaces can ignore it.
    """
    library = raw.get("library")
    if not isinstance(library, dict):
        return
    roots = library.get("roots")
    if not isinstance(roots, list):
        return
    seen: dict[str, tuple[str | int, ...]] = {}
    for idx, root in enumerate(roots):
        if not isinstance(root, dict):
            continue
        path = root.get("path")
        if not isinstance(path, str):
            continue
        loc = ("library", "roots", idx, "path")
        if path in seen:
            first_path = codes.format_jsonpath(seen[path])
            collector.add(
                code=codes.E_PATH_DUPLICATE,
                severity=ValidationSeverity.WARNING,
                message=f"root path {path!r} already used at {first_path}",
                loc=loc,
                line_index=line_index,
            )
        else:
            seen[path] = loc
```

And register: change `_RULES` to:

```python
_RULES: list[_Rule] = [
    _rule_id_duplicate,
    _rule_path_duplicate,
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/validation/test_semantic.py -v`
Expected: all rule 1 + rule 2 tests pass.

- [ ] **Step 5: Lint and type-check**

Run: `uv run ruff check src/chaos_librarian/validation/semantic.py tests/validation/test_semantic.py && uv run ty check src/chaos_librarian/validation/semantic.py tests/validation/test_semantic.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/validation/semantic.py tests/validation/test_semantic.py
git commit -m "feat(validation): add Rule 2 (E_PATH_DUPLICATE warning on root path aliases)"
```

---

## Task 8: Rule 3 (`E_DURATION_SYNTAX`)

**Files:**
- Modify: `src/chaos_librarian/validation/semantic.py`
- Modify: `tests/validation/test_semantic.py`

Rule 3: every `timeline[*].at` and `slow_copy_start.duration` parses via `clock.parse_duration`. Emit one `E_DURATION_SYNTAX` per bad string with the parser's reason in the message.

- [ ] **Step 1: Write failing tests**

Append to `tests/validation/test_semantic.py`:

```python
class TestRule3DurationSyntax:
    """Every duration string in the timeline must parse.

    WHY: bad durations silently coerce to 0 or crash downstream when
    the journal converts them to logical_time_ns; flagging here keeps
    the contract of "validated scenarios always have parseable times."
    """

    def test_bad_at_field(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "e1", "at": "not-a-duration", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_DURATION_SYNTAX for i in collector.issues)

    def test_bad_slow_copy_duration(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "bogus",  # parse failure
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(
            i.code == codes.E_DURATION_SYNTAX and "duration" in (i.path or "")
            for i in collector.issues
        )

    def test_valid_durations_no_issues(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "e1", "at": "1s", "action": "delete_file", "target": "a"},
                {"id": "e2", "at": "1m30s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_DURATION_SYNTAX for i in collector.issues)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/validation/test_semantic.py::TestRule3DurationSyntax -v`
Expected: fails.

- [ ] **Step 3: Implement Rule 3**

Append to `semantic.py` (before `_RULES`):

```python
# ---- Rule 3: E_DURATION_SYNTAX --------------------------------------------


def _rule_duration_syntax(
    raw: dict,
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> None:
    """Reject unparseable duration strings on timeline events.

    Fields checked: ``timeline[*].at`` (every event) and
    ``slow_copy_start.duration`` (only when ``action == "slow_copy_start"``).
    """
    from chaos_librarian.clock import DurationParseError, parse_duration

    timeline = raw.get("timeline")
    if not isinstance(timeline, list):
        return
    for idx, event in enumerate(timeline):
        if not isinstance(event, dict):
            continue
        at = event.get("at")
        if isinstance(at, str):
            try:
                parse_duration(at)
            except DurationParseError as e:
                collector.add(
                    code=codes.E_DURATION_SYNTAX,
                    severity=ValidationSeverity.ERROR,
                    message=f"invalid at duration {at!r}: {e.reason}",
                    loc=("timeline", idx, "at"),
                    line_index=line_index,
                )
        if event.get("action") == "slow_copy_start":
            duration = event.get("duration")
            if isinstance(duration, str):
                try:
                    parse_duration(duration)
                except DurationParseError as e:
                    collector.add(
                        code=codes.E_DURATION_SYNTAX,
                        severity=ValidationSeverity.ERROR,
                        message=f"invalid duration {duration!r}: {e.reason}",
                        loc=("timeline", idx, "duration"),
                        line_index=line_index,
                    )
```

Move the `from chaos_librarian.clock import ...` to module top to satisfy ruff `E402` and avoid the import-inside-function pattern:

```python
# at the top of semantic.py, after the existing imports
from chaos_librarian.clock import DurationParseError, parse_duration
```

…and drop the inline import from `_rule_duration_syntax`.

Register:

```python
_RULES: list[_Rule] = [
    _rule_id_duplicate,
    _rule_path_duplicate,
    _rule_duration_syntax,
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/validation/test_semantic.py -v`
Expected: all rules 1–3 tests pass.

- [ ] **Step 5: Lint and type-check + commit**

Run: `uv run ruff check src/chaos_librarian/validation/semantic.py && uv run ty check src/chaos_librarian/validation/semantic.py`
Expected: clean.

```bash
git add src/chaos_librarian/validation/semantic.py tests/validation/test_semantic.py
git commit -m "feat(validation): add Rule 3 (E_DURATION_SYNTAX)"
```

---

## Task 9: Rule 4 (`E_TARGET_UNKNOWN`)

**Files:**
- Modify: `src/chaos_librarian/validation/semantic.py`
- Modify: `tests/validation/test_semantic.py`

Rule 4: every `timeline[*].target` must resolve to an `asset.id` defined in `works[*].variants[*].bundle.assets[*]`. The 9 timeline event variants: all except `slow_copy_commit` carry a `target:`.

Build the set of known asset IDs from a single pass over works; then check each timeline event's `target` against it.

- [ ] **Step 1: Write failing tests**

```python
class TestRule4TargetUnknown:
    """Every timeline target: must resolve to a real asset id.

    WHY: an unresolved target would crash the materializer at runtime;
    catching it at validate avoids polluting the journal with a half-
    applied event.
    """

    def test_unknown_target(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "e1", "at": "1s", "action": "delete_file", "target": "ghost"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(
            i.code == codes.E_TARGET_UNKNOWN and "ghost" in i.message
            for i in collector.issues
        )

    def test_known_target_passes(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "e1", "at": "1s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_TARGET_UNKNOWN for i in collector.issues)

    def test_slow_copy_commit_has_no_target_so_no_check(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "1s",
                },
                {"id": "c1", "at": "2s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_TARGET_UNKNOWN for i in collector.issues)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/validation/test_semantic.py::TestRule4TargetUnknown -v`
Expected: fails.

- [ ] **Step 3: Implement Rule 4**

```python
# ---- Rule 4: E_TARGET_UNKNOWN ---------------------------------------------


def _rule_target_unknown(
    raw: dict,
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> None:
    """Reject timeline events whose ``target:`` is not a defined asset id."""
    asset_ids = _collect_asset_ids(raw)
    timeline = raw.get("timeline")
    if not isinstance(timeline, list):
        return
    for idx, event in enumerate(timeline):
        if not isinstance(event, dict):
            continue
        target = event.get("target")
        if not isinstance(target, str):
            continue  # slow_copy_commit has no target; Pydantic owns shape
        if target not in asset_ids:
            collector.add(
                code=codes.E_TARGET_UNKNOWN,
                severity=ValidationSeverity.ERROR,
                message=f"target asset {target!r} is not defined in any bundle",
                loc=("timeline", idx, "target"),
                line_index=line_index,
            )


def _collect_asset_ids(raw: dict) -> set[str]:
    """Return every defined ``works[*].variants[*].bundle.assets[*].id``."""
    result: set[str] = set()
    works = raw.get("works")
    if not isinstance(works, list):
        return result
    for work in works:
        if not isinstance(work, dict):
            continue
        variants = work.get("variants")
        if not isinstance(variants, list):
            continue
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            bundle = variant.get("bundle")
            if not isinstance(bundle, dict):
                continue
            assets = bundle.get("assets")
            if not isinstance(assets, list):
                continue
            for asset in assets:
                if isinstance(asset, dict) and isinstance(asset.get("id"), str):
                    result.add(asset["id"])
    return result
```

Register:

```python
_RULES: list[_Rule] = [
    _rule_id_duplicate,
    _rule_path_duplicate,
    _rule_duration_syntax,
    _rule_target_unknown,
]
```

- [ ] **Step 4: Run tests, lint, commit**

```bash
uv run pytest tests/validation/test_semantic.py -v
uv run ruff check src/chaos_librarian/validation/semantic.py && uv run ty check src/chaos_librarian/validation/semantic.py
git add src/chaos_librarian/validation/semantic.py tests/validation/test_semantic.py
git commit -m "feat(validation): add Rule 4 (E_TARGET_UNKNOWN)"
```

---

## Task 10: Rules 5a + 5b (`E_SLOW_COPY_UNPAIRED`, `E_SLOW_COPY_TIMING`)

**Files:**
- Modify: `src/chaos_librarian/validation/semantic.py`
- Modify: `tests/validation/test_semantic.py`

5a (structural): every `slow_copy_commit.for` references an existing `slow_copy_start.id`; every start has exactly one matching commit. Commit-without-start = orphan commit; start without commit = orphan start; multiple commits referencing the same start = ambiguous commit.

5b (timing, strict equality): for each matched pair, `parse_duration(commit.at) == parse_duration(start.at) + parse_duration(start.duration)`. Preconditions: all three strings parseable (else Rule 3 already flagged) AND Rule 5a did not fire for this pair.

- [ ] **Step 1: Write failing tests**

```python
class TestRule5aSlowCopyUnpaired:
    """Structural pairing for slow_copy_start / slow_copy_commit.

    WHY: an orphan commit applies nothing (the temp file does not exist);
    an orphan start leaves a permanent temp file in the library.
    """

    def test_commit_without_start(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "c1", "at": "1s", "action": "slow_copy_commit", "for": "ghost"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_SLOW_COPY_UNPAIRED for i in collector.issues)

    def test_start_without_commit(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "1s",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_SLOW_COPY_UNPAIRED for i in collector.issues)

    def test_two_commits_for_one_start(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "1s",
                },
                {"id": "c1", "at": "2s", "action": "slow_copy_commit", "for": "s1"},
                {"id": "c2", "at": "3s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_SLOW_COPY_UNPAIRED for i in collector.issues)

    def test_correctly_paired_no_issue(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "3s",
                },
                {"id": "c1", "at": "4s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_SLOW_COPY_UNPAIRED for i in collector.issues)


class TestRule5bSlowCopyTiming:
    """For each matched pair, commit.at must equal start.at + start.duration.

    WHY: the design spec says the temp file is "grown over the declared
    duration: between the two events." Any drift would mean either an
    idle gap (commit too late) or premature commit (impossible). Closes
    Codex review finding #2.
    """

    def test_commit_too_early_is_error(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "3s",
                },
                {"id": "c1", "at": "3s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_SLOW_COPY_TIMING for i in collector.issues)

    def test_commit_too_late_is_error(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "3s",
                },
                {"id": "c1", "at": "5s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_SLOW_COPY_TIMING for i in collector.issues)

    def test_exact_match_no_issue(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "3s",
                },
                {"id": "c1", "at": "4s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_SLOW_COPY_TIMING for i in collector.issues)

    def test_skipped_when_durations_unparseable(self) -> None:
        """Rule 3 already flags; Rule 5b must not double-report."""
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "bogus",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "x",
                    "temp_path": "x.part",
                    "duration": "3s",
                },
                {"id": "c1", "at": "4s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_SLOW_COPY_TIMING for i in collector.issues)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/validation/test_semantic.py::TestRule5aSlowCopyUnpaired tests/validation/test_semantic.py::TestRule5bSlowCopyTiming -v`
Expected: fails.

- [ ] **Step 3: Implement Rules 5a + 5b**

```python
# ---- Rules 5a + 5b: slow-copy pairing and timing --------------------------


def _rule_slow_copy_unpaired(
    raw: dict,
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> None:
    """5a: structural pairing of slow_copy_start ↔ slow_copy_commit."""
    timeline = raw.get("timeline")
    if not isinstance(timeline, list):
        return
    starts: dict[str, tuple[int, dict]] = {}  # id -> (idx, event)
    commits: list[tuple[int, dict]] = []
    for idx, event in enumerate(timeline):
        if not isinstance(event, dict):
            continue
        action = event.get("action")
        ev_id = event.get("id")
        if action == "slow_copy_start" and isinstance(ev_id, str):
            starts[ev_id] = (idx, event)
        elif action == "slow_copy_commit":
            commits.append((idx, event))

    commits_per_start: dict[str, int] = {sid: 0 for sid in starts}
    for c_idx, commit in commits:
        ref = commit.get("for")
        if not isinstance(ref, str):
            continue  # Pydantic owns shape
        if ref not in starts:
            collector.add(
                code=codes.E_SLOW_COPY_UNPAIRED,
                severity=ValidationSeverity.ERROR,
                message=f"slow_copy_commit references unknown slow_copy_start {ref!r}",
                loc=("timeline", c_idx, "for"),
                line_index=line_index,
            )
            continue
        commits_per_start[ref] += 1

    for sid, count in commits_per_start.items():
        s_idx, _ = starts[sid]
        if count == 0:
            collector.add(
                code=codes.E_SLOW_COPY_UNPAIRED,
                severity=ValidationSeverity.ERROR,
                message=f"slow_copy_start {sid!r} has no matching slow_copy_commit",
                loc=("timeline", s_idx, "id"),
                line_index=line_index,
            )
        elif count > 1:
            collector.add(
                code=codes.E_SLOW_COPY_UNPAIRED,
                severity=ValidationSeverity.ERROR,
                message=f"slow_copy_start {sid!r} has {count} matching commits (expected 1)",
                loc=("timeline", s_idx, "id"),
                line_index=line_index,
            )


def _rule_slow_copy_timing(
    raw: dict,
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> None:
    """5b: strict equality ``commit.at == start.at + start.duration``.

    Preconditions: durations on both events parse (Rule 3 already flagged
    otherwise) AND structural pairing holds (Rule 5a already flagged
    orphans). Skipping here prevents double-reporting.
    """
    timeline = raw.get("timeline")
    if not isinstance(timeline, list):
        return
    starts: dict[str, tuple[int, dict]] = {}
    for idx, event in enumerate(timeline):
        if isinstance(event, dict) and event.get("action") == "slow_copy_start":
            sid = event.get("id")
            if isinstance(sid, str):
                starts[sid] = (idx, event)

    for c_idx, commit in enumerate(timeline):
        if not isinstance(commit, dict) or commit.get("action") != "slow_copy_commit":
            continue
        ref = commit.get("for")
        if not isinstance(ref, str) or ref not in starts:
            continue  # Rule 5a flagged orphan
        _, start = starts[ref]
        try:
            start_at_ns = parse_duration(str(start.get("at")))
            start_dur_ns = parse_duration(str(start.get("duration")))
            commit_at_ns = parse_duration(str(commit.get("at")))
        except DurationParseError:
            continue  # Rule 3 flagged
        expected = start_at_ns + start_dur_ns
        if commit_at_ns != expected:
            collector.add(
                code=codes.E_SLOW_COPY_TIMING,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"slow_copy_commit.at {commit.get('at')!r} != "
                    f"start.at {start.get('at')!r} + duration {start.get('duration')!r}"
                ),
                loc=("timeline", c_idx, "at"),
                line_index=line_index,
            )
```

Register:

```python
_RULES: list[_Rule] = [
    _rule_id_duplicate,
    _rule_path_duplicate,
    _rule_duration_syntax,
    _rule_target_unknown,
    _rule_slow_copy_unpaired,
    _rule_slow_copy_timing,
]
```

- [ ] **Step 4: Run tests, lint, commit**

```bash
uv run pytest tests/validation/test_semantic.py -v
uv run ruff check src/chaos_librarian/validation/semantic.py && uv run ty check src/chaos_librarian/validation/semantic.py
git add src/chaos_librarian/validation/semantic.py tests/validation/test_semantic.py
git commit -m "feat(validation): add Rules 5a/5b (slow-copy pairing and strict-equality timing)"
```

---

## Task 11: Rule 6 (`E_PATH_CONTAINMENT`)

**Files:**
- Modify: `src/chaos_librarian/validation/semantic.py`
- Modify: `tests/validation/test_semantic.py`

Rule 6: every `library.roots[*].path`, every `to:` field, every `temp_path:` must pass `paths.resolve_under_library(candidate, synthetic_root)`. Synthetic root: `Path("/__chaos_librarian_validate__/library")`. The containment helper's structural checks (absolute-path rejection, `..` escape, empty-path rejection) do not depend on the root existing.

Fields per event variant carrying paths:
- `move_asset.to`, `rename_file.to`, `add_file.to`, `create_sidecar.to`, `slow_copy_start.to`, `slow_copy_start.temp_path`

(`delete_file`, `reencode_*`, `slow_copy_commit` carry no paths.)

- [ ] **Step 1: Write failing tests**

```python
class TestRule6PathContainment:
    """Every scenario path must pass the containment helper.

    WHY: a path that resolves outside the library root is a filesystem-
    safety violation; the runtime (plan/materialize) would refuse to
    write there. Catching at validate prevents partial runs.
    """

    def test_absolute_root_path_rejected(self) -> None:
        raw = _minimal_scenario()
        raw["library"]["roots"][0]["path"] = "/etc/passwd"
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)

    def test_dotdot_escape_in_to(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "e1",
                    "at": "1s",
                    "action": "rename_file",
                    "target": "a",
                    "to": "../../etc/passwd",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)

    def test_temp_path_checked(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "s1",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a",
                    "to": "movies/x.mkv",
                    "temp_path": "/tmp/x.part",  # absolute — rejected
                    "duration": "1s",
                },
                {"id": "c1", "at": "2s", "action": "slow_copy_commit", "for": "s1"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        # at least one E_PATH_CONTAINMENT against the temp_path
        assert any(
            i.code == codes.E_PATH_CONTAINMENT and "temp_path" in (i.path or "")
            for i in collector.issues
        )

    def test_valid_relative_paths_no_issue(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {
                    "id": "e1",
                    "at": "1s",
                    "action": "rename_file",
                    "target": "a",
                    "to": "movies-hd/Foo.mkv",
                },
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_PATH_CONTAINMENT for i in collector.issues)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/validation/test_semantic.py::TestRule6PathContainment -v`
Expected: fails.

- [ ] **Step 3: Implement Rule 6**

Add to top imports in `semantic.py`:

```python
from pathlib import Path

from chaos_librarian.contract.paths import PathContainmentError, resolve_under_library
```

```python
# ---- Rule 6: E_PATH_CONTAINMENT -------------------------------------------


_SYNTHETIC_LIBRARY_ROOT: Path = Path("/__chaos_librarian_validate__/library")

# Per-action-variant path field names. Pulled from contract/scenario.py.
_PATH_FIELDS_BY_ACTION: dict[str, tuple[str, ...]] = {
    "move_asset": ("to",),
    "rename_file": ("to",),
    "add_file": ("to",),
    "create_sidecar": ("to",),
    "slow_copy_start": ("to", "temp_path"),
}


def _rule_path_containment(
    raw: dict,
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> None:
    """Reject paths that violate library-root containment.

    Uses ``contract.paths.resolve_under_library`` against a synthetic
    absolute root. The helper's structural checks (absolute, ``..``,
    empty) do not require the root to exist on the filesystem.
    """
    # library.roots[*].path
    library = raw.get("library")
    if isinstance(library, dict):
        roots = library.get("roots")
        if isinstance(roots, list):
            for idx, root in enumerate(roots):
                if not isinstance(root, dict):
                    continue
                path = root.get("path")
                if isinstance(path, str):
                    _check_containment(
                        path,
                        loc=("library", "roots", idx, "path"),
                        line_index=line_index,
                        collector=collector,
                    )

    # timeline[*].(to|temp_path)
    timeline = raw.get("timeline")
    if not isinstance(timeline, list):
        return
    for idx, event in enumerate(timeline):
        if not isinstance(event, dict):
            continue
        action = event.get("action")
        if not isinstance(action, str):
            continue
        fields = _PATH_FIELDS_BY_ACTION.get(action, ())
        for field_name in fields:
            value = event.get(field_name)
            if isinstance(value, str):
                _check_containment(
                    value,
                    loc=("timeline", idx, field_name),
                    line_index=line_index,
                    collector=collector,
                )


def _check_containment(
    raw_path: str,
    *,
    loc: tuple[str | int, ...],
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> None:
    try:
        resolve_under_library(Path(raw_path), _SYNTHETIC_LIBRARY_ROOT)
    except PathContainmentError as e:
        collector.add(
            code=codes.E_PATH_CONTAINMENT,
            severity=ValidationSeverity.ERROR,
            message=str(e),
            loc=loc,
            line_index=line_index,
        )
```

Register:

```python
_RULES: list[_Rule] = [
    _rule_id_duplicate,
    _rule_path_duplicate,
    _rule_duration_syntax,
    _rule_target_unknown,
    _rule_slow_copy_unpaired,
    _rule_slow_copy_timing,
    _rule_path_containment,
]
```

- [ ] **Step 4: Run tests, lint, commit**

```bash
uv run pytest tests/validation/test_semantic.py -v
uv run ruff check src/chaos_librarian/validation/semantic.py && uv run ty check src/chaos_librarian/validation/semantic.py
git add src/chaos_librarian/validation/semantic.py tests/validation/test_semantic.py
git commit -m "feat(validation): add Rule 6 (E_PATH_CONTAINMENT)"
```

---

## Task 12: Rule 7 (`E_TIMELINE_ORDER`)

**Files:**
- Modify: `src/chaos_librarian/validation/semantic.py`
- Modify: `tests/validation/test_semantic.py`

Rule 7: timeline `at:` values are non-decreasing (ties allowed). Skip pairs where either value is unparseable (Rule 3 already flagged).

- [ ] **Step 1: Write failing tests**

```python
class TestRule7TimelineOrder:
    """Timeline at: values must be non-decreasing.

    WHY: the design spec says events with the same at: apply in declared
    order. A scenario that goes backwards in time would either crash the
    materializer or produce a journal whose logical_time_ns is non-
    monotonic — both make replay impossible.
    """

    def test_out_of_order_flagged(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "e1", "at": "5s", "action": "delete_file", "target": "a"},
                {"id": "e2", "at": "1s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert any(i.code == codes.E_TIMELINE_ORDER for i in collector.issues)

    def test_ties_allowed(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "e1", "at": "1s", "action": "delete_file", "target": "a"},
                {"id": "e2", "at": "1s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        assert not any(i.code == codes.E_TIMELINE_ORDER for i in collector.issues)

    def test_unparseable_skipped(self) -> None:
        raw = _minimal_scenario(
            timeline=[
                {"id": "e1", "at": "bogus", "action": "delete_file", "target": "a"},
                {"id": "e2", "at": "1s", "action": "delete_file", "target": "a"},
            ],
        )
        collector = IssueCollector()
        run_semantic_pass(raw, _empty_index(), collector)
        # Rule 3 fires; Rule 7 must not double-report.
        assert not any(i.code == codes.E_TIMELINE_ORDER for i in collector.issues)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/validation/test_semantic.py::TestRule7TimelineOrder -v`
Expected: fails.

- [ ] **Step 3: Implement Rule 7**

```python
# ---- Rule 7: E_TIMELINE_ORDER ---------------------------------------------


def _rule_timeline_order(
    raw: dict,
    line_index: "LineIndex",
    collector: "IssueCollector",
) -> None:
    """Reject timeline events whose ``at:`` is earlier than the previous one.

    Ties are allowed. Pairs where either ``at:`` is unparseable are
    skipped (Rule 3 already flagged the unparseable string).
    """
    timeline = raw.get("timeline")
    if not isinstance(timeline, list):
        return
    last_ns: int | None = None
    last_idx: int = -1
    for idx, event in enumerate(timeline):
        if not isinstance(event, dict):
            continue
        at = event.get("at")
        if not isinstance(at, str):
            continue
        try:
            at_ns = parse_duration(at)
        except DurationParseError:
            continue
        if last_ns is not None and at_ns < last_ns:
            collector.add(
                code=codes.E_TIMELINE_ORDER,
                severity=ValidationSeverity.ERROR,
                message=(
                    f"timeline event at {at!r} precedes previous event "
                    f"at index {last_idx}"
                ),
                loc=("timeline", idx, "at"),
                line_index=line_index,
            )
        last_ns = at_ns
        last_idx = idx
```

Register:

```python
_RULES: list[_Rule] = [
    _rule_id_duplicate,
    _rule_path_duplicate,
    _rule_duration_syntax,
    _rule_target_unknown,
    _rule_slow_copy_unpaired,
    _rule_slow_copy_timing,
    _rule_path_containment,
    _rule_timeline_order,
]
```

- [ ] **Step 4: Run tests, lint, commit**

```bash
uv run pytest tests/validation/test_semantic.py -v
uv run ruff check src/chaos_librarian/validation/semantic.py && uv run ty check src/chaos_librarian/validation/semantic.py
git add src/chaos_librarian/validation/semantic.py tests/validation/test_semantic.py
git commit -m "feat(validation): add Rule 7 (E_TIMELINE_ORDER)"
```

---

## Task 13: CLI wiring + `_render_human` + update existing tests

**Files:**
- Modify: `src/chaos_librarian/cli/app.py` (replace `_stub("validate")` body, add `_render_human`)
- Modify: `tests/cli/test_app.py` (delete `test_validate_stub_with_valid_scenario_exits_one`)
- Create: `tests/cli/test_validate.py`

The CLI command becomes a thin shell that calls `run_validation`, dumps JSON or a human-readable table, and exits 0 or 3.

The existing `test_validate_stub_with_valid_scenario_exits_one` test (tests/cli/test_app.py:58–62) expects exit 1 for an empty file. After this task, an empty file emits `E_TOP_LEVEL_NOT_MAPPING` and exits 3. Delete the test — its purpose (gate the stub) is moot once validate is real.

`_render_human` formats issues as severity-colored aligned rows. Colors only when `sys.stdout.isatty()` (so test output stays plain).

- [ ] **Step 1: Write failing tests**

Create `tests/cli/test_validate.py`:

```python
# tests/cli/test_validate.py
"""End-to-end tests for the validate CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _write(tmp_path: Path, content: str, name: str = "s.yaml") -> Path:
    p = tmp_path / name
    p.write_text(content)
    return p


class TestValidateExitCodes:
    """Valid scenarios exit 0; any error-severity issue exits 3.

    WHY: the exit code is the contract surface for CI gates and agentic
    scripting. JSON output is also stable; humans get a separate format.
    """

    def test_valid_fixture_exits_zero(self) -> None:
        result = runner.invoke(
            app, ["validate", str(FIXTURE_DIR / "identity-move-rename.yaml")]
        )
        assert result.exit_code == 0, result.stdout + result.stderr

    def test_invalid_scenario_exits_three(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "42\n")  # top-level scalar → E_TOP_LEVEL_NOT_MAPPING
        result = runner.invoke(app, ["validate", str(path)])
        assert result.exit_code == 3


class TestValidateJSONShape:
    """``--json`` emits a ValidationReport-shaped JSON object.

    WHY: voom-v2 and agentic tooling consume this output; the shape is
    frozen by ``schemas/validation.schema.json``.
    """

    def test_json_for_valid_scenario(self) -> None:
        result = runner.invoke(
            app, ["validate", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--json"]
        )
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["ok"] is True
        assert payload["scenario_id"] == "identity-move-rename"
        assert payload["issues"] == []

    def test_json_for_invalid_scenario(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "42\n")
        result = runner.invoke(app, ["validate", str(path), "--json"])
        assert result.exit_code == 3
        payload = json.loads(result.stdout)
        assert payload["ok"] is False
        assert any(i["code"] == "E_TOP_LEVEL_NOT_MAPPING" for i in payload["issues"])


class TestValidateHumanOutput:
    """Default (no ``--json``) emits a human-readable report.

    WHY: this is the interactive format; format may change but presence
    of basic columns (status, code, message) should not.
    """

    def test_human_for_valid_scenario(self) -> None:
        result = runner.invoke(
            app, ["validate", str(FIXTURE_DIR / "identity-move-rename.yaml")]
        )
        assert result.exit_code == 0
        assert "identity-move-rename" in result.stdout
        assert "OK" in result.stdout

    def test_human_for_invalid_scenario(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "42\n")
        result = runner.invoke(app, ["validate", str(path)])
        assert result.exit_code == 3
        assert "FAIL" in result.stdout
        assert "E_TOP_LEVEL_NOT_MAPPING" in result.stdout
```

- [ ] **Step 2: Delete the stub test in `tests/cli/test_app.py`**

Remove the body of `test_validate_stub_with_valid_scenario_exits_one` (lines 58–62 in the current file). This test is now obsolete — validate is no longer a stub.

```python
# Delete this entire function from tests/cli/test_app.py:
def test_validate_stub_with_valid_scenario_exits_one(tmp_path: Path) -> None:
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("")
    result = runner.invoke(app, ["validate", str(scenario)])
    assert result.exit_code == 1
```

The existing `TestValidatePathValidation` class (rejecting missing files / directories with exit 2) stays — its assertions about Typer-level path checks remain correct.

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/cli/test_validate.py tests/cli/test_app.py -v`
Expected: `tests/cli/test_validate.py` tests fail (validate is still a stub). `tests/cli/test_app.py` passes (the obsolete test is gone).

- [ ] **Step 4: Implement CLI wiring**

Add these imports to the top of `src/chaos_librarian/cli/app.py` (alongside the existing `typer` import):

```python
from chaos_librarian.contract.validation import ValidationReport, ValidationSeverity
from chaos_librarian.validation import run_validation
```

Replace the existing `validate` function body (currently calls `_stub("validate")`) with:

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

Add the private renderer at the bottom of the file (after the last `@app.command()`):

```python
_SEVERITY_LABEL = {
    ValidationSeverity.ERROR: "ERROR",
    ValidationSeverity.WARNING: "WARN ",
    ValidationSeverity.INFO: "INFO ",
}


def _render_human(report: ValidationReport) -> None:
    status = "OK" if report.ok else f"FAIL ({len(report.issues)} issues)"
    typer.echo(f"scenario: {report.scenario_id}")
    typer.echo(f"status: {status}")
    if not report.issues:
        return
    typer.echo("")
    for issue in report.issues:
        label = _SEVERITY_LABEL[issue.severity]
        location = (
            f"line {issue.line}:{issue.column}"
            if issue.line is not None and issue.column is not None
            else ""
        )
        path = issue.path or ""
        typer.echo(
            f"{label}  {issue.code:<25} {path:<35} {location:<14} {issue.message}"
        )
```

No colorization in Sprint 1 — the spec says human output is non-stable, and uncolored output also keeps `typer.testing.CliRunner` output assertions simple.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/cli -v`
Expected: every CLI test passes.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check src/chaos_librarian/cli tests/cli && uv run ruff format --check src/chaos_librarian/cli tests/cli && uv run ty check src/chaos_librarian/cli tests/cli`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_validate.py tests/cli/test_app.py
git commit -m "feat(cli): wire validate command to run_validation pipeline"
```

---

## Task 14: Invalid fixture corpus + parametrized invalid-corpus test + valid-fixture smoke

**Files:**
- Create: `tests/fixtures/scenarios/invalid/<13 files>.yaml`
- Create: `tests/validation/test_invalid_corpus.py`

The 13 invalid fixtures (10 from the original Sprint 1 design + 3 added by the Codex review followup). Each fixture is the smallest reproducer for one error code; first line of each file is a YAML comment naming the expected code.

The parametrized test walks `invalid/`, parses the leading `# expected: E_*` comment, runs `validate`, and asserts the report contains at least one issue with that code AND `ok=False`. Smallest-reproducer + at-least-one keeps the suite robust as the code set grows.

A complementary `test_valid_fixtures_produce_no_errors` runs every top-level fixture in `tests/fixtures/scenarios/*.yaml` through `run_validation` and asserts `ok=True` with zero issues.

- [ ] **Step 1: Author the 13 invalid fixtures**

Run: `mkdir -p tests/fixtures/scenarios/invalid`

Then create each file. Every fixture begins with `# expected: E_<CODE>` so the parametrized test can extract it.

**File: `tests/fixtures/scenarios/invalid/yaml-parse-error.yaml`**
```yaml
# expected: E_YAML_PARSE
schema_version: 1
scenario_id: bad
seed: 1
duration_scale: short
library:
  roots: [
```

**File: `tests/fixtures/scenarios/invalid/missing-required-field.yaml`**
```yaml
# expected: E_FIELD_MISSING
schema_version: 1
seed: 1
duration_scale: short
library:
  roots: []
works: []
timeline: []
# scenario_id intentionally missing
```

**File: `tests/fixtures/scenarios/invalid/unknown-field.yaml`**
```yaml
# expected: E_FIELD_UNKNOWN
schema_version: 1
scenario_id: bad
seed: 1
duration_scale: short
library:
  roots: []
works: []
timeline: []
made_up_field: 1
```

**File: `tests/fixtures/scenarios/invalid/unknown-action.yaml`**
```yaml
# expected: E_TIMELINE_ACTION_UNKNOWN
schema_version: 1
scenario_id: bad
seed: 1
duration_scale: short
library:
  roots: []
works: []
timeline:
  - id: e1
    at: 1s
    action: bogus_action
    target: x
```

**File: `tests/fixtures/scenarios/invalid/bad-duration.yaml`**
```yaml
# expected: E_DURATION_SYNTAX
schema_version: 1
scenario_id: bad
seed: 1
duration_scale: short
library:
  roots:
    - id: r
      path: r
works:
  - id: w
    title: t
    variants:
      - id: v
        label: l
        bundle:
          id: b
          assets:
            - id: a
              role: primary_video
              container: mkv
              duration_seconds: 1
timeline:
  - id: e1
    at: not-a-duration
    action: delete_file
    target: a
```

**File: `tests/fixtures/scenarios/invalid/duplicate-asset-id.yaml`**
```yaml
# expected: E_ID_DUPLICATE
schema_version: 1
scenario_id: bad
seed: 1
duration_scale: short
library:
  roots:
    - id: r
      path: r
works:
  - id: w
    title: t
    variants:
      - id: v
        label: l
        bundle:
          id: b
          assets:
            - id: a
              role: primary_video
              container: mkv
              duration_seconds: 1
            - id: a
              role: secondary_video
              container: mkv
              duration_seconds: 1
timeline: []
```

**File: `tests/fixtures/scenarios/invalid/duplicate-asset-id-cross-bundle.yaml`**
```yaml
# expected: E_ID_DUPLICATE
schema_version: 1
scenario_id: bad
seed: 1
duration_scale: short
library:
  roots:
    - id: r
      path: r
works:
  - id: w
    title: t
    variants:
      - id: v1
        label: l1
        bundle:
          id: b1
          assets:
            - id: main
              role: primary_video
              container: mkv
              duration_seconds: 1
      - id: v2
        label: l2
        bundle:
          id: b2
          assets:
            - id: main  # collides with b1's asset id across bundles
              role: primary_video
              container: mkv
              duration_seconds: 1
timeline: []
```

**File: `tests/fixtures/scenarios/invalid/target-unknown.yaml`**
```yaml
# expected: E_TARGET_UNKNOWN
schema_version: 1
scenario_id: bad
seed: 1
duration_scale: short
library:
  roots:
    - id: r
      path: r
works:
  - id: w
    title: t
    variants:
      - id: v
        label: l
        bundle:
          id: b
          assets:
            - id: a
              role: primary_video
              container: mkv
              duration_seconds: 1
timeline:
  - id: e1
    at: 1s
    action: delete_file
    target: ghost
```

**File: `tests/fixtures/scenarios/invalid/slow-copy-unpaired.yaml`**
```yaml
# expected: E_SLOW_COPY_UNPAIRED
schema_version: 1
scenario_id: bad
seed: 1
duration_scale: short
library:
  roots:
    - id: r
      path: r
works:
  - id: w
    title: t
    variants:
      - id: v
        label: l
        bundle:
          id: b
          assets:
            - id: a
              role: primary_video
              container: mkv
              duration_seconds: 1
timeline:
  - id: c1
    at: 1s
    action: slow_copy_commit
    for: nonexistent_start
```

**File: `tests/fixtures/scenarios/invalid/slow-copy-timing-mismatch.yaml`**
```yaml
# expected: E_SLOW_COPY_TIMING
schema_version: 1
scenario_id: bad
seed: 1
duration_scale: short
library:
  roots:
    - id: r
      path: r
works:
  - id: w
    title: t
    variants:
      - id: v
        label: l
        bundle:
          id: b
          assets:
            - id: a
              role: primary_video
              container: mkv
              duration_seconds: 1
timeline:
  - id: s1
    at: 1s
    action: slow_copy_start
    target: a
    to: r/x.mkv
    temp_path: r/x.mkv.part
    duration: 3s
  - id: c1
    at: 5s  # should be 4s = 1s + 3s
    action: slow_copy_commit
    for: s1
```

**File: `tests/fixtures/scenarios/invalid/path-escape.yaml`**
```yaml
# expected: E_PATH_CONTAINMENT
schema_version: 1
scenario_id: bad
seed: 1
duration_scale: short
library:
  roots:
    - id: r
      path: r
works:
  - id: w
    title: t
    variants:
      - id: v
        label: l
        bundle:
          id: b
          assets:
            - id: a
              role: primary_video
              container: mkv
              duration_seconds: 1
timeline:
  - id: e1
    at: 1s
    action: rename_file
    target: a
    to: ../../etc/passwd
```

**File: `tests/fixtures/scenarios/invalid/timeline-out-of-order.yaml`**
```yaml
# expected: E_TIMELINE_ORDER
schema_version: 1
scenario_id: bad
seed: 1
duration_scale: short
library:
  roots:
    - id: r
      path: r
works:
  - id: w
    title: t
    variants:
      - id: v
        label: l
        bundle:
          id: b
          assets:
            - id: a
              role: primary_video
              container: mkv
              duration_seconds: 1
timeline:
  - id: e1
    at: 5s
    action: delete_file
    target: a
  - id: e2
    at: 1s
    action: delete_file
    target: a
```

**File: `tests/fixtures/scenarios/invalid/top-level-not-mapping.yaml`**
```yaml
# expected: E_TOP_LEVEL_NOT_MAPPING
42
```

- [ ] **Step 2: Write `test_invalid_corpus.py` and the valid-corpus smoke**

```python
# tests/validation/test_invalid_corpus.py
"""Parametrized: every invalid fixture surfaces its expected code.

Each fixture's first line is ``# expected: E_<CODE>``. The test asserts
the report contains at least one issue with that code AND ``ok=False``.
A separate test asserts every valid fixture in tests/fixtures/scenarios/
produces ``ok=True`` with no issues (Sprint 1 exit-criteria smoke).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from chaos_librarian.validation import run_validation

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
INVALID_DIR = FIXTURE_DIR / "invalid"


_EXPECTED_RE = re.compile(r"#\s*expected:\s*(E_[A-Z_]+)")


def _expected_code(path: Path) -> str:
    first_line = path.read_text().splitlines()[0]
    m = _EXPECTED_RE.search(first_line)
    if m is None:
        raise AssertionError(
            f"{path.name}: first line must be `# expected: E_<CODE>`, got {first_line!r}"
        )
    return m.group(1)


def _invalid_fixtures() -> list[Path]:
    return sorted(INVALID_DIR.glob("*.yaml"))


def _valid_fixtures() -> list[Path]:
    return sorted(FIXTURE_DIR.glob("*.yaml"))


@pytest.mark.parametrize("path", _invalid_fixtures(), ids=lambda p: p.name)
def test_invalid_fixture_produces_expected_code(path: Path) -> None:
    """Each invalid fixture surfaces at least one issue with its expected code.

    WHY: this is the regression guard for the public error-code set.
    Adding a code without a fixture (or removing a fixture without
    removing the code) is caught here.
    """
    expected = _expected_code(path)
    report = run_validation(path)
    assert report.ok is False, f"{path.name}: expected ok=False"
    assert any(i.code == expected for i in report.issues), (
        f"{path.name}: no issue with code {expected} in "
        f"{[i.code for i in report.issues]}"
    )


@pytest.mark.parametrize("path", _valid_fixtures(), ids=lambda p: p.name)
def test_valid_fixture_validates_clean(path: Path) -> None:
    """Every top-level fixture is valid (Sprint 1 exit-criteria smoke).

    WHY: if a shipped fixture stops validating, either it has drifted
    from the schema or a new rule has a false positive. Either way the
    refactor that broke it must be reconsidered.
    """
    report = run_validation(path)
    assert report.ok is True, (
        f"{path.name}: expected ok=True, got issues {[i.code for i in report.issues]}"
    )
    assert report.issues == []
```

- [ ] **Step 3: Run the corpus tests**

Run: `uv run pytest tests/validation/test_invalid_corpus.py -v`
Expected: all 13 invalid tests pass, all 4 valid tests pass.

If `yaml-parse-error.yaml` fails because ruamel parses the unterminated `[` as valid YAML, replace its body with `key: : value` (double colon) or `\t- bad indent` (mixing tabs and spaces).

- [ ] **Step 4: Run the full suite to confirm nothing else regressed**

Run: `uv run pytest`
Expected: every test passes.

- [ ] **Step 5: Lint + type-check + commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

```bash
git add tests/fixtures/scenarios/invalid tests/validation/test_invalid_corpus.py
git commit -m "test(validation): add invalid fixture corpus and corpus tests"
```

---

## Task 15: Docs reconciliation

**Files:**
- Modify: `docs/specs/chaos-librarian-design.md` (Sprint 1 / Sprint 2 sections)
- Modify: `docs/contract/cli-reference.md` (drop "every command stubbed" footnote)
- Modify: `CLAUDE.md` (project-state line)

Spec-level cleanups so future readers don't see stale Sprint 0 framing.

- [ ] **Step 1: Locate the target lines**

```bash
grep -n "Sprint 1\|Sprint 2\|stub\|Sprint 0" docs/specs/chaos-librarian-design.md | head -40
grep -n "stub\|Sprint 0" docs/contract/cli-reference.md
grep -n "Sprint 0\|stub" CLAUDE.md
```

- [ ] **Step 2: Update `docs/specs/chaos-librarian-design.md`**

In the Sprint 1 deliverables section, add "duration string parser (`parse_duration`)" to the list. In the Sprint 2 deliverables section, change "duration string parser" to "duration string *formatters* (`format_duration_human`, `format_duration_json`)" and add a clarifying sentence: "Sprint 2 consumes the duration parser shipped in Sprint 1."

- [ ] **Step 3: Update `docs/contract/cli-reference.md`**

Find the footnote that says "Sprint 0 ships every command as a stub" (or similar). Reword to "Every command except `validate` ships as a stub. `validate` was implemented in Sprint 1."

- [ ] **Step 4: Update `CLAUDE.md` §"Project state"**

Update the sentence describing CLI stubs:

- Before: "Every CLI command is a stub that exits 1."
- After: "`validate` is implemented as of Sprint 1. The other eight CLI commands are stubs that exit 1."

- [ ] **Step 5: Commit**

```bash
git add docs/specs/chaos-librarian-design.md docs/contract/cli-reference.md CLAUDE.md
git commit -m "docs: reconcile Sprint 0/1/2 deliverables now that validate ships"
```

---

## Exit Criteria

The PR is mergeable when every command below passes:

```bash
uv run pytest
uv run ty check src tests
uv run ruff check .
uv run ruff format --check .
uv run python -m chaos_librarian.schema_export --check
uv run chaos-librarian validate tests/fixtures/scenarios/identity-move-rename.yaml --json
uv run chaos-librarian validate tests/fixtures/scenarios/invalid/bad-duration.yaml --json
uv run chaos-librarian validate tests/fixtures/scenarios/invalid/duplicate-asset-id-cross-bundle.yaml --json
```

Expected:
- `pytest`: all green.
- `ty`, `ruff`, `schema_export --check`: clean (the schema-export check is informational here since this sprint touches no contract models, but running it confirms nothing regressed).
- The first `validate` command exits `0` and prints `"ok": true`.
- The `bad-duration` command exits `3` and prints at least one `E_DURATION_SYNTAX` issue with a non-null `line`.
- The `duplicate-asset-id-cross-bundle` command exits `3` and prints an `E_ID_DUPLICATE` issue whose message contains `asset_id` (regression guard for Codex finding #1).
