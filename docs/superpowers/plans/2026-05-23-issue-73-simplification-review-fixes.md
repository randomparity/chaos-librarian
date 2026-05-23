# Issue 73 Simplification Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Simplify the issue #73 duplicate/variant expansion-pack tests without changing
fixture behavior or adapter semantics.

**Architecture:** Keep contract tests focused on fixture shape and adapter evidence, and
move materializer hash evidence into a materializer test. Reuse shared adapter test
support for plan fixture writing and observed-state construction so branch-local helpers
do not duplicate established workflows.

**Tech Stack:** Python 3.13, pytest, Pydantic contract models, existing Chaos Librarian
adapter and materializer helpers.

---

## Files

- Modify: `tests/support/adapter.py`
- Modify: `tests/contract/test_duplicate_variant_expansion_pack.py`
- Create: `tests/materializer/test_duplicate_variant_expansion_pack.py`
- Create: `docs/superpowers/plans/2026-05-23-issue-73-simplification-review-fixes.md`

## Task 1: Extend Shared Observed-State Support

- [ ] **Step 1: Update the shared helper signature**

In `tests/support/adapter.py`, change `observed_from_fixture` so existing callers keep
the same defaults and new callers can request topology and null current paths:

```python
def observed_from_fixture(
    oracle_fixture: OracleFixture,
    *,
    run_id: uuid.UUID | None = None,
    path_override: str | None = None,
    include_current_paths: bool = True,
    include_topology: bool = False,
) -> ObservedState:
```

- [ ] **Step 2: Build topology maps once**

Inside the helper, add work, variant, bundle, and location maps before asset iteration:

```python
work_refs = {work.id: f"observed-{work.id}" for work in oracle_fixture.current_manifest.works}
variant_refs = {
    variant.id: f"observed-{variant.id}"
    for variant in oracle_fixture.current_manifest.variants
}
bundle_refs = {
    bundle.id: f"observed-{bundle.id}" for bundle in oracle_fixture.current_manifest.bundles
}
bundles_by_id = {bundle.id: bundle for bundle in oracle_fixture.current_manifest.bundles}
variants_by_id = {
    variant.id: variant for variant in oracle_fixture.current_manifest.variants
}
asset_refs_by_bundle: dict[str, list[str]] = {}
```

- [ ] **Step 3: Populate asset refs while building assets**

For each asset, set `current_path` to `None` when `include_current_paths=False`, preserve
the existing first-asset `path_override` behavior, and populate topology refs only when
`include_topology=True`:

```python
bundle = bundles_by_id[asset.bundle_id]
variant = variants_by_id[bundle.variant_id]
observed_ref = f"observed-{asset.id}"
asset_refs_by_bundle.setdefault(asset.bundle_id, []).append(observed_ref)
current_path = location.path if location is not None and include_current_paths else None
if include_current_paths and path_override is not None and not assets:
    current_path = path_override
```

Use these values in `ObservedAsset(...)`:

```python
work_ref=work_refs[variant.work_id] if include_topology else None,
variant_ref=variant_refs[bundle.variant_id] if include_topology else None,
bundle_ref=bundle_refs[asset.bundle_id] if include_topology else None,
```

- [ ] **Step 4: Return optional topology collections**

When `include_topology=True`, include `works`, `variants`, and `bundles` built from the
same maps. When false, preserve the current default shape by omitting topology lists.

- [ ] **Step 5: Verify existing adapter callers still pass**

Run:

```bash
uv run pytest tests/cli/test_compare.py tests/adapter/test_compare_final_state.py -q --no-cov
```

Expected: all tests pass.

## Task 2: Simplify Contract Expansion-Pack Tests

- [ ] **Step 1: Reuse shared fixture writers**

In `tests/contract/test_duplicate_variant_expansion_pack.py`, replace local plan writing
with:

```python
from tests.support.adapter import (
    observed_from_fixture as _observed_from_fixture,
    write_plan_fixture as _write_plan_fixture,
)
```

Then reduce `_plan_fixture` to:

```python
def _plan_fixture(tmp_path: Path) -> OracleFixture:
    run_dir = _write_plan_fixture(tmp_path, "duplicate-variant-expanded.yaml")
    return load_fixture(run_dir)
```

- [ ] **Step 2: Share the plan fixture across read-only tests**

Add a module-scoped fixture:

```python
@pytest.fixture(scope="module")
def oracle_fixture(tmp_path_factory: pytest.TempPathFactory) -> OracleFixture:
    return _plan_fixture(tmp_path_factory.mktemp("duplicate-variant-expanded"))
```

Update the three adapter tests to accept `oracle_fixture: OracleFixture` instead of
`tmp_path: Path`.

- [ ] **Step 3: Use shared observed-state conversion**

Replace calls to the deleted local helper with:

```python
_observed_from_fixture(oracle_fixture, include_topology=True)
_observed_from_fixture(
    oracle_fixture,
    include_current_paths=False,
    include_topology=True,
)
```

Delete the local `_observed_from_fixture` helper and its now-unused observed-state imports.

- [ ] **Step 4: Split pathless topology assertions by intent**

Replace the mixed pathless topology test with two tests:

```python
def test_duplicate_variant_pathless_topology_export_reports_ambiguity(
    oracle_fixture: OracleFixture,
) -> None:
    observed = _observed_from_fixture(
        oracle_fixture,
        include_current_paths=False,
        include_topology=True,
    )
    report = compare_fixture_to_observed(oracle_fixture, observed)

    assert {
        finding.evidence[0].value
        for finding in report.findings
        if finding.code == "D_MATCH_AMBIGUOUS"
    } == {"Synthetic Echo|hd|1", "Synthetic Pair|hd|2"}
```

```python
def test_duplicate_variant_pathless_topology_export_reports_deleted_unique_matches(
    oracle_fixture: OracleFixture,
) -> None:
    observed = _observed_from_fixture(
        oracle_fixture,
        include_current_paths=False,
        include_topology=True,
    )
    report = compare_fixture_to_observed(oracle_fixture, observed)

    assert {
        finding.oracle_asset_id
        for finding in report.findings
        if finding.code == "D_DELETION_MISMATCH"
    } == {"asset_echo_sd", "asset_ladder_1080p", "asset_ladder_sd"}
```

- [ ] **Step 5: Verify the contract tests**

Run:

```bash
uv run pytest tests/contract/test_duplicate_variant_expansion_pack.py -q --no-cov
```

Expected: all tests pass.

## Task 3: Move Materializer Hash Evidence To Materializer Tests

- [ ] **Step 1: Create a materializer-scoped test file**

Create `tests/materializer/test_duplicate_variant_expansion_pack.py` and move the
hash-evidence assertion there. Keep the test narrow by calling `materialize_one_asset`
directly with mocked `run_ffmpeg` and `probe_file`, not the full `materialize_scenario`
or adapter compare stack.

- [ ] **Step 2: Preserve argv-derived fake bytes**

Use the existing hash payload behavior:

```python
def _synthetic_media_payload(argv: list[str]) -> bytes:
    recipe = "\0".join(argv[:-1]).encode()
    return hashlib.sha256(recipe).hexdigest().encode()
```

Patch `chaos_librarian.materializer.synthesis.run_ffmpeg` so `materialize_one_asset`
still computes real content hashes from written bytes.

- [ ] **Step 3: Delete materializer plumbing from contract test**

Remove the materializer imports, fake capabilities, fake probe, fake ffmpeg, and
`test_duplicate_variant_expansion_pack_materialized_hash_evidence` from
`tests/contract/test_duplicate_variant_expansion_pack.py`.

- [ ] **Step 4: Verify materializer and contract coverage**

Run:

```bash
uv run pytest tests/materializer/test_duplicate_variant_expansion_pack.py -q --no-cov
uv run pytest tests/contract/test_duplicate_variant_expansion_pack.py -q --no-cov
```

Expected: both test files pass.

## Task 4: Final Verification And Commit

- [ ] **Step 1: Run focused branch checks**

Run:

```bash
uv run pytest tests/contract/test_duplicate_variant_expansion_pack.py -q --no-cov
uv run pytest tests/materializer/test_duplicate_variant_expansion_pack.py -q --no-cov
uv run pytest tests/contract/test_sample_scenarios.py -q --no-cov
uv run pytest tests/docs/test_documentation.py -q --no-cov
uv run pytest tests/cli/test_compare.py tests/adapter/test_compare_final_state.py -q --no-cov
```

Expected: all tests pass.

- [ ] **Step 2: Run static checks**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Expected: every command exits `0` with no warnings.

- [ ] **Step 3: Commit**

Run:

```bash
git add tests/support/adapter.py \
  tests/contract/test_duplicate_variant_expansion_pack.py \
  tests/materializer/test_duplicate_variant_expansion_pack.py \
  docs/superpowers/plans/2026-05-23-issue-73-simplification-review-fixes.md
git commit -m "Simplify duplicate variant expansion tests"
```
