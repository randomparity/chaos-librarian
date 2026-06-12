# Run Visualizer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a post-hoc exporter that turns one chaos-librarian run directory into a single self-contained HTML file for scrubbing the synthetic library's state forwards/backwards through the run's timeline, with a per-file detail drawer (layout @ step + full change timeline).

**Architecture:** The testable logic lives in a new `chaos_librarian.visualize` package (so it is linted by ruff, type-checked by `ty`, and counted by the `--cov=chaos_librarian` gate). It re-runs the scenario through the same engine path as `plan`/`replay` (`build_initial_state` → `apply_event` → `to_manifest`), snapshotting the manifest after every journal entry, cross-checks the on-disk journal positionally, and emits a JSON payload embedded in an HTML template. `scripts/visualize_run.py` is a thin argparse entry point; the viewer (`scripts/visualize_template.html`) is render-only vanilla JS with zero event semantics.

**Tech Stack:** Python 3.13, `uv`, `pytest`, `ruff`, `ty`; Pydantic v2 contract models (reused, not modified); vanilla HTML/CSS/JS for the viewer (no dependencies, must open from `file://`).

**Spec:** `docs/superpowers/specs/2026-06-11-run-visualizer-design.md`

**Deviation from spec, recorded:** The spec names `scripts/visualize_run.py` + `scripts/visualize_template.html` and a single `tests/scripts/test_visualize_run.py`. This plan keeps those two deliverables but moves the *logic* into `src/chaos_librarian/visualize/` (the script becomes a thin shim) and splits tests into `tests/visualize/` (unit, mirroring `src/` per the AGENTS.md convention) plus `tests/scripts/test_visualize_run_script.py` (invocation smoke). Rationale: a bare `scripts/*.py` is outside the type-check/coverage surface; the package placement adds **no** Typer command, so the frozen CLI contract is untouched — the spec's "no CLI-contract commitment" decision still holds.

**Conventions to honor (from AGENTS.md / CLAUDE.md):**
- Absolute imports only (`from chaos_librarian.visualize.x import y`), never relative.
- `model_config = ConfigDict(extra="forbid")` is already on every contract model; the visualizer does not add contract models (no schema bump, no `schemas/` regen).
- Enums: `enum.StrEnum`. Negative tests: build a `dict` and call `Model.model_validate(payload)`.
- ≤100 lines/function, complexity ≤8, ≤100-char lines, Google-style docstrings on public APIs.
- Run on the existing branch `feat/library-visualization` (already checked out). Do not work on `main`.

**Per-task guardrails (run before every commit):**
```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check src tests
uv run pytest tests/visualize tests/scripts -q
```

---

## File Structure

**Create (package logic):**
- `src/chaos_librarian/visualize/__init__.py` — public surface: `build_payload`, `render_html`, error types.
- `src/chaos_librarian/visualize/errors.py` — `MissingArtifactError`, `JournalDivergenceError`, `JournalCorruptLineError` (subclasses of `ChaosLibrarianError`).
- `src/chaos_librarian/visualize/replay.py` — `replay_with_snapshots(run_dir)` → per-entry snapshots + events + live/planned boundary + torn-write flag, with the positional journal cross-check.
- `src/chaos_librarian/visualize/diff.py` — `build_diffs(snapshots)` → per-step added/removed/changed entity ids + paths (locations, versions, sidecars).
- `src/chaos_librarian/visualize/payload.py` — `build_payload(run_dir)` → the JSON-serializable dict embedded into the HTML.
- `src/chaos_librarian/visualize/render.py` — `render_html(payload, template_path=None)` → HTML string with `<`→`<` escaping + size warning.

**Create (deliverables):**
- `scripts/visualize_template.html` — the viewer (HTML/CSS/JS, render-only).
- `scripts/visualize_run.py` — thin argparse CLI entry point.

**Create (tests + fixtures):**
- `tests/visualize/__init__.py`
- `tests/visualize/test_replay.py`, `test_diff.py`, `test_payload.py`, `test_render.py`
- `tests/scripts/test_visualize_run_script.py`

**Fixtures (reuse existing corpus — do not author new ones; AGENTS.md Rule 3):**
- `tests/fixtures/scenarios/active-library-churn.yaml` — `move_asset` + slow-copy pair (drives prefix, in-flight temp_path, divergence tests).
- `tests/fixtures/scenarios/tv-season-folders.yaml` — `renumber_episode` + `move_episode_to_season` (proves indirect hierarchy-driven path re-render appears in the per-file timeline — spec finding 2). `rename_season` is in no fixture; `renumber_episode` is the spec's accepted alternative and is corpus-backed.
- `tests/fixtures/scenarios/embed-extract-roundtrip.yaml` — `embed_subtitle` (track/sidecar-level change).
- All three are confirmed `status: OK` under `chaos-librarian validate`.

**Do not modify:** any `src/chaos_librarian/contract/` model, `schemas/`, or `src/chaos_librarian/cli/`.

---

## Task 1: Error types

**Files:**
- Create: `src/chaos_librarian/visualize/__init__.py` (empty for now)
- Create: `src/chaos_librarian/visualize/errors.py`
- Create: `tests/visualize/__init__.py` (empty)
- Test: `tests/visualize/test_errors.py`

- [ ] **Step 1: Create the empty package markers**

Create `src/chaos_librarian/visualize/__init__.py` with a module docstring only:

```python
"""Post-hoc run visualizer: replay a run dir into a self-contained HTML timeline."""
```

Create `tests/visualize/__init__.py` empty (zero bytes).

- [ ] **Step 2: Write the failing test**

`tests/visualize/test_errors.py`:

```python
"""Error-type contract for the visualizer."""

from __future__ import annotations

import pytest

from chaos_librarian.errors import ChaosLibrarianError
from chaos_librarian.visualize.errors import (
    JournalCorruptLineError,
    JournalDivergenceError,
    MissingArtifactError,
)


def test_missing_artifact_names_artifact_and_producer() -> None:
    err = MissingArtifactError(artifact="replay.json", produced_by="chaos-librarian plan")
    assert isinstance(err, ChaosLibrarianError)
    assert "replay.json" in str(err)
    assert "chaos-librarian plan" in str(err)


def test_divergence_cites_position_and_both_ids() -> None:
    err = JournalDivergenceError(position=4, disk_event_id="move_009", replay_event_id="move_005")
    assert isinstance(err, ChaosLibrarianError)
    assert "4" in str(err)
    assert "move_009" in str(err)
    assert "move_005" in str(err)
    assert err.position == 4


def test_corrupt_line_cites_line_number() -> None:
    err = JournalCorruptLineError(line=7, detail="expecting value")
    assert isinstance(err, ChaosLibrarianError)
    assert "7" in str(err)
    assert err.line == 7
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/visualize/test_errors.py -q`
Expected: FAIL — `ModuleNotFoundError: chaos_librarian.visualize.errors`.

- [ ] **Step 4: Write the implementation**

`src/chaos_librarian/visualize/errors.py`:

```python
"""Visualizer error types, all subclasses of ``ChaosLibrarianError`` so the
thin script entry point can catch one base and exit with an actionable message."""

from __future__ import annotations

from chaos_librarian.errors import ChaosLibrarianError


class MissingArtifactError(ChaosLibrarianError):
    """A required run-dir artifact is absent."""

    def __init__(self, *, artifact: str, produced_by: str) -> None:
        super().__init__(
            f"missing required artifact {artifact!r} — produced by `{produced_by}`"
        )
        self.artifact = artifact
        self.produced_by = produced_by


class JournalDivergenceError(ChaosLibrarianError):
    """The on-disk journal disagrees with the replayed sequence at a position."""

    def __init__(self, *, position: int, disk_event_id: str, replay_event_id: str) -> None:
        super().__init__(
            f"journal diverges at position {position}: on-disk event_id "
            f"{disk_event_id!r} != replayed event_id {replay_event_id!r}"
        )
        self.position = position
        self.disk_event_id = disk_event_id
        self.replay_event_id = replay_event_id


class JournalCorruptLineError(ChaosLibrarianError):
    """A non-final journal line failed to parse (corruption, not a torn write)."""

    def __init__(self, *, line: int, detail: str) -> None:
        super().__init__(f"journal.jsonl line {line} is unparseable: {detail}")
        self.line = line
        self.detail = detail
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/visualize/test_errors.py -q`
Expected: PASS (3 passed).

- [ ] **Step 6: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check src tests
git add src/chaos_librarian/visualize tests/visualize
git commit -m "feat(visualize): add visualizer error types"
```

---

## Task 2: Journal line parsing with torn-write handling

**Files:**
- Create: `src/chaos_librarian/visualize/replay.py`
- Test: `tests/visualize/test_replay.py`

This task implements *only* the journal-line reader (the prefix/torn/corrupt distinction). The full replay loop is Task 3.

- [ ] **Step 1: Write the failing test**

`tests/visualize/test_replay.py`:

```python
"""Replay + snapshot tests for the visualizer."""

from __future__ import annotations

import pytest

from chaos_librarian.visualize.errors import JournalCorruptLineError
from chaos_librarian.visualize.replay import ParsedJournal, parse_journal_text

_GOOD = (
    '{"schema_version":1,"event_id":"e1","scenario_id":"s","run_id":'
    '"00000000-0000-0000-0000-000000000000","logical_time_ns":1,"action":'
    '"add_file","phase":"atomic"}'
)


def test_all_lines_parse_no_torn_flag() -> None:
    result = parse_journal_text(_GOOD + "\n" + _GOOD + "\n")
    assert isinstance(result, ParsedJournal)
    assert len(result.entries) == 2
    assert result.ended_mid_write is False


def test_torn_final_line_is_dropped_with_flag() -> None:
    result = parse_journal_text(_GOOD + "\n" + '{"schema_version":1,"event')
    assert len(result.entries) == 1
    assert result.ended_mid_write is True


def test_corrupt_nonfinal_line_is_hard_error() -> None:
    with pytest.raises(JournalCorruptLineError) as exc:
        parse_journal_text('{"broken":true}\n' + _GOOD + "\n")
    assert exc.value.line == 1


def test_empty_text_is_empty_prefix() -> None:
    result = parse_journal_text("")
    assert result.entries == []
    assert result.ended_mid_write is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/visualize/test_replay.py -q`
Expected: FAIL — `ImportError` (no `parse_journal_text`).

- [ ] **Step 3: Write the implementation**

`src/chaos_librarian/visualize/replay.py` (this task adds the top of the file; Task 3 appends to it):

```python
"""Replay a run dir into per-journal-entry manifest snapshots.

The exporter re-runs the scenario through the same engine path as
``plan``/``replay`` (``build_initial_state`` → ``apply_event`` →
``to_manifest``), snapshotting after every journal entry, and cross-checks
the on-disk journal positionally on ``(event_id, action, phase)``.
"""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import TypeAdapter, ValidationError

from chaos_librarian.contract.journal import JournalEntry
from chaos_librarian.visualize.errors import JournalCorruptLineError

_JOURNAL_ADAPTER: TypeAdapter[JournalEntry] = TypeAdapter(JournalEntry)


@dataclass(frozen=True)
class ParsedJournal:
    """On-disk journal entries plus a torn-final-line marker.

    Attributes:
        entries: Successfully parsed entries, in file order.
        ended_mid_write: ``True`` when the final line was an incomplete
            (torn) write that was dropped — the expected shape of a still-
            running or crashed run.
    """

    entries: list[JournalEntry]
    ended_mid_write: bool


def parse_journal_text(text: str) -> ParsedJournal:
    """Parse journal.jsonl text, tolerating a torn final line.

    A final line that fails to parse is treated as the journal head (a torn
    write) and dropped with ``ended_mid_write=True``. Any *non-final*
    unparseable line is corruption and raises ``JournalCorruptLineError``.

    Args:
        text: Raw contents of ``journal.jsonl`` (may be empty).

    Returns:
        A :class:`ParsedJournal`.

    Raises:
        JournalCorruptLineError: a non-final line failed to parse.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    entries: list[JournalEntry] = []
    ended_mid_write = False
    for idx, line in enumerate(lines, start=1):
        try:
            entries.append(_JOURNAL_ADAPTER.validate_json(line))
        except ValidationError as exc:
            if idx == len(lines):
                ended_mid_write = True
                break
            raise JournalCorruptLineError(line=idx, detail=str(exc)) from exc
    return ParsedJournal(entries=entries, ended_mid_write=ended_mid_write)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/visualize/test_replay.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check src tests
git add src/chaos_librarian/visualize/replay.py tests/visualize/test_replay.py
git commit -m "feat(visualize): parse journal with torn-write tolerance"
```

---

## Task 3: Replay loop with per-entry snapshots and the cross-check

**Files:**
- Modify: `src/chaos_librarian/visualize/replay.py` (append)
- Modify: `tests/visualize/test_replay.py` (append)

This task reuses the existing `active-library-churn.yaml` corpus fixture (confirmed `status: OK`); no new fixture is authored.

- [ ] **Step 1: Write the failing test (append to `tests/visualize/test_replay.py`)**

Add imports at the top of the file:

```python
from pathlib import Path

from chaos_librarian.visualize.errors import JournalDivergenceError
from chaos_librarian.visualize.replay import ReplayResult, replay_with_snapshots
```

Add a fixture-builder helper and tests. Build a real run dir with the CLI so the test exercises the actual `plan`/`step` artifacts:

```python
_FIXTURE = "tests/fixtures/scenarios/active-library-churn.yaml"


def _plan_run_dir(tmp_path: Path, *, steps: int | None = None) -> Path:
    import subprocess

    out = tmp_path / "run"
    cmd = ["uv", "run", "chaos-librarian", "plan", _FIXTURE, "--out", str(out)]
    if steps is not None:
        cmd += ["--steps", str(steps)]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def test_snapshot_count_is_event_count_plus_one(tmp_path: Path) -> None:
    run_dir = _plan_run_dir(tmp_path)
    result = replay_with_snapshots(run_dir)
    assert isinstance(result, ReplayResult)
    assert len(result.snapshots) == len(result.events) + 1
    assert result.live_count == len(result.events)
    assert result.ended_mid_write is False


def test_initial_snapshot_is_seeded_state(tmp_path: Path) -> None:
    run_dir = _plan_run_dir(tmp_path)
    result = replay_with_snapshots(run_dir)
    # snapshot[0] is the seeded library before any event.
    assert "locations" in result.snapshots[0]


def test_prefix_run_marks_planned_tail(tmp_path: Path) -> None:
    full = replay_with_snapshots(_plan_run_dir(tmp_path / "a"))
    partial = replay_with_snapshots(_plan_run_dir(tmp_path / "b", steps=1))
    # Same scenario: the partial run replays the full timeline for snapshots
    # but marks only the executed prefix as live.
    assert partial.total_events == full.total_events
    assert partial.live_count < full.total_events


def test_divergent_journal_is_hard_error(tmp_path: Path) -> None:
    import json

    run_dir = _plan_run_dir(tmp_path)
    journal = run_dir / "journal.jsonl"
    lines = journal.read_text().splitlines()
    # Rewrite the first entry's event_id via a JSON round-trip so the line
    # stays valid JSON but diverges from the replayed event_id.
    first = json.loads(lines[0])
    first["event_id"] = "TAMPERED"
    lines[0] = json.dumps(first)
    journal.write_text("\n".join(lines) + "\n")
    with pytest.raises(JournalDivergenceError) as exc:
        replay_with_snapshots(run_dir)
    assert exc.value.disk_event_id == "TAMPERED"
    assert exc.value.position == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/visualize/test_replay.py -q`
Expected: FAIL — `ImportError` (no `replay_with_snapshots` / `ReplayResult`).

- [ ] **Step 3: Write the implementation (append to `src/chaos_librarian/visualize/replay.py`)**

Add imports to the existing import block:

```python
from pathlib import Path

from chaos_librarian.contract.replay_bundle import ReplayBundle
from chaos_librarian.determinism import IdAllocator, TraceRecorder
from chaos_librarian.engine.context import EngineEventContext
from chaos_librarian.engine.events import apply_event
from chaos_librarian.engine.resolution import resolve_timeline
from chaos_librarian.engine.state import build_initial_state
from chaos_librarian.validation import prepare_replay_input_from_bytes
from chaos_librarian.visualize.errors import JournalDivergenceError, MissingArtifactError

_REPLAY_BUNDLE_ADAPTER: TypeAdapter[ReplayBundle] = TypeAdapter(ReplayBundle)
```

Append the result type and the loop:

```python
@dataclass(frozen=True)
class ReplayResult:
    """Per-entry snapshots plus live/planned boundary metadata.

    Attributes:
        snapshots: ``model_dump(mode="json")`` of the manifest after each
            journal entry; ``snapshots[0]`` is the seeded initial state, so
            ``len(snapshots) == total_events + 1``.
        events: Every replayed journal entry (live + planned), in order.
        live_count: Number of entries actually present on disk (the prefix
            that was executed). Entries at indices ``>= live_count`` are
            planned-but-not-executed.
        total_events: ``len(events)`` — the full resolved timeline.
        ended_mid_write: The on-disk journal's final line was a torn write.
        scenario_id / run_id / execution_mode: header metadata.
    """

    snapshots: list[dict[str, object]]
    events: list[JournalEntry]
    live_count: int
    total_events: int
    ended_mid_write: bool
    scenario_id: str
    run_id: str
    execution_mode: str


def _require(run_dir: Path, name: str, produced_by: str) -> Path:
    target = run_dir / name
    if not target.exists():
        raise MissingArtifactError(artifact=name, produced_by=produced_by)
    return target


def _cross_check(disk: list[JournalEntry], replayed: list[JournalEntry]) -> None:
    """Compare on-disk prefix against the replayed sequence on (id, action, phase)."""
    if len(disk) > len(replayed):
        extra = disk[len(replayed)]
        raise JournalDivergenceError(
            position=len(replayed),
            disk_event_id=extra.event_id,
            replay_event_id="<past end of timeline>",
        )
    for pos, disk_entry in enumerate(disk):
        replay_entry = replayed[pos]
        if (disk_entry.event_id, disk_entry.action, disk_entry.phase) != (
            replay_entry.event_id,
            replay_entry.action,
            replay_entry.phase,
        ):
            raise JournalDivergenceError(
                position=pos,
                disk_event_id=disk_entry.event_id,
                replay_event_id=replay_entry.event_id,
            )


def replay_with_snapshots(run_dir: Path) -> ReplayResult:
    """Replay ``run_dir`` into per-entry manifest snapshots.

    Reads ``replay.json`` (either execution mode) for the verbatim scenario
    and resolved seed, re-runs the full resolved timeline, and snapshots the
    manifest after each journal entry. The on-disk ``journal.jsonl`` defines
    the live prefix and is cross-checked positionally.

    Args:
        run_dir: A scenario run directory.

    Returns:
        A :class:`ReplayResult`.

    Raises:
        MissingArtifactError: a required artifact is absent.
        JournalCorruptLineError: a non-final journal line is unparseable.
        JournalDivergenceError: the on-disk journal disagrees with replay.
    """
    bundle_path = _require(run_dir, "replay.json", "chaos-librarian plan")
    _require(run_dir, "scenario.yaml", "chaos-librarian plan")
    journal_path = _require(run_dir, "journal.jsonl", "chaos-librarian plan")

    bundle = _REPLAY_BUNDLE_ADAPTER.validate_json(bundle_path.read_bytes())
    prepared = prepare_replay_input_from_bytes(
        scenario_bytes=bundle.scenario.encode("utf-8"),
        source_label=f"visualize:{bundle.run_id}",
    )
    scenario = prepared.run_input.scenario

    recorder = TraceRecorder()
    ids = IdAllocator(recorder)
    state = build_initial_state(scenario, ids)
    ctx = EngineEventContext(
        run_id=bundle.run_id,
        scenario_id=scenario.scenario_id,
        resolved_seed=bundle.resolved_seed,
    )

    snapshots: list[dict[str, object]] = [state.to_manifest().model_dump(mode="json")]
    events: list[JournalEntry] = []
    for resolved in resolve_timeline(scenario):
        for entry in apply_event(state, resolved, ids, ctx):
            events.append(entry)
            snapshots.append(state.to_manifest().model_dump(mode="json"))

    parsed = parse_journal_text(journal_path.read_text())
    _cross_check(parsed.entries, events)

    return ReplayResult(
        snapshots=snapshots,
        events=events,
        live_count=len(parsed.entries),
        total_events=len(events),
        ended_mid_write=parsed.ended_mid_write,
        scenario_id=scenario.scenario_id,
        run_id=str(bundle.run_id),
        execution_mode=bundle.execution_mode.value,
    )
```

> Snapshot-per-entry note: snapshotting *inside* the inner loop means a resolved event that emits N entries yields N identical post-state snapshots (each entry observes the same committed state). This keeps `len(snapshots) == total_events + 1` exact regardless of multi-entry events.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/visualize/test_replay.py -q`
Expected: PASS. If `test_prefix_run_marks_planned_tail` fails because `--steps 1` lands mid-slow-copy, set `steps` to a value that lands on a step boundary before the slow-copy pair (inspect `active-library-churn.yaml`'s timeline order).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check src tests
git add src/chaos_librarian/visualize/replay.py tests/visualize/test_replay.py
git commit -m "feat(visualize): replay run dir into per-entry snapshots with cross-check"
```

---

## Task 4: Per-step entity diffs

**Files:**
- Create: `src/chaos_librarian/visualize/diff.py`
- Test: `tests/visualize/test_diff.py`

- [ ] **Step 1: Write the failing test**

`tests/visualize/test_diff.py`:

```python
"""Per-step entity-diff tests."""

from __future__ import annotations

from chaos_librarian.visualize.diff import build_diffs, diff_snapshots


def _snap(locations: list[dict], versions: list[dict] | None = None) -> dict:
    return {"locations": locations, "versions": versions or [], "sidecars": []}


def test_added_and_removed_location_ids() -> None:
    prev = _snap([{"id": "loc1", "asset_id": "a1", "path": "x.mkv"}])
    curr = _snap([{"id": "loc2", "asset_id": "a2", "path": "y.mkv"}])
    d = diff_snapshots(prev, curr)
    assert d["locations"]["added"] == ["loc2"]
    assert d["locations"]["removed"] == ["loc1"]


def test_changed_location_reports_path_field() -> None:
    prev = _snap([{"id": "loc1", "asset_id": "a1", "path": "old.mkv"}])
    curr = _snap([{"id": "loc1", "asset_id": "a1", "path": "new.mkv"}])
    d = diff_snapshots(prev, curr)
    changed = d["locations"]["changed"]
    assert len(changed) == 1
    assert changed[0]["id"] == "loc1"
    assert "path" in changed[0]["fields"]
    assert changed[0]["from"]["path"] == "old.mkv"
    assert changed[0]["to"]["path"] == "new.mkv"


def test_identical_snapshots_have_no_changes() -> None:
    snap = _snap([{"id": "loc1", "asset_id": "a1", "path": "x.mkv"}])
    d = diff_snapshots(snap, snap)
    assert d["locations"] == {"added": [], "removed": [], "changed": []}


def test_build_diffs_has_one_entry_per_transition() -> None:
    snaps = [_snap([]), _snap([{"id": "l", "asset_id": "a", "path": "p"}]), _snap([])]
    diffs = build_diffs(snaps)
    assert len(diffs) == len(snaps) - 1
    assert diffs[0]["locations"]["added"] == ["l"]
    assert diffs[1]["locations"]["removed"] == ["l"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/visualize/test_diff.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Write the implementation**

`src/chaos_librarian/visualize/diff.py`:

```python
"""Per-step entity diffs between adjacent manifest snapshots.

Diffs are computed at the location / version / sidecar level. Because
``to_manifest`` re-renders every location's ``path`` from current hierarchy
state, an indirect change (e.g. ``rename_season`` re-rendering a file's path)
surfaces here as a location ``path`` change even though its journal entry
targets a hierarchy entity — this is what lets the viewer's per-file Timeline
include indirect changes (spec finding 2).
"""

from __future__ import annotations

_COLLECTIONS = ("locations", "versions", "sidecars")


def _index(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(row["id"]): row for row in rows}


def _diff_collection(
    prev_rows: list[dict[str, object]],
    curr_rows: list[dict[str, object]],
) -> dict[str, object]:
    prev, curr = _index(prev_rows), _index(curr_rows)
    added = sorted(curr.keys() - prev.keys())
    removed = sorted(prev.keys() - curr.keys())
    changed: list[dict[str, object]] = []
    for row_id in sorted(curr.keys() & prev.keys()):
        before, after = prev[row_id], curr[row_id]
        if before == after:
            continue
        fields = sorted(
            key for key in set(before) | set(after) if before.get(key) != after.get(key)
        )
        changed.append({"id": row_id, "fields": fields, "from": before, "to": after})
    return {"added": added, "removed": removed, "changed": changed}


def diff_snapshots(prev: dict[str, object], curr: dict[str, object]) -> dict[str, object]:
    """Diff two manifest snapshots at the location/version/sidecar level.

    Args:
        prev: Manifest dump before the step.
        curr: Manifest dump after the step.

    Returns:
        A dict keyed by collection name, each holding ``added``/``removed``
        (sorted id lists) and ``changed`` (id + differing fields + from/to).
    """
    result: dict[str, object] = {}
    for name in _COLLECTIONS:
        prev_rows = list(prev.get(name, []))  # type: ignore[arg-type]
        curr_rows = list(curr.get(name, []))  # type: ignore[arg-type]
        result[name] = _diff_collection(prev_rows, curr_rows)
    return result


def build_diffs(snapshots: list[dict[str, object]]) -> list[dict[str, object]]:
    """Return one diff per snapshot transition (``len(snapshots) - 1`` entries).

    Args:
        snapshots: Per-entry manifest dumps from ``replay_with_snapshots``.

    Returns:
        A list of per-step diffs; ``diffs[i]`` describes the change from
        ``snapshots[i]`` to ``snapshots[i + 1]``.
    """
    return [diff_snapshots(snapshots[i], snapshots[i + 1]) for i in range(len(snapshots) - 1)]
```

> The two `# type: ignore[arg-type]` lines guard the `list(...)` over a value typed `object`. If `ty` reports them as unused or wants a different code, replace with a narrowing helper (`def _rows(snap, name) -> list[dict]`) rather than leaving a warning — the project bans stale ignores.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/visualize/test_diff.py -q`
Expected: PASS (4 passed).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check src tests
git add src/chaos_librarian/visualize/diff.py tests/visualize/test_diff.py
git commit -m "feat(visualize): per-step entity diffs"
```

---

## Task 5: Payload assembly

**Files:**
- Create: `src/chaos_librarian/visualize/payload.py`
- Modify: `src/chaos_librarian/visualize/__init__.py`
- Test: `tests/visualize/test_payload.py`

- [ ] **Step 1: Write the failing test**

`tests/visualize/test_payload.py`:

```python
"""Payload-assembly tests, including the materialize-equivalence prerequisite."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from chaos_librarian.visualize import build_payload

_FIXTURE = "tests/fixtures/scenarios/active-library-churn.yaml"
_TV_FIXTURE = "tests/fixtures/scenarios/tv-season-folders.yaml"
_SUB_FIXTURE = "tests/fixtures/scenarios/embed-extract-roundtrip.yaml"


def _plan_fixture(tmp_path: Path, fixture: str) -> Path:
    out = tmp_path / "run"
    subprocess.run(
        ["uv", "run", "chaos-librarian", "plan", fixture, "--out", str(out)],
        check=True,
        capture_output=True,
    )
    return out


def _plan(tmp_path: Path) -> Path:
    return _plan_fixture(tmp_path, _FIXTURE)


def _changed_field_appears(payload: dict, collection: str, field: str) -> bool:
    return any(
        any(field in c["fields"] for c in diff[collection]["changed"])
        for diff in payload["diffs"]
    )


def test_payload_shape(tmp_path: Path) -> None:
    payload = build_payload(_plan(tmp_path))
    assert set(payload) >= {"meta", "snapshots", "events", "diffs", "probed_final"}
    assert len(payload["snapshots"]) == len(payload["events"]) + 1
    assert len(payload["diffs"]) == len(payload["events"])
    meta = payload["meta"]
    assert meta["scenario_id"]
    assert meta["live_count"] == len(payload["events"])
    assert meta["ended_mid_write"] is False


def test_planned_events_flagged_for_prefix_run(tmp_path: Path) -> None:
    out = tmp_path / "run"
    subprocess.run(
        ["uv", "run", "chaos-librarian", "plan", _FIXTURE, "--out", str(out), "--steps", "1"],
        check=True,
        capture_output=True,
    )
    payload = build_payload(out)
    executed = [e["executed"] for e in payload["events"]]
    assert executed[0] is True
    assert executed[-1] is False  # tail is planned-but-not-executed


def test_plan_only_has_no_probed_final(tmp_path: Path) -> None:
    payload = build_payload(_plan(tmp_path))
    assert payload["probed_final"] is None


def test_hierarchy_event_surfaces_as_location_path_change(tmp_path: Path) -> None:
    # Spec finding 2: a renumber_episode / move_episode_to_season re-renders
    # episode file paths. to_manifest() re-renders locations[].path, so the
    # indirect change MUST appear as a location "path" change in some diff —
    # this is what lets the viewer's per-file Timeline include it.
    payload = build_payload(_plan_fixture(tmp_path, _TV_FIXTURE))
    assert _changed_field_appears(payload, "locations", "path")


def test_embed_subtitle_surfaces_as_version_or_sidecar_change(tmp_path: Path) -> None:
    payload = build_payload(_plan_fixture(tmp_path, _SUB_FIXTURE))
    touched = any(
        diff["versions"]["added"] or diff["versions"]["changed"]
        or diff["sidecars"]["added"] or diff["sidecars"]["changed"]
        for diff in payload["diffs"]
    )
    assert touched


@pytest.mark.skipif(
    subprocess.run(
        ["uv", "run", "chaos-librarian", "capabilities"], capture_output=True
    ).returncode
    != 0,
    reason="media toolchain unavailable",
)
def test_materialize_run_dir_passes_cross_check(tmp_path: Path) -> None:
    # Spec prerequisite: plan-path replay must be journal-equivalent for a
    # materialize bundle. If this raises JournalDivergenceError the
    # equivalence assumption is broken and the comparison contract must be
    # renegotiated (blocking design revision, not a runtime fallback).
    out = tmp_path / "mrun"
    subprocess.run(
        ["uv", "run", "chaos-librarian", "materialize", _FIXTURE, "--out", str(out)],
        check=True,
        capture_output=True,
    )
    payload = build_payload(out)
    assert payload["probed_final"] is not None
    assert len(payload["snapshots"]) == len(payload["events"]) + 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/visualize/test_payload.py -q`
Expected: FAIL — `ImportError: cannot import name 'build_payload'`.

- [ ] **Step 3: Write the implementation**

`src/chaos_librarian/visualize/payload.py`:

```python
"""Assemble the JSON payload embedded into the visualizer HTML."""

from __future__ import annotations

from pathlib import Path

from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.visualize.diff import build_diffs
from chaos_librarian.visualize.replay import ReplayResult, replay_with_snapshots


def _probed_final(run_dir: Path, final_snapshot: dict[str, object]) -> dict[str, object] | None:
    """Map asset_id → probed media from manifest.current.json, if present.

    Probed entries whose asset_id is absent from the final replayed snapshot
    are dropped (they indicate a manifest from a different run). Returns None
    when manifest.current.json is absent or carries no probed data.
    """
    current_path = run_dir / "manifest.current.json"
    if not current_path.exists():
        return None
    current = Manifest.model_validate_json(current_path.read_text())
    final_assets = {str(a["id"]) for a in final_snapshot.get("assets", [])}  # type: ignore[union-attr]
    probed: dict[str, object] = {}
    for version in current.versions:
        if version.probed is not None and version.asset_id in final_assets:
            probed[version.asset_id] = version.probed.model_dump(mode="json")
    return probed or None


def _events_payload(result: ReplayResult) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for index, entry in enumerate(result.events):
        dumped = entry.model_dump(mode="json")
        dumped["executed"] = index < result.live_count
        out.append(dumped)
    return out


def build_payload(run_dir: Path) -> dict[str, object]:
    """Build the full visualizer payload for a run directory.

    Args:
        run_dir: A scenario run directory.

    Returns:
        A JSON-serializable dict with ``meta``, ``snapshots``, ``events``,
        ``diffs``, and ``probed_final``.

    Raises:
        MissingArtifactError, JournalCorruptLineError, JournalDivergenceError:
            propagated from the replay step.
    """
    result = replay_with_snapshots(run_dir)
    diffs = build_diffs(result.snapshots)
    warnings: list[str] = []
    if result.ended_mid_write:
        warnings.append("journal ended mid-write; final torn line dropped")
    return {
        "meta": {
            "scenario_id": result.scenario_id,
            "run_id": result.run_id,
            "execution_mode": result.execution_mode,
            "live_count": result.live_count,
            "total_events": result.total_events,
            "ended_mid_write": result.ended_mid_write,
            "warnings": warnings,
        },
        "snapshots": result.snapshots,
        "events": _events_payload(result),
        "diffs": diffs,
        "probed_final": _probed_final(run_dir, result.snapshots[-1]),
    }
```

> Resolve the two `# type: ignore` hints the same way as Task 4 if `ty` objects — narrow with a helper, do not leave a warning.

`src/chaos_librarian/visualize/__init__.py`:

```python
"""Post-hoc run visualizer: replay a run dir into a self-contained HTML timeline."""

from __future__ import annotations

from chaos_librarian.visualize.errors import (
    JournalCorruptLineError,
    JournalDivergenceError,
    MissingArtifactError,
)
from chaos_librarian.visualize.payload import build_payload

__all__ = [
    "JournalCorruptLineError",
    "JournalDivergenceError",
    "MissingArtifactError",
    "build_payload",
]
```

> `render_html` is added to `__all__` in Task 7.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/visualize/test_payload.py -q`
Expected: PASS (the materialize test SKIPS if no media toolchain). If the materialize test *fails with `JournalDivergenceError`*, STOP — the spec's plan-replay-equivalence prerequisite is violated; surface it (do not paper over). The fix is a design decision (which fields the cross-check compares per mode), not a code patch to silence the error.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check src tests
git add src/chaos_librarian/visualize/payload.py src/chaos_librarian/visualize/__init__.py tests/visualize/test_payload.py
git commit -m "feat(visualize): assemble payload with probed-final and planned-event flags"
```

---

## Task 6: HTML template (the viewer)

**Files:**
- Create: `scripts/visualize_template.html`

This is a render-only artifact (no event semantics). It is verified by the smoke test in Task 8 and manually in a browser. No TDD steps — it is a single create-file task.

- [ ] **Step 1: Create the template**

Create `scripts/visualize_template.html`. Requirements the file must satisfy (checked by Task 8's smoke test and the escaping test):
- Contains exactly one payload island: `<script type="application/json" id="cl-payload">__CL_PAYLOAD__</script>`. The token `__CL_PAYLOAD__` is replaced by the renderer.
- All payload-derived strings are inserted via `textContent` / `document.createTextNode` — **never** `innerHTML`. (Task 8 asserts no `innerHTML` appears in the file.)
- Hybrid main screen: header bar (scenario id, run id, execution mode, `step t / N`, current action + event_id); a file-tree canvas built from `snapshots[t].locations` + `sidecars`; a colored per-event scrub strip (one tick per event, planned ticks ghosted, torn-write badge at the boundary when `meta.ended_mid_write`).
- Keyboard: `←`/`→` step by one; `Home`/`End` jump to extremes; click/drag on the strip sets the playhead but cannot move past `live_count - 1`.
- File detail drawer keyed by **location id** (or sidecar id), with **Layout** and **Timeline** tabs. Layout @ step t shows path, role, container, duration, variant/bundle/work context, version index + hash, track table (codec/language/default/forced), sidecars, corruption; for a sidecar selection it shows kind/language/hash/path + owning-asset link. The probed-final section renders only when `payload.probed_final` has the asset id. Timeline tab lists every step whose diff touches the selected location, its owning asset, or that asset's versions/sidecars (this is why hierarchy-driven path changes appear); clicking a row sets the playhead.

A complete reference implementation follows. Paste it verbatim, then adjust styling to taste:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>chaos-librarian run visualizer</title>
<style>
  :root { --bg:#0f1117; --panel:#1a1d27; --line:#2a2f3d; --txt:#d8dbe6; --muted:#8b90a3;
          --add:#2fbf71; --del:#e0556e; --mod:#e0a13a; --plan:#454b5e; --play:#4f8cff; }
  * { box-sizing: border-box; }
  body { margin:0; font:13px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace;
         background:var(--bg); color:var(--txt); }
  header { padding:8px 12px; background:var(--panel); border-bottom:1px solid var(--line);
           display:flex; gap:16px; flex-wrap:wrap; align-items:center; }
  header b { color:#fff; }
  #banner { background:#3a2a12; color:#e0a13a; padding:4px 12px; display:none; }
  #main { display:flex; height:calc(100vh - 120px); }
  #canvas { flex:1; overflow:auto; padding:10px 14px; }
  #drawer { width:0; transition:width .12s; overflow:hidden; background:var(--panel);
            border-left:1px solid var(--line); }
  #drawer.open { width:42%; }
  #drawer .body { padding:10px 14px; }
  .tabs { display:flex; gap:6px; border-bottom:1px solid var(--line); padding:6px 14px 0; }
  .tab { padding:4px 10px; cursor:pointer; border:1px solid var(--line); border-bottom:none;
         border-radius:4px 4px 0 0; color:var(--muted); }
  .tab.on { color:#fff; background:var(--bg); }
  .node { cursor:pointer; padding:1px 0; white-space:pre; }
  .node:hover { background:#222633; }
  .node.sel { background:#2b3350; }
  .dir { color:var(--muted); }
  .touched-add { color:var(--add); } .touched-del { color:var(--del); }
  .touched-mod { color:var(--mod); } .ghost { color:var(--muted); font-style:italic; }
  .badge { font-size:11px; padding:0 5px; border-radius:3px; background:#333; margin-left:6px; }
  #strip { display:flex; height:34px; align-items:stretch; padding:6px 12px; gap:1px;
           background:var(--panel); border-top:1px solid var(--line); overflow-x:auto; }
  .tick { flex:1 0 4px; min-width:4px; border-radius:1px; cursor:pointer; }
  .tick.play { outline:2px solid var(--play); outline-offset:-2px; }
  .tick.planned { opacity:.35; cursor:not-allowed; }
  #scrub { padding:6px 12px; display:flex; gap:10px; align-items:center; background:var(--panel); }
  #scrub input { flex:1; }
  table { border-collapse:collapse; width:100%; margin:6px 0; }
  th,td { text-align:left; border-bottom:1px solid var(--line); padding:2px 6px; }
  .tl-row { padding:4px 6px; border-left:3px solid var(--line); cursor:pointer; margin:2px 0; }
  .tl-row.now { border-left-color:var(--play); background:#1d2436; }
  a.assetlink { color:var(--play); cursor:pointer; }
</style>
</head>
<body>
<header>
  <span>run: <b id="h-scenario"></b></span>
  <span id="h-run" class="ghost"></span>
  <span>mode: <b id="h-mode"></b></span>
  <span>step <b id="h-step"></b> / <b id="h-total"></b></span>
  <span id="h-action" class="ghost"></span>
</header>
<div id="banner"></div>
<div id="main">
  <div id="canvas"></div>
  <div id="drawer">
    <div class="tabs">
      <div class="tab on" data-tab="layout" id="tab-layout">Layout</div>
      <div class="tab" data-tab="timeline" id="tab-timeline">Timeline</div>
    </div>
    <div class="body" id="drawer-body"></div>
  </div>
</div>
<div id="strip"></div>
<div id="scrub">
  <button id="btn-start">⏮</button><button id="btn-prev">◀</button>
  <input type="range" id="range" min="0" value="0">
  <button id="btn-next">▶</button><button id="btn-end">⏭</button>
  <span id="scrub-label" class="ghost"></span>
</div>

<script type="application/json" id="cl-payload">__CL_PAYLOAD__</script>
<script>
"use strict";
const PAYLOAD = JSON.parse(document.getElementById("cl-payload").textContent);
const { meta, snapshots, events, diffs, probed_final } = PAYLOAD;
let t = 0;                 // current step index into snapshots (0..total_events)
let sel = null;            // {kind:"location"|"sidecar", id}
let tab = "layout";
const liveMax = Math.max(0, meta.live_count); // last scrubbable snapshot index

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = text; // text-only: hostile strings stay inert
  return n;
}
function rowsById(snap, key) {
  const m = new Map();
  (snap[key] || []).forEach(r => m.set(r.id, r));
  return m;
}
function eventCategory(action) {
  const A = action || "";
  if (/(reencode|remux|edit_metadata|corrupt_tags)/.test(A)) return "var(--mod)";
  if (/(move|rename|archive|move_between_roots)/.test(A)) return "var(--mod)";
  if (/(sidecar|subtitle)/.test(A)) return "var(--add)";
  if (/(slow_copy|network_lag|network_fs)/.test(A)) return "var(--play)";
  if (/(corrupt|truncate|wrong_oracle)/.test(A)) return "var(--del)";
  return "#7a8094"; // neutral fallback for unknown/new actions
}

function diffTouchesLocation(diff, locId, assetId, snap) {
  const hit = (coll, id) => coll.added.includes(id) || coll.removed.includes(id)
    || coll.changed.some(c => c.id === id);
  if (hit(diff.locations, locId)) return true;
  // owning asset's other locations (path re-renders from hierarchy events)
  for (const l of (snap.locations || [])) {
    if (l.asset_id === assetId && hit(diff.locations, l.id)) return true;
  }
  for (const v of (snap.versions || [])) {
    if (v.asset_id === assetId && hit(diff.versions, v.id)) return true;
  }
  for (const s of (snap.sidecars || [])) {
    if (s.asset_id === assetId && hit(diff.sidecars, s.id)) return true;
  }
  return false;
}

function renderHeader() {
  document.getElementById("h-scenario").textContent = meta.scenario_id;
  document.getElementById("h-run").textContent = meta.run_id;
  document.getElementById("h-mode").textContent = meta.execution_mode;
  document.getElementById("h-step").textContent = t;
  document.getElementById("h-total").textContent = meta.total_events;
  const ev = t > 0 ? events[t - 1] : null;
  document.getElementById("h-action").textContent =
    ev ? `${ev.action} (${ev.event_id})` : "initial state";
  const banner = document.getElementById("banner");
  if (meta.ended_mid_write && t >= liveMax) {
    banner.style.display = "block";
    banner.textContent = "journal ended mid-write — steps beyond here are planned, not executed";
  } else { banner.style.display = "none"; }
}

function renderStrip() {
  const strip = document.getElementById("strip");
  strip.replaceChildren();
  events.forEach((ev, i) => {
    const tick = el("div", "tick");
    tick.style.background = eventCategory(ev.action);
    if (!ev.executed) tick.classList.add("planned");
    if (i + 1 === t) tick.classList.add("play");
    tick.title = `${ev.event_id} · ${ev.action} · ${(ev.target_ids || []).join(",")}`;
    tick.onclick = () => { if (ev.executed) setStep(i + 1); };
    strip.appendChild(tick);
  });
}

function renderTree() {
  const snap = snapshots[t];
  const prevDiff = t > 0 ? diffs[t - 1] : null;
  const canvas = document.getElementById("canvas");
  canvas.replaceChildren();
  const entries = [];
  (snap.locations || []).forEach(l => entries.push({ kind: "location", id: l.id,
    path: l.temp_path || l.path, asset_id: l.asset_id, ghost: !!l.temp_path }));
  (snap.sidecars || []).forEach(s => entries.push({ kind: "sidecar", id: s.id,
    path: s.path, asset_id: s.asset_id, ghost: false }));
  entries.sort((a, b) => a.path.localeCompare(b.path));
  for (const e of entries) {
    const node = el("div", "node");
    let cls = "";
    if (prevDiff) {
      const coll = e.kind === "location" ? prevDiff.locations : prevDiff.sidecars;
      if (coll.added.includes(e.id)) cls = "touched-add";
      else if (coll.changed.some(c => c.id === e.id)) cls = "touched-mod";
    }
    if (cls) node.classList.add(cls);
    if (e.ghost) node.classList.add("ghost");
    if (sel && sel.id === e.id) node.classList.add("sel");
    node.textContent = e.path + (e.ghost ? "  (in flight)" : "");
    node.onclick = () => selectFile(e.kind, e.id);
    canvas.appendChild(node);
  }
}

function ownerAsset(snap, selObj) {
  const coll = selObj.kind === "location" ? snap.locations : snap.sidecars;
  const row = (coll || []).find(r => r.id === selObj.id);
  return row ? row.asset_id : null;
}

function renderDrawer() {
  const drawer = document.getElementById("drawer");
  const body = document.getElementById("drawer-body");
  body.replaceChildren();
  if (!sel) { drawer.classList.remove("open"); return; }
  drawer.classList.add("open");
  document.getElementById("tab-layout").classList.toggle("on", tab === "layout");
  document.getElementById("tab-timeline").classList.toggle("on", tab === "timeline");
  if (tab === "layout") renderLayoutTab(body);
  else renderTimelineTab(body);
}

function renderLayoutTab(body) {
  const snap = snapshots[t];
  const assetId = ownerAsset(snap, sel);
  if (sel.kind === "sidecar") {
    const sc = (snap.sidecars || []).find(s => s.id === sel.id);
    if (!sc) { body.appendChild(el("p", "ghost", "not present at step " + t)); return; }
    body.appendChild(el("h3", null, sc.path));
    body.appendChild(el("div", null, `kind: ${sc.kind}  lang: ${sc.language || "—"}`));
    body.appendChild(el("div", "ghost", `hash: ${sc.content_hash || "—"}`));
    const link = el("a", "assetlink", `owning asset: ${sc.asset_id}`);
    link.onclick = () => openAssetPrimary(sc.asset_id);
    body.appendChild(link);
    return;
  }
  const loc = (snap.locations || []).find(l => l.id === sel.id);
  if (!loc) { body.appendChild(el("p", "ghost", "not present at step " + t)); return; }
  body.appendChild(el("h3", null, loc.temp_path || loc.path));
  const asset = (snap.assets || []).find(a => a.id === assetId);
  if (asset) body.appendChild(el("div", null,
    `role: ${asset.role}  container: ${asset.container}  dur: ${asset.duration_seconds}s`));
  const version = (snap.versions || []).filter(v => v.asset_id === assetId).slice(-1)[0];
  if (version) {
    body.appendChild(el("div", "ghost", `v${version.index}  hash: ${version.content_hash || "—"}`));
    if (version.probed) appendStreams(body, "tracks (model)", version.probed.streams || []);
    if (version.corruption) body.appendChild(el("div", "touched-del",
      `corruption: ${JSON.stringify(version.corruption)}`));
  }
  if (probed_final && probed_final[assetId]) {
    appendStreams(body, "probed (final, ffprobe)", probed_final[assetId].streams || []);
  }
}

function appendStreams(body, label, streams) {
  body.appendChild(el("div", "ghost", label));
  const table = el("table");
  const head = el("tr");
  ["kind", "codec", "language", "default", "forced"].forEach(h => head.appendChild(el("th", null, h)));
  table.appendChild(head);
  streams.forEach(s => {
    const tr = el("tr");
    [s.kind, s.codec, s.language || "—", String(s.default ?? ""), String(s.forced ?? "")]
      .forEach(v => tr.appendChild(el("td", null, v)));
    table.appendChild(tr);
  });
  body.appendChild(table);
}

function renderTimelineTab(body) {
  const snap = snapshots[t];
  const assetId = ownerAsset(snap, sel);
  for (let i = 0; i < diffs.length; i++) {
    const useSnap = snapshots[i + 1];
    if (!diffTouchesLocation(diffs[i], sel.id, assetId, useSnap)) continue;
    const ev = events[i];
    const row = el("div", "tl-row");
    if (i + 1 === t) row.classList.add("now");
    row.textContent = `@${ev.logical_time_ns}  ${ev.action}  ${describeDelta(ev)}`;
    row.onclick = () => { if (ev.executed) setStep(i + 1); };
    body.appendChild(row);
  }
}

function describeDelta(ev) {
  const d = ev.state_delta || {};
  if (d.from_path && d.to_path) return `${d.from_path} → ${d.to_path}`;
  if (d.final_path) return d.final_path;
  return "";
}

function selectFile(kind, id) { sel = { kind, id }; tab = "layout"; render(); }
function openAssetPrimary(assetId) {
  const snap = snapshots[t];
  const loc = (snap.locations || []).find(l => l.asset_id === assetId);
  if (loc) selectFile("location", loc.id);
}
function setStep(n) { t = Math.max(0, Math.min(liveMax, n)); render(); }

function render() {
  document.getElementById("range").max = String(liveMax);
  document.getElementById("range").value = String(t);
  document.getElementById("scrub-label").textContent = `t=${t} / ${meta.total_events}`;
  renderHeader(); renderStrip(); renderTree(); renderDrawer();
}

document.getElementById("btn-start").onclick = () => setStep(0);
document.getElementById("btn-end").onclick = () => setStep(liveMax);
document.getElementById("btn-prev").onclick = () => setStep(t - 1);
document.getElementById("btn-next").onclick = () => setStep(t + 1);
document.getElementById("range").oninput = (e) => setStep(parseInt(e.target.value, 10));
document.getElementById("tab-layout").onclick = () => { tab = "layout"; renderDrawer(); };
document.getElementById("tab-timeline").onclick = () => { tab = "timeline"; renderDrawer(); };
document.addEventListener("keydown", (e) => {
  if (e.key === "ArrowLeft") setStep(t - 1);
  else if (e.key === "ArrowRight") setStep(t + 1);
  else if (e.key === "Home") setStep(0);
  else if (e.key === "End") setStep(liveMax);
});
render();
</script>
</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add scripts/visualize_template.html
git commit -m "feat(visualize): add render-only HTML viewer template"
```

---

## Task 7: HTML renderer (payload injection + escaping)

**Files:**
- Create: `src/chaos_librarian/visualize/render.py`
- Modify: `src/chaos_librarian/visualize/__init__.py`
- Test: `tests/visualize/test_render.py`

- [ ] **Step 1: Write the failing test**

`tests/visualize/test_render.py`:

```python
"""HTML renderer tests, including the hostile-string escaping contract."""

from __future__ import annotations

import json

from chaos_librarian.visualize import render_html


def test_payload_island_present_and_parses() -> None:
    payload = {"meta": {"scenario_id": "s"}, "snapshots": [], "events": [], "diffs": []}
    html = render_html(payload)
    assert '<script type="application/json" id="cl-payload">' in html
    start = html.index('id="cl-payload">') + len('id="cl-payload">')
    end = html.index("</script>", start)
    island = html[start:end]
    assert json.loads(island) == payload


def test_hostile_string_does_not_break_island() -> None:
    payload = {
        "meta": {"scenario_id": "</script><img onerror=alert(1)>"},
        "snapshots": [], "events": [], "diffs": [],
    }
    html = render_html(payload)
    # The literal sequence "</script>" must not appear inside the island —
    # only the original closing tag of the island itself.
    assert html.count("</script>") == html.count("<script") - 0  # one real closer per opener
    start = html.index('id="cl-payload">') + len('id="cl-payload">')
    end = html.index("</script>", start)
    island = html[start:end]
    assert "<" not in island  # all '<' escaped to <
    assert json.loads(island)["meta"]["scenario_id"] == "</script><img onerror=alert(1)>"


def test_token_replaced_exactly_once() -> None:
    html = render_html({"meta": {}, "snapshots": [], "events": [], "diffs": []})
    assert "__CL_PAYLOAD__" not in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/visualize/test_render.py -q`
Expected: FAIL — `ImportError: cannot import name 'render_html'`.

- [ ] **Step 3: Write the implementation**

`src/chaos_librarian/visualize/render.py`:

```python
"""Render the visualizer payload into the self-contained HTML template."""

from __future__ import annotations

import json
import logging
from pathlib import Path

_LOGGER = logging.getLogger(__name__)
_TEMPLATE = Path(__file__).resolve().parents[3] / "scripts" / "visualize_template.html"
_TOKEN = "__CL_PAYLOAD__"  # payload injection marker, not a secret
_SIZE_WARN_BYTES = 50 * 1024 * 1024


def render_html(payload: dict[str, object], template_path: Path | None = None) -> str:
    """Embed ``payload`` into the HTML template as an escaped JSON island.

    Every ``<`` in the serialized JSON is escaped to ``\\u003c`` so no
    payload string (e.g. a path or corrupt tag containing ``</script>``)
    can terminate the island. The viewer renders all payload strings via
    ``textContent``, so the data is inert markup either way; this guards the
    serialization layer.

    Args:
        payload: The dict from ``build_payload``.
        template_path: Override for the template (defaults to
            ``scripts/visualize_template.html``).

    Returns:
        Complete HTML document text.
    """
    template = (template_path or _TEMPLATE).read_text(encoding="utf-8")
    serialized = json.dumps(payload, separators=(",", ":")).replace("<", "\\u003c")
    html = template.replace(_TOKEN, serialized)
    size = len(html.encode("utf-8"))
    if size > _SIZE_WARN_BYTES:
        _LOGGER.warning(
            "visualizer payload is %.1f MB (scaling ≈ (events+1) × manifest size); "
            "consider exporting a step-limited run",
            size / (1024 * 1024),
        )
    return html
```

> The `\\u003c` in source is a 6-character escape `<` in the emitted string, which JSON parses back to `<`. Do **not** write `"<"` (that is the char `<` itself and would defeat the escape). The test `test_hostile_string_does_not_break_island` enforces this.

Update `src/chaos_librarian/visualize/__init__.py` to export `render_html`:

```python
"""Post-hoc run visualizer: replay a run dir into a self-contained HTML timeline."""

from __future__ import annotations

from chaos_librarian.visualize.errors import (
    JournalCorruptLineError,
    JournalDivergenceError,
    MissingArtifactError,
)
from chaos_librarian.visualize.payload import build_payload
from chaos_librarian.visualize.render import render_html

__all__ = [
    "JournalCorruptLineError",
    "JournalDivergenceError",
    "MissingArtifactError",
    "build_payload",
    "render_html",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/visualize/test_render.py -q`
Expected: PASS (3 passed). If `test_hostile_string_does_not_break_island`'s `</script>` count assertion is brittle, simplify it to: `assert "</script><img" not in html` and keep the `"<" not in island` check as the real guarantee.

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check src tests
git add src/chaos_librarian/visualize/render.py src/chaos_librarian/visualize/__init__.py tests/visualize/test_render.py
git commit -m "feat(visualize): render payload into HTML with script-island escaping"
```

---

## Task 8: Script entry point + invocation smoke test

**Files:**
- Create: `scripts/visualize_run.py`
- Test: `tests/scripts/test_visualize_run_script.py`

- [ ] **Step 1: Write the failing test**

`tests/scripts/test_visualize_run_script.py`:

```python
"""Invocation smoke + escaping checks for scripts/visualize_run.py."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "visualize_run.py"
TEMPLATE = Path(__file__).resolve().parents[2] / "scripts" / "visualize_template.html"
FIXTURE = "tests/fixtures/scenarios/active-library-churn.yaml"


def test_template_uses_textcontent_not_innerhtml() -> None:
    text = TEMPLATE.read_text()
    assert "innerHTML" not in text
    assert 'id="cl-payload"' in text


def _plan(tmp_path: Path) -> Path:
    out = tmp_path / "run"
    subprocess.run(
        ["uv", "run", "chaos-librarian", "plan", FIXTURE, "--out", str(out)],
        check=True, capture_output=True,
    )
    return out


def test_script_writes_default_output(tmp_path: Path) -> None:
    run_dir = _plan(tmp_path)
    result = subprocess.run(
        ["uv", "run", "python", str(SCRIPT), str(run_dir)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
    html = run_dir / "visualize.html"
    assert html.exists()
    text = html.read_text()
    assert '<script type="application/json" id="cl-payload">' in text


def test_script_honors_output_flag(tmp_path: Path) -> None:
    run_dir = _plan(tmp_path)
    out = tmp_path / "custom.html"
    subprocess.run(
        ["uv", "run", "python", str(SCRIPT), str(run_dir), "-o", str(out)],
        check=True, capture_output=True,
    )
    assert out.exists()


def test_missing_artifact_is_actionable_error(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    result = subprocess.run(
        ["uv", "run", "python", str(SCRIPT), str(empty)],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 1
    assert "replay.json" in result.stderr
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/scripts/test_visualize_run_script.py -q`
Expected: FAIL — script does not exist yet (`test_template_uses_textcontent_not_innerhtml` may pass from Task 6; the subprocess tests fail).

- [ ] **Step 3: Write the implementation**

`scripts/visualize_run.py`:

```python
#!/usr/bin/env python
"""Export a chaos-librarian run directory to a self-contained HTML timeline.

Usage:
    uv run python scripts/visualize_run.py <run-dir> [-o OUTPUT]

The logic lives in ``chaos_librarian.visualize``; this is a thin entry point.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from chaos_librarian.errors import ChaosLibrarianError
from chaos_librarian.visualize import build_payload, render_html


def main(argv: list[str] | None = None) -> int:
    """Parse args, build the payload, render HTML. Returns a process exit code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="scenario run directory")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="output HTML path (default: <run-dir>/visualize.html)",
    )
    args = parser.parse_args(argv)

    if not args.run_dir.is_dir():
        print(f"error: not a directory: {args.run_dir}", file=sys.stderr)
        return 1

    output = args.output or args.run_dir / "visualize.html"
    try:
        payload = build_payload(args.run_dir)
        html = render_html(payload)
    except ChaosLibrarianError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    output.write_text(html, encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/scripts/test_visualize_run_script.py -q`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint, type-check, commit**

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check src tests
git add scripts/visualize_run.py tests/scripts/test_visualize_run_script.py
git commit -m "feat(visualize): add thin script entry point"
```

---

## Task 9: End-to-end verification and docs pointer

**Files:**
- Modify: `README.md` (or `docs/` index) — one-line pointer to the tool.

- [ ] **Step 1: Full guardrail sweep**

```bash
uv run ruff check . && uv run ruff format --check .
uv run ty check src tests
uv run pytest tests/visualize tests/scripts tests/contract/test_sample_scenarios.py -q
```

Expected: all pass. `test_sample_scenarios.py` is included to confirm the reused corpus fixtures still parse (no fixture was added or changed, so this should be unaffected).

- [ ] **Step 2: Manual browser check (record the result)**

```bash
# Slow-copy + move (in-flight temp file, path changes):
uv run chaos-librarian plan tests/fixtures/scenarios/active-library-churn.yaml --out /tmp/cl-vis-churn
uv run python scripts/visualize_run.py /tmp/cl-vis-churn
open /tmp/cl-vis-churn/visualize.html   # macOS

# Hierarchy indirect path re-render (finding 2):
uv run chaos-librarian plan tests/fixtures/scenarios/tv-season-folders.yaml --out /tmp/cl-vis-tv
uv run python scripts/visualize_run.py /tmp/cl-vis-tv
open /tmp/cl-vis-tv/visualize.html
```

Confirm in the browser: scrubber moves the tree; the slow-copy temp file renders ghosted at the in-flight step (churn run); clicking a file opens the drawer; in the TV run, the Timeline tab of an episode file shows the `renumber_episode` / `move_episode_to_season` step in its history even though that event targets a hierarchy entity (the indirect-change requirement); planned ticks (re-run with `--steps`) are ghosted and unscrubbable. Note any gaps as follow-up issues per AGENTS.md Rule 13.

- [ ] **Step 3: Add a docs pointer**

Add one line under an appropriate heading in `README.md`:

```markdown
- **Visualize a run:** `uv run python scripts/visualize_run.py <run-dir>` writes a
  self-contained `visualize.html` for scrubbing the library through the run's timeline.
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document the run visualizer script"
```

---

## Spec coverage check

| Spec requirement | Task |
|---|---|
| Scroll forwards/backwards through timeline | 6 (strip + scrubber + keys) |
| Click file → layout @ step (container/tracks/languages/hash/variant/bundle/sidecars) | 6 (Layout tab) |
| Full per-file change timeline, one-click switch | 6 (Timeline tab, diff-derived) |
| Post-hoc, no live tailing | 1–8 (exporter model) |
| Self-contained, double-click, no server | 6–7 (embedded island, `file://`) |
| Engine replay, viewer render-only | 3, 6 |
| Journal cross-check (event_id, action, phase) | 3 (`_cross_check`) |
| Prefix (mid-run/step) vs divergence | 3 + 5 (`executed` flag) |
| Plan-replay equivalence for materialize bundles | 5 (materialize fixture test) |
| Torn-final-line vs corrupt-non-final-line | 2 |
| Input artifact list (optional manifest.current.json) | 3, 5 |
| Probed-final section + asset-id matching/drop | 5, 6 |
| Selection by location id; sidecar Tab 1 + timeline | 6 |
| JSON-island escaping + textContent rendering | 6, 7 |
| Payload size warning | 7 |
| Empty timeline → step 0 | 3, 6 (loop handles zero events) |
| Tests: snapshot count, diff correctness, hierarchy indirect, divergence, prefix, torn-line, materialize, missing-artifact, hostile-string, island parse | 2–8 |

All spec sections map to a task.
