# Sprint 3 — Plan-Only Timeline Engine and `plan` Command

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the `chaos-librarian plan` stub into a real command that consumes a validated scenario, walks its timeline, and writes a bit-identical fixture directory containing the initial + current manifests, the planned journal, the replay bundle, the validation report, the sentinel, and a verbatim copy of the source scenario.

**Architecture:** A new internal `chaos_librarian.engine` package composes Sprint 2 primitives (RNG / IDs / Clock / TraceRecorder) with a small in-memory `WorldState` representation of the expected library. Five focused submodules — `resolution.py`, `state.py`, `events.py`, `plan.py`, `writer.py` — each independently testable. `events.apply_event` is the one place where per-action semantics live; everything else is wiring. Bit-identical plan-only output is enforced by canonicalizing every JSON artifact through one helper that uses Pydantic's `model_dump_json` with stable settings, and locked down by a regression test that runs `plan` twice and byte-compares every output file.

**Tech Stack:** Python 3.13, Pydantic v2 (existing contract models), Typer (existing CLI shell), the Sprint 1 validation pipeline (`run_validation`), and the Sprint 2 determinism package. No new runtime dependencies.

**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md) — §"Plan-Only Mode", §"Execution Modes", §"Time Model", §"Oracle Journal", §"Manifest Model", §"Replay Bundle", §"Reproducibility Guarantees", §"Sprint 3".

**Branch:** `feat/sprint-3` (does not yet exist — Task 0 creates it).

---

## Open Design Decisions Baked Into This Plan

The design doc specifies most of Sprint 3 but leaves a few semantic questions open. This plan resolves each with a default below; flag if you disagree before Task 3 lands.

1. **Initial asset locations.** Scenario `works[*].variants[*].bundle.assets[*]` items have no `path:` field, yet `identity-move-rename.yaml` opens with `move_asset` (not `add_file`). **Decision:** every declared asset is given a single initial `Version` (`version_NNNN`) and a single initial `Location` (`location_NNNN`) at the synthesized path `<roots[0].path>/<asset.id>.<container>`. `move_asset` / `rename_file` mutate the existing location; `add_file` is rejected if the asset already has a location; `delete_file` removes it. The convention is documented in `docs/contract/manifest-initial-state.md` (Task 14) so external consumers know what to expect.

2. **`plan` runs `validate` first.** `plan` MUST refuse to produce a fixture for an invalid scenario. **Decision:** Sprint 1's `run_validation` is invoked unconditionally; if `report.ok` is False the command exits `3` and writes nothing to `--out`. On success the same report is serialized into `<run-dir>/validation.json`. This bypasses re-implementation and keeps `validate` and `plan` consistent.

3. **JSON canonicalization.** Bit-identical output requires fixed serialization. **Decision:** one helper `_emit_json(model, path)` in `engine/writer.py` writes every full-document JSON file using `model.model_dump_json(indent=2, by_alias=True, exclude_none=True)` plus a single trailing `"\n"`. The journal uses `_emit_jsonl(entries, path)` which writes each entry as one `model_dump_json(by_alias=True, exclude_none=True)` line followed by `"\n"`. UTF-8 by default.

4. **Plan-only fixture contents.** §"Plan-Only Mode" enumerates six outputs plus the sentinel. **Decision:** Sprint 3 writes exactly: `.chaos-librarian-run`, `scenario.yaml` (verbatim copy of the source bytes), `replay.json`, `manifest.initial.json`, `manifest.current.json`, `journal.jsonl`, `validation.json`. No `materialization.json`, no `library/`, no `reports/` — those land in Sprints 5–7 / Sprint 4.

5. **Event handler coverage.** All nine `TimelineActionName` variants must have handlers (otherwise resolving a scenario with `add_file` or `delete_file` crashes), but Sprint 3's exit criterion only requires the first scenario pack minus Active Library Churn. **Decision:** ship handlers for every variant in `events.py`; the handlers update `WorldState` and emit one or two journal entries each. Each handler has unit tests; the four pack scenarios are the end-to-end smoke tests.

6. **`plan --json` stdout.** **Decision:** a small summary object `{"run_id": "<uuid>", "scenario_id": "...", "out": "<absolute path>", "schema_version": 1, "journal_entries": <int>, "ok": true}` — agents wanting more detail read the files. Non-`--json` prints one human line: `plan: wrote <path>`.

7. **Stateful lifecycle validation.** Sprint 1 proves target ids exist and the timeline is non-decreasing, but it does not simulate the asset lifecycle. Shape-valid timelines like `move_asset` after `delete_file` reach the engine and crash. **Decision:** add `_rule_timeline_lifecycle` to the Sprint 1 validation pipeline and emit `E_LIFECYCLE_INVALID` on transitions that the engine cannot honor. Driven from `validate` and `plan` alike; the engine's own raise-on-invalid checks become defense in depth.

8. **Run-directory creation.** §"Filesystem Safety" says `plan` / `materialize` / `run` / `replay` create the sentinel atomically as part of run-directory creation and refuse to write into a pre-existing directory unless the sentinel is present and parseable. Sprint 0's `--out` callback already rejects pre-existing paths and missing parents. **Decision:** keep the Sprint 0 callback (don't overwrite anything in V1); the "re-use a sentinel'd directory" path is a Sprint 4 concern (`step` / `inspect`).

---

## File Structure

**To create:**

```
src/chaos_librarian/engine/
  __init__.py        # public surface: run_plan, replay_plan_bundle, PlanArtifacts
  resolution.py      # ResolvedEvent + resolve_timeline(scenario)
  state.py           # WorldState dataclass + build_initial_state(scenario, ids)
  events.py          # apply_event(state, resolved, ids, clock) -> [JournalEntry]
  plan.py            # run_plan(*, run_input, validation_report) + replay_plan_bundle(bundle)
  writer.py          # write_fixture(out_dir, artifacts, scenario_bytes) — transactional staging

src/chaos_librarian/validation/
  input.py           # RunInput + prepare_run_input / prepare_run_input_from_bytes

tests/engine/
  __init__.py
  test_resolution.py
  test_state.py
  test_events_filesystem.py   # move / rename / delete / add
  test_events_media.py        # reencode_video / reencode_audio / create_sidecar
  test_events_slow_copy.py    # slow_copy_start + slow_copy_commit pairing
  test_plan.py                # run_plan determinism + artifact shape + replay_plan_bundle
  test_writer.py              # canonical JSON, sentinel atomicity, transactional staging
  test_plan_e2e.py            # the four first-pack scenarios end-to-end + bundle replay

tests/validation/test_input.py  # RunInput factories: byte-binding + parse-error routing

tests/cli/test_plan.py        # CLI invocation tests (parallel to test_validate.py)

tests/fixtures/scenarios/duplicate-variant.yaml             # fourth first-pack scenario
tests/fixtures/scenarios/invalid/lifecycle-add-on-placed.yaml          # E_LIFECYCLE_INVALID
tests/fixtures/scenarios/invalid/lifecycle-move-of-deleted.yaml        # E_LIFECYCLE_INVALID
tests/fixtures/scenarios/invalid/lifecycle-double-slow-copy-start.yaml # E_LIFECYCLE_INVALID
docs/contract/manifest-initial-state.md           # documents the initial-location convention
```

**To modify:**

- `src/chaos_librarian/cli/app.py` — replace `plan`'s stub body with a real implementation; route both `validate` and `plan` through `prepare_run_input` so they share one byte-bound read; keep the `--out` callback.
- `src/chaos_librarian/scenario_io.py` — `load_scenario` returns `(raw_data, line_index, raw_bytes, content_hash)` so the same read serves both validation and the replay bundle.
- `src/chaos_librarian/validation/pipeline.py` — `run_validation` switches signature from `(path)` to `(run_input: RunInput)`. The `ScenarioLoadError` branch moves up into the factory.
- `src/chaos_librarian/validation/__init__.py` — re-export `RunInput`, `prepare_run_input`, `prepare_run_input_from_bytes`.
- `src/chaos_librarian/validation/codes.py` — add `E_LIFECYCLE_INVALID` constant (semantic-only, no `PYDANTIC_TO_CODE` entry).
- `src/chaos_librarian/validation/semantic.py` — append `_rule_timeline_lifecycle` and register it after `_rule_timeline_order`.
- `tests/validation/test_pipeline.py` and `tests/validation/test_invalid_corpus.py` — mechanical call-site update: `run_validation(path)` → `run_validation(prepare_run_input(path))` (10 call sites total per the Explore report).
- `tests/validation/test_semantic.py` — positive-case unit tests for the three lifecycle violations.
- `tests/test_scenario_io.py` — adjusts to the wider `load_scenario` return tuple.
- `tests/cli/test_app.py` — `plan` is no longer a stub returning 1; remove it from `_FILE_ARG_COMMANDS`-based stub assertions and rely on the new `tests/cli/test_plan.py` for behavior.
- `CLAUDE.md` — update the "Project state" paragraph: Sprint 3 is now shipping `plan`; note that lifecycle validation extends Sprint 1's pipeline.
- `docs/contract/replay-bundle.md` — add a "Replay Verifier" section pointing at `chaos_librarian.engine.replay_plan_bundle`.

**Not touched:**

- `src/chaos_librarian/contract/` — no schema changes. Every artifact `plan` writes already has its Pydantic model. The drift gate must stay clean.
- `schemas/*.schema.json` — generated artifacts, no edits.
- `src/chaos_librarian/determinism/` — Sprint 2 surface stays exactly as is; the engine consumes it through `chaos_librarian.determinism`.
- The Sprint 0 path callback `_validate_new_out_path` — keep as is.
- Other CLI commands — every other stub stays a stub.

---

## Conventions Recap

These come from project `CLAUDE.md` and tripped earlier sprints. They apply to every file this plan creates.

- **Absolute imports only** — never `from .state import ...`; always `from chaos_librarian.engine.state import ...`. Ruff `flake8-tidy-imports` `ban-relative-imports = "all"` enforces this.
- **`from __future__ import annotations`** at the top of every new `.py` file.
- **Google-style docstrings** on non-trivial public APIs; module docstring on each new module.
- **No `Literal[CONSTANT]` indirect forms** — `ty` rejects them. Hardcode `Literal[1]` for `schema_version` fields when constructing Pydantic models.
- **`model_config = ConfigDict(extra="forbid")`** if you add any Pydantic models. (Sprint 3 should not need any — every artifact has its model already.)
- **Tests follow Rule 9** — each test class or test docstring includes a `WHY:` line stating the business reason for the behavior.
- **Negative tests use `Model.model_validate(payload_dict)`**, not keyword-arg construction with `# type: ignore`.
- **Pre-commit hooks** must pass — `prek run --all-files` should be green before each commit.
- **Function size** — keep handlers under 100 lines and cyclomatic complexity ≤ 8 per the global standards. If a handler grows past that, split into helpers.

---

## Task 0: Create the `feat/sprint-3` branch

**Files:** none (branch operation only).

Sprint code lands on a feature branch, per global standards and the project's documented practice (Sprints 0/1/2 each used `feat/sprint-<n>`). Run this once, before any other task touches code.

- [ ] **Step 1: Confirm working tree is clean and tracking `main`**

Run: `git status` and `git rev-parse --abbrev-ref HEAD`
Expected: working tree clean, current branch is `main` or a sibling.

- [ ] **Step 2: Create and switch to the branch**

Run: `git checkout -b feat/sprint-3`
Expected: `Switched to a new branch 'feat/sprint-3'`.

- [ ] **Step 3: Sanity-check `uv sync` and the existing suite still pass**

Run: `uv sync && uv run pytest -q`
Expected: install completes; existing tests all pass; coverage line printed at the end.

No commit at this step — the branch is empty until Task 1.

---

## Task 1: Engine package skeleton + `PlanArtifacts` dataclass

**Files:**

- Create: `src/chaos_librarian/engine/__init__.py`
- Create: `src/chaos_librarian/engine/plan.py` (contains the `PlanArtifacts` dataclass only at this stage)
- Create: `tests/engine/__init__.py`
- Create: `tests/engine/test_plan.py` (stub — one import test)

The package and the result type ship first so subsequent tasks can refer to `PlanArtifacts` without forward references. `run_plan` itself lands in Task 8 once its inputs exist.

- [ ] **Step 1: Write the failing test**

Create `tests/engine/__init__.py` empty.
Create `tests/engine/test_plan.py`:

```python
"""Tests for chaos_librarian.engine.plan (skeleton first; behavior in Task 8)."""

from __future__ import annotations

from chaos_librarian.engine import PlanArtifacts


def test_plan_artifacts_is_importable() -> None:
    """The public surface exposes PlanArtifacts.

    WHY: downstream tasks construct PlanArtifacts; if the surface drifts,
    every later import in this sprint breaks at once.
    """
    assert PlanArtifacts is not None
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/engine/test_plan.py -v`
Expected: collection or import error — `chaos_librarian.engine` does not exist.

- [ ] **Step 3: Create the package skeleton**

Create `src/chaos_librarian/engine/__init__.py`:

```python
"""Sprint 3 plan-only engine — public surface.

Downstream callers (CLI, tests) import from this package; the submodules
are implementation detail.
"""

from __future__ import annotations

from chaos_librarian.engine.plan import PlanArtifacts, run_plan

__all__ = ["PlanArtifacts", "run_plan"]
```

Create `src/chaos_librarian/engine/plan.py`:

```python
"""Plan-only orchestrator.

``run_plan`` walks a validated scenario, emits a journal + manifests +
replay bundle, and returns them as ``PlanArtifacts``. Persistence is
delegated to ``chaos_librarian.engine.writer.write_fixture``.
"""

from __future__ import annotations

from dataclasses import dataclass

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.validation import ValidationReport


@dataclass(frozen=True)
class PlanArtifacts:
    """In-memory result of a plan-only run, prior to persistence."""

    initial_manifest: Manifest
    current_manifest: Manifest
    journal: tuple[JournalEntry, ...]
    replay_bundle: PlanOnlyReplayBundle
    validation_report: ValidationReport
    sentinel: RunSentinel


def run_plan() -> PlanArtifacts:  # noqa: ARG001 — wired up in Task 8
    """Stub. Real implementation lands in Task 8."""
    raise NotImplementedError("run_plan ships in Task 8")
```

- [ ] **Step 4: Run the test — it now passes**

Run: `uv run pytest tests/engine/test_plan.py -v`
Expected: 1 passed.

- [ ] **Step 5: Run the broader suite**

Run: `uv run pytest -q`
Expected: every existing test still passes; coverage line printed.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/engine/ tests/engine/
git commit -m "feat(engine): scaffold engine package + PlanArtifacts dataclass"
```

---

## Task 2: `RunInput` value object + `prepare_run_input` factory

**Files:**

- Modify: `src/chaos_librarian/scenario_io.py` — `load_scenario` returns `(raw_data, line_index, raw_bytes, content_hash)`.
- Create: `src/chaos_librarian/validation/input.py` — `RunInput` dataclass + `prepare_run_input` / `prepare_run_input_from_bytes` factories.
- Modify: `src/chaos_librarian/validation/pipeline.py` — `run_validation` signature switches to `(run_input: RunInput) -> ValidationReport`; the `ScenarioLoadError` branch is removed (now raised by the factory).
- Modify: `src/chaos_librarian/validation/__init__.py` — re-export `RunInput`, `prepare_run_input`, `prepare_run_input_from_bytes`.
- Create: `tests/validation/test_input.py`.
- Modify: every caller listed in the Explore report — 1 in `src/chaos_librarian/cli/app.py`, 8 across `tests/validation/test_pipeline.py`, 2 in `tests/validation/test_invalid_corpus.py`. All convert from `run_validation(path)` to `run_validation(prepare_run_input(path))`.
- Modify: `tests/test_scenario_io.py` — `load_scenario`'s return tuple widens.

The Codex adversarial review found that the CLI reads the scenario file three times (`run_validation` → `read_bytes` → `load_scenario`); a mid-read replacement can produce a `validation.json` that vouches for one byte sequence while the published `scenario.yaml` / `replay.json` describe another. `RunInput` collapses every plan-time read to a single immutable record:

```python
@dataclass(frozen=True)
class RunInput:
    path: Path                 # source path (or sentinel like ``replay:<run_id>``)
    raw_bytes: bytes           # frozen at read time
    content_hash: str          # sha256 hex of raw_bytes
    raw_data: object           # parsed YAML tree (dict | list | scalar)
    line_index: LineIndex
```

`prepare_run_input(path)` reads the file once, hashes it, parses the bytes through `ruamel.yaml` from memory, and returns the frozen record. `prepare_run_input_from_bytes(raw_bytes, source_label)` is a sibling factory used by the replay verifier (Task 8) — bytes come from the replay bundle rather than disk.

**Why this and not an additive helper.** Two near-identical entry points (`run_validation(path)` for the CLI vs. `run_validation_with_metadata(path)` for plan) would invite the same byte-binding bug on whichever path skipped the metadata-aware helper. The refactor is small (single signature, mechanical call-site updates) and removes the failure mode at its source.

- [ ] **Step 1: Write the failing test**

Create `tests/validation/test_input.py`:

```python
"""Tests for chaos_librarian.validation.input."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from chaos_librarian.scenario_io import ScenarioLoadError
from chaos_librarian.validation import (
    RunInput,
    prepare_run_input,
    prepare_run_input_from_bytes,
)


class TestPrepareRunInput:
    """The factory binds raw bytes, hash, and parsed data in one record.

    WHY: validation, planning, and replay-bundle embedding must all describe
    the same byte sequence — otherwise ``validation.json`` can vouch for one
    payload while ``replay.json`` carries another. A single immutable read
    is the cheapest way to guarantee that.
    """

    def test_content_hash_matches_sha256_of_file(self, tmp_path: Path) -> None:
        path = tmp_path / "s.yaml"
        path.write_bytes(b"schema_version: 1\nscenario_id: s\nseed: 1\n")
        run_input = prepare_run_input(path)
        assert isinstance(run_input, RunInput)
        assert run_input.raw_bytes == path.read_bytes()
        assert run_input.content_hash == hashlib.sha256(path.read_bytes()).hexdigest()

    def test_from_bytes_matches_from_path(self, tmp_path: Path) -> None:
        payload = b"schema_version: 1\nscenario_id: s\nseed: 1\n"
        path = tmp_path / "s.yaml"
        path.write_bytes(payload)
        a = prepare_run_input(path)
        b = prepare_run_input_from_bytes(raw_bytes=payload, source_label="memory:s")
        assert a.raw_data == b.raw_data
        assert a.content_hash == b.content_hash

    def test_yaml_parse_error_raises_from_factory(self, tmp_path: Path) -> None:
        """``ScenarioLoadError`` must surface from the factory, never inside
        ``run_validation`` — otherwise an upstream caller could skip the
        factory and bypass the byte-binding guarantee."""
        path = tmp_path / "broken.yaml"
        path.write_text("schema_version: 1\n  : bad\n")  # invalid YAML
        with pytest.raises(ScenarioLoadError):
            prepare_run_input(path)
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/validation/test_input.py -v`
Expected: ImportError — `chaos_librarian.validation.input` does not exist yet.

- [ ] **Step 3: Widen `load_scenario` and add the factories**

Update `src/chaos_librarian/scenario_io.py` so `load_scenario` returns the four-tuple `(raw_data, line_index, raw_bytes, content_hash)`. The body now reads bytes once and computes the hash inline:

```python
def load_scenario(path: Path) -> tuple[object, LineIndex, bytes, str]:
    """Read, parse, and hash a scenario YAML file in one pass."""
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise ScenarioLoadError(f"cannot read {path}: {exc}") from exc
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    try:
        yaml = YAML(typ="rt")
        raw_data = yaml.load(io.BytesIO(raw_bytes))
    except YAMLError as exc:
        raise ScenarioLoadError.from_yaml_error(exc, path) from exc
    line_index = LineIndex.from_ruamel(raw_data)
    return raw_data, line_index, raw_bytes, content_hash
```

Create `src/chaos_librarian/validation/input.py`:

```python
"""Single-read scenario input bound to its bytes.

``RunInput`` is the unit of work threaded through the validation pipeline
and the plan-only engine. Every step that needs the parsed YAML, the raw
bytes, or the content hash refers back to the *same* immutable record —
so the report, the replay bundle, and the published ``scenario.yaml`` can
never describe drift between three reads of the same path.
"""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError

from chaos_librarian.scenario_io import LineIndex, ScenarioLoadError


@dataclass(frozen=True)
class RunInput:
    """One immutable read of a scenario source."""

    path: Path
    raw_bytes: bytes
    content_hash: str
    raw_data: object
    line_index: LineIndex


def prepare_run_input(path: Path) -> RunInput:
    """Read, hash, and parse a scenario file exactly once.

    Raises:
        ScenarioLoadError: if the file cannot be read or is not valid YAML.
    """
    try:
        raw_bytes = path.read_bytes()
    except OSError as exc:
        raise ScenarioLoadError(f"cannot read {path}: {exc}") from exc
    return _from_bytes(path=path, raw_bytes=raw_bytes)


def prepare_run_input_from_bytes(*, raw_bytes: bytes, source_label: str) -> RunInput:
    """Bind a RunInput to in-memory bytes (e.g. the scenario field of a replay bundle)."""
    return _from_bytes(path=Path(source_label), raw_bytes=raw_bytes)


def _from_bytes(*, path: Path, raw_bytes: bytes) -> RunInput:
    content_hash = hashlib.sha256(raw_bytes).hexdigest()
    try:
        yaml = YAML(typ="rt")
        raw_data = yaml.load(io.BytesIO(raw_bytes))
    except YAMLError as exc:
        raise ScenarioLoadError.from_yaml_error(exc, path) from exc
    line_index = LineIndex.from_ruamel(raw_data)
    return RunInput(
        path=path,
        raw_bytes=raw_bytes,
        content_hash=content_hash,
        raw_data=raw_data,
        line_index=line_index,
    )
```

Re-export from `src/chaos_librarian/validation/__init__.py`:

```python
from chaos_librarian.validation.input import (
    RunInput,
    prepare_run_input,
    prepare_run_input_from_bytes,
)

__all__ = [
    # ...existing exports...
    "RunInput",
    "prepare_run_input",
    "prepare_run_input_from_bytes",
]
```

- [ ] **Step 4: Switch `run_validation`'s signature**

Update `src/chaos_librarian/validation/pipeline.py` so `run_validation` takes `RunInput`:

```python
def run_validation(run_input: RunInput) -> ValidationReport:
    """Validate a pre-read scenario.

    The ``ScenarioLoadError`` branch lives in ``prepare_run_input`` now;
    callers that may face a malformed YAML file must catch it there and
    synthesize an ``E_YAML_PARSE`` report themselves.
    """
    collector = IssueCollector(run_input.line_index)
    _run_shape_pass(run_input.raw_data, collector)
    if collector.has_blocking_errors():
        return collector.to_report(scenario_id=_extract_scenario_id(run_input.raw_data))
    _run_semantic_pass(run_input.raw_data, run_input.line_index, collector)
    return collector.to_report(scenario_id=_extract_scenario_id(run_input.raw_data))
```

- [ ] **Step 5: Migrate every caller**

The Explore report listed 11 call sites of `run_validation` plus the `load_scenario` users:

- `src/chaos_librarian/cli/app.py` (the `validate` command) — see Task 10 for the synthesized `E_YAML_PARSE` wrapper.
- `tests/validation/test_pipeline.py` (8 call sites) — mechanical: `run_validation(path)` → `run_validation(prepare_run_input(path))`.
- `tests/validation/test_invalid_corpus.py` (2 call sites) — same mechanical change.
- `tests/test_scenario_io.py` — update to unpack the four-tuple.

- [ ] **Step 6: Run the broader suite**

Run: `uv run pytest -q`
Expected: every existing test still passes; the new `test_input.py` passes.

- [ ] **Step 7: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/scenario_io.py src/chaos_librarian/validation/ tests/validation/test_input.py tests/validation/test_pipeline.py tests/validation/test_invalid_corpus.py tests/test_scenario_io.py
git commit -m "feat(validation): introduce RunInput to byte-bind validation and planning"
```

---

## Task 3: `WorldState` + `build_initial_state`

**Files:**

- Create: `src/chaos_librarian/engine/state.py`
- Create: `tests/engine/test_state.py`

`WorldState` is the in-memory representation of the expected library at one logical timestamp. It mirrors `chaos_librarian.contract.manifest.Manifest` field-for-field but is mutable and indexed by id for O(1) lookup from event handlers. A `to_manifest()` method serializes it back to the contract type.

The initial-location convention is implemented here exactly once: every declared asset gets `version_0001` (per-asset counter) and `location_0001` (per-asset counter) at `<roots[0].path>/<asset.id>.<container>`.

- [ ] **Step 1: Write the failing test**

Create `tests/engine/test_state.py`:

```python
"""Tests for chaos_librarian.engine.state."""

from __future__ import annotations

from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.state import WorldState, build_initial_state


def _scenario_from_dict(data: dict[str, object]) -> Scenario:
    return Scenario.model_validate(data)


def _minimal_scenario() -> Scenario:
    return _scenario_from_dict(
        {
            "schema_version": 1,
            "scenario_id": "min",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
            "works": [
                {
                    "id": "w0",
                    "title": "T",
                    "variants": [
                        {
                            "id": "v0",
                            "label": "hd",
                            "bundle": {
                                "id": "b0",
                                "assets": [
                                    {
                                        "id": "a0",
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
            "timeline": [],
        }
    )


class TestBuildInitialState:
    """The initial WorldState assigns each asset one version and one location.

    WHY: this convention is the contract for downstream consumers — voom-v2
    relies on knowing that ``manifest.initial.json`` contains exactly one
    version+location per declared asset, at a deterministic synthesized path.
    """

    def test_one_version_and_location_per_asset(self) -> None:
        scenario = _minimal_scenario()
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        assert len(state.versions) == 1
        assert len(state.locations) == 1

    def test_initial_location_path_uses_first_root(self) -> None:
        scenario = _minimal_scenario()
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (loc,) = state.locations.values()
        assert loc.path == "movies-hd/a0.mkv"

    def test_world_state_serializes_to_manifest(self) -> None:
        scenario = _minimal_scenario()
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        manifest = state.to_manifest()
        assert isinstance(manifest, Manifest)
        assert manifest.schema_version == 1
        assert [w.id for w in manifest.works] == ["w0"]
        assert [v.id for v in manifest.variants] == ["v0"]
        assert [b.id for b in manifest.bundles] == ["b0"]
        assert [a.id for a in manifest.assets] == ["a0"]
        assert len(manifest.versions) == 1
        assert len(manifest.locations) == 1

    def test_two_assets_get_independent_locations(self) -> None:
        scenario = _scenario_from_dict(
            {
                "schema_version": 1,
                "scenario_id": "two",
                "seed": 1,
                "duration_scale": "short",
                "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
                "works": [
                    {
                        "id": "w0",
                        "title": "T",
                        "variants": [
                            {
                                "id": "v0",
                                "label": "hd",
                                "bundle": {
                                    "id": "b0",
                                    "assets": [
                                        {
                                            "id": "a0",
                                            "role": "primary_video",
                                            "container": "mkv",
                                            "duration_seconds": 1,
                                        },
                                        {
                                            "id": "a1",
                                            "role": "primary_video",
                                            "container": "mp4",
                                            "duration_seconds": 1,
                                        },
                                    ],
                                },
                            }
                        ],
                    }
                ],
                "timeline": [],
            }
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        paths = sorted(loc.path for loc in state.locations.values())
        assert paths == ["movies-hd/a0.mkv", "movies-hd/a1.mp4"]


class TestWorldStateMutations:
    """The dataclass supports the mutations event handlers need.

    WHY: handler code (Task 5+) must be able to look up an asset's current
    location in O(1) and mutate it without rebuilding the entire WorldState.
    """

    def test_move_asset_location_updates_path(self) -> None:
        scenario = _minimal_scenario()
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        # asset a0 has one location; pretend we moved it.
        loc_id = state.location_id_for_asset("a0")
        state.locations[loc_id] = state.locations[loc_id].model_copy(
            update={"path": "movies-hd/Renamed.mkv"}
        )
        (loc,) = state.locations.values()
        assert loc.path == "movies-hd/Renamed.mkv"
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/engine/test_state.py -v`
Expected: ImportError — `chaos_librarian.engine.state` does not exist.

- [ ] **Step 3: Implement `state.py`**

Create `src/chaos_librarian/engine/state.py`:

```python
"""In-memory expected library state.

Mirrors ``chaos_librarian.contract.manifest.Manifest`` field-for-field but
is mutable and indexed by id for O(1) lookup. Event handlers in
``chaos_librarian.engine.events`` consume and mutate ``WorldState``;
``to_manifest`` serializes it back to the contract type at the end of a
plan-only run.

The initial-location convention is implemented in ``build_initial_state``:
every declared asset gets ``version_0001`` and ``location_0001`` at the
synthesized path ``<roots[0].path>/<asset.id>.<container>``. See
docs/contract/manifest-initial-state.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAsset,
    ManifestBundle,
    ManifestLocation,
    ManifestSidecar,
    ManifestVariant,
    ManifestVersion,
    ManifestWork,
)
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator


@dataclass
class WorldState:
    """Mutable mirror of ``Manifest`` indexed by id."""

    works: dict[str, ManifestWork] = field(default_factory=dict)
    variants: dict[str, ManifestVariant] = field(default_factory=dict)
    bundles: dict[str, ManifestBundle] = field(default_factory=dict)
    assets: dict[str, ManifestAsset] = field(default_factory=dict)
    versions: dict[str, ManifestVersion] = field(default_factory=dict)
    locations: dict[str, ManifestLocation] = field(default_factory=dict)
    sidecars: dict[str, ManifestSidecar] = field(default_factory=dict)

    # Reverse indices so handlers can find an asset's current location/version
    # without an O(n) scan.
    _asset_to_location: dict[str, str] = field(default_factory=dict)
    _asset_to_version: dict[str, str] = field(default_factory=dict)

    def location_id_for_asset(self, asset_id: str) -> str:
        """Return the location id currently bound to ``asset_id``.

        Raises:
            KeyError: if the asset has no current location.
        """
        return self._asset_to_location[asset_id]

    def version_id_for_asset(self, asset_id: str) -> str:
        return self._asset_to_version[asset_id]

    def has_location(self, asset_id: str) -> bool:
        """Return True if ``asset_id`` is currently placed at some location."""
        return asset_id in self._asset_to_location

    def bind_location(self, asset_id: str, location: ManifestLocation) -> None:
        """Register a new location for ``asset_id``."""
        self.locations[location.id] = location
        self._asset_to_location[asset_id] = location.id

    def unbind_location(self, asset_id: str) -> None:
        """Remove the asset's current location (delete_file)."""
        loc_id = self._asset_to_location.pop(asset_id)
        self.locations.pop(loc_id)

    def bind_version(self, asset_id: str, version: ManifestVersion) -> None:
        self.versions[version.id] = version
        self._asset_to_version[asset_id] = version.id

    def to_manifest(self) -> Manifest:
        """Serialize back to the immutable Pydantic Manifest."""
        return Manifest(
            schema_version=1,
            works=list(self.works.values()),
            variants=list(self.variants.values()),
            bundles=list(self.bundles.values()),
            assets=list(self.assets.values()),
            versions=list(self.versions.values()),
            locations=list(self.locations.values()),
            sidecars=list(self.sidecars.values()),
        )


def build_initial_state(scenario: Scenario, ids: IdAllocator) -> WorldState:
    """Construct the initial WorldState for a scenario.

    Each declared asset receives:
    - one ``ManifestVersion`` with id ``version_NNNN`` and ``index=0``
    - one ``ManifestLocation`` with id ``location_NNNN`` at path
      ``<roots[0].path>/<asset.id>.<container>``

    Raises:
        ValueError: if the scenario has zero library roots (impossible
            after Sprint 1's shape pass, but defensive).
    """
    if not scenario.library.roots:
        raise ValueError("scenario has no library roots; cannot synthesize initial paths")
    primary_root = scenario.library.roots[0]
    state = WorldState()

    for work in scenario.works:
        state.works[work.id] = ManifestWork(id=work.id, title=work.title)
        for variant in work.variants:
            state.variants[variant.id] = ManifestVariant(
                id=variant.id, work_id=work.id, label=variant.label
            )
            bundle = variant.bundle
            state.bundles[bundle.id] = ManifestBundle(id=bundle.id, variant_id=variant.id)
            for asset in bundle.assets:
                state.assets[asset.id] = ManifestAsset(
                    id=asset.id,
                    bundle_id=bundle.id,
                    role=asset.role,
                    container=asset.container,
                    duration_seconds=asset.duration_seconds,
                )
                version_id = ids.next_version_id()
                state.bind_version(
                    asset.id,
                    ManifestVersion(id=version_id, asset_id=asset.id, index=0),
                )
                location_id = ids.next_location_id()
                state.bind_location(
                    asset.id,
                    ManifestLocation(
                        id=location_id,
                        asset_id=asset.id,
                        path=f"{primary_root.path}/{asset.id}.{asset.container}",
                    ),
                )

    return state
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/engine/test_state.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff check src/chaos_librarian/engine tests/engine && uv run ruff format --check src/chaos_librarian/engine tests/engine && uv run ty check src tests`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/engine/state.py tests/engine/test_state.py
git commit -m "feat(engine): add WorldState and build_initial_state"
```

---

## Task 4: Timeline resolution (`ResolvedEvent` + `resolve_timeline`)

**Files:**

- Create: `src/chaos_librarian/engine/resolution.py`
- Create: `tests/engine/test_resolution.py`

`resolve_timeline` converts a validated `Scenario` into a list of `ResolvedEvent` records ordered by `(at_ns, declared_index)`. Each `ResolvedEvent` carries the parsed `at_ns`, the declared index (for stable ordering on ties), and a reference to the original Pydantic event variant.

The Sprint 1 validation pipeline has already proven that every `at:` parses, every target id is defined, and the timeline is non-decreasing. `resolve_timeline` re-parses durations (cheap; we need the integer) but does not re-validate semantics — it asserts what validation already established.

- [ ] **Step 1: Write the failing test**

Create `tests/engine/test_resolution.py`:

```python
"""Tests for chaos_librarian.engine.resolution."""

from __future__ import annotations

from chaos_librarian.contract.scenario import Scenario, TimelineActionName
from chaos_librarian.engine.resolution import resolve_timeline


def _scenario(timeline: list[dict[str, object]]) -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 1,
            "scenario_id": "t",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
            "works": [
                {
                    "id": "w0",
                    "title": "T",
                    "variants": [
                        {
                            "id": "v0",
                            "label": "hd",
                            "bundle": {
                                "id": "b0",
                                "assets": [
                                    {
                                        "id": "a0",
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
            "timeline": timeline,
        }
    )


class TestResolveTimeline:
    """resolve_timeline produces (at_ns, idx, event) triples ordered by time.

    WHY: event handlers and the plan engine must walk a numeric timeline,
    not the string ``at:`` values; the order is the journal's emission
    order, which is part of the contract.
    """

    def test_empty_timeline_returns_empty(self) -> None:
        scenario = _scenario([])
        assert resolve_timeline(scenario) == []

    def test_single_event_returns_one(self) -> None:
        scenario = _scenario(
            [{"id": "e0", "at": "2s", "action": "move_asset", "target": "a0", "to": "movies-hd/x.mkv"}]
        )
        resolved = resolve_timeline(scenario)
        assert len(resolved) == 1
        assert resolved[0].at_ns == 2_000_000_000
        assert resolved[0].declared_index == 0
        assert resolved[0].event.action == TimelineActionName.MOVE_ASSET

    def test_multiple_events_preserve_declared_order(self) -> None:
        scenario = _scenario(
            [
                {"id": "e0", "at": "2s", "action": "move_asset", "target": "a0", "to": "movies-hd/x.mkv"},
                {"id": "e1", "at": "5s", "action": "rename_file", "target": "a0", "to": "movies-hd/y.mkv"},
            ]
        )
        resolved = resolve_timeline(scenario)
        assert [r.event.id for r in resolved] == ["e0", "e1"]
        assert [r.at_ns for r in resolved] == [2_000_000_000, 5_000_000_000]

    def test_ties_keep_declared_order(self) -> None:
        scenario = _scenario(
            [
                {"id": "e0", "at": "2s", "action": "move_asset", "target": "a0", "to": "movies-hd/x.mkv"},
                {"id": "e1", "at": "2s", "action": "rename_file", "target": "a0", "to": "movies-hd/y.mkv"},
            ]
        )
        resolved = resolve_timeline(scenario)
        assert [r.event.id for r in resolved] == ["e0", "e1"]

    def test_zero_at_is_valid(self) -> None:
        scenario = _scenario(
            [{"id": "e0", "at": "0", "action": "move_asset", "target": "a0", "to": "movies-hd/x.mkv"}]
        )
        resolved = resolve_timeline(scenario)
        assert resolved[0].at_ns == 0
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/engine/test_resolution.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `resolution.py`**

Create `src/chaos_librarian/engine/resolution.py`:

```python
"""Timeline resolution.

Converts a validated Scenario's string-typed ``timeline[*].at`` values into
ordered numeric (``at_ns``, declared index, event) triples. Sprint 1's
validation pipeline has already proven every ``at:`` parses and the
timeline is non-decreasing; this module re-parses for the integer value
and does not re-validate semantics. Ordering on ties preserves declared
order, matching docs/specs/chaos-librarian-design.md §"Mutation Model".
"""

from __future__ import annotations

from dataclasses import dataclass

from chaos_librarian.clock import parse_duration
from chaos_librarian.contract.scenario import Scenario, TimelineEvent


@dataclass(frozen=True)
class ResolvedEvent:
    """One timeline event with its parsed numeric timestamp."""

    at_ns: int
    declared_index: int
    event: TimelineEvent


def resolve_timeline(scenario: Scenario) -> list[ResolvedEvent]:
    """Return the scenario's timeline as numeric, ordered ``ResolvedEvent``s.

    Args:
        scenario: A validated Scenario instance.

    Returns:
        Events ordered by ``(at_ns, declared_index)``. Empty if the scenario
        has an empty timeline.
    """
    resolved = [
        ResolvedEvent(at_ns=parse_duration(event.at), declared_index=idx, event=event)
        for idx, event in enumerate(scenario.timeline)
    ]
    resolved.sort(key=lambda r: (r.at_ns, r.declared_index))
    return resolved
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/engine/test_resolution.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff check src/chaos_librarian/engine tests/engine && uv run ruff format --check src/chaos_librarian/engine tests/engine && uv run ty check src tests`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/engine/resolution.py tests/engine/test_resolution.py
git commit -m "feat(engine): add resolve_timeline and ResolvedEvent"
```

---

## Task 5: Event handlers — atomic filesystem mutations

**Files:**

- Create: `src/chaos_librarian/engine/events.py`
- Create: `tests/engine/test_events_filesystem.py`

`events.apply_event(state, resolved, ids, run_id, scenario_id)` returns a tuple of journal entries (always one for atomic events; two for paired slow-copy phases, but those land in Task 7). This task ships handlers for the four atomic filesystem mutations: `move_asset`, `rename_file`, `delete_file`, `add_file`.

Each handler updates `WorldState` and returns one `AtomicJournalEntry` describing the change. `target_ids` is the affected `asset_id`; `location_ids` is the affected location; `state_delta` is a small mapping describing the action-specific payload (e.g. `{"from_path": "...", "to_path": "..."}`).

- [ ] **Step 1: Write the failing test**

Create `tests/engine/test_events_filesystem.py`:

```python
"""Tests for atomic filesystem event handlers in chaos_librarian.engine.events."""

from __future__ import annotations

import uuid

import pytest

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _scenario(timeline: list[dict[str, object]]) -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 1,
            "scenario_id": "fs",
            "seed": 1,
            "duration_scale": "short",
            "library": {
                "roots": [
                    {"id": "r0", "path": "movies-hd"},
                    {"id": "r1", "path": "archive"},
                ]
            },
            "works": [
                {
                    "id": "w0",
                    "title": "T",
                    "variants": [
                        {
                            "id": "v0",
                            "label": "hd",
                            "bundle": {
                                "id": "b0",
                                "assets": [
                                    {
                                        "id": "a0",
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
            "timeline": timeline,
        }
    )


class TestMoveAssetHandler:
    """move_asset updates the asset's location path and emits one journal entry.

    WHY: location-path mutations are the most common test surface for
    scanner/watcher tests; the journal entry must record both endpoints
    so adapters can verify the move was observed.
    """

    def test_move_updates_location_path(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "move_asset",
                    "target": "a0",
                    "to": "movies-hd/Renamed.mkv",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        entries = apply_event(state, resolved, ids, _RUN_ID, "fs")
        (entry,) = entries
        assert isinstance(entry, AtomicJournalEntry)
        assert entry.phase == JournalPhase.ATOMIC
        assert entry.action == "move_asset"
        assert entry.target_ids == ["a0"]
        assert entry.state_delta["from_path"] == "movies-hd/a0.mkv"
        assert entry.state_delta["to_path"] == "movies-hd/Renamed.mkv"
        # location updated in-place
        (loc,) = state.locations.values()
        assert loc.path == "movies-hd/Renamed.mkv"


class TestRenameFileHandler:
    """rename_file is move_asset with a same-root target — same wire shape.

    WHY: the journal entry's ``action`` field discriminates the two; rename
    is recorded distinctly so adapters know the operation was a rename
    not a cross-root move.
    """

    def test_rename_updates_path_and_records_action(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "rename_file",
                    "target": "a0",
                    "to": "movies-hd/Renamed.mkv",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        (entry,) = apply_event(state, resolved, ids, _RUN_ID, "fs")
        assert entry.action == "rename_file"
        (loc,) = state.locations.values()
        assert loc.path == "movies-hd/Renamed.mkv"


class TestDeleteFileHandler:
    """delete_file removes the location and records the prior path.

    WHY: an oracle that says "this path is now absent" is what scanner
    tests assert against. The journal's ``state_delta.removed_path`` is the
    single source of truth.
    """

    def test_delete_removes_location(self) -> None:
        scenario = _scenario(
            [{"id": "e0", "at": "1s", "action": "delete_file", "target": "a0"}]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        (entry,) = apply_event(state, resolved, ids, _RUN_ID, "fs")
        assert entry.action == "delete_file"
        assert entry.state_delta["removed_path"] == "movies-hd/a0.mkv"
        assert state.locations == {}


class TestAddFileHandler:
    """add_file places an asset that currently has no location.

    WHY: after a delete_file, an add_file is the supported way to re-place
    the asset; without this handler scenarios that delete-then-add crash.
    """

    def test_add_after_delete_rebinds_location(self) -> None:
        scenario = _scenario(
            [
                {"id": "e0", "at": "1s", "action": "delete_file", "target": "a0"},
                {
                    "id": "e1",
                    "at": "2s",
                    "action": "add_file",
                    "target": "a0",
                    "to": "archive/a0.mkv",
                },
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        resolved = resolve_timeline(scenario)
        for r in resolved:
            apply_event(state, r, ids, _RUN_ID, "fs")
        (loc,) = state.locations.values()
        assert loc.path == "archive/a0.mkv"

    def test_add_rejects_already_placed_asset(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "add_file",
                    "target": "a0",
                    "to": "archive/a0.mkv",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        with pytest.raises(ValueError, match="already has a location"):
            apply_event(state, resolved, ids, _RUN_ID, "fs")
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/engine/test_events_filesystem.py -v`
Expected: ImportError — `events.py` does not exist yet.

- [ ] **Step 3: Implement `events.py` (partial — atomic FS handlers only)**

Create `src/chaos_librarian/engine/events.py`:

```python
"""Event handlers — one function per ``TimelineActionName`` variant.

``apply_event`` is the single entry point. Each handler:

- mutates the in-memory ``WorldState`` in place
- returns one or more ``JournalEntry`` records describing the change
- never touches the filesystem (plan-only)

Per-action helpers are kept short (<30 lines) so adding a new variant in a
later sprint is a localized change.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from chaos_librarian.contract.journal import (
    AtomicJournalEntry,
    JournalEntry,
    JournalPhase,
)
from chaos_librarian.contract.manifest import ManifestLocation
from chaos_librarian.contract.scenario import (
    AddFileEvent,
    DeleteFileEvent,
    MoveAssetEvent,
    RenameFileEvent,
    TimelineActionName,
    TimelineEvent,
)
from chaos_librarian.determinism import IdAllocator
from chaos_librarian.engine.resolution import ResolvedEvent
from chaos_librarian.engine.state import WorldState


def apply_event(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    """Dispatch one resolved event to its handler and return its journal entries."""
    handler = _HANDLERS[resolved.event.action]
    return handler(state, resolved, ids, run_id, scenario_id)


_Handler = Callable[
    [WorldState, ResolvedEvent, IdAllocator, uuid.UUID, str],
    tuple[JournalEntry, ...],
]


def _new_atomic_entry(
    *,
    resolved: ResolvedEvent,
    run_id: uuid.UUID,
    scenario_id: str,
    action: str,
    target_ids: list[str],
    location_ids: list[str],
    state_delta: dict[str, object],
    input_version_ids: list[str] | None = None,
    output_version_ids: list[str] | None = None,
) -> AtomicJournalEntry:
    return AtomicJournalEntry(
        schema_version=1,
        event_id=resolved.event.id,
        scenario_id=scenario_id,
        run_id=run_id,
        logical_time_ns=resolved.at_ns,
        action=action,
        target_ids=target_ids,
        input_version_ids=input_version_ids or [],
        output_version_ids=output_version_ids or [],
        location_ids=location_ids,
        state_delta=state_delta,
        phase=JournalPhase.ATOMIC,
    )


def _handle_move_asset(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,  # noqa: ARG001 — no allocation for atomic move
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, MoveAssetEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    state.locations[loc_id] = previous.model_copy(update={"path": event.to})
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.MOVE_ASSET,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={"from_path": previous.path, "to_path": event.to},
    )
    return (entry,)


def _handle_rename_file(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,  # noqa: ARG001
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, RenameFileEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    state.locations[loc_id] = previous.model_copy(update={"path": event.to})
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.RENAME_FILE,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={"from_path": previous.path, "to_path": event.to},
    )
    return (entry,)


def _handle_delete_file(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,  # noqa: ARG001
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, DeleteFileEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    state.unbind_location(event.target)
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.DELETE_FILE,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={"removed_path": previous.path},
    )
    return (entry,)


def _handle_add_file(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, AddFileEvent)
    if state.has_location(event.target):
        raise ValueError(
            f"add_file: asset {event.target!r} already has a location; "
            f"use move_asset or rename_file to relocate"
        )
    location_id = ids.next_location_id()
    location = ManifestLocation(id=location_id, asset_id=event.target, path=event.to)
    state.bind_location(event.target, location)
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.ADD_FILE,
        target_ids=[event.target],
        location_ids=[location_id],
        state_delta={"added_path": event.to},
    )
    return (entry,)


# Tasks 5 and 6 add the remaining five action variants to this table.
_HANDLERS: dict[TimelineActionName, _Handler] = {
    TimelineActionName.MOVE_ASSET: _handle_move_asset,
    TimelineActionName.RENAME_FILE: _handle_rename_file,
    TimelineActionName.DELETE_FILE: _handle_delete_file,
    TimelineActionName.ADD_FILE: _handle_add_file,
}
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/engine/test_events_filesystem.py -v`
Expected: 5 passed.

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff check src/chaos_librarian/engine tests/engine && uv run ruff format --check src/chaos_librarian/engine tests/engine && uv run ty check src tests`
Expected: clean. (If `ty` complains about `MoveAssetEvent | RenameFileEvent | ...` narrowing without the `assert isinstance`, the asserts in each handler are the resolution.)

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/engine/events.py tests/engine/test_events_filesystem.py
git commit -m "feat(engine): add atomic filesystem event handlers"
```

---

## Task 6: Event handlers — media mutations + sidecar

**Files:**

- Modify: `src/chaos_librarian/engine/events.py` (add three handlers + register in `_HANDLERS`)
- Create: `tests/engine/test_events_media.py`

`reencode_video` and `reencode_audio` are version-bumping mutations: they allocate a new `version_NNNN` (asset content changed) without changing the location path. `create_sidecar` allocates a new `sidecar_NNNN`. State-delta payloads record what changed (codec, resolution, channels, sidecar path).

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_events_media.py`:

```python
"""Tests for media + sidecar handlers in chaos_librarian.engine.events."""

from __future__ import annotations

import uuid

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _scenario(timeline: list[dict[str, object]]) -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 1,
            "scenario_id": "media",
            "seed": 1,
            "duration_scale": "short",
            "library": {"roots": [{"id": "r0", "path": "movies-hd"}]},
            "works": [
                {
                    "id": "w0",
                    "title": "T",
                    "variants": [
                        {
                            "id": "v0",
                            "label": "hd",
                            "bundle": {
                                "id": "b0",
                                "assets": [
                                    {
                                        "id": "a0",
                                        "role": "primary_video",
                                        "container": "mkv",
                                        "duration_seconds": 1,
                                        "video": {
                                            "source": "color_bars",
                                            "codec": "h264",
                                            "resolution": "1080p",
                                        },
                                        "audio": [
                                            {
                                                "codec": "aac",
                                                "channels": "5.1",
                                                "language": "eng",
                                            }
                                        ],
                                    }
                                ],
                            },
                        }
                    ],
                }
            ],
            "timeline": timeline,
        }
    )


class TestReencodeVideoHandler:
    """reencode_video allocates a new version and records the codec/resolution delta.

    WHY: version history is the oracle for "the file's content changed";
    voom-v2's reconciliation depends on it.
    """

    def test_reencode_video_bumps_version(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "3s",
                    "action": "reencode_video",
                    "target": "a0",
                    "resolution": "sd",
                    "codec": "h264",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        before_versions = set(state.versions.keys())
        (resolved,) = resolve_timeline(scenario)
        (entry,) = apply_event(state, resolved, ids, _RUN_ID, "media")
        assert isinstance(entry, AtomicJournalEntry)
        assert entry.phase == JournalPhase.ATOMIC
        assert entry.action == "reencode_video"
        new_versions = set(state.versions.keys()) - before_versions
        assert len(new_versions) == 1
        assert entry.state_delta["resolution"] == "sd"
        assert entry.state_delta["codec"] == "h264"


class TestReencodeAudioHandler:
    """reencode_audio bumps version and records channel transition.

    WHY: stereo/5.1 downmix tests rely on the from→to channel delta being
    in the journal — adapters can assert it without re-deriving from probes.
    """

    def test_reencode_audio_records_channel_transition(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "3s",
                    "action": "reencode_audio",
                    "target": "a0",
                    "from_channels": "5.1",
                    "to_channels": "stereo",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        (entry,) = apply_event(state, resolved, ids, _RUN_ID, "media")
        assert entry.action == "reencode_audio"
        assert entry.state_delta["from_channels"] == "5.1"
        assert entry.state_delta["to_channels"] == "stereo"


class TestCreateSidecarHandler:
    """create_sidecar allocates a new sidecar id and records the path.

    WHY: sidecar reconciliation tests (Bundle Sidecars first-pack
    scenario) need a deterministic sidecar id and a reference to the
    asset it belongs to.
    """

    def test_create_sidecar_emits_sidecar_id(self) -> None:
        scenario = _scenario(
            [
                {
                    "id": "e0",
                    "at": "1s",
                    "action": "create_sidecar",
                    "target": "a0",
                    "to": "movies-hd/a0.eng.srt",
                }
            ]
        )
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        (resolved,) = resolve_timeline(scenario)
        (entry,) = apply_event(state, resolved, ids, _RUN_ID, "media")
        assert entry.action == "create_sidecar"
        assert entry.state_delta["sidecar_path"] == "movies-hd/a0.eng.srt"
        assert len(state.sidecars) == 1
        (sidecar,) = state.sidecars.values()
        assert sidecar.asset_id == "a0"
        assert sidecar.path == "movies-hd/a0.eng.srt"
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/engine/test_events_media.py -v`
Expected: failures — handlers not registered.

- [ ] **Step 3: Add the three handlers to `events.py`**

Open `src/chaos_librarian/engine/events.py`. Add the imports below the existing import block:

```python
from chaos_librarian.contract.manifest import ManifestSidecar, ManifestVersion
from chaos_librarian.contract.scenario import (
    CreateSidecarEvent,
    ReencodeAudioEvent,
    ReencodeVideoEvent,
)
```

Add these three handler functions after `_handle_add_file`:

```python
def _handle_reencode_video(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, ReencodeVideoEvent)
    prior_version_id = state.version_id_for_asset(event.target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    state.bind_version(
        event.target,
        ManifestVersion(id=new_version_id, asset_id=event.target, index=prior_version.index + 1),
    )
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.REENCODE_VIDEO,
        target_ids=[event.target],
        location_ids=[state.location_id_for_asset(event.target)],
        state_delta={"resolution": event.resolution, "codec": event.codec},
        input_version_ids=[prior_version_id],
        output_version_ids=[new_version_id],
    )
    return (entry,)


def _handle_reencode_audio(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, ReencodeAudioEvent)
    prior_version_id = state.version_id_for_asset(event.target)
    prior_version = state.versions[prior_version_id]
    new_version_id = ids.next_version_id()
    state.bind_version(
        event.target,
        ManifestVersion(id=new_version_id, asset_id=event.target, index=prior_version.index + 1),
    )
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.REENCODE_AUDIO,
        target_ids=[event.target],
        location_ids=[state.location_id_for_asset(event.target)],
        state_delta={"from_channels": event.from_channels, "to_channels": event.to_channels},
        input_version_ids=[prior_version_id],
        output_version_ids=[new_version_id],
    )
    return (entry,)


def _handle_create_sidecar(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, CreateSidecarEvent)
    sidecar_id = ids.next_sidecar_id()
    sidecar = ManifestSidecar(
        id=sidecar_id,
        asset_id=event.target,
        kind="subtitle",  # V1: only subtitle sidecars exist; future kinds map here.
        path=event.to,
    )
    state.sidecars[sidecar_id] = sidecar
    entry = _new_atomic_entry(
        resolved=resolved,
        run_id=run_id,
        scenario_id=scenario_id,
        action=TimelineActionName.CREATE_SIDECAR,
        target_ids=[event.target],
        location_ids=[state.location_id_for_asset(event.target)],
        state_delta={"sidecar_path": event.to, "sidecar_id": sidecar_id},
    )
    return (entry,)
```

Register them in `_HANDLERS`:

```python
_HANDLERS: dict[TimelineActionName, _Handler] = {
    TimelineActionName.MOVE_ASSET: _handle_move_asset,
    TimelineActionName.RENAME_FILE: _handle_rename_file,
    TimelineActionName.DELETE_FILE: _handle_delete_file,
    TimelineActionName.ADD_FILE: _handle_add_file,
    TimelineActionName.REENCODE_VIDEO: _handle_reencode_video,
    TimelineActionName.REENCODE_AUDIO: _handle_reencode_audio,
    TimelineActionName.CREATE_SIDECAR: _handle_create_sidecar,
}
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/engine/test_events_media.py tests/engine/test_events_filesystem.py -v`
Expected: 8 passed (5 from Task 5 + 3 here).

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff check src/chaos_librarian/engine tests/engine && uv run ruff format --check src/chaos_librarian/engine tests/engine && uv run ty check src tests`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/engine/events.py tests/engine/test_events_media.py
git commit -m "feat(engine): add reencode and sidecar event handlers"
```

---

## Task 7: Event handlers — slow-copy pair (multi-phase)

**Files:**

- Modify: `src/chaos_librarian/engine/state.py` (add `pending_slow_copies` index)
- Modify: `src/chaos_librarian/engine/events.py` (add two handlers + register)
- Create: `tests/engine/test_events_slow_copy.py`

`slow_copy_start` and `slow_copy_commit` are the only multi-phase pair in V1. The start emits a `StartedJournalEntry` (carries `temp_path`) and stages the location in WorldState with `temp_path` set; the location's `path` field is left at the pre-copy value until the commit. The commit emits a `CommittedJournalEntry` (carries `related_event_id`, no `temp_path`), atomically renames the location to the final path, and clears `temp_path`. The validation pipeline already proved pairing + timing in Sprint 1.

The start/commit handlers need a side index to pass the final path from start → commit, since the commit event carries only the `for_:` back-reference. We add `pending_slow_copies: dict[str, tuple[str, str]]` on `WorldState` mapping `start_event_id → (location_id, final_path)`; the commit drains the entry.

- [ ] **Step 1: Extend `WorldState` with the pending-slow-copy index**

Open `src/chaos_librarian/engine/state.py`. Add this field to the `WorldState` dataclass after `_asset_to_version`:

```python
    pending_slow_copies: dict[str, tuple[str, str]] = field(default_factory=dict)
    """Maps slow_copy_start event_id → (location_id, final_path). Drained on commit."""
```

(No other changes to `state.py`. The state-only test in `test_state.py` does not reference this field, so it remains green.)

- [ ] **Step 2: Write the failing tests**

Create `tests/engine/test_events_slow_copy.py`:

```python
"""Tests for slow_copy_start / slow_copy_commit handlers."""

from __future__ import annotations

import uuid

from chaos_librarian.contract.journal import (
    CommittedJournalEntry,
    JournalPhase,
    StartedJournalEntry,
)
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _scenario() -> Scenario:
    return Scenario.model_validate(
        {
            "schema_version": 1,
            "scenario_id": "sc",
            "seed": 7,
            "duration_scale": "short",
            "library": {
                "roots": [
                    {"id": "staging", "path": "staging"},
                    {"id": "movies_hd", "path": "movies-hd"},
                ]
            },
            "works": [
                {
                    "id": "w0",
                    "title": "T",
                    "variants": [
                        {
                            "id": "v0",
                            "label": "hd",
                            "bundle": {
                                "id": "b0",
                                "assets": [
                                    {
                                        "id": "a0",
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
            "timeline": [
                {
                    "id": "copy_start_001",
                    "at": "1s",
                    "action": "slow_copy_start",
                    "target": "a0",
                    "to": "movies-hd/Nova.mkv",
                    "temp_path": "movies-hd/Nova.mkv.part",
                    "duration": "3s",
                },
                {
                    "id": "copy_commit_001",
                    "at": "4s",
                    "action": "slow_copy_commit",
                    "for": "copy_start_001",
                },
            ],
        }
    )


class TestSlowCopyStart:
    """slow_copy_start stages a temp_path on the asset's location.

    WHY: watchers must be able to observe partial files in-flight; the
    journal records the temp path so the test harness knows what to look
    for.
    """

    def test_started_entry_carries_temp_path(self) -> None:
        scenario = _scenario()
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        start_event, _ = resolve_timeline(scenario)
        (entry,) = apply_event(state, start_event, ids, _RUN_ID, "sc")
        assert isinstance(entry, StartedJournalEntry)
        assert entry.phase == JournalPhase.STARTED
        assert entry.temp_path == "movies-hd/Nova.mkv.part"
        # Location is staged with temp_path; final path not yet committed.
        loc = state.locations[state.location_id_for_asset("a0")]
        assert loc.temp_path == "movies-hd/Nova.mkv.part"


class TestSlowCopyCommit:
    """slow_copy_commit promotes temp_path to final path.

    WHY: the commit is what makes the file observable as fully copied; the
    journal's CommittedJournalEntry is the oracle anchor for that moment.
    """

    def test_commit_clears_temp_and_sets_final_path(self) -> None:
        scenario = _scenario()
        ids = IdAllocator(TraceRecorder())
        state = build_initial_state(scenario, ids)
        resolved = resolve_timeline(scenario)
        for r in resolved:
            entries = apply_event(state, r, ids, _RUN_ID, "sc")
        # ``entries`` from the last loop iteration is the commit entry.
        (commit_entry,) = entries
        assert isinstance(commit_entry, CommittedJournalEntry)
        assert commit_entry.phase == JournalPhase.COMMITTED
        assert commit_entry.related_event_id == "copy_start_001"
        loc = state.locations[state.location_id_for_asset("a0")]
        assert loc.temp_path is None
        assert loc.path == "movies-hd/Nova.mkv"
        assert state.pending_slow_copies == {}
```

- [ ] **Step 3: Run the failing tests**

Run: `uv run pytest tests/engine/test_events_slow_copy.py -v`
Expected: KeyError or NotImplementedError on the slow_copy_start action.

- [ ] **Step 4: Add the two handlers to `events.py`**

Open `src/chaos_librarian/engine/events.py`. Extend the existing journal imports to include the multi-phase entry classes, and add `SlowCopyStartEvent` / `SlowCopyCommitEvent` to the scenario imports. The combined import block at the top of `events.py` should be:

```python
from chaos_librarian.contract.journal import (
    AtomicJournalEntry,
    CommittedJournalEntry,
    JournalEntry,
    JournalPhase,
    StartedJournalEntry,
)
from chaos_librarian.contract.manifest import ManifestLocation, ManifestSidecar, ManifestVersion
from chaos_librarian.contract.scenario import (
    AddFileEvent,
    CreateSidecarEvent,
    DeleteFileEvent,
    MoveAssetEvent,
    ReencodeAudioEvent,
    ReencodeVideoEvent,
    RenameFileEvent,
    SlowCopyCommitEvent,
    SlowCopyStartEvent,
    TimelineActionName,
    TimelineEvent,
)
```

Add the two handlers after `_handle_create_sidecar`:

```python
def _handle_slow_copy_start(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,  # noqa: ARG001 — no new id allocated; reuses existing location
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, SlowCopyStartEvent)
    loc_id = state.location_id_for_asset(event.target)
    previous = state.locations[loc_id]
    state.locations[loc_id] = previous.model_copy(update={"temp_path": event.temp_path})
    state.pending_slow_copies[event.id] = (loc_id, event.to)
    entry = StartedJournalEntry(
        schema_version=1,
        event_id=event.id,
        scenario_id=scenario_id,
        run_id=run_id,
        logical_time_ns=resolved.at_ns,
        action=TimelineActionName.SLOW_COPY_START,
        target_ids=[event.target],
        location_ids=[loc_id],
        state_delta={"final_path": event.to, "temp_path": event.temp_path},
        phase=JournalPhase.STARTED,
        temp_path=event.temp_path,
    )
    return (entry,)


def _handle_slow_copy_commit(
    state: WorldState,
    resolved: ResolvedEvent,
    ids: IdAllocator,  # noqa: ARG001
    run_id: uuid.UUID,
    scenario_id: str,
) -> tuple[JournalEntry, ...]:
    event = resolved.event
    assert isinstance(event, SlowCopyCommitEvent)
    loc_id, final_path = state.pending_slow_copies.pop(event.for_)
    previous = state.locations[loc_id]
    state.locations[loc_id] = previous.model_copy(
        update={"path": final_path, "temp_path": None}
    )
    entry = CommittedJournalEntry(
        schema_version=1,
        event_id=event.id,
        scenario_id=scenario_id,
        run_id=run_id,
        logical_time_ns=resolved.at_ns,
        action=TimelineActionName.SLOW_COPY_COMMIT,
        target_ids=[previous.asset_id],
        location_ids=[loc_id],
        state_delta={"final_path": final_path},
        phase=JournalPhase.COMMITTED,
        related_event_id=event.for_,
    )
    return (entry,)
```

Register the two handlers in `_HANDLERS`:

```python
_HANDLERS: dict[TimelineActionName, _Handler] = {
    TimelineActionName.MOVE_ASSET: _handle_move_asset,
    TimelineActionName.RENAME_FILE: _handle_rename_file,
    TimelineActionName.DELETE_FILE: _handle_delete_file,
    TimelineActionName.ADD_FILE: _handle_add_file,
    TimelineActionName.REENCODE_VIDEO: _handle_reencode_video,
    TimelineActionName.REENCODE_AUDIO: _handle_reencode_audio,
    TimelineActionName.CREATE_SIDECAR: _handle_create_sidecar,
    TimelineActionName.SLOW_COPY_START: _handle_slow_copy_start,
    TimelineActionName.SLOW_COPY_COMMIT: _handle_slow_copy_commit,
}
```

- [ ] **Step 5: Run all event tests**

Run: `uv run pytest tests/engine/ -v`
Expected: every test from Tasks 1–6 passes (state, resolution, FS handlers, media handlers, slow-copy handlers).

- [ ] **Step 6: Lint, format, type-check**

Run: `uv run ruff check src/chaos_librarian/engine tests/engine && uv run ruff format --check src/chaos_librarian/engine tests/engine && uv run ty check src tests`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/engine/events.py src/chaos_librarian/engine/state.py tests/engine/test_events_slow_copy.py
git commit -m "feat(engine): add slow_copy multi-phase handlers"
```

---

## Task 8: `run_plan` orchestrator + `replay_plan_bundle` helper

**Files:**

- Modify: `src/chaos_librarian/engine/plan.py` (replace the NotImplementedError stub with the real orchestrator; add `replay_plan_bundle`)
- Modify: `src/chaos_librarian/engine/__init__.py` (export `replay_plan_bundle`)
- Modify: `tests/engine/test_plan.py` (extend with real behavior tests; keep the import test)

`run_plan(*, run_input, validation_report)` is the orchestrator. It:

1. Resolves the seed (`resolve_seed(parsed.seed)` where `parsed = Scenario.model_validate(run_input.raw_data)`).
2. Constructs a fresh `TraceRecorder`, `IdAllocator`, `RngStreams`, `Clock`.
3. Builds the initial `WorldState` and clones it for the "current" path.
4. Walks `resolve_timeline(parsed)`, applying each event in turn and accumulating journal entries; the clock is advanced to each event's `at_ns`.
5. Computes the deterministic plan-only `run_id` via `compute_plan_only_run_id(run_input.content_hash, resolved_seed)` — using the hash already bound to the read, not a fresh recomputation.
6. Assembles a `PlanOnlyReplayBundle` containing the verbatim YAML (`run_input.raw_bytes`), run_id, resolved_seed, execution_trace (from `TraceRecorder.entries()`), and chaos-librarian version.
7. Builds a `RunSentinel` (no `created_at` in plan-only).
8. Returns `PlanArtifacts`.

The keyword-only signature plus `RunInput` argument is what binds validation, planning, and the embedded scenario to one set of bytes — see [Finding 1 in the revision plan]. `run_plan` does NOT call `run_validation`; the caller (CLI / replay helper) is responsible for invoking validation and passing the resulting report in. This keeps `run_plan` a pure transformation and makes unit tests cheap.

`replay_plan_bundle(bundle: PlanOnlyReplayBundle) -> PlanArtifacts` is a sibling helper that re-runs `plan` from a recorded bundle:

```python
def replay_plan_bundle(bundle: PlanOnlyReplayBundle) -> PlanArtifacts:
    yaml_bytes = bundle.scenario.encode("utf-8")
    run_input = prepare_run_input_from_bytes(
        raw_bytes=yaml_bytes,
        source_label=f"replay:{bundle.run_id}",
    )
    report = run_validation(run_input)
    if not report.ok:
        raise RuntimeError(
            "replay scenario re-validation failed: "
            f"{[i.code for i in report.issues if i.severity == ValidationSeverity.ERROR]}"
        )
    return run_plan(run_input=run_input, validation_report=report)
```

Sprint 4 wraps this helper in the public `chaos-librarian replay` CLI command and adds divergence reporting (exit 6). Shipping the helper in Sprint 3 lets the bundle-driven round-trip test (Task 13) exercise the actual replay code path rather than running `plan` twice.

- [ ] **Step 1: Extend the failing test**

Replace `tests/engine/test_plan.py` with:

```python
"""Tests for chaos_librarian.engine.plan."""

from __future__ import annotations

from pathlib import Path

from chaos_librarian.contract.replay_bundle import (
    ExecutionMode,
    PlanOnlyReplayBundle,
)
from chaos_librarian.engine import PlanArtifacts, replay_plan_bundle, run_plan
from chaos_librarian.validation import prepare_run_input, run_validation

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _input_and_report(name: str) -> tuple[object, object]:
    run_input = prepare_run_input(FIXTURE_DIR / name)
    return run_input, run_validation(run_input)


class TestRunPlanBasics:
    """run_plan returns a PlanArtifacts with all six artifacts populated.

    WHY: every artifact field is part of the public contract; missing one
    means the fixture write step has no source for that file.
    """

    def test_returns_plan_artifacts(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report)
        assert isinstance(artifacts, PlanArtifacts)
        assert artifacts.initial_manifest.schema_version == 1
        assert artifacts.current_manifest.schema_version == 1
        assert len(artifacts.journal) == 2  # move + rename
        assert isinstance(artifacts.replay_bundle, PlanOnlyReplayBundle)
        assert artifacts.replay_bundle.execution_mode == ExecutionMode.PLAN_ONLY
        assert artifacts.replay_bundle.resolved_seed == 42
        assert artifacts.validation_report.ok is True
        assert artifacts.sentinel.created_at is None


class TestRunPlanDeterminism:
    """run_plan is deterministic for a fixed (scenario, seed).

    WHY: this is Sprint 3's headline exit criterion — plan-only output is
    bit-identical for a fixed seed across runs.
    """

    def test_two_runs_produce_equal_artifacts(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        a = run_plan(run_input=run_input, validation_report=report)
        b = run_plan(run_input=run_input, validation_report=report)
        assert a.initial_manifest == b.initial_manifest
        assert a.current_manifest == b.current_manifest
        assert a.journal == b.journal
        assert a.replay_bundle == b.replay_bundle
        assert a.sentinel == b.sentinel

    def test_run_id_is_plan_only_uuid5(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        a = run_plan(run_input=run_input, validation_report=report)
        # UUIDv5 has version field == 5.
        assert a.replay_bundle.run_id.version == 5


class TestRunPlanFirstPack:
    """Every first-pack scenario (minus Active Library Churn) runs to completion.

    WHY: this is Sprint 3's exit criterion: the four first-pack scenarios
    execute end-to-end. Sprint 8 adds Active Library Churn.
    """

    @staticmethod
    def _names() -> list[str]:
        return [
            "identity-move-rename.yaml",
            "version-evolution.yaml",
            "bundle-sidecars.yaml",
            "duplicate-variant.yaml",
        ]

    def test_each_pack_scenario_runs(self) -> None:
        for name in self._names():
            run_input, report = _input_and_report(name)
            artifacts = run_plan(run_input=run_input, validation_report=report)
            assert artifacts.replay_bundle.run_id is not None, name


class TestReplayPlanBundle:
    """``replay_plan_bundle`` reproduces an in-memory PlanArtifacts from a bundle.

    WHY: Sprint 3 exit criterion — replay of a plan-only bundle reproduces
    the same artifacts byte-for-byte. The end-to-end byte check lives in
    Task 13; this unit test pins the in-memory contract.
    """

    def test_replay_returns_equivalent_artifacts(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        original = run_plan(run_input=run_input, validation_report=report)
        replayed = replay_plan_bundle(original.replay_bundle)
        assert replayed.replay_bundle == original.replay_bundle
        assert replayed.initial_manifest == original.initial_manifest
        assert replayed.current_manifest == original.current_manifest
        assert replayed.journal == original.journal
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/engine/test_plan.py -v`
Expected: failures — `run_plan` still raises NotImplementedError; `duplicate-variant.yaml` doesn't exist yet (covered by Task 11).

- [ ] **Step 3: Implement `run_plan` and `replay_plan_bundle` in `plan.py`**

Replace `src/chaos_librarian/engine/plan.py` with:

```python
"""Plan-only orchestrator and bundle-driven replay helper.

``run_plan`` consumes a pre-read ``RunInput`` plus a validation report,
walks the timeline, and returns the complete set of in-memory artifacts.
Persistence is delegated to ``chaos_librarian.engine.writer.write_fixture``.

``replay_plan_bundle`` re-runs ``plan`` from a recorded ``PlanOnlyReplayBundle``
so a previously emitted fixture can be reproduced from its bundle alone.
Sprint 4 wraps it in the public ``replay`` CLI command.
"""

from __future__ import annotations

from dataclasses import dataclass

from chaos_librarian import __version__ as _chaos_librarian_version
from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import (
    ExecutionMode,
    PlanOnlyReplayBundle,
    compute_plan_only_run_id,
)
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.contract.validation import ValidationReport, ValidationSeverity
from chaos_librarian.determinism import (
    IdAllocator,
    TraceRecorder,
    resolve_seed,
)
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state
from chaos_librarian.validation import (
    RunInput,
    prepare_run_input_from_bytes,
    run_validation,
)


@dataclass(frozen=True)
class PlanArtifacts:
    """In-memory result of a plan-only run, prior to persistence."""

    initial_manifest: Manifest
    current_manifest: Manifest
    journal: tuple[JournalEntry, ...]
    replay_bundle: PlanOnlyReplayBundle
    validation_report: ValidationReport
    sentinel: RunSentinel


def run_plan(
    *,
    run_input: RunInput,
    validation_report: ValidationReport,
) -> PlanArtifacts:
    """Walk the scenario carried by ``run_input`` and assemble every plan-only artifact.

    Args:
        run_input: A frozen, byte-bound read of the scenario. ``raw_bytes``
            is embedded in the replay bundle; ``content_hash`` derives the
            deterministic ``run_id``.
        validation_report: The Sprint 1 report; serialized into the fixture
            as ``validation.json``. Must be ``ok=True`` if the caller wants
            a real fixture, but ``run_plan`` does not re-check.

    Returns:
        ``PlanArtifacts`` ready to hand to ``write_fixture``.
    """
    parsed = Scenario.model_validate(run_input.raw_data)
    resolved_seed = resolve_seed(parsed.seed)
    recorder = TraceRecorder()
    ids = IdAllocator(recorder)
    # Sprint 3 has no handler that draws from RngStreams; the trace ends up
    # alloc-only. Sprints 5+ that add randomness will pass a streams instance
    # into apply_event the same way they pass ``ids``.

    initial_state = build_initial_state(parsed, ids)
    initial_manifest = initial_state.to_manifest()

    run_id = compute_plan_only_run_id(
        scenario_content_hash=run_input.content_hash,
        resolved_seed=resolved_seed,
    )

    journal: list[JournalEntry] = []
    for resolved in resolve_timeline(parsed):
        entries = apply_event(
            initial_state,
            resolved,
            ids,
            run_id,
            parsed.scenario_id,
        )
        journal.extend(entries)

    current_manifest = initial_state.to_manifest()

    bundle = PlanOnlyReplayBundle(
        schema_version=1,
        chaos_librarian_version=_chaos_librarian_version,
        scenario=run_input.raw_bytes.decode("utf-8"),
        run_id=run_id,
        resolved_seed=resolved_seed,
        execution_trace=list(recorder.entries()),
        execution_mode=ExecutionMode.PLAN_ONLY,
    )

    sentinel = RunSentinel(
        run_id=run_id,
        schema_version=1,
        created_by=f"chaos-librarian {_chaos_librarian_version}",
        # created_at omitted in plan-only — see "Filesystem Safety".
        created_at=None,
    )

    return PlanArtifacts(
        initial_manifest=initial_manifest,
        current_manifest=current_manifest,
        journal=tuple(journal),
        replay_bundle=bundle,
        validation_report=validation_report,
        sentinel=sentinel,
    )


def replay_plan_bundle(bundle: PlanOnlyReplayBundle) -> PlanArtifacts:
    """Re-run ``plan`` from a recorded plan-only bundle.

    Takes the bundle's verbatim ``scenario`` field, treats it as the
    canonical bytes for the replay run, and returns a ``PlanArtifacts``
    record identical to the original run on success. Sprint 4 wraps this
    helper in the public ``chaos-librarian replay`` CLI command and adds
    divergence reporting (exit 6).
    """
    yaml_bytes = bundle.scenario.encode("utf-8")
    run_input = prepare_run_input_from_bytes(
        raw_bytes=yaml_bytes,
        source_label=f"replay:{bundle.run_id}",
    )
    report = run_validation(run_input)
    if not report.ok:
        errors = [i.code for i in report.issues if i.severity == ValidationSeverity.ERROR]
        raise RuntimeError(f"replay scenario re-validation failed: {errors}")
    return run_plan(run_input=run_input, validation_report=report)
```

Update `src/chaos_librarian/engine/__init__.py` to export `replay_plan_bundle`:

```python
from chaos_librarian.engine.plan import PlanArtifacts, replay_plan_bundle, run_plan

__all__ = ["PlanArtifacts", "replay_plan_bundle", "run_plan"]
```

Note: `current_manifest` reuses the same `initial_state.to_manifest()` because every event mutated the same `WorldState`. The "initial" snapshot was already captured into `initial_manifest` BEFORE walking the timeline, so the two manifests differ correctly. **Watch out:** `Manifest` instances are independent objects (Pydantic validates per call), so the two snapshots cannot alias.

- [ ] **Step 4: Run the tests except `test_each_pack_scenario_runs`**

Run: `uv run pytest tests/engine/test_plan.py -v -k "not test_each_pack_scenario_runs"`
Expected: 4 passed (basics + determinism + run_id).

`test_each_pack_scenario_runs` will fail until Task 11 ships `duplicate-variant.yaml`.

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff check src/chaos_librarian/engine tests/engine && uv run ruff format --check src/chaos_librarian/engine tests/engine && uv run ty check src tests`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/engine/plan.py src/chaos_librarian/engine/__init__.py tests/engine/test_plan.py
git commit -m "feat(engine): implement run_plan orchestrator + replay_plan_bundle"
```

---

## Task 9: Fixture writer (`write_fixture`)

**Files:**

- Create: `src/chaos_librarian/engine/writer.py`
- Create: `tests/engine/test_writer.py`

`write_fixture(out_dir, artifacts, scenario_yaml_bytes)` stages every artifact under a sibling temp directory, writes the sentinel last inside the staging dir, then `Path.replace`s the staging dir onto `out_dir` atomically. The seven artifacts:

- `scenario.yaml` — `scenario_yaml_bytes` verbatim
- `replay.json` — canonical JSON
- `manifest.initial.json` — canonical JSON
- `manifest.current.json` — canonical JSON
- `journal.jsonl` — one entry per line
- `validation.json` — canonical JSON
- `.chaos-librarian-run` — sentinel (written LAST inside staging so a partial-write failure can never leave a sentinel-marked directory)

All JSON files use the canonicalization helpers (`indent=2`, `by_alias=True`, `exclude_none=True`, trailing `\n`).

**Why the staging-directory pattern.** The Codex adversarial review found that `mkdir`-then-write-many-files leaves a window where `.chaos-librarian-run` exists but the six artifact files do not, so any failure after the sentinel publishes an incomplete fixture that `clean` / `inspect` / `replay` would trust. Staging publishes the full directory tree in one `rename(2)` syscall — atomic on POSIX and macOS — so observers see either nothing or the complete fixture. `tempfile.mkdtemp(..., dir=out_dir.parent)` guarantees same-FS placement so `replace` does not fall back to a copy. The exception handler uses `BaseException` so `KeyboardInterrupt` and `SystemExit` also trigger cleanup; `shutil.rmtree(..., ignore_errors=True)` is best-effort, and a leftover `.chaos-librarian-staging-*` directory after a hard crash cannot be mistaken for a fixture (wrong prefix and no sentinel).

- [ ] **Step 1: Write the failing test**

Create `tests/engine/test_writer.py`:

```python
"""Tests for chaos_librarian.engine.writer."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import ExecutionMode, PlanOnlyReplayBundle
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.validation import ValidationReport
from chaos_librarian.engine import PlanArtifacts
from chaos_librarian.engine.writer import write_fixture

_RUN_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")


def _empty_artifacts() -> tuple[PlanArtifacts, bytes]:
    empty_manifest = Manifest(
        schema_version=1,
        works=[],
        variants=[],
        bundles=[],
        assets=[],
        versions=[],
        locations=[],
        sidecars=[],
    )
    bundle = PlanOnlyReplayBundle(
        schema_version=1,
        chaos_librarian_version="0.0.0",
        scenario="schema_version: 1\n",
        run_id=_RUN_ID,
        resolved_seed=1,
        execution_trace=[],
        execution_mode=ExecutionMode.PLAN_ONLY,
    )
    sentinel = RunSentinel(
        run_id=_RUN_ID,
        schema_version=1,
        created_by="chaos-librarian 0.0.0",
        created_at=None,
    )
    artifacts = PlanArtifacts(
        initial_manifest=empty_manifest,
        current_manifest=empty_manifest,
        journal=(),
        replay_bundle=bundle,
        validation_report=ValidationReport(
            schema_version=1, scenario_id="t", ok=True, issues=[]
        ),
        sentinel=sentinel,
    )
    return artifacts, b"schema_version: 1\n"


class TestWriteFixtureFileSet:
    """write_fixture writes exactly seven files at the run directory.

    WHY: any extra file becomes part of the contract; any missing file
    breaks the fixture-layout doc. The seven-file set is the contract.
    """

    def test_creates_expected_files(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()
        write_fixture(out, artifacts, scenario_bytes)
        files = sorted(p.name for p in out.iterdir())
        assert files == [
            ".chaos-librarian-run",
            "journal.jsonl",
            "manifest.current.json",
            "manifest.initial.json",
            "replay.json",
            "scenario.yaml",
            "validation.json",
        ]

    def test_scenario_yaml_is_verbatim(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()
        write_fixture(out, artifacts, scenario_bytes)
        assert (out / "scenario.yaml").read_bytes() == scenario_bytes

    def test_sentinel_round_trips_via_pydantic(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()
        write_fixture(out, artifacts, scenario_bytes)
        loaded = RunSentinel.model_validate_json(
            (out / ".chaos-librarian-run").read_text()
        )
        assert loaded.run_id == _RUN_ID
        assert loaded.created_at is None  # plan-only omission

    def test_journal_is_jsonl_with_trailing_newline(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()
        write_fixture(out, artifacts, scenario_bytes)
        text = (out / "journal.jsonl").read_text()
        # Empty journal: an empty file with no body. Trailing newline is N/A
        # for zero entries; the test asserts no whitespace garbage.
        assert text == ""


class TestWriteFixtureRefusesExistingDir:
    """write_fixture refuses a pre-existing target directory.

    WHY: ``--out`` callback also refuses; this is defense in depth. A
    scenario where the callback is bypassed (programmatic call from a
    library) still must not clobber.
    """

    def test_existing_dir_raises(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        out.mkdir()
        artifacts, scenario_bytes = _empty_artifacts()
        with pytest.raises(FileExistsError):
            write_fixture(out, artifacts, scenario_bytes)


class TestWriteFixtureDeterministicBytes:
    """Two writes of the same artifacts produce byte-identical files.

    WHY: this is the headline Sprint 3 invariant. The artifacts dataclass
    is frozen, so equal inputs must yield equal bytes on disk.
    """

    def test_byte_equal(self, tmp_path: Path) -> None:
        a, b = tmp_path / "a", tmp_path / "b"
        artifacts, scenario_bytes = _empty_artifacts()
        write_fixture(a, artifacts, scenario_bytes)
        write_fixture(b, artifacts, scenario_bytes)
        for name in [
            ".chaos-librarian-run",
            "manifest.current.json",
            "manifest.initial.json",
            "replay.json",
            "validation.json",
            "scenario.yaml",
            "journal.jsonl",
        ]:
            assert (a / name).read_bytes() == (b / name).read_bytes(), name


class TestPlanOnlyExcludesVolatileFields:
    """The plan-only replay bundle on disk omits ``created_at``.

    WHY: the bundle's plan-only variant has no created_at field; exclude_none
    keeps materialize fields from leaking when a future code path sets None.
    """

    def test_replay_json_has_no_created_at(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()
        write_fixture(out, artifacts, scenario_bytes)
        payload = json.loads((out / "replay.json").read_text())
        assert "created_at" not in payload
        assert "toolchain" not in payload


class TestWriteFixtureIsTransactional:
    """A mid-write failure leaves no fixture at all.

    WHY: future tools treat the sentinel as the trust boundary. A partial
    write that landed a sentinel would lie about the contents.
    """

    def test_failure_leaves_no_out_dir(self, tmp_path: Path, monkeypatch) -> None:
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()

        from chaos_librarian.engine import writer as writer_mod

        call_count = {"n": 0}
        real_emit_json = writer_mod._emit_json

        def flaky_emit_json(model, target):
            call_count["n"] += 1
            if call_count["n"] == 3:  # fail mid-write
                raise OSError("simulated disk full")
            real_emit_json(model, target)

        monkeypatch.setattr(writer_mod, "_emit_json", flaky_emit_json)
        with pytest.raises(OSError, match="simulated disk full"):
            write_fixture(out, artifacts, scenario_bytes)
        assert not out.exists()
        leftover = [
            p for p in tmp_path.iterdir() if p.name.startswith(".chaos-librarian-staging-")
        ]
        assert leftover == []

    def test_sentinel_is_written_last(self, tmp_path: Path, monkeypatch) -> None:
        """If the rename itself never runs, the sentinel must not have been written
        into ``out_dir`` first (the staging-dir approach guarantees this)."""
        out = tmp_path / "run-001"
        artifacts, scenario_bytes = _empty_artifacts()

        from chaos_librarian.engine import writer as writer_mod

        def boom(self, target):  # noqa: ARG001
            raise OSError("boom")

        monkeypatch.setattr(writer_mod.Path, "replace", boom)
        with pytest.raises(OSError, match="boom"):
            write_fixture(out, artifacts, scenario_bytes)
        assert not out.exists()
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/engine/test_writer.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `writer.py`**

Create `src/chaos_librarian/engine/writer.py`:

```python
"""Fixture-directory writer for plan-only runs.

Stages the seven plan-only artifacts under a sibling temp directory and
atomically renames it onto ``<out_dir>``:

1. ``scenario.yaml`` (verbatim source bytes)
2. ``replay.json``
3. ``manifest.initial.json``
4. ``manifest.current.json``
5. ``journal.jsonl``
6. ``validation.json``
7. ``.chaos-librarian-run`` (sentinel, written LAST inside staging)

The single ``Path.replace`` makes publication atomic on POSIX and macOS:
observers see either nothing or every file. Any failure during staging
triggers ``shutil.rmtree`` so a partial fixture cannot persist.

JSON canonicalization is centralized in ``_emit_json`` /  ``_emit_jsonl``
so every Sprint 3 artifact serializes the same way: ``indent=2``,
``by_alias=True``, ``exclude_none=True``, trailing ``"\n"``. This is what
makes plan-only output bit-identical.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Iterable
from pathlib import Path

from pydantic import BaseModel

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.engine.plan import PlanArtifacts


def write_fixture(
    out_dir: Path,
    artifacts: PlanArtifacts,
    scenario_yaml_bytes: bytes,
) -> None:
    """Persist a PlanArtifacts result to disk atomically.

    Args:
        out_dir: Target directory. MUST NOT already exist; the function
            creates it (via atomic rename from staging) and refuses to
            overwrite.
        artifacts: The result of ``run_plan``.
        scenario_yaml_bytes: Verbatim source YAML bytes, written to
            ``scenario.yaml`` without modification.

    Raises:
        FileExistsError: If ``out_dir`` already exists.
    """
    if out_dir.exists():
        raise FileExistsError(f"refusing to write into existing directory: {out_dir}")

    staging = Path(
        tempfile.mkdtemp(prefix=".chaos-librarian-staging-", dir=out_dir.parent)
    )
    try:
        (staging / "scenario.yaml").write_bytes(scenario_yaml_bytes)
        _emit_json(artifacts.replay_bundle, staging / "replay.json")
        _emit_json(artifacts.initial_manifest, staging / "manifest.initial.json")
        _emit_json(artifacts.current_manifest, staging / "manifest.current.json")
        _emit_jsonl(artifacts.journal, staging / "journal.jsonl")
        _emit_json(artifacts.validation_report, staging / "validation.json")
        _emit_sentinel(staging, artifacts.sentinel)  # written LAST inside staging
        staging.replace(out_dir)
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise


def _emit_sentinel(out_dir: Path, sentinel: RunSentinel) -> None:
    """Write the sentinel into the staging directory.

    The staging-directory approach makes intra-file atomicity unnecessary —
    the whole directory is published in one ``rename(2)`` — but the file is
    still emitted last so a tool watching the staging dir cannot observe a
    sentinel before the artifacts.
    """
    target = out_dir / ".chaos-librarian-run"
    payload = sentinel.model_dump_json(indent=2, by_alias=True, exclude_none=True) + "\n"
    target.write_text(payload)


def _emit_json(model: BaseModel, target: Path) -> None:
    """Write one Pydantic model as canonical JSON with trailing newline."""
    payload = model.model_dump_json(indent=2, by_alias=True, exclude_none=True) + "\n"
    target.write_text(payload)


def _emit_jsonl(entries: Iterable[JournalEntry], target: Path) -> None:
    """Write each entry as one canonical-JSON line; empty iter writes an empty file."""
    lines: list[str] = []
    for entry in entries:
        lines.append(entry.model_dump_json(by_alias=True, exclude_none=True))
    if not lines:
        target.write_text("")
        return
    target.write_text("\n".join(lines) + "\n")
```

- [ ] **Step 4: Run the writer tests**

Run: `uv run pytest tests/engine/test_writer.py -v`
Expected: 9 passed (7 original + 2 transactional).

- [ ] **Step 5: Lint, format, type-check**

Run: `uv run ruff check src/chaos_librarian/engine tests/engine && uv run ruff format --check src/chaos_librarian/engine tests/engine && uv run ty check src tests`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/engine/writer.py tests/engine/test_writer.py
git commit -m "feat(engine): add canonical fixture writer"
```

---

## Task 10: Wire `plan` CLI command

**Files:**

- Modify: `src/chaos_librarian/cli/app.py` (replace `plan`'s stub body)
- Modify: `tests/cli/test_app.py` (remove the now-incorrect "plan exits 1" expectation)
- Create: `tests/cli/test_plan.py`

`plan` calls `prepare_run_input(scenario)` exactly once, hands the resulting `RunInput` to `run_validation`, and (on success) threads the same record into `run_plan`. On failure it prints the report (JSON or human) and exits `3` without creating `--out`. `validate` is updated to follow the same pattern; the small `_synthesize_yaml_parse_report` helper preserves Sprint 1's `E_YAML_PARSE` / exit-3 contract on unparseable input. Prints the summary JSON or human one-liner. Exits `0`.

- [ ] **Step 1: Write the failing CLI test**

Create `tests/cli/test_plan.py`:

```python
"""End-to-end tests for the plan CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


class TestPlanExitCodes:
    """Valid scenarios exit 0; invalid ones exit 3 without creating --out.

    WHY: exit codes drive CI gates and agentic scripts. The "no --out on
    failure" rule keeps tooling from cleaning up half-written fixtures.
    """

    def test_valid_scenario_exits_zero(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        result = runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        assert (out / ".chaos-librarian-run").exists()

    def test_invalid_scenario_exits_three_without_out(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("42\n")  # E_TOP_LEVEL_NOT_MAPPING
        out = tmp_path / "run-001"
        result = runner.invoke(app, ["plan", str(bad), "--out", str(out)])
        assert result.exit_code == 3
        assert not out.exists()


class TestPlanJSONSummary:
    """``--json`` emits a small summary object.

    WHY: agents consume this; the small shape is the contract surface.
    """

    def test_json_summary_fields(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        result = runner.invoke(
            app,
            [
                "plan",
                str(FIXTURE_DIR / "identity-move-rename.yaml"),
                "--out",
                str(out),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        payload = json.loads(result.stdout)
        assert payload["scenario_id"] == "identity-move-rename"
        assert payload["out"] == str(out.resolve())
        assert payload["journal_entries"] == 2
        assert payload["ok"] is True
        assert "run_id" in payload


class TestPlanWritesEveryFile:
    """plan writes the seven plan-only artifacts.

    WHY: locks the public fixture layout for plan-only mode (see
    docs/contract/fixture-layout.md).
    """

    def test_seven_files(self, tmp_path: Path) -> None:
        out = tmp_path / "run-001"
        runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out)],
        )
        names = sorted(p.name for p in out.iterdir())
        assert names == [
            ".chaos-librarian-run",
            "journal.jsonl",
            "manifest.current.json",
            "manifest.initial.json",
            "replay.json",
            "scenario.yaml",
            "validation.json",
        ]


class TestPlanLifecycleViolation:
    """Add-on-placed lifecycle error exits 3 without unhandled exception.

    WHY: shape-valid timelines that violate the asset lifecycle used to crash
    the engine; ``_rule_timeline_lifecycle`` pre-empts them in validation so
    the CLI returns the same structured exit-3 used for every other invalid
    scenario.
    """

    def test_lifecycle_violation_exits_three(self, tmp_path: Path) -> None:
        bad = FIXTURE_DIR / "invalid" / "lifecycle-add-on-placed.yaml"
        out = tmp_path / "run-001"
        result = runner.invoke(app, ["plan", str(bad), "--out", str(out)])
        assert result.exit_code == 3
        assert not out.exists()
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/cli/test_plan.py -v`
Expected: failures — `plan` still calls `_stub("plan")`.

- [ ] **Step 3: Replace `plan`'s stub body**

Open `src/chaos_librarian/cli/app.py`. Add imports (combine with the existing `from chaos_librarian.validation import ...` block):

```python
import json

from chaos_librarian.engine import PlanArtifacts, run_plan
from chaos_librarian.engine.writer import write_fixture
from chaos_librarian.scenario_io import ScenarioLoadError
from chaos_librarian.validation import prepare_run_input, run_validation
```

Replace the `plan` function body:

```python
@app.command()
def plan(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=_validate_new_out_path)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Plan a scenario without creating media."""
    try:
        run_input = prepare_run_input(scenario)
    except ScenarioLoadError as exc:
        report = _synthesize_yaml_parse_report(scenario, exc)
        _emit_failure(report, json_output)
        raise typer.Exit(code=3) from exc

    report = run_validation(run_input)
    if not report.ok:
        _emit_failure(report, json_output)
        raise typer.Exit(code=3)

    artifacts = run_plan(run_input=run_input, validation_report=report)
    write_fixture(out, artifacts, run_input.raw_bytes)

    if json_output:
        typer.echo(_plan_summary_json(artifacts, out))
    else:
        typer.echo(f"plan: wrote {out}")


def _emit_failure(report: ValidationReport, json_output: bool) -> None:
    if json_output:
        typer.echo(report.model_dump_json(by_alias=True, exclude_none=True))
    else:
        _render_human(report)


def _plan_summary_json(artifacts: PlanArtifacts, out: Path) -> str:
    summary = {
        "run_id": str(artifacts.replay_bundle.run_id),
        "scenario_id": artifacts.validation_report.scenario_id,
        "schema_version": 1,
        "out": str(out.resolve()),
        "journal_entries": len(artifacts.journal),
        "ok": artifacts.validation_report.ok,
    }
    return json.dumps(summary, sort_keys=True)
```

Add the `_synthesize_yaml_parse_report` helper (here, or in a small `cli/_reports.py` if `app.py` grows too dense). It maps a `ScenarioLoadError` to the Sprint 1 `E_YAML_PARSE` shape so the CLI still emits a structured `validation.json`-style payload on unparseable input:

```python
def _synthesize_yaml_parse_report(
    scenario_path: Path, exc: ScenarioLoadError
) -> ValidationReport:
    return ValidationReport(
        schema_version=1,
        scenario_id=scenario_path.stem,
        ok=False,
        issues=[
            ValidationIssue(
                code=E_YAML_PARSE,
                severity=ValidationSeverity.ERROR,
                message=str(exc),
                loc=None,
                line=exc.line,
                column=exc.column,
            )
        ],
    )
```

Apply the same `prepare_run_input` + `_synthesize_yaml_parse_report` wrapper to the `validate` command so both commands share one byte-bound read path.

- [ ] **Step 4: Update `tests/cli/test_app.py`**

The parameterized stub test `test_file_arg_stub_with_valid_paths_exits_one` currently asserts `plan` exits `1`. That regresses now. Edit the body:

```python
@pytest.mark.parametrize(("name", "extra_args", "takes_out"), _FILE_ARG_COMMANDS)
def test_file_arg_stub_with_valid_paths_exits_one(
    name: str,
    extra_args: list[str],
    takes_out: bool,
    tmp_path: Path,
) -> None:
    scenario = tmp_path / "scenario.yaml"
    scenario.write_text("")
    out = tmp_path / "run-001"
    code = _invoke_with_file_arg(name, extra_args, takes_out, scenario, out)
    # ``validate`` and ``plan`` are real commands; they exit on validation
    # failure (empty file → YAML parse error → exit 3). The stub-only check
    # below covers ``materialize`` / ``run`` / ``replay``.
    if name in {"validate", "plan"}:
        assert code == 3
    else:
        assert code == 1
```

- [ ] **Step 5: Run the CLI tests**

Run: `uv run pytest tests/cli/ -v`
Expected: every existing test passes; `tests/cli/test_plan.py` passes.

- [ ] **Step 6: Run the full suite (excluding the duplicate-variant pack test)**

Run: `uv run pytest -q -k "not test_each_pack_scenario_runs"`
Expected: every test passes.

- [ ] **Step 7: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_app.py tests/cli/test_plan.py
git commit -m "feat(cli): implement plan command"
```

---

## Task 11: Author `duplicate-variant.yaml` fixture

**Files:**

- Create: `tests/fixtures/scenarios/duplicate-variant.yaml`

The First Scenario Pack §"Duplicate/Variant" calls for: "one work with HD and 4K variants plus a duplicate HD encode." The minimum scenario shape is two variants under one work, both targeting the same logical content, with a duplicate asset. No timeline events are needed for the variant modeling itself — the pack scenario tests that the engine handles multi-variant initial state correctly.

- [ ] **Step 1: Write the failing pack test**

There is no new test file — `tests/engine/test_plan.py::TestRunPlanFirstPack::test_each_pack_scenario_runs` already references `duplicate-variant.yaml` and will fail until the fixture lands.

Run: `uv run pytest tests/engine/test_plan.py::TestRunPlanFirstPack -v`
Expected: failure — file not found.

- [ ] **Step 2: Author the fixture**

Create `tests/fixtures/scenarios/duplicate-variant.yaml`:

```yaml
schema_version: 1
scenario_id: duplicate-variant
seed: 23
duration_scale: short

library:
  roots:
    - id: movies_hd
      path: movies-hd
    - id: movies_4k
      path: movies-4k

works:
  - id: work_supernova
    title: Synthetic Supernova
    variants:
      - id: variant_hd
        label: hd
        bundle:
          id: bundle_hd
          assets:
            - id: asset_hd_main
              role: primary_video
              container: mkv
              duration_seconds: 6
              video:
                source: mandelbrot
                codec: h264
                resolution: 1080p
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
            - id: asset_hd_dup
              role: primary_video
              container: mkv
              duration_seconds: 6
              video:
                source: mandelbrot
                codec: h264
                resolution: 1080p
              audio:
                - codec: aac
                  channels: stereo
                  language: eng
      - id: variant_4k
        label: uhd
        bundle:
          id: bundle_4k
          assets:
            - id: asset_4k_main
              role: primary_video
              container: mkv
              duration_seconds: 6
              video:
                source: mandelbrot
                codec: h265
                resolution: 4k
              audio:
                - codec: ac3
                  channels: "5.1"
                  language: eng

timeline: []
```

- [ ] **Step 3: Confirm the existing contract smoke test picks it up**

`tests/contract/test_sample_scenarios.py` (Sprint 0) parameterizes over every `*.yaml` under `tests/fixtures/scenarios/` (non-invalid). Run it:

Run: `uv run pytest tests/contract/test_sample_scenarios.py -v`
Expected: every sample including `duplicate-variant.yaml` validates through Pydantic. If the test file does NOT auto-discover, open it and confirm — early sprints used `Path(...).glob` for discovery.

- [ ] **Step 4: Run the full Sprint 3 suite end-to-end**

Run: `uv run pytest -q`
Expected: every test, including `test_each_pack_scenario_runs`, passes.

- [ ] **Step 5: Validate the new fixture also through the validate CLI**

Run: `uv run chaos-librarian validate tests/fixtures/scenarios/duplicate-variant.yaml --json`
Expected: exit code 0; JSON shows `"ok": true`, zero issues.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/scenarios/duplicate-variant.yaml
git commit -m "test(fixtures): add duplicate-variant first-pack scenario"
```

---

## Task 12: Lifecycle validation rule + invalid fixtures

**Files:**

- Modify: `src/chaos_librarian/validation/codes.py` — add `E_LIFECYCLE_INVALID`.
- Modify: `src/chaos_librarian/validation/semantic.py` — append `_rule_timeline_lifecycle` and register it after `_rule_timeline_order`.
- Modify: `tests/validation/test_semantic.py` — positive-case unit tests for each new lifecycle violation.
- Create: `tests/fixtures/scenarios/invalid/lifecycle-add-on-placed.yaml`.
- Create: `tests/fixtures/scenarios/invalid/lifecycle-move-of-deleted.yaml`.
- Create: `tests/fixtures/scenarios/invalid/lifecycle-double-slow-copy-start.yaml`.

Shape-valid timelines like `add_file` on an already-placed asset, `move_asset` after `delete_file`, or `slow_copy_start` on an asset that still has an open copy used to reach the engine's atomic handlers and raise unstructured `ValueError`s. The new rule simulates the lifecycle on top of Sprint 1's shape + cross-reference passes and surfaces these as structured `E_LIFECYCLE_INVALID` issues with `loc` / `line` set, so they appear in `validation.json` and trigger `plan`'s exit 3.

`E_LIFECYCLE_INVALID` is semantic-only and stays out of `PYDANTIC_TO_CODE` — it does not correspond to a Pydantic shape failure.

- [ ] **Step 1: Write the failing rule tests**

Append to `tests/validation/test_semantic.py`:

```python
class TestRuleTimelineLifecycle:
    """The lifecycle rule rejects sequences that the engine cannot honor.

    WHY: shape-valid timelines used to crash the engine with unstructured
    ``ValueError``s. The rule keeps the failure mode inside the validation
    pipeline so the CLI emits an ``E_LIFECYCLE_INVALID`` report and exits 3.
    """

    @pytest.mark.parametrize(
        "fixture",
        [
            "lifecycle-add-on-placed.yaml",
            "lifecycle-move-of-deleted.yaml",
            "lifecycle-double-slow-copy-start.yaml",
        ],
    )
    def test_lifecycle_fixture_reports_invalid(self, fixture: str) -> None:
        path = INVALID_FIXTURE_DIR / fixture
        report = run_validation(prepare_run_input(path))
        codes = [issue.code for issue in report.issues]
        assert E_LIFECYCLE_INVALID in codes
        assert report.ok is False
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/validation/test_semantic.py::TestRuleTimelineLifecycle -v`
Expected: failure — `E_LIFECYCLE_INVALID` is unknown.

- [ ] **Step 3: Add the error code and the rule**

Append to `src/chaos_librarian/validation/codes.py`:

```python
E_LIFECYCLE_INVALID: Final = "E_LIFECYCLE_INVALID"
```

(No `PYDANTIC_TO_CODE` entry — it is a semantic-only rule.)

Append `_rule_timeline_lifecycle` to `src/chaos_librarian/validation/semantic.py` and register it in `_RULES` after `_rule_timeline_order` so simpler diagnostics fire first:

```python
def _rule_timeline_lifecycle(
    raw: Mapping[str, object],
    line_index: LineIndex,
    collector: IssueCollector,
) -> None:
    """Reject timelines that cannot execute against the asset lifecycle.

    Simulates: every declared asset starts "placed" (per the initial-state
    convention in docs/contract/manifest-initial-state.md); slow-copy pairs
    must not interleave with other mutations on the same asset; commit
    references must point at an open ``slow_copy_start``.
    """
    placed: set[str] = set(_iter_asset_ids(raw))
    pending_slow_copies: dict[str, str] = {}  # start_event_id -> asset_id

    for idx, event in _iter_timeline_events(raw):
        action = event.get("action")
        target = event.get("target")
        loc: _Loc = ("timeline", idx, "action")

        if action == TimelineActionName.ADD_FILE and isinstance(target, str):
            if target in placed:
                collector.add(
                    code=E_LIFECYCLE_INVALID,
                    severity=ValidationSeverity.ERROR,
                    message=f"add_file on already-placed asset {target!r}",
                    loc=loc,
                    line_index=line_index,
                )
            placed.add(target)
            continue

        if action in {
            TimelineActionName.MOVE_ASSET,
            TimelineActionName.RENAME_FILE,
            TimelineActionName.DELETE_FILE,
        } and isinstance(target, str):
            if target not in placed:
                collector.add(
                    code=E_LIFECYCLE_INVALID,
                    severity=ValidationSeverity.ERROR,
                    message=f"{action} on unplaced asset {target!r}",
                    loc=loc,
                    line_index=line_index,
                )
            if action == TimelineActionName.DELETE_FILE:
                placed.discard(target)
            continue

        if action == TimelineActionName.SLOW_COPY_START and isinstance(target, str):
            ev_id = event.get("id")
            if target not in placed:
                collector.add(
                    code=E_LIFECYCLE_INVALID,
                    severity=ValidationSeverity.ERROR,
                    message=f"slow_copy_start on unplaced asset {target!r}",
                    loc=loc,
                    line_index=line_index,
                )
            if isinstance(ev_id, str):
                if target in pending_slow_copies.values():
                    collector.add(
                        code=E_LIFECYCLE_INVALID,
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"slow_copy_start on asset {target!r} that already "
                            "has a pending copy"
                        ),
                        loc=loc,
                        line_index=line_index,
                    )
                pending_slow_copies[ev_id] = target
            continue

        if action == TimelineActionName.SLOW_COPY_COMMIT:
            ref = event.get("for")
            if isinstance(ref, str) and ref in pending_slow_copies:
                pending_slow_copies.pop(ref)
            # Rule 5a already flags pure orphan commits; the lifecycle rule
            # only owns the "start already consumed" / "asset deleted mid-copy"
            # branches handled above.
```

- [ ] **Step 4: Author the three invalid fixtures**

Each fixture's first line MUST start with `# expected: E_LIFECYCLE_INVALID` so `tests/validation/test_invalid_corpus.py` picks the code up.

`tests/fixtures/scenarios/invalid/lifecycle-add-on-placed.yaml`:

```yaml
# expected: E_LIFECYCLE_INVALID
schema_version: 1
scenario_id: lifecycle-add-on-placed
seed: 1
duration_scale: short

library:
  roots:
    - id: r0
      path: movies-hd

works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1

timeline:
  - id: e1
    at: "PT0S"
    action: add_file
    target: a0
```

`tests/fixtures/scenarios/invalid/lifecycle-move-of-deleted.yaml`:

```yaml
# expected: E_LIFECYCLE_INVALID
schema_version: 1
scenario_id: lifecycle-move-of-deleted
seed: 1
duration_scale: short

library:
  roots:
    - id: r0
      path: movies-hd

works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1

timeline:
  - id: e1
    at: "PT0S"
    action: delete_file
    target: a0
  - id: e2
    at: "PT1S"
    action: move_asset
    target: a0
    to: movies-hd/renamed.mkv
```

`tests/fixtures/scenarios/invalid/lifecycle-double-slow-copy-start.yaml`:

```yaml
# expected: E_LIFECYCLE_INVALID
schema_version: 1
scenario_id: lifecycle-double-slow-copy-start
seed: 1
duration_scale: short

library:
  roots:
    - id: r0
      path: movies-hd

works:
  - id: w0
    title: T
    variants:
      - id: v0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: primary_video
              container: mkv
              duration_seconds: 1

timeline:
  - id: c1
    at: "PT0S"
    action: slow_copy_start
    target: a0
    to: movies-hd/copy.mkv
  - id: c2
    at: "PT1S"
    action: slow_copy_start
    target: a0
    to: movies-hd/copy2.mkv
```

- [ ] **Step 5: Run the rule + corpus tests**

Run: `uv run pytest tests/validation/ -v`
Expected: every test passes, including the three new lifecycle fixtures (the existing corpus harness picks them up via the `# expected:` marker).

- [ ] **Step 6: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/validation/codes.py src/chaos_librarian/validation/semantic.py tests/validation/test_semantic.py tests/fixtures/scenarios/invalid/lifecycle-add-on-placed.yaml tests/fixtures/scenarios/invalid/lifecycle-move-of-deleted.yaml tests/fixtures/scenarios/invalid/lifecycle-double-slow-copy-start.yaml
git commit -m "feat(validation): add E_LIFECYCLE_INVALID stateful lifecycle rule"
```

**Engine side note.** With the lifecycle rule active, the `add_file already has a location` `ValueError` in `_handle_add_file` becomes unreachable from the CLI path. It stays as a defense-in-depth assertion (Rule 12: "Fail loud") — its docstring grows one line noting the lifecycle rule should pre-empt it — and the unit tests added in Task 5 continue to exercise it directly.

---

## Task 13: End-to-end + bit-identical regression test

**Files:**

- Create: `tests/engine/test_plan_e2e.py`

This is the headline Sprint 3 regression: run `plan` twice via the CLI, byte-compare every output file, and assert equality. Also runs `plan` against each first-pack scenario as a smoke test of the full pipeline.

- [ ] **Step 1: Write the failing test**

Create `tests/engine/test_plan_e2e.py`:

```python
"""End-to-end plan tests: full CLI invocation, byte-identical regression."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"

_PACK_SCENARIOS = [
    "identity-move-rename.yaml",
    "version-evolution.yaml",
    "bundle-sidecars.yaml",
    "duplicate-variant.yaml",
    "slow-copy.yaml",
]


@pytest.mark.parametrize("scenario_name", _PACK_SCENARIOS)
def test_pack_scenario_plans_successfully(scenario_name: str, tmp_path: Path) -> None:
    """Every first-pack scenario (plus slow-copy fixture) plans end-to-end.

    WHY: Sprint 3 exit criterion — first scenario pack minus Active Library
    Churn executes successfully. ``slow-copy.yaml`` is included because the
    slow-copy multi-phase pair is the only V1 multi-phase mutation and must
    not regress.
    """
    out = tmp_path / "run"
    result = runner.invoke(
        app, ["plan", str(FIXTURE_DIR / scenario_name), "--out", str(out)]
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    assert (out / ".chaos-librarian-run").exists()
    assert (out / "replay.json").exists()


@pytest.mark.parametrize("scenario_name", _PACK_SCENARIOS)
def test_pack_scenario_bit_identical_across_runs(
    scenario_name: str, tmp_path: Path
) -> None:
    """Two plan runs of the same scenario+seed produce byte-identical files.

    WHY: this proves same-input determinism. The replay round-trip below
    proves that ``replay.json`` is enough to reproduce the fixture. The two
    tests together pin the headline bit-identical guarantee from both ends:
    re-running the same input, and re-running from the bundle alone.
    """
    out_a = tmp_path / "run-a"
    out_b = tmp_path / "run-b"
    result_a = runner.invoke(
        app, ["plan", str(FIXTURE_DIR / scenario_name), "--out", str(out_a)]
    )
    result_b = runner.invoke(
        app, ["plan", str(FIXTURE_DIR / scenario_name), "--out", str(out_b)]
    )
    assert result_a.exit_code == 0, result_a.stdout + result_a.stderr
    assert result_b.exit_code == 0, result_b.stdout + result_b.stderr

    file_names = sorted(p.name for p in out_a.iterdir())
    assert file_names == sorted(p.name for p in out_b.iterdir())
    for name in file_names:
        assert (out_a / name).read_bytes() == (out_b / name).read_bytes(), name


def test_replay_bundle_round_trip_matches_original(tmp_path: Path) -> None:
    """Replay from the bundle reproduces every artifact byte-for-byte.

    WHY: Sprint 3 exit criterion — replay of a plan-only bundle reproduces
    the same artifacts byte-for-byte. The earlier surrogate (two ``plan``
    invocations) only proved same-input determinism; this one exercises
    ``replay_plan_bundle`` so the bundle's structural completeness is what
    keeps the test green.
    """
    from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle
    from chaos_librarian.engine import replay_plan_bundle
    from chaos_librarian.engine.writer import write_fixture

    out_original = tmp_path / "run-original"
    out_replay = tmp_path / "run-replay"

    result = runner.invoke(
        app,
        ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out_original)],
    )
    assert result.exit_code == 0, result.stdout + result.stderr

    bundle = PlanOnlyReplayBundle.model_validate_json(
        (out_original / "replay.json").read_text()
    )
    replayed = replay_plan_bundle(bundle)
    write_fixture(out_replay, replayed, bundle.scenario.encode("utf-8"))

    for name in [
        ".chaos-librarian-run",
        "manifest.current.json",
        "manifest.initial.json",
        "replay.json",
        "scenario.yaml",
        "validation.json",
        "journal.jsonl",
    ]:
        assert (out_original / name).read_bytes() == (out_replay / name).read_bytes(), name
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/engine/test_plan_e2e.py -v`
Expected: every test passes. If the bit-identical test FAILS, the failure message tells you which file diverged — typical culprits: timestamp leakage, dict ordering, `exclude_none` settings, or the journal writer's newline handling.

- [ ] **Step 3: Run the full suite + coverage gate**

Run: `uv run pytest -q`
Expected: every test passes; coverage stays above the 88% floor (`fail_under = 88` in pyproject).

- [ ] **Step 4: Lint, format, type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 5: Verify schemas haven't drifted**

Run: `uv run python -m chaos_librarian.schema_export --check`
Expected: `All 7 schemas up-to-date.` Sprint 3 should NOT have touched any contract model.

- [ ] **Step 6: Commit**

```bash
git add tests/engine/test_plan_e2e.py
git commit -m "test(engine): bit-identical plan regression + pack smoke"
```

---

## Task 14: Documentation reconciliation

**Files:**

- Modify: `CLAUDE.md` (update "Project state" paragraph)
- Create: `docs/contract/manifest-initial-state.md`
- Modify: `docs/contract/cli-reference.md` (mark `plan` as implemented)
- Modify: `docs/contract/fixture-layout.md` (note plan-only file subset)
- Modify: `docs/contract/replay-bundle.md` (add a sentence confirming plan-only bit-identical guarantee)

Docs reconciliation is part of every sprint; pointing them at the new reality avoids "implemented" features going un-discovered by external consumers.

- [ ] **Step 1: Update `CLAUDE.md`**

Find the "Project state" paragraph that mentions `plan` is a stub. Replace it with:

```markdown
Sprint 0 (`feat/sprint-0`, PR #5) is **contract-only**: it freezes seven JSON Schema artifacts and a Typer CLI surface. `validate` ships in Sprint 1 (`feat/sprint-1`); `plan` ships in Sprint 3 (`feat/sprint-3`). Sprint 3 also extends Sprint 1's validation pipeline with `E_LIFECYCLE_INVALID`, which rejects shape-valid timelines that the engine cannot execute (add-on-placed, move-after-delete, double slow-copy). The remaining seven CLI commands are stubs that exit 1. Later sprints implement materialize / run / step / replay / inspect / capabilities / clean.
```

- [ ] **Step 2: Create `docs/contract/manifest-initial-state.md`**

```markdown
# Initial-Manifest Convention

`manifest.initial.json` describes the expected library state at `t=0`,
*before* any timeline event has applied. Sprint 3's plan-only engine
synthesizes the initial state from the scenario's `works[*].variants[*].bundle.assets[*]` declarations using this convention:

- One `Version` per asset (`version_NNNN`, monotonic allocator counter, `index = 0`).
- One `Location` per asset (`location_NNNN`, monotonic allocator counter), at path:

  ```
  <library.roots[0].path>/<asset.id>.<asset.container>
  ```

- No `Sidecar`s at `t=0`; sidecars are created by explicit `create_sidecar` timeline events.

Authors who want a custom initial path should use an `add_file` timeline
event at `t=0` after the asset is declared. Sprint 3 does NOT yet ship a
scenario-level "initial path" override; it lands in a later sprint if a
fixture genuinely needs it.

See [`chaos-librarian-design.md`](../specs/chaos-librarian-design.md)
§"Manifest Model" for the full schema.
```

- [ ] **Step 3: Update `docs/contract/cli-reference.md`**

Find:

> Every command except `validate` ships as a Sprint 0 stub and exits `1`.
> `validate` was implemented in Sprint 1.

Replace with:

> Sprint 0 ships every command as a stub returning `1`. `validate`
> (Sprint 1) and `plan` (Sprint 3) are real commands. The remaining seven
> commands still exit `1`.

- [ ] **Step 4: Update `docs/contract/fixture-layout.md`**

Below the layout block, add:

```markdown
## Plan-Only Subset

Plan-only runs (Sprint 3) write a strict subset of the full layout:

- `.chaos-librarian-run` (sentinel)
- `scenario.yaml`
- `replay.json`
- `manifest.initial.json`
- `manifest.current.json`
- `journal.jsonl`
- `validation.json`

`materialization.json`, `library/`, and `reports/` are written by later
sprints (5 / 6+ / 4 respectively).
```

- [ ] **Step 5: Update `docs/contract/replay-bundle.md`**

Append at the end of the Mode-Split Fields section:

```markdown
## Bit-Identical Plan-Only Output (Sprint 3)

Two `chaos-librarian plan` invocations on the same scenario + seed produce
byte-identical `replay.json`, manifests, journal, and sentinel. The
plan-only `run_id` is deterministic (UUIDv5 of scenario hash + seed) and
`created_at` is omitted, so no volatile fields leak into the bundle.

## Replay Verifier

`chaos_librarian.engine.replay_plan_bundle(bundle)` re-runs `plan` from a
recorded `PlanOnlyReplayBundle` alone — it re-validates the embedded
scenario, re-resolves the timeline, and returns a fresh `PlanArtifacts`
that compares byte-for-byte with the original fixture when written through
`write_fixture`. Sprint 4 wraps this helper in the public `chaos-librarian
replay` CLI command and adds divergence reporting (exit 6).
```

- [ ] **Step 6: Verify nothing else needs touching**

Run: `rg -n "plan stub|plan is a stub|plan exits 1" docs/ CLAUDE.md README.md`
Expected: no matches.

- [ ] **Step 7: Commit**

```bash
git add CLAUDE.md docs/contract/
git commit -m "docs(sprint-3): reconcile plan command and initial-manifest convention"
```

---

## Task 15: Final sweep + open the PR

**Files:** none (run checks, push, open PR).

- [ ] **Step 1: Run the full battery one more time**

Run in order:

```bash
uv sync
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
uv run pytest -q
prek run --all-files
```

Every step must succeed. The schema drift gate must say "All 7 schemas up-to-date" — Sprint 3 ships no schema changes.

- [ ] **Step 2: Push the branch**

Run: `git push -u origin feat/sprint-3`
Expected: branch pushes; remote tracks `feat/sprint-3`.

- [ ] **Step 3: Open the PR**

Run:

```bash
gh pr create --title "feat(sprint-3): plan-only timeline engine and plan command" --body "$(cat <<'EOF'
## Summary
- Adds the internal `chaos_librarian.engine` package: timeline resolution, in-memory `WorldState`, per-action event handlers, plan-only orchestrator (`run_plan`), bundle-driven replay helper (`replay_plan_bundle`), and transactional fixture writer.
- Adds `chaos_librarian.validation.RunInput` plus `prepare_run_input` so `validate` and `plan` share a single byte-bound read; the recorded `validation.json`, the published `scenario.yaml`, and the `replay.json` scenario field all describe the same bytes.
- Wires the `plan` CLI command end-to-end: validate → resolve → walk → emit; refuses `--out` on validation failure (exit 3); publishes the fixture via atomic staging-directory rename so a partial write cannot leave a sentinel-marked directory.
- Extends Sprint 1's validation pipeline with `E_LIFECYCLE_INVALID`: shape-valid timelines like add-on-placed or move-after-delete now fail validation instead of crashing the engine.
- Ships the fourth first-pack fixture `duplicate-variant.yaml`, the bit-identical regression test, and a bundle-driven replay round-trip that calls `replay_plan_bundle` on the original `replay.json` and byte-compares every fixture file.

## Review response
This branch addresses the four findings from Codex's adversarial review of `docs/superpowers/plans/2026-05-18-sprint-3-plan-only.md`:

1. **Validation byte-binding** — `RunInput` collapses every plan-time read of the scenario into a single immutable record threaded through `run_validation` and `run_plan`.
2. **Transactional fixture publication** — `write_fixture` stages all seven files under `.chaos-librarian-staging-*` and publishes via one `Path.replace`; the sentinel is written last inside staging, so a partial write can never leave a sentinel-marked directory.
3. **Lifecycle exit code** — `_rule_timeline_lifecycle` keeps shape-valid-but-engine-incompatible timelines out of the engine; `plan` reports them with structured exit 3 instead of an unhandled exception.
4. **Real replay verifier** — `replay_plan_bundle` re-runs `plan` from the recorded bundle alone; `test_replay_bundle_round_trip_matches_original` exercises the replay code path that the headline exit criterion actually requires.

## Plan
See [`docs/superpowers/plans/2026-05-18-sprint-3-plan-only.md`](docs/superpowers/plans/2026-05-18-sprint-3-plan-only.md).

## Test plan
- [ ] `uv run pytest -q` — full suite green
- [ ] `uv run python -m chaos_librarian.schema_export --check` — no schema drift
- [ ] `uv run chaos-librarian plan tests/fixtures/scenarios/identity-move-rename.yaml --out /tmp/plan-run --json` — exits 0, prints summary, writes 7 files
- [ ] `uv run chaos-librarian plan tests/fixtures/scenarios/invalid/lifecycle-add-on-placed.yaml --out /tmp/lifecycle-test --json` — exits 3, no directory at `/tmp/lifecycle-test`
- [ ] `uv run pytest tests/engine/test_plan_e2e.py::test_replay_bundle_round_trip_matches_original -v` — bundle-driven round-trip is green

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 4: Watch CI**

Run: `gh pr checks --watch`
Expected: every check passes. If a check fails, diagnose and fix on the branch — never `--no-verify` past a real check.

---

## Verification Checklist Against Sprint 3 Exit Criteria

| Criterion | Where Verified |
| --- | --- |
| Plan-only output is bit-identical for a fixed seed across runs | `tests/engine/test_plan_e2e.py::test_pack_scenario_bit_identical_across_runs` (parameterized over five fixtures) |
| Replay of a plan-only bundle reproduces the same artifacts byte-for-byte | `tests/engine/test_plan_e2e.py::test_replay_bundle_round_trip_matches_original` — calls `replay_plan_bundle(...)` on the original `replay.json` and byte-compares every fixture file |
| First scenario pack (excluding Active Library Churn) executes successfully | `tests/engine/test_plan.py::TestRunPlanFirstPack::test_each_pack_scenario_runs` + `tests/engine/test_plan_e2e.py::test_pack_scenario_plans_successfully` |
| `chaos-librarian plan scenario.yaml --out fixtures/run-001 --json` works | `tests/cli/test_plan.py::TestPlanJSONSummary` + `TestPlanWritesEveryFile` |
| Timeline event resolution (validate targets, sort by `at:`, detect ordering collisions) | Sprint 1 validation already covers target / ordering; `tests/engine/test_resolution.py` covers numeric ordering and ties |
| Plan-only execution emits initial manifest, planned current manifest, planned journal, replay bundle, validation report | `tests/engine/test_plan.py::TestRunPlanBasics::test_returns_plan_artifacts` + `tests/engine/test_writer.py::TestWriteFixtureFileSet` |

If any row is unverified after Task 15, treat it as a Sprint 3 regression — do not merge until it's green.
