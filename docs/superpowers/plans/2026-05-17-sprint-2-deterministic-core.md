# Sprint 2 — Deterministic Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the internal `chaos_librarian.determinism` package — RNG / ID allocator / clock / trace recorder / seeding helpers — that Sprints 3, 4, and 8 compose into actual scenario runs.

**Architecture:** Five focused submodules under `src/chaos_librarian/determinism/`, each independently testable. A `TraceRecorder` instance is constructor-injected into `RngStreams` and `IdAllocator`; no shared "session" object exists yet. The public surface re-exports nine names from `determinism/__init__.py`; downstream sprints import only from the package, never from submodules. Property tests via `hypothesis` lock down the three load-bearing determinism guarantees (stream independence, allocator order-stability, duration round-trip).

**Tech Stack:** Python 3.13, Pydantic v2 (for the existing `ExecutionTraceEntry` union), `random.Random`, `hashlib.sha256`, `secrets.randbits`, `dataclasses`, `hypothesis` (new dev dep). No new runtime dependencies.

**Source spec:** [`docs/superpowers/specs/2026-05-17-sprint-2-deterministic-core-design.md`](../specs/2026-05-17-sprint-2-deterministic-core-design.md).

**Branch:** `feat/sprint-2` (already exists, 2 commits ahead of `main`).

---

## File Structure

**To create:**

```
src/chaos_librarian/determinism/
  __init__.py        # public surface (re-exports)
  rng.py             # RngStream + RngStreams
  ids.py             # IdAllocator + IdAllocatorOverflow
  clock.py           # Clock + format_duration_human + format_duration_json
  trace.py           # TraceRecorder
  seeding.py         # resolve_seed + scenario_content_hash

tests/determinism/
  __init__.py
  test_trace.py
  test_seeding.py
  test_ids.py
  test_ids_properties.py
  test_clock.py
  test_clock_properties.py
  test_rng.py
  test_rng_properties.py
```

**To modify:**

- `pyproject.toml` — add `hypothesis` to `[dependency-groups] dev`.
- `.gitignore` — add `.hypothesis/`.
- `CLAUDE.md` — update stale "current open: #1, #2, #3, #4" line; all four issues are closed.

**Not touched (per spec):**

- `src/chaos_librarian/clock.py` (Sprint 1's parser) — stays exactly where it is; no relocation, no rename, no signature change.
- `src/chaos_librarian/contract/replay_bundle.py` — the trace-entry models live here already; we only construct them.
- `src/chaos_librarian/cli/app.py` — Sprint 2 ships no CLI changes.
- `schemas/*.schema.json` — no schema changes (drift gate must stay clean).

---

## Conventions Recap

These come from project `CLAUDE.md` and have tripped earlier sprints. They apply to every file this plan creates.

- **Absolute imports only** — never `from .trace import ...`; always `from chaos_librarian.determinism.trace import ...`. Ruff `flake8-tidy-imports` `ban-relative-imports = "all"` enforces this.
- **`from __future__ import annotations`** at the top of every new `.py` file.
- **Google-style docstrings** on non-trivial public APIs; module docstring on each new module.
- **No `Literal[CONSTANT]`** indirect forms — `ty` rejects them. (Sprint 2 has no `schema_version` fields so this rarely bites here, but the rule still applies.)
- **Tests follow Rule 9** — each test class or test docstring includes a `WHY:` line stating the business reason for the behavior. Plain "this returns the right value" is a smell.
- **Pre-commit hooks** must pass — `prek run --all-files` should be green before each commit (the existing repo has ruff/format/uv-lock hooks).

---

## Task 1: Add `hypothesis` dev dependency and ignore its cache directory

**Files:**

- Modify: `pyproject.toml`
- Modify: `.gitignore`

Adding `hypothesis` up front so Tasks 5, 7, and 9 can introduce property tests without a separate dependency commit later.

- [ ] **Step 1: Add `hypothesis` to dev dependency group**

Edit `pyproject.toml`. Find the `[dependency-groups]` block:

```toml
[dependency-groups]
dev = [
    "pytest>=8",
    "pytest-cov>=5",
    "ruff>=0.7",
    "ty",
]
```

Replace with:

```toml
[dependency-groups]
dev = [
    "hypothesis>=6.100",
    "pytest>=8",
    "pytest-cov>=5",
    "ruff>=0.7",
    "ty",
]
```

`hypothesis>=6.100` is the minimum that supports Python 3.13 cleanly; check `uv pip show hypothesis` after sync if you want to confirm the resolved version.

- [ ] **Step 2: Add `.hypothesis/` to `.gitignore`**

Edit `.gitignore`. Find the `# Tooling` block:

```text
# Tooling
.ruff_cache/
.pytest_cache/
.coverage
htmlcov/
.ty_cache/
```

Replace with:

```text
# Tooling
.ruff_cache/
.pytest_cache/
.coverage
htmlcov/
.ty_cache/
.hypothesis/
```

- [ ] **Step 3: Sync the lockfile**

Run: `uv sync`
Expected: command exits 0 and prints something like `Installed X packages` (hypothesis and its transitive deps). `uv.lock` is updated.

- [ ] **Step 4: Confirm hypothesis is importable**

Run: `uv run python -c "import hypothesis; print(hypothesis.__version__)"`
Expected: a version string like `6.100.0` (or higher), no traceback.

- [ ] **Step 5: Confirm existing test suite still passes**

Run: `uv run pytest -q`
Expected: every existing Sprint 0/1 test green; no collection errors.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock .gitignore
git commit -m "chore(deps): add hypothesis for Sprint 2 property tests"
```

---

## Task 2: Create the `determinism` package skeleton and `TraceRecorder`

**Files:**

- Create: `src/chaos_librarian/determinism/__init__.py` (empty placeholder for now — populated in Task 10)
- Create: `src/chaos_librarian/determinism/trace.py`
- Create: `tests/determinism/__init__.py` (empty)
- Create: `tests/determinism/test_trace.py`

`TraceRecorder` is the foundational dependency — `RngStreams` and `IdAllocator` will take it in their constructors, so it ships first. The recorder is the only writer to the trace; nothing else appends.

- [ ] **Step 1: Create empty package init files**

Create `src/chaos_librarian/determinism/__init__.py` with exactly this content:

```python
"""Sprint 2 deterministic primitives — public surface populated in Task 10."""
```

Create `tests/determinism/__init__.py` with exactly this content:

```python
```

(Empty file — the unit `tests/` package already exists with an `__init__.py`, but the new `tests/determinism/` subpackage needs its own marker file so pytest discovers it cleanly.)

- [ ] **Step 2: Write the failing test file**

Create `tests/determinism/test_trace.py`:

```python
"""Tests for chaos_librarian.determinism.trace.TraceRecorder."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.replay_bundle import (
    AllocTraceEntry,
    MaterializerTraceEntry,
    RngTraceEntry,
)
from chaos_librarian.determinism.trace import TraceRecorder


class TestRecorderEntryDispatch:
    """Each record_* method appends the correct discriminated-union subclass.

    WHY: downstream sprints embed these entries verbatim in a ReplayBundle;
    the wrong subclass would break the bundle's discriminator-based oneOf.
    """

    def test_record_rng_appends_rng_entry(self) -> None:
        rec = TraceRecorder()
        rec.record_rng(stream="video_source", value="0.5")
        (entry,) = rec.entries()
        assert isinstance(entry, RngTraceEntry)
        assert entry.kind == "rng"
        assert entry.stream == "video_source"
        assert entry.value == "0.5"

    def test_record_alloc_appends_alloc_entry(self) -> None:
        rec = TraceRecorder()
        rec.record_alloc(stream="version", value="version_0001")
        (entry,) = rec.entries()
        assert isinstance(entry, AllocTraceEntry)
        assert entry.kind == "alloc"
        assert entry.stream == "version"
        assert entry.value == "version_0001"

    def test_record_materializer_appends_materializer_entry(self) -> None:
        rec = TraceRecorder()
        rec.record_materializer(stream="ffmpeg", value="ok", exit_code=0)
        (entry,) = rec.entries()
        assert isinstance(entry, MaterializerTraceEntry)
        assert entry.kind == "materializer"
        assert entry.stream == "ffmpeg"
        assert entry.value == "ok"
        assert entry.exit_code == 0


class TestRecorderOrderAndLen:
    """Entries are recorded in call order; __len__ matches.

    WHY: trace fidelity is a load-bearing determinism guarantee — Sprint 4's
    replay compares traces position-by-position to detect divergence.
    """

    def test_entries_preserve_call_order(self) -> None:
        rec = TraceRecorder()
        rec.record_rng(stream="a", value="1")
        rec.record_alloc(stream="version", value="version_0001")
        rec.record_rng(stream="a", value="2")
        kinds = [e.kind for e in rec.entries()]
        assert kinds == ["rng", "alloc", "rng"]

    def test_len_matches_entry_count(self) -> None:
        rec = TraceRecorder()
        assert len(rec) == 0
        rec.record_rng(stream="a", value="1")
        assert len(rec) == 1
        rec.record_alloc(stream="version", value="version_0001")
        assert len(rec) == 2


class TestRecorderSnapshotIsImmutable:
    """entries() returns an immutable tuple snapshot, not the internal list.

    WHY: the recorder is the only writer (closed API). Returning a list
    would let third parties mutate the recorded sequence after the fact,
    contradicting the determinism guarantee.
    """

    def test_entries_returns_tuple(self) -> None:
        rec = TraceRecorder()
        rec.record_rng(stream="a", value="1")
        assert isinstance(rec.entries(), tuple)

    def test_snapshot_cannot_be_appended_to(self) -> None:
        rec = TraceRecorder()
        rec.record_rng(stream="a", value="1")
        snapshot = rec.entries()
        with pytest.raises(AttributeError):
            snapshot.append("anything")  # type: ignore[attr-defined]

    def test_snapshot_does_not_reflect_later_records(self) -> None:
        rec = TraceRecorder()
        rec.record_rng(stream="a", value="1")
        snapshot = rec.entries()
        rec.record_rng(stream="a", value="2")
        assert len(snapshot) == 1
```

- [ ] **Step 3: Run the test file to confirm it fails for the right reason**

Run: `uv run pytest tests/determinism/test_trace.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'chaos_librarian.determinism.trace'`. (The import line in the test file fails before any test body runs.)

- [ ] **Step 4: Implement `TraceRecorder`**

Create `src/chaos_librarian/determinism/trace.py`:

```python
"""Append-only execution-trace recorder.

The recorder owns the canonical sequence of trace entries that downstream
sprints embed in a ReplayBundle. It is the only writer; no third-party
append path exists. Constructor-injected into RngStreams and IdAllocator.
"""

from __future__ import annotations

from chaos_librarian.contract.replay_bundle import (
    AllocTraceEntry,
    ExecutionTraceEntry,
    MaterializerTraceEntry,
    RngTraceEntry,
)


class TraceRecorder:
    """Append-only buffer of ExecutionTraceEntry values."""

    def __init__(self) -> None:
        self._entries: list[ExecutionTraceEntry] = []

    def record_rng(self, stream: str, value: str) -> None:
        """Append an RngTraceEntry for one RNG draw."""
        self._entries.append(RngTraceEntry(kind="rng", stream=stream, value=value))

    def record_alloc(self, stream: str, value: str) -> None:
        """Append an AllocTraceEntry for one identifier allocation."""
        self._entries.append(AllocTraceEntry(kind="alloc", stream=stream, value=value))

    def record_materializer(self, stream: str, value: str, exit_code: int) -> None:
        """Append a MaterializerTraceEntry for one materializer subprocess.

        Declared in Sprint 2 to close the recorder API; Sprint 5 is the first
        consumer.
        """
        self._entries.append(
            MaterializerTraceEntry(
                kind="materializer",
                stream=stream,
                value=value,
                exit_code=exit_code,
            )
        )

    def entries(self) -> tuple[ExecutionTraceEntry, ...]:
        """Return an immutable tuple snapshot of recorded entries.

        Pydantic accepts tuples for ``list[...]`` fields during serialization,
        so Sprint 3's plan-only assembler can pass the snapshot through to
        the replay bundle without an extra copy step.
        """
        return tuple(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
```

- [ ] **Step 5: Run the tests, expect green**

Run: `uv run pytest tests/determinism/test_trace.py -v`
Expected: 8 tests pass.

- [ ] **Step 6: Run lint / type / format checks**

Run: `uv run ruff check src/chaos_librarian/determinism tests/determinism && uv run ruff format --check src/chaos_librarian/determinism tests/determinism && uv run ty check src/chaos_librarian/determinism tests/determinism`
Expected: all three exit 0.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/determinism/__init__.py \
  src/chaos_librarian/determinism/trace.py \
  tests/determinism/__init__.py \
  tests/determinism/test_trace.py
git commit -m "feat(determinism): add TraceRecorder with immutable snapshot API"
```

---

## Task 3: `resolve_seed` and `scenario_content_hash`

**Files:**

- Create: `src/chaos_librarian/determinism/seeding.py`
- Create: `tests/determinism/test_seeding.py`

Both helpers are pure functions with no recorder dependency. They live here because they are runtime helpers — not schema — and feed Sprint 3's plan-only `run_id` derivation.

- [ ] **Step 1: Write the failing test**

Create `tests/determinism/test_seeding.py`:

```python
"""Tests for chaos_librarian.determinism.seeding."""

from __future__ import annotations

import hashlib

from chaos_librarian.contract.replay_bundle import compute_plan_only_run_id
from chaos_librarian.determinism.seeding import resolve_seed, scenario_content_hash


class TestResolveSeed:
    """resolve_seed normalises declared scenario seeds to integers.

    WHY: Sprint 3 records the result as replay_bundle.resolved_seed so even
    a ``seed: random`` scenario is replayable.
    """

    def test_integer_seed_is_returned_verbatim(self) -> None:
        assert resolve_seed(0) == 0
        assert resolve_seed(42) == 42
        assert resolve_seed(2**63 - 1) == 2**63 - 1

    def test_random_seed_is_a_64_bit_unsigned_integer(self) -> None:
        seed = resolve_seed("random")
        assert isinstance(seed, int)
        assert 0 <= seed < 2**64

    def test_random_seed_varies_across_calls(self) -> None:
        # Probability of a 64-bit collision in 16 draws is ~1.7e-17;
        # if this test fails we have a much bigger problem than flakiness.
        seeds = {resolve_seed("random") for _ in range(16)}
        assert len(seeds) == 16


class TestScenarioContentHash:
    """scenario_content_hash is a stable lowercase hex sha256 of the YAML bytes.

    WHY: this is the hash compute_plan_only_run_id consumes to derive the
    deterministic UUIDv5 run_id; bit-identical bundles require a bit-identical
    hash function across runs.
    """

    def test_matches_hashlib_sha256(self) -> None:
        payload = b"scenario:\n  seed: 42\n"
        assert scenario_content_hash(payload) == hashlib.sha256(payload).hexdigest()

    def test_returns_lowercase_hex_digest(self) -> None:
        digest = scenario_content_hash(b"abc")
        assert len(digest) == 64
        assert digest == digest.lower()
        assert all(c in "0123456789abcdef" for c in digest)

    def test_distinct_inputs_hash_differently(self) -> None:
        assert scenario_content_hash(b"a") != scenario_content_hash(b"b")

    def test_feeds_compute_plan_only_run_id(self) -> None:
        # Plan-only run_id derivation must be reproducible across runs given
        # the same scenario bytes and resolved seed.
        payload = b"scenario:\n  seed: 7\n"
        digest = scenario_content_hash(payload)
        run_id_a = compute_plan_only_run_id(digest, 7)
        run_id_b = compute_plan_only_run_id(digest, 7)
        assert run_id_a == run_id_b
```

- [ ] **Step 2: Confirm the test fails with the expected import error**

Run: `uv run pytest tests/determinism/test_seeding.py -v`
Expected: `ModuleNotFoundError: No module named 'chaos_librarian.determinism.seeding'`.

- [ ] **Step 3: Implement the module**

Create `src/chaos_librarian/determinism/seeding.py`:

```python
"""Runtime helpers for seed resolution and scenario content hashing.

These functions live next to the deterministic primitives because they are
runtime inputs — not schemas — to RngStreams construction and to the
plan-only run_id derivation in contract.replay_bundle.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Literal


def resolve_seed(declared: int | Literal["random"]) -> int:
    """Return a concrete integer seed for the run.

    Args:
        declared: Either an integer (returned verbatim) or the string
            ``"random"`` (drawn from ``secrets.randbits(64)``).

    Returns:
        Non-negative integer seed; in the ``"random"`` branch the value is
        in ``[0, 2**64)``.
    """
    if declared == "random":
        return secrets.randbits(64)
    return declared


def scenario_content_hash(scenario_yaml_bytes: bytes) -> str:
    """Return the lowercase hex sha256 digest of the verbatim scenario YAML bytes.

    Sprint 3 passes this digest into
    ``chaos_librarian.contract.replay_bundle.compute_plan_only_run_id`` to
    derive the deterministic UUIDv5 ``run_id`` for plan-only bundles.
    """
    return hashlib.sha256(scenario_yaml_bytes).hexdigest()
```

- [ ] **Step 4: Run the tests, expect green**

Run: `uv run pytest tests/determinism/test_seeding.py -v`
Expected: 7 tests pass.

- [ ] **Step 5: Run lint / type / format**

Run: `uv run ruff check src/chaos_librarian/determinism tests/determinism && uv run ruff format --check src/chaos_librarian/determinism tests/determinism && uv run ty check src/chaos_librarian/determinism tests/determinism`
Expected: all three exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/determinism/seeding.py tests/determinism/test_seeding.py
git commit -m "feat(determinism): add resolve_seed and scenario_content_hash"
```

---

## Task 4: `IdAllocator` counter behavior

**Files:**

- Create: `src/chaos_librarian/determinism/ids.py`
- Create: `tests/determinism/test_ids.py`

Counter-only allocator with one independent counter per namespace plus the overflow guard. The property test for interleaving lives in Task 5.

- [ ] **Step 1: Write the failing test**

Create `tests/determinism/test_ids.py`:

```python
"""Tests for chaos_librarian.determinism.ids.IdAllocator."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.replay_bundle import AllocTraceEntry
from chaos_librarian.determinism.ids import IdAllocator, IdAllocatorOverflow
from chaos_librarian.determinism.trace import TraceRecorder


class TestAllocatorBasicSequence:
    """First call returns _0001; subsequent calls increment monotonically.

    WHY: lexicographic sort of allocator-owned IDs (version, location,
    sidecar, mutation) is a downstream assumption in journal ordering and
    manifest snapshotting. A reset or skip would invalidate ordered diffs.
    """

    def test_first_call_returns_0001(self) -> None:
        alloc = IdAllocator(recorder=TraceRecorder())
        assert alloc.next_version_id() == "version_0001"
        assert alloc.next_location_id() == "location_0001"
        assert alloc.next_sidecar_id() == "sidecar_0001"
        assert alloc.next_mutation_id() == "mutation_0001"

    def test_sequential_calls_increment_within_namespace(self) -> None:
        alloc = IdAllocator(recorder=TraceRecorder())
        ids = [alloc.next_version_id() for _ in range(3)]
        assert ids == ["version_0001", "version_0002", "version_0003"]

    def test_id_is_zero_padded_to_four_digits(self) -> None:
        alloc = IdAllocator(recorder=TraceRecorder())
        for _ in range(11):
            last = alloc.next_version_id()
        assert last == "version_0011"


class TestNamespaceIndependence:
    """Each namespace has its own counter; bumping one never moves another.

    WHY: scenario authors interleave version/location/sidecar/mutation
    allocations freely; cross-talk would silently desync identifier streams
    from one another and from the trace.
    """

    def test_other_namespaces_unaffected_by_version_calls(self) -> None:
        alloc = IdAllocator(recorder=TraceRecorder())
        for _ in range(5):
            alloc.next_version_id()
        assert alloc.next_location_id() == "location_0001"
        assert alloc.next_sidecar_id() == "sidecar_0001"
        assert alloc.next_mutation_id() == "mutation_0001"


class TestAllocatorTraceFidelity:
    """Each allocation appends exactly one AllocTraceEntry with the right stream/value.

    WHY: trace fidelity is the load-bearing input to Sprint 4's replay
    divergence detection. A missing or mislabelled entry would silently mask
    a real bug.
    """

    def test_allocation_appends_alloc_entry(self) -> None:
        rec = TraceRecorder()
        alloc = IdAllocator(recorder=rec)
        result = alloc.next_version_id()
        (entry,) = rec.entries()
        assert isinstance(entry, AllocTraceEntry)
        assert entry.kind == "alloc"
        assert entry.stream == "version"
        assert entry.value == result

    def test_multiple_allocations_in_call_order(self) -> None:
        rec = TraceRecorder()
        alloc = IdAllocator(recorder=rec)
        alloc.next_version_id()
        alloc.next_location_id()
        alloc.next_version_id()
        streams = [e.stream for e in rec.entries()]
        values = [e.value for e in rec.entries()]
        assert streams == ["version", "location", "version"]
        assert values == ["version_0001", "location_0001", "version_0002"]


class TestAllocatorOverflow:
    """The 10,000th call into a namespace raises IdAllocatorOverflow.

    WHY: 4-digit width keeps lexicographic sort stable across allocator-owned
    IDs. Silently producing ``version_10000`` would break sort order in
    downstream tools and contract consumers.
    """

    def test_overflow_after_9999_allocations(self) -> None:
        alloc = IdAllocator(recorder=TraceRecorder())
        for _ in range(9_999):
            alloc.next_version_id()
        with pytest.raises(IdAllocatorOverflow) as excinfo:
            alloc.next_version_id()
        assert "version" in str(excinfo.value)

    def test_overflow_does_not_affect_other_namespaces(self) -> None:
        alloc = IdAllocator(recorder=TraceRecorder())
        for _ in range(9_999):
            alloc.next_version_id()
        with pytest.raises(IdAllocatorOverflow):
            alloc.next_version_id()
        # location counter must still start at 1.
        assert alloc.next_location_id() == "location_0001"
```

- [ ] **Step 2: Confirm the test fails with the expected import error**

Run: `uv run pytest tests/determinism/test_ids.py -v`
Expected: `ModuleNotFoundError: No module named 'chaos_librarian.determinism.ids'`.

- [ ] **Step 3: Implement the module**

Create `src/chaos_librarian/determinism/ids.py`:

```python
"""Monotonic ID allocator with one independent counter per namespace.

The allocator owns only the four namespaces whose IDs have no source in
the scenario YAML — ``version``, ``location``, ``sidecar``, ``mutation``.
The other four oracle namespaces (``work``, ``variant``, ``bundle``,
``asset``) are scenario-authored ``str`` fields on the Scenario model
and flow verbatim through the timeline into the manifest; the allocator
never generates or mutates those values.
"""

from __future__ import annotations

from chaos_librarian.determinism.trace import TraceRecorder

_MAX_PER_NAMESPACE = 9_999
_NAMESPACES = ("version", "location", "sidecar", "mutation")


class IdAllocatorOverflow(RuntimeError):
    """Raised when a namespace counter would advance past 9_999."""


class IdAllocator:
    """Per-namespace counter-only allocator."""

    def __init__(self, recorder: TraceRecorder) -> None:
        self._recorder = recorder
        self._counters: dict[str, int] = dict.fromkeys(_NAMESPACES, 0)

    def _allocate(self, namespace: str) -> str:
        current = self._counters[namespace]
        if current >= _MAX_PER_NAMESPACE:
            raise IdAllocatorOverflow(
                f"namespace {namespace!r} exhausted at {current} allocations "
                f"(max {_MAX_PER_NAMESPACE} per namespace)"
            )
        next_n = current + 1
        self._counters[namespace] = next_n
        allocated = f"{namespace}_{next_n:04d}"
        self._recorder.record_alloc(stream=namespace, value=allocated)
        return allocated

    def next_version_id(self) -> str:
        return self._allocate("version")

    def next_location_id(self) -> str:
        return self._allocate("location")

    def next_sidecar_id(self) -> str:
        return self._allocate("sidecar")

    def next_mutation_id(self) -> str:
        return self._allocate("mutation")
```

- [ ] **Step 4: Run the tests, expect green**

Run: `uv run pytest tests/determinism/test_ids.py -v`
Expected: 8 tests pass.

- [ ] **Step 5: Run lint / type / format**

Run: `uv run ruff check src/chaos_librarian/determinism tests/determinism && uv run ruff format --check src/chaos_librarian/determinism tests/determinism && uv run ty check src/chaos_librarian/determinism tests/determinism`
Expected: all three exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/determinism/ids.py tests/determinism/test_ids.py
git commit -m "feat(determinism): add IdAllocator with per-namespace counters and overflow guard"
```

---

## Task 5: `IdAllocator` interleaving property test

**Files:**

- Create: `tests/determinism/test_ids_properties.py`

Hypothesis-based check that the allocator's behavior under arbitrary call interleaving is fully determined by per-namespace call counts. Reuses the implementation from Task 4 unchanged.

- [ ] **Step 1: Write the property test**

Create `tests/determinism/test_ids_properties.py`:

```python
"""Property tests for IdAllocator interleaving stability."""

from __future__ import annotations

from collections import Counter

from hypothesis import given, settings
from hypothesis import strategies as st

from chaos_librarian.determinism.ids import IdAllocator
from chaos_librarian.determinism.trace import TraceRecorder

_METHODS = {
    "version": "next_version_id",
    "location": "next_location_id",
    "sidecar": "next_sidecar_id",
    "mutation": "next_mutation_id",
}


@given(
    calls=st.lists(
        st.sampled_from(list(_METHODS)),
        min_size=0,
        max_size=200,
    )
)
@settings(max_examples=200, deadline=None)
def test_allocator_output_depends_only_on_per_namespace_counts(calls: list[str]) -> None:
    """For any interleaving of next_*_id() calls across the four namespaces,
    the resulting ID list is determined entirely by per-namespace counts.

    WHY: this is the operational form of the "allocator order-stability"
    guarantee. If a future change accidentally couples two namespaces (e.g.,
    a shared counter), this test will catch it.
    """
    alloc = IdAllocator(recorder=TraceRecorder())
    actual: list[str] = []
    for namespace in calls:
        method = getattr(alloc, _METHODS[namespace])
        actual.append(method())

    # Hand-rolled per-namespace counter — the reference implementation.
    reference_counters: Counter[str] = Counter()
    expected: list[str] = []
    for namespace in calls:
        reference_counters[namespace] += 1
        expected.append(f"{namespace}_{reference_counters[namespace]:04d}")

    assert actual == expected
```

- [ ] **Step 2: Run the test, expect green**

Run: `uv run pytest tests/determinism/test_ids_properties.py -v`
Expected: 1 test passes; hypothesis reports `Falsifying example` only if the implementation is wrong.

- [ ] **Step 3: Run lint / type / format**

Run: `uv run ruff check tests/determinism && uv run ruff format --check tests/determinism && uv run ty check tests/determinism`
Expected: all three exit 0.

- [ ] **Step 4: Commit**

```bash
git add tests/determinism/test_ids_properties.py
git commit -m "test(determinism): property-check IdAllocator interleaving stability"
```

---

## Task 6: `Clock` plus duration formatters

**Files:**

- Create: `src/chaos_librarian/determinism/clock.py`
- Create: `tests/determinism/test_clock.py`

Logical clock (monotonic only), `format_duration_human`, `format_duration_json`. The round-trip property test lives in Task 7.

- [ ] **Step 1: Write the failing test**

Create `tests/determinism/test_clock.py`:

```python
"""Tests for chaos_librarian.determinism.clock."""

from __future__ import annotations

import pytest

from chaos_librarian.clock import parse_duration
from chaos_librarian.determinism.clock import (
    Clock,
    format_duration_human,
    format_duration_json,
)


class TestClockMonotonic:
    """Clock only moves forward.

    WHY: Sprint 3 walks a timeline by issuing set_to(at:) jumps; any backward
    motion would silently reorder events that the journal must record in
    declared order.
    """

    def test_default_starts_at_zero(self) -> None:
        assert Clock().now() == 0

    def test_advance_returns_new_now(self) -> None:
        clk = Clock()
        new_now = clk.advance(1_000)
        assert new_now == 1_000
        assert clk.now() == 1_000

    def test_advance_accumulates(self) -> None:
        clk = Clock()
        clk.advance(500)
        clk.advance(250)
        assert clk.now() == 750

    def test_advance_zero_is_ok(self) -> None:
        clk = Clock()
        assert clk.advance(0) == 0

    def test_advance_negative_raises(self) -> None:
        clk = Clock()
        with pytest.raises(ValueError, match="delta_ns"):
            clk.advance(-1)

    def test_set_to_forward_is_ok(self) -> None:
        clk = Clock()
        clk.set_to(5_000)
        assert clk.now() == 5_000
        clk.set_to(5_000)
        assert clk.now() == 5_000

    def test_set_to_backward_raises(self) -> None:
        clk = Clock()
        clk.set_to(5_000)
        with pytest.raises(ValueError, match="current_ns"):
            clk.set_to(4_999)


class TestFormatDurationHumanEdges:
    """Edge cases for format_duration_human.

    WHY: every JSON-vs-human boundary in later sprints calls this; surprising
    output here ripples into log readability and into the parse/format
    round-trip guarantee.
    """

    def test_zero(self) -> None:
        assert format_duration_human(0) == "0s"

    def test_minute_and_milliseconds(self) -> None:
        # The canonical example from the design spec.
        assert format_duration_human(90_250_000_000) == "1m30s250ms"

    def test_microsecond_residue(self) -> None:
        # 1m30s250ms + 500us, exactly the spec example.
        assert format_duration_human(90_250_000_000 + 500_000) == "1m30s250ms500us"

    def test_nanosecond_residue(self) -> None:
        assert (
            format_duration_human(90_250_000_000 + 500_000 + 123)
            == "1m30s250ms500us123ns"
        )

    def test_only_top_unit(self) -> None:
        assert format_duration_human(1_000_000_000) == "1s"
        assert format_duration_human(60_000_000_000) == "1m"
        assert format_duration_human(3_600_000_000_000) == "1h"

    def test_negative_raises(self) -> None:
        with pytest.raises(ValueError, match=">= 0"):
            format_duration_human(-1)


class TestFormatDurationJson:
    """format_duration_json returns ints verbatim.

    WHY: the function exists as a named hop so every JSON emission site is
    grep-able and can be swapped to a string representation later without
    touching call sites.
    """

    def test_returns_int_verbatim(self) -> None:
        assert format_duration_json(0) == 0
        assert format_duration_json(90_250_000_000) == 90_250_000_000

    def test_non_int_raises_type_error(self) -> None:
        with pytest.raises(TypeError):
            format_duration_json("90s")  # type: ignore[arg-type]


class TestParseFormatRoundTripExamples:
    """Hand-rolled spot checks before the hypothesis property in Task 7.

    WHY: the round-trip property is load-bearing — Sprint 3 will format
    durations into bundles and Sprint 4 may re-parse them on replay.
    """

    @pytest.mark.parametrize(
        "ns",
        [
            0,
            1_000_000,           # 1ms
            500_000_000,         # 500ms
            1_000_000_000,       # 1s
            90_250_000_000,      # 1m30s250ms
            3_723_000_000_000,   # 1h2m3s
        ],
    )
    def test_round_trip(self, ns: int) -> None:
        assert parse_duration(format_duration_human(ns)) == ns
```

- [ ] **Step 2: Confirm the test fails with the expected import error**

Run: `uv run pytest tests/determinism/test_clock.py -v`
Expected: `ModuleNotFoundError: No module named 'chaos_librarian.determinism.clock'`.

- [ ] **Step 3: Implement the module**

Create `src/chaos_librarian/determinism/clock.py`:

```python
"""Logical clock and duration formatters.

The Clock is monotonic-only — no scheduling, no wall-clock awareness.
Sprint 3 will use it to walk a timeline's ``at:`` values; Sprint 8 will
add wall-clock-mode wiring on top.

The formatters here pair with Sprint 1's
``chaos_librarian.clock.parse_duration``. The round-trip identity
``parse_duration(format_duration_human(ns)) == ns`` holds for every
``ns >= 0`` representable as a clean h/m/s/ms sum (no microsecond /
nanosecond residue).
"""

from __future__ import annotations

from dataclasses import dataclass

_NS_PER_HOUR = 3_600_000_000_000
_NS_PER_MINUTE = 60_000_000_000
_NS_PER_SECOND = 1_000_000_000
_NS_PER_MS = 1_000_000
_NS_PER_US = 1_000

_HUMAN_UNITS: tuple[tuple[str, int], ...] = (
    ("h", _NS_PER_HOUR),
    ("m", _NS_PER_MINUTE),
    ("s", _NS_PER_SECOND),
    ("ms", _NS_PER_MS),
    ("us", _NS_PER_US),
    ("ns", 1),
)


@dataclass
class Clock:
    """Monotonic logical clock measured in nanoseconds since t=0."""

    current_ns: int = 0

    def advance(self, delta_ns: int) -> int:
        """Move the clock forward by ``delta_ns`` and return the new ``current_ns``.

        Raises:
            ValueError: If ``delta_ns < 0``.
        """
        if delta_ns < 0:
            raise ValueError(f"advance requires delta_ns >= 0, got {delta_ns}")
        self.current_ns += delta_ns
        return self.current_ns

    def now(self) -> int:
        """Return the current logical timestamp in nanoseconds."""
        return self.current_ns

    def set_to(self, target_ns: int) -> None:
        """Jump the clock to ``target_ns``.

        Raises:
            ValueError: If ``target_ns`` is earlier than ``current_ns``.
        """
        if target_ns < self.current_ns:
            raise ValueError(
                f"set_to requires target_ns >= current_ns "
                f"({self.current_ns}), got {target_ns}"
            )
        self.current_ns = target_ns


def format_duration_human(ns: int) -> str:
    """Format ``ns`` as a grammar-compatible duration string.

    Examples:
        ``format_duration_human(0) == "0s"``
        ``format_duration_human(90_250_000_000) == "1m30s250ms"``
        ``format_duration_human(90_250_500_123) == "1m30s250ms500us123ns"``

    The output is parseable by ``chaos_librarian.clock.parse_duration``
    when the input has no sub-millisecond residue.

    Raises:
        ValueError: If ``ns < 0``.
    """
    if ns < 0:
        raise ValueError(f"format_duration_human requires ns >= 0, got {ns}")
    if ns == 0:
        return "0s"
    parts: list[str] = []
    remaining = ns
    for unit, multiplier in _HUMAN_UNITS:
        count, remaining = divmod(remaining, multiplier)
        if count:
            parts.append(f"{count}{unit}")
    return "".join(parts)


def format_duration_json(ns: int) -> int:
    """Return ``ns`` verbatim after a type check.

    Exists as a named function so every JSON emission site is grep-able
    and can be swapped to a string representation later without touching
    call sites.

    Raises:
        TypeError: If ``ns`` is not an ``int``.
    """
    if not isinstance(ns, int):
        raise TypeError(f"format_duration_json expects int, got {type(ns).__name__}")
    return ns
```

- [ ] **Step 4: Verify the spec's specific microsecond example**

A quick sanity check before running the full test: `format_duration_human(90_250_000_000 + 500_000)` should be `1m30s250ms500us`. The plan's test asserts both forms; the previous example using `90_250_000_500_000` is a different value (90.25 milliseconds * 1000 = 25h... ns) so it is parameterised as a *second*, larger, separate assertion. Read the test carefully and don't assume both should produce the same string.

- [ ] **Step 5: Run the tests, expect green**

Run: `uv run pytest tests/determinism/test_clock.py -v`
Expected: every assertion passes (about 20 tests across the four classes).

- [ ] **Step 6: Run lint / type / format**

Run: `uv run ruff check src/chaos_librarian/determinism tests/determinism && uv run ruff format --check src/chaos_librarian/determinism tests/determinism && uv run ty check src/chaos_librarian/determinism tests/determinism`
Expected: all three exit 0.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/determinism/clock.py tests/determinism/test_clock.py
git commit -m "feat(determinism): add Clock and grammar-compatible duration formatters"
```

---

## Task 7: Duration round-trip property test

**Files:**

- Create: `tests/determinism/test_clock_properties.py`

Hypothesis property that locks down `parse_duration(format_duration_human(ns)) == ns` over the clean h/m/s/ms space.

- [ ] **Step 1: Write the property test**

Create `tests/determinism/test_clock_properties.py`:

```python
"""Property tests for the parse_duration / format_duration_human round-trip."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from chaos_librarian.clock import parse_duration
from chaos_librarian.determinism.clock import format_duration_human

_NS_PER_HOUR = 3_600_000_000_000
_NS_PER_MINUTE = 60_000_000_000
_NS_PER_SECOND = 1_000_000_000
_NS_PER_MS = 1_000_000


@given(
    hours=st.integers(min_value=0, max_value=23),
    minutes=st.integers(min_value=0, max_value=59),
    seconds=st.integers(min_value=0, max_value=59),
    millis=st.integers(min_value=0, max_value=999),
)
@settings(max_examples=200, deadline=None)
def test_parse_format_round_trip_over_clean_hms_ms_sum(
    hours: int, minutes: int, seconds: int, millis: int
) -> None:
    """parse_duration(format_duration_human(ns)) == ns for any clean h/m/s/ms sum.

    WHY: round-trip stability is a load-bearing determinism guarantee —
    Sprint 3 formats durations into bundles, and Sprint 4's replay may
    re-parse them. The strategy bounds keep the composed sum well below
    i64_max, so overflow is impossible here.
    """
    ns = (
        hours * _NS_PER_HOUR
        + minutes * _NS_PER_MINUTE
        + seconds * _NS_PER_SECOND
        + millis * _NS_PER_MS
    )
    assert parse_duration(format_duration_human(ns)) == ns
```

- [ ] **Step 2: Run the property test, expect green**

Run: `uv run pytest tests/determinism/test_clock_properties.py -v`
Expected: 1 test passes; hypothesis explores ~200 example sums without finding a falsifying case.

- [ ] **Step 3: Run lint / type / format**

Run: `uv run ruff check tests/determinism && uv run ruff format --check tests/determinism && uv run ty check tests/determinism`
Expected: all three exit 0.

- [ ] **Step 4: Commit**

```bash
git add tests/determinism/test_clock_properties.py
git commit -m "test(determinism): property-check parse/format duration round-trip"
```

---

## Task 8: `RngStream` and `RngStreams`

**Files:**

- Create: `src/chaos_librarian/determinism/rng.py`
- Create: `tests/determinism/test_rng.py`

Per-stream recording RNG plus the sub-seed-derived factory. The wrapper pattern (not subclass) is deliberate — see spec rationale on nested recording / undocumented `random.Random` internals.

- [ ] **Step 1: Write the failing test**

Create `tests/determinism/test_rng.py`:

```python
"""Tests for chaos_librarian.determinism.rng (RngStream + RngStreams)."""

from __future__ import annotations

import pytest

from chaos_librarian.contract.replay_bundle import RngTraceEntry
from chaos_librarian.determinism.rng import RngStream, RngStreams
from chaos_librarian.determinism.trace import TraceRecorder


class TestStreamCache:
    """RngStreams returns the same RngStream instance per name.

    WHY: stream identity makes the per-stream call sequence well-defined.
    Returning a fresh instance per call would silently restart the underlying
    random.Random on every stream() lookup, defeating determinism.
    """

    def test_same_name_returns_same_instance(self) -> None:
        streams = RngStreams(resolved_seed=42, recorder=TraceRecorder())
        assert streams.stream("video_source") is streams.stream("video_source")

    def test_distinct_names_return_distinct_instances(self) -> None:
        streams = RngStreams(resolved_seed=42, recorder=TraceRecorder())
        assert streams.stream("a") is not streams.stream("b")


class TestSameSeedSameDraws:
    """Two RngStreams built from the same seed produce identical draws.

    WHY: this is the operational form of the "same seed → same RNG draws"
    determinism guarantee that bit-identical plan-only bundles bottom out in.
    """

    def test_random_draws_match(self) -> None:
        a = RngStreams(resolved_seed=42, recorder=TraceRecorder()).stream("video_source")
        b = RngStreams(resolved_seed=42, recorder=TraceRecorder()).stream("video_source")
        assert [a.random() for _ in range(20)] == [b.random() for _ in range(20)]

    def test_randint_draws_match(self) -> None:
        a = RngStreams(resolved_seed=99, recorder=TraceRecorder()).stream("audio_source")
        b = RngStreams(resolved_seed=99, recorder=TraceRecorder()).stream("audio_source")
        assert [a.randint(0, 100) for _ in range(20)] == [b.randint(0, 100) for _ in range(20)]


class TestSubSeedDivergesByName:
    """Different stream names under the same seed produce different draws.

    WHY: the sub-seed derivation (sha256(seed/name)) is what gives Sprint 5/6
    additive freedom — adding a new stream cannot perturb existing ones.
    """

    def test_different_names_diverge(self) -> None:
        streams = RngStreams(resolved_seed=42, recorder=TraceRecorder())
        a_draws = [streams.stream("a").random() for _ in range(20)]
        b_draws = [streams.stream("b").random() for _ in range(20)]
        assert a_draws != b_draws


class TestTraceFidelity:
    """Every documented draw records exactly one RngTraceEntry with value=repr(returned).

    WHY: trace fidelity is the input to Sprint 4 replay divergence detection.
    A missing or mis-labelled entry would silently mask a real bug; an extra
    entry would invalidate position-based trace comparison.
    """

    def test_random_records_one_entry(self) -> None:
        rec = TraceRecorder()
        streams = RngStreams(resolved_seed=42, recorder=rec)
        v = streams.stream("video_source").random()
        (entry,) = rec.entries()
        assert isinstance(entry, RngTraceEntry)
        assert entry.kind == "rng"
        assert entry.stream == "video_source"
        assert entry.value == repr(v)

    def test_each_documented_method_records_one_entry(self) -> None:
        rec = TraceRecorder()
        s = RngStreams(resolved_seed=42, recorder=rec).stream("metadata")
        s.random()
        s.randint(0, 10)
        s.randrange(10)
        s.randrange(2, 10)
        s.randrange(2, 10, 2)
        s.randbytes(4)
        s.choice([1, 2, 3])
        s.choices([1, 2, 3], k=2)
        s.sample([1, 2, 3], 2)
        s.uniform(0.0, 1.0)
        s.gauss(0.0, 1.0)
        assert len(rec) == 11
        assert all(e.kind == "rng" for e in rec.entries())
        assert all(e.stream == "metadata" for e in rec.entries())

    def test_value_is_repr_of_returned(self) -> None:
        rec = TraceRecorder()
        s = RngStreams(resolved_seed=42, recorder=rec).stream("file_layout")
        v = s.randbytes(4)
        (entry,) = rec.entries()
        assert entry.value == repr(v)
        # And the recorded string survives a pure-Python compare.
        assert isinstance(entry.value, str)


class TestShuffleIsExcluded:
    """RngStream deliberately does not expose shuffle.

    WHY: random.shuffle mutates in place and returns None. With value=repr(returned),
    every shuffle would record "None" regardless of the resulting permutation,
    defeating trace-driven divergence detection. Callers needing random
    reordering use sample(seq, k=len(seq)).
    """

    def test_shuffle_attribute_absent(self) -> None:
        rec = TraceRecorder()
        s = RngStreams(resolved_seed=1, recorder=rec).stream("a")
        assert not hasattr(s, "shuffle")


class TestRngStreamConstructionDoesNotLog:
    """Constructing RngStreams or asking for a stream records nothing.

    WHY: only user-facing draws should appear in the trace. If sub-seed
    derivation accidentally produced an entry, the trace would be polluted
    with non-deterministic counts depending on stream-cache lookups.
    """

    def test_constructor_does_not_record(self) -> None:
        rec = TraceRecorder()
        RngStreams(resolved_seed=42, recorder=rec)
        assert len(rec) == 0

    def test_stream_lookup_does_not_record(self) -> None:
        rec = TraceRecorder()
        streams = RngStreams(resolved_seed=42, recorder=rec)
        streams.stream("a")
        streams.stream("a")
        streams.stream("b")
        assert len(rec) == 0


class TestRngStreamSeparationByStream:
    """A single RngStreams produces independent sequences across streams.

    WHY: ensures the cache keys the underlying random.Random by name, not
    by accident of construction order.
    """

    def test_two_streams_under_one_factory_are_independent(self) -> None:
        streams = RngStreams(resolved_seed=42, recorder=TraceRecorder())
        a = streams.stream("a")
        b = streams.stream("b")
        a_draws = [a.random() for _ in range(10)]
        b_draws = [b.random() for _ in range(10)]
        # Same seed, different names — sub-seeds diverge.
        assert a_draws != b_draws


class TestStreamIsNotRandomSubclass:
    """RngStream is not a subclass of random.Random.

    WHY: subclassing leaks random.Random's undocumented internals (e.g.
    _randbelow) and creates a nested-recording problem when overridden
    methods call each other. The wrapper pattern is deliberate — see the
    Sprint 2 design spec rationale.
    """

    def test_not_a_random_subclass(self) -> None:
        import random

        rec = TraceRecorder()
        s = RngStreams(resolved_seed=42, recorder=rec).stream("a")
        assert not isinstance(s, random.Random)
        assert type(s) is RngStream
```

- [ ] **Step 2: Confirm the test fails with the expected import error**

Run: `uv run pytest tests/determinism/test_rng.py -v`
Expected: `ModuleNotFoundError: No module named 'chaos_librarian.determinism.rng'`.

- [ ] **Step 3: Implement the module**

Create `src/chaos_librarian/determinism/rng.py`:

```python
"""Per-stream recording RNG.

RngStreams derives a sub-seed per stream name from
``sha256(f"{resolved_seed}/{name}").digest()[:8]``, caches one RngStream
per name, and records every user-facing draw in the trace. RngStream
wraps a private ``random.Random`` rather than subclassing it — see the
Sprint 2 design spec rationale on nested-recording / undocumented
``random.Random`` internals.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from typing import TypeVar

from chaos_librarian.determinism.trace import TraceRecorder

T = TypeVar("T")


def _derive_subseed(resolved_seed: int, stream_name: str) -> int:
    digest = hashlib.sha256(f"{resolved_seed}/{stream_name}".encode()).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False)


class RngStream:
    """Recording RNG for a single named stream.

    Wraps one private ``random.Random`` and records exactly one
    ``RngTraceEntry`` per user-facing call. Methods that return ``None``
    (e.g. ``random.Random.shuffle``) are deliberately excluded — their
    trace value would not capture the operation result. Callers needing
    random reordering use ``sample(seq, k=len(seq))``.
    """

    def __init__(self, name: str, subseed: int, recorder: TraceRecorder) -> None:
        self._name = name
        self._random = random.Random(subseed)
        self._recorder = recorder

    def _record(self, value: object) -> None:
        self._recorder.record_rng(stream=self._name, value=repr(value))

    def random(self) -> float:
        value = self._random.random()
        self._record(value)
        return value

    def randint(self, a: int, b: int) -> int:
        value = self._random.randint(a, b)
        self._record(value)
        return value

    def randrange(self, start: int, stop: int | None = None, step: int = 1) -> int:
        if stop is None:
            value = self._random.randrange(start)
        else:
            value = self._random.randrange(start, stop, step)
        self._record(value)
        return value

    def randbytes(self, n: int) -> bytes:
        value = self._random.randbytes(n)
        self._record(value)
        return value

    def choice(self, seq: Sequence[T]) -> T:
        value = self._random.choice(seq)
        self._record(value)
        return value

    def choices(self, seq: Sequence[T], k: int = 1) -> list[T]:
        value = self._random.choices(seq, k=k)
        self._record(value)
        return value

    def sample(self, seq: Sequence[T], k: int) -> list[T]:
        value = self._random.sample(seq, k)
        self._record(value)
        return value

    def uniform(self, a: float, b: float) -> float:
        value = self._random.uniform(a, b)
        self._record(value)
        return value

    def gauss(self, mu: float, sigma: float) -> float:
        value = self._random.gauss(mu, sigma)
        self._record(value)
        return value


class RngStreams:
    """Factory of cached, named RngStream instances seeded sub-deterministically."""

    def __init__(self, resolved_seed: int, recorder: TraceRecorder) -> None:
        self._resolved_seed = resolved_seed
        self._recorder = recorder
        self._cache: dict[str, RngStream] = {}

    def stream(self, name: str) -> RngStream:
        """Return the cached RngStream for ``name``, constructing on first lookup."""
        cached = self._cache.get(name)
        if cached is not None:
            return cached
        stream = RngStream(
            name=name,
            subseed=_derive_subseed(self._resolved_seed, name),
            recorder=self._recorder,
        )
        self._cache[name] = stream
        return stream
```

- [ ] **Step 4: Run the tests, expect green**

Run: `uv run pytest tests/determinism/test_rng.py -v`
Expected: every test passes (~15 tests across the eight classes).

- [ ] **Step 5: Run lint / type / format**

Run: `uv run ruff check src/chaos_librarian/determinism tests/determinism && uv run ruff format --check src/chaos_librarian/determinism tests/determinism && uv run ty check src/chaos_librarian/determinism tests/determinism`
Expected: all three exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/determinism/rng.py tests/determinism/test_rng.py
git commit -m "feat(determinism): add recording RngStream and RngStreams factory"
```

---

## Task 9: RNG stream-independence property test

**Files:**

- Create: `tests/determinism/test_rng_properties.py`

Hypothesis property that locks down stream independence — drawing from stream A any number of times cannot perturb the values stream B produces.

- [ ] **Step 1: Write the property test**

Create `tests/determinism/test_rng_properties.py`:

```python
"""Property tests for RngStreams stream independence."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

from chaos_librarian.determinism.rng import RngStreams
from chaos_librarian.determinism.trace import TraceRecorder


@given(
    seed=st.integers(min_value=0, max_value=2**63 - 1),
    a_draws=st.integers(min_value=0, max_value=64),
    b_draws=st.integers(min_value=1, max_value=32),
)
@settings(max_examples=200, deadline=None)
def test_stream_b_draws_are_independent_of_stream_a(
    seed: int, a_draws: int, b_draws: int
) -> None:
    """Drawing from stream A any number of times does not perturb stream B.

    WHY: this is the operational form of the "stream independence"
    determinism guarantee — Sprint 5/6/7 add new stream names without
    invalidating earlier fixtures because each sub-seed is derived
    independently from sha256(seed/name).
    """
    rec_with_a = TraceRecorder()
    streams_with_a = RngStreams(resolved_seed=seed, recorder=rec_with_a)
    stream_a = streams_with_a.stream("a")
    for _ in range(a_draws):
        stream_a.random()
    stream_b = streams_with_a.stream("b")
    with_a = [stream_b.random() for _ in range(b_draws)]

    rec_without_a = TraceRecorder()
    streams_without_a = RngStreams(resolved_seed=seed, recorder=rec_without_a)
    stream_b_solo = streams_without_a.stream("b")
    without_a = [stream_b_solo.random() for _ in range(b_draws)]

    assert with_a == without_a
```

- [ ] **Step 2: Run the property test, expect green**

Run: `uv run pytest tests/determinism/test_rng_properties.py -v`
Expected: 1 test passes; hypothesis explores ~200 (seed, a_draws, b_draws) tuples.

- [ ] **Step 3: Run lint / type / format**

Run: `uv run ruff check tests/determinism && uv run ruff format --check tests/determinism && uv run ty check tests/determinism`
Expected: all three exit 0.

- [ ] **Step 4: Confirm the determinism property-test suite as a whole stays under 5 seconds**

Run: `uv run pytest tests/determinism/test_rng_properties.py tests/determinism/test_ids_properties.py tests/determinism/test_clock_properties.py --durations=0`
Expected: total runtime well under 5 seconds (the spec's exit criterion). If any single test exceeds ~1 second, reduce `max_examples` on the offender — but in practice 200 examples at this complexity finish in tens of milliseconds.

- [ ] **Step 5: Commit**

```bash
git add tests/determinism/test_rng_properties.py
git commit -m "test(determinism): property-check RngStreams stream independence"
```

---

## Task 10: Public surface (`determinism/__init__.py`) and import-smoke test

**Files:**

- Modify: `src/chaos_librarian/determinism/__init__.py` (replace the placeholder with the public re-exports)
- Create: `tests/determinism/test_public_surface.py`

This is the only file consumers in Sprints 3+ touch; locking down `__all__` here is the contract.

- [ ] **Step 1: Write the failing test**

Create `tests/determinism/test_public_surface.py`:

```python
"""Smoke test that the Sprint 2 public surface imports cleanly and behaves."""

from __future__ import annotations


def test_public_surface_matches_spec() -> None:
    """All nine names import from chaos_librarian.determinism.

    WHY: downstream sprints import only from this package; the submodule
    layout is implementation detail. If a re-export is missed, Sprint 3
    would have to reach into private submodules and the package boundary
    would leak.
    """
    from chaos_librarian.determinism import (
        Clock,
        IdAllocator,
        IdAllocatorOverflow,
        RngStreams,
        TraceRecorder,
        format_duration_human,
        format_duration_json,
        resolve_seed,
        scenario_content_hash,
    )

    rec = TraceRecorder()
    rng = RngStreams(resolved_seed=42, recorder=rec)
    # Cached stream returns identical instance — the exit-criteria smoke from
    # the design spec.
    assert rng.stream("video_source") is rng.stream("video_source")
    alloc = IdAllocator(recorder=rec)
    assert alloc.next_version_id() == "version_0001"
    clk = Clock()
    clk.advance(1_000)
    assert clk.now() == 1_000
    assert format_duration_human(0) == "0s"
    assert format_duration_json(0) == 0
    assert isinstance(resolve_seed(7), int)
    assert isinstance(scenario_content_hash(b"x"), str)


def test_dunder_all_is_alphabetised_and_exact() -> None:
    """__all__ lists exactly the nine names from the spec, in alphabetical order.

    WHY: __all__ is part of the public contract. Adding a name here is
    additive (and intentional); reordering or removing one is a break.
    """
    import chaos_librarian.determinism as determinism

    assert determinism.__all__ == [
        "Clock",
        "IdAllocator",
        "IdAllocatorOverflow",
        "RngStreams",
        "TraceRecorder",
        "format_duration_human",
        "format_duration_json",
        "resolve_seed",
        "scenario_content_hash",
    ]
```

- [ ] **Step 2: Run the test — it must fail because `__init__.py` is still the placeholder**

Run: `uv run pytest tests/determinism/test_public_surface.py -v`
Expected: `ImportError: cannot import name 'Clock' from 'chaos_librarian.determinism'` (or the equivalent message; the file currently only has a module docstring).

- [ ] **Step 3: Replace the placeholder `__init__.py`**

Overwrite `src/chaos_librarian/determinism/__init__.py` with:

```python
"""Sprint 2 deterministic primitives — public surface.

Downstream sprints import from this package; the submodules are
implementation detail.
"""

from chaos_librarian.determinism.clock import (
    Clock,
    format_duration_human,
    format_duration_json,
)
from chaos_librarian.determinism.ids import IdAllocator, IdAllocatorOverflow
from chaos_librarian.determinism.rng import RngStreams
from chaos_librarian.determinism.seeding import resolve_seed, scenario_content_hash
from chaos_librarian.determinism.trace import TraceRecorder

__all__ = [
    "Clock",
    "IdAllocator",
    "IdAllocatorOverflow",
    "RngStreams",
    "TraceRecorder",
    "format_duration_human",
    "format_duration_json",
    "resolve_seed",
    "scenario_content_hash",
]
```

- [ ] **Step 4: Run the test, expect green**

Run: `uv run pytest tests/determinism/test_public_surface.py -v`
Expected: both tests pass.

- [ ] **Step 5: Run the full determinism test suite for a sanity check**

Run: `uv run pytest tests/determinism -v`
Expected: every test in the eight test files passes; total runtime well under 5 seconds.

- [ ] **Step 6: Run lint / type / format on the whole project**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all three exit 0.

- [ ] **Step 7: Confirm schema export drift gate stays clean**

Run: `uv run python -m chaos_librarian.schema_export --check`
Expected: exit 0 (no schema changes this sprint).

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/determinism/__init__.py tests/determinism/test_public_surface.py
git commit -m "feat(determinism): expose public surface from determinism package"
```

---

## Task 11: Docs reconciliation, full verification, and PR

**Files:**

- Modify: `CLAUDE.md`

`docs/specs/chaos-librarian-design.md` §"Sprint 2" already lists "duration string *formatters*" (from the Sprint 1 PR) and doesn't need a content edit. No new `docs/contract/` files — the determinism module is internal.

- [ ] **Step 1: Update the stale CLAUDE.md "current open" line**

Edit `CLAUDE.md`. Find this line (it's the one in the "Project state" section that lists issues #1–#4):

```text
Active per-sprint implementation plans live at `docs/superpowers/plans/`. Deferred work is tracked as GitHub issues — current open: #1 (ExecutionTraceEntry discriminated-union refinement), #2 (CLI Path validation hardening), #3 (uv_build version pin), #4 (plan documentation maintenance).
```

Replace with:

```text
Active per-sprint implementation plans live at `docs/superpowers/plans/`. No deferred-work issues are currently open.
```

(Confirm via `gh issue list --state open --limit 5` before committing — the spec asserts all four issues are closed; if a new one has been filed since, the engineer should update the wording to reflect actual state rather than blindly applying this edit.)

- [ ] **Step 2: Run the complete exit-criteria suite**

These commands together are the Sprint 2 spec's exit criteria. They must all pass before opening the PR.

Run each, expecting exit 0 on every one:

```bash
uv run pytest
uv run ty check src tests
uv run ruff check .
uv run ruff format --check .
uv run python -m chaos_librarian.schema_export --check
```

- [ ] **Step 3: Smoke-import the exact block from the spec exit criteria**

Run: `uv run python -c "$(cat <<'PY'
from chaos_librarian.determinism import (
    Clock, IdAllocator, RngStreams, TraceRecorder,
    resolve_seed, scenario_content_hash,
    format_duration_human, format_duration_json,
)
rec = TraceRecorder()
rng = RngStreams(resolved_seed=42, recorder=rec)
assert rng.stream("video_source") is rng.stream("video_source")
print("ok")
PY
)"`
Expected: prints `ok`, exit 0.

- [ ] **Step 4: Confirm the property suite still completes well under 5 seconds**

Run: `uv run pytest tests/determinism --durations=10`
Expected: total wall time under 5 seconds; the `--durations=10` summary shows no single test taking more than ~1 second.

- [ ] **Step 5: Run prek hooks if installed**

Run: `prek run --all-files`
Expected: every hook exits 0. (If `prek` is not installed locally, skip; CI will run the equivalent checks.)

- [ ] **Step 6: Commit the docs reconciliation**

```bash
git add CLAUDE.md
git commit -m "docs(sprint-2): reconcile project-state notes after Sprint 2 work"
```

- [ ] **Step 7: Push the branch and open the PR**

Run: `git push -u origin feat/sprint-2`

Then open the PR. Use the existing PR template style (look at `gh pr view <recent-sprint-pr>` for tone):

```bash
gh pr create --title "feat(sprint-2): deterministic core (RNG / IDs / clock / trace)" --body "$(cat <<'EOF'
## Summary

- Adds `chaos_librarian.determinism` package: `RngStreams`, `IdAllocator`, `Clock`, `TraceRecorder`, `resolve_seed`, `scenario_content_hash`, `format_duration_human`, `format_duration_json`.
- Sprint 2 ships no CLI, no I/O, no schema changes — every module is a pure primitive plus property tests proving the determinism contract.
- Builds on the Sprint 2 design spec (`docs/superpowers/specs/2026-05-17-sprint-2-deterministic-core-design.md`) and the Codex adversarial-review follow-up.

## Test plan

- [ ] `uv run pytest` — full suite green (existing Sprint 0/1 + new determinism tests).
- [ ] `uv run ty check src tests` clean.
- [ ] `uv run ruff check . && uv run ruff format --check .` clean.
- [ ] `uv run python -m chaos_librarian.schema_export --check` clean (no schema changes).
- [ ] Determinism property suite (`tests/determinism/test_*_properties.py`) completes under 5 seconds.
- [ ] Direct-import smoke from a fresh Python shell:
      `from chaos_librarian.determinism import Clock, IdAllocator, RngStreams, TraceRecorder, ...`

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

Expected: PR URL printed; CI starts on push.

- [ ] **Step 8: Wait for CI green**

Run: `gh pr checks --watch`
Expected: every workflow exits success. If any check fails, follow the project's "Issue fixes land on active sprint branch" rule from memory — fix inline on `feat/sprint-2`, no fix branch.

---

## Summary of Determinism Guarantees → Tests Mapping

This matches the spec's "Determinism Guarantees" section. Use this as a sanity check before merging — every guarantee must have at least one passing test.

| Guarantee | Test file(s) |
|-----------|--------------|
| 1. Same seed → same RNG draws | `test_rng.py::TestSameSeedSameDraws`, `test_rng_properties.py` |
| 2. Stream independence | `test_rng_properties.py`, `test_rng.py::TestSubSeedDivergesByName` |
| 3. Allocator order-stability | `test_ids.py::TestNamespaceIndependence`, `test_ids_properties.py` |
| 4. Allocator overflow is loud | `test_ids.py::TestAllocatorOverflow` |
| 5. Clock monotonicity | `test_clock.py::TestClockMonotonic` |
| 6. Duration parse/format round-trip | `test_clock_properties.py`, `test_clock.py::TestParseFormatRoundTripExamples` |
| 7. Trace recorder fidelity + immutable snapshot | `test_trace.py`, `test_ids.py::TestAllocatorTraceFidelity`, `test_rng.py::TestTraceFidelity` |

---

## Out of Scope (Sprint 3+)

Do **not** add any of these in this PR — they belong in later sprints per the design spec:

- Scenario consumption / timeline walking — Sprint 3 (`plan`).
- Replay-bundle assembly and persistence — Sprint 3.
- Wall-clock-mode differentiation — Sprint 8 (`run`).
- Materializer subprocess wiring — Sprint 5. (`record_materializer` is *declared* but has no Sprint 2 caller.)
- Any CLI command changes. The eight stub commands stay stubs.
- Configuration / strictness flags.
- Any new docs under `docs/contract/`.
- Any move or rename of the existing top-level `chaos_librarian.clock` parser.
