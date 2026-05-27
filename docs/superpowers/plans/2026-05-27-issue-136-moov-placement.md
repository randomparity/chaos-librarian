# Issue 136 MP4 Moov Placement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MP4 `moov` atom placement options for static materialization.

**Architecture:** Add an optional `Asset.mp4_moov_placement` enum field, pass it
to the FFmpeg builder, and record the chosen option on `MaterializedAsset`.
Validation owns author-facing misuse, while the FFmpeg builder also rejects
non-MP4 placement for direct callers.

**Tech Stack:** Pydantic v2 contracts, Typer validation pipeline, FFmpeg
`-movflags +faststart`, pytest, ruff, ty.

---

## File Map

- `src/chaos_librarian/contract/scenario.py`: new `Mp4MoovPlacement` enum and
  optional `Asset.mp4_moov_placement`.
- `src/chaos_librarian/contract/materialization.py`: optional
  `MaterializedAsset.mp4_moov_placement`.
- `src/chaos_librarian/contract/__init__.py`: bump scenario and materialization
  schema constants.
- `src/chaos_librarian/validation/rules/materialize_media_matrix.py`: reject
  placement requests on non-MP4 assets.
- `src/chaos_librarian/materializer/tooling/ffmpeg.py`: add `-movflags
  +faststart` for `moov_at_start`.
- `src/chaos_librarian/materializer/synthesis.py`: pass the asset option into
  FFmpeg and materialization evidence.
- `schemas/*.schema.json`: regenerated schema artifacts.
- `docs/contract/schema-reference.md`: current version table and v20/v13 note.
- Tests under `tests/contract/`, `tests/validation/`, `tests/materializer/`,
  and `tests/integration/`.

## Task 1: Contract And Evidence Shape

**Files:**
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/contract/materialization.py`
- Modify: `src/chaos_librarian/contract/__init__.py`
- Test: `tests/contract/test_scenario.py`
- Test: `tests/contract/test_materialization.py`
- Test: `tests/contract/test_contract_constants.py`

- [ ] **Step 1: Write failing contract tests**

Add tests for enum values, asset round-trip, invalid values, materialized
evidence, and version constants. Import `Mp4MoovPlacement` from
`chaos_librarian.contract.scenario` in `test_materialization.py`.

```python
def test_mp4_moov_placement_asset_round_trip() -> None:
    payload = _base_payload()
    asset = _video_asset_payload("asset_moov")
    asset["container"] = "mp4"
    asset["mp4_moov_placement"] = "moov_at_start"
    payload["movies"] = [
        {
            "id": "movie_moov",
            "title": "Moov",
            "layout": "movie_flat",
            "variants": [_variant_payload(asset)],
        }
    ]

    scenario = Scenario.model_validate(payload)

    assert scenario.movies[0].variants[0].bundle.assets[0].mp4_moov_placement.value == (
        "moov_at_start"
    )


def test_mp4_moov_placement_rejects_unknown_value() -> None:
    payload = _base_payload()
    asset = _video_asset_payload("asset_moov")
    asset["container"] = "mp4"
    asset["mp4_moov_placement"] = "middle"
    payload["movies"] = [
        {
            "id": "movie_moov",
            "title": "Moov",
            "layout": "movie_flat",
            "variants": [_variant_payload(asset)],
        }
    ]

    with pytest.raises(ValidationError):
        Scenario.model_validate(payload)
```

In `test_materialization.py`, assert:

```python
asset = MaterializedAsset(
    asset_id="asset_mp4",
    location_path="library/movie/main.mp4",
    content_hash="sha256:" + "0" * 64,
    size_bytes=100,
    duration_seconds=1.0,
    invocation_index=0,
    mp4_moov_placement=Mp4MoovPlacement.MOOV_AT_START,
)
assert asset.model_dump(mode="json")["mp4_moov_placement"] == "moov_at_start"
```

Update constant expectations:

```python
assert SCENARIO_SCHEMA_VERSION == 20
assert MATERIALIZATION_SCHEMA_VERSION == 13
```

Update direct scenario/materialization version assertions in existing tests:

```python
assert scenario.schema_version == 20
```

Rename version-specific test names from `v19`/`nineteen` and `twelve` to
`v20`/`twenty` and `thirteen` in the touched contract test files.

- [ ] **Step 2: Run tests to verify RED**

```bash
uv run pytest --no-cov \
  tests/contract/test_scenario.py \
  tests/contract/test_materialization.py \
  tests/contract/test_contract_constants.py -q
```

Expected: failures for missing `Mp4MoovPlacement`, missing asset field, and old
schema literals.

- [ ] **Step 3: Implement contract shape**

Add:

```python
class Mp4MoovPlacement(enum.StrEnum):
    """MP4 top-level moov atom placement requested at mux time."""

    MOOV_AT_START = "moov_at_start"
    MOOV_AT_END = "moov_at_end"
```

Add to `Asset`:

```python
mp4_moov_placement: Mp4MoovPlacement | None = None
```

Add to `MaterializedAsset`:

```python
mp4_moov_placement: Mp4MoovPlacement | None = None
```

Bump constants and matching model literals:

```python
SCENARIO_SCHEMA_VERSION: Final = 20
MATERIALIZATION_SCHEMA_VERSION: Final = 13
schema_version: Literal[20]
schema_version: Literal[13]
```

- [ ] **Step 4: Run tests to verify GREEN**

```bash
uv run pytest --no-cov \
  tests/contract/test_scenario.py \
  tests/contract/test_materialization.py \
  tests/contract/test_contract_constants.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/contract tests/contract
git commit -m "Add MP4 moov placement contracts"
```

## Task 2: Validation Rule

**Files:**
- Modify: `src/chaos_librarian/validation/rules/materialize_media_matrix.py`
- Create: `tests/fixtures/scenarios/invalid/mp4-moov-placement-non-mp4.yaml`
- Test: `tests/validation/rules/test_materialize_media_matrix.py`
- Test: `tests/validation/test_invalid_corpus.py`

- [ ] **Step 1: Write failing validation tests**

Add a validation test using the existing temp-scenario pattern:

```python
def test_mp4_moov_placement_rejected_on_non_mp4(tmp_path: Path) -> None:
    scenario = tmp_path / "mp4-moov-on-mkv.yaml"
    _write_movie_scenario(
        scenario,
        container="mkv",
        mp4_moov_placement="moov_at_start",
    )

    path = _first_materialize_issue_path(scenario)

    assert path.endswith(".assets.0.mp4_moov_placement")
```

Extend `_write_movie_scenario()` in the same test file with:

```python
container: str = "mkv",
mp4_moov_placement: str | None = None,
```

and render:

```python
moov_line = (
    f"              mp4_moov_placement: {mp4_moov_placement}\n"
    if mp4_moov_placement
    else ""
)
...
              container: {container}
{moov_line.rstrip()}
```

Add invalid corpus fixture:

```yaml
# expected: E_MATERIALIZE_UNSUPPORTED
schema_version: 20
scenario_id: invalid-mp4-moov-placement-non-mp4
seed: 136
duration_scale: short
library: {roots: [{id: root_main, path: library}]}
movies:
  - id: movie_bad
    title: Bad Moov
    layout: movie_flat
    variants:
      - id: variant_bad
        label: mkv
        bundle:
          id: bundle_bad
          assets:
            - id: asset_bad
              role: main
              container: mkv
              mp4_moov_placement: moov_at_start
              duration_seconds: 1.0
              video: {source: color_bars, codec: h264, resolution: sd}
              audio: [{source: sine, codec: aac, channels: stereo, language: eng}]
series: []
artists: []
timeline: []
```

- [ ] **Step 2: Run tests to verify RED**

```bash
uv run pytest --no-cov \
  tests/validation/rules/test_materialize_media_matrix.py::test_mp4_moov_placement_rejected_on_non_mp4 \
  'tests/validation/test_invalid_corpus.py::test_invalid_fixture_produces_expected_code[mp4-moov-placement-non-mp4.yaml]' \
  -q
```

Expected: the raw-rule test fails because no issue is reported.

- [ ] **Step 3: Implement validation**

Add helper:

```python
def _check_mp4_moov_placement(
    *,
    asset: Mapping[str, object],
    asset_loc: _Loc,
    reporter: Reporter,
) -> None:
    placement = asset.get("mp4_moov_placement")
    if not isinstance(placement, str):
        return
    if asset.get("container") == "mp4":
        return
    reporter.error(
        code=E_MATERIALIZE_UNSUPPORTED,
        message="mp4_moov_placement is only supported for mp4 assets",
        loc=(*asset_loc, "mp4_moov_placement"),
    )
```

Call it at the start of `_check_video_asset()` and `_check_track_asset()`.

- [ ] **Step 4: Run tests to verify GREEN**

```bash
uv run pytest --no-cov \
  tests/validation/rules/test_materialize_media_matrix.py::test_mp4_moov_placement_rejected_on_non_mp4 \
  'tests/validation/test_invalid_corpus.py::test_invalid_fixture_produces_expected_code[mp4-moov-placement-non-mp4.yaml]' \
  -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/validation tests/validation tests/fixtures/scenarios/invalid
git commit -m "Validate MP4 moov placement container"
```

## Task 3: FFmpeg Builder And Materialized Evidence

**Files:**
- Modify: `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Test: `tests/materializer/test_ffmpeg_builder.py`
- Test: `tests/materializer/test_synthesis.py`

- [ ] **Step 1: Write failing FFmpeg and evidence tests**

In `test_ffmpeg_builder.py`:

```python
def test_mp4_moov_at_start_adds_faststart(tmp_path: Path) -> None:
    argv = build_command(
        video=_video(),
        video_input=recipe_color_bars(width=640, height=480, fps=24, duration_s=1.0, seed=1),
        audios=[_audio()],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=tmp_path / "asset.mp4",
        mp4_moov_placement=Mp4MoovPlacement.MOOV_AT_START,
    )

    assert argv[argv.index("-movflags") + 1] == "+faststart"


def test_mp4_moov_at_end_uses_default_mp4_order(tmp_path: Path) -> None:
    argv = build_command(
        video=_video(),
        video_input=recipe_color_bars(width=640, height=480, fps=24, duration_s=1.0, seed=1),
        audios=[_audio()],
        audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
        output_path=tmp_path / "asset.mp4",
        mp4_moov_placement=Mp4MoovPlacement.MOOV_AT_END,
    )

    assert "-movflags" not in argv
```

Add non-MP4 direct-call rejection:

```python
with pytest.raises(UnsupportedMaterializationError) as exc:
    build_command(..., output_path=tmp_path / "asset.mkv",
                  mp4_moov_placement=Mp4MoovPlacement.MOOV_AT_START)
assert exc.value.field == "mp4_moov_placement"
```

In `test_synthesis.py`, assert `materialize_one_asset()` passes
`asset.mp4_moov_placement` into `build_command()` and stores it on the returned
`MaterializedAsset`.

- [ ] **Step 2: Run tests to verify RED**

```bash
uv run pytest --no-cov \
  tests/materializer/test_ffmpeg_builder.py \
  tests/materializer/test_synthesis.py -q
```

Expected: failures for unknown parameter/evidence.

- [ ] **Step 3: Implement FFmpeg args and evidence**

Add to `build_command()`:

```python
mp4_moov_placement: Mp4MoovPlacement | None = None,
```

Reject non-MP4:

```python
if mp4_moov_placement is not None and container != "mp4":
    raise UnsupportedMaterializationError(
        "mp4_moov_placement is only supported for mp4 assets",
        field="mp4_moov_placement",
        payload={"container": container},
    )
```

Add output args in `_build_video_command()`:

```python
if mp4_moov_placement is Mp4MoovPlacement.MOOV_AT_START:
    argv.extend(["-movflags", "+faststart"])
```

Pass from synthesis:

```python
mp4_moov_placement=asset.mp4_moov_placement,
```

Record evidence:

```python
mp4_moov_placement=asset.mp4_moov_placement,
```

- [ ] **Step 4: Run tests to verify GREEN**

```bash
uv run pytest --no-cov \
  tests/materializer/test_ffmpeg_builder.py \
  tests/materializer/test_synthesis.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add src/chaos_librarian/materializer tests/materializer
git commit -m "Materialize MP4 moov placement"
```

## Task 4: Real MP4 Atom-Order Fixture

**Files:**
- Create: `tests/fixtures/scenarios/mp4-moov-placement.yaml`
- Create: `tests/integration/test_mp4_moov_placement_real.py`

- [ ] **Step 1: Write failing integration fixture and test**

Create one scenario with two MP4 assets, one `moov_at_start` and one
`moov_at_end`. The test should materialize it and parse top-level MP4 atoms:

```python
def _top_level_atom_offsets(path: Path) -> dict[str, int]:
    offsets: dict[str, int] = {}
    with path.open("rb") as fh:
        file_size = path.stat().st_size
        offset = 0
        while offset + 8 <= file_size:
            fh.seek(offset)
            header = fh.read(8)
            size = int.from_bytes(header[:4], "big")
            atom = header[4:].decode("ascii", errors="replace")
            offsets.setdefault(atom, offset)
            if size == 1:
                size = int.from_bytes(fh.read(8), "big")
            elif size == 0:
                break
            offset += size
    return offsets
```

Assert:

```python
start_offsets = _top_level_atom_offsets(start_path)
end_offsets = _top_level_atom_offsets(end_path)
assert start_offsets["moov"] < start_offsets["mdat"]
assert end_offsets["mdat"] < end_offsets["moov"]
```

Also assert materialization evidence:

```python
placements = {item.asset_id: item.mp4_moov_placement for item in report.materialized}
assert placements["asset_moov_start"] is Mp4MoovPlacement.MOOV_AT_START
assert placements["asset_moov_end"] is Mp4MoovPlacement.MOOV_AT_END
```

- [ ] **Step 2: Run test to verify RED or behavior gap**

```bash
uv run pytest --no-cov tests/integration/test_mp4_moov_placement_real.py -q
```

Expected: pass if Task 3 already fully wired FFmpeg, otherwise fail on atom
order or evidence. If it passes immediately, keep it as the real-tool
regression check for Task 3.

- [ ] **Step 3: Fix only integration-discovered gaps**

Adjust FFmpeg args only if the real MP4 atom ordering test fails. Do not add
extra muxing modes.

- [ ] **Step 4: Run test to verify GREEN**

```bash
uv run pytest --no-cov tests/integration/test_mp4_moov_placement_real.py -q
```

Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/scenarios/mp4-moov-placement.yaml \
  tests/integration/test_mp4_moov_placement_real.py
git commit -m "Add MP4 moov placement fixture"
```

## Task 5: Schema Artifacts And Docs

**Files:**
- Modify: `schemas/*.schema.json`
- Modify: `tests/fixtures/scenarios/**/*.yaml`
- Modify: test literals containing `schema_version: 19`
- Modify: `docs/contract/schema-reference.md`

- [ ] **Step 1: Verify stale schema-version failures**

```bash
uv run pytest --no-cov tests/contract/test_sample_scenarios.py -q
```

Expected: failures saying Scenario expects schema version 20.

- [ ] **Step 2: Mechanically migrate scenario literals**

```bash
rg -l 'schema_version: 19' tests src | xargs perl -0pi -e 's/schema_version: 19/schema_version: 20/g'
rg -l '"schema_version": 19' tests src | xargs perl -0pi -e 's/"schema_version": 19/"schema_version": 20/g'
rg -l 'schema_version=19' tests src | xargs perl -0pi -e 's/schema_version=19/schema_version=20/g'
```

Do not edit historical plan/spec files.

- [ ] **Step 3: Regenerate schemas**

```bash
uv run python -m chaos_librarian.schema_export --write
uv run python -m chaos_librarian.schema_export --check
```

Expected: writes 21 schemas, then reports all up to date.

- [ ] **Step 4: Update docs**

In `docs/contract/schema-reference.md`, set scenario to 20 and materialization
to 13. Add:

```markdown
Scenario v20 adds MP4 `moov` atom placement options on assets. Materialization
v13 records the selected MP4 placement on each materialized asset.
```

- [ ] **Step 5: Run focused verification**

```bash
uv run pytest --no-cov \
  tests/contract \
  tests/validation \
  tests/materializer/test_ffmpeg_builder.py \
  tests/materializer/test_synthesis.py \
  tests/integration/test_mp4_moov_placement_real.py \
  tests/docs/test_documentation.py::test_schema_reference_lists_current_contract_versions \
  -q
```

Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add schemas docs tests src
git commit -m "Regenerate schemas for MP4 moov placement"
```

## Final Verification

- [ ] Run adversarial code review against `origin/main...HEAD` and address up
  to three rounds of material findings.
- [ ] Run simplification review and apply the highest-value safe simplification.
- [ ] Run final checks:

```bash
uv run python -m chaos_librarian.schema_export --check
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run pytest -q
git diff --check
```

- [ ] Push branch, open PR with `Closes #136`, monitor CI, merge, verify the
  issue closes.
