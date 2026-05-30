# Batch Scenario Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--count N` batch mode to the existing `chaos-librarian generate` command that writes N deterministic fuzz scenarios into a directory, layered on the shipped lane architecture.

**Architecture:** Pure planning helpers in `generation.py`/`profiles.py` compute the `(lane, seed)` work-list and file names; the `generate` command branches on `count` — `count == 1` is byte-identical to today's single-file behaviour, `count > 1` streams one scenario at a time into a directory with rollback on failure. No Pydantic model or JSON Schema changes.

**Tech Stack:** Python 3.13, Typer CLI, Pydantic v2, pytest, `uv`. Lint `ruff`, types `ty`.

**Spec:** `docs/superpowers/specs/2026-05-29-issue-104-batch-generate-design.md`
**ADR:** `docs/adr/0001-batch-generate-seed-and-lane-distribution.md`

---

## File Structure

- `src/chaos_librarian/contract/profiles.py` — add `CANONICAL_FUZZ_LANES` ordered-tuple mapping (batch lane-cycling order).
- `src/chaos_librarian/generation.py` — add `scenario_id_for`, `BatchItem`, `plan_generation_batch`; refactor the inlined `scenario_id` to call `scenario_id_for`.
- `src/chaos_librarian/cli/commands/generate.py` — add `--count`; unified flow with `_resolve_lane_for_batch`, `_write_single`, `_write_batch`, `_validate_out_dir`, `_batch_targets`, `_rollback`, `_batch_summary_json`.
- `tests/test_generation.py` — unit tests for the pure helpers.
- `tests/cli/test_generate.py` — CLI tests for batch behaviour + preserved single-file behaviour.
- `tests/cli/test_generate_replay.py` — add a plan-mode test on a batch-generated file.
- `docs/user/commands.md`, `docs/contract/cli-reference.md` — document `--count`.

Guardrails for every commit:

```bash
uv run ruff check && uv run ruff format --check . && uv run ty check src tests && uv run python -m pytest -q
```

---

### Task 1: `scenario_id_for` single-source-of-truth helper

**Files:**
- Modify: `src/chaos_librarian/generation.py`
- Test: `tests/test_generation.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_generation.py`:

```python
from chaos_librarian.generation import scenario_id_for


def test_scenario_id_for_matches_generated_scenario_id() -> None:
    generated = generation.generate_scenario(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.CORE_FS,
        seed=456,
    )
    assert generated.scenario.scenario_id == scenario_id_for(
        FuzzProfileName.FUZZ_REGRESSION, FuzzLaneName.CORE_FS, 456
    )
    assert scenario_id_for(FuzzProfileName.FUZZ_SMOKE, FuzzLaneName.SMOKE, 7) == (
        "fuzz-smoke-smoke-seed-7"
    )
```

Confirm the test module already imports `generation`, `FuzzProfileName`, `FuzzLaneName`; if not, add:

```python
from chaos_librarian import generation
from chaos_librarian.contract.profiles import FuzzLaneName, FuzzProfileName
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/test_generation.py::test_scenario_id_for_matches_generated_scenario_id -q`
Expected: FAIL — `ImportError: cannot import name 'scenario_id_for'`.

- [ ] **Step 3: Add the helper and use it in the generator**

In `src/chaos_librarian/generation.py`, add after the imports / before `generate_scenario_yaml`:

```python
def scenario_id_for(profile: FuzzProfileName, lane: FuzzLaneName, seed: int) -> str:
    """Return the canonical ``scenario_id`` for a generated fuzz scenario.

    Single source of truth shared by the generator and the batch path planner so
    file names and the ``scenario_id`` embedded in the YAML cannot drift.
    """
    return f"{profile.value}-{lane.value}-seed-{seed}"
```

Then in `_generate_scenario_yaml_unvalidated`, replace the inlined id:

```python
        "scenario_id": f"{profile.value}-{resolved_lane.value}-seed-{seed}",
```

with:

```python
        "scenario_id": scenario_id_for(profile, resolved_lane, seed),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_generation.py -q`
Expected: PASS (the new test and all existing generation tests — the id string is unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/generation.py tests/test_generation.py
git commit -m "refactor: extract scenario_id_for single source of truth

Refs #104

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Canonical lane ordering for batch cycling

**Files:**
- Modify: `src/chaos_librarian/contract/profiles.py`
- Test: `tests/contract/test_profiles.py` (create if absent)

- [ ] **Step 1: Write the failing test**

Create or append `tests/contract/test_profiles.py`:

```python
"""Tests for fuzz profile/lane metadata."""

from __future__ import annotations

from chaos_librarian.contract.profiles import (
    CANONICAL_FUZZ_LANES,
    FUZZ_LANES_BY_PROFILE,
    FuzzProfileName,
)


def test_canonical_lane_order_covers_each_profile_exactly() -> None:
    assert set(CANONICAL_FUZZ_LANES) == set(FuzzProfileName)
    for profile, order in CANONICAL_FUZZ_LANES.items():
        # ordered tuple and the existing frozenset must not drift apart
        assert frozenset(order) == FUZZ_LANES_BY_PROFILE[profile]
        # no duplicates in the ordered tuple
        assert len(order) == len(set(order))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run python -m pytest tests/contract/test_profiles.py -q`
Expected: FAIL — `ImportError: cannot import name 'CANONICAL_FUZZ_LANES'`.

- [ ] **Step 3: Add the mapping**

In `src/chaos_librarian/contract/profiles.py`, add immediately after `FUZZ_LANES_BY_PROFILE`:

```python
CANONICAL_FUZZ_LANES: Final[dict[FuzzProfileName, tuple[FuzzLaneName, ...]]] = {
    FuzzProfileName.FUZZ_SMOKE: (FuzzLaneName.SMOKE,),
    FuzzProfileName.FUZZ_REGRESSION: (
        FuzzLaneName.CORE_FS,
        FuzzLaneName.MEDIA_REWRITE,
        FuzzLaneName.SIDECAR_SUBTITLE,
        FuzzLaneName.MALFORMED,
        FuzzLaneName.NEGATIVE_ORACLE,
        FuzzLaneName.FILESYSTEM_ARTIFACT,
        FuzzLaneName.NETWORK_LAG,
        FuzzLaneName.TV_TOPOLOGY,
        FuzzLaneName.MUSIC_TOPOLOGY,
    ),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run python -m pytest tests/contract/test_profiles.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/contract/profiles.py tests/contract/test_profiles.py
git commit -m "feat: add canonical fuzz lane order for batch cycling

Refs #104

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `plan_generation_batch` pure work-list planner

**Files:**
- Modify: `src/chaos_librarian/generation.py`
- Test: `tests/test_generation.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_generation.py`:

```python
from chaos_librarian.generation import BatchItem, plan_generation_batch
from chaos_librarian.contract.profiles import CANONICAL_FUZZ_LANES


def test_plan_batch_fixed_lane_increments_seed() -> None:
    items = plan_generation_batch(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=FuzzLaneName.CORE_FS,
        seed=99,
        count=3,
    )
    assert items == (
        BatchItem(lane=FuzzLaneName.CORE_FS, seed=99),
        BatchItem(lane=FuzzLaneName.CORE_FS, seed=100),
        BatchItem(lane=FuzzLaneName.CORE_FS, seed=101),
    )


def test_plan_batch_cycles_lanes_when_lane_is_none() -> None:
    order = CANONICAL_FUZZ_LANES[FuzzProfileName.FUZZ_REGRESSION]
    n = len(order)
    items = plan_generation_batch(
        profile=FuzzProfileName.FUZZ_REGRESSION,
        lane=None,
        seed=42,
        count=n + 2,
    )
    assert len(items) == n + 2
    assert [it.lane for it in items[:n]] == list(order)
    # cycling wraps; second pass reuses the lane with a fresh seed
    assert items[n].lane == order[0]
    assert items[n].seed == 42 + n
    assert [it.seed for it in items] == list(range(42, 42 + n + 2))


def test_plan_batch_smoke_uses_smoke_lane() -> None:
    items = plan_generation_batch(
        profile=FuzzProfileName.FUZZ_SMOKE, lane=None, seed=5, count=4
    )
    assert all(it.lane == FuzzLaneName.SMOKE for it in items)
    assert [it.seed for it in items] == [5, 6, 7, 8]


def test_plan_batch_count_one_returns_single_item() -> None:
    items = plan_generation_batch(
        profile=FuzzProfileName.FUZZ_SMOKE, lane=FuzzLaneName.SMOKE, seed=1, count=1
    )
    assert items == (BatchItem(lane=FuzzLaneName.SMOKE, seed=1),)


def test_plan_batch_rejects_non_positive_count() -> None:
    with pytest.raises(ValueError, match="count must be >= 1"):
        plan_generation_batch(
            profile=FuzzProfileName.FUZZ_SMOKE, lane=FuzzLaneName.SMOKE, seed=1, count=0
        )
```

Ensure `import pytest` is present in the test module.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run python -m pytest tests/test_generation.py -k plan_batch -q`
Expected: FAIL — `ImportError: cannot import name 'BatchItem'`.

- [ ] **Step 3: Implement the planner**

In `src/chaos_librarian/generation.py`, add the import:

```python
from chaos_librarian.contract.profiles import CANONICAL_FUZZ_LANES, FuzzLaneName, FuzzProfileName
```

(merge with the existing `from chaos_librarian.contract.profiles import ...` line).

Add the dataclass and planner near `scenario_id_for`:

```python
@dataclass(frozen=True, slots=True)
class BatchItem:
    """One unit of batch work: the lane and seed for a single scenario."""

    lane: FuzzLaneName
    seed: int


def plan_generation_batch(
    profile: FuzzProfileName,
    lane: FuzzLaneName | None,
    seed: int,
    count: int,
) -> tuple[BatchItem, ...]:
    """Return the deterministic ``(lane, seed)`` work-list for a batch.

    ``seed_i = seed + i``. When ``lane`` is ``None`` the lanes cycle the
    canonical order for the profile; otherwise every item uses ``lane``.
    """
    if count < 1:
        raise ValueError("count must be >= 1")
    if lane is None:
        order = CANONICAL_FUZZ_LANES[profile]
        return tuple(
            BatchItem(lane=order[i % len(order)], seed=seed + i) for i in range(count)
        )
    return tuple(BatchItem(lane=lane, seed=seed + i) for i in range(count))
```

(`dataclass` is already imported at the top of the module.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run python -m pytest tests/test_generation.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/generation.py tests/test_generation.py
git commit -m "feat: add plan_generation_batch work-list planner

Refs #104

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Rewire `generate` command through the planner (count==1 preserved)

**Files:**
- Modify: `src/chaos_librarian/cli/commands/generate.py`
- Test: `tests/cli/test_generate.py` (existing tests must stay green)

This task refactors the command so `count == 1` flows through the same planner without behaviour change. The `--count` option is added but only `count == 1` is wired; `count > 1` is implemented in Task 5.

- [ ] **Step 1: Replace the command module**

Replace the entire body of `src/chaos_librarian/cli/commands/generate.py` with:

```python
"""``generate`` command: write deterministic fuzz scenario YAML."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer

from chaos_librarian.cli._render import validate_new_out_path
from chaos_librarian.cli.app import app
from chaos_librarian.contract.profiles import FUZZ_LANES_BY_PROFILE, FuzzLaneName, FuzzProfileName
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.generation import (
    BatchItem,
    generate_scenario,
    generated_scenario_summary,
    plan_generation_batch,
    scenario_id_for,
    write_generated_scenario,
)


@app.command()
def generate(
    profile: Annotated[FuzzProfileName, typer.Option("--profile")],
    seed: Annotated[int, typer.Option("--seed", min=0)],
    out: Annotated[Path, typer.Option("--out")],
    lane: Annotated[FuzzLaneName | None, typer.Option("--lane")] = None,
    count: Annotated[int, typer.Option("--count", min=1, max=1000)] = 1,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Generate one or more deterministic fuzz scenario YAML files.

    With ``--count 1`` (default) ``--out`` is a new file. With ``--count > 1``
    ``--out`` is an existing directory and each scenario is written as
    ``<scenario_id>.yaml``.
    """
    resolved_lane = _resolve_lane_for_batch(profile=profile, lane=lane, count=count)
    items = plan_generation_batch(
        profile=profile, lane=resolved_lane, seed=seed, count=count
    )
    if count == 1:
        _write_single(profile=profile, item=items[0], out=out, json_output=json_output)
        return
    _write_batch(profile=profile, items=items, out_dir=out, json_output=json_output)


def _resolve_lane_for_batch(
    profile: FuzzProfileName, lane: FuzzLaneName | None, count: int
) -> FuzzLaneName | None:
    """Validate and resolve ``--lane``; return ``None`` to cycle the lane order."""
    if lane is not None:
        if lane not in FUZZ_LANES_BY_PROFILE[profile]:
            raise typer.BadParameter(f"lane {lane.value} is not valid for {profile.value}")
        return lane
    if profile is FuzzProfileName.FUZZ_SMOKE:
        return FuzzLaneName.SMOKE
    if count == 1:
        raise typer.BadParameter("--lane is required for fuzz-regression")
    return None


def _write_single(
    profile: FuzzProfileName, item: BatchItem, out: Path, json_output: bool
) -> None:
    validate_new_out_path(out)
    generated = generate_scenario(profile=profile, lane=item.lane, seed=item.seed)
    write_generated_scenario(out, generated.data)
    if json_output:
        typer.echo(generated_scenario_summary(out, generated.data, scenario=generated.scenario))
    else:
        typer.echo(f"generate: wrote {out}")


def _write_batch(
    profile: FuzzProfileName,
    items: tuple[BatchItem, ...],
    out_dir: Path,
    json_output: bool,
) -> None:
    _validate_out_dir(out_dir)
    targets = _batch_targets(profile=profile, items=items, out_dir=out_dir)
    written: list[Path] = []
    records: list[tuple[Path, bytes, Scenario]] = []
    for item, path in targets:
        try:
            generated = generate_scenario(profile=profile, lane=item.lane, seed=item.seed)
            _assert_scenario_id(profile=profile, item=item, generated_id=generated.scenario.scenario_id)
            write_generated_scenario(path, generated.data)
        except Exception as exc:  # noqa: BLE001 — rollback then re-report any write/gen failure
            removed = _rollback(written)
            typer.echo(
                f"generate: failed at profile={profile.value} lane={item.lane.value} "
                f"seed={item.seed}: {exc}",
                err=True,
            )
            if removed:
                joined = ", ".join(str(p) for p in removed)
                typer.echo(
                    f"generate: rolled back {len(removed)} partially written files: {joined}",
                    err=True,
                )
            raise typer.Exit(code=1) from exc
        written.append(path)
        records.append((path, generated.data, generated.scenario))
        if not json_output:
            typer.echo(f"generate: wrote {path}")
    if json_output:
        typer.echo(_batch_summary_json(out_dir, records))
    else:
        typer.echo(f"generate: wrote {len(records)} scenarios to {out_dir}")


def _validate_out_dir(out_dir: Path) -> None:
    if not out_dir.exists():
        raise typer.BadParameter(f"--out directory does not exist: {out_dir}")
    if not out_dir.is_dir():
        raise typer.BadParameter(f"--out is not a directory: {out_dir}")


def _batch_targets(
    profile: FuzzProfileName, items: tuple[BatchItem, ...], out_dir: Path
) -> list[tuple[BatchItem, Path]]:
    targets: list[tuple[BatchItem, Path]] = []
    names: set[str] = set()
    for item in items:
        name = f"{scenario_id_for(profile, item.lane, item.seed)}.yaml"
        if name in names:
            raise RuntimeError(f"batch produced a duplicate file name: {name}")
        names.add(name)
        path = out_dir / name
        if path.exists():
            raise typer.BadParameter(f"--out already contains target file: {path}")
        targets.append((item, path))
    return targets


def _assert_scenario_id(
    profile: FuzzProfileName, item: BatchItem, generated_id: str
) -> None:
    expected = scenario_id_for(profile, item.lane, item.seed)
    if generated_id != expected:
        raise RuntimeError(
            f"generated scenario_id {generated_id!r} does not match planned {expected!r}"
        )


def _rollback(written: list[Path]) -> list[Path]:
    removed: list[Path] = []
    for path in written:
        try:
            path.unlink(missing_ok=True)
            removed.append(path)
        except OSError:
            pass
    return removed


def _batch_summary_json(out_dir: Path, records: list[tuple[Path, bytes, Scenario]]) -> str:
    scenarios = [
        json.loads(generated_scenario_summary(path, data, scenario=scenario))
        for path, data, scenario in records
    ]
    scenarios.sort(key=lambda summary: summary["scenario_path"])
    payload: dict[str, object] = {
        "ok": True,
        "count": len(scenarios),
        "out_dir": str(out_dir.resolve()),
        "scenarios": scenarios,
    }
    return json.dumps(payload, sort_keys=True)
```

- [ ] **Step 2: Run the existing CLI tests to verify count==1 is unchanged**

Run: `uv run python -m pytest tests/cli/test_generate.py tests/cli/test_generate_replay.py -q`
Expected: PASS — all seven existing `test_generate.py` tests and the replay test still pass (single-file path, lane-required error, mismatch error, existing-out rejection, random-seed rejection, topology lanes, json-validates-once).

- [ ] **Step 3: Run lint and types**

Run: `uv run ruff check src/chaos_librarian/cli/commands/generate.py && uv run ty check src`
Expected: PASS. If `ruff` flags the `# noqa: BLE001`, confirm `BLE001` (blind-except) is the actual code reported; the broad catch is intentional (rollback must run for any failure) and justified inline.

- [ ] **Step 4: Commit**

```bash
git add src/chaos_librarian/cli/commands/generate.py
git commit -m "refactor: route generate through batch planner, add --count option

Refs #104

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Batch CLI behaviour tests

**Files:**
- Test: `tests/cli/test_generate.py`

The implementation already exists from Task 4; this task adds the tests that exercise `count > 1`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/cli/test_generate.py`:

```python
from chaos_librarian.contract.profiles import CANONICAL_FUZZ_LANES, FuzzProfileName


def _run(args: list[str]) -> Result:
    return runner.invoke(app, args)


def test_batch_smoke_writes_count_files(tmp_path: Path) -> None:
    out = tmp_path / "gen"
    out.mkdir()

    result = _run(
        ["generate", "--profile", "fuzz-smoke", "--count", "3", "--seed", "42", "--out", str(out)]
    )

    assert result.exit_code == 0, _plain_output(result)
    files = sorted(p.name for p in out.glob("*.yaml"))
    assert files == [
        "fuzz-smoke-smoke-seed-42.yaml",
        "fuzz-smoke-smoke-seed-43.yaml",
        "fuzz-smoke-smoke-seed-44.yaml",
    ]
    for path in out.glob("*.yaml"):
        assert _load_generated(path).generation is not None


def test_batch_regression_cycles_lanes(tmp_path: Path) -> None:
    out = tmp_path / "gen"
    out.mkdir()
    order = CANONICAL_FUZZ_LANES[FuzzProfileName.FUZZ_REGRESSION]

    result = _run(
        [
            "generate", "--profile", "fuzz-regression",
            "--count", str(len(order)), "--seed", "100", "--out", str(out),
        ]
    )

    assert result.exit_code == 0, _plain_output(result)
    lanes = {
        _load_generated(p).generation.lane.value  # type: ignore[union-attr]
        for p in out.glob("*.yaml")
    }
    assert lanes == {lane.value for lane in order}
    assert len(list(out.glob("*.yaml"))) == len(order)


def test_batch_explicit_lane_uses_one_lane(tmp_path: Path) -> None:
    out = tmp_path / "gen"
    out.mkdir()

    result = _run(
        [
            "generate", "--profile", "fuzz-regression", "--lane", "core-fs",
            "--count", "4", "--seed", "10", "--out", str(out),
        ]
    )

    assert result.exit_code == 0, _plain_output(result)
    files = sorted(p.name for p in out.glob("*.yaml"))
    assert files == [f"fuzz-regression-core-fs-seed-{s}.yaml" for s in (10, 11, 12, 13)]


def test_batch_is_deterministic(tmp_path: Path) -> None:
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    out_a.mkdir()
    out_b.mkdir()
    args = ["generate", "--profile", "fuzz-regression", "--count", "5", "--seed", "7", "--out"]

    assert _run([*args, str(out_a)]).exit_code == 0
    assert _run([*args, str(out_b)]).exit_code == 0

    names_a = sorted(p.name for p in out_a.glob("*.yaml"))
    names_b = sorted(p.name for p in out_b.glob("*.yaml"))
    assert names_a == names_b
    for name in names_a:
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes()


def test_batch_json_emits_only_summary_object(tmp_path: Path) -> None:
    out = tmp_path / "gen"
    out.mkdir()

    result = _run(
        ["generate", "--profile", "fuzz-smoke", "--count", "3", "--seed", "42",
         "--out", str(out), "--json"]
    )

    assert result.exit_code == 0, _plain_output(result)
    payload = json.loads(result.stdout)  # must parse — no progress lines on stdout
    assert payload["ok"] is True
    assert payload["count"] == 3
    assert payload["out_dir"] == str(out.resolve())
    assert [s["seed"] for s in payload["scenarios"]] == [42, 43, 44]


def test_batch_matches_single_file_output(tmp_path: Path) -> None:
    batch_dir = tmp_path / "batch"
    batch_dir.mkdir()
    single = tmp_path / "single.yaml"

    assert _run(
        ["generate", "--profile", "fuzz-regression", "--count", "3", "--seed", "200",
         "--out", str(batch_dir)]
    ).exit_code == 0
    # item index 1 of the cycle: second canonical lane, seed 201
    lane = CANONICAL_FUZZ_LANES[FuzzProfileName.FUZZ_REGRESSION][1].value
    assert _run(
        ["generate", "--profile", "fuzz-regression", "--lane", lane, "--seed", "201",
         "--out", str(single)]
    ).exit_code == 0

    batch_file = batch_dir / f"fuzz-regression-{lane}-seed-201.yaml"
    assert batch_file.read_bytes() == single.read_bytes()


def test_batch_rejects_missing_out_dir(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist"

    result = _run(
        ["generate", "--profile", "fuzz-smoke", "--count", "2", "--seed", "1", "--out", str(missing)]
    )

    assert result.exit_code == 2
    assert not missing.exists()


def test_batch_rejects_out_that_is_a_file(tmp_path: Path) -> None:
    out = tmp_path / "afile"
    out.write_text("x", encoding="utf-8")

    result = _run(
        ["generate", "--profile", "fuzz-smoke", "--count", "2", "--seed", "1", "--out", str(out)]
    )

    assert result.exit_code == 2
    assert out.read_text(encoding="utf-8") == "x"


def test_batch_collision_pre_check_writes_nothing(tmp_path: Path) -> None:
    out = tmp_path / "gen"
    out.mkdir()
    # pre-create a file that the batch would target
    (out / "fuzz-smoke-smoke-seed-43.yaml").write_text("pre", encoding="utf-8")

    result = _run(
        ["generate", "--profile", "fuzz-smoke", "--count", "3", "--seed", "42", "--out", str(out)]
    )

    assert result.exit_code == 2
    # no new files written; the pre-existing file is untouched
    assert sorted(p.name for p in out.glob("*.yaml")) == ["fuzz-smoke-smoke-seed-43.yaml"]
    assert (out / "fuzz-smoke-smoke-seed-43.yaml").read_text(encoding="utf-8") == "pre"


def test_batch_rollback_removes_written_files_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out = tmp_path / "gen"
    out.mkdir()

    from chaos_librarian.cli.commands import generate as generate_cmd

    real_generate = generate_cmd.generate_scenario
    calls = {"n": 0}

    def failing_generate(**kwargs: Any) -> Any:
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real_generate(**kwargs)

    monkeypatch.setattr(generate_cmd, "generate_scenario", failing_generate)

    result = _run(
        ["generate", "--profile", "fuzz-smoke", "--count", "3", "--seed", "42", "--out", str(out)]
    )

    assert result.exit_code == 1
    assert "rolled back" in _plain_output(result)
    # first file was written then rolled back; nothing remains
    assert list(out.glob("*.yaml")) == []
```

- [ ] **Step 2: Run the new tests to verify they pass**

Run: `uv run python -m pytest tests/cli/test_generate.py -q`
Expected: PASS (existing + new). The rollback test asserts the partial file is removed and exit code is 1.

- [ ] **Step 3: Commit**

```bash
git add tests/cli/test_generate.py
git commit -m "test: cover batch generate behaviour and rollback

Refs #104

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Plan-mode coverage for a batch-generated scenario

**Files:**
- Test: `tests/cli/test_generate_replay.py`

Satisfies the "works in both materialize and plan modes" acceptance criterion at the unit level (plan needs no media tools).

- [ ] **Step 1: Write the failing test**

Append to `tests/cli/test_generate_replay.py`:

```python
def test_batch_generated_scenario_plans(tmp_path: Path) -> None:
    out = tmp_path / "gen"
    out.mkdir()
    run_dir = tmp_path / "run"

    gen = runner.invoke(
        app,
        ["generate", "--profile", "fuzz-smoke", "--count", "2", "--seed", "70", "--out", str(out)],
    )
    assert gen.exit_code == 0, gen.stdout + gen.stderr

    scenario = out / "fuzz-smoke-smoke-seed-70.yaml"
    assert scenario.exists()
    plan_result = runner.invoke(app, ["plan", str(scenario), "--out", str(run_dir), "--json"])
    assert plan_result.exit_code == 0, plan_result.stdout + plan_result.stderr
```

- [ ] **Step 2: Run the test to verify it passes**

Run: `uv run python -m pytest tests/cli/test_generate_replay.py -q`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/cli/test_generate_replay.py
git commit -m "test: plan a batch-generated scenario

Refs #104

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Document `--count`

**Files:**
- Modify: `docs/user/commands.md`
- Modify: `docs/contract/cli-reference.md`

- [ ] **Step 1: Update `docs/user/commands.md`**

Change the `generate` heading (currently line ~16) to include `--count`:

```markdown
## `generate --profile PROFILE [--lane LANE] [--count N] --seed SEED --out OUT [--json]`
```

Add after the existing examples block (after the closing ```` ``` ````):

````markdown
Generate a batch of scenarios into a directory with `--count N` (default `1`).
With `--count 1`, `--out` is a new file (as above). With `--count > 1`, `--out`
must be an existing directory and each scenario is written as
`<scenario_id>.yaml`:

```bash
# 9 fuzz-regression scenarios, one per lane, seeds 42..50
uv run chaos-librarian generate --profile fuzz-regression --count 9 --seed 42 --out ./generated/

# 20 fuzz-smoke scenarios, seeds 42..61
uv run chaos-librarian generate --profile fuzz-smoke --count 20 --seed 42 --out ./generated/
```

Item `i` uses `seed + i`. For `fuzz-regression` without `--lane`, lanes cycle the
canonical order; with `--lane L`, all items use lane `L`. Output is deterministic
for a given `(profile, seed, count, lane)`. On any failure the batch removes the
files it wrote so the command can be re-run.
````

- [ ] **Step 2: Update `docs/contract/cli-reference.md`**

In the `generate` section (the paragraph beginning "`generate` writes deterministic fuzz scenario YAML"), add a sentence:

```markdown
`--count N` (default `1`) generates a batch: with `N > 1`, `--out` is an existing
directory and `N` scenarios are written as `<scenario_id>.yaml`, with seeds
`seed .. seed+N-1` and (for `fuzz-regression` without `--lane`) lanes cycling the
canonical order.
```

If the section shows example invocations (lines ~5-6), add:

```
chaos-librarian generate --profile fuzz-regression --count 9 --seed 42 --out ./generated/
```

- [ ] **Step 3: Verify docs reference nothing false**

Run: `uv run chaos-librarian generate --help`
Expected: the help text lists `--count`. Confirm the documented flags match.

- [ ] **Step 4: Commit**

```bash
git add docs/user/commands.md docs/contract/cli-reference.md
git commit -m "docs: document generate --count batch mode

Refs #104

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Full guardrails + help-snapshot check

**Files:** none (verification only); fix any fallout.

- [ ] **Step 1: Run the complete guardrail suite**

Run:

```bash
uv run ruff check && uv run ruff format --check . && uv run ty check src tests && uv run python -m pytest -q && uv run python -m chaos_librarian.schema_export --check
```

Expected: all PASS. The schema drift gate passes unchanged (no model edits).

- [ ] **Step 2: Resolve any CLI snapshot/help test fallout**

If `tests/cli/test_app.py` (or any `--help` snapshot) fails because `--count` was added, that is expected drift from a new option. Inspect the failure; if it is a committed help/option snapshot, update the snapshot to include `--count` and confirm the command *order* (the frozen contract) is unchanged. Re-run the suite.

- [ ] **Step 3: Commit any fixups**

```bash
git add -A
git commit -m "test: update CLI help snapshot for --count

Refs #104

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

(Skip this commit if Step 1 was already fully green.)

---

## Self-Review Notes

- **Spec coverage:** `--count` (Tasks 4-5), directory `--out` for `count>1` + file for `count==1` (Task 4), `seed+i` and lane cycling (Task 3), `scenario_id_for` single source of truth + traversal-safe names (Task 1), canonical lane order + drift guard (Task 2), rollback + collision pre-check + `--json` stdout purity (Tasks 4-5), plan-mode AC (Task 6), no-schema-change guardrail (Task 8), docs (Task 7). The "empty timeline / single asset / max budgets" issue edges are generator-level and covered by existing `tests/test_generation*.py`, as the spec records.
- **No placeholders:** every code and test step is complete.
- **Type consistency:** `BatchItem(lane, seed)`, `plan_generation_batch(profile, lane, seed, count)`, `scenario_id_for(profile, lane, seed)`, and `CANONICAL_FUZZ_LANES` are used identically across tasks.
