# Sprint 2 — Deterministic Core

Status: design accepted, implementation plan pending.
Branch: `feat/sprint-2`.
Related: [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md) §"Sprint 2".

## Purpose

Sprint 2 ships the internal `determinism` building blocks that Sprints 3
(`plan`), 4 (`step` / `replay`), and 8 (wall-clock `run`) will compose into
actual runs: a seeded RNG with per-stream sub-seeds, a monotonic ID
allocator, a simple logical clock, an execution-trace recorder, and the
duration *formatters* that pair with Sprint 1's `parse_duration`. Sprint 2
adds no CLI surface and no I/O — every module is a pure primitive plus
property tests proving the determinism contract.

The sprint is load-bearing for the project's "deterministic replay comes
first" design principle: Sprint 3 plan-only bundles are required to be
bit-identical for the same scenario + seed, and that guarantee bottoms out
in the RNG / allocator / clock / trace shipped here.

## Scope

### In Sprint 2

- `RngStreams` — seed-derived, per-stream `random.Random` factory using
  `sha256(seed || stream_name)`. Cached per name. Every draw appends an
  `RngTraceEntry` to the recorder.
- `IdAllocator` — monotonic per-namespace counters returning
  `version_0001`, `location_0001`, `sidecar_0001`, `mutation_0001`. Every
  allocation appends an `AllocTraceEntry` to the recorder.
- `Clock` — `current_ns: int` + `advance(delta_ns)` + `now()` + `set_to(t)`;
  no scheduling, no wall-clock awareness. Monotonic-only.
- `TraceRecorder` — append-only buffer of `ExecutionTraceEntry` values.
  Constructor-injected into `RngStreams` and `IdAllocator`. Closed API
  (no third-party append path).
- `resolve_seed(int | "random") -> int` and
  `scenario_content_hash(bytes) -> str` — runtime helpers that Sprint 3
  uses to populate `replay_bundle.resolved_seed` and to derive the
  plan-only `run_id` via the existing
  `contract.replay_bundle.compute_plan_only_run_id`.
- `format_duration_human(ns: int) -> str` (`"1m30.250s"`) and
  `format_duration_json(ns: int) -> int` — paired with Sprint 1's
  `parse_duration`. The formatters live in `determinism/clock.py`; the
  Sprint 1 parser stays at top-level `chaos_librarian.clock`.
- Property tests (via `hypothesis`) for: same-seed determinism, stream
  independence, allocator-call interleaving, parse/format round-trip.

### Out of Sprint 2 (deferred)

- Scenario consumption / timeline walking — Sprint 3 (`plan`).
- Replay-bundle assembly and persistence — Sprint 3.
- Wall-clock-mode differentiation — Sprint 8 (`run`).
- Materializer subprocess wiring — Sprint 5.
  `TraceRecorder.record_materializer` is declared in Sprint 2 so the
  recorder API is closed, but nothing in Sprint 2 calls it.
- Any CLI command changes. The eight remaining stub commands stay stubs.
- Configuration / strictness flags. None of the Sprint 2 modules read
  configuration.

## Architecture

```text
src/chaos_librarian/
  determinism/
    __init__.py        # public surface (re-exports)
    rng.py             # RngStreams
    ids.py             # IdAllocator, IdAllocatorOverflow
    clock.py           # Clock + format_duration_human + format_duration_json
    trace.py           # TraceRecorder
    seeding.py         # resolve_seed, scenario_content_hash
```

The existing top-level `chaos_librarian.clock` (Sprint 1's `parse_duration`)
stays where it is — it is already a consumer-facing parser shared with
`validation.semantic`. The Sprint 2 formatters live alongside the `Clock`
object in `determinism/clock.py`; the public re-export from
`determinism/__init__.py` is what downstream sprints import. Sprint 2 does
not move or rename the existing parser.

Each module is independently testable. There is no cross-module state — a
`TraceRecorder` instance is the only object passed between `RngStreams` and
`IdAllocator`, and Sprint 2 never constructs a "session" or "context"
object that owns them jointly. Sprint 3 is the first consumer that holds
all five together inside a run.

## Component Contracts

### `determinism/seeding.py`

```python
def resolve_seed(declared: int | Literal["random"]) -> int: ...
def scenario_content_hash(scenario_yaml_bytes: bytes) -> str: ...
```

- `resolve_seed(int)` returns the int verbatim.
- `resolve_seed("random")` draws 64 bits from `secrets.randbits(64)` and
  returns the resulting int. Sprint 3 records the result as
  `replay_bundle.resolved_seed` so a `seed: random` scenario is still
  replayable.
- `scenario_content_hash(bytes)` returns the lowercase hex sha256 digest
  of the verbatim scenario YAML bytes (the same bytes that Sprint 3 will
  store as `replay_bundle.scenario`). This is the input to
  `contract.replay_bundle.compute_plan_only_run_id`.
- The hash function lives here, not in `contract/`, because it is a
  runtime helper rather than a schema. The contract module only knows the
  hash algorithm by name through the docstring on
  `compute_plan_only_run_id`.

### `determinism/rng.py`

```python
class RngStream:
    """Per-stream recording RNG. Wraps a private random.Random; not a subclass."""

    def random(self) -> float: ...
    def randint(self, a: int, b: int) -> int: ...
    def randrange(self, start: int, stop: int | None = None, step: int = 1) -> int: ...
    def randbytes(self, n: int) -> bytes: ...
    def choice(self, seq: Sequence[T]) -> T: ...
    def choices(self, seq: Sequence[T], k: int = 1) -> list[T]: ...
    def sample(self, seq: Sequence[T], k: int) -> list[T]: ...
    def shuffle(self, x: list[T]) -> None: ...
    def uniform(self, a: float, b: float) -> float: ...
    def gauss(self, mu: float, sigma: float) -> float: ...


class RngStreams:
    def __init__(self, resolved_seed: int, recorder: TraceRecorder) -> None: ...
    def stream(self, name: str) -> RngStream: ...
```

- `stream(name)` returns a cached `RngStream` whose backing
  `random.Random` is seeded with the integer formed by the first 8 bytes
  of `sha256(f"{resolved_seed}/{name}".encode()).digest()`. Subsequent
  calls with the same name return the same instance.
- `RngStream` is a thin wrapper, NOT a subclass of `random.Random`. This
  is deliberate: subclassing leaks `random.Random`'s undocumented
  internals (e.g., `_randbelow`, direct `random()` calls from inside
  `randint`) and creates a nested-recording problem when overridden
  methods call each other. The wrapper holds one private `random.Random`
  instance, delegates each documented draw method to it, and records
  exactly one `RngTraceEntry(kind="rng", stream=<name>, value=repr(v))`
  per user-facing call.
- The wrapper exposes exactly the methods listed in the contract above.
  Methods not in that list are out of contract for Sprint 2; consumers
  that need a new primitive add it explicitly with a trace hook in a
  later sprint.
- `value` is `repr(returned_value)` so floats, tuples, and byte strings
  round-trip in the trace as their canonical Python repr; consumers
  comparing traces compare strings byte-for-byte.
- Stream names are stable contract strings. Sprint 2 introduces no
  consumers yet, but reserves a documented namespace for upcoming
  sprints:

  | Stream name              | Sprint that begins consuming |
  |--------------------------|------------------------------|
  | `id_alloc`               | Reserved; counter-only today |
  | `video_source`           | Sprint 5 (content sources)   |
  | `audio_source`           | Sprint 5                     |
  | `subtitle_source`        | Sprint 5                     |
  | `metadata`               | Sprint 5                     |
  | `file_layout`            | Sprint 6 (filesystem mutations) |
  | `materializer_jitter`    | Sprint 5/6                   |

  Adding a stream name is non-breaking. Renaming or removing one is a
  contract break in the same sense that journal schema names are.

- Stream independence is the load-bearing property: adding a new stream
  name in a later sprint cannot perturb the byte stream of any existing
  stream, because each name's sub-seed is computed independently from the
  resolved seed via sha256.

### `determinism/ids.py`

```python
class IdAllocatorOverflow(RuntimeError): ...

class IdAllocator:
    def __init__(self, recorder: TraceRecorder) -> None: ...
    def next_version_id(self) -> str: ...
    def next_location_id(self) -> str: ...
    def next_sidecar_id(self) -> str: ...
    def next_mutation_id(self) -> str: ...
```

- Each method bumps a private per-namespace counter (starting at 1) and
  returns `f"{namespace}_{counter:04d}"` — `version_0001`,
  `location_0001`, `sidecar_0001`, `mutation_0001`.
- Each allocation appends `AllocTraceEntry(kind="alloc", stream=<namespace>,
  value=<allocated_id>)` to the recorder.
- Width is 4 digits. The default scenario pack is bounded to under 50 MB
  total materialized size, and no realistic V1 scenario approaches 10,000
  allocations in a single namespace. When the counter would advance past
  9,999, the next call raises `IdAllocatorOverflow` rather than silently
  producing `version_10000` and breaking lexicographic sort. This is a
  named, tested failure mode — not a silent expansion.
- Namespaces are independent: bumping `next_version_id` does not affect
  the counter behind `next_location_id`.
- No randomness is consumed today. The `id_alloc` RNG stream is reserved
  for any future allocator that needs randomized choice (e.g., picking
  among legal location paths); current allocator is purely counter-based.

### `determinism/clock.py`

```python
@dataclass
class Clock:
    current_ns: int = 0

    def advance(self, delta_ns: int) -> int: ...   # returns new current_ns
    def now(self) -> int: ...
    def set_to(self, target_ns: int) -> None: ...

def format_duration_human(ns: int) -> str: ...
def format_duration_json(ns: int) -> int: ...
```

- `advance(delta_ns)` requires `delta_ns >= 0` — raises `ValueError`
  otherwise. The clock only moves forward; this is enforced at the
  primitive layer so Sprint 3 cannot accidentally reorder events.
- `set_to(target_ns)` requires `target_ns >= current_ns` — same reason.
  Sprint 3 will use it to jump the clock to the next event's `at:`.
- `now()` returns `current_ns` (added so callers do not reach for the
  dataclass field directly; preserves a single read API).
- `format_duration_human(0)` returns `"0s"`.
  `format_duration_human(90_250_000_000)` returns `"1m30.250s"`. Uses
  h/m/s/ms decomposition; sub-millisecond residue is rendered as a
  trailing microsecond or nanosecond suffix (e.g., `"1m30.250s500us"`,
  `"1m30.250s500us123ns"`) only when the residue is nonzero. This
  matches the design-spec time-model wording while staying
  human-readable.
- `format_duration_json(ns)` is conceptually `int(ns)` with a `TypeError`
  guard for non-int input. It exists as a named function so every JSON
  emission site goes through it, keeping grep-ability and leaving room to
  swap the representation later (e.g., to a string-with-units) without
  touching every call site.
- Round-trip guarantee:
  `parse_duration(format_duration_human(ns)) == ns` for every `ns >= 0`
  representable as a clean h/m/s/ms sum (no us/ns residue). For inputs
  with sub-ms residue the round-trip is intentionally partial — the
  formatter still emits the µs suffix for debuggability, but the parser
  does not need to consume it because no scenario writes durations in µs.

### `determinism/trace.py`

```python
class TraceRecorder:
    def __init__(self) -> None: ...
    def record_rng(self, stream: str, value: str) -> None: ...
    def record_alloc(self, stream: str, value: str) -> None: ...
    def record_materializer(self, stream: str, value: str, exit_code: int) -> None: ...
    def entries(self) -> list[ExecutionTraceEntry]: ...
    def __len__(self) -> int: ...
```

- Backing storage is a private `list[ExecutionTraceEntry]`. Each `record_*`
  method constructs the right subclass
  (`RngTraceEntry` / `AllocTraceEntry` / `MaterializerTraceEntry` from
  `contract.replay_bundle`) so callers never import the discriminated
  union types directly.
- `entries()` returns the internal list — not a copy. Sprint 3's
  plan-only assembler treats it as a snapshot at end-of-run; mutating
  the returned list afterwards is out of contract.
- `record_materializer` is declared now but no Sprint 2 caller exists.
  Shipping it closes the recorder API so Sprint 5's materializer just
  calls it.
- Trace entries are recorded in call order. The recorder does not sort,
  filter, or dedupe.

### Public surface (`determinism/__init__.py`)

```python
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

Downstream sprints import from `chaos_librarian.determinism`. The
submodules are implementation detail.

## Dependencies

New dev-dependency: `hypothesis` (property testing). Added to
`[dependency-groups] dev` in `pyproject.toml` (PEP 735 style, matching
the existing `pytest`/`ruff`/`ty` declarations). It is the standard
Python property-testing library and the design spec explicitly calls for
property tests, so the dependency justifies itself. No new runtime
dependencies.

The `hypothesis` examples database directory (`.hypothesis/`) is added
to `.gitignore` (not currently covered by the existing entries).

## Determinism Guarantees

These are the load-bearing contracts that downstream sprints rely on.
Each guarantee has at least one dedicated test (see "Test Strategy").

1. **Same seed → same RNG draws.** For any fixed `resolved_seed` and
   fixed sequence of `(stream_name, method, args)` calls, draws are
   bit-identical across runs and across Python processes on the same
   Python 3.13 build.
2. **Stream independence.** Drawing from stream A any number of times
   does not change values produced by stream B. Adding a new stream name
   cannot perturb existing streams. This is the property that lets
   Sprints 5/6/7 add content sources without invalidating earlier
   fixtures.
3. **Allocator order-stability.** For any fixed sequence of
   `next_*_id()` calls across the four namespaces, the returned IDs are
   bit-identical across runs. Each namespace counter is independent.
4. **Allocator overflow is loud.** The 10,000th call into a namespace
   raises `IdAllocatorOverflow` with a clear message identifying the
   namespace.
5. **Clock monotonicity.** `advance(d)` with `d < 0` raises;
   `set_to(t)` with `t < current_ns` raises. No code path can move the
   clock backward.
6. **Duration parse/format round-trip.** For every `ns >= 0`
   representable as a clean h/m/s/ms sum,
   `parse_duration(format_duration_human(ns)) == ns`.
7. **Trace recorder fidelity.** Every RNG draw and every allocation
   produces exactly one trace entry, in call order, with the right
   `kind` and `stream`. The recorder is the only writer; nothing else
   appends to the trace.

## Test Strategy

```text
tests/
  determinism/
    __init__.py
    test_seeding.py              # resolve_seed branches, content-hash stability
    test_rng.py                  # determinism, RecordingRandom proxy, trace fidelity
    test_rng_properties.py       # hypothesis: stream independence, same-seed equivalence
    test_ids.py                  # counter behavior, overflow, namespace independence
    test_ids_properties.py       # hypothesis: interleaved call sequences -> stable IDs
    test_clock.py                # monotonicity, formatter edges
    test_clock_properties.py     # hypothesis: parse(format_human(ns)) == ns
    test_trace.py                # ordering, kind dispatch, materializer record
```

Property tests use `@settings(max_examples=200, deadline=None)` to keep
CI under 5 seconds for the suite and to avoid hypothesis flakiness from
shared-runner timing. The three load-bearing property tests:

- **Stream independence** (`test_rng_properties.py`) — given two distinct
  stream names and arbitrary call sequences, draws on stream B are
  identical whether or not stream A was drawn first. Strategy: draw a
  small `st.lists` of `(method, args)` tuples; compare two recorders
  built with and without intervening A draws.
- **Allocator interleaving** (`test_ids_properties.py`) — given an
  arbitrary sequence of `next_*_id()` calls drawn from the four
  namespaces, the resulting ID list is determined entirely by
  per-namespace counts. Strategy: `st.lists(st.sampled_from(["version",
  "location", "sidecar", "mutation"]))`, then compare against a
  hand-rolled per-namespace counter.
- **Duration round-trip** (`test_clock_properties.py`) —
  `parse_duration(format_duration_human(ns)) == ns` for `ns` drawn from
  clean h/m/s/ms sums. Strategy: compose `ns` from
  `st.integers(min_value=0, max_value=23)` (hours),
  `st.integers(min_value=0, max_value=59)` (minutes/seconds),
  `st.integers(min_value=0, max_value=999)` (milliseconds), with the sum
  capped well below `i64_max`.

Hand-rolled (non-property) tests cover trace fidelity, overflow,
edge-case formatting, and the `resolve_seed("random")` smoke path. Each
test follows CLAUDE.md Rule 9 — the WHY goes in the docstring (e.g.,
"stream independence keeps Sprint 5 from invalidating Sprint 3
fixtures").

## CLI Wiring

None. Sprint 2 ships no CLI changes. The eight stub commands
(`plan`, `materialize`, `run`, `step`, `replay`, `inspect`,
`capabilities`, `clean`) remain stubs that exit with code 1.

## Exit Criteria

The PR is mergeable when:

- `uv run pytest` passes — every new test file green; existing Sprint 0/1
  tests still green.
- `uv run ty check src tests` clean.
- `uv run ruff check . && uv run ruff format --check .` clean.
- `uv run python -m chaos_librarian.schema_export --check` clean (no
  schema changes expected this sprint).
- The property-test suite completes in under 5 seconds on CI.
- A direct-import smoke from a fresh Python shell works:

  ```python
  from chaos_librarian.determinism import (
      Clock, IdAllocator, RngStreams, TraceRecorder,
      resolve_seed, scenario_content_hash,
      format_duration_human, format_duration_json,
  )
  rec = TraceRecorder()
  rng = RngStreams(resolved_seed=42, recorder=rec)
  # Cached stream returns identical instance.
  assert rng.stream("video_source") is rng.stream("video_source")
  ```

- CI green on `feat/sprint-2`.

## Docs Reconciliation

In the same PR:

- `docs/specs/chaos-librarian-design.md` §"Sprint 2": no content changes
  required — the Sprint 1 PR already rewrote this section's deliverable
  list to say "duration string *formatters*" and to clarify that
  Sprint 2 consumes Sprint 1's parser.
- `CLAUDE.md` §"Project state": update the stale "deferred work is
  tracked as GitHub issues — current open: #1, #2, #3, #4" line. All
  four issues are closed; replace with an accurate statement (no open
  deferred-work issues at time of writing).
- `CLAUDE.md` §"Project state": the sentence about `validate` being
  implemented and "the other eight CLI commands are stubs" stays
  accurate — Sprint 2 ships no CLI.
- No new docs under `docs/contract/`. The determinism module is
  internal; consumers see only the trace shape, which is already
  documented through `contract/replay_bundle.py`.

## Non-Goals

- No CLI changes.
- No scenario consumption inside the allocator.
- No replay-bundle assembly or persistence (Sprint 3).
- No wall-clock awareness (Sprint 8).
- No materializer subprocess wiring (Sprint 5).
- No `--strict` or severity-tuning flags; none of the Sprint 2 modules
  read configuration.
- No relocation of the existing top-level `chaos_librarian.clock`
  parser. Sprint 1's import sites stay untouched.
- No expansion of the timeline event set or the `ExecutionTraceEntry`
  union — both are frozen.
