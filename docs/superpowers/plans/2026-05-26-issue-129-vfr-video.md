# Issue 129 VFR Video Recipe Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add optional variable-frame-rate video cadence recipes for #129.

**Architecture:** Add an optional `VideoTrack.vfr_cadence` enum field and keep
CFR as the default. Phase-A content-source resolution wraps existing lavfi video
recipes with a deterministic 120 fps + `select` cadence filter only when the
field is set. Capabilities expose VFR cadence markers through the existing
provider `sources` tuple.

**Tech Stack:** Python 3.13, Pydantic v2, Typer, FFmpeg/ffprobe, pytest, ruff,
ty, JSON Schema export.

---

### Task 1: Contract And Schema Version

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `tests/contract/test_contract_constants.py`
- Modify: `tests/contract/test_scenario.py`

- [ ] **Step 1: Write failing contract tests**

Add imports for `VideoVfrCadence` in `tests/contract/test_scenario.py`, then add:

```python
def test_video_vfr_cadence_enum_values() -> None:
    assert VideoVfrCadence.TWENTY_FOUR_TO_THIRTY.value == "24_to_30"
    assert VideoVfrCadence.THIRTY_TO_SIXTY.value == "30_to_60"
    assert VideoVfrCadence.TWENTY_FOUR_THIRTY_SIXTY.value == "24_30_60"


def test_video_track_vfr_cadence_defaults_to_none() -> None:
    track = VideoTrack.model_validate(
        {"source": "color_bars", "codec": "h264", "resolution": "sd"}
    )

    assert track.vfr_cadence is None


def test_video_track_accepts_supported_vfr_cadence() -> None:
    track = VideoTrack.model_validate(
        {
            "source": "color_bars",
            "codec": "h264",
            "resolution": "sd",
            "vfr_cadence": "24_to_30",
        }
    )

    assert track.vfr_cadence is VideoVfrCadence.TWENTY_FOUR_TO_THIRTY


def test_video_track_rejects_unknown_vfr_cadence() -> None:
    payload = {
        "source": "color_bars",
        "codec": "h264",
        "resolution": "sd",
        "vfr_cadence": "12_to_144",
    }

    with pytest.raises(ValidationError):
        VideoTrack.model_validate(payload)
```

Update the schema-version assertions in `tests/contract/test_scenario.py` and
`tests/contract/test_contract_constants.py` to expect `13`.

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/contract/test_scenario.py \
  tests/contract/test_contract_constants.py -q
```

Expected: failures for missing `VideoVfrCadence`, missing `vfr_cadence`, and
schema version still being 12.

- [ ] **Step 3: Implement the contract**

In `src/chaos_librarian/contract/__init__.py`, change:

```python
SCENARIO_SCHEMA_VERSION: Final = 13
```

In `src/chaos_librarian/contract/scenario.py`, add:

```python
class VideoVfrCadence(enum.StrEnum):
    """Supported variable-frame-rate cadence transitions."""

    TWENTY_FOUR_TO_THIRTY = "24_to_30"
    THIRTY_TO_SIXTY = "30_to_60"
    TWENTY_FOUR_THIRTY_SIXTY = "24_30_60"
```

Then extend `VideoTrack`:

```python
class VideoTrack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: VideoSource
    codec: str
    resolution: str
    vfr_cadence: VideoVfrCadence | None = None
```

Change `Scenario.schema_version` from `Literal[12]` to `Literal[13]`.

- [ ] **Step 4: Verify contract tests pass**

Run:

```bash
uv run pytest tests/contract/test_scenario.py \
  tests/contract/test_contract_constants.py -q
```

Expected: both files pass except any fixture-version tests that still need the
bulk fixture update in Task 3.

### Task 2: VFR Recipe, Evidence, Capabilities, And Real Probe Tests

**Files:**
- Modify: `src/chaos_librarian/materializer/content_sources.py`
- Modify: `tests/materializer/test_content_sources.py`
- Modify: `tests/materializer/test_recipes.py`
- Modify: `tests/cli/test_capabilities.py`
- Modify: `tests/validation/rules/test_materialize_media_matrix.py`
- Create: `tests/fixtures/scenarios/vfr-video.yaml`
- Modify: `tests/integration/test_materialize_real.py`

- [ ] **Step 1: Write failing recipe/evidence/capability tests**

In `tests/materializer/test_content_sources.py`, update `_video_request()` to
accept `vfr_cadence=None`, then add:

```python
def test_vfr_video_source_uses_select_filter_and_records_cadence() -> None:
    request = _video_request(vfr_cadence=VideoVfrCadence.TWENTY_FOUR_TO_THIRTY)

    resolution = resolve_video_source(source=VideoSource.COLOR_BARS, request=request)

    assert resolution.ffmpeg_input.lavfi is not None
    assert "rate=120" in resolution.ffmpeg_input.lavfi
    assert "select=" in resolution.ffmpeg_input.lavfi
    assert "mod(n,5)" in resolution.ffmpeg_input.lavfi
    assert "mod(n,4)" in resolution.ffmpeg_input.lavfi
```

Add a digest comparison:

```python
def test_vfr_cadence_changes_recipe_digest() -> None:
    cfr = resolve_video_source(source=VideoSource.COLOR_BARS, request=_video_request())
    vfr = resolve_video_source(
        source=VideoSource.COLOR_BARS,
        request=_video_request(vfr_cadence=VideoVfrCadence.THIRTY_TO_SIXTY),
    )

    assert vfr.evidence.recipe_digest != cfr.evidence.recipe_digest
```

In `tests/materializer/test_recipes.py`, add a parametrized test around the new
pure helper:

```python
@pytest.mark.parametrize(
    ("cadence", "expected_mods"),
    [
        (VideoVfrCadence.TWENTY_FOUR_TO_THIRTY, ("mod(n,5)", "mod(n,4)")),
        (VideoVfrCadence.THIRTY_TO_SIXTY, ("mod(n,4)", "mod(n,2)")),
        (VideoVfrCadence.TWENTY_FOUR_THIRTY_SIXTY, ("mod(n,5)", "mod(n,4)", "mod(n,2)")),
    ],
)
def test_apply_vfr_cadence_wraps_lavfi_select_filter(cadence, expected_mods) -> None:
    base = recipe_color_bars(width=640, height=480, fps=120, duration_s=3.0, seed=1)

    wrapped = apply_vfr_cadence(base, cadence=cadence, duration_s=3.0)

    assert wrapped.lavfi is not None
    assert wrapped.lavfi.startswith("smptebars=size=640x480:rate=120,select=")
    for expected in expected_mods:
        assert expected in wrapped.lavfi
    assert wrapped.extra_flags == base.extra_flags
```

Update `test_collect_content_source_capabilities_reports_registered_source_union()`
to expect:

```python
"video:vfr:24_to_30",
"video:vfr:30_to_60",
"video:vfr:24_30_60",
```

In `tests/cli/test_capabilities.py`, add `video:vfr:24_to_30` to the mocked
provider sources and assert the human output contains it.

In `tests/validation/rules/test_materialize_media_matrix.py`, add a validation
smoke test with `vfr_cadence: 24_to_30` in the video block and assert
`report.ok is True`.

- [ ] **Step 2: Write failing real-materialize VFR test**

Create `tests/fixtures/scenarios/vfr-video.yaml` using schema version 13, one
movie asset, `container: mkv`, `source: color_bars`, `codec: h264`,
`resolution: sd`, `duration_seconds: 3.0`, and `vfr_cadence: 24_30_60`.

In `tests/integration/test_materialize_real.py`, add:

```python
def test_materialize_vfr_video_has_variable_packet_intervals(tmp_path: Path) -> None:
    out = tmp_path / "vfr"
    result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "vfr-video.yaml"), "--out", str(out), "--json"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    media_path = next((out / "library").rglob("*.mkv"))

    deltas = _video_packet_deltas(media_path)

    assert len(set(deltas)) > 1
    assert any(delta in {42, 41} for delta in deltas)
    assert 33 in deltas
    assert any(delta in {17, 16} for delta in deltas)
```

Add `_video_packet_deltas(path: Path) -> list[int]` in the test file. It should
run:

```bash
ffprobe -hide_banner -v error -select_streams v:0 \
  -show_entries packet=pts_time -of json <path>
```

Parse consecutive packet `pts_time` values and return rounded millisecond deltas.

- [ ] **Step 3: Verify all new tests fail before production code**

Run:

```bash
uv run pytest tests/materializer/test_content_sources.py \
  tests/materializer/test_recipes.py \
  tests/cli/test_capabilities.py \
  tests/validation/rules/test_materialize_media_matrix.py \
  tests/integration/test_materialize_real.py::test_materialize_vfr_video_has_variable_packet_intervals -q
```

Expected: failures for missing `VideoVfrCadence`, `VideoSourceRequest.vfr_cadence`,
`apply_vfr_cadence`, missing capability markers, or validation/materialize rejection.

- [ ] **Step 4: Implement VFR wrapping and capability markers**

In `src/chaos_librarian/materializer/tooling/recipes.py`, extend the existing
typing import to include `Final` and add:

```python
from typing import Final

from chaos_librarian.contract.scenario import AUDIO_CHANNEL_COUNTS_BY_NAME, VideoVfrCadence

VFR_BASE_FPS: Final = 120

_CADENCE_SELECT_MODS: Final[dict[VideoVfrCadence, tuple[int, ...]]] = {
    VideoVfrCadence.TWENTY_FOUR_TO_THIRTY: (5, 4),
    VideoVfrCadence.THIRTY_TO_SIXTY: (4, 2),
    VideoVfrCadence.TWENTY_FOUR_THIRTY_SIXTY: (5, 4, 2),
}


def apply_vfr_cadence(
    ffmpeg_input: FFmpegInput, *, cadence: VideoVfrCadence, duration_s: float
) -> FFmpegInput:
    if ffmpeg_input.lavfi is None:
        raise ValueError("VFR cadence requires a lavfi video input")
    filters = _vfr_select_filter(cadence=cadence, duration_s=duration_s)
    return FFmpegInput(
        lavfi=f"{ffmpeg_input.lavfi},{filters}",
        extra_flags=ffmpeg_input.extra_flags,
    )
```

Add these helpers below `apply_vfr_cadence()`:

```python
def _vfr_select_filter(*, cadence: VideoVfrCadence, duration_s: float) -> str:
    mods = _CADENCE_SELECT_MODS[cadence]
    segment_s = duration_s / len(mods)
    expression = _select_expression(mods=mods, segment_s=segment_s)
    return f"select='{expression}'"


def _select_expression(*, mods: tuple[int, ...], segment_s: float) -> str:
    expression = f"not(mod(n,{mods[-1]}))"
    for index in range(len(mods) - 2, -1, -1):
        boundary = round(segment_s * (index + 1), 6)
        expression = f"if(lt(t,{boundary}),not(mod(n,{mods[index]})),{expression})"
    return expression
```

In `src/chaos_librarian/materializer/content_sources.py`, import
`VideoVfrCadence`, `VFR_BASE_FPS`, and `apply_vfr_cadence`; add
`vfr_cadence: VideoVfrCadence | None = None` to `VideoSourceRequest`. In
`resolve_video_input()`, call the existing recipe at `VFR_BASE_FPS` when cadence
is set, then wrap it with `apply_vfr_cadence()`. Include `vfr_cadence` in
`_request_payload()`.

Also add:

```python
VFR_CAPABILITY_SOURCES: Final[tuple[str, ...]] = tuple(
    f"video:vfr:{cadence.value}" for cadence in VideoVfrCadence
)
```

Append `*VFR_CAPABILITY_SOURCES` to `_BuiltinLavfiProvider.capability()`.

- [ ] **Step 5: Verify VFR tests pass**

Run:

```bash
uv run pytest tests/materializer/test_content_sources.py \
  tests/materializer/test_recipes.py \
  tests/cli/test_capabilities.py \
  tests/validation/rules/test_materialize_media_matrix.py \
  tests/integration/test_materialize_real.py::test_materialize_vfr_video_has_variable_packet_intervals -q
```

Expected: selected tests pass.

### Task 3: Schema Artifacts And Fixture Version Sweep

**Files:**
- Modify: `schemas/scenario.schema.json`
- Modify: all scenario fixtures and tests that embed `schema_version: 12`

- [ ] **Step 1: Update fixture/test scenario versions**

Find current contract literals:

```bash
rg -n "schema_version: 12|schema_version=12|schema_version\\\": 12|schema_version == 12|SCENARIO_SCHEMA_VERSION == 12" tests src schemas
```

Update only current contract fixtures, test payloads, and assertions to version
13. Do not touch historical docs that describe older sprints.

- [ ] **Step 2: Regenerate schema artifacts**

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
```

Expected: schema export rewrites `schemas/scenario.schema.json`.

- [ ] **Step 3: Verify schema drift gate**

Run:

```bash
uv run python -m chaos_librarian.schema_export --check
```

Expected: all schemas up-to-date.

### Task 4: Final Review And Verification

**Files:**
- Review all changed files.

- [ ] **Step 1: Run focused tests**

Run:

```bash
uv run pytest tests/contract/test_scenario.py \
  tests/contract/test_contract_constants.py \
  tests/materializer/test_content_sources.py \
  tests/materializer/test_recipes.py \
  tests/cli/test_capabilities.py \
  tests/validation/rules/test_materialize_media_matrix.py \
  tests/integration/test_materialize_real.py::test_materialize_vfr_video_has_variable_packet_intervals -q
```

Expected: selected tests pass.

- [ ] **Step 2: Run lint, format, type, schema, and relevant suite**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
uv run pytest -q
```

Expected: every command exits 0 with no warnings.

- [ ] **Step 3: Run adversarial code review and simplification review**

Review the working-tree diff for correctness risks. Address material findings,
then review for safe simplification and address the highest-leverage concrete
recommendations before opening the PR.
