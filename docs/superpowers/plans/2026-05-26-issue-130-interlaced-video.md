# Issue 130 Interlaced Video Recipe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional interlaced video recipes for #130.

**Architecture:** Add an optional `VideoTrack.field_order` enum field and keep
progressive video as the default. Phase-A content-source resolution wraps
existing lavfi video recipes with a deterministic double-rate `tinterlace`
pipeline only when `field_order` is set. The ffmpeg argv builder applies the
matching h264/hevc interlace encoder parameter. Capabilities expose interlaced
field-order markers through the existing provider `sources` tuple.

**Tech Stack:** Python 3.13, Pydantic v2, FFmpeg/ffprobe, pytest, ruff, ty,
JSON Schema export.

---

### Task 1: Contract And Schema Version

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `tests/contract/test_contract_constants.py`
- Modify: `tests/contract/test_scenario.py`

- [ ] **Step 1: Write failing contract tests**

Add `VideoFieldOrder` assertions:

```python
def test_video_field_order_enum_values() -> None:
    assert VideoFieldOrder.TOP_FIELD_FIRST.value == "top_field_first"
    assert VideoFieldOrder.BOTTOM_FIELD_FIRST.value == "bottom_field_first"


def test_video_track_field_order_defaults_to_none() -> None:
    track = VideoTrack.model_validate(
        {"source": "color_bars", "codec": "h264", "resolution": "sd"}
    )

    assert track.field_order is None


def test_video_track_accepts_supported_field_order() -> None:
    track = VideoTrack.model_validate(
        {
            "source": "color_bars",
            "codec": "h264",
            "resolution": "sd",
            "field_order": "top_field_first",
        }
    )

    assert track.field_order is VideoFieldOrder.TOP_FIELD_FIRST


def test_video_track_rejects_unknown_field_order() -> None:
    payload = {
        "source": "color_bars",
        "codec": "h264",
        "resolution": "sd",
        "field_order": "sideways",
    }

    with pytest.raises(ValidationError):
        VideoTrack.model_validate(payload)
```

Update schema-version assertions to expect `14`.

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/contract/test_scenario.py \
  tests/contract/test_contract_constants.py -q --no-cov
```

Expected: failures for missing `VideoFieldOrder`, missing `field_order`, and
schema version still being 13.

- [ ] **Step 3: Implement the contract**

Add:

```python
class VideoFieldOrder(enum.StrEnum):
    """Supported interlaced video field orders."""

    TOP_FIELD_FIRST = "top_field_first"
    BOTTOM_FIELD_FIRST = "bottom_field_first"
```

Extend `VideoTrack` with:

```python
field_order: VideoFieldOrder | None = None
```

Bump `SCENARIO_SCHEMA_VERSION` to `14` and change
`Scenario.schema_version` to `Literal[14]`.

- [ ] **Step 4: Verify contract tests pass**

Run the same contract command with `--no-cov`.

### Task 2: Recipes, Evidence, Capabilities, And FFmpeg Args

**Files:**
- Modify: `src/chaos_librarian/materializer/content_sources.py`
- Modify: `src/chaos_librarian/materializer/tooling/recipes.py`
- Modify: `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Modify: `tests/materializer/test_content_sources.py`
- Modify: `tests/materializer/test_recipes.py`
- Modify: `tests/materializer/test_ffmpeg_builder.py`
- Modify: `tests/cli/test_capabilities.py`

- [ ] **Step 1: Write failing recipe/evidence/capability tests**

Add content-source tests that prove:

- `field_order=top_field_first` uses `rate=48` for the default 24 fps request.
- top-field-first lavfi contains
  `tinterlace=mode=interleave_top,setfield=tff`.
- bottom-field-first lavfi contains
  `tinterlace=mode=interleave_bottom,setfield=bff`.
- Field order changes `recipe_digest`.
- A direct provider request with both `field_order` and `vfr_cadence` raises
  `UnsupportedMaterializationError`.
- Capabilities include `video:interlaced:top_field_first` and
  `video:interlaced:bottom_field_first`.

Add pure recipe tests for a helper like:

```python
apply_interlaced_field_order(ffmpeg_input, field_order=VideoFieldOrder.TOP_FIELD_FIRST)
```

Add ffmpeg builder tests that prove:

- h264 top field first emits `-x264-params tff=1`
- h264 bottom field first emits `-x264-params bff=1`
- hevc/h265 top field first emits `-x265-params interlace=tff`
- hevc/h265 bottom field first emits `-x265-params interlace=bff`

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/materializer/test_content_sources.py \
  tests/materializer/test_recipes.py \
  tests/materializer/test_ffmpeg_builder.py \
  tests/cli/test_capabilities.py -q --no-cov
```

- [ ] **Step 3: Implement recipes and ffmpeg args**

In `recipes.py`, add a pure helper that appends the matching `tinterlace` and
`setfield` filters, raising `ValueError` for non-lavfi input.

In `content_sources.py`, extend `VideoSourceRequest` with `field_order`, double
the requested fps only when `field_order` is set, apply interlace wrapping, add
capability markers, include `field_order` in `_request_payload`, and reject
direct requests that set both `field_order` and `vfr_cadence`.

In `preflight.py` and `synthesis.py`, pass `video.field_order` into
`VideoSourceRequest`.

In `ffmpeg.py`, add codec-specific encoder parameters after `-c:v` and
`-preset`.

- [ ] **Step 4: Verify focused tests pass**

Run the same focused command with `--no-cov`.

### Task 3: Validation And Real Materialization

**Files:**
- Modify: `src/chaos_librarian/media_matrix.py`
- Modify: `src/chaos_librarian/validation/rules/materialize_media_matrix.py`
- Modify: `tests/validation/rules/test_materialize_media_matrix.py`
- Create: `tests/fixtures/scenarios/interlaced-video.yaml`
- Modify: `tests/integration/test_materialize_real.py`

- [ ] **Step 1: Write failing validation and real-probe tests**

Add validation coverage that:

- A supported interlaced movie scenario validates cleanly.
- `field_order` combined with `vfr_cadence` returns
  `E_MATERIALIZE_UNSUPPORTED`.

Add a real integration test parametrized over both field orders. Materialize a
Matroska h264 fixture and ffprobe:

```bash
ffprobe -hide_banner -v error -select_streams v:0 \
  -show_entries stream=field_order -of json <file>
```

Expected values:

- `top_field_first`: `tb`
- `bottom_field_first`: `bt`

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/validation/rules/test_materialize_media_matrix.py \
  tests/integration/test_materialize_real.py::test_materialize_interlaced_video_reports_field_order \
  -q --no-cov
```

- [ ] **Step 3: Implement validation**

In `rule_materialize_media_matrix`, when `video.field_order` is present, reject
`vfr_cadence` on the same video mapping. The existing media matrix checks
already reject unsupported video codecs and containers before subprocess
execution.

- [ ] **Step 4: Verify focused tests pass**

Run the same validation/integration command with `--no-cov`.

### Task 4: Schema Artifacts, Fixtures, Docs, And Final Verification

**Files:**
- Modify: `schemas/scenario.schema.json`
- Modify: `docs/contract/schema-reference.md`
- Modify: scenario fixtures and tests that carry the current Scenario version.

- [ ] **Step 1: Sweep current Scenario version references**

Use `rg` to find current-version references that must move from 13 to 14:

```bash
rg -n 'schema_version: 13|"schema_version": 13|schema_version = 13|Scenario v13|SCENARIO_SCHEMA_VERSION == 13' \
  tests docs src
```

Update current fixtures/tests/docs to 14. Preserve historical prose that
intentionally describes Scenario v13.

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

Re-read the diff for unnecessary complexity, run adversarial code review, run
simplification review, address concrete findings, rerun impacted checks, then
commit.
