# Issue #2 — CLI Path Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Flip all CLI Path Argument/Option validations in `src/chaos_librarian/cli/app.py` from their permissive Sprint 0 defaults to the final-form values specified in issue #2, so the frozen CLI contract surface is complete on day one rather than trickling in across Sprints 1–4.

**Architecture:** Each command's `Path` Argument gets `exists=True` and an explicit `dir_okay`/`file_okay` matching the kind of path it expects (file vs run-directory). Each `--out` Option gets a shared `_validate_new_out_path` callback that enforces "parent must exist, path itself must not." All nine commands remain stubs that exit `1` — the new validation runs *before* the stub, so invalid paths exit `2` (Typer/Click `BadParameter`) instead of reaching the stub. Tests use `tmp_path` for valid inputs and add per-command rejection-path tests.

**Tech Stack:** Python 3.13, Typer 0.x on Click 8.2+, pytest with `tmp_path`, `typer.testing.CliRunner`.

**Scope boundary — what this plan does NOT do:** `clean`'s sentinel-content check (parse `.chaos-librarian-run`, validate against `RunSentinel`, refuse on mismatch) is runtime safety logic, not Typer Path-shape validation. It ships with Sprint 4's real `clean` implementation. Issue #2 is closed when path-shape validation lands; the sentinel check will be a separate Sprint 4 acceptance item.

**Branch + commit convention (per active-sprint memory):** Work on the current `feat/sprint-0` branch. Do NOT create a worktree, fix branch, or new PR. Every commit message ends with `Refs #2` (NOT `Closes #2`) so the issue stays open until PR #5 merges to `main` and resolves it via the PR body.

---

## File Structure

Only two files change. The validation lives in `cli/app.py` (the same module it constrains); no new module is justified yet (YAGNI — one helper).

```
chaos-librarian/
├── src/chaos_librarian/cli/
│   └── app.py                    [modified] flip validation + add _validate_new_out_path
└── tests/cli/
    └── test_app.py               [modified] tmp_path fixtures + rejection-path tests
```

---

## Notes for the implementer

- **Exit codes:** Typer/Click `BadParameter` (including built-in `exists=True` failure) exits with code `2`. Stubs exit `1`. Rejection tests assert `exit_code == 2`; positive stub tests assert `exit_code == 1`.
- **`tmp_path`:** pytest's built-in fixture; provides a fresh `pathlib.Path` directory per test. Use `tmp_path / "scenario.yaml"` and `.write_text("")` to make a real (empty) file for positive paths.
- **`CliRunner`:** the existing module-level `runner = CliRunner()` at `tests/cli/test_app.py:12` is shared by all tests. Keep using it.
- **Parametrized stub test:** the existing `test_stub_command_exits_one` at `tests/cli/test_app.py:34` is replaced piecewise — one row leaves the parametrize list each task as that command gets its own dedicated positive test. After Task 9 only `capabilities` remains; Task 10 collapses what's left.
- **Callback signature:** Typer callbacks receive `(value)` or `(ctx, param, value)`. We use the simple `(value)` form because we only need the value and Typer wraps `BadParameter` into a usage error automatically.
- **Project conventions to honor:**
  - `Annotated[Path, typer.Argument(...)]` form (ruff B008) — already used; keep it.
  - Absolute imports only (`from chaos_librarian.cli.app import app`).
  - No commented-out code; no `# type: ignore` (use `dict` payloads in negative tests).
  - After ANY change in `src/chaos_librarian/contract/`, regenerate `schemas/` — this plan does NOT touch `contract/`, so no schema regen is needed.
- **Final-form per-command target (reproduced from issue #2):**

  | command       | argument / option | validation                                          |
  |---------------|-------------------|-----------------------------------------------------|
  | `validate`    | `scenario`        | `exists=True, dir_okay=False`                       |
  | `plan`        | `scenario`        | `exists=True, dir_okay=False`                       |
  | `plan`        | `--out`           | callback: parent exists; path itself does not       |
  | `materialize` | `scenario`        | `exists=True, dir_okay=False`                       |
  | `materialize` | `--out`           | callback: parent exists; path itself does not       |
  | `run`         | `scenario`        | `exists=True, dir_okay=False`                       |
  | `run`         | `--out`           | callback: parent exists; path itself does not       |
  | `step`        | `run_dir`         | `exists=True, dir_okay=True, file_okay=False`       |
  | `replay`      | `bundle`          | `exists=True, dir_okay=False`                       |
  | `replay`      | `--out`           | callback: parent exists; path itself does not       |
  | `inspect`     | `run_dir`         | `exists=True, dir_okay=True, file_okay=False`       |
  | `clean`       | `run_dir`         | `exists=True, dir_okay=True, file_okay=False`       |
  | `capabilities`| (none)            | (unchanged — no Path args)                          |

---

## Task 1: Add `_validate_new_out_path` callback helper

**Files:**
- Modify: `src/chaos_librarian/cli/app.py` (add helper after `_stub`)
- Modify: `tests/cli/test_app.py` (add test for helper behavior via `plan` once Task 3 flips that command — covered there; here we just add the helper for reuse)

The helper has no commands wired to it yet at the end of this task — that's intentional. Tasks 3, 4, 5, 9 wire it in. Adding it first means each command-flip task is a one-line wiring change rather than mixing "add helper" with "wire helper" semantics.

- [ ] **Step 1: Add the helper to `app.py`**

Edit `src/chaos_librarian/cli/app.py` — insert AFTER the existing `_stub` function (currently ends at line 24), BEFORE the first `@app.command()` (currently line 27):

```python
def _validate_new_out_path(value: Path) -> Path:
    """Reject --out paths whose parent is missing or that already exist.

    The CLI never overwrites an existing output directory and requires
    the caller to have prepared a writable parent. This runs as a Typer
    callback so failures surface as exit-code 2 BadParameter errors
    before any command body executes.
    """
    if value.exists():
        raise typer.BadParameter(f"--out path already exists: {value}")
    parent = value.parent
    if not parent.exists():
        raise typer.BadParameter(f"--out parent directory does not exist: {parent}")
    if not parent.is_dir():
        raise typer.BadParameter(f"--out parent is not a directory: {parent}")
    return value
```

- [ ] **Step 2: Confirm app still parses / `--help` still works**

Run: `uv run chaos-librarian --help`
Expected: usage banner with all 9 commands; exit 0. (The helper is defined but unused — should have no behavioral effect yet.)

- [ ] **Step 3: Run existing tests to confirm no regressions**

Run: `uv run pytest tests/cli/ -v`
Expected: every test passes (12 passed in the existing suite). The helper is dead code at this point — that is the intent.

- [ ] **Step 4: Lint + types**

Run: `uv run ruff check src/chaos_librarian/cli/app.py && uv run ty check src/chaos_librarian/cli/app.py`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/cli/app.py
git commit -m "feat(cli): add _validate_new_out_path callback helper

Reusable Typer callback for --out options. Enforces that the parent
directory exists and the --out path itself does not. Unused at this
commit; subsequent commits wire it into plan/materialize/run/replay.

Refs #2"
```

---

## Task 2: Flip `validate` command

**Files:**
- Modify: `src/chaos_librarian/cli/app.py:28-33` (validate command)
- Modify: `tests/cli/test_app.py` (drop `validate` from parametrized stub test; add dedicated positive + rejection tests)

- [ ] **Step 1: Add failing rejection tests for `validate`**

Append to `tests/cli/test_app.py`:

```python
class TestValidatePathValidation:
    def test_rejects_missing_scenario(self, tmp_path):
        missing = tmp_path / "does-not-exist.yaml"
        result = runner.invoke(app, ["validate", str(missing)])
        assert result.exit_code == 2, (
            f"missing scenario should exit 2 (BadParameter), got {result.exit_code}"
        )

    def test_rejects_directory_as_scenario(self, tmp_path):
        a_dir = tmp_path / "a-dir"
        a_dir.mkdir()
        result = runner.invoke(app, ["validate", str(a_dir)])
        assert result.exit_code == 2, (
            f"directory passed as scenario should exit 2, got {result.exit_code}"
        )
```

- [ ] **Step 2: Run rejection tests — should FAIL**

Run: `uv run pytest tests/cli/test_app.py::TestValidatePathValidation -v`
Expected: both tests FAIL with `assert 1 == 2` (current stub exits 1 regardless of path validity).

- [ ] **Step 3: Add dedicated positive stub test for `validate`**

Append to `tests/cli/test_app.py`:

```python
def test_validate_stub_with_valid_scenario_exits_one(tmp_path):
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("")
    result = runner.invoke(app, ["validate", str(scenario)])
    assert result.exit_code == 1, (
        f"validate stub with valid path should exit 1, got {result.exit_code}"
    )
```

- [ ] **Step 4: Remove `validate` row from the existing parametrized stub test**

Edit `tests/cli/test_app.py`, in `test_stub_command_exits_one`'s `@pytest.mark.parametrize` list — delete the line `["validate", "scenario.yaml"],` (currently at line 37).

- [ ] **Step 5: Apply the validation flip**

Edit `src/chaos_librarian/cli/app.py:29` — change:

```python
    scenario: Annotated[Path, typer.Argument(exists=False, dir_okay=False)],
```

to:

```python
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
```

- [ ] **Step 6: Run all `validate`-related tests — should PASS**

Run: `uv run pytest tests/cli/test_app.py -v -k validate`
Expected: rejection tests pass (exit 2), positive stub test passes (exit 1).

- [ ] **Step 7: Run the full CLI suite — should PASS**

Run: `uv run pytest tests/cli/ -v`
Expected: every test green.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_app.py
git commit -m "feat(cli): enforce exists=True on validate scenario arg

Flip validate's scenario argument from permissive Sprint 0 default
(exists=False) to final-form (exists=True, dir_okay=False). Replace
the parametrized stub row with a dedicated positive test using
tmp_path, and add rejection tests for missing-file and directory
inputs.

Refs #2"
```

---

## Task 3: Flip `plan` command

**Files:**
- Modify: `src/chaos_librarian/cli/app.py:36-43` (plan command)
- Modify: `tests/cli/test_app.py`

- [ ] **Step 1: Add failing rejection tests for `plan`**

Append to `tests/cli/test_app.py`:

```python
class TestPlanPathValidation:
    def test_rejects_missing_scenario(self, tmp_path):
        missing = tmp_path / "missing.yaml"
        out = tmp_path / "run-001"
        result = runner.invoke(app, ["plan", str(missing), "--out", str(out)])
        assert result.exit_code == 2

    def test_rejects_directory_as_scenario(self, tmp_path):
        a_dir = tmp_path / "a-dir"
        a_dir.mkdir()
        out = tmp_path / "run-001"
        result = runner.invoke(app, ["plan", str(a_dir), "--out", str(out)])
        assert result.exit_code == 2

    def test_rejects_out_when_parent_missing(self, tmp_path):
        scenario = tmp_path / "scenario.yaml"
        scenario.write_text("")
        out = tmp_path / "nonexistent-parent" / "run-001"
        result = runner.invoke(app, ["plan", str(scenario), "--out", str(out)])
        assert result.exit_code == 2

    def test_rejects_out_when_path_already_exists(self, tmp_path):
        scenario = tmp_path / "scenario.yaml"
        scenario.write_text("")
        out = tmp_path / "run-001"
        out.mkdir()
        result = runner.invoke(app, ["plan", str(scenario), "--out", str(out)])
        assert result.exit_code == 2
```

- [ ] **Step 2: Run rejection tests — should FAIL**

Run: `uv run pytest tests/cli/test_app.py::TestPlanPathValidation -v`
Expected: all four FAIL (current stub exits 1 regardless).

- [ ] **Step 3: Add dedicated positive stub test**

Append to `tests/cli/test_app.py`:

```python
def test_plan_stub_with_valid_paths_exits_one(tmp_path):
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("")
    out = tmp_path / "run-001"
    result = runner.invoke(app, ["plan", str(scenario), "--out", str(out)])
    assert result.exit_code == 1
```

- [ ] **Step 4: Remove `plan` row from the parametrized stub test**

Edit `tests/cli/test_app.py`, in `test_stub_command_exits_one` — delete the line `["plan", "scenario.yaml", "--out", "fixtures/run-001"],`.

- [ ] **Step 5: Apply the validation flip**

Edit `src/chaos_librarian/cli/app.py:37-40` — change the `plan` signature to:

```python
@app.command()
def plan(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=_validate_new_out_path)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
```

- [ ] **Step 6: Run all `plan`-related tests — should PASS**

Run: `uv run pytest tests/cli/test_app.py -v -k plan`
Expected: all four rejection tests + positive stub test pass.

- [ ] **Step 7: Run the full CLI suite**

Run: `uv run pytest tests/cli/ -v`
Expected: every test green.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_app.py
git commit -m "feat(cli): enforce exists=True + --out callback on plan

Flip plan's scenario arg to exists=True, dir_okay=False, and wire the
shared _validate_new_out_path callback onto --out so plan rejects
non-existent scenarios, directories-as-scenarios, --out paths whose
parent is missing, and --out paths that already exist.

Refs #2"
```

---

## Task 4: Flip `materialize` command

**Files:**
- Modify: `src/chaos_librarian/cli/app.py:46-53`
- Modify: `tests/cli/test_app.py`

- [ ] **Step 1: Add failing rejection tests**

Append to `tests/cli/test_app.py`:

```python
class TestMaterializePathValidation:
    def test_rejects_missing_scenario(self, tmp_path):
        missing = tmp_path / "missing.yaml"
        out = tmp_path / "run-001"
        result = runner.invoke(app, ["materialize", str(missing), "--out", str(out)])
        assert result.exit_code == 2

    def test_rejects_directory_as_scenario(self, tmp_path):
        a_dir = tmp_path / "a-dir"
        a_dir.mkdir()
        out = tmp_path / "run-001"
        result = runner.invoke(app, ["materialize", str(a_dir), "--out", str(out)])
        assert result.exit_code == 2

    def test_rejects_out_when_parent_missing(self, tmp_path):
        scenario = tmp_path / "scenario.yaml"
        scenario.write_text("")
        out = tmp_path / "nonexistent-parent" / "run-001"
        result = runner.invoke(app, ["materialize", str(scenario), "--out", str(out)])
        assert result.exit_code == 2

    def test_rejects_out_when_path_already_exists(self, tmp_path):
        scenario = tmp_path / "scenario.yaml"
        scenario.write_text("")
        out = tmp_path / "run-001"
        out.mkdir()
        result = runner.invoke(app, ["materialize", str(scenario), "--out", str(out)])
        assert result.exit_code == 2
```

- [ ] **Step 2: Run rejection tests — should FAIL**

Run: `uv run pytest tests/cli/test_app.py::TestMaterializePathValidation -v`
Expected: all four FAIL.

- [ ] **Step 3: Add dedicated positive stub test**

Append to `tests/cli/test_app.py`:

```python
def test_materialize_stub_with_valid_paths_exits_one(tmp_path):
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("")
    out = tmp_path / "run-001"
    result = runner.invoke(app, ["materialize", str(scenario), "--out", str(out)])
    assert result.exit_code == 1
```

- [ ] **Step 4: Remove `materialize` row from the parametrized stub test**

Delete the line `["materialize", "scenario.yaml", "--out", "fixtures/run-001"],` from `test_stub_command_exits_one`.

- [ ] **Step 5: Apply the validation flip**

Edit `src/chaos_librarian/cli/app.py:47-50` — change the `materialize` signature to:

```python
@app.command()
def materialize(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=_validate_new_out_path)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
```

- [ ] **Step 6: Run all `materialize`-related tests — should PASS**

Run: `uv run pytest tests/cli/test_app.py -v -k materialize`
Expected: all green.

- [ ] **Step 7: Run the full CLI suite**

Run: `uv run pytest tests/cli/ -v`

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_app.py
git commit -m "feat(cli): enforce exists=True + --out callback on materialize

Flip materialize's scenario arg to exists=True, dir_okay=False and
wire the _validate_new_out_path callback onto --out.

Refs #2"
```

---

## Task 5: Flip `run` command

**Files:**
- Modify: `src/chaos_librarian/cli/app.py:56-65`
- Modify: `tests/cli/test_app.py`

- [ ] **Step 1: Add failing rejection tests**

Append to `tests/cli/test_app.py`:

```python
class TestRunPathValidation:
    def test_rejects_missing_scenario(self, tmp_path):
        missing = tmp_path / "missing.yaml"
        out = tmp_path / "run-001"
        result = runner.invoke(
            app,
            ["run", str(missing), "--out", str(out), "--duration", "10s"],
        )
        assert result.exit_code == 2

    def test_rejects_directory_as_scenario(self, tmp_path):
        a_dir = tmp_path / "a-dir"
        a_dir.mkdir()
        out = tmp_path / "run-001"
        result = runner.invoke(
            app,
            ["run", str(a_dir), "--out", str(out), "--duration", "10s"],
        )
        assert result.exit_code == 2

    def test_rejects_out_when_parent_missing(self, tmp_path):
        scenario = tmp_path / "scenario.yaml"
        scenario.write_text("")
        out = tmp_path / "nonexistent-parent" / "run-001"
        result = runner.invoke(
            app,
            ["run", str(scenario), "--out", str(out), "--duration", "10s"],
        )
        assert result.exit_code == 2

    def test_rejects_out_when_path_already_exists(self, tmp_path):
        scenario = tmp_path / "scenario.yaml"
        scenario.write_text("")
        out = tmp_path / "run-001"
        out.mkdir()
        result = runner.invoke(
            app,
            ["run", str(scenario), "--out", str(out), "--duration", "10s"],
        )
        assert result.exit_code == 2
```

- [ ] **Step 2: Run rejection tests — should FAIL**

Run: `uv run pytest tests/cli/test_app.py::TestRunPathValidation -v`
Expected: all four FAIL.

- [ ] **Step 3: Add dedicated positive stub test**

Append to `tests/cli/test_app.py`:

```python
def test_run_stub_with_valid_paths_exits_one(tmp_path):
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("")
    out = tmp_path / "run-001"
    result = runner.invoke(
        app,
        ["run", str(scenario), "--out", str(out), "--duration", "10s"],
    )
    assert result.exit_code == 1
```

- [ ] **Step 4: Remove `run` row from the parametrized stub test**

Delete the line `["run", "scenario.yaml", "--out", "fixtures/run-001", "--duration", "10s"],` from `test_stub_command_exits_one`.

- [ ] **Step 5: Apply the validation flip**

Edit `src/chaos_librarian/cli/app.py:57-62` — change `run`'s signature to:

```python
@app.command()
def run(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=_validate_new_out_path)],
    duration: Annotated[str, typer.Option("--duration")],
    speed: Annotated[str, typer.Option("--speed")] = "1x",
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
```

- [ ] **Step 6: Run all `run`-related tests — should PASS**

Run: `uv run pytest tests/cli/test_app.py -v -k "Run or run_stub"`
Expected: all green. (`-k` filter intentionally narrow — many test names contain "run" generically.)

- [ ] **Step 7: Run the full CLI suite**

Run: `uv run pytest tests/cli/ -v`

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_app.py
git commit -m "feat(cli): enforce exists=True + --out callback on run

Flip run's scenario arg to exists=True, dir_okay=False and wire the
_validate_new_out_path callback onto --out.

Refs #2"
```

---

## Task 6: Flip `step` command

**Files:**
- Modify: `src/chaos_librarian/cli/app.py:68-75`
- Modify: `tests/cli/test_app.py`

- [ ] **Step 1: Add failing rejection tests**

Append to `tests/cli/test_app.py`:

```python
class TestStepPathValidation:
    def test_rejects_missing_run_dir(self, tmp_path):
        missing = tmp_path / "missing-run"
        result = runner.invoke(app, ["step", str(missing), "--next"])
        assert result.exit_code == 2

    def test_rejects_file_as_run_dir(self, tmp_path):
        a_file = tmp_path / "not-a-dir"
        a_file.write_text("")
        result = runner.invoke(app, ["step", str(a_file), "--next"])
        assert result.exit_code == 2
```

- [ ] **Step 2: Run rejection tests — should FAIL**

Run: `uv run pytest tests/cli/test_app.py::TestStepPathValidation -v`
Expected: both FAIL.

- [ ] **Step 3: Add dedicated positive stub test**

Append to `tests/cli/test_app.py`:

```python
def test_step_stub_with_valid_run_dir_exits_one(tmp_path):
    run_dir = tmp_path / "run-001"
    run_dir.mkdir()
    result = runner.invoke(app, ["step", str(run_dir), "--next"])
    assert result.exit_code == 1
```

- [ ] **Step 4: Remove `step` row from the parametrized stub test**

Delete the line `["step", "fixtures/run-001", "--next"],` from `test_stub_command_exits_one`.

- [ ] **Step 5: Apply the validation flip**

Edit `src/chaos_librarian/cli/app.py:70` — change:

```python
    run_dir: Annotated[Path, typer.Argument(exists=False)],
```

to:

```python
    run_dir: Annotated[Path, typer.Argument(exists=True, dir_okay=True, file_okay=False)],
```

- [ ] **Step 6: Run all `step`-related tests — should PASS**

Run: `uv run pytest tests/cli/test_app.py -v -k step`

- [ ] **Step 7: Run the full CLI suite**

Run: `uv run pytest tests/cli/ -v`

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_app.py
git commit -m "feat(cli): enforce run-dir validation on step

Flip step's run_dir argument to exists=True, dir_okay=True,
file_okay=False so step rejects missing run-dirs and files passed
where a directory is required.

Refs #2"
```

---

## Task 7: Flip `inspect` command

**Files:**
- Modify: `src/chaos_librarian/cli/app.py:88-94`
- Modify: `tests/cli/test_app.py`

- [ ] **Step 1: Add failing rejection tests**

Append to `tests/cli/test_app.py`:

```python
class TestInspectPathValidation:
    def test_rejects_missing_run_dir(self, tmp_path):
        missing = tmp_path / "missing-run"
        result = runner.invoke(app, ["inspect", str(missing)])
        assert result.exit_code == 2

    def test_rejects_file_as_run_dir(self, tmp_path):
        a_file = tmp_path / "not-a-dir"
        a_file.write_text("")
        result = runner.invoke(app, ["inspect", str(a_file)])
        assert result.exit_code == 2
```

- [ ] **Step 2: Run rejection tests — should FAIL**

Run: `uv run pytest tests/cli/test_app.py::TestInspectPathValidation -v`

- [ ] **Step 3: Add dedicated positive stub test**

Append to `tests/cli/test_app.py`:

```python
def test_inspect_stub_with_valid_run_dir_exits_one(tmp_path):
    run_dir = tmp_path / "run-001"
    run_dir.mkdir()
    result = runner.invoke(app, ["inspect", str(run_dir)])
    assert result.exit_code == 1
```

- [ ] **Step 4: Remove `inspect` row from the parametrized stub test**

Delete the line `["inspect", "fixtures/run-001"],` from `test_stub_command_exits_one`.

- [ ] **Step 5: Apply the validation flip**

Edit `src/chaos_librarian/cli/app.py:90` — change:

```python
    run_dir: Annotated[Path, typer.Argument(exists=False)],
```

to:

```python
    run_dir: Annotated[Path, typer.Argument(exists=True, dir_okay=True, file_okay=False)],
```

- [ ] **Step 6: Run all `inspect`-related tests — should PASS**

Run: `uv run pytest tests/cli/test_app.py -v -k inspect`

- [ ] **Step 7: Run the full CLI suite**

Run: `uv run pytest tests/cli/ -v`

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_app.py
git commit -m "feat(cli): enforce run-dir validation on inspect

Flip inspect's run_dir argument to exists=True, dir_okay=True,
file_okay=False.

Refs #2"
```

---

## Task 8: Flip `clean` command (path-shape only; defer sentinel check)

**Files:**
- Modify: `src/chaos_librarian/cli/app.py:105-111`
- Modify: `tests/cli/test_app.py`

This task does NOT add the sentinel-content check (`.chaos-librarian-run` parse + RunSentinel validate + run_id match). That belongs with the real `clean` implementation in Sprint 4 because it requires reading and parsing the sentinel file, which is runtime safety logic rather than CLI Path-shape validation. The Sprint 4 plan for `clean` will add it and update issue #2's checklist accordingly.

- [ ] **Step 1: Add failing rejection tests**

Append to `tests/cli/test_app.py`:

```python
class TestCleanPathValidation:
    def test_rejects_missing_run_dir(self, tmp_path):
        missing = tmp_path / "missing-run"
        result = runner.invoke(app, ["clean", str(missing)])
        assert result.exit_code == 2

    def test_rejects_file_as_run_dir(self, tmp_path):
        a_file = tmp_path / "not-a-dir"
        a_file.write_text("")
        result = runner.invoke(app, ["clean", str(a_file)])
        assert result.exit_code == 2
```

- [ ] **Step 2: Run rejection tests — should FAIL**

Run: `uv run pytest tests/cli/test_app.py::TestCleanPathValidation -v`

- [ ] **Step 3: Add dedicated positive stub test**

Append to `tests/cli/test_app.py`:

```python
def test_clean_stub_with_valid_run_dir_exits_one(tmp_path):
    run_dir = tmp_path / "run-001"
    run_dir.mkdir()
    result = runner.invoke(app, ["clean", str(run_dir)])
    assert result.exit_code == 1
```

- [ ] **Step 4: Remove `clean` row from the parametrized stub test**

Delete the line `["clean", "fixtures/run-001"],` from `test_stub_command_exits_one`.

- [ ] **Step 5: Apply the validation flip**

Edit `src/chaos_librarian/cli/app.py:107` — change:

```python
    run_dir: Annotated[Path, typer.Argument(exists=False)],
```

to:

```python
    run_dir: Annotated[Path, typer.Argument(exists=True, dir_okay=True, file_okay=False)],
```

- [ ] **Step 6: Run all `clean`-related tests — should PASS**

Run: `uv run pytest tests/cli/test_app.py -v -k clean`

- [ ] **Step 7: Run the full CLI suite**

Run: `uv run pytest tests/cli/ -v`

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_app.py
git commit -m "feat(cli): enforce run-dir validation on clean

Flip clean's run_dir argument to exists=True, dir_okay=True,
file_okay=False. The .chaos-librarian-run sentinel content check
(parse + RunSentinel validate + run_id match) is deferred to the
Sprint 4 clean implementation; this commit covers only Typer-level
path-shape validation.

Refs #2"
```

---

## Task 9: Flip `replay` command

**Files:**
- Modify: `src/chaos_librarian/cli/app.py:78-85`
- Modify: `tests/cli/test_app.py`

- [ ] **Step 1: Add failing rejection tests**

Append to `tests/cli/test_app.py`:

```python
class TestReplayPathValidation:
    def test_rejects_missing_bundle(self, tmp_path):
        missing = tmp_path / "missing-replay.json"
        out = tmp_path / "replay-out"
        result = runner.invoke(app, ["replay", str(missing), "--out", str(out)])
        assert result.exit_code == 2

    def test_rejects_directory_as_bundle(self, tmp_path):
        a_dir = tmp_path / "a-dir"
        a_dir.mkdir()
        out = tmp_path / "replay-out"
        result = runner.invoke(app, ["replay", str(a_dir), "--out", str(out)])
        assert result.exit_code == 2

    def test_rejects_out_when_parent_missing(self, tmp_path):
        bundle = tmp_path / "replay.json"
        bundle.write_text("")
        out = tmp_path / "nonexistent-parent" / "replay-out"
        result = runner.invoke(app, ["replay", str(bundle), "--out", str(out)])
        assert result.exit_code == 2

    def test_rejects_out_when_path_already_exists(self, tmp_path):
        bundle = tmp_path / "replay.json"
        bundle.write_text("")
        out = tmp_path / "replay-out"
        out.mkdir()
        result = runner.invoke(app, ["replay", str(bundle), "--out", str(out)])
        assert result.exit_code == 2
```

- [ ] **Step 2: Run rejection tests — should FAIL**

Run: `uv run pytest tests/cli/test_app.py::TestReplayPathValidation -v`

- [ ] **Step 3: Add dedicated positive stub test**

Append to `tests/cli/test_app.py`:

```python
def test_replay_stub_with_valid_paths_exits_one(tmp_path):
    bundle = tmp_path / "replay.json"
    bundle.write_text("")
    out = tmp_path / "replay-out"
    result = runner.invoke(app, ["replay", str(bundle), "--out", str(out)])
    assert result.exit_code == 1
```

- [ ] **Step 4: Remove `replay` row from the parametrized stub test**

Delete the line `["replay", "fixtures/run-001/replay.json", "--out", "fixtures/replay-001"],` from `test_stub_command_exits_one`.

- [ ] **Step 5: Apply the validation flip**

Edit `src/chaos_librarian/cli/app.py:79-82` — change `replay`'s signature to:

```python
@app.command()
def replay(
    bundle: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=_validate_new_out_path)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
```

- [ ] **Step 6: Run all `replay`-related tests — should PASS**

Run: `uv run pytest tests/cli/test_app.py -v -k replay`

- [ ] **Step 7: Run the full CLI suite**

Run: `uv run pytest tests/cli/ -v`

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_app.py
git commit -m "feat(cli): enforce exists=True + --out callback on replay

Flip replay's bundle arg to exists=True, dir_okay=False and wire the
_validate_new_out_path callback onto --out.

Refs #2"
```

---

## Task 10: Collapse the parametrized stub test + final verification

After Tasks 2–9, the `test_stub_command_exits_one` parametrize list contains only `["capabilities"]`. `capabilities` has no Path arguments, so it never needed `tmp_path`. Convert it to a plain function so the dead parametrize machinery goes away.

**Files:**
- Modify: `tests/cli/test_app.py`

- [ ] **Step 1: Confirm only `capabilities` remains in the parametrize list**

Run: `grep -n "test_stub_command_exits_one\|capabilities\|fixtures/run" tests/cli/test_app.py`
Expected: only one parametrize row left: `["capabilities"],`.

- [ ] **Step 2: Replace the parametrized test with a plain function**

Edit `tests/cli/test_app.py` — delete the `@pytest.mark.parametrize(...)` decorator and the `test_stub_command_exits_one(command_args)` function. Replace with:

```python
def test_capabilities_stub_exits_one() -> None:
    result = runner.invoke(app, ["capabilities"])
    assert result.exit_code == 1
```

- [ ] **Step 3: Run the full CLI suite**

Run: `uv run pytest tests/cli/ -v`
Expected: every test green, no skips, no warnings about unused parametrize fixtures.

- [ ] **Step 4: Run the full project suite**

Run: `uv run pytest`
Expected: all green.

- [ ] **Step 5: Lint, format, types**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 6: Schema drift check (sanity — this plan did not touch `contract/`)**

Run: `uv run python -m chaos_librarian.schema_export --check`
Expected: no drift.

- [ ] **Step 7: Pre-commit hooks**

Run: `prek run --all-files`
Expected: clean.

- [ ] **Step 8: Manual smoke — confirm rejection on the real CLI**

Run: `uv run chaos-librarian validate /nonexistent/scenario.yaml; echo "exit=$?"`
Expected: usage error to stderr; `exit=2`.

Run: `uv run chaos-librarian capabilities; echo "exit=$?"`
Expected: stub message; `exit=1`.

- [ ] **Step 9: Commit**

```bash
git add tests/cli/test_app.py
git commit -m "test(cli): collapse single-row parametrize after issue #2 fixups

With all Path-bearing commands now having dedicated positive stub
tests using tmp_path, only capabilities remained in the legacy
parametrized stub test. Replace it with a plain function.

Refs #2"
```

---

## Self-Review Notes

- **Spec coverage:** Every row in issue #2's flip table is covered by a task (validate=2, plan=3, materialize=4, run=5, step=6, inspect=7, clean=8, replay=9). `capabilities` is correctly untouched (no Path args). The deferred sentinel check is explicitly called out in Task 8 and in the top-level scope boundary.
- **No placeholders:** every step shows exact file paths, full code blocks, and the precise commands with expected output.
- **Type consistency:** `_validate_new_out_path` is defined once in Task 1 and referenced verbatim in Tasks 3, 4, 5, 9.
- **Test discipline:** every command gets failing rejection tests written *before* the validation flip; positive stub tests are added in the same task and confirmed green after the flip.
- **Commit hygiene:** each task is one focused commit ending in `Refs #2`. No `Closes #2` — per memory, that resolution happens via PR #5's body when Sprint 0 merges.
- **No scope creep:** sentinel-content check explicitly deferred; no helper module introduced; no refactor of the existing `_stub` helper.
