# Sprint 4 — Step Mode, Inspect, Clean, Replay, Reports

**Status:** design, pending implementation plan.
**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md) — §"Step Mode", §"Sprint 4", §"Filesystem Safety", §"Reports", §"Replay Bundle".
**Predecessor:** Sprint 3 (`feat/sprint-3`, merged in #9) shipped `plan` end-to-end plus the engine, writer, and `replay_plan_bundle` helper this sprint wraps in CLI form.
**Target branch:** `feat/sprint-4`.

## Goal

Complete the plan-only CLI surface. Sprint 3 wired `plan`; Sprint 4 wires the remaining four commands that operate on or against a plan-only fixture (`step`, `inspect`, `clean`, `replay`), extends `plan` with a `--steps N` flag, and ships the per-asset / per-work / per-variant / per-bundle reports that adapter authors need.

Sprint 4 closes the "stepping and replay" half of the design doc's CLI contract. After this sprint the remaining stubs (`materialize`, `run`, `capabilities`) depend on the materializer landing in Sprint 5+.

## Design Decisions Resolved In Brainstorming

The design doc leaves several Sprint-4 specifics open. Each is resolved below; flag if you disagree before the plan is written.

1. **Step fixture preparation.** `plan` gains `--steps N`. `plan --out X` (no `--steps`) runs the timeline to completion (Sprint 3 behavior, byte-identical). `plan --out X --steps 0` writes a complete fixture with an empty journal and `manifest.current = initial`. `plan --out X --steps K` (0 < K < timeline-length) writes a partial fixture. `step run-dir --next [N]` advances from wherever the fixture sits.

2. **Step state recovery.** Stateless: each `step --next` re-derives WorldState by re-running the engine from `t=0` and stopping when the journal-entry count matches what is already on disk. No new on-disk state, no schema concern, no drift risk. Plan-only is fast enough that the O(events_already_applied) cost is negligible for V1 scenarios.

3. **Replay divergence semantics.** `replay` performs two checks. First, `replay_plan_bundle()` raises `ReplayIntegrityError` when `bundle.scenario` or `bundle.resolved_seed` no longer matches `bundle.run_id`; exit code 6. Second, after writing the new fixture to `--out`, `replay` byte-compares against either an explicit `--against original-dir` or, if absent, against the bundle's parent directory when that parent is a valid sentinel'd fixture whose `run_id` matches the bundle. Any byte-level mismatch exits 6 with a structured diff.

4. **Report scope (plan-only).** Reports are derived from manifest + journal data only — no content hashes, no probed media facts (those land with Sprint 5's materializer). Per-asset: `initial` snapshot, ordered `history` (journal entries targeting the asset), `current` snapshot or `None` if deleted. Per-work/variant/bundle: member id lists. The schema is forward-compatible: Sprint 5+ adds `content_hash` and probed facts as new optional fields under `schema_version: 1`.

5. **Reports are a versioned contract.** Four Pydantic models in `chaos_librarian.contract.reports` export to `schemas/asset-report.schema.json`, `work-report.schema.json`, `variant-report.schema.json`, `bundle-report.schema.json`. The Sprint 0 drift gate covers them.

6. **Reports generation timing.** Always on. Both `plan` and `step` write `reports/` as part of fixture emission. No flag to remember; fixtures are always "complete" for adapter consumers.

7. **`inspect` shape.** Single JSON summary block — `run_id`, `scenario_id`, `schema_version`, `execution_mode`, `journal_entries`, `steps_remaining`, manifest counts (works/variants/bundles/assets/sidecars), `created_at`. Concise enough to pipe to `jq`. Detailed per-entity views live in `reports/`.

8. **`step --next` arity.** `--next` accepts an optional positive integer (default 1). `step run-dir --next` advances one event; `step run-dir --next 5` advances five. `--next 0` and negative values exit 2 (usage error). When the timeline is exhausted, JSON output emits `{"done": true, "steps_applied": <0_or_partial>, "steps_remaining": 0}` and exits 0 cleanly — running out of events is not an error condition.

9. **`clean` success output.** Human: `clean: removed <abs path> (run_id <uuid>)`. JSON: `{"removed": "<abs path>", "run_id": "<uuid>"}`. Sentinel violations exit 7 with `{"error": "sentinel_invalid", "reason": "..."}`.

10. **Sentinel re-entry.** `step`, `inspect`, and `clean` each verify `<run-dir>/.chaos-librarian-run` parses as `RunSentinel` before any read or mutation. This is the "re-use a sentinel'd directory" path Sprint 3 deferred. `step` adds a second check: it recomputes the plan-only `run_id` from the on-disk `scenario.yaml` + `bundle.resolved_seed` and compares to `bundle.run_id`; mismatch exits 7 as `scenario_tampered`.

11. **`divergence.schema.json`.** Not added in Sprint 4. Sprint 9 owns it because its scope (app-vs-oracle comparison) is broader than Sprint 4's fixture-vs-fixture diff. Sprint 4 emits the same shape Sprint 9 will formalize, but does not export a schema artifact for it.

## Architecture

Single PR on `feat/sprint-4`. Six independently testable units extend Sprint 3's engine + CLI without changing any existing artifact schema.

### New modules

```
src/chaos_librarian/contract/
  reports.py            # Pydantic: AssetReport, WorkReport, VariantReport, BundleReport
                        # plus the small leaf types (AssetSnapshot, AssetHistoryEntry)

src/chaos_librarian/engine/
  reports.py            # build_report_set(initial, current, journal) -> ReportSet (pure)
  step.py               # step_fixture(run_dir, n_events) -> StepResult (pure; reads I/O,
                        # returns in-memory result; writing is the CLI's responsibility)
  diff.py               # compare_fixtures(left_dir, right_dir) -> FixtureDiff
```

### Modified modules

```
src/chaos_librarian/engine/
  plan.py               # run_plan gains steps_limit: int | None = None
  writer.py             # write_fixture also emits reports/; new append_step() for
                        # incremental updates from step
  __init__.py           # re-export step_fixture, build_report_set, compare_fixtures

src/chaos_librarian/cli/app.py
                        # plan gains --steps; step/inspect/clean/replay get real bodies

src/chaos_librarian/schema_export.py
                        # adds the four report schemas to the drift gate
```

### Generated artifacts

```
schemas/
  asset-report.schema.json
  work-report.schema.json
  variant-report.schema.json
  bundle-report.schema.json
```

### Tests

```
tests/contract/
  test_reports.py            # round-trip + extra=forbid

tests/engine/
  test_reports.py            # build_report_set on synthetic inputs
  test_step.py               # cursor recovery, tampered scenario, journal corruption
  test_diff.py               # byte_diff / missing_in_left / missing_in_right
  test_plan_steps.py         # plan --steps 0, --steps K, --steps full == Sprint 3 baseline
  test_plan_e2e.py           # EXTEND: step-vs-plan journal equivalence; replay round-trip

tests/cli/
  test_step.py
  test_inspect.py
  test_clean.py
  test_replay.py
```

### Not touched

- `src/chaos_librarian/contract/` (other than the new `reports.py`) — no schema changes to scenario, journal, manifest, replay bundle, validation, materialization, or run sentinel.
- `src/chaos_librarian/determinism/` — Sprint 2 surface stays exactly as is.
- `src/chaos_librarian/validation/` — no new validation rules. Sprint 3's lifecycle pass already covers everything `step` exercises.
- Other CLI commands (`materialize`, `run`, `capabilities`) — still stubs exiting 1.

## Components

### `contract/reports.py` — schema models

```python
class AssetSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location_path: str | None         # None if asset has been deleted
    version_id: str
    version_index: int

class AssetHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    logical_time_ns: int
    event_id: str
    action: str
    state_delta: dict[str, object]    # verbatim slice from the journal entry

class AssetReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    asset_id: str
    initial: AssetSnapshot
    history: list[AssetHistoryEntry]
    current: AssetSnapshot | None     # None after delete_file

class WorkReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    work_id: str
    title: str
    variant_ids: list[str]
    asset_ids: list[str]              # transitive through variants

class VariantReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    variant_id: str
    work_id: str
    label: str
    bundle_id: str
    asset_ids: list[str]

class BundleReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1]
    bundle_id: str
    variant_id: str
    asset_ids: list[str]
    sidecar_ids: list[str]            # currently bound sidecars only
```

All models use `extra="forbid"`. Forward compatibility is preserved by Pydantic's normal behavior: new optional fields can be added under `schema_version: 1` without breaking existing readers, but no field may be removed or retyped.

### `engine/reports.py` — `build_report_set`

```python
@dataclass(frozen=True)
class ReportSet:
    assets: tuple[AssetReport, ...]
    works: tuple[WorkReport, ...]
    variants: tuple[VariantReport, ...]
    bundles: tuple[BundleReport, ...]


def build_report_set(
    *,
    initial: Manifest,
    current: Manifest,
    journal: Iterable[JournalEntry],
) -> ReportSet: ...
```

Pure function. No I/O. Called from both `run_plan` (after the timeline loop) and `step_fixture` (after each advance). Iteration order is stable (lexicographic on id) so report files are bit-identical for the same logical state.

History is derived by filtering journal entries on `target_ids` membership. `initial` and `current` snapshots are pulled from the respective manifests by `asset_id`. A deleted asset has `current=None`; its `history` still includes the `delete_file` entry.

### `engine/step.py` — `step_fixture`

```python
@dataclass(frozen=True)
class StepResult:
    new_entries: tuple[JournalEntry, ...]
    new_current_manifest: Manifest
    new_report_set: ReportSet
    steps_applied: int            # resolved events applied this call
    steps_remaining: int          # resolved events still to apply after this call
    done: bool                    # steps_remaining == 0


def step_fixture(run_dir: Path, n_events: int) -> StepResult: ...
```

Algorithm:

1. Verify `<run-dir>/.chaos-librarian-run` parses as `RunSentinel` — exit 7 on failure (raised as `SentinelInvalidError`; CLI maps to exit 7).
2. Read `scenario.yaml` (bytes), `replay.json` (as `PlanOnlyReplayBundle`), `journal.jsonl` (parse each line as `JournalEntry`).
3. Recompute `compute_plan_only_run_id(sha256(scenario_bytes).hex(), bundle.resolved_seed)`; compare to `bundle.run_id`. Mismatch → `ScenarioTamperedError`, exit 7.
4. Build a fresh `WorldState` from the scenario (Sprint 3's `build_initial_state`); set up a fresh `IdAllocator` + `TraceRecorder`.
5. Walk `resolve_timeline(scenario)` in order. For each resolved event, call `apply_event` and count the journal entries it produces. Stop replaying when the cumulative count equals `len(existing_journal)`. The state at that point is the cursor.
6. Continue applying up to `n_events` more resolved events, collecting their new journal entries.
7. Build the new `current_manifest` from `state.to_manifest()` and the new `ReportSet` from `build_report_set(initial, current, full_journal)`.
8. Return `StepResult` — the function does not write.

Cursor-recovery cost is O(events_already_applied). Step counts resolved events, not journal entries, so a slow_copy pair counts as one step for `--next` purposes even though it adds two journal lines.

### `engine/diff.py` — `compare_fixtures`

```python
@dataclass(frozen=True)
class FixtureFileDiff:
    path: str                          # relative to fixture root
    kind: Literal["byte_diff", "missing_in_left", "missing_in_right"]
    left_bytes: int | None
    right_bytes: int | None
    first_diff_line: int | None        # JSON / JSONL files only
    preview_left: str | None
    preview_right: str | None


@dataclass(frozen=True)
class FixtureDiff:
    left_dir: Path
    right_dir: Path
    files: tuple[FixtureFileDiff, ...]

    def is_clean(self) -> bool: return not self.files
```

Walks both directories, treats `.chaos-librarian-run/created_at` as ignorable (plan-only omits it anyway), and compares every other file by exact byte content. For JSON / JSONL files, the first differing line is surfaced with a short preview; for other files only byte counts are reported. No third-party diff library; the project keeps zero new runtime dependencies.

### `engine/plan.py` — `steps_limit` extension

```python
def run_plan(
    *,
    run_input: RunInput,
    validation_report: ValidationReport,
    resolved_seed_override: int | None = None,
    steps_limit: int | None = None,    # NEW; None = full timeline
) -> PlanArtifacts: ...
```

Behavior unchanged when `steps_limit is None`. When set, the timeline loop stops after `steps_limit` resolved events have been applied (slow_copy_start counts as one step even though it does not commit). The resulting `journal`, `current_manifest`, and `replay_bundle.execution_trace` reflect only the applied prefix; the `replay_bundle.run_id` is still the deterministic UUIDv5 (which depends only on `scenario_content_hash` and `resolved_seed`, not on event count). The `validation_report` is unchanged.

`steps_limit=0` is a valid input that produces an empty journal and `current_manifest == initial_manifest`.

### `engine/writer.py` — `reports/` emission and `append_step`

`write_fixture` extends to also stage `reports/{assets,works,variants,bundles}/<id>.json` before the atomic top-level rename. Output is bit-identical: every file is `model_dump_json(indent=2, by_alias=True, exclude_none=True) + "\n"`.

```python
def append_step(
    run_dir: Path,
    new_entries: Iterable[JournalEntry],
    new_current_manifest: Manifest,
    new_report_set: ReportSet,
) -> None: ...
```

Used by `step` to update an existing fixture incrementally. Algorithm:

1. Stage updated `manifest.current.json` and every report file in sibling tempfiles inside `run_dir`. Atomic `Path.replace` per file.
2. Append the new journal lines to `journal.jsonl` (no rewrite — the prior bytes are preserved).

This is not fully atomic across all files — if the process is killed between step 1 and step 2, the manifest reflects a state newer than the journal. The recovery rule, documented in the spec, is that the next `step --next` re-derives state from the journal and produces a consistent fixture. We never *write* an inconsistent fixture on purpose, but a partially-completed step is recoverable. Full atomicity is a non-goal for V1; `step` is an offline-test tool, not a daemon.

### `cli/app.py` — five command bodies

**`plan`** gains:

```python
steps: Annotated[int | None, typer.Option("--steps", min=0)] = None
```

passed through as `steps_limit=steps` to `run_plan`. Negative values rejected by Typer's `min=0`; the CLI exits 2 on invalid usage.

**`step`** — full body:

```python
@app.command()
def step(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    next_count: Annotated[int, typer.Option("--next", min=1)] = 1,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    try:
        result = step_fixture(run_dir, n_events=next_count)
    except SentinelInvalidError as exc:
        _emit_sentinel_error(exc, json_output=json_output); raise typer.Exit(7)
    except ScenarioTamperedError as exc:
        _emit_tampered_error(exc, json_output=json_output); raise typer.Exit(7)
    except JournalCorruptError as exc:
        _emit_corruption_error(exc, json_output=json_output); raise typer.Exit(1)

    append_step(run_dir,
                result.new_entries,
                result.new_current_manifest,
                result.new_report_set)

    if json_output:
        typer.echo(_step_summary_json(result, run_dir))
    else:
        typer.echo(f"step: applied {result.steps_applied}, remaining {result.steps_remaining}")
```

**`inspect`**:

```python
@app.command()
def inspect(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    summary = build_inspect_summary(run_dir)  # raises SentinelInvalidError → exit 7
    if json_output:
        typer.echo(summary.model_dump_json(by_alias=True, exclude_none=True))
    else:
        _render_inspect_human(summary)
```

Summary shape:

```json
{
  "run_id": "<uuid>",
  "scenario_id": "identity-move-rename",
  "schema_version": 1,
  "execution_mode": "plan_only",
  "journal_entries": 3,
  "steps_remaining": 4,
  "counts": {"works": 1, "variants": 1, "bundles": 1, "assets": 1, "sidecars": 0},
  "created_at": null
}
```

`steps_remaining` measures resolved events still to apply (not journal lines), so it matches the user-facing count of `--next` calls remaining.

**`clean`**:

```python
@app.command()
def clean(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    sentinel = _read_sentinel_or_exit_7(run_dir, json_output=json_output)
    shutil.rmtree(run_dir)
    if json_output:
        typer.echo(json.dumps({"removed": str(run_dir.resolve()), "run_id": str(sentinel.run_id)},
                              sort_keys=True))
    else:
        typer.echo(f"clean: removed {run_dir.resolve()} (run_id {sentinel.run_id})")
```

No `--force` flag. V1 ships sentinel-only protection per the design doc.

**`replay`**:

```python
@app.command()
def replay(
    bundle: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=_validate_new_out_path)],
    against: Annotated[Path | None, typer.Option("--against", exists=True, file_okay=False)] = None,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    parsed_bundle = PlanOnlyReplayBundle.model_validate_json(bundle.read_text())
    try:
        artifacts = replay_plan_bundle(parsed_bundle)
    except ReplayIntegrityError as exc:
        _emit_integrity_error(exc, json_output=json_output); raise typer.Exit(6)

    write_fixture(out, artifacts, parsed_bundle.scenario.encode("utf-8"))

    target = against or _infer_original(bundle, parsed_bundle.run_id)
    if target is not None:
        diff = compare_fixtures(target, out)
        if not diff.is_clean():
            _emit_divergence_diff(diff, json_output=json_output); raise typer.Exit(6)

    if json_output:
        typer.echo(_replay_success_json(artifacts, out, target))
    else:
        target_note = f" (matches {target})" if target else ""
        typer.echo(f"replay: wrote {out}{target_note}")
```

`_infer_original`: returns `bundle.parent` if it contains a parseable `.chaos-librarian-run` whose `run_id` matches `parsed_bundle.run_id`. Otherwise returns `None` and no auto-compare happens.

## Data Flow

### `plan --out X --steps N`

```
validate(scenario) → run_validation
                  → run_plan(steps_limit=N)
                       → build_initial_state, resolve_timeline
                       → apply first K resolved events where K ≤ N
                       → build_report_set(initial, current, journal)
                  → write_fixture(X, artifacts, scenario_bytes)
                       → emits scenario.yaml, replay.json, manifest.initial.json,
                         manifest.current.json, journal.jsonl, validation.json,
                         .chaos-librarian-run, and reports/{assets,works,variants,bundles}/*.json
```

`--steps` omitted = full timeline. Sprint 3's bit-identical regression continues to pass.

### `step run-dir --next N`

```
verify_sentinel(run-dir)               # exit 7 on missing/malformed
verify_run_id(scenario.yaml, replay.json)  # exit 7 on scenario tampering
read journal.jsonl                     # parse each line; exit 1 on corruption
cursor = recover_state_at_cursor(scenario, resolved_seed, len(journal))
new_entries, new_state = apply_next_N(state, ids, cursor, N)
new_reports = build_report_set(initial, new_state.to_manifest(), journal + new_entries)
append_step(run-dir, new_entries, new_state.to_manifest(), new_reports)
```

JSON output:

```json
{"run_id": "<uuid>", "steps_applied": 1, "steps_remaining": 4,
 "journal_entries_total": 3, "done": false}
```

End-of-timeline: `steps_applied: 0, steps_remaining: 0, done: true`, exit 0.

### `inspect run-dir`

```
verify_sentinel(run-dir)
read replay.json (mode, run_id, scenario_id), manifest.current.json (counts),
     journal.jsonl (line count), scenario (for steps_remaining)
emit summary block
```

### `clean run-dir`

```
verify_sentinel(run-dir)
shutil.rmtree(run-dir)
emit removal line
```

### `replay bundle --against original-dir --out new-dir`

```
parse bundle as PlanOnlyReplayBundle
artifacts = replay_plan_bundle(bundle)        # ReplayIntegrityError → exit 6
write_fixture(new-dir, artifacts, bundle.scenario.encode("utf-8"))
target = --against or _infer_original(bundle path)
if target:
    diff = compare_fixtures(target, new-dir)
    if not diff.is_clean():
        emit structured diff; exit 6
emit success line
```

### Structured divergence diff payload (exit 6, both integrity and artifact-diff variants)

Integrity break:

```json
{
  "error": "replay_divergence",
  "kind": "integrity",
  "recorded_run_id": "<uuid>",
  "computed_run_id": "<uuid>",
  "message": "bundle.scenario or bundle.resolved_seed has been modified"
}
```

Artifact divergence:

```json
{
  "error": "replay_divergence",
  "kind": "artifact_diff",
  "run_id": "<uuid>",
  "left_dir": "/path/to/original",
  "right_dir": "/path/to/replay",
  "files": [
    {"path": "journal.jsonl", "kind": "byte_diff", "left_bytes": 1234, "right_bytes": 1235,
     "first_diff_line": 7, "preview_left": "...", "preview_right": "..."},
    {"path": "reports/assets/asset_001.json", "kind": "missing_in_right"}
  ]
}
```

No `divergence.schema.json` artifact in Sprint 4; Sprint 9 will export a schema that covers both this case and the broader app-vs-oracle case.

## Error Handling

### Exit code matrix

| Command | Condition | Code |
|---------|-----------|------|
| any | usage error (bad args, `--next 0`, `--next` non-int) | 2 |
| `plan` | `--steps` negative | 2 (rejected by Typer `min=0`) |
| `plan` | scenario validation fails | 3 |
| `step` | timeline exhausted | 0 (with `done: true`) |
| `step`, `inspect`, `clean` | sentinel missing / malformed / un-parseable | 7 |
| `step` | scenario.yaml mutated since fixture creation | 7 (`scenario_tampered`) |
| `step` | journal.jsonl corrupt | 1 (`journal_corrupt`) |
| `replay` | `ReplayIntegrityError` | 6 |
| `replay` | byte-diff against original or `--against` | 6 |
| any | unexpected exception | 1 |

No new exit codes; Sprint 4 stays within the design doc's frozen 0–7 range.

### Edge cases

1. **`step` on a Sprint 3 plan fixture (timeline already complete).** Fixture has a full journal; `step --next` finds `steps_remaining=0` and emits `done: true`, exit 0.

2. **`step` on a corrupted journal.** Per-line `JournalEntry.model_validate_json` failure → `JournalCorruptError`, exit 1 with structured message naming the offending line. No automatic repair.

3. **`step` after `scenario.yaml` has been hand-edited.** The integrity check at start (`compute_plan_only_run_id(sha256(scenario_bytes), bundle.resolved_seed) == bundle.run_id`) fails; exit 7 with `scenario_tampered`, naming both run_ids.

4. **`step --next N` past end of timeline.** Apply only what remains; return `steps_applied=<actual>`, `steps_remaining=0`, `done=true`, exit 0. Caller detects via `done`.

5. **`clean` on a directory with no sentinel.** Exit 7, `sentinel_missing`. We never recurse-delete an unsentineled directory.

6. **`clean` race (sentinel disappears between verify and rmtree).** `shutil.rmtree` swallows ENOENT at the top level. The command still exits 0 with the path it intended to remove.

7. **`replay --against` pointing at a different scenario's fixture.** `compare_fixtures` reports wholesale divergence. That IS correct behavior; the user asked to compare. Exit 6, structured diff.

8. **`replay` writing into a sentinel-protected parent of itself.** `--out` is validated by the existing `_validate_new_out_path` callback (must not exist). The auto-discover rule only inspects `bundle.parent`, never traverses upward.

9. **`inspect` on a Sprint 3 fixture (no `reports/`).** Summary doesn't read reports, so this is forward-compatible.

10. **Reports for a deleted asset.** `AssetReport.current` is `None`; `history` lists every prior mutation including the `delete_file` entry.

11. **Reports schema drift gate.** Adding the four schemas means the first commit that adds the models also commits `schemas/asset-report.schema.json` etc. — same pattern Sprints 0/1/3 used.

12. **Concurrent `step` invocations.** Not supported. No file locking. Behavior is undefined per the design doc's existing non-goal ("Concurrent / overlapping mutations within the timeline beyond the explicit multi-phase pairs").

## Testing

### Per-component unit tests

```
tests/contract/test_reports.py
  - round-trip each report type through Pydantic
  - extra="forbid" rejection
  - drift gate covered by existing schema_export test once the four schemas land

tests/engine/test_reports.py
  - asset with no mutations → history empty, current==initial
  - asset with move + reencode → ordered history, current reflects both
  - deleted asset → current is None, history present including delete_file
  - slow_copy pair → both started and committed entries appear in history
  - work/variant/bundle reports list correct members and cross-references

tests/engine/test_step.py
  - cursor recovery on identity-move-rename (atomic events only)
  - cursor recovery on a slow_copy scenario (one resolved event ↔ two journal entries)
  - step from t=0 produces journal identical to plan
  - --next 5 on a 3-event scenario applies 3, returns done=true
  - tampered scenario.yaml → exit 7 (scenario_tampered)
  - corrupt journal.jsonl → exit 1 (journal_corrupt)
  - missing sentinel → exit 7 (sentinel_missing)

tests/engine/test_diff.py
  - identical fixtures → is_clean()
  - one-byte change in journal → byte_diff with first_diff_line populated
  - missing file in right → missing_in_right
  - extra file in right → missing_in_left
  - sentinel created_at differences ignored (plan-only omits the field, so this is trivially clean)

tests/engine/test_plan_steps.py
  - --steps 0 → empty journal, current == initial, reports/ present
  - --steps K for 0 < K < timeline-length → partial journal
  - omitted --steps → byte-identical to Sprint 3 baseline (regression)
  - --steps -1 → exit 2 (Typer rejects)

tests/engine/test_plan_e2e.py (EXTEND existing file)
  - "step + plan journals are byte-identical" headline test:
      · plan scenario.yaml --out A (full run)
      · plan scenario.yaml --out B --steps 0; step B --next K (K = len(timeline))
      · assert A/journal.jsonl == B/journal.jsonl
      · assert A/manifest.current.json == B/manifest.current.json
      · assert A/reports/ == B/reports/ (recursive byte-compare)
      · run across all four first-pack scenarios
  - "replay + plan are byte-identical via CLI":
      · plan --out A
      · replay A/replay.json --out B
      · assert no divergence (replay exits 0)
```

### CLI tests

```
tests/cli/test_step.py
  - happy path: --next 1 on a paused fixture
  - --next 5 batching
  - --next 0, --next -1 → exit 2
  - missing sentinel → exit 7
  - tampered scenario → exit 7
  - timeline exhausted → exit 0 with done=true

tests/cli/test_inspect.py
  - happy path on plan fixture
  - happy path on paused fixture (steps_remaining > 0)
  - missing sentinel → exit 7

tests/cli/test_clean.py
  - happy path removes directory
  - missing sentinel → exit 7, directory untouched
  - malformed sentinel → exit 7, directory untouched
  - JSON output shape

tests/cli/test_replay.py
  - happy path on Sprint 3 plan fixture
  - integrity break (mutate bundle.scenario) → exit 6 with integrity payload
  - artifact divergence (corrupt original journal.jsonl) → exit 6 with structured diff
  - --against pointing at a different scenario → exit 6 (wholesale divergence)
  - auto-discover original from bundle.parent works when sentinel matches
  - no auto-discover when bundle.parent has no sentinel
```

### Exit criteria (mapped to tests)

1. *Step mode and plan mode produce identical journals for the same scenario.* → `test_plan_e2e.py::test_step_and_plan_journals_match` across all four first-pack scenarios.
2. *Replay reproduces a prior run; divergence exits 6 with a structured diff.* → `tests/cli/test_replay.py::test_replay_emits_structured_diff_on_divergence` and `::test_replay_integrity_exits_6`.

Implicit:

3. Every command refuses to operate on a non-sentinel'd directory (covered per-command).
4. `plan` with no `--steps` is byte-identical to Sprint 3 output (regression in `test_plan_steps.py`).
5. Report files validate against their exported schemas (drift gate via `schema_export --check`).

### Verification commands

```bash
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
prek run --all-files
```

All five must pass on `feat/sprint-4` before PR.

## Non-Goals

- No `--force` flag on `clean`.
- No concurrent `step` support.
- No `divergence.schema.json` artifact (deferred to Sprint 9).
- No backwards-incremental step (no `--prev`).
- No partial-fixture recovery tools.
- No new `E_` validation codes; the Sprint 3 lifecycle pass covers everything Sprint 4 exercises.
- No materializer-related work — no content hashes in reports, no probed media facts, no FFmpeg invocation.
- No wall-clock support — `run` stays a stub until Sprint 8.

## Open Questions

None identified during brainstorming. If implementation surfaces structural issues (especially around `append_step` atomicity in the face of unexpected interrupts), the plan will document the resolution rather than amending this spec.
