# Issue 86 Required Null Report Current Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Serialize required nullable report fields, especially deleted-asset `current`, without emitting optional null defaults.

**Architecture:** Keep the fix in `engine.writer.canonical_json()` so plan, step, and materialize success report writers share the same artifact serializer. The serializer walks Pydantic models in field order, preserves required nulls, and drops optional nulls.

**Tech Stack:** Python 3.13, Pydantic v2, pytest, ruff, ty.

---

### Task 1: Regression Coverage

**Files:**
- Modify: `tests/engine/test_writer.py`

- [ ] **Step 1: Write the failing test**

Add imports:

```python
from chaos_librarian.adapter.fixture import load_fixture
from chaos_librarian.contract.reports import AssetReport
from chaos_librarian.engine import step_fixture
```

Add this test to `TestAppendStep`:

```python
    def test_deleted_asset_report_keeps_required_current_null(self, tmp_path: Path) -> None:
        run_input, report = _prepare("active-library-churn.yaml")
        artifacts = run_plan(
            run_input=run_input,
            validation_report=report,
            steps_limit=3,
        )
        out = tmp_path / "run"
        write_fixture(out, artifacts, run_input.raw_bytes)

        step_fixture(out, n_steps=3)

        report_path = out / "reports" / "assets" / "asset_main.json"
        payload = json.loads(report_path.read_text())
        assert "current" in payload
        assert payload["current"] is None
        AssetReport.model_validate_json(report_path.read_text())
        load_fixture(out)
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest tests/engine/test_writer.py::TestAppendStep::test_deleted_asset_report_keeps_required_current_null -q --no-cov
```

Expected: FAIL because `"current"` is missing from the serialized asset report.

### Task 2: Required-Null Serializer

**Files:**
- Modify: `src/chaos_librarian/engine/writer.py`
- Test: `tests/engine/test_writer.py`

- [ ] **Step 1: Implement the minimal serializer**

Add `import json` and replace `canonical_json()` with a serializer that dumps
Pydantic models in JSON mode, then removes only optional nulls:

```python
def canonical_json(model: BaseModel) -> str:
    """Canonical text form of a Pydantic model: indent=2, by_alias, trailing newline."""
    payload = _dump_preserving_required_nulls(model)
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
```

Add helpers:

```python
def _dump_preserving_required_nulls(model: BaseModel) -> dict[str, object]:
    raw = model.model_dump(mode="json", by_alias=True, exclude_none=False)
    if not isinstance(raw, dict):
        raise TypeError(f"expected object dump for {type(model).__name__}")
    return dict(_iter_serialized_fields(model, raw))


def _iter_serialized_fields(
    model: BaseModel,
    raw: dict[str, object],
) -> Iterable[tuple[str, object]]:
    fields = type(model).model_fields.items()
    for (field_name, field), (key, raw_value) in zip(fields, raw.items(), strict=True):
        value = getattr(model, field_name)
        if value is None:
            if field.is_required():
                yield key, None
            continue
        yield key, _dump_value_preserving_required_nulls(value, raw_value)


def _dump_value_preserving_required_nulls(value: object, raw_value: object) -> object:
    if isinstance(value, BaseModel):
        return _dump_preserving_required_nulls(value)
    if isinstance(value, list | tuple):
        if not isinstance(raw_value, list):
            return raw_value
        return [
            _dump_value_preserving_required_nulls(item, raw_item)
            for item, raw_item in zip(value, raw_value, strict=True)
        ]
    return raw_value
```

This walks `type(model).model_fields`, uses the serialized key already present
in `raw`, preserves required `None`, omits optional `None`, recurses into nested
`BaseModel` values and lists/tuples, and otherwise returns the JSON-mode dumped
value.

- [ ] **Step 2: Verify GREEN**

Run:

```bash
uv run pytest tests/engine/test_writer.py::TestAppendStep::test_deleted_asset_report_keeps_required_current_null -q --no-cov
```

Expected: PASS.

### Task 3: Focused Verification

**Files:**
- Test: `tests/engine/test_writer.py`
- Test: `tests/adapter/test_fixture.py`

- [ ] **Step 1: Run focused suites**

Run:

```bash
uv run pytest tests/engine/test_writer.py tests/adapter/test_fixture.py -q --no-cov
```

Expected: PASS.

- [ ] **Step 2: Run static checks and schema drift gate**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Expected: all commands exit 0 with no warnings.
