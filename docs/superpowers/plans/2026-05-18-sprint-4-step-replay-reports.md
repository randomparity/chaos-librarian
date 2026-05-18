# Sprint 4 — Step Mode, Inspect, Clean, Replay, Reports

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the plan-only CLI surface. Turn `step`, `inspect`, `clean`, and `replay` from Sprint 0 stubs into real commands; extend `plan` with `--steps N`; emit per-asset / per-work / per-variant / per-bundle reports; add `applied_events` to the replay bundle so partial fixtures are first-class replayable artifacts.

**Architecture:** Three new engine modules (`reports.py`, `step.py`, `diff.py`) plus one new contract module (`reports.py`) extend Sprint 3's engine. `PlanOnlyReplayBundle` gains an `applied_events: int` field that records prefix length as bundle metadata; `compute_plan_only_run_id` stays 2-arg, so two truncation points of the same scenario+seed share a `run_id` and partial fixtures are first-class replayable artifacts. `step_fixture` re-runs the engine from `t=0` and verifies each regenerated journal entry against the on-disk entry, catching hand-edited or duplicated journal lines before they poison reports. `replay` adds artifact divergence detection via byte-comparison; `applied_events` tampering is caught at that stage. Step-mode boundaries are computed by a new `step_boundaries(resolved_timeline)` helper in `engine/resolution.py`: a consecutive `slow_copy_start` + `slow_copy_commit` pair counts as one user-visible step. `PlanOnlyReplayBundle` also gains a `journal_digest: str` field (sha256-hex of the serialized journal) so `replay_plan_bundle` can verify integrity without a comparison target.

**Tech Stack:** Python 3.13, Pydantic v2, Typer (existing CLI shell), Sprint 1 validation pipeline, Sprint 2 determinism package, Sprint 3 engine. No new runtime dependencies.

**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md) — §"Step Mode", §"Sprint 4", §"Filesystem Safety", §"Reports", §"Replay Bundle".

**Design doc:** [`docs/superpowers/specs/2026-05-18-sprint-4-design.md`](../specs/2026-05-18-sprint-4-design.md) — load-bearing for every task in this plan; the design's component breakdown and edge cases ARE the implementation contract. Read it once before Task 1, refer back when a task's "Behavior" pointer is terse.

**Branch:** `feat/sprint-4` (already exists; the design doc commit `6944002` is its tip).

---

## Open Design Decisions Baked Into This Plan

The Sprint 4 design left a few low-level questions implicit. Each is resolved below; flag if you disagree before Task 1.

1. **`REPLAY_BUNDLE_SCHEMA_VERSION` bumps from 1 to 2.** Two field-adds land in this sprint: `applied_events: int` (round 2) and `journal_digest: str` (round 3). Per Decision #4 of the design, a single sprint's field-adds share one schema bump. `REPLAY_BUNDLE_SCHEMA_VERSION: Final = 2`; both bundle subclass annotations bump to `Literal[2]`. The 2-arg signature of `compute_plan_only_run_id` is unchanged from Sprint 3 — `applied_events` is bundle metadata, not a hash input. See plan-revision context for why folding was rejected.

2. **`*_REPORT_SCHEMA_VERSION` constants land at 1.** Per Decision #4, the four new constants (`ASSET_REPORT_SCHEMA_VERSION`, `WORK_REPORT_SCHEMA_VERSION`, `VARIANT_REPORT_SCHEMA_VERSION`, `BUNDLE_REPORT_SCHEMA_VERSION`) are declared as bare `Final = 1` in `contract/__init__.py`. Sprint 5 will bump them to 2 when content hashes land.

3. **Step-mode exception module.** `SentinelInvalidError`, `ScenarioTamperedError`, and `JournalCorruptError` live in `chaos_librarian.engine.step` next to `step_fixture`. All three inherit from `ChaosLibrarianError`. `ReplayIntegrityError` stays in `engine/plan.py` where Sprint 3 put it.

4. **`step --next` CLI signature change.** The Sprint 0 stub declared `next_: bool = False`. Decision #8 of the design says `--next` accepts an optional positive integer (default 1). The implementation replaces the bool with `next_count: Annotated[int, typer.Option("--next", min=1)] = 1`. This changes the CLI's surface for `step` (bool flag → int option with min=1) but the design freezes the int semantics now — same flag name, same command name, same argument order.

5. **`step` writes a new `replay.json` after every advance.** Decision #12 / edge case 13 say `bundle.applied_events` and `bundle.run_id` update during the next write. `append_step` rewrites `replay.json` atomically (sibling tempfile + `Path.replace`) so the on-disk bundle always reflects the journal's current length. Without this, a partial `step` followed by `replay` would integrity-fail because the recorded `run_id` no longer matches the journal length.

6. **`compare_fixtures` ignores `reports/` ordering only at the directory-listing level.** Inside `reports/assets/<id>.json` the file content is the JSON document; byte-compare is fine because `build_report_set` sorts by id lexicographically. Directory walks use `sorted(...iterdir())` so file enumeration is stable. No path-style normalization beyond that.

7. **`_infer_original` cross-checks `applied_events`.** Two bundles of the same scenario+seed at different truncation points share `run_id`. To keep `replay`'s auto-discover precise, `_infer_original` reads the parent's `replay.json` and confirms both `run_id` AND `applied_events` match before returning the parent. A mismatched-prefix parent falls through to `--against`-required handling. Journal_digest is also checked at integrity time; the cross-check stays as auto-discover precision, not redundancy.

8. **`step_boundaries` is the single source of truth for step-unit semantics.** `run_plan`, `step_fixture`, `replay_plan_bundle`, and `inspect` all derive boundary lists from this one helper. `bundle.applied_events` is the raw event count; the helper translates between raw counts and user-visible step counts at the API boundary.

9. **`journal_digest` is sha256-hex of the on-disk byte stream.** Specifically `b"".join(entry.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8") + b"\n" for entry in journal)`. This matches what `writer.py` writes to `journal.jsonl`, so a downstream byte-diff and a digest mismatch always agree on the offending file.

---

## File Structure

**To create:**

```
src/chaos_librarian/contract/
  reports.py            # AssetSnapshot, AssetHistoryEntry, AssetReport, WorkReport,
                        # VariantReport, BundleReport (all schema_version: Literal[1])

src/chaos_librarian/engine/
  reports.py            # ReportSet dataclass + build_report_set(initial, current, journal)
  step.py               # step_fixture(run_dir, n_events) -> StepResult + three errors
  diff.py               # FixtureFileDiff, FixtureDiff + compare_fixtures(left, right)

tests/contract/
  test_reports.py       # round-trip + extra="forbid" + schema_version literal pinning

src/chaos_librarian/engine/  # (extending existing module)
  resolution.py             # new: step_boundaries(resolved_timeline) helper
                            # (resolve_timeline stays as-is)

tests/engine/
  test_reports.py       # build_report_set on synthetic Manifest+journal inputs
  test_resolution.py    # NEW: step_boundaries cases (atomic, slow_copy pair,
                        # non-adjacent pair, empty)
  test_step.py          # cursor recovery (happy + four corruption modes)
  test_diff.py          # is_clean + byte_diff + missing_in_left + missing_in_right
  test_plan_steps.py    # --steps 0 / --steps K / omitted / negative; applied_events
                        # binding + run_id distinctness across step counts

tests/cli/
  test_step.py
  test_inspect.py
  test_clean.py
  test_replay.py
```

**To modify:**

- `src/chaos_librarian/contract/__init__.py` — bump `REPLAY_BUNDLE_SCHEMA_VERSION` to `2`; add four `*_REPORT_SCHEMA_VERSION: Final = 1` constants.
- `src/chaos_librarian/contract/replay_bundle.py` — `_ReplayBundleBase` gains `applied_events: int = Field(ge=0)` and `journal_digest: str = Field(pattern=r"^[0-9a-f]{64}$")`; both bundle subclass annotations bump to `Literal[2]`. `compute_plan_only_run_id` is unchanged (stays 2-arg).
- `src/chaos_librarian/engine/resolution.py` — append the `step_boundaries` function alongside `resolve_timeline`. No change to `resolve_timeline`'s signature or behavior.
- `src/chaos_librarian/engine/plan.py` — `run_plan` accepts `steps_limit: int | None = None`; sets `bundle.applied_events`; `replay_plan_bundle` passes `bundle.applied_events` through as `steps_limit`.
- `src/chaos_librarian/engine/writer.py` — `write_fixture` also stages `reports/{assets,works,variants,bundles}/<id>.json` before the atomic rename; new `append_step(run_dir, ...)` updates the journal/manifest/reports/replay.json on an existing fixture.
- `src/chaos_librarian/engine/__init__.py` — re-export `step_fixture`, `StepResult`, `build_report_set`, `compare_fixtures`, `ReportSet`, and the three step-mode errors.
- `src/chaos_librarian/cli/app.py` — replace four stubs (`step`, `inspect`, `clean`, `replay`) with real bodies; extend `plan` with `--steps`.
- `src/chaos_librarian/schema_export.py` — register the four report models in `MODELS`.
- `tests/contract/test_replay_bundle.py` — payload helpers gain `applied_events: 0`; bundle constructors gain `applied_events=...`; `schema_version` constant assertions still pass via the named constant. `compute_plan_only_run_id` callsites are unchanged (stays 2-arg).
- `tests/engine/test_plan.py` and `tests/engine/test_plan_e2e.py` — bundle constructors gain `applied_events=...`; journal-count assertion that pinned `applied_events == len(timeline)` added. `compute_plan_only_run_id` callsites unchanged.
- `CLAUDE.md` — update the "Project state" paragraph: Sprint 4 ships step/inspect/clean/replay + plan-`--steps` + reports.

**Not touched:**

- `src/chaos_librarian/contract/{scenario,manifest,journal,validation,materialization,run_sentinel}.py` — no schema changes.
- `schemas/{scenario,manifest,journal,validation,materialization,run-sentinel}.schema.json` — regenerated only because the drift gate runs against all models; if `--check` reports drift outside `replay-bundle.schema.json` and the four new report schemas, something has gone wrong.
- `src/chaos_librarian/determinism/` — Sprint 2 surface stays as is.
- `src/chaos_librarian/validation/` — no new validation rules; Sprint 3's `E_LIFECYCLE_INVALID` already covers everything `step` exercises.
- The Sprint 0 path callback `_validate_new_out_path` — keep as is.
- Sprint 4 leaves `materialize`, `run`, and `capabilities` as stubs.

---

## Conventions Recap

These come from project `CLAUDE.md` and tripped earlier sprints. They apply to every file this plan creates or modifies.

- **Absolute imports only** — never `from .step import ...`; always `from chaos_librarian.engine.step import ...`. Ruff `flake8-tidy-imports` `ban-relative-imports = "all"` enforces this.
- **`from __future__ import annotations`** at the top of every new `.py` file.
- **Google-style docstrings** on non-trivial public APIs; module docstring on each new module.
- **No `Literal[CONSTANT]` indirect forms** — `ty` rejects them. Hardcode `Literal[1]` / `Literal[2]` for `schema_version` fields when constructing or annotating Pydantic models. Constants are referenced by name in *test fixtures*, not in field annotations.
- **`model_config = ConfigDict(extra="forbid")`** on every BaseModel class.
- **Tests follow Rule 9** — each test class or test docstring includes a `WHY:` line stating the business reason for the behavior.
- **Negative tests use `Model.model_validate(payload_dict)`**, not keyword-arg construction with `# type: ignore`.
- **`enum.StrEnum`** for string enums (ruff UP042 rejects `class X(str, Enum):`).
- **Typer `Annotated[Path, typer.Argument(...)]`**, not `Path = typer.Argument(...)` (ruff B008).
- **Pre-commit hooks** must pass — `prek run --all-files` should be green before each commit.
- **Function size** — ≤100 lines, cyclomatic complexity ≤8. Split into helpers if growing past that.
- **After editing any model in `src/chaos_librarian/contract/`**: regenerate `schemas/` with `uv run python -m chaos_librarian.schema_export --write` and commit the updated artifacts in the same change. The drift gate fails CI otherwise.

---

## Task 0: Confirm branch and clean working tree

**Files:** none (branch operation only).

The design doc commit `6944002` is the tip of `feat/sprint-4`. This task just confirms the branch state before implementation begins.

- [ ] **Step 1: Confirm the branch and tree state**

Run: `git status && git rev-parse --abbrev-ref HEAD && git log --oneline -1`
Expected: working tree clean, current branch `feat/sprint-4`, HEAD is `6944002 docs(sprint-4): commit the sprint-4 design spec` (or a later sprint-4 commit if one has been added).

- [ ] **Step 2: Sanity-check the existing suite passes**

Run: `uv sync && uv run pytest -q`
Expected: install completes; every existing test passes.

- [ ] **Step 3: Confirm the drift gate is clean against current code**

Run: `uv run python -m chaos_librarian.schema_export --check`
Expected: `All 7 schemas up-to-date.`

No commit at this task.

---

## Task 1: `applied_events` + `journal_digest` fields + schema bump

**Files:**

- Modify: `src/chaos_librarian/contract/__init__.py:18` — bump `REPLAY_BUNDLE_SCHEMA_VERSION` to `2`.
- Modify: `src/chaos_librarian/contract/replay_bundle.py:87-95` — `_ReplayBundleBase` gains `applied_events: int = Field(ge=0)` AND `journal_digest: str = Field(pattern=r"^[0-9a-f]{64}$")`.
- Modify: `src/chaos_librarian/contract/replay_bundle.py:101,110` — both subclass `schema_version` annotations switch to `Literal[2]`.
- Modify: `tests/contract/test_replay_bundle.py` — payload helpers gain `applied_events: 0` and the empty-journal `journal_digest`; bundle constructors gain `applied_events=...` and `journal_digest=...`; add the negative-applied_events test, the run_id-independence positive test, `test_journal_digest_required`, `test_journal_digest_must_be_sha256_hex`, `test_journal_digest_matches_helper_output`. `compute_plan_only_run_id` remains 2-arg.
- Modify (auto-regenerated): `schemas/replay-bundle.schema.json`.

Decision #12 of the design adds `applied_events` to the bundle as metadata (the field is not hashed into `run_id`). Round 3 adds `journal_digest` to give `replay_plan_bundle` a self-contained integrity check. Decision #4 (the project-wide field-add rule) requires the schema_version bump. This task lands both fields plus the bump together — they're a single atomic contract change.

The engine and CLI changes that consume `applied_events` are in later tasks; this one keeps scope to the contract layer plus its test surface so the schema change can be reviewed and committed independently.

- [ ] **Step 1: Write the failing tests**

Add to `tests/contract/test_replay_bundle.py`:

```python
def test_run_id_independent_of_applied_events() -> None:
    """run_id is invariant across applied_events values.

    WHY: under the no-fold design, two bundles of the same scenario+seed
    at different truncation points share a run_id — they describe the
    same logical run at different prefixes. The previous fold-into-run_id
    design was rejected because it broke step-mode cursor recovery (the
    journal entries stamped during plan carried the old run_id while the
    regenerated entries on the next step carried a new run_id, tripping
    JournalCorruptError on the plan's own writes). Codex review
    finding 1.
    """
    h = _scenario_hash("x")
    base = compute_plan_only_run_id(h, resolved_seed=1)
    assert compute_plan_only_run_id(h, resolved_seed=1) == base
    # applied_events is bundle metadata, not part of the hash; constructing
    # bundles with different applied_events does not affect the run_id.
    payload_zero = {**_plan_only_base(), "applied_events": 0, "run_id": str(base)}
    payload_five = {**_plan_only_base(), "applied_events": 5, "run_id": str(base)}
    assert TypeAdapter(ReplayBundle).validate_python(payload_zero).run_id == base
    assert TypeAdapter(ReplayBundle).validate_python(payload_five).run_id == base


def test_plan_only_bundle_rejects_negative_applied_events() -> None:
    """applied_events must be non-negative.

    WHY: a negative count would imply a journal of negative length —
    nonsensical; reject at the schema layer so no downstream code has to
    defend against it.
    """
    payload = {**_plan_only_base(), "applied_events": -1}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(payload)
```

Update `_plan_only_base` and `_materialize_base` helpers in the same file to include `"applied_events": 0` and `"journal_digest": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"` (the empty-journal sha256) in the payload dict. The `compute_plan_only_run_id` call inside the helper stays 2-arg — neither new field is a hash input.

Update every existing test that constructs `PlanOnlyReplayBundle(...)` or `MaterializeReplayBundle(...)` to include `applied_events=0` (or the matching value for that test's scenario) and `journal_digest=<some-valid-sha256-fixture>` (use the empty-journal sha256 above as the default fixture).

Add an assertion in `test_plan_only_bundle_has_no_created_at_or_toolchain_fields` (after `parsed = json.loads(...)`):

```python
    assert parsed["applied_events"] == 0
    assert parsed["journal_digest"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
```

Add three new tests to the same file:

```python
def test_journal_digest_required() -> None:
    """journal_digest is mandatory on every plan-only bundle.

    WHY: it's the self-contained integrity anchor — without it,
    applied_events tampering goes undetected when no --against is
    supplied (Codex round 3 finding 2).
    """
    payload = {**_plan_only_base()}
    del payload["journal_digest"]
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(payload)


def test_journal_digest_must_be_sha256_hex() -> None:
    """journal_digest is constrained to 64 lowercase hex chars."""
    payload = {**_plan_only_base(), "journal_digest": "nothex"}
    with pytest.raises(ValidationError):
        TypeAdapter(ReplayBundle).validate_python(payload)


def test_journal_digest_matches_helper_output() -> None:
    """A known journal produces a known digest.

    WHY: ensures the documented digest formula (sha256 of the on-disk
    journal byte stream) is what bundles actually record.
    """
    payload = {**_plan_only_base()}  # empty journal helper default
    bundle = TypeAdapter(ReplayBundle).validate_python(payload)
    assert (
        bundle.journal_digest
        == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/contract/test_replay_bundle.py -v`
Expected: at least two failures — the negative-applied_events test fails because the field doesn't exist yet, and the run_id-independence test fails to import `ReplayBundle`/payload helpers updated for `applied_events`. The 2-arg `compute_plan_only_run_id` signature is unchanged, so no callsite TypeError.

- [ ] **Step 3: Bump the schema constant**

Edit `src/chaos_librarian/contract/__init__.py:18`:

```python
REPLAY_BUNDLE_SCHEMA_VERSION: Final = 2
```

Leave the other six constants at `1`.

- [ ] **Step 4: ~~Extend the run_id helper~~ (deleted)**

`compute_plan_only_run_id` stays 2-arg. The Sprint 3 signature `(scenario_content_hash: str, resolved_seed: int) -> uuid.UUID` is preserved verbatim. `applied_events` is bundle metadata and does not enter the hash. See plan-revision context (Codex finding 1) for the rationale: folding `applied_events` into the hash broke step-mode cursor recovery because journal entries stamped during the original `plan` carried one `run_id` while regenerated entries on the next `step` would have carried a different `run_id`.

- [ ] **Step 5: Add the field to the bundle base class and bump subclass literals**

Edit `src/chaos_librarian/contract/replay_bundle.py`:

In `_ReplayBundleBase` (around line 87-95) add the field. The final class looks like:

```python
class _ReplayBundleBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    chaos_librarian_version: str
    scenario: str  # verbatim YAML
    run_id: uuid.UUID
    resolved_seed: int
    applied_events: int = Field(ge=0)
    journal_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    execution_trace: list[ExecutionTraceEntry] = Field(default_factory=list)
```

`PlanOnlyReplayBundle` and `MaterializeReplayBundle` keep their bodies; the `schema_version` annotation is inherited unchanged.

- [ ] **Step 6: Run the new tests — they pass; old tests now type-check**

Run: `uv run pytest tests/contract/test_replay_bundle.py -v`
Expected: all tests pass.

- [ ] **Step 7: Regenerate the schema artifact**

Run: `uv run python -m chaos_librarian.schema_export --write`
Expected: `Wrote 7 schemas to .../schemas`. `git diff schemas/replay-bundle.schema.json` shows the new `applied_events` property in both `oneOf` arms and the `schema_version` enum updates from `1` to `2`.

- [ ] **Step 8: Confirm drift gate is clean**

Run: `uv run python -m chaos_librarian.schema_export --check`
Expected: `All 7 schemas up-to-date.`

- [ ] **Step 9: Run the full suite — broken downstream callers expose themselves**

Run: `uv run pytest -q`
Expected: tests in `tests/engine/test_plan.py` and `tests/engine/test_plan_e2e.py` fail with `PlanOnlyReplayBundle.__init__() missing 1 required positional argument: 'applied_events'` in any test that builds a bundle directly. `compute_plan_only_run_id` callsites are unaffected (signature unchanged). Note these for Task 5 / Task 6.

- [ ] **Step 10: Patch the existing callsites in `engine/plan.py`**

Edit `src/chaos_librarian/engine/plan.py:87-90`. The `compute_plan_only_run_id` call stays 2-arg:

```python
    resolved_timeline = resolve_timeline(parsed)
    run_id = compute_plan_only_run_id(
        scenario_content_hash=run_input.content_hash,
        resolved_seed=resolved_seed,
    )
```

Update the bundle constructor at lines 105-113 to include `applied_events=len(resolved_timeline)` AND `journal_digest=journal_digest` (the new field still gets set on the bundle — it's just not hashed). Compute `journal_digest` immediately after the journal-building loop:

```python
import hashlib

journal_bytes = b"".join(
    entry.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8") + b"\n"
    for entry in journal
)
journal_digest = hashlib.sha256(journal_bytes).hexdigest()
```

Also change the for-loop on line 93 to iterate `resolved_timeline` instead of recomputing.

(Task 5 will extend this further with `steps_limit`; this step keeps Sprint 3 callers green so the contract bump can land independently.)

- [ ] **Step 11: Run the full suite — green again**

Run: `uv run pytest -q`
Expected: all tests pass. The Sprint 3 byte-identical regression tests still pass (every run still produces the same bytes for the same scenario+seed; only the constant they hash to has changed).

- [ ] **Step 12: Lint and type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 13: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/replay_bundle.py \
        src/chaos_librarian/engine/plan.py \
        schemas/replay-bundle.schema.json \
        tests/contract/test_replay_bundle.py
git commit -m "feat(contract): add applied_events + journal_digest to plan-only replay bundle

PlanOnlyReplayBundle now carries applied_events: int (raw event count,
constrained at replay time to a step boundary) and journal_digest: str
(sha256-hex of the serialized journal bytes). Neither field is hashed
into run_id — two bundles of the same scenario+seed at different
truncation points share a run_id (they describe the same logical run
at different prefixes). journal_digest gives replay a self-contained
integrity check: applied_events tampering is caught even when no
--against is supplied. REPLAY_BUNDLE_SCHEMA_VERSION bumps from 1 to 2
(single sprint, two field-adds) per the project-wide field-add rule."
```

---

## Task 2: `contract/reports.py` + report schema constants + drift-gate registration

**Files:**

- Create: `src/chaos_librarian/contract/reports.py` — six Pydantic models.
- Modify: `src/chaos_librarian/contract/__init__.py` — add four `*_REPORT_SCHEMA_VERSION: Final = 1` constants.
- Modify: `src/chaos_librarian/schema_export.py:29-37` — register four entries in `MODELS`.
- Create: `tests/contract/test_reports.py` — round-trip, `extra="forbid"`, schema-version pinning.
- Auto-generated: `schemas/asset-report.schema.json`, `work-report.schema.json`, `variant-report.schema.json`, `bundle-report.schema.json`.

The four report models capture the per-asset / per-work / per-variant / per-bundle adapter contract. They are derived from manifest + journal data only — no content hashes, no probed media facts. Sprint 5 will bump these versions when it adds those fields.

- [ ] **Step 1: Write the failing test**

Create `tests/contract/test_reports.py`:

```python
"""Tests for the four report schemas.

Reports are an adapter-facing contract; every field is part of the
public surface and must round-trip through Pydantic with no
serialization loss. ``extra="forbid"`` means typos in adapter-emitted
payloads are caught at the schema layer rather than silently ignored.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import (
    ASSET_REPORT_SCHEMA_VERSION,
    BUNDLE_REPORT_SCHEMA_VERSION,
    VARIANT_REPORT_SCHEMA_VERSION,
    WORK_REPORT_SCHEMA_VERSION,
)
from chaos_librarian.contract.reports import (
    AssetHistoryEntry,
    AssetReport,
    AssetSnapshot,
    BundleReport,
    VariantReport,
    WorkReport,
)


class TestAssetReport:
    """AssetReport carries initial/current snapshots + history.

    WHY: this is what adapter authors read to learn what happened to one
    asset across the timeline. Sprint 4 freezes the shape.
    """

    def _snapshot(self) -> AssetSnapshot:
        return AssetSnapshot(
            location_path="movies-hd/asset.mkv",
            version_id="version_0001",
            version_index=0,
        )

    def _history_entry(self) -> AssetHistoryEntry:
        return AssetHistoryEntry(
            logical_time_ns=2_000_000_000,
            event_id="move_001",
            action="move_asset",
            state_delta={"from": "movies-hd/asset.mkv", "to": "movies-hd/Blazar.mkv"},
        )

    def test_round_trip(self) -> None:
        report = AssetReport(
            schema_version=1,
            asset_id="asset_hd_main",
            initial=self._snapshot(),
            history=[self._history_entry()],
            current=self._snapshot(),
        )
        loaded = AssetReport.model_validate_json(report.model_dump_json())
        assert loaded == report

    def test_current_may_be_none(self) -> None:
        report = AssetReport(
            schema_version=1,
            asset_id="asset_hd_main",
            initial=self._snapshot(),
            history=[self._history_entry()],
            current=None,
        )
        parsed = json.loads(report.model_dump_json(exclude_none=False))
        assert parsed["current"] is None

    def test_rejects_extra_field(self) -> None:
        payload = {
            "schema_version": 1,
            "asset_id": "asset_hd_main",
            "initial": self._snapshot().model_dump(),
            "history": [],
            "current": None,
            "content_hash": "abc",  # Sprint 5 field — must be rejected at Sprint 4
        }
        with pytest.raises(ValidationError):
            AssetReport.model_validate(payload)

    def test_schema_version_constant_is_one(self) -> None:
        """The exported constant pins the Literal annotation."""
        assert ASSET_REPORT_SCHEMA_VERSION == 1


class TestOtherReports:
    """Work / variant / bundle reports list members + cross-references.

    WHY: the three reports are the navigation surface adapters use to
    walk from a work down to its assets, or from a bundle up to its
    variant.
    """

    def test_work_report_round_trip(self) -> None:
        wr = WorkReport(
            schema_version=1,
            work_id="work_blazar",
            title="Synthetic Blazar",
            variant_ids=["variant_hd"],
            asset_ids=["asset_hd_main"],
        )
        assert WorkReport.model_validate_json(wr.model_dump_json()) == wr

    def test_variant_report_round_trip(self) -> None:
        vr = VariantReport(
            schema_version=1,
            variant_id="variant_hd",
            work_id="work_blazar",
            label="hd",
            bundle_id="bundle_hd",
            asset_ids=["asset_hd_main"],
        )
        assert VariantReport.model_validate_json(vr.model_dump_json()) == vr

    def test_bundle_report_round_trip(self) -> None:
        br = BundleReport(
            schema_version=1,
            bundle_id="bundle_hd",
            variant_id="variant_hd",
            asset_ids=["asset_hd_main"],
            sidecar_ids=[],
        )
        assert BundleReport.model_validate_json(br.model_dump_json()) == br

    def test_constants_are_one(self) -> None:
        assert WORK_REPORT_SCHEMA_VERSION == 1
        assert VARIANT_REPORT_SCHEMA_VERSION == 1
        assert BUNDLE_REPORT_SCHEMA_VERSION == 1
```

- [ ] **Step 2: Run the failing test**

Run: `uv run pytest tests/contract/test_reports.py -v`
Expected: ImportError — `chaos_librarian.contract.reports` does not exist; the four `*_REPORT_SCHEMA_VERSION` constants are missing from `chaos_librarian.contract.__init__`.

- [ ] **Step 3: Add the four constants**

Edit `src/chaos_librarian/contract/__init__.py`, after line 21 (after `RUN_SENTINEL_SCHEMA_VERSION`), add:

```python
ASSET_REPORT_SCHEMA_VERSION: Final = 1
WORK_REPORT_SCHEMA_VERSION: Final = 1
VARIANT_REPORT_SCHEMA_VERSION: Final = 1
BUNDLE_REPORT_SCHEMA_VERSION: Final = 1
```

- [ ] **Step 4: Create the report models**

Create `src/chaos_librarian/contract/reports.py`:

```python
"""Per-entity report schemas (adapter-facing contract).

Sprint 4 reports are derived purely from manifest + journal data. They do
NOT carry content hashes or probed media facts — those land in Sprint 5
under ``schema_version: 2`` (per the project-wide field-add rule).

Reports are emitted by ``plan`` and ``step`` into ``<run-dir>/reports/``
as four parallel sub-trees (``assets/``, ``works/``, ``variants/``,
``bundles/``). External consumers (voom-v2) key on ``schema_version`` and
load the matching exported schema.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AssetSnapshot(BaseModel):
    """A point-in-time view of one asset's location + version binding."""

    model_config = ConfigDict(extra="forbid")

    location_path: str | None  # None if the asset is currently deleted
    version_id: str
    version_index: int


class AssetHistoryEntry(BaseModel):
    """One journal event that targets this asset, verbatim."""

    model_config = ConfigDict(extra="forbid")

    logical_time_ns: int
    event_id: str
    action: str
    state_delta: dict[str, object]


class AssetReport(BaseModel):
    """Per-asset history report — initial snapshot, ordered history, current snapshot.

    ``current`` is ``None`` if the asset has been deleted; ``history``
    still includes the ``delete_file`` entry in that case.
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    asset_id: str
    initial: AssetSnapshot
    history: list[AssetHistoryEntry] = Field(default_factory=list)
    current: AssetSnapshot | None


class WorkReport(BaseModel):
    """Per-work report — variants + transitive asset ids."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    work_id: str
    title: str
    variant_ids: list[str]
    asset_ids: list[str]


class VariantReport(BaseModel):
    """Per-variant report — owning work, bundle, member assets."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    variant_id: str
    work_id: str
    label: str
    bundle_id: str
    asset_ids: list[str]


class BundleReport(BaseModel):
    """Per-bundle report — owning variant, member assets, currently-bound sidecars."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    bundle_id: str
    variant_id: str
    asset_ids: list[str]
    sidecar_ids: list[str] = Field(default_factory=list)
```

- [ ] **Step 5: Register the new models in `schema_export.py`**

Edit `src/chaos_librarian/schema_export.py:29-37`. Add four entries to `MODELS` after the existing seven:

```python
from chaos_librarian.contract.reports import (
    AssetReport,
    BundleReport,
    VariantReport,
    WorkReport,
)

MODELS: Final[list[tuple[str, object]]] = [
    ("scenario.schema.json", Scenario),
    ("manifest.schema.json", Manifest),
    ("journal.schema.json", TypeAdapter(JournalEntry)),
    ("replay-bundle.schema.json", TypeAdapter(ReplayBundle)),
    ("validation.schema.json", ValidationReport),
    ("materialization.schema.json", MaterializationReport),
    ("run-sentinel.schema.json", RunSentinel),
    ("asset-report.schema.json", AssetReport),
    ("work-report.schema.json", WorkReport),
    ("variant-report.schema.json", VariantReport),
    ("bundle-report.schema.json", BundleReport),
]
```

- [ ] **Step 6: Run the tests — they now pass**

Run: `uv run pytest tests/contract/test_reports.py -v`
Expected: every test passes.

- [ ] **Step 7: Regenerate the schemas**

Run: `uv run python -m chaos_librarian.schema_export --write`
Expected: `Wrote 11 schemas to .../schemas`. Four new files appear under `schemas/`: `asset-report.schema.json`, `work-report.schema.json`, `variant-report.schema.json`, `bundle-report.schema.json`.

- [ ] **Step 8: Confirm drift gate is clean**

Run: `uv run python -m chaos_librarian.schema_export --check`
Expected: `All 11 schemas up-to-date.`

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest -q`
Expected: every test passes (the four new schemas don't affect any existing test).

- [ ] **Step 10: Lint and type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 11: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/reports.py \
        src/chaos_librarian/schema_export.py \
        schemas/asset-report.schema.json \
        schemas/work-report.schema.json \
        schemas/variant-report.schema.json \
        schemas/bundle-report.schema.json \
        tests/contract/test_reports.py
git commit -m "feat(contract): add four per-entity report schemas

AssetReport, WorkReport, VariantReport, BundleReport. All four start
at schema_version=1; Sprint 5 will bump them when content hashes land.
Reports are derived from manifest + journal data only — no content
hashes, no probed media facts."
```

---

## Task 3: `engine/reports.py` — pure `build_report_set` function

**Files:**

- Create: `src/chaos_librarian/engine/reports.py` — `ReportSet` dataclass + `build_report_set`.
- Create: `tests/engine/test_reports.py` — synthetic-input tests for every cross-cut.

`build_report_set` is a pure function: it takes `initial: Manifest`, `current: Manifest`, `journal: Iterable[JournalEntry]` and returns a `ReportSet` of immutable, lexicographically-sorted report tuples. It has no I/O and no engine state — both `run_plan` (after the timeline loop) and `step_fixture` (after each advance) call it.

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_reports.py`:

```python
"""Tests for chaos_librarian.engine.reports.build_report_set."""

from __future__ import annotations

import uuid

from chaos_librarian.contract.journal import AtomicJournalEntry, JournalPhase
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
from chaos_librarian.engine.reports import ReportSet, build_report_set


_RUN_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _manifest_with_one_asset(*, location_path: str | None = "movies-hd/a.mkv") -> Manifest:
    locations = (
        [
            ManifestLocation(
                id="location_0001",
                asset_id="asset_hd_main",
                path=location_path,
            )
        ]
        if location_path is not None
        else []
    )
    return Manifest(
        schema_version=1,
        works=[ManifestWork(id="work_blazar", title="Synthetic Blazar")],
        variants=[ManifestVariant(id="variant_hd", work_id="work_blazar", label="hd")],
        bundles=[ManifestBundle(id="bundle_hd", variant_id="variant_hd")],
        assets=[
            ManifestAsset(
                id="asset_hd_main",
                bundle_id="bundle_hd",
                role="primary_video",
                container="mkv",
                duration_seconds=12.0,
            )
        ],
        versions=[ManifestVersion(id="version_0001", asset_id="asset_hd_main", index=0)],
        locations=locations,
        sidecars=[],
    )


def _atomic_entry(*, event_id: str, action: str, target: str, delta: dict[str, object]) -> AtomicJournalEntry:
    return AtomicJournalEntry(
        schema_version=1,
        event_id=event_id,
        scenario_id="t",
        run_id=_RUN_ID,
        logical_time_ns=1_000_000_000,
        action=action,
        target_ids=[target],
        state_delta=delta,
        phase=JournalPhase.ATOMIC,
    )


class TestBuildReportSet:
    """Reports describe the asset/work/variant/bundle cross-cuts of a run.

    WHY: this is the adapter-facing contract; every cross-cut listed in
    the design must populate.
    """

    def test_empty_journal_yields_initial_history(self) -> None:
        m = _manifest_with_one_asset()
        rs = build_report_set(initial=m, current=m, journal=[])
        assert isinstance(rs, ReportSet)
        assert len(rs.assets) == 1
        assert rs.assets[0].history == []
        assert rs.assets[0].current == rs.assets[0].initial

    def test_history_filters_to_asset_target(self) -> None:
        m = _manifest_with_one_asset()
        entry = _atomic_entry(
            event_id="move_001",
            action="move_asset",
            target="asset_hd_main",
            delta={"to": "movies-hd/Blazar.mkv"},
        )
        rs = build_report_set(initial=m, current=m, journal=[entry])
        asset_report = rs.assets[0]
        assert len(asset_report.history) == 1
        assert asset_report.history[0].event_id == "move_001"
        assert asset_report.history[0].action == "move_asset"
        assert asset_report.history[0].state_delta == {"to": "movies-hd/Blazar.mkv"}

    def test_deleted_asset_has_none_current(self) -> None:
        initial = _manifest_with_one_asset()
        current = _manifest_with_one_asset(location_path=None)
        # In a real run the current manifest would also drop the location row;
        # here the snapshot lookup falls back to "no location" → current is None.
        entry = _atomic_entry(
            event_id="del_001",
            action="delete_file",
            target="asset_hd_main",
            delta={},
        )
        rs = build_report_set(initial=initial, current=current, journal=[entry])
        assert rs.assets[0].current is None
        assert any(h.action == "delete_file" for h in rs.assets[0].history)

    def test_work_lists_variants_and_transitive_assets(self) -> None:
        m = _manifest_with_one_asset()
        rs = build_report_set(initial=m, current=m, journal=[])
        wr = rs.works[0]
        assert wr.work_id == "work_blazar"
        assert wr.variant_ids == ["variant_hd"]
        assert wr.asset_ids == ["asset_hd_main"]

    def test_variant_links_bundle_and_work(self) -> None:
        m = _manifest_with_one_asset()
        rs = build_report_set(initial=m, current=m, journal=[])
        vr = rs.variants[0]
        assert vr.variant_id == "variant_hd"
        assert vr.work_id == "work_blazar"
        assert vr.bundle_id == "bundle_hd"
        assert vr.asset_ids == ["asset_hd_main"]

    def test_bundle_lists_assets_and_sidecars(self) -> None:
        m = _manifest_with_one_asset()
        m.sidecars.append(
            ManifestSidecar(
                id="sidecar_0001",
                asset_id="asset_hd_main",
                kind="subtitles",
                path="movies-hd/a.eng.srt",
            )
        )
        rs = build_report_set(initial=m, current=m, journal=[])
        br = rs.bundles[0]
        assert br.bundle_id == "bundle_hd"
        assert br.asset_ids == ["asset_hd_main"]
        assert br.sidecar_ids == ["sidecar_0001"]

    def test_iteration_order_is_stable(self) -> None:
        """Reports sort by id lexicographically.

        WHY: report files are written one per id; bit-identical fixtures
        require deterministic enumeration.
        """
        m = _manifest_with_one_asset()
        rs1 = build_report_set(initial=m, current=m, journal=[])
        rs2 = build_report_set(initial=m, current=m, journal=[])
        assert [a.asset_id for a in rs1.assets] == [a.asset_id for a in rs2.assets]
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/engine/test_reports.py -v`
Expected: ImportError — `chaos_librarian.engine.reports` does not exist.

- [ ] **Step 3: Implement `build_report_set`**

Create `src/chaos_librarian/engine/reports.py`:

```python
"""Per-entity report builders.

``build_report_set`` is a pure function: it takes the initial manifest,
the current manifest, and the journal, and returns a ``ReportSet`` of
sorted, immutable report tuples. Both ``run_plan`` (after the timeline
loop) and ``step_fixture`` (after each advance) call it; neither owns
any persistence — see ``engine/writer.py`` for that.

Iteration order is lexicographic on id so report files are bit-identical
for the same logical state.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import Manifest, ManifestLocation, ManifestVersion
from chaos_librarian.contract.reports import (
    AssetHistoryEntry,
    AssetReport,
    AssetSnapshot,
    BundleReport,
    VariantReport,
    WorkReport,
)


@dataclass(frozen=True)
class ReportSet:
    """Sorted, immutable bundle of every per-entity report a fixture emits."""

    assets: tuple[AssetReport, ...]
    works: tuple[WorkReport, ...]
    variants: tuple[VariantReport, ...]
    bundles: tuple[BundleReport, ...]


def build_report_set(
    *,
    initial: Manifest,
    current: Manifest,
    journal: Iterable[JournalEntry],
) -> ReportSet:
    """Derive per-entity reports from manifest + journal state.

    Args:
        initial: The initial manifest emitted at ``t=0``.
        current: The manifest reflecting the state after the journal's
            last entry.
        journal: Every journal entry in the run so far. Iterated once.

    Returns:
        ``ReportSet`` sorted lexicographically by id within each tuple.
    """
    journal_list = list(journal)
    assets = tuple(
        sorted(
            (
                _build_asset_report(asset.id, initial, current, journal_list)
                for asset in initial.assets
            ),
            key=lambda a: a.asset_id,
        )
    )
    works = tuple(sorted((_build_work_report(w, initial) for w in initial.works), key=lambda r: r.work_id))
    variants = tuple(
        sorted((_build_variant_report(v, initial) for v in initial.variants), key=lambda r: r.variant_id)
    )
    bundles = tuple(
        sorted((_build_bundle_report(b, initial, current) for b in initial.bundles), key=lambda r: r.bundle_id)
    )
    return ReportSet(assets=assets, works=works, variants=variants, bundles=bundles)


def _snapshot_for(asset_id: str, manifest: Manifest) -> AssetSnapshot | None:
    version = _find_version(asset_id, manifest.versions)
    if version is None:
        return None
    location = _find_location(asset_id, manifest.locations)
    return AssetSnapshot(
        location_path=location.path if location else None,
        version_id=version.id,
        version_index=version.index,
    )


def _find_version(asset_id: str, versions: list[ManifestVersion]) -> ManifestVersion | None:
    for v in versions:
        if v.asset_id == asset_id:
            return v
    return None


def _find_location(asset_id: str, locations: list[ManifestLocation]) -> ManifestLocation | None:
    for loc in locations:
        if loc.asset_id == asset_id:
            return loc
    return None


def _build_asset_report(
    asset_id: str,
    initial: Manifest,
    current: Manifest,
    journal: list[JournalEntry],
) -> AssetReport:
    initial_snapshot = _snapshot_for(asset_id, initial)
    if initial_snapshot is None:
        raise ValueError(f"asset {asset_id} missing from initial manifest")
    history = [
        AssetHistoryEntry(
            logical_time_ns=entry.logical_time_ns,
            event_id=entry.event_id,
            action=entry.action,
            state_delta=dict(entry.state_delta),
        )
        for entry in journal
        if asset_id in entry.target_ids
    ]
    return AssetReport(
        schema_version=1,
        asset_id=asset_id,
        initial=initial_snapshot,
        history=history,
        current=_snapshot_for(asset_id, current),
    )


def _build_work_report(work, initial: Manifest) -> WorkReport:
    variant_ids = sorted(v.id for v in initial.variants if v.work_id == work.id)
    asset_ids: list[str] = []
    for v in initial.variants:
        if v.work_id != work.id:
            continue
        for b in initial.bundles:
            if b.variant_id != v.id:
                continue
            asset_ids.extend(a.id for a in initial.assets if a.bundle_id == b.id)
    return WorkReport(
        schema_version=1,
        work_id=work.id,
        title=work.title,
        variant_ids=variant_ids,
        asset_ids=sorted(asset_ids),
    )


def _build_variant_report(variant, initial: Manifest) -> VariantReport:
    bundle = next(b for b in initial.bundles if b.variant_id == variant.id)
    asset_ids = sorted(a.id for a in initial.assets if a.bundle_id == bundle.id)
    return VariantReport(
        schema_version=1,
        variant_id=variant.id,
        work_id=variant.work_id,
        label=variant.label,
        bundle_id=bundle.id,
        asset_ids=asset_ids,
    )


def _build_bundle_report(bundle, initial: Manifest, current: Manifest) -> BundleReport:
    asset_ids = sorted(a.id for a in initial.assets if a.bundle_id == bundle.id)
    sidecar_ids = sorted(s.id for s in current.sidecars if s.asset_id in set(asset_ids))
    return BundleReport(
        schema_version=1,
        bundle_id=bundle.id,
        variant_id=bundle.variant_id,
        asset_ids=asset_ids,
        sidecar_ids=sidecar_ids,
    )
```

- [ ] **Step 4: Run the tests — they pass**

Run: `uv run pytest tests/engine/test_reports.py -v`
Expected: every test passes.

- [ ] **Step 5: Run the broader suite**

Run: `uv run pytest -q`
Expected: every test passes.

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/engine/reports.py tests/engine/test_reports.py
git commit -m "feat(engine): add build_report_set pure function

Derives per-asset/work/variant/bundle reports from manifest + journal
data. Pure function — no I/O. Both run_plan and step_fixture call it.
Iteration order is lexicographic on id so report files are
bit-identical for the same logical state."
```

---

## Task 4: `engine/writer.py` — emit `reports/` + new `append_step`

**Files:**

- Modify: `src/chaos_librarian/engine/writer.py` — `write_fixture` stages `reports/` subdirs; new `append_step` function.
- Modify: `src/chaos_librarian/engine/plan.py` — `PlanArtifacts` gains `reports: ReportSet`; `run_plan` populates it via `build_report_set`.
- Modify: `tests/engine/test_writer.py` — assert `reports/` files are written and bit-identical across runs.

`write_fixture` already does the transactional-staging dance. Sprint 4 adds `reports/{assets,works,variants,bundles}/<id>.json` to the staged tree before the atomic rename. `append_step` is the equivalent for incrementally updating an existing fixture: it rewrites the four mutable files (`manifest.current.json`, `replay.json`, every report file) atomically per-file, and appends to the journal.

- [ ] **Step 1: Add `reports` to `PlanArtifacts`**

Edit `src/chaos_librarian/engine/plan.py:42-52`:

```python
from chaos_librarian.engine.reports import ReportSet, build_report_set


@dataclass(frozen=True)
class PlanArtifacts:
    """In-memory result of a plan-only run, prior to persistence."""

    initial_manifest: Manifest
    current_manifest: Manifest
    journal: tuple[JournalEntry, ...]
    replay_bundle: PlanOnlyReplayBundle
    validation_report: ValidationReport
    sentinel: RunSentinel
    reports: ReportSet
```

In `run_plan` (around line 103), after `current_manifest = initial_state.to_manifest()`, add:

```python
    reports = build_report_set(
        initial=initial_manifest,
        current=current_manifest,
        journal=journal,
    )
```

Add `reports=reports` to the `return PlanArtifacts(...)` call.

- [ ] **Step 2: Write the failing writer tests**

Add to `tests/engine/test_writer.py` (new file if doesn't exist; otherwise append):

```python
class TestWriterEmitsReports:
    """write_fixture stages reports/ subdirs before the atomic rename.

    WHY: reports are part of every plan-only fixture; adapter consumers
    rely on them. The subdir layout (assets/works/variants/bundles) is
    public contract.
    """

    def test_reports_subdirs_exist(self, tmp_path: Path) -> None:
        run_input, report = _prepare("identity-move-rename.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report)
        out = tmp_path / "run"
        write_fixture(out, artifacts, run_input.raw_bytes)
        assert (out / "reports" / "assets").is_dir()
        assert (out / "reports" / "works").is_dir()
        assert (out / "reports" / "variants").is_dir()
        assert (out / "reports" / "bundles").is_dir()

    def test_asset_report_file_per_id(self, tmp_path: Path) -> None:
        run_input, report = _prepare("identity-move-rename.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report)
        out = tmp_path / "run"
        write_fixture(out, artifacts, run_input.raw_bytes)
        assert (out / "reports" / "assets" / "asset_hd_main.json").exists()

    def test_two_writes_byte_identical(self, tmp_path: Path) -> None:
        run_input, report = _prepare("identity-move-rename.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report)
        a = tmp_path / "a"
        b = tmp_path / "b"
        write_fixture(a, artifacts, run_input.raw_bytes)
        write_fixture(b, artifacts, run_input.raw_bytes)
        for report_dir in ["assets", "works", "variants", "bundles"]:
            a_files = sorted((a / "reports" / report_dir).iterdir())
            b_files = sorted((b / "reports" / report_dir).iterdir())
            assert [p.name for p in a_files] == [p.name for p in b_files]
            for fa, fb in zip(a_files, b_files, strict=True):
                assert fa.read_bytes() == fb.read_bytes(), fa.name


class TestAppendStep:
    """append_step updates manifest.current/replay.json/reports atomically.

    WHY: step mode mutates a fixture in-place; the updated files must
    appear consistently or not at all.
    """

    def test_journal_grows(self, tmp_path: Path) -> None:
        run_input, report = _prepare("identity-move-rename.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report, steps_limit=0)
        out = tmp_path / "run"
        write_fixture(out, artifacts, run_input.raw_bytes)
        # Journal starts empty
        assert (out / "journal.jsonl").read_text() == ""
        # Re-plan with the first event applied
        artifacts_after = run_plan(run_input=run_input, validation_report=report, steps_limit=1)
        new_entries = artifacts_after.journal
        append_step(
            out,
            new_entries=new_entries,
            new_current_manifest=artifacts_after.current_manifest,
            new_report_set=artifacts_after.reports,
            new_replay_bundle=artifacts_after.replay_bundle,
        )
        # One line now present in the journal
        assert sum(1 for _ in (out / "journal.jsonl").read_text().splitlines()) == 1
```

(`_prepare` is a helper that calls `prepare_run_input` + `run_validation`; reuse the existing helper in `test_writer.py` or define one near the top of the new tests.)

- [ ] **Step 3: Run the failing tests**

Run: `uv run pytest tests/engine/test_writer.py -v`
Expected: failures — `write_fixture` doesn't stage `reports/`, `append_step` doesn't exist.

- [ ] **Step 4: Extend `write_fixture` to stage `reports/`**

Edit `src/chaos_librarian/engine/writer.py`. After the existing artifact writes inside the `try:` block (after `_emit_json(artifacts.validation_report, staging / "validation.json")`), before `_emit_sentinel`:

```python
        _stage_reports(staging, artifacts.reports)
```

Add the helper function near the bottom of the file:

```python
def _stage_reports(staging: Path, reports: ReportSet) -> None:
    reports_root = staging / "reports"
    (reports_root / "assets").mkdir(parents=True)
    (reports_root / "works").mkdir()
    (reports_root / "variants").mkdir()
    (reports_root / "bundles").mkdir()
    for report in reports.assets:
        _emit_json(report, reports_root / "assets" / f"{report.asset_id}.json")
    for report in reports.works:
        _emit_json(report, reports_root / "works" / f"{report.work_id}.json")
    for report in reports.variants:
        _emit_json(report, reports_root / "variants" / f"{report.variant_id}.json")
    for report in reports.bundles:
        _emit_json(report, reports_root / "bundles" / f"{report.bundle_id}.json")
```

Add the import at the top of the file:

```python
from chaos_librarian.engine.reports import ReportSet
```

- [ ] **Step 5: Implement `append_step`**

Add to `src/chaos_librarian/engine/writer.py`:

```python
def append_step(
    run_dir: Path,
    *,
    new_entries: Iterable[JournalEntry],
    new_current_manifest: Manifest,
    new_report_set: ReportSet,
    new_replay_bundle: PlanOnlyReplayBundle,
) -> None:
    """Update an existing plan-only fixture with a step's new journal entries.

    Rewrites the four mutable files atomically per-file (sibling tempfile +
    ``Path.replace``) and appends the new journal lines. Not atomic *across*
    files; the documented recovery rule is that the next ``step --next``
    re-derives state from the journal — see
    docs/superpowers/specs/2026-05-18-sprint-4-design.md "Edge case 12".

    Args:
        run_dir: An existing fixture directory created by ``write_fixture``.
        new_entries: Journal entries to append to ``journal.jsonl``.
        new_current_manifest: Manifest after the step's events.
        new_report_set: Report set after the step's events.
        new_replay_bundle: Replay bundle with updated applied_events and
            recomputed run_id.
    """
    _replace_atomic(run_dir / "manifest.current.json", _emit_to_str(new_current_manifest))
    _replace_atomic(run_dir / "replay.json", _emit_to_str(new_replay_bundle))
    _replace_atomic_reports(run_dir / "reports", new_report_set)
    _append_journal_lines(run_dir / "journal.jsonl", new_entries)


def _emit_to_str(model: BaseModel) -> str:
    return model.model_dump_json(indent=2, by_alias=True, exclude_none=True) + "\n"


def _replace_atomic(target: Path, content: str) -> None:
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(target)


def _replace_atomic_reports(reports_root: Path, reports: ReportSet) -> None:
    for report in reports.assets:
        _replace_atomic(reports_root / "assets" / f"{report.asset_id}.json", _emit_to_str(report))
    for report in reports.works:
        _replace_atomic(reports_root / "works" / f"{report.work_id}.json", _emit_to_str(report))
    for report in reports.variants:
        _replace_atomic(reports_root / "variants" / f"{report.variant_id}.json", _emit_to_str(report))
    for report in reports.bundles:
        _replace_atomic(reports_root / "bundles" / f"{report.bundle_id}.json", _emit_to_str(report))


def _append_journal_lines(target: Path, entries: Iterable[JournalEntry]) -> None:
    lines = [entry.model_dump_json(by_alias=True, exclude_none=True) for entry in entries]
    if not lines:
        return
    existing = target.read_text() if target.exists() else ""
    suffix = "\n".join(lines) + "\n"
    target.write_text(existing + suffix)
```

Add the import at the top:

```python
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle
```

- [ ] **Step 6: Run the tests — they pass**

Run: `uv run pytest tests/engine/test_writer.py -v`
Expected: every test passes.

Note: the `test_journal_grows` test depends on `run_plan(..., steps_limit=...)` which lands in Task 5. If running this task standalone, mark that test `xfail` for now and remove the marker in Task 5; if running in order, Task 5 lands before the test executes.

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: every test passes. Existing `test_plan.py` and `test_plan_e2e.py` tests now require `reports=` in any directly-constructed `PlanArtifacts`; update those callsites if any are direct (the e2e tests go through `run_plan` so they pick up the new field automatically).

- [ ] **Step 8: Lint and type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 9: Commit**

```bash
git add src/chaos_librarian/engine/plan.py \
        src/chaos_librarian/engine/writer.py \
        tests/engine/test_writer.py \
        tests/engine/test_plan.py
git commit -m "feat(engine): write reports/ subdirs + add append_step

write_fixture stages reports/{assets,works,variants,bundles}/<id>.json
before the atomic rename. append_step updates an existing fixture
in-place: per-file atomic rewrites of manifest.current.json,
replay.json, and every report; append for journal.jsonl. PlanArtifacts
carries the ReportSet so write_fixture has a single source."
```

---

## Task 4.5: `engine/resolution.py` — `step_boundaries` helper

**Files:**

- Modify: `src/chaos_librarian/engine/resolution.py` — append `step_boundaries(resolved_timeline) -> list[int]`.
- Create: `tests/engine/test_resolution.py` — boundary tests.

This helper is the single source of truth for step-unit semantics. `run_plan`, `step_fixture`, `replay_plan_bundle`, and `inspect` all translate between raw event counts and user-visible step counts via this one function. Adjacent `slow_copy_start` + `slow_copy_commit` (matching `for_` ↔ `id`) is one step; non-adjacent halves degrade to single-event steps (defensive default — non-adjacent pairs are out of scope for Sprint 4).

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_resolution.py`:

```python
"""Tests for chaos_librarian.engine.resolution.step_boundaries.

WHY: step_boundaries is the single source of truth for step-unit
semantics across run_plan, step_fixture, replay_plan_bundle, and
inspect. Wrong boundaries here mean --steps N and --next N count the
wrong thing — exactly the Codex round 3 finding 1 failure mode.
"""

from __future__ import annotations

from chaos_librarian.engine.resolution import resolve_timeline, step_boundaries
# (additional imports for synthetic ResolvedEvent / Scenario construction)


class TestStepBoundaries:
    def test_atomic_only_scenario(self) -> None:
        # identity-move-rename: two atomic events
        resolved = resolve_timeline(_scenario("identity-move-rename.yaml"))
        assert step_boundaries(resolved) == [1, 2]

    def test_slow_copy_adjacent_pair_is_one_step(self) -> None:
        # slow-copy.yaml: slow_copy_start + slow_copy_commit (adjacent, matching for_/id)
        resolved = resolve_timeline(_scenario("slow-copy.yaml"))
        assert step_boundaries(resolved) == [2]

    def test_non_adjacent_slow_copy_degrades_to_singles(self) -> None:
        # Synthetic: [slow_copy_start, atomic_move, slow_copy_commit]
        resolved = _synthetic_three_event_with_split_pair()
        assert step_boundaries(resolved) == [1, 2, 3]

    def test_empty_timeline(self) -> None:
        assert step_boundaries([]) == []
```

- [ ] **Step 2: Implement `step_boundaries`**

Append to `src/chaos_librarian/engine/resolution.py`:

```python
def step_boundaries(resolved_timeline: list[ResolvedEvent]) -> list[int]:
    """Return cumulative raw-event counts after each step-unit boundary.

    A consecutive ``slow_copy_start`` followed by ``slow_copy_commit`` whose
    ``for_`` field references the start's ``id`` is one step unit covering
    two raw events. Every other action is its own single-event step.
    """
    boundaries: list[int] = []
    i = 0
    while i < len(resolved_timeline):
        action = resolved_timeline[i].event.action
        if (
            action == TimelineActionName.SLOW_COPY_START
            and i + 1 < len(resolved_timeline)
            and resolved_timeline[i + 1].event.action == TimelineActionName.SLOW_COPY_COMMIT
            and resolved_timeline[i + 1].event.for_ == resolved_timeline[i].event.id
        ):
            boundaries.append(i + 2)
            i += 2
        else:
            boundaries.append(i + 1)
            i += 1
    return boundaries
```

- [ ] **Step 3: Run tests; expect pass**

Run: `uv run pytest tests/engine/test_resolution.py -v`
Expected: every test passes.

- [ ] **Step 4: Lint, type-check, commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

```bash
git add src/chaos_librarian/engine/resolution.py tests/engine/test_resolution.py
git commit -m "feat(engine): add step_boundaries helper

step_boundaries(resolved_timeline) is the single source of truth for
step-unit semantics. A consecutive slow_copy_start + slow_copy_commit
pair (matching for_/id) is one step unit (+2 raw events); every other
action is its own single-event step. run_plan, step_fixture,
replay_plan_bundle, and inspect all derive boundary lists from this
one helper."
```

---

## Task 5: `run_plan` accepts `steps_limit` + sets `applied_events`

**Files:**

- Modify: `src/chaos_librarian/engine/plan.py:54-130` — add `steps_limit: int | None = None` parameter; respect it in the timeline loop; set `applied_events` on the bundle constructor. `compute_plan_only_run_id` stays 2-arg.
- Modify: `tests/engine/test_plan.py` — add `TestRunPlanStepsLimit` class.

This is the contract surface for `plan --steps N`. Behavior unchanged when `steps_limit is None` (full timeline). When set, the timeline loop stops after `min(steps_limit, len(resolved_timeline))` resolved events have been applied; `applied_events` records that count on the bundle. `run_id` is computed from `scenario_content_hash` + `resolved_seed` only — two partial runs of the same scenario+seed share a `run_id` regardless of `applied_events`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/engine/test_plan.py`:

```python
class TestRunPlanStepsLimit:
    """run_plan stops at steps_limit and binds applied_events accordingly.

    WHY: partial fixtures are first-class artifacts (decision #12). Their
    identity is bound to scenario+seed via run_id; the prefix length is
    recorded separately in applied_events so two truncation points of
    the same run share a run_id.
    """

    def test_zero_steps_yields_empty_journal(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report, steps_limit=0)
        assert artifacts.journal == ()
        assert artifacts.replay_bundle.applied_events == 0
        assert (
            artifacts.replay_bundle.journal_digest
            == hashlib.sha256(b"").hexdigest()
        )
        # Same scenario+seed → same run_id, even though applied_events differ.
        full = run_plan(run_input=run_input, validation_report=report)
        assert full.replay_bundle.applied_events == 2  # identity-move-rename has two events
        assert full.replay_bundle.run_id == artifacts.replay_bundle.run_id

    def test_partial_run_shared_run_id(self) -> None:
        # identity-move-rename: two atomic events → boundaries = [1, 2]
        run_input, report = _input_and_report("identity-move-rename.yaml")
        one = run_plan(run_input=run_input, validation_report=report, steps_limit=1)
        two = run_plan(run_input=run_input, validation_report=report, steps_limit=2)
        assert one.replay_bundle.applied_events == 1
        assert two.replay_bundle.applied_events == 2
        assert one.replay_bundle.run_id == two.replay_bundle.run_id
        assert len(one.journal) == 1
        assert len(two.journal) == 2
        # slow-copy: one step unit covers two raw events → boundaries = [2]
        sc_input, sc_report = _input_and_report("slow-copy.yaml")
        sc_one = run_plan(run_input=sc_input, validation_report=sc_report, steps_limit=1)
        assert sc_one.replay_bundle.applied_events == 2
        assert len(sc_one.journal) == 2

    def test_steps_limit_exceeds_timeline_clamps(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report, steps_limit=99)
        assert artifacts.replay_bundle.applied_events == 2  # clamped
        full = run_plan(run_input=run_input, validation_report=report)
        assert artifacts.replay_bundle.run_id == full.replay_bundle.run_id

    def test_none_yields_full_run(self) -> None:
        """steps_limit=None is equivalent to len(timeline) for applied_events."""
        run_input, report = _input_and_report("identity-move-rename.yaml")
        none_run = run_plan(run_input=run_input, validation_report=report, steps_limit=None)
        full = run_plan(run_input=run_input, validation_report=report, steps_limit=2)
        assert none_run.replay_bundle.run_id == full.replay_bundle.run_id
        assert none_run.replay_bundle.applied_events == 2


class TestRunPlanSlowCopyBoundary:
    """--steps 1 on slow-copy.yaml applies BOTH start AND commit.

    WHY: Codex round 3 finding 1 — a step unit is user-visible, not
    journal-entry-shaped. One step on a slow_copy pair advances both
    halves together; the engine must never produce an off-boundary
    fixture.
    """

    def test_slow_copy_one_step_applies_both_halves(self) -> None:
        run_input, report = _input_and_report("slow-copy.yaml")
        artifacts = run_plan(run_input=run_input, validation_report=report, steps_limit=1)
        assert artifacts.replay_bundle.applied_events == 2
        assert len(artifacts.journal) == 2
        # Ordering: started then committed
        assert artifacts.journal[0].phase.value == "started"
        assert artifacts.journal[1].phase.value == "committed"
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/engine/test_plan.py::TestRunPlanStepsLimit -v`
Expected: failures — `run_plan` doesn't accept `steps_limit`.

- [ ] **Step 3: Extend `run_plan`**

Edit `src/chaos_librarian/engine/plan.py`. Update the signature:

```python
def run_plan(
    *,
    run_input: RunInput,
    validation_report: ValidationReport,
    resolved_seed_override: int | None = None,
    steps_limit: int | None = None,
) -> PlanArtifacts:
```

Add the corresponding docstring sentence after the existing args:

```
    steps_limit: Cap on resolved events to apply. ``None`` (default)
        runs the entire timeline. ``0`` produces an empty journal and
        ``current_manifest == initial_manifest``. Values above
        ``len(resolve_timeline(parsed))`` are clamped silently.
```

Rewrite the body so it (a) materializes the resolved timeline once, (b) computes `applied_events` before the run_id call, and (c) caps the loop:

```python
    parsed = Scenario.model_validate(run_input.raw_data)
    resolved_seed = (
        resolved_seed_override if resolved_seed_override is not None else resolve_seed(parsed.seed)
    )
    recorder = TraceRecorder()
    ids = IdAllocator(recorder)

    initial_state = build_initial_state(parsed, ids)
    initial_manifest = initial_state.to_manifest()

    resolved_timeline = resolve_timeline(parsed)
    boundaries = step_boundaries(resolved_timeline)
    if steps_limit is None:
        applied_events = boundaries[-1] if boundaries else 0
    elif steps_limit <= 0:
        applied_events = 0
    elif steps_limit >= len(boundaries):
        applied_events = boundaries[-1] if boundaries else 0
    else:
        applied_events = boundaries[steps_limit - 1]

    run_id = compute_plan_only_run_id(
        scenario_content_hash=run_input.content_hash,
        resolved_seed=resolved_seed,
    )

    journal: list[JournalEntry] = []
    for resolved in resolved_timeline[:applied_events]:
        entries = apply_event(initial_state, resolved, ids, run_id, parsed.scenario_id)
        journal.extend(entries)

    journal_bytes = b"".join(
        entry.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8") + b"\n"
        for entry in journal
    )
    journal_digest = hashlib.sha256(journal_bytes).hexdigest()

    current_manifest = initial_state.to_manifest()
    reports = build_report_set(
        initial=initial_manifest,
        current=current_manifest,
        journal=journal,
    )

    bundle = PlanOnlyReplayBundle(
        schema_version=2,
        chaos_librarian_version=_chaos_librarian_version,
        scenario=run_input.raw_bytes.decode("utf-8"),
        run_id=run_id,
        resolved_seed=resolved_seed,
        applied_events=applied_events,
        journal_digest=journal_digest,
        execution_trace=list(recorder.entries()),
        execution_mode=ExecutionMode.PLAN_ONLY,
    )

    sentinel = RunSentinel(
        run_id=run_id,
        schema_version=1,
        created_by=f"chaos-librarian {_chaos_librarian_version}",
        created_at=None,
    )

    return PlanArtifacts(
        initial_manifest=initial_manifest,
        current_manifest=current_manifest,
        journal=tuple(journal),
        replay_bundle=bundle,
        validation_report=validation_report,
        sentinel=sentinel,
        reports=reports,
    )
```

Ensure `import hashlib` is at the top of `src/chaos_librarian/engine/plan.py` (Task 1 added it; if Task 5 runs ahead of Task 1's hashlib import, add it here). Import `step_boundaries` alongside the existing `resolve_timeline`:

```python
from chaos_librarian.engine.resolution import resolve_timeline, step_boundaries
```

- [ ] **Step 4: Run the new tests — they pass**

Run: `uv run pytest tests/engine/test_plan.py::TestRunPlanStepsLimit -v`
Expected: every test passes.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: every test passes; Sprint 3 byte-identical regression still passes (same scenario+seed still produces the same fixture).

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/engine/plan.py tests/engine/test_plan.py
git commit -m "feat(engine): run_plan accepts steps_limit (step-unit counted)

steps_limit=N counts user-visible step units, translated to raw event
counts via step_boundaries. A slow_copy_start + slow_copy_commit pair
advances together (one step = +2 raw events). applied_events records
the raw count actually applied and is recorded on the bundle as
metadata (not hashed into run_id). journal_digest is computed from the
serialized journal bytes for self-contained integrity checks at replay
time. steps_limit=None preserves Sprint 3 full-run semantics."
```

---

## Task 6: `replay_plan_bundle` passes `applied_events` as `steps_limit`

**Files:**

- Modify: `src/chaos_librarian/engine/plan.py:143-179` — `replay_plan_bundle` passes `bundle.applied_events` to `run_plan` as `steps_limit`.
- Modify: `tests/engine/test_plan.py` — add replay round-trip tests for `--steps 0` and `--steps K` partial bundles.

The Sprint 3 helper already exists and uses `resolved_seed_override`. Sprint 4 adds the `steps_limit` passthrough so a partial bundle replays as the same partial fixture. The integrity check at the end stays as Sprint 3 wrote it — only `scenario` / `resolved_seed` tampering trips `ReplayIntegrityError`. `applied_events` tampering is detected later, at the artifact-diff stage of `replay`: a tampered count produces a fixture of the tampered length that no longer byte-matches `--against` (covered by Task 13's CLI test).

- [ ] **Step 1: Write the failing tests**

Add to `tests/engine/test_plan.py`:

```python
class TestReplayPartialBundles:
    """replay_plan_bundle reproduces partial fixtures.

    WHY: decision #12 of the design — partial fixtures are first-class.
    The integrity check only fires on scenario / resolved_seed tampering;
    applied_events tampering is caught at the artifact-diff stage by the
    CLI (Task 13).
    """

    def test_replay_zero_step_bundle(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        original = run_plan(run_input=run_input, validation_report=report, steps_limit=0)
        replayed = replay_plan_bundle(original.replay_bundle)
        assert replayed.replay_bundle.run_id == original.replay_bundle.run_id
        assert replayed.replay_bundle.applied_events == 0
        assert replayed.journal == ()

    def test_replay_partial_bundle_round_trip(self) -> None:
        run_input, report = _input_and_report("identity-move-rename.yaml")
        original = run_plan(run_input=run_input, validation_report=report, steps_limit=1)
        replayed = replay_plan_bundle(original.replay_bundle)
        assert replayed.journal == original.journal
        assert replayed.replay_bundle.run_id == original.replay_bundle.run_id
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/engine/test_plan.py::TestReplayPartialBundles -v`
Expected: failures — `replay_plan_bundle` doesn't pass `steps_limit` through; partial replays produce full-run journals.

- [ ] **Step 3: Wire boundary, applied_events, and digest checks through `replay_plan_bundle`**

Edit `src/chaos_librarian/engine/plan.py:143-179`. Replace the integrity-check block with three checks (scenario/seed via run_id, boundary, digest):

```python
parsed = Scenario.model_validate(run_input.raw_data)
resolved_timeline = resolve_timeline(parsed)
boundaries = step_boundaries(resolved_timeline)
valid_boundaries = {0, *boundaries}
if bundle.applied_events not in valid_boundaries:
    raise ReplayIntegrityError(
        f"applied_events {bundle.applied_events} is not on a step boundary "
        f"(valid: {sorted(valid_boundaries)})"
    )

# Translate raw count to step-unit count for run_plan
if bundle.applied_events == 0:
    step_count = 0
else:
    step_count = boundaries.index(bundle.applied_events) + 1

artifacts = run_plan(
    run_input=run_input,
    validation_report=report,
    resolved_seed_override=bundle.resolved_seed,
    steps_limit=step_count,
)

if artifacts.replay_bundle.run_id != bundle.run_id:
    raise ReplayIntegrityError(...)  # existing scenario/seed check

if artifacts.replay_bundle.journal_digest != bundle.journal_digest:
    raise ReplayIntegrityError(
        f"journal_digest mismatch: recorded {bundle.journal_digest}, "
        f"recomputed {artifacts.replay_bundle.journal_digest}"
    )
```

The three checks run in order: scenario/seed via run_id (round 2 — unchanged), boundary (round 3, finding 1), digest (round 3, finding 2). All trip `ReplayIntegrityError` → exit 6. The boundary and digest checks fire even when no `--against` is supplied, giving the bundle self-contained integrity. Update the docstring's `Raises:` section to enumerate all three cases.

Add the test cases below (round 3 regressions) to `TestReplayPartialBundles` (or a new class `TestReplayIntegrityRoundThree`):

```python
def test_replay_mid_pair_tamper_trips_integrity(self) -> None:
    """Tampering applied_events to an off-boundary value trips integrity.

    WHY: Codex round 3 finding 1 — partial fixtures must land on a
    step-unit boundary; mid-pair counts are nonsensical.
    """
    run_input, report = _input_and_report("slow-copy.yaml")
    original = run_plan(run_input=run_input, validation_report=report, steps_limit=1)
    # boundaries == [2]; flip applied_events from 2 to 1 (mid-pair)
    tampered = original.replay_bundle.model_copy(update={"applied_events": 1})
    with pytest.raises(ReplayIntegrityError):
        replay_plan_bundle(tampered)


def test_replay_journal_digest_mismatch_trips_integrity(self) -> None:
    """Tampering journal_digest directly trips integrity.

    WHY: Codex round 3 finding 2 — digest is the self-contained integrity
    anchor.
    """
    run_input, report = _input_and_report("identity-move-rename.yaml")
    original = run_plan(run_input=run_input, validation_report=report, steps_limit=1)
    bogus = "0" * 64
    tampered = original.replay_bundle.model_copy(update={"journal_digest": bogus})
    with pytest.raises(ReplayIntegrityError):
        replay_plan_bundle(tampered)


def test_replay_applied_events_tampered_to_valid_boundary_trips_digest(self) -> None:
    """applied_events flipped between two valid boundaries is caught by digest.

    WHY: Codex round 3 finding 2 — without journal_digest, flipping
    applied_events from 1 to 2 (both valid on identity-move-rename) would
    silently produce a longer fixture. The recorded digest reflects the
    1-event journal, so the recomputed 2-event digest must mismatch.
    """
    run_input, report = _input_and_report("identity-move-rename.yaml")
    original = run_plan(run_input=run_input, validation_report=report, steps_limit=1)
    # boundaries == [1, 2]; both are valid. Flip applied_events but leave digest.
    tampered = original.replay_bundle.model_copy(update={"applied_events": 2})
    with pytest.raises(ReplayIntegrityError):
        replay_plan_bundle(tampered)
```

- [ ] **Step 4: Run the new tests — they pass**

Run: `uv run pytest tests/engine/test_plan.py::TestReplayPartialBundles -v`
Expected: every test passes.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: every test passes; Sprint 3 e2e replay round-trip still passes (full-run `applied_events` matches between original and replay).

- [ ] **Step 6: Lint and type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/engine/plan.py tests/engine/test_plan.py
git commit -m "feat(engine): replay_plan_bundle adds boundary + digest integrity

Three integrity checks fire in order before artifact-diff: (1) run_id
recompute (scenario/seed tampering), (2) applied_events on a step
boundary (Codex round 3 finding 1 — mid-pair counts), (3) journal_digest
match (Codex round 3 finding 2 — applied_events flipped between two
valid boundaries). All trip ReplayIntegrityError → exit 6. The boundary
and digest checks fire even when no --against is supplied, giving the
bundle self-contained integrity. After integrity passes, bundle.applied_events
(translated to a step-unit count) is threaded through as steps_limit so a
partial bundle replays as the same partial fixture."
```

---

## Task 7: `engine/step.py` — `step_fixture` with prefix-verification

**Files:**

- Create: `src/chaos_librarian/engine/step.py` — `StepResult` dataclass, `step_fixture`, three errors.
- Modify: `src/chaos_librarian/engine/__init__.py` — re-export `step_fixture`, `StepResult`, the three errors, `build_report_set`, `ReportSet`.
- Create: `tests/engine/test_step.py` — eleven tests covering happy path + four corruption modes + sentinel/tampering.

This is the largest engine task. `step_fixture` re-derives world state from the scenario by walking the timeline from `t=0`, verifying each regenerated journal entry against the on-disk entry (catching the second Codex finding). It then applies up to `n_events` more resolved events and returns the deltas. It does not write — that's `append_step`'s job in the CLI layer.

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_step.py`:

```python
"""Tests for chaos_librarian.engine.step.step_fixture."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle
from chaos_librarian.engine import (
    JournalCorruptError,
    ScenarioTamperedError,
    SentinelInvalidError,
    StepResult,
    step_fixture,
)
from chaos_librarian.engine.plan import run_plan
from chaos_librarian.engine.writer import write_fixture
from chaos_librarian.validation import prepare_run_input, run_validation

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _make_fixture(tmp_path: Path, scenario_name: str, *, steps_limit: int | None = None) -> Path:
    run_input = prepare_run_input(FIXTURE_DIR / scenario_name)
    report = run_validation(run_input)
    artifacts = run_plan(
        run_input=run_input,
        validation_report=report,
        steps_limit=steps_limit,
    )
    out = tmp_path / "run"
    write_fixture(out, artifacts, run_input.raw_bytes)
    return out


class TestStepFixtureHappyPath:
    """step_fixture from an empty-journal fixture matches a full plan run.

    WHY: this is the headline exit criterion — step mode and plan mode
    produce identical journals.
    """

    def test_step_from_zero_matches_full_plan(self, tmp_path: Path) -> None:
        # Start from a --steps 0 fixture (empty journal)
        paused = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=0)
        result = step_fixture(paused, n_events=2)
        assert isinstance(result, StepResult)
        assert result.steps_applied == 2
        assert result.steps_remaining == 0
        assert result.done is True
        # Compare against a full plan
        full_dir = tmp_path / "full"
        full_input = prepare_run_input(FIXTURE_DIR / "identity-move-rename.yaml")
        full_report = run_validation(full_input)
        full = run_plan(run_input=full_input, validation_report=full_report)
        assert result.new_entries == full.journal

    def test_step_on_completed_fixture_returns_done(self, tmp_path: Path) -> None:
        full = _make_fixture(tmp_path, "identity-move-rename.yaml")
        result = step_fixture(full, n_events=5)
        assert result.steps_applied == 0
        assert result.steps_remaining == 0
        assert result.done is True
        assert result.new_entries == ()

    def test_slow_copy_pair_counts_as_one_step(self, tmp_path: Path) -> None:
        # slow_copy_start + slow_copy_commit is ONE step unit; --next 1
        # advances both halves together (Codex round 3 finding 1).
        paused = _make_fixture(tmp_path, "slow-copy.yaml", steps_limit=0)
        result = step_fixture(paused, n_events=1)
        assert result.steps_applied == 1            # step units
        assert len(result.new_entries) == 2         # raw entries
        assert result.new_entries[0].phase.value == "started"
        assert result.new_entries[1].phase.value == "committed"


class TestStepFixtureSentinelChecks:
    """step_fixture refuses to operate without a valid sentinel.

    WHY: prevents accidentally treating a non-chaos-librarian directory
    as a fixture (re-use of a sentinel'd directory was deferred from
    Sprint 3; Sprint 4 owns it).
    """

    def test_missing_sentinel_raises(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=0)
        (fixture / ".chaos-librarian-run").unlink()
        with pytest.raises(SentinelInvalidError):
            step_fixture(fixture, n_events=1)

    def test_malformed_sentinel_raises(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=0)
        (fixture / ".chaos-librarian-run").write_text("not json")
        with pytest.raises(SentinelInvalidError):
            step_fixture(fixture, n_events=1)


class TestStepFixtureScenarioTampering:
    """Hand-editing scenario.yaml after fixture creation trips the integrity check.

    WHY: prevents step-mode replays from drifting from the bundle's
    recorded identity.
    """

    def test_modified_scenario_raises(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=0)
        scenario_path = fixture / "scenario.yaml"
        scenario_path.write_text(scenario_path.read_text() + "\n# hand-edited\n")
        with pytest.raises(ScenarioTamperedError):
            step_fixture(fixture, n_events=1)


class TestStepFixtureJournalCorruption:
    """Cursor recovery rejects any mismatch between disk and regenerated journal.

    WHY: the second Codex finding — trusting len(existing_journal) lets
    hand-edited or duplicated journal lines slip through.
    """

    def test_corrupt_json_line(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=1)
        journal = fixture / "journal.jsonl"
        journal.write_text("{not json\n")
        with pytest.raises(JournalCorruptError):
            step_fixture(fixture, n_events=1)

    def test_hand_edited_entry_action(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=1)
        journal = fixture / "journal.jsonl"
        line = journal.read_text().strip()
        entry = json.loads(line)
        entry["action"] = "delete_file"
        journal.write_text(json.dumps(entry) + "\n")
        with pytest.raises(JournalCorruptError):
            step_fixture(fixture, n_events=1)

    def test_duplicated_line_off_boundary(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=2)
        journal = fixture / "journal.jsonl"
        lines = journal.read_text().splitlines()
        # Duplicate the first line so the journal has three entries when only
        # two resolved events exist.
        journal.write_text(lines[0] + "\n" + lines[0] + "\n" + lines[1] + "\n")
        with pytest.raises(JournalCorruptError):
            step_fixture(fixture, n_events=1)

    def test_slow_copy_started_without_committed_off_boundary(self, tmp_path: Path) -> None:
        """A journal ending mid-pair is off-boundary.

        WHY: the slow_copy pair is one resolved event but two journal
        entries; truncating between them leaves the journal length
        equal to one even though no resolved event has completed.
        """
        # slow-copy.yaml: 1 slow_copy_start (1 entry) + 1 slow_copy_commit (1 entry).
        # Use --steps 1 to materialize just the start (an off-boundary truncation
        # would be steps_limit=1 followed by manual deletion of the commit).
        fixture = _make_fixture(tmp_path, "slow-copy.yaml", steps_limit=2)
        journal = fixture / "journal.jsonl"
        # Truncate the second resolved event's journal entry (the 'committed')
        # so the journal contains only the 'started' line.
        lines = journal.read_text().splitlines()
        journal.write_text(lines[0] + "\n")
        with pytest.raises(JournalCorruptError):
            step_fixture(fixture, n_events=1)


class TestStepFixtureFromEmpty:
    """Engine-level direct test for step_fixture on a --steps 0 fixture.

    WHY: Codex finding 2 — empty journal must be a happy-path cursor,
    not an off_boundary error. The documented initial-step workflow
    (plan --steps 0 → step --next 1) was blocked before this fix
    because _recover_cursor entered the first resolved event, called
    apply_event, then tripped the matched >= len(existing_journal)
    guard on the first regenerated entry.
    """

    def test_step_from_steps_zero_engine_level(self, tmp_path: Path) -> None:
        paused = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=0)
        result = step_fixture(paused, n_events=1)
        assert result.steps_applied == 1
        assert result.new_replay_bundle.applied_events == 1


class TestStepFixtureTwice:
    """Two consecutive step calls from a --steps 0 fixture produce a
    full-run journal byte-equal to plan.

    WHY: Codex finding 1 — the previous fold-into-run_id design broke
    here because journal entries from step 1 carried a different run_id
    than the regenerated entries during step 2's cursor recovery. With
    the fold dropped, run_id is invariant and cursor recovery succeeds.
    """

    def test_step_twice_matches_plan(self, tmp_path: Path) -> None:
        paused = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=0)
        # Step 1 — advance one event, persist via append_step
        result1 = step_fixture(paused, n_events=1)
        from chaos_librarian.engine.writer import append_step
        append_step(
            paused,
            new_entries=result1.new_entries,
            new_current_manifest=result1.new_current_manifest,
            new_report_set=result1.new_report_set,
            new_replay_bundle=result1.new_replay_bundle,
        )
        # Step 2 — must recover cursor cleanly, advance the second event
        result2 = step_fixture(paused, n_events=1)
        assert result2.steps_applied == 1
        assert result2.done is True
        # Compare combined journal against a full plan run
        full = _make_fixture(tmp_path / "full", "identity-move-rename.yaml")
        combined = list(result1.new_entries) + list(result2.new_entries)
        full_entries = tuple(
            JournalEntry.model_validate_json(line)
            for line in (full / "journal.jsonl").read_text().splitlines()
        )
        assert tuple(combined) == full_entries


class TestStepFixtureRoundThree:
    """Round-3 regressions: step-unit semantics and journal_digest recompute.

    WHY: Codex round 3 findings 1 + 2. --next N counts step units; a
    slow_copy pair advances together. step_fixture also recomputes the
    journal_digest so the persisted bundle stays internally consistent
    after every advance.
    """

    def test_step_advances_slow_copy_pair_in_one_call(self, tmp_path: Path) -> None:
        paused = _make_fixture(tmp_path, "slow-copy.yaml", steps_limit=0)
        result = step_fixture(paused, n_events=1)
        assert result.steps_applied == 1            # step units
        assert len(result.new_entries) == 2         # raw entries (start + commit)
        assert result.new_replay_bundle.applied_events == 2

    def test_step_recomputes_journal_digest(self, tmp_path: Path) -> None:
        import hashlib
        paused = _make_fixture(tmp_path, "identity-move-rename.yaml", steps_limit=0)
        result = step_fixture(paused, n_events=1)
        expected = hashlib.sha256(
            b"".join(
                entry.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8") + b"\n"
                for entry in result.new_entries
            )
        ).hexdigest()
        assert result.new_replay_bundle.journal_digest == expected
```

(The `full` comparison uses `JournalEntry.model_validate_json` directly on the on-disk lines. If `JournalEntry` isn't already imported at the top of `test_step.py`, add `from chaos_librarian.contract.journal import JournalEntry`.)

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/engine/test_step.py -v`
Expected: ImportError — `chaos_librarian.engine.step` does not exist.

- [ ] **Step 3: Implement `step_fixture` and the three errors**

Create `src/chaos_librarian/engine/step.py`:

```python
"""Step-mode advance: re-derive cursor state, apply N more events.

``step_fixture`` reads an existing plan-only fixture, verifies it has a
parseable sentinel and matching ``run_id``, recovers world state by
replaying ``resolve_timeline(scenario)`` against the on-disk journal
(verifying every regenerated entry against its counterpart), and then
applies up to ``n_events`` more resolved events. The function does
NOT write — the CLI layer calls ``append_step`` to persist the result.

The recovery loop is the second Codex finding's fix: trusting only
``len(existing_journal)`` would let a hand-edited or duplicated journal
line slip through, poisoning subsequent reports built from
``full_journal``. Per-entry Pydantic equality catches every semantic
difference; an off-boundary length (e.g. truncated slow_copy pair) is
also rejected with a structured error.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.replay_bundle import (
    PlanOnlyReplayBundle,
    compute_plan_only_run_id,
)
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.scenario import Scenario
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.reports import ReportSet, build_report_set
from chaos_librarian.engine.resolution import resolve_timeline, step_boundaries
from chaos_librarian.engine.state import WorldState, build_initial_state
from chaos_librarian.errors import ChaosLibrarianError
from chaos_librarian.validation import prepare_run_input_from_bytes

_JOURNAL_ADAPTER: TypeAdapter[JournalEntry] = TypeAdapter(JournalEntry)


class SentinelInvalidError(ChaosLibrarianError):
    """Raised when a run-directory sentinel is missing, unparseable, or stale."""


class ScenarioTamperedError(ChaosLibrarianError):
    """Raised when the on-disk scenario no longer matches bundle.run_id."""

    def __init__(self, *, recorded: str, recomputed: str) -> None:
        super().__init__(
            f"scenario.yaml mutated: recorded run_id {recorded} != recomputed {recomputed}"
        )
        self.recorded = recorded
        self.recomputed = recomputed


class JournalCorruptError(ChaosLibrarianError):
    """Raised when the on-disk journal disagrees with the regenerated prefix.

    Three sub-cases:
    - ``parse``: a journal line fails ``JournalEntry.model_validate_json``.
    - ``entry_mismatch``: a regenerated entry disagrees with the on-disk
      entry (any field).
    - ``off_boundary``: the on-disk journal length doesn't land on a
      step-unit boundary (computed via ``step_boundaries``); a journal
      ending with a slow_copy ``started`` without its ``committed`` is
      the canonical trigger.
    """

    def __init__(self, *, kind: str, line: int | None = None, detail: str = "") -> None:
        super().__init__(f"journal corrupt ({kind}) at line {line}: {detail}".rstrip(": "))
        self.kind = kind
        self.line = line
        self.detail = detail


@dataclass(frozen=True)
class StepResult:
    """In-memory result of one ``step --next N`` invocation."""

    new_entries: tuple[JournalEntry, ...]
    new_current_manifest: Manifest
    new_report_set: ReportSet
    new_replay_bundle: PlanOnlyReplayBundle
    steps_applied: int
    steps_remaining: int
    done: bool


def step_fixture(run_dir: Path, *, n_events: int) -> StepResult:
    """Advance an existing plan-only fixture by up to ``n_events`` resolved events.

    Args:
        run_dir: Existing fixture directory (must carry a parseable
            ``.chaos-librarian-run`` sentinel).
        n_events: Maximum resolved events to apply this call. Must be
            ≥ 1; the CLI rejects 0 / negative via Typer's ``min=1``.

    Returns:
        ``StepResult`` describing what was applied. The function never
        writes; the caller persists via ``append_step``.

    Raises:
        SentinelInvalidError: sentinel missing or unparseable.
        ScenarioTamperedError: scenario.yaml mutated since fixture creation.
        JournalCorruptError: on-disk journal disagrees with the
            regenerated prefix.
    """
    _verify_sentinel(run_dir)
    scenario_bytes = (run_dir / "scenario.yaml").read_bytes()
    bundle = PlanOnlyReplayBundle.model_validate_json((run_dir / "replay.json").read_text())
    _verify_scenario_integrity(scenario_bytes, bundle)

    existing_journal = _parse_journal(run_dir / "journal.jsonl")
    run_input = prepare_run_input_from_bytes(
        raw_bytes=scenario_bytes,
        source_label=f"step:{run_dir}",
    )
    scenario = Scenario.model_validate(run_input.raw_data)
    recorder = TraceRecorder()
    ids = IdAllocator(recorder)
    state = build_initial_state(scenario, ids)
    initial_manifest = state.to_manifest()

    resolved_timeline = resolve_timeline(scenario)
    boundaries = step_boundaries(resolved_timeline)
    cursor_index = _recover_cursor(
        state=state,
        ids=ids,
        resolved_timeline=resolved_timeline,
        existing_journal=existing_journal,
        run_id=bundle.run_id,
        scenario_id=scenario.scenario_id,
    )

    # Translate n_events (step units) → raw event count via boundaries.
    if cursor_index == 0:
        step_at_cursor = 0
    else:
        step_at_cursor = boundaries.index(cursor_index) + 1
    target_step = min(step_at_cursor + n_events, len(boundaries))
    target_raw = boundaries[target_step - 1] if target_step > 0 else 0

    new_entries_list: list[JournalEntry] = []
    for resolved in resolved_timeline[cursor_index:target_raw]:
        entries = apply_event(state, resolved, ids, bundle.run_id, scenario.scenario_id)
        new_entries_list.extend(entries)

    final_cursor = target_raw
    steps_applied = target_step - step_at_cursor
    steps_remaining = len(boundaries) - target_step
    full_journal = existing_journal + new_entries_list
    current_manifest = state.to_manifest()

    report_set = build_report_set(
        initial=initial_manifest,
        current=current_manifest,
        journal=full_journal,
    )
    new_bundle = bundle.model_copy(
        update={
            "applied_events": final_cursor,
            "journal_digest": _compute_journal_digest(full_journal),
        }
    )

    return StepResult(
        new_entries=tuple(new_entries_list),
        new_current_manifest=current_manifest,
        new_report_set=report_set,
        new_replay_bundle=new_bundle,
        steps_applied=steps_applied,
        steps_remaining=steps_remaining,
        done=steps_remaining == 0,
    )


def _compute_journal_digest(journal: list[JournalEntry]) -> str:
    journal_bytes = b"".join(
        entry.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8") + b"\n"
        for entry in journal
    )
    return hashlib.sha256(journal_bytes).hexdigest()


def _verify_sentinel(run_dir: Path) -> None:
    target = run_dir / ".chaos-librarian-run"
    if not target.exists():
        raise SentinelInvalidError(f"sentinel missing: {target}")
    try:
        RunSentinel.model_validate_json(target.read_text())
    except (ValidationError, ValueError) as exc:
        raise SentinelInvalidError(f"sentinel unparseable: {exc}") from exc


def _verify_scenario_integrity(scenario_bytes: bytes, bundle: PlanOnlyReplayBundle) -> None:
    content_hash = hashlib.sha256(scenario_bytes).hexdigest()
    recomputed = compute_plan_only_run_id(
        content_hash,
        bundle.resolved_seed,
    )
    if recomputed != bundle.run_id:
        raise ScenarioTamperedError(
            recorded=str(bundle.run_id),
            recomputed=str(recomputed),
        )


def _parse_journal(path: Path) -> list[JournalEntry]:
    if not path.exists():
        return []
    text = path.read_text()
    if not text:
        return []
    entries: list[JournalEntry] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        try:
            entries.append(_JOURNAL_ADAPTER.validate_json(line))
        except ValidationError as exc:
            raise JournalCorruptError(kind="parse", line=idx, detail=str(exc)) from exc
    return entries


def _recover_cursor(
    *,
    state: WorldState,
    ids: IdAllocator,
    resolved_timeline: list,
    existing_journal: list[JournalEntry],
    run_id,
    scenario_id: str,
) -> int:
    """Replay the timeline until the regenerated journal matches existing_journal.

    Returns the resolved-event index that produced the last on-disk entry,
    or 0 if existing_journal is empty (no apply_event calls performed).
    Raises JournalCorruptError on any mismatch or off-step-unit-boundary length.
    The boundary check uses ``step_boundaries`` so a journal truncated
    mid-slow_copy-pair (started without committed) is rejected.
    """
    if not existing_journal:
        return 0
    boundaries = step_boundaries(resolved_timeline)
    valid = {0, *boundaries}
    matched = 0
    for resolved_index, resolved in enumerate(resolved_timeline):
        regenerated = apply_event(state, resolved, ids, run_id, scenario_id)
        for entry in regenerated:
            if matched >= len(existing_journal):
                raise JournalCorruptError(
                    kind="off_boundary",
                    line=matched,
                    detail=(
                        f"regenerated entry would overshoot mid-event "
                        f"(applied_events_at_cursor={resolved_index}, "
                        f"journal_length={len(existing_journal)})"
                    ),
                )
            disk_entry = existing_journal[matched]
            if entry != disk_entry:
                raise JournalCorruptError(
                    kind="entry_mismatch",
                    line=matched + 1,
                    detail=f"expected {entry!r}, found {disk_entry!r}",
                )
            matched += 1
        if matched == len(existing_journal):
            if matched not in valid:
                raise JournalCorruptError(
                    kind="off_boundary",
                    line=matched,
                    detail=(
                        f"journal length {matched} is not a step-unit boundary "
                        f"(valid: {sorted(valid)})"
                    ),
                )
            return resolved_index + 1
    raise JournalCorruptError(
        kind="off_boundary",
        line=matched,
        detail=(
            f"journal length {len(existing_journal)} did not align with any "
            f"step-unit boundary (matched {matched})"
        ),
    )


```

Note: `step_fixture` advances events inline via `resolved_timeline[cursor_index:target_raw]` because the n_events → raw count translation already happened against `step_boundaries`. No `_apply_next` helper is needed.

- [ ] **Step 4: Re-export the new surface**

Edit `src/chaos_librarian/engine/__init__.py`:

```python
"""Sprint 3 plan-only engine — public surface.

Downstream callers (CLI, tests) import from this package; the submodules
are implementation detail.
"""

from __future__ import annotations

from chaos_librarian.engine.diff import FixtureDiff, FixtureFileDiff, compare_fixtures
from chaos_librarian.engine.plan import (
    PlanArtifacts,
    ReplayIntegrityError,
    replay_plan_bundle,
    run_plan,
)
from chaos_librarian.engine.reports import ReportSet, build_report_set
from chaos_librarian.engine.step import (
    JournalCorruptError,
    ScenarioTamperedError,
    SentinelInvalidError,
    StepResult,
    step_fixture,
)

__all__ = [
    "FixtureDiff",
    "FixtureFileDiff",
    "JournalCorruptError",
    "PlanArtifacts",
    "ReplayIntegrityError",
    "ReportSet",
    "ScenarioTamperedError",
    "SentinelInvalidError",
    "StepResult",
    "build_report_set",
    "compare_fixtures",
    "replay_plan_bundle",
    "run_plan",
    "step_fixture",
]
```

(The `compare_fixtures` import will fail until Task 8 lands. If running tasks in isolation, leave that import out and re-add it in Task 8 Step 2. If running in order, Task 8 follows immediately so the import line stays.)

- [ ] **Step 5: Run the tests — they pass**

Run: `uv run pytest tests/engine/test_step.py -v`
Expected: every test passes.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: every test passes.

- [ ] **Step 7: Lint and type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean. `step.py` should land under ≤100 lines per function; if `step_fixture` itself grows past that, split a `_finalize_step_result` helper.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/engine/step.py \
        src/chaos_librarian/engine/__init__.py \
        tests/engine/test_step.py
git commit -m "feat(engine): add step_fixture with prefix-verified recovery

Cursor recovery re-derives world state by replaying the timeline from
t=0 and verifying every regenerated journal entry against the on-disk
entry. Hand-edited, duplicated, or off-boundary-truncated journals are
rejected with JournalCorruptError. Resolves the second finding of the
Codex adversarial review."
```

---

## Task 8: `engine/diff.py` — `compare_fixtures`

**Files:**

- Create: `src/chaos_librarian/engine/diff.py` — `FixtureFileDiff`, `FixtureDiff`, `compare_fixtures`.
- Modify: `src/chaos_librarian/engine/__init__.py` — re-export `FixtureDiff`, `FixtureFileDiff`, `compare_fixtures` (already added in Task 7 Step 4).
- Create: `tests/engine/test_diff.py`.

Walks two fixture directories and reports per-file divergences. Used by `replay` (Task 13) to produce exit-6 structured diffs. No third-party diff dependency; the project keeps zero new runtime deps.

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_diff.py`:

```python
"""Tests for chaos_librarian.engine.diff.compare_fixtures."""

from __future__ import annotations

from pathlib import Path

from chaos_librarian.engine.diff import FixtureDiff, compare_fixtures
from chaos_librarian.engine.plan import run_plan
from chaos_librarian.engine.writer import write_fixture
from chaos_librarian.validation import prepare_run_input, run_validation

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _make_fixture(tmp_path: Path, name: str) -> Path:
    run_input = prepare_run_input(FIXTURE_DIR / "identity-move-rename.yaml")
    report = run_validation(run_input)
    artifacts = run_plan(run_input=run_input, validation_report=report)
    out = tmp_path / name
    write_fixture(out, artifacts, run_input.raw_bytes)
    return out


class TestCompareFixtures:
    """compare_fixtures detects per-file divergences.

    WHY: replay uses this to produce structured exit-6 diffs.
    """

    def test_identical_fixtures_are_clean(self, tmp_path: Path) -> None:
        a = _make_fixture(tmp_path, "a")
        b = _make_fixture(tmp_path, "b")
        diff = compare_fixtures(a, b)
        assert isinstance(diff, FixtureDiff)
        assert diff.is_clean()

    def test_byte_diff_in_journal(self, tmp_path: Path) -> None:
        a = _make_fixture(tmp_path, "a")
        b = _make_fixture(tmp_path, "b")
        (b / "journal.jsonl").write_text((a / "journal.jsonl").read_text() + "\n# hacked\n")
        diff = compare_fixtures(a, b)
        assert not diff.is_clean()
        offenders = {f.path for f in diff.files}
        assert "journal.jsonl" in offenders
        journal_diff = next(f for f in diff.files if f.path == "journal.jsonl")
        assert journal_diff.kind == "byte_diff"

    def test_missing_in_right(self, tmp_path: Path) -> None:
        a = _make_fixture(tmp_path, "a")
        b = _make_fixture(tmp_path, "b")
        (b / "reports" / "assets" / "asset_hd_main.json").unlink()
        diff = compare_fixtures(a, b)
        kinds = {f.path: f.kind for f in diff.files}
        assert kinds["reports/assets/asset_hd_main.json"] == "missing_in_right"

    def test_missing_in_left(self, tmp_path: Path) -> None:
        a = _make_fixture(tmp_path, "a")
        b = _make_fixture(tmp_path, "b")
        (b / "extra.txt").write_text("extra")
        diff = compare_fixtures(a, b)
        kinds = {f.path: f.kind for f in diff.files}
        assert kinds["extra.txt"] == "missing_in_left"
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/engine/test_diff.py -v`
Expected: ImportError.

- [ ] **Step 3: Implement `compare_fixtures`**

Create `src/chaos_librarian/engine/diff.py`:

```python
"""Per-file fixture comparison used by ``replay`` for exit-6 diffs.

Walks both directories in lockstep (lexicographic order) and reports
divergences. Treats every file as bytes; JSON / JSONL files surface
the first differing line plus short previews. No third-party diff
dependency.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_DiffKind = Literal["byte_diff", "missing_in_left", "missing_in_right"]
_TEXT_EXTENSIONS = {".json", ".jsonl", ".yaml", ".yml", ""}
_PREVIEW_LIMIT = 200


@dataclass(frozen=True)
class FixtureFileDiff:
    path: str
    kind: _DiffKind
    left_bytes: int | None = None
    right_bytes: int | None = None
    first_diff_line: int | None = None
    preview_left: str | None = None
    preview_right: str | None = None


@dataclass(frozen=True)
class FixtureDiff:
    left_dir: Path
    right_dir: Path
    files: tuple[FixtureFileDiff, ...]

    def is_clean(self) -> bool:
        return not self.files


def compare_fixtures(left_dir: Path, right_dir: Path) -> FixtureDiff:
    """Return per-file divergences between two fixture directories."""
    left_files = _collect(left_dir)
    right_files = _collect(right_dir)
    all_keys = sorted(left_files | right_files)
    diffs: list[FixtureFileDiff] = []
    for rel in all_keys:
        left = (left_dir / rel) if rel in left_files else None
        right = (right_dir / rel) if rel in right_files else None
        if left is None:
            diffs.append(
                FixtureFileDiff(
                    path=rel,
                    kind="missing_in_left",
                    right_bytes=right.stat().st_size if right else None,
                )
            )
            continue
        if right is None:
            diffs.append(
                FixtureFileDiff(
                    path=rel,
                    kind="missing_in_right",
                    left_bytes=left.stat().st_size,
                )
            )
            continue
        left_bytes = left.read_bytes()
        right_bytes = right.read_bytes()
        if left_bytes == right_bytes:
            continue
        diffs.append(_byte_diff_for(rel, left, right, left_bytes, right_bytes))
    return FixtureDiff(left_dir=left_dir, right_dir=right_dir, files=tuple(diffs))


def _collect(root: Path) -> set[str]:
    rels: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rels.add(str(path.relative_to(root)))
    return rels


def _byte_diff_for(rel: str, left: Path, right: Path, left_bytes: bytes, right_bytes: bytes) -> FixtureFileDiff:
    suffix = Path(rel).suffix.lower()
    if suffix in _TEXT_EXTENSIONS:
        first_diff_line, preview_left, preview_right = _line_diff(left_bytes, right_bytes)
    else:
        first_diff_line, preview_left, preview_right = None, None, None
    return FixtureFileDiff(
        path=rel,
        kind="byte_diff",
        left_bytes=len(left_bytes),
        right_bytes=len(right_bytes),
        first_diff_line=first_diff_line,
        preview_left=preview_left,
        preview_right=preview_right,
    )


def _line_diff(left: bytes, right: bytes) -> tuple[int | None, str | None, str | None]:
    left_lines = left.decode("utf-8", errors="replace").splitlines()
    right_lines = right.decode("utf-8", errors="replace").splitlines()
    for idx, (l_line, r_line) in enumerate(zip(left_lines, right_lines, strict=False), start=1):
        if l_line != r_line:
            return idx, l_line[:_PREVIEW_LIMIT], r_line[:_PREVIEW_LIMIT]
    if len(left_lines) != len(right_lines):
        idx = min(len(left_lines), len(right_lines)) + 1
        l_preview = left_lines[idx - 1][:_PREVIEW_LIMIT] if idx - 1 < len(left_lines) else None
        r_preview = right_lines[idx - 1][:_PREVIEW_LIMIT] if idx - 1 < len(right_lines) else None
        return idx, l_preview, r_preview
    return None, None, None
```

- [ ] **Step 4: Run the tests — they pass**

Run: `uv run pytest tests/engine/test_diff.py -v`
Expected: every test passes.

- [ ] **Step 5: Run the full suite + lint**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/engine/diff.py \
        src/chaos_librarian/engine/__init__.py \
        tests/engine/test_diff.py
git commit -m "feat(engine): add compare_fixtures for replay divergence

Walks two fixture directories and reports per-file divergences
(byte_diff / missing_in_left / missing_in_right). For text-like files
the first differing line is surfaced with previews. No new runtime
dependency."
```

---

## Task 9: `plan --steps` CLI flag

**Files:**

- Modify: `src/chaos_librarian/cli/app.py:95-120` — `plan` gains `--steps`.
- Create: `tests/engine/test_plan_steps.py` — CLI-level tests for `--steps 0/K/missing/negative`.

The engine work is already done in Task 5; this task just plumbs the flag through Typer.

- [ ] **Step 1: Write the failing tests**

Create `tests/engine/test_plan_steps.py`:

```python
"""Tests for plan --steps flag (CLI level)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


class TestPlanSteps:
    """plan --steps caps the timeline; missing flag runs the full timeline.

    WHY: partial fixtures are the input surface for step mode and replay.
    """

    def test_steps_zero_empties_journal(self, tmp_path: Path) -> None:
        out = tmp_path / "run"
        result = runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out), "--steps", "0"],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        assert (out / "journal.jsonl").read_text() == ""
        bundle = PlanOnlyReplayBundle.model_validate_json((out / "replay.json").read_text())
        assert bundle.applied_events == 0

    def test_steps_k_partial_journal(self, tmp_path: Path) -> None:
        # identity-move-rename is atomic-only: 1 step unit = 1 raw event.
        out = tmp_path / "run"
        result = runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out), "--steps", "1"],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        bundle = PlanOnlyReplayBundle.model_validate_json((out / "replay.json").read_text())
        assert bundle.applied_events == 1
        assert sum(1 for _ in (out / "journal.jsonl").read_text().splitlines()) == 1

    def test_steps_one_on_slow_copy_applies_pair(self, tmp_path: Path) -> None:
        """--steps 1 on slow-copy.yaml advances BOTH halves of the pair.

        WHY: Codex round 3 finding 1 — one step unit covers
        slow_copy_start + slow_copy_commit; the journal must have both
        entries.
        """
        out = tmp_path / "run"
        result = runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "slow-copy.yaml"), "--out", str(out), "--steps", "1"],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        bundle = PlanOnlyReplayBundle.model_validate_json((out / "replay.json").read_text())
        assert bundle.applied_events == 2
        lines = (out / "journal.jsonl").read_text().splitlines()
        assert len(lines) == 2
        phases = [json.loads(line)["phase"] for line in lines]
        assert phases == ["started", "committed"]

    def test_steps_negative_is_usage_error(self, tmp_path: Path) -> None:
        out = tmp_path / "run"
        result = runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out), "--steps", "-1"],
        )
        assert result.exit_code == 2

    def test_steps_missing_is_full_run(self, tmp_path: Path) -> None:
        out = tmp_path / "run"
        result = runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
        bundle = PlanOnlyReplayBundle.model_validate_json((out / "replay.json").read_text())
        assert bundle.applied_events == 2
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/engine/test_plan_steps.py -v`
Expected: failures — `--steps` is not a recognized option.

- [ ] **Step 3: Add `--steps` to the `plan` command**

Edit `src/chaos_librarian/cli/app.py:95-120`. Change the signature:

```python
@app.command()
def plan(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=_validate_new_out_path)],
    steps: Annotated[int | None, typer.Option("--steps", min=0)] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Plan a scenario without creating media."""
    try:
        run_input = prepare_run_input(scenario)
    except ScenarioLoadError as exc:
        report = _synthesize_yaml_parse_report(scenario, exc)
        _emit_failure(report, json_output=json_output)
        raise typer.Exit(code=3) from exc

    report = run_validation(run_input)
    if not report.ok:
        _emit_failure(report, json_output=json_output)
        raise typer.Exit(code=3)

    artifacts = run_plan(run_input=run_input, validation_report=report, steps_limit=steps)
    write_fixture(out, artifacts, run_input.raw_bytes)

    if json_output:
        typer.echo(_plan_summary_json(artifacts, out))
    else:
        typer.echo(f"plan: wrote {out}")
```

- [ ] **Step 4: Run the tests — they pass**

Run: `uv run pytest tests/engine/test_plan_steps.py -v`
Expected: every test passes.

- [ ] **Step 5: Run the full suite + lint**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/engine/test_plan_steps.py
git commit -m "feat(cli): plan --steps N for partial fixtures

--steps 0 produces an empty-journal fixture; --steps K (K < timeline)
produces a partial fixture; omitted --steps preserves Sprint 3 full-run
behavior. Negative values exit 2 (Typer min=0)."
```

---

## Task 10: `step` CLI command

**Files:**

- Modify: `src/chaos_librarian/cli/app.py:164-171` — replace the `step` stub with a real body.
- Create: `tests/cli/test_step.py` — happy path, batching, errors, JSON output.

The engine work is already in Tasks 4 and 7. This task wires Typer to call `step_fixture` + `append_step` and map the three step-mode errors to exit codes 1 / 7.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_step.py`:

```python
"""End-to-end tests for the step CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _make_paused(tmp_path: Path) -> Path:
    out = tmp_path / "run"
    result = runner.invoke(
        app,
        ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out), "--steps", "0"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    return out


class TestStepHappyPath:
    """step --next advances the fixture and updates replay.json.

    WHY: this is the headline step-mode behavior — partial fixtures are
    rewritable.
    """

    def test_next_one(self, tmp_path: Path) -> None:
        paused = _make_paused(tmp_path)
        result = runner.invoke(app, ["step", str(paused), "--next", "1"])
        assert result.exit_code == 0, result.stdout + result.stderr
        bundle = PlanOnlyReplayBundle.model_validate_json((paused / "replay.json").read_text())
        assert bundle.applied_events == 1

    def test_batch_advance(self, tmp_path: Path) -> None:
        paused = _make_paused(tmp_path)
        result = runner.invoke(app, ["step", str(paused), "--next", "5"])
        assert result.exit_code == 0, result.stdout + result.stderr
        bundle = PlanOnlyReplayBundle.model_validate_json((paused / "replay.json").read_text())
        assert bundle.applied_events == 2  # identity-move-rename has only two events
        assert "applied 2" in result.stdout

    def test_done_on_completed(self, tmp_path: Path) -> None:
        full = tmp_path / "run"
        runner.invoke(app, ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(full)])
        result = runner.invoke(app, ["step", str(full), "--next", "1", "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["done"] is True
        assert payload["steps_applied"] == 0

    def test_json_summary(self, tmp_path: Path) -> None:
        paused = _make_paused(tmp_path)
        result = runner.invoke(app, ["step", str(paused), "--next", "1", "--json"])
        payload = json.loads(result.stdout)
        assert payload["steps_applied"] == 1
        assert payload["done"] is False
        assert "run_id" in payload


class TestStepErrors:
    """step maps engine errors to exit codes.

    WHY: agents key on the exit-code matrix in the design.
    """

    def test_negative_next(self, tmp_path: Path) -> None:
        paused = _make_paused(tmp_path)
        result = runner.invoke(app, ["step", str(paused), "--next", "-1"])
        assert result.exit_code == 2

    def test_missing_sentinel(self, tmp_path: Path) -> None:
        paused = _make_paused(tmp_path)
        (paused / ".chaos-librarian-run").unlink()
        result = runner.invoke(app, ["step", str(paused), "--next", "1"])
        assert result.exit_code == 7

    def test_tampered_scenario(self, tmp_path: Path) -> None:
        paused = _make_paused(tmp_path)
        sp = paused / "scenario.yaml"
        sp.write_text(sp.read_text() + "\n# tamper\n")
        result = runner.invoke(app, ["step", str(paused), "--next", "1"])
        assert result.exit_code == 7

    def test_corrupt_journal(self, tmp_path: Path) -> None:
        # Need a journal with entries to corrupt — use --steps 1
        out = tmp_path / "run"
        runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out), "--steps", "1"],
        )
        (out / "journal.jsonl").write_text("{not json\n")
        result = runner.invoke(app, ["step", str(out), "--next", "1"])
        assert result.exit_code == 1
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/cli/test_step.py -v`
Expected: failures — `step` is still a stub.

- [ ] **Step 3: Replace the `step` stub body**

Edit `src/chaos_librarian/cli/app.py`. Replace the stub at lines 164-171 with:

```python
@app.command()
def step(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    next_count: Annotated[int, typer.Option("--next", min=1)] = 1,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Advance a step-mode run by ``--next`` resolved events (default 1)."""
    try:
        result = step_fixture(run_dir, n_events=next_count)
    except SentinelInvalidError as exc:
        _emit_step_error("sentinel_invalid", str(exc), json_output=json_output)
        raise typer.Exit(code=7) from exc
    except ScenarioTamperedError as exc:
        _emit_step_error(
            "scenario_tampered",
            str(exc),
            json_output=json_output,
            extra={"recorded_run_id": exc.recorded, "recomputed_run_id": exc.recomputed},
        )
        raise typer.Exit(code=7) from exc
    except JournalCorruptError as exc:
        _emit_step_error(
            "journal_corrupt",
            str(exc),
            json_output=json_output,
            extra={"kind": exc.kind, "line": exc.line, "detail": exc.detail},
        )
        raise typer.Exit(code=1) from exc

    append_step(
        run_dir,
        new_entries=result.new_entries,
        new_current_manifest=result.new_current_manifest,
        new_report_set=result.new_report_set,
        new_replay_bundle=result.new_replay_bundle,
    )

    if json_output:
        typer.echo(_step_summary_json(result))
    else:
        typer.echo(f"step: applied {result.steps_applied}, remaining {result.steps_remaining}")


def _step_summary_json(result: StepResult) -> str:
    payload = {
        "run_id": str(result.new_replay_bundle.run_id),
        "steps_applied": result.steps_applied,
        "steps_remaining": result.steps_remaining,
        "applied_events": result.new_replay_bundle.applied_events,
        "done": result.done,
    }
    return json.dumps(payload, sort_keys=True)


def _emit_step_error(
    error_code: str,
    message: str,
    *,
    json_output: bool,
    extra: dict[str, object] | None = None,
) -> None:
    if json_output:
        payload: dict[str, object] = {"error": error_code, "message": message}
        if extra:
            payload.update(extra)
        typer.echo(json.dumps(payload, sort_keys=True), err=True)
    else:
        typer.echo(f"{error_code}: {message}", err=True)
```

Add the imports at the top of `app.py`:

```python
from chaos_librarian.engine import (
    JournalCorruptError,
    ScenarioTamperedError,
    SentinelInvalidError,
    StepResult,
    step_fixture,
)
from chaos_librarian.engine.writer import append_step, write_fixture
```

(Replace the existing `from chaos_librarian.engine import PlanArtifacts, run_plan` line with this consolidated import.)

- [ ] **Step 4: Run the tests — they pass**

Run: `uv run pytest tests/cli/test_step.py -v`
Expected: every test passes.

- [ ] **Step 5: Run the full suite + lint**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_step.py
git commit -m "feat(cli): real step --next [N] command body

Calls engine.step_fixture, persists via writer.append_step. Maps the
three step-mode errors to exit codes (1/7) with structured JSON
output. --next defaults to 1; --next 0 / negative exit 2 via Typer's
min=1 validator."
```

---

## Task 11: `inspect` CLI command

**Files:**

- Modify: `src/chaos_librarian/cli/app.py:184-190` — replace the `inspect` stub.
- Create: `tests/cli/test_inspect.py`.

`inspect` is read-only: verify the sentinel, read `replay.json` + `manifest.current.json` + `journal.jsonl`, emit one summary block. Steps-remaining is `len(resolve_timeline(scenario)) - bundle.applied_events`.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_inspect.py`:

```python
"""End-to-end tests for the inspect CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _make_fixture(tmp_path: Path, steps: int | None) -> Path:
    out = tmp_path / "run"
    args = ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out)]
    if steps is not None:
        args += ["--steps", str(steps)]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.stdout + result.stderr
    return out


class TestInspect:
    """inspect emits a JSON summary or a human block.

    WHY: agents pipe --json output through jq; humans want a clean block.
    """

    def test_full_fixture_json(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, steps=None)
        result = runner.invoke(app, ["inspect", str(fixture), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["scenario_id"] == "identity-move-rename"
        assert payload["execution_mode"] == "plan_only"
        assert payload["journal_entries"] == 2
        assert payload["steps_remaining"] == 0
        assert payload["counts"]["assets"] == 1

    def test_partial_fixture_steps_remaining(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, steps=1)
        result = runner.invoke(app, ["inspect", str(fixture), "--json"])
        payload = json.loads(result.stdout)
        assert payload["steps_remaining"] == 1
        assert payload["journal_entries"] == 1

    def test_missing_sentinel(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path, steps=None)
        (fixture / ".chaos-librarian-run").unlink()
        result = runner.invoke(app, ["inspect", str(fixture)])
        assert result.exit_code == 7

    def test_inspect_slow_copy_partial(self, tmp_path: Path) -> None:
        """inspect reports step-unit counts, not raw event counts.

        WHY: Codex round 3 finding 1 — --next is step-unit-counted; the
        inspect summary must use the same unit so adapters see a
        consistent story.
        """
        out = tmp_path / "run"
        runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "slow-copy.yaml"), "--out", str(out), "--steps", "0"],
        )
        result = runner.invoke(app, ["inspect", str(out), "--json"])
        payload = json.loads(result.stdout)
        assert payload["applied_steps"] == 0
        assert payload["steps_remaining"] == 1  # one step unit covers the whole pair
        assert payload["applied_events"] == 0
        assert payload["journal_entries"] == 0
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/cli/test_inspect.py -v`
Expected: failures — `inspect` stub returns 1.

- [ ] **Step 3: Replace the `inspect` stub body**

Edit `src/chaos_librarian/cli/app.py:184-190`:

```python
@app.command()
def inspect(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Inspect a run directory."""
    try:
        summary = _build_inspect_summary(run_dir)
    except SentinelInvalidError as exc:
        _emit_step_error("sentinel_invalid", str(exc), json_output=json_output)
        raise typer.Exit(code=7) from exc

    if json_output:
        typer.echo(json.dumps(summary, sort_keys=True))
    else:
        _render_inspect_human(summary)


def _build_inspect_summary(run_dir: Path) -> dict[str, object]:
    sentinel_path = run_dir / ".chaos-librarian-run"
    if not sentinel_path.exists():
        raise SentinelInvalidError(f"sentinel missing: {sentinel_path}")
    try:
        from chaos_librarian.contract.run_sentinel import RunSentinel
        RunSentinel.model_validate_json(sentinel_path.read_text())
    except Exception as exc:  # noqa: BLE001
        raise SentinelInvalidError(f"sentinel unparseable: {exc}") from exc

    from chaos_librarian.contract.manifest import Manifest
    from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle
    from chaos_librarian.contract.scenario import Scenario
    from chaos_librarian.engine.resolution import resolve_timeline

    bundle = PlanOnlyReplayBundle.model_validate_json((run_dir / "replay.json").read_text())
    manifest_current = Manifest.model_validate_json(
        (run_dir / "manifest.current.json").read_text()
    )
    journal_path = run_dir / "journal.jsonl"
    journal_entries = (
        sum(1 for line in journal_path.read_text().splitlines() if line.strip())
        if journal_path.exists()
        else 0
    )
    from chaos_librarian.engine.resolution import step_boundaries
    from chaos_librarian.validation import prepare_run_input_from_bytes

    scenario_bytes = (run_dir / "scenario.yaml").read_bytes()
    run_input = prepare_run_input_from_bytes(
        raw_bytes=scenario_bytes,
        source_label=f"inspect:{run_dir}",
    )
    scenario = Scenario.model_validate(run_input.raw_data)
    resolved_timeline = resolve_timeline(scenario)
    boundaries = step_boundaries(resolved_timeline)
    if bundle.applied_events == 0:
        applied_steps = 0
    elif bundle.applied_events in boundaries:
        applied_steps = boundaries.index(bundle.applied_events) + 1
    else:
        # Off-boundary detection here is informational; the integrity
        # error fires at replay/step time, not inspect time.
        applied_steps = 0
    steps_remaining = len(boundaries) - applied_steps
    return {
        "run_id": str(bundle.run_id),
        "scenario_id": scenario.scenario_id,
        "schema_version": bundle.schema_version,
        "execution_mode": bundle.execution_mode.value,
        "journal_entries": journal_entries,
        "applied_events": bundle.applied_events,
        "applied_steps": applied_steps,
        "steps_remaining": steps_remaining,
        "counts": {
            "works": len(manifest_current.works),
            "variants": len(manifest_current.variants),
            "bundles": len(manifest_current.bundles),
            "assets": len(manifest_current.assets),
            "sidecars": len(manifest_current.sidecars),
        },
        "created_at": None,
    }


def _render_inspect_human(summary: dict[str, object]) -> None:
    typer.echo(f"run_id:           {summary['run_id']}")
    typer.echo(f"scenario_id:      {summary['scenario_id']}")
    typer.echo(f"execution_mode:   {summary['execution_mode']}")
    typer.echo(f"journal_entries:  {summary['journal_entries']}")
    typer.echo(f"applied_events:   {summary['applied_events']}")
    typer.echo(f"applied_steps:    {summary['applied_steps']}")
    typer.echo(f"steps_remaining:  {summary['steps_remaining']}")
    counts = summary["counts"]
    typer.echo(
        f"counts:           works={counts['works']} variants={counts['variants']} "
        f"bundles={counts['bundles']} assets={counts['assets']} sidecars={counts['sidecars']}"
    )
```

- [ ] **Step 4: Run the tests — they pass**

Run: `uv run pytest tests/cli/test_inspect.py -v`
Expected: every test passes.

- [ ] **Step 5: Run the full suite + lint**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_inspect.py
git commit -m "feat(cli): real inspect command body

Reads replay.json + manifest.current + journal, emits one summary
block. steps_remaining is the resolved-event delta. Sentinel
violations exit 7."
```

---

## Task 12: `clean` CLI command

**Files:**

- Modify: `src/chaos_librarian/cli/app.py:201-207` — replace the `clean` stub.
- Create: `tests/cli/test_clean.py`.

`clean` is the simplest command: verify the sentinel, `shutil.rmtree`, emit a one-line confirmation. No `--force` flag in V1.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_clean.py`:

```python
"""End-to-end tests for the clean CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _make_fixture(tmp_path: Path) -> Path:
    out = tmp_path / "run"
    runner.invoke(app, ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(out)])
    return out


class TestClean:
    """clean removes sentinel'd directories, refuses everything else.

    WHY: V1's only protection against rm-rf-by-mistake is the sentinel.
    """

    def test_removes_sentinel_dir(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path)
        result = runner.invoke(app, ["clean", str(fixture)])
        assert result.exit_code == 0
        assert not fixture.exists()

    def test_json_output(self, tmp_path: Path) -> None:
        fixture = _make_fixture(tmp_path)
        result = runner.invoke(app, ["clean", str(fixture), "--json"])
        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert payload["removed"] == str(fixture.resolve())
        assert "run_id" in payload

    def test_missing_sentinel(self, tmp_path: Path) -> None:
        # A bare directory has no sentinel
        bare = tmp_path / "bare"
        bare.mkdir()
        (bare / "data.txt").write_text("important")
        result = runner.invoke(app, ["clean", str(bare)])
        assert result.exit_code == 7
        assert bare.exists()
        assert (bare / "data.txt").exists()

    def test_malformed_sentinel(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad"
        bad.mkdir()
        (bad / ".chaos-librarian-run").write_text("not json")
        result = runner.invoke(app, ["clean", str(bad)])
        assert result.exit_code == 7
        assert bad.exists()
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/cli/test_clean.py -v`
Expected: failures.

- [ ] **Step 3: Replace the `clean` stub body**

Edit `src/chaos_librarian/cli/app.py:201-207`:

```python
@app.command()
def clean(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Remove a run directory (sentinel-protected)."""
    sentinel_path = run_dir / ".chaos-librarian-run"
    if not sentinel_path.exists():
        _emit_step_error(
            "sentinel_invalid",
            f"sentinel missing: {sentinel_path}",
            json_output=json_output,
        )
        raise typer.Exit(code=7)
    from chaos_librarian.contract.run_sentinel import RunSentinel
    try:
        sentinel = RunSentinel.model_validate_json(sentinel_path.read_text())
    except Exception as exc:  # noqa: BLE001
        _emit_step_error(
            "sentinel_invalid",
            f"sentinel unparseable: {exc}",
            json_output=json_output,
        )
        raise typer.Exit(code=7) from exc

    resolved = run_dir.resolve()
    import shutil
    shutil.rmtree(run_dir)

    if json_output:
        typer.echo(
            json.dumps({"removed": str(resolved), "run_id": str(sentinel.run_id)}, sort_keys=True)
        )
    else:
        typer.echo(f"clean: removed {resolved} (run_id {sentinel.run_id})")
```

- [ ] **Step 4: Run the tests — they pass**

Run: `uv run pytest tests/cli/test_clean.py -v`
Expected: every test passes.

- [ ] **Step 5: Run the full suite + lint**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_clean.py
git commit -m "feat(cli): real clean command body

shutil.rmtree gated by sentinel validation; exit 7 on missing or
malformed sentinel without deleting anything."
```

---

## Task 13: `replay` CLI command

**Files:**

- Modify: `src/chaos_librarian/cli/app.py:174-181` — replace the `replay` stub with a real body that supports `--against` and auto-discover.
- Create: `tests/cli/test_replay.py`.

`replay` calls `replay_plan_bundle` (integrity check), writes a fresh fixture, optionally byte-compares against either `--against` or the bundle's parent directory, and emits exit 6 on either kind of divergence.

- [ ] **Step 1: Write the failing tests**

Create `tests/cli/test_replay.py`:

```python
"""End-to-end tests for the replay CLI command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _make_full_fixture(tmp_path: Path, name: str = "identity-move-rename.yaml") -> Path:
    out = tmp_path / "run"
    runner.invoke(app, ["plan", str(FIXTURE_DIR / name), "--out", str(out)])
    return out


class TestReplayHappyPath:
    """replay reproduces a fixture from its bundle.

    WHY: Sprint 4 headline — replay round-trips byte-identical.
    """

    def test_replay_full_fixture(self, tmp_path: Path) -> None:
        fixture = _make_full_fixture(tmp_path)
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(fixture / "replay.json"), "--out", str(out), "--against", str(fixture)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr

    def test_replay_partial_fixture(self, tmp_path: Path) -> None:
        # --steps 1 fixture
        partial = tmp_path / "partial"
        runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(partial), "--steps", "1"],
        )
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(partial / "replay.json"), "--out", str(out), "--against", str(partial)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr

    def test_replay_empty_journal_fixture(self, tmp_path: Path) -> None:
        empty = tmp_path / "empty"
        runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(empty), "--steps", "0"],
        )
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(empty / "replay.json"), "--out", str(out), "--against", str(empty)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr


class TestReplayIntegrityErrors:
    """Tampered bundles trip exit 6 with the integrity payload.

    WHY: integrity breaks must not silently produce divergent fixtures.
    """

    def test_tampered_scenario_field(self, tmp_path: Path) -> None:
        fixture = _make_full_fixture(tmp_path)
        bundle_path = fixture / "replay.json"
        payload = json.loads(bundle_path.read_text())
        payload["scenario"] = payload["scenario"] + "\n# tamper\n"
        bundle_path.write_text(json.dumps(payload))
        result = runner.invoke(app, ["replay", str(bundle_path), "--out", str(tmp_path / "out")])
        assert result.exit_code == 6

    def test_tampered_applied_events(self, tmp_path: Path) -> None:
        """Tampering applied_events trips exit 6 via journal_digest mismatch.

        WHY: two same-scenario+seed bundles share run_id, so the run_id
        check passes. Detection now falls to the digest check inside
        replay_plan_bundle: the recorded digest reflects the 1-event
        journal, but the recomputed digest after replaying 2 events
        won't match. Exit 6 even without --against.
        """
        # --steps 1 fixture, then flip applied_events to 2.
        partial = tmp_path / "partial"
        runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(partial), "--steps", "1"],
        )
        bundle_path = partial / "replay.json"
        payload = json.loads(bundle_path.read_text())
        payload["applied_events"] = 2
        bundle_path.write_text(json.dumps(payload))
        result = runner.invoke(app, ["replay", str(bundle_path), "--out", str(tmp_path / "out")])
        assert result.exit_code == 6

    def test_replay_no_against_catches_applied_events_tamper(self, tmp_path: Path) -> None:
        """A bundle copied outside its fixture, with applied_events tampered, still
        trips exit 6 via journal_digest mismatch — no --against, no sentinel'd parent.

        WHY: Codex round 3 finding 2 — the integrity story must be
        self-contained, not dependent on having a comparison target.
        """
        # Build a partial fixture
        partial = tmp_path / "partial"
        runner.invoke(
            app,
            [
                "plan",
                str(FIXTURE_DIR / "identity-move-rename.yaml"),
                "--out",
                str(partial),
                "--steps",
                "1",
            ],
        )
        # Copy ONLY the replay.json to a bare directory (no sibling sentinel)
        bare = tmp_path / "bare"
        bare.mkdir()
        bundle_copy = bare / "replay.json"
        payload = json.loads((partial / "replay.json").read_text())
        payload["applied_events"] = 2  # tamper: was 1
        bundle_copy.write_text(json.dumps(payload))
        # Replay with no --against
        out = tmp_path / "replay"
        result = runner.invoke(app, ["replay", str(bundle_copy), "--out", str(out)])
        assert result.exit_code == 6


class TestReplayArtifactDivergence:
    """If --against (or the auto-discovered original) diverges, exit 6.

    WHY: this is the second half of decision #3.
    """

    def test_against_divergent_fixture(self, tmp_path: Path) -> None:
        fixture = _make_full_fixture(tmp_path)
        # Mutate the original journal so the byte-diff fires
        journal = fixture / "journal.jsonl"
        journal.write_text(journal.read_text() + "\n# extra")
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(fixture / "replay.json"), "--out", str(out), "--against", str(fixture)],
        )
        assert result.exit_code == 6


class TestReplayOfSteppedFixture:
    """A fixture that has been advanced via step replays byte-identical against itself.

    WHY: Codex finding 1 — the previous fold-into-run_id design would have
    failed this test (the stepped fixture's replay.json.run_id would have
    encoded the new applied_events, but the journal still carried the
    original run_id). With the fold dropped, the stepped fixture is a
    valid replay source.
    """

    def test_replay_of_stepped_fixture_against_itself(self, tmp_path: Path) -> None:
        paused = tmp_path / "paused"
        runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / "identity-move-rename.yaml"), "--out", str(paused), "--steps", "0"],
        )
        step_result = runner.invoke(app, ["step", str(paused), "--next", "1"])
        assert step_result.exit_code == 0
        out = tmp_path / "replay"
        result = runner.invoke(
            app,
            ["replay", str(paused / "replay.json"), "--out", str(out), "--against", str(paused)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
```

- [ ] **Step 2: Run the failing tests**

Run: `uv run pytest tests/cli/test_replay.py -v`
Expected: failures — `replay` stub returns 1.

- [ ] **Step 3: Replace the `replay` stub body**

Edit `src/chaos_librarian/cli/app.py:174-181`:

```python
@app.command()
def replay(
    bundle: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=_validate_new_out_path)],
    against: Annotated[Path | None, typer.Option("--against", exists=True, file_okay=False)] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Replay a recorded run from its replay.json bundle."""
    parsed_bundle = PlanOnlyReplayBundle.model_validate_json(bundle.read_text())
    try:
        artifacts = replay_plan_bundle(parsed_bundle)
    except ReplayIntegrityError as exc:
        payload = {
            "error": "replay_divergence",
            "kind": "integrity",
            "recorded_run_id": str(parsed_bundle.run_id),
            "message": str(exc),
        }
        if json_output:
            typer.echo(json.dumps(payload, sort_keys=True), err=True)
        else:
            typer.echo(f"replay: integrity break — {exc}", err=True)
        raise typer.Exit(code=6) from exc

    write_fixture(out, artifacts, parsed_bundle.scenario.encode("utf-8"))

    target = against or _infer_original(bundle, parsed_bundle.run_id, parsed_bundle.applied_events)
    if target is not None:
        diff = compare_fixtures(target, out)
        if not diff.is_clean():
            payload = {
                "error": "replay_divergence",
                "kind": "artifact_diff",
                "run_id": str(parsed_bundle.run_id),
                "left_dir": str(target),
                "right_dir": str(out),
                "files": [
                    {
                        "path": f.path,
                        "kind": f.kind,
                        "left_bytes": f.left_bytes,
                        "right_bytes": f.right_bytes,
                        "first_diff_line": f.first_diff_line,
                        "preview_left": f.preview_left,
                        "preview_right": f.preview_right,
                    }
                    for f in diff.files
                ],
            }
            if json_output:
                typer.echo(json.dumps(payload, sort_keys=True), err=True)
            else:
                typer.echo(
                    f"replay: artifact divergence ({len(diff.files)} file(s))", err=True
                )
                for f in diff.files:
                    typer.echo(f"  - {f.path} [{f.kind}]", err=True)
            raise typer.Exit(code=6)

    if json_output:
        typer.echo(
            json.dumps(
                {"out": str(out.resolve()), "run_id": str(parsed_bundle.run_id),
                 "compared_against": str(target) if target else None},
                sort_keys=True,
            )
        )
    else:
        suffix = f" (matches {target})" if target else ""
        typer.echo(f"replay: wrote {out}{suffix}")


def _infer_original(bundle_path: Path, run_id, applied_events: int) -> Path | None:
    """Return bundle.parent if it contains a sentinel whose run_id matches
    AND whose replay.json.applied_events matches the bundle's applied_events.

    Two bundles of the same scenario+seed at different truncation points
    share a run_id; without the applied_events cross-check, auto-discover
    could match a different-length parent.
    """
    parent = bundle_path.parent
    sentinel_path = parent / ".chaos-librarian-run"
    if not sentinel_path.exists():
        return None
    try:
        from chaos_librarian.contract.run_sentinel import RunSentinel
        sentinel = RunSentinel.model_validate_json(sentinel_path.read_text())
    except Exception:  # noqa: BLE001
        return None
    if sentinel.run_id != run_id:
        return None
    parent_replay = parent / "replay.json"
    if not parent_replay.exists():
        return None
    try:
        parent_bundle = PlanOnlyReplayBundle.model_validate_json(parent_replay.read_text())
    except Exception:  # noqa: BLE001
        return None
    if parent_bundle.applied_events != applied_events:
        return None
    return parent
```

Add imports at the top of `app.py`:

```python
from chaos_librarian.contract.replay_bundle import PlanOnlyReplayBundle
from chaos_librarian.engine import (
    JournalCorruptError,
    ReplayIntegrityError,
    ScenarioTamperedError,
    SentinelInvalidError,
    StepResult,
    compare_fixtures,
    replay_plan_bundle,
    step_fixture,
)
```

(Consolidate with the import from Task 10; keep one block.)

- [ ] **Step 4: Run the tests — they pass**

Run: `uv run pytest tests/cli/test_replay.py -v`
Expected: every test passes.

- [ ] **Step 5: Run the full suite + lint**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_replay.py
git commit -m "feat(cli): real replay command body

Calls replay_plan_bundle; writes the fresh fixture to --out;
byte-compares against --against or the auto-discovered bundle parent.
Integrity break or artifact divergence exits 6 with a structured
payload."
```

---

## Task 14: End-to-end regression — step vs plan + replay round-trips

**Files:**

- Modify: `tests/engine/test_plan_e2e.py` — extend with step-vs-plan and partial-replay round-trip tests across all pack scenarios.

Headline exit criterion: `plan A` and `plan B --steps 0` + `step B --next K` produce byte-identical journals and reports.

- [ ] **Step 1: Add the extension tests**

Append to `tests/engine/test_plan_e2e.py`:

```python
class TestStepVsPlanByteIdentical:
    """step from t=0 produces a journal identical to plan.

    WHY: headline exit criterion. Step mode and plan mode are equivalent
    constructions of the same fixture.
    """

    @pytest.mark.parametrize("scenario_name", _PACK_SCENARIOS)
    def test_step_and_plan_journals_match(self, scenario_name: str, tmp_path: Path) -> None:
        plan_dir = tmp_path / "plan"
        step_dir = tmp_path / "step"
        assert runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / scenario_name), "--out", str(plan_dir)],
        ).exit_code == 0
        assert runner.invoke(
            app,
            ["plan", str(FIXTURE_DIR / scenario_name), "--out", str(step_dir), "--steps", "0"],
        ).exit_code == 0
        # Advance the empty fixture through every event
        for _ in range(20):  # generous cap; --next is idempotent at done
            result = runner.invoke(app, ["step", str(step_dir), "--next", "1", "--json"])
            payload = json.loads(result.stdout)
            if payload["done"]:
                break
        # Compare the two fixtures
        assert (plan_dir / "journal.jsonl").read_bytes() == (step_dir / "journal.jsonl").read_bytes()
        assert (plan_dir / "manifest.current.json").read_bytes() == (
            step_dir / "manifest.current.json"
        ).read_bytes()
        for sub in ("assets", "works", "variants", "bundles"):
            plan_files = sorted((plan_dir / "reports" / sub).iterdir())
            step_files = sorted((step_dir / "reports" / sub).iterdir())
            assert [p.name for p in plan_files] == [p.name for p in step_files]
            for pf, sf in zip(plan_files, step_files, strict=True):
                assert pf.read_bytes() == sf.read_bytes(), pf.name


class TestPartialReplayRoundTripCLI:
    """A --steps K fixture replays byte-identical via the CLI.

    WHY: partial fixtures must be first-class — decision #12 / Codex
    finding 1.
    """

    @pytest.mark.parametrize(
        "scenario_name,k",
        [
            ("identity-move-rename.yaml", 0),
            ("identity-move-rename.yaml", 1),
            ("identity-move-rename.yaml", 2),
            ("slow-copy.yaml", 0),
            ("slow-copy.yaml", 1),  # one step = entire pair
        ],
    )
    def test_partial_fixture_round_trip(
        self, scenario_name: str, k: int, tmp_path: Path
    ) -> None:
        original = tmp_path / "original"
        replay_out = tmp_path / "replay"
        plan_args = [
            "plan",
            str(FIXTURE_DIR / scenario_name),
            "--out",
            str(original),
            "--steps",
            str(k),
        ]
        assert runner.invoke(app, plan_args).exit_code == 0
        result = runner.invoke(
            app,
            [
                "replay",
                str(original / "replay.json"),
                "--out",
                str(replay_out),
                "--against",
                str(original),
            ],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
```

Add `import json` at the top of the file if missing.

- [ ] **Step 2: Run the tests — they pass**

Run: `uv run pytest tests/engine/test_plan_e2e.py -v`
Expected: every test passes.

- [ ] **Step 3: Run the full suite + lint**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: every test passes; lints clean.

- [ ] **Step 4: Confirm drift gate is still clean**

Run: `uv run python -m chaos_librarian.schema_export --check`
Expected: `All 11 schemas up-to-date.`

- [ ] **Step 5: Run pre-commit hooks**

Run: `prek run --all-files`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add tests/engine/test_plan_e2e.py
git commit -m "test(engine): cross-mode round-trip regressions

step-from-t=0 matches plan byte-for-byte across the first scenario
pack. --steps K fixtures replay byte-identical. These are the
Sprint 4 headline exit criteria."
```

---

## Task 15: CLAUDE.md update + final verification

**Files:**

- Modify: `CLAUDE.md` — update the "Project state" paragraph.

The sprint's last task is to make the new state visible to future readers (and future Claude sessions).

- [ ] **Step 1: Update the project-state paragraph**

Edit `CLAUDE.md`. Find the paragraph beginning "Sprint 0 (`feat/sprint-0`, PR #5) is **contract-only**" and replace it with:

```markdown
Sprint 0 (`feat/sprint-0`, PR #5) is **contract-only**: it freezes seven JSON Schema artifacts and a Typer CLI surface. `validate` ships in Sprint 1 (`feat/sprint-1`); `plan` ships in Sprint 3 (`feat/sprint-3`). Sprint 3 also extends Sprint 1's validation pipeline with `E_LIFECYCLE_INVALID`, which rejects shape-valid timelines that the engine cannot execute (add-on-placed, move-after-delete, double slow-copy). Sprint 4 (`feat/sprint-4`) extends `plan` with `--steps N`, ships the remaining four plan-mode commands (`step`, `inspect`, `clean`, `replay`), and adds four per-entity report schemas (`asset-report`, `work-report`, `variant-report`, `bundle-report`). `PlanOnlyReplayBundle` gains `applied_events` (raw event count, constrained to land on a step boundary) and `journal_digest` (sha256 of the serialized journal) as bundle metadata. A new `step_boundaries(resolved_timeline)` helper makes `--steps N` and `--next N` count user-visible step units (a `slow_copy_start` + `slow_copy_commit` adjacent pair = one step). `REPLAY_BUNDLE_SCHEMA_VERSION` bumps to `2` for both field-adds. The remaining three CLI commands (`materialize`, `run`, `capabilities`) are stubs that exit 1.
```

- [ ] **Step 2: Run the verification battery one more time**

Run all five gates:

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
prek run --all-files
```

Expected: each command exits 0. `pytest` reports the full Sprint 4 test surface passing (≥50 new tests on top of Sprint 3's baseline).

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(claude-md): mark Sprint 4 commands as shipped"
```

- [ ] **Step 4: Open the PR**

```bash
gh pr create --base main --head feat/sprint-4 --title "feat(sprint-4): step / inspect / clean / replay + reports + applied_events" --body "$(cat <<'EOF'
## Summary
- `plan --steps N` and four new commands (`step`, `inspect`, `clean`, `replay`); `--steps` and `--next` count user-visible step units (a slow_copy pair = one step)
- Four per-entity report schemas (asset / work / variant / bundle) emitted under `reports/`
- `applied_events` (raw event count, constrained to a step boundary) and `journal_digest` (sha256 of the serialized journal) added to `PlanOnlyReplayBundle` as metadata — neither is folded into `run_id`, but both are verified at replay time so the bundle has self-contained integrity (no `--against` required)
- New `step_boundaries(resolved_timeline)` helper is the single source of truth for step-unit semantics across `run_plan`, `step_fixture`, `replay_plan_bundle`, and `inspect`
- `step_fixture` verifies each on-disk journal entry against the regenerated prefix and rejects off-step-unit-boundary journal lengths
- `REPLAY_BUNDLE_SCHEMA_VERSION` bumps from 1 to 2 (single sprint, two field-adds) per the project-wide field-add rule

## Test plan
- [x] step-from-t=0 matches plan byte-for-byte across the first scenario pack
- [x] partial-fixture replay round-trips byte-identical
- [x] tampered scenario / applied_events / journal trip the documented exit codes
- [x] schema drift gate clean (11 schemas)
- [x] `prek run --all-files` clean

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

---

## Self-Review Notes

After this plan was written:

- **Spec coverage** — every section of the design doc has at least one task. The Codex-finding mitigations land in Tasks 1 (applied_events run_id), 7 (prefix-verified recovery), and 2 (schema-version policy via the `*_REPORT_SCHEMA_VERSION` constants). The "Open Design Decisions" surface the schema-version bump, the error-module placement, the CLI signature change, and the replay.json rewrite policy explicitly.
- **Placeholder scan** — no `TODO`, no `TBD`, no "similar to Task N" without the code repeated. The CLI bodies in Tasks 10–13 each show their full Typer function plus the imports they need.
- **Type consistency** — `step_fixture` returns `StepResult` everywhere; `compute_plan_only_run_id` is 2-arg in every Task that calls it (`applied_events` is bundle metadata, not a hash input); `applied_events` is `int` (with `Field(ge=0)`) in every reference. The `engine/__init__.py` re-exports listed in Task 7 Step 4 are referenced by every CLI body that imports from `chaos_librarian.engine`.
- **Loose ends to watch during execution** — the `step_fixture` skeleton in Task 7 Step 3 uses a tuple-return helper (`_apply_next`) where a single int counter would be tighter; if you find it noisy, refactor into `_apply_next(...) -> tuple[list[JournalEntry], int]` (entries + resolved-event count) rather than tuple-of-lists.
