# Issue 88 Slow Copy Idle Growth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make wall-clock slow-copy temp files grow during idle waits before commit.

**Architecture:** Keep the wall-clock loop single-threaded. When active slow copies exist and no event is due, cap the sleep target to an internal polling interval so the existing top-of-loop growth call can update temp-file size.

**Tech Stack:** Python 3.13, pytest, ruff, ty.

---

### Task 1: Full-Run Slow-Copy Growth Regression

**Files:**
- Modify: `tests/materializer/test_wall_clock.py`

- [ ] **Step 1: Write the failing test**

Add this test near `test_watcher_polling_observes_partial_slow_copy`:

```python
def test_active_slow_copy_grows_during_idle_waits(
    fake_clock: FakeClock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    observed_sizes: list[int] = []
    original = wall_clock._grow_active_slow_copies

    def spy(library_root, sessions, *, logical_ns: int) -> None:
        original(library_root, sessions, logical_ns=logical_ns)
        temp = library_root / "movies-hd" / "Nova.mkv.part"
        if temp.exists():
            observed_sizes.append(temp.stat().st_size)

    monkeypatch.setattr(wall_clock, "_grow_active_slow_copies", spy)

    wall_clock.run_wall_clock_scenario(
        _FIXTURE_DIR / "slow-copy-materialize.yaml",
        tmp_path / "run",
        duration="5s",
        speed="1x",
    )

    source_size = len(b"asset_main-bytes")
    partial_sizes = {
        size for size in observed_sizes if 0 < size < source_size
    }
    assert len(partial_sizes) >= 2
```

- [ ] **Step 2: Verify RED**

Run:

```bash
uv run pytest tests/materializer/test_wall_clock.py::test_active_slow_copy_grows_during_idle_waits -q --no-cov
```

Expected: FAIL because the scheduler observes fewer than two distinct partial
temp sizes during a full slow copy.

### Task 2: Slow-Copy Poll Wake Cap

**Files:**
- Modify: `src/chaos_librarian/materializer/wall_clock.py`
- Test: `tests/materializer/test_wall_clock.py`

- [ ] **Step 1: Add the internal poll interval**

Add this module constant near the dataclasses:

```python
_SLOW_COPY_POLL_INTERVAL_NS = 1_000_000_000
```

- [ ] **Step 2: Cap idle sleeps while slow copies are active**

Replace the no-due sleep block in `_run_timed_phase()` with:

```python
            if due_count == 0:
                wake_ns = _next_wake_ns(start_wall_ns, deadline_ns, journal[cursor], speed)
                if state.slow_copies:
                    wake_ns = min(wake_ns, now_ns + _SLOW_COPY_POLL_INTERVAL_NS)
                _sleep_until(wake_ns)
                continue
```

- [ ] **Step 3: Verify GREEN**

Run:

```bash
uv run pytest tests/materializer/test_wall_clock.py::test_active_slow_copy_grows_during_idle_waits -q --no-cov
```

Expected: PASS.

### Task 3: Focused Verification

**Files:**
- Test: `tests/materializer/test_wall_clock.py`
- Test: `tests/integration/test_wall_clock_run.py`

- [ ] **Step 1: Run focused wall-clock tests**

Run:

```bash
uv run pytest tests/materializer/test_wall_clock.py tests/integration/test_wall_clock_run.py -q --no-cov
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

- [ ] **Step 3: Re-run the real polling repro**

Run a local `slow-copy-materialize` wall-clock run with 1x speed and poll
`movies-hd/Nova.mkv.part` while the run is active. Expected: at least two
increasing non-final temp-file sizes before final promotion.
