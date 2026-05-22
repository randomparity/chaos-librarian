# Sprint 9 Integration Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a consumer-neutral adapter that compares a consumer-exported observed state JSON document against a Chaos Librarian fixture and emits a structured divergence report.

**Architecture:** Add two contract schemas (`observed-state`, `divergence`) and a new `chaos_librarian.adapter` package. The adapter loads fixture artifacts, validates observed payloads, builds deterministic evidence indexes, matches assets by ranked evidence, then runs final-state and optional identity-history checks. The engine and materializer remain producers of neutral oracle artifacts; no consumer database schema enters Chaos Librarian.

**Tech Stack:** Python 3.13, Pydantic v2, Typer, existing JSON Schema exporter, pytest, ruff, ty.

---

## Source Inputs

**Design doc:** [`docs/superpowers/specs/2026-05-22-sprint-9-integration-harness-design.md`](../specs/2026-05-22-sprint-9-integration-harness-design.md)

**Primary source of truth:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md)

**Execution branch:** Start implementation from a non-main branch. If execution begins from the current design branch (`feat/sprint-9-design`), create or switch to an implementation branch such as `feat/sprint-9` before editing code.

## Open Design Decisions Baked Into This Plan

1. **New contracts live in their own modules.** Create `contract/observed_state.py` and `contract/divergence.py`. Do not add these models to existing contract files; the new schemas are independent public artifacts.

2. **`CompareMode` lives in `contract/divergence.py`.** The CLI, adapter API, and report model all import the same enum so string values cannot drift.

3. **Observed-state validation fails before comparison.** Duplicate refs, invalid paths, missing per-action path fields, dangling topology refs, contradictory topology, and invalid grouped lifecycle links are Pydantic validation errors. `adapter.observed.load_observed_state()` catches those and raises `AdapterInputError(error_code="E_ADAPTER_OBSERVED_INVALID")`.

4. **Fixture loading derives reports when reports are absent.** Modern fixtures contain `reports/`, but the loader should still compare older plan-only fixtures by deriving an in-memory `ReportSet` from `manifest.initial.json`, `manifest.current.json`, and `journal.jsonl`. If a `reports/` directory is present but malformed, fail with `E_ADAPTER_FIXTURE_INVALID`.

5. **No fuzzy or policy matching.** Matching uses only current path, historical path, content hash, and exact supplied topology evidence. If evidence is ambiguous at a precedence level, emit `D_MATCH_AMBIGUOUS`; do not choose a best guess.

6. **Topology matching is conservative.** Topology can add evidence only when supplied work titles, variant labels, bundle refs, and bundle membership produce a unique mapping. Topology mismatches are reported only after asset matching; they do not remap an already matched pair.

7. **Sidecar comparison is scoped by matched asset.** Observed sidecars are nested under observed assets. Oracle sidecars are compared only against the matched observed asset's sidecars, by path first and content hash second when present.

8. **Identity-history filters oracle sidecar filesystem actions.** `create_sidecar` and other non-asset-identity entries are ignored for durable asset lifecycle comparison. Sidecar current state is covered by sidecar comparison.

9. **Grouped observed-link validation stays in the contract layer.** Private helpers in `contract/observed_state.py` own explicit and implicit observed link validation for `delete_file` + `add_file` and `slow_copy_start` + `slow_copy_commit`. `adapter.history` consumes already-valid observed history and owns comparison only.

10. **CLI command order appends `compare` last.** Existing command order is public contract. Add `compare` after `clean` and update tests/docs together.

11. **Commit cadence.** One commit per task keeps reviewable boundaries. Use imperative commit subjects such as `feat(contract): add observed-state schema`.

## File Structure

### To create

```text
src/chaos_librarian/contract/observed_state.py
  ObservedState, ObservedConsumer, ObservedAsset, ObservedSidecar,
  ObservedWork, ObservedVariant, ObservedBundle, ObservedBundleSidecarRef,
  ObservedAction, ObservedPathHistoryEntry, ObservedEvent.

src/chaos_librarian/contract/divergence.py
  CompareMode, DivergenceReport, DivergenceFinding, DivergenceCode,
  DivergenceSeverity, MatchEvidence, DivergenceFixtureMetadata,
  DivergenceObservedMetadata.

src/chaos_librarian/adapter/__init__.py
  Public API exports: CompareMode, OracleFixture, AdapterInputError,
  load_fixture, load_observed_state, compare_fixture_to_observed.

src/chaos_librarian/adapter/errors.py
  Adapter input error class and E_ADAPTER_* constants.

src/chaos_librarian/adapter/fixture.py
  OracleFixture / OracleReports dataclasses and load_fixture(run_dir).

src/chaos_librarian/adapter/observed.py
  load_observed_state(path).

src/chaos_librarian/adapter/index.py
  OracleIndex, ObservedIndex, normalized asset/sidecar/history views.

src/chaos_librarian/adapter/matching.py
  Ranked evidence matching and D_MATCH_AMBIGUOUS construction.

src/chaos_librarian/adapter/probe.py
  ProbedMedia comparison with exact stream fields and duration tolerance.

src/chaos_librarian/adapter/history.py
  Identity-history expected/observed lifecycle extraction and comparison.

src/chaos_librarian/adapter/compare.py
  compare_fixture_to_observed orchestration and final-state finding builders.

src/chaos_librarian/cli/commands/compare.py
  Typer command wrapper for the adapter API.

tests/contract/test_observed_state.py
tests/contract/test_divergence.py
tests/adapter/test_fixture.py
tests/adapter/test_observed.py
tests/adapter/test_matching.py
tests/adapter/test_compare_final_state.py
tests/adapter/test_compare_identity_history.py
tests/cli/test_compare.py

docs/contract/observed-state.md
docs/contract/divergence-report.md
docs/contract/integration-recipes.md
```

### To modify

```text
src/chaos_librarian/contract/__init__.py
  Add OBSERVED_STATE_SCHEMA_VERSION: Final = 1
  Add DIVERGENCE_SCHEMA_VERSION: Final = 1

src/chaos_librarian/schema_export.py
  Add observed-state.schema.json and divergence.schema.json to MODELS.

src/chaos_librarian/cli/_envelope.py
  Add E_ADAPTER_FIXTURE_INVALID, E_ADAPTER_OBSERVED_INVALID,
  E_ADAPTER_RUN_ID_MISMATCH constants if command tests need shared exports.

src/chaos_librarian/cli/commands/__init__.py
  Import compare after clean.

tests/cli/test_app.py
  Add compare to ALL_COMMANDS only. Compare gets dedicated two-positional
  path validation tests in tests/cli/test_compare.py rather than joining the
  existing single-path argument tables.

tests/contract/test_contract_constants.py
  Assert the two new schema-version constants.

tests/contract/test_schema_export.py
  Assert schema export includes observed-state.schema.json and
  divergence.schema.json.

docs/contract/cli-reference.md
docs/contract/schema-reference.md
docs/contract/fixture-layout.md
  Document compare, new schemas, and observed-state fixture relationship.

schemas/observed-state.schema.json
schemas/divergence.schema.json
  Generated by `uv run python -m chaos_librarian.schema_export --write`.
```

## Task 1: Contract Models And Schema Export

**Files:**
- Create: `src/chaos_librarian/contract/observed_state.py`
- Create: `src/chaos_librarian/contract/divergence.py`
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/schema_export.py`
- Modify: `tests/contract/test_contract_constants.py`
- Modify: `tests/contract/test_schema_export.py`
- Test: `tests/contract/test_observed_state.py`
- Test: `tests/contract/test_divergence.py`

- [ ] **Step 1: Write basic contract tests**

Add tests that construct valid scanner, prober, and watcher observed payloads as dictionaries and validate them with `ObservedState.model_validate(payload)`. Include these test names:

```python
def test_scanner_observed_state_round_trips_minimal_assets() -> None: ...
def test_prober_observed_state_round_trips_hash_and_probe() -> None: ...
def test_watcher_observed_state_round_trips_path_history_and_events() -> None: ...
def test_observed_state_rejects_extra_fields() -> None: ...
def test_observed_state_rejects_invalid_hash() -> None: ...
def test_divergence_report_round_trips_final_state_finding() -> None: ...
def test_divergence_report_round_trips_identity_history_related_events() -> None: ...
def test_divergence_report_metadata_round_trips() -> None: ...
def test_divergence_report_rejects_ok_true_with_error_finding() -> None: ...
def test_divergence_report_rejects_ok_false_without_error_findings() -> None: ...
```

Use `Model.model_validate(payload)` for negative tests, not invalid keyword construction.

- [ ] **Step 2: Verify tests fail for missing modules**

Run:

```bash
uv run pytest tests/contract/test_observed_state.py tests/contract/test_divergence.py -q
```

Expected: import failures for `chaos_librarian.contract.observed_state` and `chaos_librarian.contract.divergence`.

- [ ] **Step 3: Implement model skeletons**

Implement the exact model fields from the design doc with `ConfigDict(extra="forbid")` on every `BaseModel`. Use `enum.StrEnum` for `ObservedAction`, `CompareMode`, `DivergenceCode`, and `DivergenceSeverity`.

Required constants in `contract/__init__.py`:

```python
OBSERVED_STATE_SCHEMA_VERSION: Final = 1
DIVERGENCE_SCHEMA_VERSION: Final = 1
```

Required literals:

```python
class ObservedState(BaseModel):
    schema_version: Literal[1]

class DivergenceReport(BaseModel):
    schema_version: Literal[1]
```

Required divergence metadata models:

```python
class DivergenceFixtureMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_dir: str
    execution_mode: str
    asset_count: int
    journal_entries: int


class DivergenceObservedMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consumer_name: str
    consumer_version: str | None = None
    observed_at: datetime
    asset_count: int
```

Define these in Task 1 before schema export. Later adapter tasks populate these models; they do not change their contract shape.

- [ ] **Step 4: Add divergence ok invariant**

Add a `@model_validator(mode="after")` to `DivergenceReport`:

```python
has_error = any(finding.severity is DivergenceSeverity.ERROR for finding in self.findings)
if self.ok == has_error:
    raise ValueError("ok must be false when error findings are present")
return self
```

Keep the message direct; tests should assert validation fails, not depend on the full message text.

- [ ] **Step 5: Register schema exports**

Add:

```python
from chaos_librarian.contract.divergence import DivergenceReport
from chaos_librarian.contract.observed_state import ObservedState
```

Then add these filenames to `MODELS`:

```python
("observed-state.schema.json", ObservedState),
("divergence.schema.json", DivergenceReport),
```

- [ ] **Step 6: Regenerate schemas and run contract checks**

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
uv run pytest tests/contract/test_observed_state.py tests/contract/test_divergence.py \
  tests/contract/test_contract_constants.py tests/contract/test_schema_export.py -q
uv run python -m chaos_librarian.schema_export --check
```

Expected: all commands pass and the two new schema files exist under `schemas/`.
`schemas/divergence.schema.json` includes the fixture and observed metadata fields
defined in this task.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/contract src/chaos_librarian/schema_export.py \
  tests/contract schemas
git commit -m "feat(contract): add sprint 9 comparison schemas"
```

## Task 2: Observed-State Integrity Validation

**Files:**
- Modify: `src/chaos_librarian/contract/observed_state.py`
- Test: `tests/contract/test_observed_state.py`

- [ ] **Step 1: Add path and action validation tests**

Add tests for:

```python
def test_observed_state_rejects_absolute_current_path() -> None: ...
def test_observed_state_rejects_parent_segment_in_path() -> None: ...
def test_observed_state_rejects_backslash_path_separator() -> None: ...
def test_observed_state_rejects_create_sidecar_history_action() -> None: ...
def test_observed_state_rejects_move_without_from_and_to_paths() -> None: ...
def test_observed_state_rejects_delete_without_from_path() -> None: ...
def test_observed_state_rejects_add_without_to_path() -> None: ...
def test_observed_state_rejects_slow_copy_start_without_temp_path() -> None: ...
def test_observed_state_rejects_global_event_without_ref_evidence() -> None: ...
```

Each test should mutate one field in a valid base payload and assert `ValidationError`.

- [ ] **Step 2: Add topology validation tests**

Add tests for:

```python
def test_observed_state_rejects_duplicate_asset_refs() -> None: ...
def test_observed_state_rejects_duplicate_sidecar_refs_within_asset() -> None: ...
def test_observed_state_allows_same_sidecar_ref_under_different_assets() -> None: ...
def test_observed_state_rejects_dangling_asset_bundle_ref() -> None: ...
def test_observed_state_rejects_bundle_asset_ref_not_declared() -> None: ...
def test_observed_state_accepts_bundle_sidecar_ref_scoped_by_asset_ref() -> None: ...
def test_observed_state_rejects_cross_bundle_sidecar_ref() -> None: ...
def test_observed_state_rejects_asset_variant_work_contradiction() -> None: ...
def test_observed_state_rejects_bundle_variant_contradiction() -> None: ...
```

- [ ] **Step 3: Add grouped lifecycle link validation tests**

Add tests for:

```python
def test_grouped_history_accepts_reciprocal_explicit_links() -> None: ...
def test_grouped_history_accepts_deterministic_implicit_per_asset_links() -> None: ...
def test_grouped_history_rejects_dangling_related_event_ref() -> None: ...
def test_grouped_history_rejects_one_sided_link() -> None: ...
def test_grouped_history_rejects_non_reciprocal_link() -> None: ...
def test_grouped_history_rejects_mixed_explicit_and_implicit_pair() -> None: ...
def test_grouped_history_rejects_ambiguous_implicit_pairing() -> None: ...
```

Use `delete_file` + `add_file` and `slow_copy_start` + `slow_copy_commit` examples. Global `events` must always use explicit reciprocal links.

- [ ] **Step 4: Verify the new tests fail**

Run:

```bash
uv run pytest tests/contract/test_observed_state.py -q
```

Expected: validation tests fail because validators are not implemented.

- [ ] **Step 5: Implement path validators**

Add a shared private helper in `observed_state.py`:

```python
def _validate_observed_path(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    path = PurePosixPath(value)
    if value == "" or path.is_absolute() or "\\" in value:
        raise ValueError(f"{field_name} must be a relative POSIX path")
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{field_name} must not contain empty, dot, or parent segments")
    return value
```

Call it from `field_validator` methods for every observed path field:
`current_path`, `ObservedSidecar.path`, history `from_path` / `to_path` /
`temp_path`, and event `path` / `from_path` / `to_path` / `temp_path`.

- [ ] **Step 6: Implement per-action field validators**

Add validators to `ObservedPathHistoryEntry` and `ObservedEvent` that enforce:

```text
move_asset, rename_file, archive_file, move_between_roots -> from_path + to_path
delete_file -> from_path
add_file -> to_path
slow_copy_start -> from_path + to_path + temp_path
slow_copy_commit -> to_path
```

For `ObservedEvent`, also require `observed_ref` or both `before_observed_ref` and `after_observed_ref`.

- [ ] **Step 7: Implement `ObservedState` reference validators**

In a model-level validator:

1. Build ref sets for assets, works, variants, bundles.
2. Check uniqueness within each collection.
3. Check sidecar uniqueness within each parent asset.
4. Check asset `work_ref`, `variant_ref`, and `bundle_ref` point to declared objects when present.
5. Check variant `work_ref` and bundle `variant_ref`.
6. Check every `bundle.asset_refs[]` points to an observed asset.
7. Check every `bundle.sidecar_refs[]` has an `asset_ref` listed in that bundle and a `sidecar_ref` under that asset.
8. Check asset, variant, and bundle topology agree when multiple directions are supplied.

Raise `ValueError` with a message containing the invalid reference kind.

- [ ] **Step 8: Implement grouped lifecycle link validation**

Validate explicit links by building a map of `observed_event_ref -> entry` for each per-asset history list and for global events. A valid explicit group has both entries present and reciprocal `related_observed_event_ref` values. Reject one-sided, dangling, non-reciprocal, and mixed explicit/implicit pairings.

For implicit per-asset grouping, only allow both entries to omit link refs. Pair by action family, path fields, and observation order. If more than one possible counterpart exists, reject as ambiguous.

- [ ] **Step 9: Run contract checks**

Run:

```bash
uv run pytest tests/contract/test_observed_state.py -q
uv run ruff check src/chaos_librarian/contract/observed_state.py tests/contract/test_observed_state.py
uv run ty check src/chaos_librarian/contract tests/contract
uv run python -m chaos_librarian.schema_export --check
```

Expected: all commands pass.

- [ ] **Step 10: Commit**

```bash
git add src/chaos_librarian/contract/observed_state.py tests/contract/test_observed_state.py
git commit -m "feat(contract): validate observed-state integrity"
```

## Task 3: Adapter Fixture And Observed Loaders

**Files:**
- Create: `src/chaos_librarian/adapter/__init__.py`
- Create: `src/chaos_librarian/adapter/errors.py`
- Create: `src/chaos_librarian/adapter/fixture.py`
- Create: `src/chaos_librarian/adapter/observed.py`
- Test: `tests/adapter/test_fixture.py`
- Test: `tests/adapter/test_observed.py`

- [ ] **Step 1: Write fixture loader tests**

Add tests for:

```python
def test_load_fixture_reads_required_artifacts(tmp_path: Path) -> None: ...
def test_load_fixture_derives_reports_when_reports_directory_missing(tmp_path: Path) -> None: ...
def test_load_fixture_rejects_missing_sentinel(tmp_path: Path) -> None: ...
def test_load_fixture_rejects_malformed_replay_json(tmp_path: Path) -> None: ...
def test_load_fixture_rejects_malformed_present_report(tmp_path: Path) -> None: ...
def test_load_fixture_rejects_sentinel_run_id_mismatch(tmp_path: Path) -> None: ...
def test_load_fixture_rejects_journal_run_id_mismatch(tmp_path: Path) -> None: ...
def test_load_fixture_rejects_mixed_journal_scenario_ids(tmp_path: Path) -> None: ...
def test_load_fixture_rejects_report_filename_id_mismatch(tmp_path: Path) -> None: ...
def test_load_fixture_rejects_report_id_missing_from_manifest(tmp_path: Path) -> None: ...
```

Use existing contract models to write the fixture files. Keep fixture builders in this test file; do not add project-wide test utilities until another file needs them.

- [ ] **Step 2: Write observed loader tests**

Add tests for:

```python
def test_load_observed_state_reads_valid_json(tmp_path: Path) -> None: ...
def test_load_observed_state_rejects_malformed_json(tmp_path: Path) -> None: ...
def test_load_observed_state_rejects_schema_invalid_json(tmp_path: Path) -> None: ...
```

Assert `AdapterInputError.error_code` is `E_ADAPTER_OBSERVED_INVALID` for observed JSON failures.

- [ ] **Step 3: Verify loader tests fail**

Run:

```bash
uv run pytest tests/adapter/test_fixture.py tests/adapter/test_observed.py -q
```

Expected: import failures for the new adapter package.

- [ ] **Step 4: Implement adapter errors**

Create constants:

```python
E_ADAPTER_FIXTURE_INVALID = "E_ADAPTER_FIXTURE_INVALID"
E_ADAPTER_OBSERVED_INVALID = "E_ADAPTER_OBSERVED_INVALID"
E_ADAPTER_RUN_ID_MISMATCH = "E_ADAPTER_RUN_ID_MISMATCH"
```

Implement:

```python
class AdapterInputError(ChaosLibrarianError):
    def __init__(
        self,
        *,
        error_code: str,
        message: str,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.details = dict(details or {})
```

- [ ] **Step 5: Implement `OracleFixture` and `load_fixture`**

Required dataclasses:

```python
@dataclass(frozen=True)
class OracleReports:
    assets: Mapping[str, AssetReport]
    works: Mapping[str, WorkReport]
    variants: Mapping[str, VariantReport]
    bundles: Mapping[str, BundleReport]

@dataclass(frozen=True)
class OracleFixture:
    run_dir: Path
    run_id: uuid.UUID
    scenario_id: str
    sentinel: RunSentinel
    replay_bundle: ReplayBundle
    initial_manifest: Manifest
    current_manifest: Manifest
    journal: tuple[JournalEntry, ...]
    reports: OracleReports
```

`load_fixture(run_dir)` must:

1. Call `verify_sentinel(run_dir)` and map `SentinelInvalidError` through unchanged for CLI exit 7.
2. Parse `replay.json` with `TypeAdapter(ReplayBundle)`.
3. Parse `scenario.yaml` with `prepare_run_input_from_bytes()` to obtain `scenario_id`.
4. Parse `manifest.initial.json` and `manifest.current.json`.
5. Parse `journal.jsonl`, skipping blank lines and reporting the 1-based line number on parse failure.
6. Cross-check `sentinel.run_id == replay_bundle.run_id`.
7. Cross-check every journal entry's `run_id` equals `replay_bundle.run_id`.
8. Cross-check every journal entry's `scenario_id` equals the parsed `scenario_id`.
9. Load `reports/` when present and validate every JSON file.
10. For present reports, require each filename stem to match the report id field.
11. For present reports, require report ids to exist in the corresponding manifest collection:
    asset reports in `initial_manifest.assets`, work reports in `initial_manifest.works`,
    variant reports in `initial_manifest.variants`, and bundle reports in
    `initial_manifest.bundles`.
12. Derive `ReportSet` via `build_report_set()` when `reports/` is absent.

Every malformed or internally inconsistent fixture artifact except the sentinel raises `AdapterInputError(error_code=E_ADAPTER_FIXTURE_INVALID)`.

- [ ] **Step 6: Implement `load_observed_state`**

Read bytes from the observed JSON file and call `ObservedState.model_validate_json()`. Catch `OSError`, `json.JSONDecodeError` when applicable, and `ValidationError`, and raise `AdapterInputError(error_code=E_ADAPTER_OBSERVED_INVALID)`.

- [ ] **Step 7: Export public adapter API**

In `adapter/__init__.py`, export:

```python
__all__ = [
    "AdapterInputError",
    "CompareMode",
    "OracleFixture",
    "compare_fixture_to_observed",
    "load_fixture",
    "load_observed_state",
]
```

Import `compare_fixture_to_observed` lazily from `adapter.compare` only after Task 6 creates it, or export it in Task 6 to avoid a temporary broken import.

- [ ] **Step 8: Run loader checks**

Run:

```bash
uv run pytest tests/adapter/test_fixture.py tests/adapter/test_observed.py -q
uv run ruff check src/chaos_librarian/adapter tests/adapter/test_fixture.py tests/adapter/test_observed.py
uv run ty check src/chaos_librarian/adapter tests/adapter
```

Expected: all commands pass.

- [ ] **Step 9: Commit**

```bash
git add src/chaos_librarian/adapter tests/adapter
git commit -m "feat(adapter): load fixtures and observed state"
```

## Task 4: Evidence Indexes And Deterministic Matching

**Files:**
- Create: `src/chaos_librarian/adapter/index.py`
- Create: `src/chaos_librarian/adapter/matching.py`
- Test: `tests/adapter/test_matching.py`

- [ ] **Step 1: Write matching tests**

Add tests for:

```python
def test_matches_by_unique_current_path_before_hash() -> None: ...
def test_matches_deleted_asset_by_historical_path() -> None: ...
def test_matches_by_hash_when_paths_are_absent() -> None: ...
def test_unique_higher_precedence_match_wins_over_lower_conflict() -> None: ...
def test_observed_asset_mapping_to_two_oracles_is_ambiguous() -> None: ...
def test_oracle_asset_mapping_to_two_observed_assets_is_ambiguous() -> None: ...
def test_ambiguous_candidates_do_not_also_emit_missing_or_unexpected() -> None: ...
def test_unmatched_oracle_asset_emits_asset_missing() -> None: ...
def test_unmatched_observed_asset_emits_asset_unexpected() -> None: ...
```

Use small dataclass fixtures rather than writing full run directories in these tests. The matcher should accept indexes, not filesystem paths.

- [ ] **Step 2: Verify matching tests fail**

Run:

```bash
uv run pytest tests/adapter/test_matching.py -q
```

Expected: import failures for `adapter.index` or `adapter.matching`.

- [ ] **Step 3: Implement normalized index types**

Create focused dataclasses:

```python
@dataclass(frozen=True)
class OracleAssetView:
    asset_id: str
    bundle_id: str
    current_path: str | None
    content_hash: str | None
    probed: ProbedMedia | None
    path_history: tuple[PathHistoryEntry, ...]
    sidecars: tuple[ManifestSidecar, ...]

@dataclass(frozen=True)
class ObservedAssetView:
    observed_ref: str
    current_path: str | None
    content_hash: str | None
    probed: ProbedMedia | None
    work_ref: str | None
    variant_ref: str | None
    bundle_ref: str | None
    sidecars: tuple[ObservedSidecar, ...]
    path_history: tuple[ObservedPathHistoryEntry, ...]
```

Build `OracleIndex` from `OracleFixture` and `ObservedIndex` from `ObservedState`. Keep maps keyed by ids/refs and precompute path/hash lookup dictionaries.

- [ ] **Step 4: Implement ranked matching**

Implement `match_assets(oracle_index, observed_index) -> MatchResult` with:

```python
@dataclass(frozen=True)
class AssetMatch:
    oracle_asset_id: str
    observed_ref: str
    evidence: tuple[MatchEvidence, ...]

@dataclass(frozen=True)
class MatchResult:
    matches: tuple[AssetMatch, ...]
    findings: tuple[DivergenceFinding, ...]
    unmatched_oracle_asset_ids: tuple[str, ...]
    unmatched_observed_refs: tuple[str, ...]
    ambiguous_oracle_asset_ids: tuple[str, ...]
    ambiguous_observed_refs: tuple[str, ...]
```

Process precedence in order:

1. current path
2. historical path
3. content hash
4. topology

At each level, match only pairs where neither side is already matched or already marked ambiguous. If any key maps to multiple candidates on either side, add `D_MATCH_AMBIGUOUS` findings, record those oracle ids / observed refs in the ambiguous fields, and do not match those candidates at that or later precedence levels.

- [ ] **Step 5: Add missing/unexpected findings**

After all precedence levels, emit:

```text
D_ASSET_MISSING for every unmatched oracle asset that is not ambiguous
D_ASSET_UNEXPECTED for every unmatched observed asset that is not ambiguous
```

Messages should include the asset id or observed ref. Keep exact wording stable enough for users, but tests should assert code and ids first. A candidate that already produced `D_MATCH_AMBIGUOUS` must not also produce `D_ASSET_MISSING` or `D_ASSET_UNEXPECTED`.

- [ ] **Step 6: Run matching checks**

Run:

```bash
uv run pytest tests/adapter/test_matching.py -q
uv run ruff check src/chaos_librarian/adapter/index.py src/chaos_librarian/adapter/matching.py tests/adapter/test_matching.py
uv run ty check src/chaos_librarian/adapter tests/adapter/test_matching.py
```

Expected: all commands pass.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/adapter/index.py src/chaos_librarian/adapter/matching.py \
  tests/adapter/test_matching.py
git commit -m "feat(adapter): match assets by ranked evidence"
```

## Task 5: Final-State Comparison

**Files:**
- Create: `src/chaos_librarian/adapter/probe.py`
- Create: `src/chaos_librarian/adapter/compare.py`
- Modify: `src/chaos_librarian/adapter/__init__.py`
- Test: `tests/adapter/test_compare_final_state.py`

- [ ] **Step 1: Write final-state comparison tests**

Add tests for:

```python
def test_clean_observed_state_returns_ok_report() -> None: ...
def test_run_id_mismatch_is_input_error_not_divergence() -> None: ...
def test_path_mismatch_emits_d_path_mismatch() -> None: ...
def test_deletion_mismatch_emits_d_deletion_mismatch() -> None: ...
def test_hash_mismatch_requires_both_hashes() -> None: ...
def test_probe_mismatch_requires_both_probed_values() -> None: ...
def test_probe_duration_uses_point_zero_five_second_tolerance() -> None: ...
def test_missing_observed_sidecar_emits_d_sidecar_missing() -> None: ...
def test_unexpected_observed_sidecar_emits_d_sidecar_unexpected() -> None: ...
def test_topology_mismatch_emits_d_topology_mismatch_when_both_sides_supply_refs() -> None: ...
def test_final_state_mode_skips_history_when_no_history_supplied() -> None: ...
```

Construct `OracleFixture` dataclasses directly for unit tests. Use one integration-style test with a real temporary fixture directory only if direct construction hides loader behavior.

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/adapter/test_compare_final_state.py -q
```

Expected: missing `compare_fixture_to_observed` or missing findings.

- [ ] **Step 3: Implement probe comparison**

`compare_probed_media(expected: ProbedMedia, observed: ProbedMedia) -> list[tuple[str, object, object]]` compares:

```text
container
stream count
stream order
stream kind
codec
language
width
height
channels
sample_rate
default
forced
duration_seconds with abs(delta) > 0.05
```

Ignore `size_bytes` in probe comparison. Return field-level differences so `D_PROBE_MISMATCH.expected` and `.observed` can be concise dictionaries.

- [ ] **Step 4: Implement `compare_fixture_to_observed` orchestration**

Function signature:

```python
def compare_fixture_to_observed(
    fixture: OracleFixture,
    observed: ObservedState,
    *,
    mode: CompareMode = CompareMode.FINAL_STATE,
) -> DivergenceReport:
```

First check `fixture.run_id == observed.run_id`; on mismatch raise `AdapterInputError(error_code=E_ADAPTER_RUN_ID_MISMATCH)`.

Then:

1. Build oracle and observed indexes.
2. Run matching.
3. Compare current paths and deletion state for matched assets.
4. Compare hashes only when both sides supply a hash.
5. Compare probed media only when both sides supply `probed`.
6. Compare sidecars for matched assets.
7. Compare topology when both sides supply refs.
8. Add history findings only in `IDENTITY_HISTORY` mode; leave this call empty until Task 6.
9. Return `DivergenceReport(ok=not any(error findings), mode=mode, ...)`.

- [ ] **Step 5: Populate report metadata**

Use the `DivergenceFixtureMetadata` and `DivergenceObservedMetadata` models defined in Task 1. Populate them in `compare_fixture_to_observed()`:

```python
fixture=DivergenceFixtureMetadata(
    run_dir=str(fixture.run_dir),
    execution_mode=fixture.replay_bundle.execution_mode.value,
    asset_count=len(fixture.current_manifest.assets),
    journal_entries=len(fixture.journal),
)
observed=DivergenceObservedMetadata(
    consumer_name=observed.consumer.name,
    consumer_version=observed.consumer.version,
    observed_at=observed.observed_at,
    asset_count=len(observed.assets),
)
```

Do not change `contract/divergence.py` or regenerate schemas in this task. If metadata needs a new field, stop and revise Task 1 instead of changing the contract mid-adapter.

- [ ] **Step 6: Run final-state checks**

Run:

```bash
uv run pytest tests/adapter/test_compare_final_state.py tests/adapter/test_matching.py -q
uv run ruff check src/chaos_librarian/adapter tests/adapter/test_compare_final_state.py
uv run ty check src/chaos_librarian/adapter tests/adapter
```

Expected: all commands pass.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/adapter tests/adapter/test_compare_final_state.py
git commit -m "feat(adapter): compare final observed state"
```

## Task 6: Identity-History Comparison

**Files:**
- Create: `src/chaos_librarian/adapter/history.py`
- Modify: `src/chaos_librarian/adapter/compare.py`
- Test: `tests/adapter/test_compare_identity_history.py`

- [ ] **Step 1: Write identity-history tests**

Add clean comparison tests for:

```python
def test_identity_history_clean_move_asset() -> None: ...
def test_identity_history_clean_rename_file() -> None: ...
def test_identity_history_clean_archive_file() -> None: ...
def test_identity_history_clean_move_between_roots() -> None: ...
def test_identity_history_clean_slow_copy_group() -> None: ...
def test_identity_history_clean_delete_add_group() -> None: ...
```

Add failure tests for:

```python
def test_identity_history_ignores_oracle_create_sidecar_path_history() -> None: ...
def test_identity_history_missing_all_evidence_emits_history_missing() -> None: ...
def test_identity_history_missing_single_event_emits_history_missing() -> None: ...
def test_identity_history_missing_slow_copy_group_reports_related_event_ids() -> None: ...
def test_identity_history_split_global_event_emits_identity_split() -> None: ...
def test_identity_history_conflict_beats_identity_split() -> None: ...
def test_identity_history_unexpected_observed_history_emits_history_unexpected() -> None: ...
```

- [ ] **Step 2: Verify identity-history tests fail**

Run:

```bash
uv run pytest tests/adapter/test_compare_identity_history.py -q
```

Expected: history findings are missing.

- [ ] **Step 3: Implement oracle lifecycle extraction**

In `history.py`, define:

```python
IDENTITY_ACTIONS: Final[frozenset[TimelineActionName]] = frozenset({
    TimelineActionName.MOVE_ASSET,
    TimelineActionName.RENAME_FILE,
    TimelineActionName.DELETE_FILE,
    TimelineActionName.ADD_FILE,
    TimelineActionName.SLOW_COPY_START,
    TimelineActionName.SLOW_COPY_COMMIT,
    TimelineActionName.ARCHIVE_FILE,
    TimelineActionName.MOVE_BETWEEN_ROOTS,
})
```

Convert each matched oracle asset's `AssetReport.path_history` into expected lifecycle objects. Group adjacent `delete_file` + `add_file` for the same oracle asset when paths represent removal and restoration. Group `slow_copy_start` + `slow_copy_commit` by journal ordering and related path fields.

- [ ] **Step 4: Implement observed lifecycle extraction**

For each matched observed asset, collect:

1. Per-asset `path_history` entries.
2. Global `events` where `observed_ref`, `before_observed_ref`, or `after_observed_ref` references the matched observed asset.

Normalize both sources into:

```python
@dataclass(frozen=True)
class ObservedLifecycleEvidence:
    action: ObservedAction
    observed_ref_before: str
    observed_ref_after: str
    from_path: str | None
    to_path: str | None
    temp_path: str | None
    observed_event_ref: str | None
```

For per-asset history, before and after refs are the same matched `observed_ref`.

- [ ] **Step 5: Implement history comparison**

`compare_identity_history(match_result, oracle_index, observed_index) -> tuple[DivergenceFinding, ...]` must:

1. Emit `D_HISTORY_MISSING` for each expected lifecycle with no matching observed evidence.
2. Emit `D_IDENTITY_SPLIT` when all available evidence consistently maps one oracle lifecycle to different before/after observed refs.
3. Emit `D_HISTORY_CONFLICT` when per-asset and global evidence disagree for the same oracle lifecycle.
4. Emit `D_HISTORY_UNEXPECTED` for observed path mutations that do not map to any oracle lifecycle.
5. For grouped lifecycles, set `oracle_event_id` to the first oracle event and `related_oracle_event_ids` to the rest in journal order.
6. Never emit both `D_HISTORY_CONFLICT` and `D_IDENTITY_SPLIT` for the same oracle event.

- [ ] **Step 6: Wire history into compare orchestration**

In `compare_fixture_to_observed`, call identity-history comparison only when `mode is CompareMode.IDENTITY_HISTORY`. In final-state mode, do not inspect missing history and do not emit history findings.

- [ ] **Step 7: Run history checks**

Run:

```bash
uv run pytest tests/adapter/test_compare_identity_history.py tests/adapter/test_compare_final_state.py -q
uv run ruff check src/chaos_librarian/adapter/history.py src/chaos_librarian/adapter/compare.py \
  tests/adapter/test_compare_identity_history.py
uv run ty check src/chaos_librarian/adapter tests/adapter
```

Expected: all commands pass.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/adapter/history.py src/chaos_librarian/adapter/compare.py \
  tests/adapter/test_compare_identity_history.py
git commit -m "feat(adapter): compare identity history"
```

## Task 7: Compare CLI

**Files:**
- Create: `src/chaos_librarian/cli/commands/compare.py`
- Modify: `src/chaos_librarian/cli/commands/__init__.py`
- Modify: `src/chaos_librarian/cli/_envelope.py`
- Modify: `tests/cli/test_app.py`
- Test: `tests/cli/test_compare.py`

- [ ] **Step 1: Write CLI tests**

Add tests for:

```python
def test_compare_help_succeeds() -> None: ...
def test_compare_clean_exits_zero_and_writes_json_report(tmp_path: Path) -> None: ...
def test_compare_divergent_exits_six_and_writes_json_report(tmp_path: Path) -> None: ...
def test_compare_identity_history_missing_evidence_exits_six(tmp_path: Path) -> None: ...
def test_compare_malformed_observed_json_exits_one_with_error_envelope(tmp_path: Path) -> None: ...
def test_compare_run_id_mismatch_exits_one_not_divergence(tmp_path: Path) -> None: ...
def test_compare_missing_sentinel_exits_seven(tmp_path: Path) -> None: ...
def test_compare_rejects_missing_run_dir(tmp_path: Path) -> None: ...
def test_compare_rejects_file_run_dir(tmp_path: Path) -> None: ...
def test_compare_rejects_missing_observed_file(tmp_path: Path) -> None: ...
def test_compare_rejects_observed_directory(tmp_path: Path) -> None: ...
```

Update `ALL_COMMANDS` in `tests/cli/test_app.py` to append `"compare"`. Do not add compare to `_FILE_ARG_COMMANDS` or `_DIR_ARG_COMMANDS`; those tables cover commands with one positional path, while compare has both a run directory and an observed JSON file. The four compare-specific path tests above cover the two positional arguments directly.

- [ ] **Step 2: Verify CLI tests fail**

Run:

```bash
uv run pytest tests/cli/test_compare.py tests/cli/test_app.py -q
```

Expected: compare command missing and command-order test fails until registered.

- [ ] **Step 3: Implement command**

Command shape:

```python
@app.command()
def compare(
    run_dir: Annotated[Path, typer.Argument(exists=True, file_okay=False)],
    observed: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    mode: Annotated[CompareMode, typer.Option("--mode")] = CompareMode.FINAL_STATE,
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    ...
```

Behavior:

1. Load fixture with `load_fixture(run_dir)`.
2. Load observed state with `load_observed_state(observed)`.
3. Run `compare_fixture_to_observed(fixture, observed_state, mode=mode)`.
4. If `--json`, write `report.model_dump_json(indent=2, exclude_none=True)` to stdout.
5. If not JSON, write `compare: ok (N findings)` or `compare: divergence (N findings)` plus one summary line per finding.
6. Exit `0` when `report.ok` is true.
7. Exit `6` when `report.ok` is false.
8. Map `AdapterInputError` to `emit_cli_error(..., json_output=json_output)` and exit `1`.
9. Map `SentinelInvalidError` to `E_SENTINEL_INVALID` and exit `7`.

- [ ] **Step 4: Register command last**

In `cli/commands/__init__.py`, append:

```python
from chaos_librarian.cli.commands import compare
```

Do not reorder existing imports.

- [ ] **Step 5: Add adapter error constants to envelope module**

Expose the three adapter input error codes from `_envelope.py` only if tests or command code import them from the CLI layer. The source constants stay in `adapter.errors`.

- [ ] **Step 6: Run CLI checks**

Run:

```bash
uv run pytest tests/cli/test_compare.py tests/cli/test_app.py -q
uv run chaos-librarian compare --help
uv run ruff check src/chaos_librarian/cli src/chaos_librarian/adapter tests/cli/test_compare.py
uv run ty check src/chaos_librarian/cli src/chaos_librarian/adapter tests/cli tests/adapter
```

Expected: pytest passes, help exits `0`, ruff and ty are clean.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/cli tests/cli
git commit -m "feat(cli): add compare command"
```

## Task 8: Contract Documentation

**Files:**
- Create: `docs/contract/observed-state.md`
- Create: `docs/contract/divergence-report.md`
- Create: `docs/contract/integration-recipes.md`
- Modify: `docs/contract/cli-reference.md`
- Modify: `docs/contract/schema-reference.md`
- Modify: `docs/contract/fixture-layout.md`

- [ ] **Step 1: Document observed-state exporter contract**

`docs/contract/observed-state.md` must include:

1. Purpose: consumer-neutral export, not a Chaos Librarian oracle.
2. Required top-level fields.
3. Library-relative POSIX path rule.
4. Scanner minimal example with `observed_ref` and `current_path`.
5. Prober example with `content_hash` and `probed`.
6. Watcher example with per-asset `path_history`.
7. Watcher example with global `events`.
8. Topology refs and bundle sidecar ref scoping by `{asset_ref, sidecar_ref}`.
9. Input-error conditions that produce `E_ADAPTER_OBSERVED_INVALID`.

- [ ] **Step 2: Document divergence report contract**

`docs/contract/divergence-report.md` must include:

1. `DivergenceReport` top-level fields.
2. `ok` invariant.
3. `mode` values.
4. `DivergenceFinding` fields.
5. All Sprint 9 divergence codes and meanings.
6. Grouped lifecycle `oracle_event_id` / `related_oracle_event_ids` rule.
7. CLI exit code split: `0`, `6`, `1`, and `7`.

- [ ] **Step 3: Document recipes**

`docs/contract/integration-recipes.md` must include:

1. Scanner recipe using `final-state`.
2. Prober recipe using hashes and probed media.
3. Watcher recipe using `identity-history`.
4. Daemon churn recipe for `run` fixtures.
5. Fast CI and extended CI guidance.

Do not include voom-v2 SQL, table names, or schema-specific code.

- [ ] **Step 4: Update existing contract docs**

Update:

```text
docs/contract/cli-reference.md      # compare syntax and exit codes
docs/contract/schema-reference.md   # observed-state and divergence schemas
docs/contract/fixture-layout.md     # observed-state is an external input, not fixture output
```

- [ ] **Step 5: Check docs references**

Run:

```bash
rg -n "observed-state|divergence|compare|identity-history" docs/contract docs/superpowers/specs/2026-05-22-sprint-9-integration-harness-design.md
```

Expected: new docs and design doc all reference the same command names, modes, and schema filenames.

- [ ] **Step 6: Commit**

```bash
git add docs/contract
git commit -m "docs: document sprint 9 integration harness"
```

## Task 9: End-To-End Verification And Cleanup

**Files:**
- Modify only files that fail verification.

- [ ] **Step 1: Run focused test suite**

Run:

```bash
uv run pytest tests/contract/test_observed_state.py tests/contract/test_divergence.py \
  tests/adapter tests/cli/test_compare.py tests/cli/test_app.py -q
```

Expected: all tests pass.

- [ ] **Step 2: Run schema drift gate**

Run:

```bash
uv run python -m chaos_librarian.schema_export --check
```

Expected: `All 14 schemas up-to-date.` if no other schemas are added before Sprint 9. If the count differs because later work added schemas, the command must still exit `0`.

- [ ] **Step 3: Run lint, format, and type checks**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
```

Expected: all commands pass with zero warnings.

- [ ] **Step 4: Smoke-test the CLI**

Run:

```bash
uv run chaos-librarian --help
uv run chaos-librarian compare --help
```

Expected: both commands exit `0`; top-level help lists `compare` after `clean`.

- [ ] **Step 5: Review the diff for scope**

Run:

```bash
git diff --stat origin/main...HEAD
git diff --check
```

Confirm the diff is limited to Sprint 9 contracts, adapter, CLI, schemas, tests, and docs.

- [ ] **Step 6: Commit any verification fixes**

If verification required code or docs changes:

```bash
git add <changed-files>
git commit -m "fix: finish sprint 9 verification"
```

Do not create an empty commit when no fixes are needed.

## Self-Review Checklist

- Every in-scope design requirement has a task:
  - observed-state contract and schema export: Tasks 1-2
  - divergence report contract and schema export: Task 1
  - fixture and observed loaders: Task 3
  - deterministic matching: Task 4
  - final-state comparison: Task 5
  - identity-history comparison: Task 6
  - compare CLI: Task 7
  - consumer-facing docs: Task 8
  - verification: Task 9
- Error domains stay separate:
  - adapter input errors: `E_ADAPTER_*`, command exits `1`
  - divergence findings: `D_*`, command exits `6`
  - sentinel/fs safety: existing sentinel errors, command exits `7`
- No voom-v2-specific storage schema appears in contracts, adapter, tests, or docs.
- New contract model files regenerate checked-in JSON Schema artifacts in the same change.
- Divergence metadata fields are defined before the first divergence schema export.
- Observed grouped-link validation does not import from `chaos_librarian.adapter`.
- Ambiguous matches are excluded from missing/unexpected asset-presence findings.
- Fixture loading rejects mixed journal/report artifacts as invalid fixture input.
- Compare path validation tests cover both positional path arguments directly.
- `final-state` never fails only because history is absent.
- `identity-history` never silently downgrades to final-state behavior.
