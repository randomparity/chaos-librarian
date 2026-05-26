# Issue 131 SDR Color Signaling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional SDR color-space and color-range signaling for #131.

**Architecture:** Add optional `VideoTrack.color_space` and
`VideoTrack.color_range` enum fields. These values do not change the lavfi
source, but they are included in `VideoSourceRequest` so replay evidence changes
when signaling changes. Video content-source evidence carries the selected
values when present. The ffmpeg argv builder emits output-side `-colorspace` and
`-color_range` flags.

**Tech Stack:** Python 3.13, Pydantic v2, FFmpeg/ffprobe, pytest, ruff, ty,
JSON Schema export.

---

### Task 1: Contract And Schema Version

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `tests/contract/test_contract_constants.py`
- Modify: `tests/contract/test_scenario.py`
- Modify: `src/chaos_librarian/contract/content_sources.py`
- Modify: `src/chaos_librarian/contract/materialization.py`
- Modify: `src/chaos_librarian/contract/replay_bundle.py`
- Modify: `tests/contract/test_content_sources.py`
- Modify: `tests/contract/test_materialization.py`
- Modify: `tests/contract/test_replay_bundle.py`

- [ ] **Step 1: Write failing contract tests**

Add enum/default/accept/reject tests for:

```python
VideoColorSpace.BT601 == "bt601"
VideoColorSpace.BT709 == "bt709"
VideoColorSpace.BT2020 == "bt2020"
VideoColorRange.LIMITED == "limited"
VideoColorRange.FULL == "full"
```

Assert `VideoTrack` defaults both fields to `None`, accepts
`color_space="bt709"` and `color_range="full"`, rejects unknown values, and
updates Scenario version expectations to `15`.

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/contract/test_scenario.py \
  tests/contract/test_contract_constants.py -q --no-cov
```

- [ ] **Step 3: Implement the contract**

Add `VideoColorSpace` and `VideoColorRange` enum classes, add the optional
fields to `VideoTrack`, bump `SCENARIO_SCHEMA_VERSION` to `15`, and change
`Scenario.schema_version` to `Literal[15]`. Add optional `color_space` and
`color_range` fields to `ContentSourceEvidence`; bump materialization schema
version to `10` and replay bundle schema version to `8` because materialize/run
JSON can now include those fields.

- [ ] **Step 4: Verify contract tests pass**

Run the same contract command with `--no-cov`.

### Task 2: Evidence, Capabilities, And FFmpeg Args

**Files:**
- Modify: `src/chaos_librarian/materializer/content_sources.py`
- Modify: `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Modify: `tests/materializer/test_content_sources.py`
- Modify: `tests/materializer/test_ffmpeg_builder.py`
- Modify: `tests/cli/test_capabilities.py`

- [ ] **Step 1: Write failing tests**

Add content-source tests that prove:

- `color_space` changes `recipe_digest`.
- `color_range` changes `recipe_digest`.
- Video evidence carries selected `color_space` and `color_range` values.
- Capabilities include all five markers:
  `video:color_space:bt601`, `video:color_space:bt709`,
  `video:color_space:bt2020`, `video:color_range:limited`,
  `video:color_range:full`.

Add ffmpeg builder tests that prove:

- `bt601` emits `-colorspace smpte170m`
- `bt709` emits `-colorspace bt709`
- `bt2020` emits `-colorspace bt2020nc`
- `limited` emits `-color_range tv`
- `full` emits `-color_range pc`

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/materializer/test_content_sources.py \
  tests/materializer/test_ffmpeg_builder.py \
  tests/cli/test_capabilities.py -q --no-cov
```

- [ ] **Step 3: Implement plumbing and argv output flags**

Extend `VideoSourceRequest` with `color_space` and `color_range`, include both
in `_request_payload`, add capability marker tuples, and pass the scenario
fields from preflight/synthesis.

In `ffmpeg.py`, map contract values to ffmpeg output args:

```python
bt601 -> smpte170m
bt709 -> bt709
bt2020 -> bt2020nc
limited -> tv
full -> pc
```

- [ ] **Step 4: Verify focused tests pass**

Run the same focused command with `--no-cov`.

### Task 3: Real Materialization And Validation Surface

**Files:**
- Modify: `tests/validation/test_shape.py`
- Modify: `tests/validation/rules/test_materialize_media_matrix.py`
- Create: `tests/fixtures/scenarios/color-signaling-video.yaml`
- Modify: `tests/integration/test_materialize_real.py`

- [ ] **Step 1: Write failing tests**

Add validation coverage for a supported color-signaling movie scenario. Shape
validation already rejects unknown enum values, so add a public validation
pipeline test proving an unsupported `color_space` value fails before
materialization. No extra semantic rule is needed for the first slice.

Add a real ffprobe integration test parametrized over the full supported SDR
matrix:

- `bt601` + `limited` -> `smpte170m` + `tv`
- `bt601` + `full` -> `smpte170m` + `pc`
- `bt709` + `limited` -> `bt709` + `tv`
- `bt709` + `full` -> `bt709` + `pc`
- `bt2020` + `limited` -> `bt2020nc` + `tv`
- `bt2020` + `full` -> `bt2020nc` + `pc`

Assert `materialization.json` and `replay.json` content-source evidence expose
the selected contract values.

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/validation/rules/test_materialize_media_matrix.py \
  tests/integration/test_materialize_real.py::test_materialize_color_signaling_reports_metadata \
  -q --no-cov
```

- [ ] **Step 3: Implement only what the tests require**

No new semantic rule is expected. If the validation clean test fails, fix
scenario shape/schema-version setup rather than adding redundant validation.

- [ ] **Step 4: Verify focused tests pass**

Run the same focused command with `--no-cov`.

### Task 4: Schema Artifacts, Current-Version Sweep, And Final Verification

**Files:**
- Modify: `schemas/scenario.schema.json`
- Modify: `schemas/materialization.schema.json`
- Modify: `schemas/replay-bundle.schema.json`
- Modify: `docs/contract/schema-reference.md`
- Modify: scenario fixtures/tests that carry the current Scenario version.

- [ ] **Step 1: Sweep current Scenario version references**

Use `rg` to find current-version references that must move from 14 to 15:

```bash
rg -n 'schema_version: 14|"schema_version": 14|schema_version=14|schema_version == 14|SCENARIO_SCHEMA_VERSION == 14|scenario \\| 14' \
  tests src docs/contract schemas
```

Preserve historical prose that intentionally describes Scenario v14.

- [ ] **Step 2: Regenerate schemas**

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
uv run python -m chaos_librarian.schema_export --check
```

- [ ] **Step 3: Run verification gates**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run pytest -q
```

- [ ] **Step 4: Review and commit**

Run adversarial code review, address concrete findings, run simplification
review, address the most relevant simplification, rerun impacted checks, then
commit.
