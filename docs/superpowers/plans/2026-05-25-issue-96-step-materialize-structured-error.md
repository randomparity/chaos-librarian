# Issue 96 Step Materialize Structured Error Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development
> (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps
> use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `step --json` reject materialize/run replay bundles with a stable
structured error instead of a traceback.

**Architecture:** Keep `step_fixture()` plan-only. Add a CLI preflight that uses the
existing replay-bundle union adapter to detect non-plan replay bundles before the
plan-only engine parses `replay.json`.

**Tech Stack:** Python 3.13, Typer, Pydantic v2, pytest.

---

### Task 1: Structured CLI Error For Unsupported Step Modes

**Files:**
- Modify: `src/chaos_librarian/cli/_envelope.py`
- Modify: `src/chaos_librarian/cli/commands/step.py`
- Modify: `docs/contract/cli-reference.md`
- Modify: `docs/user/commands.md`
- Modify: `tests/cli/test_step.py`

- [x] **Step 1: Add failing CLI regression tests**

Add tests to `tests/cli/test_step.py`:

```python
def _replace_replay_with_materialize_bundle(run_dir: Path) -> None:
    plan = PlanOnlyReplayBundle.model_validate_json((run_dir / "replay.json").read_text())
    bundle = MaterializeReplayBundle(
        **plan.model_dump(),
        execution_mode=ExecutionMode.MATERIALIZE,
        created_at=datetime(2026, 5, 25, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="8.1.1", ffprobe="8.1.1", mkvtoolnix="98.0"),
        content_sources=[],
    )
    (run_dir / "replay.json").write_text(bundle.model_dump_json(indent=2) + "\n")


def test_step_refuses_materialized_run_dir_with_structured_json(tmp_path: Path) -> None:
    out = _make_paused(tmp_path)
    _replace_replay_with_materialize_bundle(out)

    result = runner.invoke(app, ["step", str(out), "--next", "1", "--json"])

    assert result.exit_code == 1
    assert "Traceback" not in result.stderr
    payload = json.loads(result.stderr)
    assert payload["error_code"] == "E_STEP_UNSUPPORTED_MODE"
    assert payload["details"]["execution_mode"] == "materialize"
    assert payload["details"]["supported_execution_mode"] == "plan_only"


def test_step_reports_invalid_replay_bundle_json(tmp_path: Path) -> None:
    paused = _make_paused(tmp_path)
    (paused / "replay.json").write_text("{not json\n")

    result = runner.invoke(app, ["step", str(paused), "--json"])

    assert result.exit_code == 1
    assert "Traceback" not in result.stderr
    payload = json.loads(result.stderr)
    assert payload["error_code"] == "E_REPLAY_BUNDLE_INVALID"
    assert payload["bundle_path"].endswith("replay.json")
```

Run:

```bash
uv run pytest tests/cli/test_step.py \
  -q --no-cov
```

Expected: the materialized-run test fails with the current traceback behavior.

- [x] **Step 2: Add envelope constant**

Add this constant in `src/chaos_librarian/cli/_envelope.py` next to the other
shared CLI envelope codes:

```python
E_STEP_UNSUPPORTED_MODE: Final = "E_STEP_UNSUPPORTED_MODE"
```

Add it to `__all__`.

- [x] **Step 3: Add step replay preflight**

In `src/chaos_librarian/cli/commands/step.py`, import:

```python
from pydantic import ValidationError

from chaos_librarian.cli._envelope import (
    E_REPLAY_BUNDLE_INVALID,
    E_STEP_UNSUPPORTED_MODE,
    ...
)
from chaos_librarian.cli._replay_io import REPLAY_BUNDLE_ADAPTER
from chaos_librarian.contract.replay_bundle import ExecutionMode, PlanOnlyReplayBundle
```

Add a helper:

```python
def _preflight_step_replay_bundle(run_dir: Path, *, json_output: bool) -> None:
    bundle_path = run_dir / "replay.json"
    try:
        bundle = REPLAY_BUNDLE_ADAPTER.validate_json(bundle_path.read_bytes())
    except (OSError, ValidationError) as exc:
        emit_cli_error(
            error_code=E_REPLAY_BUNDLE_INVALID,
            message=f"replay bundle is not parseable: {exc}",
            json_output=json_output,
            extra_top_level={"bundle_path": str(bundle_path)},
        )
        raise typer.Exit(code=1) from exc
    if isinstance(bundle, PlanOnlyReplayBundle):
        return
    mode = bundle.execution_mode.value
    emit_cli_error(
        error_code=E_STEP_UNSUPPORTED_MODE,
        message=f"step supports plan_only replay bundles only; got {mode}",
        json_output=json_output,
        details={
            "execution_mode": mode,
            "supported_execution_mode": ExecutionMode.PLAN_ONLY.value,
        },
    )
    raise typer.Exit(code=1)
```

Call it after the existing sentinel `IN_PROGRESS` check and before
`step_fixture(run_dir, n_steps=next_count)`.

- [x] **Step 4: Document step mode support**

Update `docs/contract/cli-reference.md` command text:

```markdown
`step` advances a plan-only fixture by `--next N` user-visible step units.
Materialize and run directories are rejected with `E_STEP_UNSUPPORTED_MODE`
until materialized stepping is implemented.
```

Update `docs/user/commands.md` near the `step` command with the same contract.

- [x] **Step 5: Run focused verification**

Run:

```bash
uv run pytest tests/cli/test_step.py tests/engine/test_step.py -q --no-cov
uv run ruff check src/chaos_librarian/cli/_envelope.py \
  src/chaos_librarian/cli/commands/step.py tests/cli/test_step.py
uv run ruff format --check src/chaos_librarian/cli/_envelope.py \
  src/chaos_librarian/cli/commands/step.py tests/cli/test_step.py
uv run ty check src tests
```

Expected: all commands pass.
