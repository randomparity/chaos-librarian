# MVP Documentation Implementation Plan

> **Status:** Executed on `docs/mvp-documentation-plan`.
>
> This file is retained as implementation history. Do not execute it as a live
> checklist: adversarial review changed the final docs and guardrails after this
> plan was written. The current files under `README.md`, `docs/`, and
> `tests/docs/` are authoritative.
>
> Review changes after execution:
>
> - The README plan-only quick start no longer runs `capabilities`; plan-only
>   workflows do not require media tools.
> - Docs tests now derive CLI command names, timeline actions, and schema
>   versions from the code instead of duplicating fixed lists.
> - Targeted pytest subset examples use `--no-cov`; the full suite remains the
>   coverage gate.
> - Capability docs distinguish ffmpeg/ffprobe startup requirements from the
>   stricter mkvmerge-backed media-mutation readiness signal.

**Goal:** Build complete MVP user and developer documentation for Chaos Librarian.

**Architecture:** Keep `README.md` as the high-signal project entry point,
`docs/README.md` as the documentation map, `docs/user/` as task-oriented user
guides, `docs/developer/` as implementation and contribution guidance, and
`docs/contract/` as stable consumer contract reference. Add lightweight pytest
checks so the quick-start path, command list, and known stale contract language
cannot drift silently.

**Tech Stack:** Markdown, existing Typer CLI, existing pytest suite, Python 3.13,
`uv`, `ruff`, `ty`, checked-in JSON Schema artifacts under `schemas/`.

---

## Current Findings To Fix

- `README.md` is only a two-sentence pointer and does not support MVP adoption.
- `docs/contract/cli-reference.md` says `run` is a stub, but
  `src/chaos_librarian/cli/commands/run.py` implements wall-clock mode.
- `docs/contract/manifest-initial-state.md` recommends `add_file` at `t=0`
  for custom initial paths, but validation rejects `add_file` on an already
  placed asset. Use `move_asset` at `t=0` for that authoring pattern.
- `docs/contract/fixture-layout.md` still describes `reports/` as written by
  later sprint work. The writer emits reports for plan fixtures now.
- Scenario authoring details live mostly in code and fixtures instead of a
  user-facing guide.
- Developer architecture exists in historical sprint plans, but there is no
  current implementation-oriented developer guide.

## Success Criteria

- A new user can install dependencies, validate a scenario, create a plan-only
  fixture, inspect it, and understand generated artifacts from `README.md`.
- A user with media tools can discover capability requirements and run
  `materialize` or `run` without reading source code.
- A consumer implementer can find schema contracts, fixture layout, observed
  state format, divergence report format, and compare workflows from
  `docs/README.md`.
- A contributor can understand package layout, validation, timeline planning,
  materialization, adapter comparison, schema export, and verification commands.
- Docs-specific tests fail before the documentation changes and pass after the
  documentation changes.
- Existing project verification remains clean.

## File Structure

- Modify: `README.md` - concise project pitch, feature summary, quick start,
  command map, output overview, links into `docs/`.
- Create: `docs/README.md` - documentation front door.
- Create: `docs/user/installation.md` - prerequisites and setup.
- Create: `docs/user/quickstart.md` - executable first fixture flow.
- Create: `docs/user/scenario-authoring.md` - scenario YAML model and actions.
- Create: `docs/user/commands.md` - task-oriented CLI usage.
- Create: `docs/user/run-artifacts.md` - run directory and artifact meanings.
- Create: `docs/user/integration.md` - scanner/prober/watcher comparison flow.
- Create: `docs/user/troubleshooting.md` - exit codes and common failures.
- Create: `docs/developer/architecture.md` - current module architecture.
- Create: `docs/developer/contracts-and-schemas.md` - Pydantic and schema flow.
- Create: `docs/developer/validation-pipeline.md` - validation layers and rules.
- Create: `docs/developer/timeline-engine.md` - resolver, events, journal, step.
- Create: `docs/developer/materializer.md` - media tooling and phase-B effects.
- Create: `docs/developer/adapter-compare.md` - observed-state compare internals.
- Create: `docs/developer/testing.md` - local verification and test layout.
- Create: `docs/developer/release-checklist.md` - pre-merge release checks.
- Modify: `docs/contract/cli-reference.md` - make command reference current.
- Modify: `docs/contract/fixture-layout.md` - make report/layout language current.
- Modify: `docs/contract/manifest-initial-state.md` - replace bad `add_file`
  custom-path guidance.
- Modify: `docs/contract/schema-reference.md` - list all current schema versions.
- Create: `tests/docs/__init__.py` - test package marker.
- Create: `tests/docs/test_documentation.py` - documentation smoke checks.

## Task 1: Documentation Guardrail Tests

**Files:**
- Create: `tests/docs/__init__.py`
- Create: `tests/docs/test_documentation.py`

- [ ] **Step 1: Confirm branch state**

Run:

```bash
git status --short --branch
```

Expected: current branch is `docs/mvp-documentation-plan`, with no unrelated
local edits.

- [ ] **Step 2: Create the docs test package**

Create `tests/docs/__init__.py` as an empty file.

- [ ] **Step 3: Add documentation smoke tests**

Create `tests/docs/test_documentation.py` with exactly this content:

```python
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "README.md"
DOCS = ROOT / "docs"


USER_DOCS = [
    "user/installation.md",
    "user/quickstart.md",
    "user/scenario-authoring.md",
    "user/commands.md",
    "user/run-artifacts.md",
    "user/integration.md",
    "user/troubleshooting.md",
]

DEVELOPER_DOCS = [
    "developer/architecture.md",
    "developer/contracts-and-schemas.md",
    "developer/validation-pipeline.md",
    "developer/timeline-engine.md",
    "developer/materializer.md",
    "developer/adapter-compare.md",
    "developer/testing.md",
    "developer/release-checklist.md",
]

CLI_COMMANDS = [
    "validate",
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

TIMELINE_ACTIONS = [
    "move_asset",
    "rename_file",
    "delete_file",
    "add_file",
    "reencode_video",
    "reencode_audio",
    "create_sidecar",
    "slow_copy_start",
    "slow_copy_commit",
    "archive_file",
    "move_between_roots",
    "remux_container",
    "edit_metadata",
    "embed_subtitle",
    "extract_subtitle",
    "remove_sidecar",
    "update_sidecar",
    "corrupt_container_header",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_readme_contains_mvp_quickstart_and_feature_map() -> None:
    text = _read(README)

    required_snippets = [
        "Scenario-driven synthetic media library simulator",
        "## Features",
        "## Quick Start",
        "uv sync",
        "uv run chaos-librarian capabilities --json",
        "uv run chaos-librarian validate tests/fixtures/scenarios/static-library.yaml --json",
        "uv run chaos-librarian plan tests/fixtures/scenarios/static-library.yaml",
        "uv run chaos-librarian inspect \"$RUN_DIR\" --json",
        "## Documentation",
        "docs/README.md",
    ]
    for snippet in required_snippets:
        assert snippet in text


def test_docs_index_links_to_user_and_developer_guides() -> None:
    docs_index = DOCS / "README.md"
    expected_paths = [*USER_DOCS, *DEVELOPER_DOCS]
    missing = [
        relative_path
        for relative_path in expected_paths
        if not (DOCS / relative_path).is_file()
    ]

    assert docs_index.is_file(), "docs/README.md is missing"
    assert not missing, f"missing documentation files: {missing}"

    text = _read(DOCS / "README.md")

    for relative_path in expected_paths:
        assert f"]({relative_path})" in text, relative_path


def test_contract_cli_reference_matches_current_cli_surface() -> None:
    text = _read(DOCS / "contract" / "cli-reference.md")

    for command in CLI_COMMANDS:
        assert f"chaos-librarian {command}" in text
    assert "`run` remains a stub" not in text
    assert "stub" not in text.lower()
    assert "--duration" in text
    assert "--speed" in text


def test_contract_docs_do_not_preserve_known_stale_guidance() -> None:
    fixture_layout = _read(DOCS / "contract" / "fixture-layout.md")
    initial_state = _read(DOCS / "contract" / "manifest-initial-state.md")

    assert (
        "`reports/` are written by plan, materialize, and run outputs."
        in fixture_layout
    )
    assert "written by later" not in fixture_layout
    assert "add_file` timeline event at `t=0`" not in initial_state
    assert "`move_asset` timeline event at `t=0`" in initial_state


def test_user_docs_cover_commands_and_timeline_actions() -> None:
    commands_path = DOCS / "user" / "commands.md"
    scenario_path = DOCS / "user" / "scenario-authoring.md"

    assert commands_path.is_file(), "docs/user/commands.md is missing"
    assert scenario_path.is_file(), "docs/user/scenario-authoring.md is missing"

    commands = _read(commands_path)
    scenario = _read(scenario_path)

    for command in CLI_COMMANDS:
        assert command in commands
    for action in TIMELINE_ACTIONS:
        assert action in scenario
```

- [ ] **Step 4: Run the tests and confirm they fail for the current docs**

Run:

```bash
uv run pytest tests/docs/test_documentation.py -q
```

Expected: FAIL. The failure output should include the missing `docs/README.md`
assertion, the missing documentation file list, README quick-start snippets,
and stale contract text.

- [ ] **Step 5: Leave the failing docs tests uncommitted**

Do not commit after this task. The docs tests are intentionally red until the
documentation files are written, and this project should not record an
intermediate commit whose relevant tests fail. Keep `tests/docs/` in the working
tree and continue to Task 2.

Expected: `git status --short` shows uncommitted `tests/docs/__init__.py` and
`tests/docs/test_documentation.py`.

## Task 2: Root README

**Files:**
- Modify: `README.md`
- Test: `tests/docs/test_documentation.py`

- [ ] **Step 1: Replace the existing README**

Replace `README.md` with a concise entry point using these exact top-level
sections:

````markdown
# Chaos Librarian

Scenario-driven synthetic media library simulator for testing scanners,
watchers, media probes, durable identity, bundle tracking, and reconciliation.

Chaos Librarian creates deterministic media-library fixtures from YAML
scenarios. It can stop at an oracle-only plan, materialize real media files,
advance mutations step by step, run wall-clock churn for daemons, and compare a
consumer export back to the neutral oracle it produced.

## Features

- Deterministic oracle fixtures: scenario YAML becomes manifests, a JSONL
  journal, replay metadata, and per-entity reports.
- Plan-only mode: validate scenario behavior without creating media files.
- Real media materialization: synthesize media with ffmpeg and probe it with
  ffprobe.
- Controlled mutation timelines: moves, renames, deletes, slow copies,
  sidecars, re-encodes, remuxes, metadata edits, subtitle operations, and
  malformed-media corruption.
- Step and wall-clock execution: choose exact assertion points for tests or
  timed churn for daemon/watch workflows.
- Consumer-neutral comparison: export observed state from an application and
  compare it with `chaos-librarian compare`.
- Schema-first contracts: checked-in JSON Schema artifacts under `schemas/`
  define the public contract.

## Requirements

- Python 3.13 or newer.
- `uv` for dependency management and local command execution.
- For plan-only workflows: no media tools are required.
- For materialize and run workflows: ffmpeg 7.0+, ffprobe 7.0+, and, for media
  mutation readiness, mkvmerge from MKVToolNix 80+.

Check local media-tool readiness:

```bash
uv run chaos-librarian capabilities --json
```

## Quick Start

```bash
uv sync
uv run chaos-librarian capabilities --json

RUN_DIR="$(mktemp -d)/chaos-static-library"

uv run chaos-librarian validate tests/fixtures/scenarios/static-library.yaml --json
uv run chaos-librarian plan tests/fixtures/scenarios/static-library.yaml --out "$RUN_DIR" --json
uv run chaos-librarian inspect "$RUN_DIR" --json
```

The plan command writes a self-contained fixture directory with
`scenario.yaml`, `manifest.initial.json`, `manifest.current.json`,
`journal.jsonl`, `replay.json`, `validation.json`, per-entity reports, and the
`.chaos-librarian-run` sentinel.

## Common Workflows

| Need | Command |
|------|---------|
| Validate a scenario | `uv run chaos-librarian validate scenario.yaml --json` |
| Plan without media files | `uv run chaos-librarian plan scenario.yaml --out run-dir --json` |
| Create real media | `uv run chaos-librarian materialize scenario.yaml --out run-dir --json` |
| Run wall-clock churn | `uv run chaos-librarian run scenario.yaml --out run-dir --duration 90s --speed 10x --json` |
| Advance a step fixture | `uv run chaos-librarian step run-dir --next 1 --json` |
| Replay a recorded run | `uv run chaos-librarian replay run-dir/replay.json --out replay-dir --json` |
| Inspect a run directory | `uv run chaos-librarian inspect run-dir --json` |
| Compare consumer output | `uv run chaos-librarian compare run-dir observed-state.json --mode final-state --json` |
| Remove a run directory | `uv run chaos-librarian clean run-dir --json` |

## Documentation

- [Documentation index](docs/README.md)
- [Installation](docs/user/installation.md)
- [Quick start](docs/user/quickstart.md)
- [Scenario authoring](docs/user/scenario-authoring.md)
- [CLI commands](docs/user/commands.md)
- [Run artifacts](docs/user/run-artifacts.md)
- [Integration guide](docs/user/integration.md)
- [Developer architecture](docs/developer/architecture.md)
- [Contract reference](docs/contract/schema-reference.md)

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Pydantic models in `src/chaos_librarian/contract/` are the schema source of
truth. After editing a contract model, regenerate checked-in schemas with:

```bash
uv run python -m chaos_librarian.schema_export --write
```
````

- [ ] **Step 2: Run the README-focused test**

Run:

```bash
uv run pytest tests/docs/test_documentation.py::test_readme_contains_mvp_quickstart_and_feature_map -q
```

Expected: PASS.

- [ ] **Step 3: Checkpoint README without committing**

Run:

```bash
git status --short
```

Expected: `README.md` and `tests/docs/` remain uncommitted. Do not commit yet:
the full docs smoke test still expects files that later tasks create.

## Task 3: User Documentation

**Files:**
- Create: `docs/README.md`
- Create: `docs/user/installation.md`
- Create: `docs/user/quickstart.md`
- Create: `docs/user/scenario-authoring.md`
- Create: `docs/user/commands.md`
- Create: `docs/user/run-artifacts.md`
- Create: `docs/user/integration.md`
- Create: `docs/user/troubleshooting.md`
- Test: `tests/docs/test_documentation.py`

- [ ] **Step 1: Create the documentation index**

Create `docs/README.md` with sections named exactly:

```markdown
# Chaos Librarian Documentation

Start with the user guides when you want to run fixtures. Use the contract
reference when integrating another application. Use the developer guides when
changing Chaos Librarian itself.

## User Guides

- [Installation](user/installation.md)
- [Quick start](user/quickstart.md)
- [Scenario authoring](user/scenario-authoring.md)
- [Commands](user/commands.md)
- [Run artifacts](user/run-artifacts.md)
- [Integration](user/integration.md)
- [Troubleshooting](user/troubleshooting.md)

## Developer Guides

- [Architecture](developer/architecture.md)
- [Contracts and schemas](developer/contracts-and-schemas.md)
- [Validation pipeline](developer/validation-pipeline.md)
- [Timeline engine](developer/timeline-engine.md)
- [Materializer](developer/materializer.md)
- [Adapter compare](developer/adapter-compare.md)
- [Testing](developer/testing.md)
- [Release checklist](developer/release-checklist.md)

## Contract Reference

- [CLI reference](contract/cli-reference.md)
- [Schema reference](contract/schema-reference.md)
- [Fixture layout](contract/fixture-layout.md)
- [Replay bundle](contract/replay-bundle.md)
- [Time model](contract/time-model.md)
- [Manifest initial state](contract/manifest-initial-state.md)
- [Observed-state contract](contract/observed-state.md)
- [Divergence report](contract/divergence-report.md)
- [Integration recipes](contract/integration-recipes.md)

## Historical Design Material

Historical sprint specs and execution plans live under `docs/superpowers/`.
They are useful design history, not the first place to learn current usage.
```

- [ ] **Step 2: Create `docs/user/installation.md`**

Include these sections and facts:

````markdown
# Installation

## Prerequisites

- Python 3.13 or newer.
- `uv`.
- ffmpeg 7.0+ and ffprobe 7.0+ for `materialize` and `run`.
- mkvmerge from MKVToolNix 80+ for full media-mutation readiness.

## Project Setup

```bash
uv sync
uv run chaos-librarian --help
```

## Capability Check

```bash
uv run chaos-librarian capabilities --json
```

Read `ready_for.materialize_static`,
`ready_for.materialize_filesystem_mutations`, and
`ready_for.materialize_media_mutations` before enabling media-heavy tests in CI.

## Plan-Only Setup

Plan-only workflows require only Python dependencies. Use `plan` when the
machine does not have media tools or when authoring scenario behavior before
generating real files.
````

- [ ] **Step 3: Create `docs/user/quickstart.md`**

Include a complete plan-only flow, a media flow, and cleanup:

````markdown
# Quick Start

## Plan-Only Fixture

```bash
uv sync
RUN_DIR="$(mktemp -d)/chaos-static-library"
uv run chaos-librarian validate tests/fixtures/scenarios/static-library.yaml --json
uv run chaos-librarian plan tests/fixtures/scenarios/static-library.yaml --out "$RUN_DIR" --json
uv run chaos-librarian inspect "$RUN_DIR" --json
```

Open `manifest.current.json` to see the expected final library state and
`journal.jsonl` to see the oracle event stream.

## Materialized Fixture

```bash
uv run chaos-librarian capabilities --json
MEDIA_RUN_DIR="$(mktemp -d)/chaos-materialized-static"
uv run chaos-librarian materialize tests/fixtures/scenarios/static-library.yaml --out "$MEDIA_RUN_DIR" --json
```

The `library/` directory contains generated media files. The manifest versions
include hashes and probed media facts when probing succeeds.

## Wall-Clock Fixture

```bash
CHURN_RUN_DIR="$(mktemp -d)/chaos-active-library-churn"
uv run chaos-librarian run tests/fixtures/scenarios/active-library-churn.yaml --out "$CHURN_RUN_DIR" --duration 30s --speed 10x --json
```

Use wall-clock mode when the application under test watches the filesystem over
time.

## Cleanup

```bash
uv run chaos-librarian clean "$RUN_DIR" --json
```

`clean` only removes directories protected by `.chaos-librarian-run`.
````

- [ ] **Step 4: Create `docs/user/scenario-authoring.md`**

Document the current scenario model with:

- Required top-level keys: `schema_version: 7`, `scenario_id`, `seed`,
  `duration_scale`, optional `profiles`, `library`, `works`, `timeline`.
- Library roots are scenario-relative authoring roots and resolve under
  `<run-dir>/library/`.
- Work topology is `works -> variants -> bundle -> assets`.
- Asset tracks: video source values `mandelbrot`, `color_bars`,
  `solid_color`, `noise`; audio source values `sine`, `silence`,
  `channel_tones`; subtitle source `generated_srt`.
- State that `noise` validates but is not materialize-ready.
- Timeline actions table with required fields:
  `move_asset(target,to)`, `rename_file(target,to)`,
  `delete_file(target)`, `add_file(target,to)`,
  `reencode_video(target,resolution,codec)`,
  `reencode_audio(target,from_channels,to_channels)`,
  `create_sidecar(target,to,kind,language)`,
  `slow_copy_start(target,to,temp_path,duration)`,
  `slow_copy_commit(for)`, `archive_file(target)`,
  `move_between_roots(target,from_root_id,to_root_id)`,
  `remux_container(target,to_container)`,
  `edit_metadata(target,fields)`,
  `embed_subtitle(target,sidecar_path)`,
  `extract_subtitle(target,to,language)`,
  `remove_sidecar(target,sidecar_path)`,
  `update_sidecar(target,sidecar_path)`,
  `corrupt_container_header(target,bytes)`.
- Profile section: `corrupt_container_header` requires
  `profiles: [malformed-media]`.
- Include a minimal scenario copied from `tests/fixtures/scenarios/static-library.yaml`
  and a mutation example from `tests/fixtures/scenarios/delete-add-restore.yaml`.

- [ ] **Step 5: Create `docs/user/commands.md`**

Document all ten commands with one subsection per command:

- `validate SCENARIO [--json]`
- `plan SCENARIO --out RUN_DIR [--steps N] [--json]`
- `materialize SCENARIO --out RUN_DIR [--json]`
- `run SCENARIO --out RUN_DIR --duration DURATION [--speed MULTIPLIER] [--json]`
- `step RUN_DIR [--next N] [--json]`
- `replay BUNDLE --out RUN_DIR [--against ORIGINAL_RUN_DIR] [--json]`
- `inspect RUN_DIR [--json]`
- `capabilities [--json]`
- `clean RUN_DIR [--json]`
- `compare RUN_DIR OBSERVED --mode final-state|identity-history [--json]`

Include the exit-code table from the contract reference and route detailed
contract information back to `docs/contract/cli-reference.md`.

- [ ] **Step 6: Create `docs/user/run-artifacts.md`**

Explain:

- `.chaos-librarian-run` sentinel and why `clean` requires it.
- `scenario.yaml` is the stored source scenario.
- `replay.json` reproduces the run.
- `manifest.initial.json` is state before timeline events.
- `manifest.current.json` is expected final/current state.
- `journal.jsonl` is the append-only oracle event stream.
- `validation.json` records validation outcome.
- `materialization.json` exists for media-producing runs.
- `reports/assets`, `reports/works`, `reports/variants`, and
  `reports/bundles` contain per-entity projections.
- `library/` contains real files for materialize and run outputs.

- [ ] **Step 7: Create `docs/user/integration.md`**

Explain:

- Chaos Librarian does not know the consumer database schema.
- Consumers export `observed-state.json` using the observed-state contract.
- Scanner/prober final-state flow:

```bash
uv run chaos-librarian compare run-dir observed-state.json --mode final-state --json
```

- Watcher identity-history flow:

```bash
uv run chaos-librarian compare run-dir observed-state.json --mode identity-history --json
```

- Exit `0` means match, exit `6` means comparison completed with divergence,
  exit `1` means adapter input error, and exit `7` means sentinel failure.

- [ ] **Step 8: Create `docs/user/troubleshooting.md`**

Include entries for:

- `E_YAML_PARSE`: read the reported scenario path and YAML parse message.
- `E_FIELD_MISSING`, `E_FIELD_UNKNOWN`, `E_FIELD_LITERAL`, `E_FIELD_TYPE`:
  fix the scenario shape.
- `E_PATH_CONTAINMENT`: keep all paths under `<run-dir>/library/`.
- `E_LIFECYCLE_INVALID`: check add/delete/move/slow-copy event ordering.
- Exit `4`: install or upgrade ffmpeg/ffprobe.
- Exit `5`: inspect `materialization.json` and tool invocation details.
- Exit `6`: inspect replay or compare divergence output.
- Exit `7`: verify the run directory has a valid `.chaos-librarian-run`.

- [ ] **Step 9: Run user-doc tests**

Run:

```bash
uv run pytest tests/docs/test_documentation.py::test_user_docs_cover_commands_and_timeline_actions -q
```

Expected: PASS.

Then run:

```bash
uv run pytest tests/docs/test_documentation.py::test_docs_index_links_to_user_and_developer_guides -q
```

Expected: FAIL until the developer docs exist; the user-doc files should no
longer be listed as missing.

- [ ] **Step 10: Checkpoint user docs without committing**

Run:

```bash
git status --short
```

Expected: `README.md`, `docs/README.md`, `docs/user/`, and `tests/docs/` remain
uncommitted. Do not commit yet because the docs smoke test is still expected to
fail until developer docs are written.

## Task 4: Developer Documentation

**Files:**
- Create: `docs/developer/architecture.md`
- Create: `docs/developer/contracts-and-schemas.md`
- Create: `docs/developer/validation-pipeline.md`
- Create: `docs/developer/timeline-engine.md`
- Create: `docs/developer/materializer.md`
- Create: `docs/developer/adapter-compare.md`
- Create: `docs/developer/testing.md`
- Create: `docs/developer/release-checklist.md`
- Test: `tests/docs/test_documentation.py`

- [ ] **Step 1: Create `docs/developer/architecture.md`**

Include a current module map:

- `contract/`: Pydantic source of truth for public schemas.
- `validation/`: YAML input preparation, shape validation, semantic rules.
- `determinism/`: seed resolution, RNG streams, clock, ID allocation, trace.
- `engine/`: plan-only timeline resolution, event handling, journal, reports,
  replay verification, step mode, fixture writer.
- `materializer/`: capability gate, content sources, ffmpeg synthesis, phase-B
  filesystem/media/corruption effects, wall-clock runner.
- `adapter/`: fixture loader, observed-state loader, matching, compare reports.
- `cli/`: Typer command modules.

Add a data-flow diagram in text:

```text
scenario.yaml
  -> prepare_run_input
  -> run_validation
  -> resolve_timeline
  -> run_plan or materialize_scenario or run_wall_clock_scenario
  -> fixture directory
  -> compare against observed-state.json
```

- [ ] **Step 2: Create `docs/developer/contracts-and-schemas.md`**

Explain:

- Pydantic v2 models in `src/chaos_librarian/contract/` are source of truth.
- `schema_export.py` writes JSON Schema draft 2020-12 artifacts under
  `schemas/`.
- Run `uv run python -m chaos_librarian.schema_export --write` after contract
  model edits.
- Run `uv run python -m chaos_librarian.schema_export --check` before commit.
- Schema-version constants live in `contract/__init__.py` and are breaking
  versions.
- Discriminated unions intentionally export as `oneOf` with `discriminator`.

- [ ] **Step 3: Create `docs/developer/validation-pipeline.md`**

Explain:

- `prepare_run_input` preserves raw YAML bytes and parsed scenario.
- Shape validation maps Pydantic errors to stable `E_*` codes.
- Semantic validation rules live under `validation/rules/`.
- New rules should be small modules with focused tests under
  `tests/validation/rules/`.
- Invalid fixtures under `tests/fixtures/scenarios/invalid/` must start with
  `# expected: E_<CODE>`.
- Lifecycle checks reject invalid event ordering such as `add_file` on a
  placed asset and operations after delete.

- [ ] **Step 4: Create `docs/developer/timeline-engine.md`**

Explain:

- `resolve_timeline` sorts by logical time and declaration order.
- `step_boundaries` treats adjacent `slow_copy_start` and `slow_copy_commit`
  pairs as one user-visible step.
- `engine/events.py` handlers return journal entries and state deltas.
- `write_fixture` publishes plan fixtures atomically via a staging directory.
- `append_step` rewrites mutable files atomically per file and appends journal
  lines.
- `replay_plan_bundle` verifies deterministic plan output.

- [ ] **Step 5: Create `docs/developer/materializer.md`**

Explain:

- `detect_capabilities` checks ffmpeg, ffprobe, and mkvmerge.
- Static materialization requires ffmpeg and ffprobe.
- Full media mutation readiness also requires mkvmerge.
- `content_sources.py` maps scenario source names to deterministic inputs.
- Initial synthesis writes real files and probes them.
- Phase-B applies filesystem, media, sidecar, and corruption actions.
- Wall-clock mode shares validation and timeline semantics with materialize.

- [ ] **Step 6: Create `docs/developer/adapter-compare.md`**

Explain:

- `load_fixture` reads oracle artifacts from a run directory.
- `load_observed_state` validates consumer JSON.
- `compare_fixture_to_observed` emits `DivergenceReport`.
- `final-state` checks current assets, paths, hashes, probed fields, sidecars,
  and topology when supplied.
- `identity-history` also checks lifecycle evidence through path history or
  global observed events.

- [ ] **Step 7: Create `docs/developer/testing.md`**

Include these commands:

```bash
uv run pytest
uv run pytest tests/cli/test_plan.py -q
uv run pytest tests/validation/rules/test_timeline_lifecycle.py -q
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
prek run --all-files
```

Explain that real-tool integration tests may skip when required media tools are
not available, but skipped tests must be visible in pytest output.

- [ ] **Step 8: Create `docs/developer/release-checklist.md`**

Include:

- Re-read documentation and code changes for stale sprint-era language.
- Run targeted tests for touched areas.
- Run `uv run pytest tests/docs -q`.
- Run ruff, format check, ty, and schema drift check.
- Run `prek run --all-files`.
- Confirm no checked-in generated files are stale.
- Confirm `README.md` and `docs/README.md` link to new public docs.

- [ ] **Step 9: Run docs index tests**

Run:

```bash
uv run pytest tests/docs/test_documentation.py::test_docs_index_links_to_user_and_developer_guides -q
```

Expected: PASS.

- [ ] **Step 10: Checkpoint developer docs without committing**

Run:

```bash
git status --short
```

Expected: `README.md`, `docs/README.md`, `docs/user/`, `docs/developer/`, and
`tests/docs/` remain uncommitted. Do not commit yet because the contract docs
still need reconciliation before the full docs smoke test is green.

## Task 5: Contract Documentation Reconciliation

**Files:**
- Modify: `docs/contract/cli-reference.md`
- Modify: `docs/contract/fixture-layout.md`
- Modify: `docs/contract/manifest-initial-state.md`
- Modify: `docs/contract/schema-reference.md`
- Test: `tests/docs/test_documentation.py`

- [ ] **Step 1: Rewrite `docs/contract/cli-reference.md`**

Keep the command block, exit-code table, and contract tone. Remove sprint status
language. Add command details for `run --duration` and `--speed`. Include this
sentence:

```markdown
`run` is the wall-clock materialization command; it applies the same logical
timeline as step mode over elapsed wall-clock time.
```

- [ ] **Step 2: Update `docs/contract/fixture-layout.md`**

Replace the stale plan-only subset paragraph with:

```markdown
Plan-only runs write every oracle artifact except `materialization.json` and
`library/`. The `reports/` tree is part of plan output and is updated by
`step`.

`reports/` are written by plan, materialize, and run outputs.
```

- [ ] **Step 3: Update `docs/contract/manifest-initial-state.md`**

Replace the bad custom-path guidance with:

```markdown
Authors who want a custom starting path should declare the asset normally and
add a `move_asset` timeline event at `t=0`. Do not use `add_file` for this:
`add_file` represents restoration of an asset that is currently absent and
validation rejects `add_file` on an already-placed asset.
```

- [ ] **Step 4: Update `docs/contract/schema-reference.md`**

Expand the current version table to list all constants from
`src/chaos_librarian/contract/__init__.py`:

```markdown
| artifact | schema_version |
|----------|----------------|
| scenario | 7 |
| manifest | 5 |
| journal | 1 |
| replay bundle | 6 |
| validation | 1 |
| materialization | 7 |
| run sentinel | 2 |
| asset report | 5 |
| work report | 1 |
| variant report | 1 |
| bundle report | 1 |
| capabilities | 2 |
| observed state | 1 |
| divergence | 1 |
```

- [ ] **Step 5: Run contract docs tests**

Run:

```bash
uv run pytest tests/docs/test_documentation.py::test_contract_cli_reference_matches_current_cli_surface tests/docs/test_documentation.py::test_contract_docs_do_not_preserve_known_stale_guidance -q
```

Expected: PASS.

- [ ] **Step 6: Run the full docs tests and commit the complete documentation change**

Run:

```bash
uv run pytest tests/docs -q
```

Expected: PASS.

Then commit all documentation and docs-test changes in one logical commit:

Run:

```bash
git add README.md docs/README.md docs/user docs/developer \
  docs/contract/cli-reference.md docs/contract/fixture-layout.md \
  docs/contract/manifest-initial-state.md docs/contract/schema-reference.md \
  tests/docs
git commit -m "docs: add MVP user and developer documentation"
```

Expected: one commit containing the README rewrite, new user docs, new developer
docs, refreshed contract docs, and docs smoke tests.

## Task 6: Final Verification

**Files:**
- Verify all changed docs and tests.

- [ ] **Step 1: Run docs tests**

Run:

```bash
uv run pytest tests/docs -q
```

Expected: PASS.

- [ ] **Step 2: Run focused existing tests for touched surfaces**

Run:

```bash
uv run pytest tests/cli tests/contract tests/validation/rules/test_timeline_lifecycle.py -q
```

Expected: PASS.

- [ ] **Step 3: Run static checks**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Expected: all commands pass with no warnings or schema drift.

- [ ] **Step 4: Review changed files**

Run:

```bash
git diff --stat origin/main...HEAD
git diff --check origin/main...HEAD
```

Expected: documentation-focused diff, no whitespace errors.

- [ ] **Step 5: Squash final cleanup into the single documentation commit if needed**

If Step 3 or Step 4 required small wording or formatting fixes, amend the single
documentation commit instead of creating a second commit:

```bash
git add README.md docs/README.md docs/user docs/developer \
  docs/contract/cli-reference.md docs/contract/fixture-layout.md \
  docs/contract/manifest-initial-state.md docs/contract/schema-reference.md \
  tests/docs
git commit --amend --no-edit
```

Expected: branch history contains one documentation change commit on top of the
base branch.

## Self-Review

- Spec coverage: root README, quick start, feature summary, detailed docs link,
  architecture docs, setup and usage docs, and developer docs are all mapped to
  tasks.
- Stale docs found during review are mapped to Task 5.
- Guardrails are mapped to Task 1 and final verification.
- Type consistency: test names, file paths, and command names match the planned
  documentation tree and current CLI surface.
