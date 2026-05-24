# Issue #74 Fuzz Profile Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic, bounded fuzz profile generation with explicit
scenario YAML output, serialized generation metadata, and replay through the
existing execution commands.

**Architecture:** Add profile labels and generation metadata to the scenario
contract, then implement a pure generator that emits normal scenario YAML. The
CLI writes that YAML atomically; validation enforces static fuzz budgets; replay
continues to use the scenario source embedded in `replay.json`.

**Tech Stack:** Python 3.13, Pydantic v2, Typer, ruamel.yaml, pytest, ruff, ty.

---

## Source Inputs

- GitHub issue: [#74](https://github.com/randomparity/chaos-librarian/issues/74)
- Design spec:
  `docs/superpowers/specs/2026-05-24-issue-74-fuzz-profile-generation-design.md`
- Source design: `docs/specs/chaos-librarian-design.md`
- Existing CLI command pattern: `src/chaos_librarian/cli/commands/plan.py`
- Existing profile budget rule:
  `src/chaos_librarian/validation/rules/profile_budgets.py`

## File Structure

Create:

```text
src/chaos_librarian/generation.py
src/chaos_librarian/cli/commands/generate.py
tests/test_generation.py
tests/cli/test_generate.py
tests/fixtures/scenarios/fuzz-smoke-seed-123.yaml
tests/fixtures/scenarios/fuzz-regression-seed-456.yaml
```

Modify:

```text
src/chaos_librarian/contract/__init__.py
src/chaos_librarian/contract/profiles.py
src/chaos_librarian/contract/scenario.py
src/chaos_librarian/validation/rules/profile_budgets.py
src/chaos_librarian/cli/commands/__init__.py
tests/contract/test_contract_constants.py
tests/contract/test_scenario.py
tests/validation/rules/test_profile_budgets.py
tests/cli/test_app.py
tests/docs/test_documentation.py
tests/fixtures/scenarios/**/*.yaml
schemas/*.schema.json
docs/specs/chaos-librarian-design.md
docs/contract/cli-reference.md
docs/contract/integration-recipes.md
docs/contract/schema-reference.md
docs/developer/testing.md
```

## Task 1: Contract And Metadata

**Files:**

- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/profiles.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `tests/contract/test_contract_constants.py`
- Modify: `tests/contract/test_scenario.py`

- [ ] **Step 1: Write failing contract tests**

Add these tests:

- `test_scenario_accepts_fuzz_generation_metadata`
- `test_generation_profile_must_be_top_level_profile`
- `test_generation_rejects_seed_random`
- `test_generation_seed_must_match_scenario_seed`
- `test_generation_budget_must_match_profile`

Use `Model.model_validate(payload)` for negative tests.

- [ ] **Step 2: Verify contract tests fail**

Run:

```bash
uv run pytest tests/contract/test_scenario.py -q --no-cov
```

Expected: failures for unknown `generation`, unknown fuzz labels, or missing
model classes.

- [ ] **Step 3: Implement contract models**

Add to `contract/profiles.py`:

```python
class FuzzProfileName(enum.StrEnum):
    FUZZ_SMOKE = "fuzz-smoke"
    FUZZ_REGRESSION = "fuzz-regression"
```

Also add `FUZZ_SMOKE = "fuzz-smoke"` and
`FUZZ_REGRESSION = "fuzz-regression"` to the existing `ProfileName` enum.

Add to `contract/scenario.py`:

```python
class GenerationBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    works: int = Field(ge=0)
    variants: int = Field(ge=0)
    bundles: int = Field(ge=0)
    assets: int = Field(ge=0)
    sidecars: int = Field(ge=0)
    timeline_events: int = Field(ge=0)


class ScenarioGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generator: Literal["chaos-librarian"] = "chaos-librarian"
    profile: FuzzProfileName
    profile_version: int = Field(ge=1)
    seed: int = Field(ge=0)
    budgets: GenerationBudget
```

Add canonical fuzz budgets and a `Scenario` model validator for profile, seed,
and budget invariants. Bump `SCENARIO_SCHEMA_VERSION` and
`Scenario.schema_version` from `9` to `10`.

- [ ] **Step 4: Verify contract tests pass**

Run:

```bash
uv run pytest tests/contract/test_scenario.py \
  tests/contract/test_contract_constants.py -q --no-cov
```

Expected: pass.

## Task 2: Fuzz Budget Validation

**Files:**

- Modify: `src/chaos_librarian/validation/rules/profile_budgets.py`
- Modify: `tests/validation/rules/test_profile_budgets.py`

- [ ] **Step 1: Write failing validation tests**

Add tests proving `fuzz-smoke` rejects 5 assets and 13 timeline events, and
`fuzz-regression` accepts the same small case.

- [ ] **Step 2: Verify validation tests fail**

Run:

```bash
uv run pytest tests/validation/rules/test_profile_budgets.py -q --no-cov
```

Expected: fuzz profile budget tests fail because the budget rule ignores the new
labels.

- [ ] **Step 3: Implement fuzz budgets**

Extend `_PERFORMANCE_BUDGETS` or rename it to `_STATIC_PROFILE_BUDGETS` and add:

```python
ProfileName.FUZZ_SMOKE.value: _StaticBudget(
    assets=4, works=3, variants=4, bundles=4, sidecars=8, timeline_events=12
)
ProfileName.FUZZ_REGRESSION.value: _StaticBudget(
    assets=18, works=12, variants=18, bundles=18, sidecars=54, timeline_events=80
)
```

- [ ] **Step 4: Verify validation tests pass**

Run:

```bash
uv run pytest tests/validation/rules/test_profile_budgets.py -q --no-cov
```

Expected: pass.

## Task 3: Generator Core

**Files:**

- Create: `src/chaos_librarian/generation.py`
- Create: `tests/test_generation.py`

- [ ] **Step 1: Write failing generator tests**

Add these tests:

- `test_generate_same_profile_and_seed_is_byte_identical`
- `test_generate_different_seed_changes_yaml`
- `test_generated_yaml_validates_as_scenario`
- `test_atomic_write_rejects_existing_destination`

- [ ] **Step 2: Verify generator tests fail**

Run:

```bash
uv run pytest tests/test_generation.py -q --no-cov
```

Expected: import failure for `chaos_librarian.generation`.

- [ ] **Step 3: Implement generation module**

Implement a focused module with:

```python
def generate_scenario_yaml(profile: FuzzProfileName, seed: int) -> bytes:
    """Return deterministic scenario YAML bytes for one fuzz profile and seed."""


def write_generated_scenario(out: Path, data: bytes) -> None:
    """Atomically write generated scenario bytes without overwriting ``out``."""


def generated_scenario_summary(out: Path, data: bytes) -> str:
    """Return sorted JSON for the successful generate command."""
```

Use `RngStreams(seed, TraceRecorder())` for choices. Build plain Python dicts in
stable key order and serialize with `ruamel.yaml.YAML(typ="rt")`. Atomic write
uses a sibling temp file plus `os.link(temp, out)` so an existing destination is
never overwritten. The generator validates its own YAML through
`Scenario.model_validate` before returning bytes.

- [ ] **Step 4: Verify generator tests pass**

Run:

```bash
uv run pytest tests/test_generation.py -q --no-cov
```

Expected: pass.

## Task 4: CLI Command

**Files:**

- Create: `src/chaos_librarian/cli/commands/generate.py`
- Modify: `src/chaos_librarian/cli/commands/__init__.py`
- Modify: `tests/cli/test_app.py`
- Create: `tests/cli/test_generate.py`

- [ ] **Step 1: Write failing CLI tests**

Add these tests:

- `test_generate_help_succeeds`
- `test_generate_writes_valid_yaml_and_json_summary`
- `test_generate_rejects_existing_out`
- `test_generate_rejects_random_seed`

Update `ALL_COMMANDS` so the expected order is:

```python
[
    "validate",
    "generate",
    "plan",
    "materialize",
    "run",
    "step",
    "replay",
    "inspect",
    "capabilities",
    "clean",
    "compare",
]
```

- [ ] **Step 2: Verify CLI tests fail**

Run:

```bash
uv run pytest tests/cli/test_app.py tests/cli/test_generate.py -q --no-cov
```

Expected: `generate` is not registered.

- [ ] **Step 3: Implement CLI command**

Register:

```python
@app.command()
def generate(
    profile: Annotated[FuzzProfileName, typer.Option("--profile")],
    seed: Annotated[int, typer.Option("--seed", min=0)],
    out: Annotated[Path, typer.Option("--out", callback=validate_new_out_path)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    data = generate_scenario_yaml(profile=profile, seed=seed)
    write_generated_scenario(out, data)
    if json_output:
        typer.echo(generated_scenario_summary(out, data))
    else:
        typer.echo(f"generate: wrote {out}")
```

Human output: `generate: wrote <out>`.
JSON output: sorted JSON containing `ok`, `scenario_path`, `profile`, `seed`,
`scenario_id`, and `sha256`.

- [ ] **Step 4: Verify CLI tests pass**

Run:

```bash
uv run pytest tests/cli/test_app.py tests/cli/test_generate.py -q --no-cov
```

Expected: pass.

## Task 5: Fixtures, Docs, And Schemas

**Files:**

- Create: `tests/fixtures/scenarios/fuzz-smoke-seed-123.yaml`
- Create: `tests/fixtures/scenarios/fuzz-regression-seed-456.yaml`
- Modify: `tests/fixtures/scenarios/*.yaml`
- Modify: `docs/specs/chaos-librarian-design.md`
- Modify: `docs/contract/cli-reference.md`
- Modify: `docs/contract/integration-recipes.md`
- Modify: `docs/contract/schema-reference.md`
- Modify: `docs/developer/testing.md`
- Modify: `tests/docs/test_documentation.py`
- Regenerate: `schemas/*.schema.json`

- [ ] **Step 1: Write failing docs tests**

Add `test_fuzz_profile_generation_docs_are_discoverable` asserting the design
policy, `generate` command, `fuzz-smoke`, `fuzz-regression`, and "Replay never
calls the generator" are documented.

- [ ] **Step 2: Verify docs tests fail**

Run:

```bash
uv run pytest tests/docs/test_documentation.py -q --no-cov
```

Expected: missing fuzz policy/docs assertions fail.

- [ ] **Step 3: Update docs and fixtures**

Update the docs listed above, then generate and commit the two fixtures with:

```bash
uv run chaos-librarian generate --profile fuzz-smoke --seed 123 \
  --out tests/fixtures/scenarios/fuzz-smoke-seed-123.yaml --json
uv run chaos-librarian generate --profile fuzz-regression --seed 456 \
  --out tests/fixtures/scenarios/fuzz-regression-seed-456.yaml --json
```

Bump existing valid and invalid scenario fixtures from `schema_version: 9` to
`10`.

- [ ] **Step 4: Regenerate schemas**

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
```

Expected: checked-in schemas match the updated contract.

- [ ] **Step 5: Verify docs, fixtures, and schema drift**

Run:

```bash
uv run pytest tests/docs/test_documentation.py \
  tests/contract/test_sample_scenarios.py \
  tests/contract/test_schema_export.py -q --no-cov
uv run python -m chaos_librarian.schema_export --check
```

Expected: pass.

## Task 6: Replay Verification And Reviews

**Files:**

- Modify: `tests/cli/test_replay.py`

- [ ] **Step 1: Add generated fixture plan/replay test**

Add or extend a focused test proving `fuzz-smoke-seed-123.yaml` can be planned
and replayed without invoking `chaos_librarian.generation.generate_scenario_yaml`.

- [ ] **Step 2: Verify replay behavior**

Run:

```bash
uv run pytest tests/engine/test_plan_e2e.py tests/cli/test_replay.py -q --no-cov
```

Expected: pass.

- [ ] **Step 3: Run adversarial code review**

Review the working tree for #74. Address material findings. Run no more than
three review rounds.

- [ ] **Step 4: Run simplification review**

Review the final diff for smaller safe design. Address the highest-value
recommendations that preserve the issue scope.

- [ ] **Step 5: Final verification**

Run:

```bash
uv run pytest tests/contract/test_scenario.py \
  tests/validation/rules/test_profile_budgets.py \
  tests/test_generation.py \
  tests/cli/test_app.py \
  tests/cli/test_generate.py \
  tests/docs/test_documentation.py \
  tests/contract/test_sample_scenarios.py \
  tests/contract/test_schema_export.py -q --no-cov
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Expected: all commands pass with no warnings.
