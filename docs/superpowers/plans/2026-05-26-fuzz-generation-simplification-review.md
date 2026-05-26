# Fuzz Generation Simplification Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the fuzz generation branch review findings without changing generated scenario behavior.

**Architecture:** Keep `chaos_librarian.generation` as the public byte-oriented API, add a parsed internal result for CLI summary reuse, and keep lane configuration as the generator source for supported generation cases. Remove dead planner state and small allocation/coupling points while preserving committed generated fixtures.

**Tech Stack:** Python 3.13, uv, pytest, ruff, ty, Typer.

---

## Review Decisions

Implement now:
- Remove unused `TimelinePlanner.placed_assets` and `deleted_assets`.
- Avoid double validation for `generate --json` by reusing the parsed generated scenario.
- Use `LaneConfig` as the single object passed into the planner.
- Derive property-test lane cases from `LANE_CONFIGS`.
- Iterate lane coverage in one pass without building a timeline copy.
- Make sidecar helper state fail loud and remove empty sidecar buckets.
- Move the profile-to-lane contract next to `FuzzLaneName` and assert lane configs cover it.

Defer to GitHub issues:
- Co-locate required lane event emission with lane coverage configuration.
- Share profile-gated action metadata between validation and generated lane profiles.

## File Structure

- Modify `src/chaos_librarian/contract/profiles.py`: own the profile-to-lane map.
- Modify `src/chaos_librarian/contract/scenario.py`: import lane map from profiles.
- Modify `src/chaos_librarian/cli/commands/generate.py`: use parsed generation result for JSON summaries.
- Modify `src/chaos_librarian/generation.py`: add internal generated-result helper.
- Modify `src/chaos_librarian/generation_lanes.py`: simplify coverage iteration and lane config helpers.
- Modify `src/chaos_librarian/generation_planner.py`: remove dead state and tighten sidecar/network helpers.
- Modify `tests/cli/test_generate.py`: lock single validation for `--json`.
- Modify `tests/test_generation.py`: replace `profiles_for_lane` coverage and assert lane contract coverage.
- Modify `tests/test_generation_properties.py`: derive lane cases from config.

### Task 1: Lock `generate --json` Validation Count

**Files:**
- Modify: `tests/cli/test_generate.py`

- [ ] **Step 1: Write the failing test**

Add this test after `test_generate_writes_valid_yaml_and_json_summary`:

```python
def test_generate_json_validates_generated_yaml_once(
    tmp_path: Path,
    monkeypatch,
) -> None:
    import chaos_librarian.generation as generation

    out = tmp_path / "generated.yaml"
    calls = 0
    original_run_validation = generation.run_validation

    def counting_run_validation(run_input):
        nonlocal calls
        calls += 1
        return original_run_validation(run_input)

    monkeypatch.setattr(generation, "run_validation", counting_run_validation)

    result = runner.invoke(
        app,
        [
            "generate",
            "--profile",
            "fuzz-smoke",
            "--seed",
            "123",
            "--out",
            str(out),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    assert calls == 1
```

- [ ] **Step 2: Run the focused test to verify it fails**

Run:

```bash
uv run pytest tests/cli/test_generate.py::test_generate_json_validates_generated_yaml_once -q --no-cov
```

Expected: FAIL with `assert 2 == 1`.

### Task 2: Reuse Parsed Generated Scenario

**Files:**
- Modify: `src/chaos_librarian/generation.py`
- Modify: `src/chaos_librarian/cli/commands/generate.py`

- [ ] **Step 1: Add a generated result object**

In `src/chaos_librarian/generation.py`, add a frozen dataclass:

```python
@dataclass(frozen=True, slots=True)
class GeneratedScenario:
    data: bytes
    scenario: Scenario
```

Then add:

```python
def generate_scenario(
    profile: FuzzProfileName,
    seed: int,
    lane: FuzzLaneName | None = None,
) -> GeneratedScenario:
    data = _generate_scenario_yaml_unvalidated(profile=profile, seed=seed, lane=lane)
    scenario = _validate_generated_yaml(data)
    return GeneratedScenario(data=data, scenario=scenario)
```

Update `generate_scenario_yaml()` to return `generate_scenario(...).data`.

- [ ] **Step 2: Split payload construction**

Move the current payload-building body into:

```python
def _generate_scenario_yaml_unvalidated(
    profile: FuzzProfileName,
    seed: int,
    lane: FuzzLaneName | None,
) -> bytes:
    ...
```

Keep coverage validation before `_dump_yaml(payload)`.

- [ ] **Step 3: Reuse the parsed scenario in CLI summary**

In `src/chaos_librarian/cli/commands/generate.py`, import `generate_scenario` and use:

```python
generated = generate_scenario(profile=profile, lane=resolved_lane, seed=seed)
write_generated_scenario(out, generated.data)
if json_output:
    typer.echo(generated_scenario_summary(out, generated.data, scenario=generated.scenario))
```

Update `generated_scenario_summary()` to accept `scenario: Scenario | None = None` and validate only when `scenario is None`.

- [ ] **Step 4: Verify the red test passes**

Run:

```bash
uv run pytest tests/cli/test_generate.py::test_generate_json_validates_generated_yaml_once -q --no-cov
```

Expected: PASS.

### Task 3: Simplify Lane Config Usage

**Files:**
- Modify: `src/chaos_librarian/contract/profiles.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/cli/commands/generate.py`
- Modify: `src/chaos_librarian/generation.py`
- Modify: `src/chaos_librarian/generation_lanes.py`
- Modify: `src/chaos_librarian/generation_planner.py`
- Modify: `tests/test_generation.py`
- Modify: `tests/test_generation_properties.py`

- [ ] **Step 1: Move lane map next to lane enum**

Move `FUZZ_LANES_BY_PROFILE` into `contract/profiles.py` and import it from there in `contract/scenario.py` and CLI code.

- [ ] **Step 2: Use `LaneConfig` directly**

Remove `profiles_for_lane()`. In `generation.py`, use `config.profiles`; in `generation_planner.py`, change `plan_payload_parts()` to accept only `config` and read `config.profile` / `config.lane`.

- [ ] **Step 3: Derive property cases from lane config**

In `tests/test_generation_properties.py`, replace the hard-coded `LANE_CASES` with:

```python
LANE_CASES = tuple(
    sorted(
        generation_lanes.LANE_CONFIGS,
        key=lambda item: (item[0].value, item[1].value),
    )
)
```

- [ ] **Step 4: Assert lane config covers the contract**

In `tests/test_generation.py`, add a test that compares `LANE_CONFIGS` grouped by profile to `FUZZ_LANES_BY_PROFILE`.

### Task 4: Remove Planner Dead State and Tighten Helpers

**Files:**
- Modify: `src/chaos_librarian/generation_lanes.py`
- Modify: `src/chaos_librarian/generation_planner.py`

- [ ] **Step 1: Remove unused planner lifecycle fields**

Delete `placed_assets`, `deleted_assets`, `__post_init__()`, and the mutations in `_delete_file()` / `_add_file()`.

- [ ] **Step 2: Avoid coverage timeline copying**

Inline the timeline list check in `coverage_for_payload()` and delete `_timeline_events()`.

- [ ] **Step 3: Return event references for network lag triggers**

Make `_rename_file()` and `_edit_metadata()` return a typed event reference and use it in `_network_lag_pair()` instead of reading `planner.events[-1]`.

- [ ] **Step 4: Make sidecar helpers fail loud**

Add a live-sidecar check, delete empty sidecar buckets after pop, and raise `ValueError` when update/remove helpers are called without a live sidecar.

### Task 5: Verify and Commit

**Files:**
- All modified files above.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest tests/test_generation.py tests/test_generation_properties.py tests/cli/test_generate.py -q --no-cov
```

Expected: PASS.

- [ ] **Step 2: Run lint/type/schema checks**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Expected: all clean.

- [ ] **Step 3: File deferred GitHub issues**

Create issues for the two deferred valid review recommendations with file pointers and sprint/branch context.

- [ ] **Step 4: Commit**

Run:

```bash
git add docs/superpowers/plans/2026-05-26-fuzz-generation-simplification-review.md \
  src/chaos_librarian/contract/profiles.py \
  src/chaos_librarian/contract/scenario.py \
  src/chaos_librarian/cli/commands/generate.py \
  src/chaos_librarian/generation.py \
  src/chaos_librarian/generation_lanes.py \
  src/chaos_librarian/generation_planner.py \
  tests/cli/test_generate.py \
  tests/test_generation.py \
  tests/test_generation_properties.py
git commit -m "refactor: simplify fuzz generation review findings"
```
