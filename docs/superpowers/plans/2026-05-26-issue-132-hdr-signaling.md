# Issue 132 HDR Signaling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add HEVC-only synthetic HDR10 and HLG signaling for #132.

**Architecture:** Add optional `VideoTrack.hdr_mode` and gate it through validation, capability detection, preflight, recipe evidence, and ffmpeg command construction. HDR output owns BT.2020/limited color signaling and uses libx265 plus `setparams` to produce probe-visible transfer metadata.

**Tech Stack:** Python 3.13, Pydantic v2, FFmpeg/ffprobe, pytest, ruff, ty, JSON Schema export.

---

### Task 1: Scenario And Capabilities Contract

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/contract/capabilities.py`
- Modify: `tests/contract/test_contract_constants.py`
- Modify: `tests/contract/test_scenario.py`
- Modify: `tests/contract/test_capabilities.py`
- Modify: tests constructing `ReadyFor`

- [ ] **Step 1: Write failing contract tests**

Add Scenario tests for:

```python
def test_video_hdr_mode_enum_values() -> None:
    assert VideoHdrMode.HDR10.value == "hdr10"
    assert VideoHdrMode.HLG.value == "hlg"


def test_video_track_defaults_hdr_mode_to_none() -> None:
    track = VideoTrack(source="color_bars", codec="hevc", resolution="sd")
    assert track.hdr_mode is None


def test_video_track_accepts_hdr_mode() -> None:
    track = VideoTrack.model_validate(
        {"source": "color_bars", "codec": "hevc", "resolution": "sd", "hdr_mode": "hdr10"}
    )
    assert track.hdr_mode is VideoHdrMode.HDR10


def test_video_track_rejects_unknown_hdr_mode() -> None:
    payload = {"source": "color_bars", "codec": "hevc", "resolution": "sd", "hdr_mode": "pqish"}
    with pytest.raises(ValidationError):
        VideoTrack.model_validate(payload)
```

Update current Scenario version tests to `16`.

Add Capabilities tests for:

```python
ready_for=ReadyFor(
    materialize_static=True,
    materialize_filesystem_mutations=True,
    materialize_media_mutations=False,
    materialize_hevc_video=True,
    materialize_hdr_video=True,
)
```

Assert `CAPABILITIES_SCHEMA_VERSION == 4`, `Capabilities.schema_version` is `4`,
and a payload missing `materialize_hdr_video` fails validation.

- [ ] **Step 2: Verify contract tests fail**

Run:

```bash
uv run pytest tests/contract/test_scenario.py \
  tests/contract/test_capabilities.py \
  tests/contract/test_contract_constants.py -q --no-cov
```

Expected: failures for missing `VideoHdrMode`, `hdr_mode`, capabilities v4, and
the new `ReadyFor` field.

- [ ] **Step 3: Implement the contracts**

Add `VideoHdrMode` to `src/chaos_librarian/contract/scenario.py`:

```python
class VideoHdrMode(enum.StrEnum):
    """Supported HDR video signaling modes."""

    HDR10 = "hdr10"
    HLG = "hlg"
```

Add `hdr_mode: VideoHdrMode | None = None` to `VideoTrack`, bump
`SCENARIO_SCHEMA_VERSION` to `16`, and change `Scenario.schema_version` to
`Literal[16]`.

In `contract/capabilities.py`, add
`materialize_hdr_video: bool` to `ReadyFor` and change
`Capabilities.schema_version` to `Literal[4]`. Bump
`CAPABILITIES_SCHEMA_VERSION` to `4`.

Update all test helpers and fake capabilities that construct `ReadyFor`.

- [ ] **Step 4: Verify contract tests pass**

Run the same contract command with `--no-cov`.

### Task 2: Capability Detection And Content-Source Markers

**Files:**
- Modify: `src/chaos_librarian/materializer/tooling/capabilities.py`
- Modify: `src/chaos_librarian/materializer/content_sources.py`
- Modify: `tests/materializer/test_capabilities.py`
- Modify: `tests/materializer/test_content_sources.py`
- Modify: `tests/cli/test_capabilities.py`

- [ ] **Step 1: Write failing tests**

In `tests/materializer/test_capabilities.py`, extend the subprocess stub to
return:

```python
FILTERS_WITH_SETPARAMS = "Filters:\n .. setparams         V->V"
FILTERS_WITHOUT_SETPARAMS = "Filters:\n TS colorspace        V->V"
X265_HELP_10BIT = "Supported pixel formats: yuv420p yuv420p10le"
X265_HELP_8BIT = "Supported pixel formats: yuv420p"
```

Add tests proving:

- all requirements present sets `caps.ready_for.materialize_hdr_video` true,
- missing `setparams` sets it false,
- missing `yuv420p10le` sets it false,
- HDR markers are omitted from provider sources when unavailable.

In `tests/materializer/test_content_sources.py`, update
`collect_content_source_capabilities` calls to pass `hdr_available=True` or
`False`. Assert `video:hdr:hdr10` and `video:hdr:hlg` appear only when true.

In `tests/cli/test_capabilities.py`, assert JSON and human output include
`materialize_hdr_video` and the HDR source marker when mocked as available.

- [ ] **Step 2: Verify tests fail**

Run:

```bash
uv run pytest tests/materializer/test_capabilities.py \
  tests/materializer/test_content_sources.py \
  tests/cli/test_capabilities.py -q --no-cov
```

- [ ] **Step 3: Implement detection and markers**

Add helpers in `tooling/capabilities.py` with these signatures and behavior:

```python
def _ffmpeg_filter_available(ffmpeg: ToolStatus, filter_name: str) -> bool:
    """Return whether FFmpeg advertises a named filter."""


def _ffmpeg_encoder_supports_pixel_format(
    ffmpeg: ToolStatus, *, encoder: str, pixel_format: str
) -> bool:
    """Return whether encoder help advertises a pixel format."""


def _ffmpeg_hdr_signaling_available(ffmpeg: ToolStatus, ffprobe: ToolStatus) -> bool:
    """Return whether this host can synthesize probe-visible HDR HEVC."""
```

`_ffmpeg_hdr_signaling_available` returns true only when ffmpeg and ffprobe meet
minimum versions, `libx265` exists, `setparams` exists, and libx265 supports
`yuv420p10le`.

Change `collect_content_source_capabilities` to:

```python
def collect_content_source_capabilities(
    ffmpeg_available: bool, *, hdr_available: bool = False
) -> ContentSourceCapabilities:
```

Add `HDR_CAPABILITY_SOURCES = ("video:hdr:hdr10", "video:hdr:hlg")` and include
it only when `hdr_available`.

In `detect_capabilities`, pass `hdr_available=hdr_video_available` and set
`ReadyFor.materialize_hdr_video=hdr_video_available`.

- [ ] **Step 4: Verify focused tests pass**

Run the same focused command with `--no-cov`.

### Task 3: Validation And Capability Gates

**Files:**
- Modify: `src/chaos_librarian/validation/rules/materialize_media_matrix.py`
- Create: `src/chaos_librarian/materializer/capability_gates.py`
- Modify: `src/chaos_librarian/materializer/run.py`
- Modify: `src/chaos_librarian/materializer/wall_clock.py`
- Modify: `src/chaos_librarian/materializer/replay.py`
- Modify: `tests/validation/rules/test_materialize_media_matrix.py`
- Modify: `tests/materializer/test_run.py`
- Modify: `tests/materializer/test_wall_clock.py`
- Modify: `tests/materializer/test_replay.py`

- [ ] **Step 1: Write failing validation tests**

Extend `_write_movie_scenario` in
`tests/validation/rules/test_materialize_media_matrix.py` with `hdr_mode`.

Add tests:

```python
def test_hdr_signaling_validates_clean(tmp_path: Path) -> None:
    scenario = tmp_path / "hdr.yaml"
    _write_movie_scenario(scenario, video_codec="hevc", hdr_mode="hdr10")
    report = run_validation(prepare_run_input(scenario))
    assert report.ok is True
    assert report.issues == []


def test_hdr_signaling_rejects_h264(tmp_path: Path) -> None:
    scenario = tmp_path / "hdr-h264.yaml"
    _write_movie_scenario(scenario, video_codec="h264", hdr_mode="hdr10")
    report = run_validation(prepare_run_input(scenario))
    issue = next(issue for issue in report.issues if issue.code == codes.E_MATERIALIZE_UNSUPPORTED)
    assert issue.path is not None
    assert issue.path.endswith(".video.hdr_mode")
```

Add matching rejection tests for `color_space="bt709"`, `color_range="full"`,
`vfr_cadence="24_to_30"`, and `field_order="top_field_first"`.

- [ ] **Step 2: Write failing capability-gate tests**

In materializer run/wall-clock/replay tests, use a scenario with
`video.codec: hevc` and `hdr_mode: hdr10`, patch capabilities with
`materialize_hevc_video=True` and `materialize_hdr_video=False`, and assert
`CapabilityGateError.field == "ready_for.materialize_hdr_video"` before the run
directory exists.

- [ ] **Step 3: Verify tests fail**

Run:

```bash
uv run pytest tests/validation/rules/test_materialize_media_matrix.py \
  tests/materializer/test_run.py \
  tests/materializer/test_wall_clock.py \
  tests/materializer/test_replay.py -q --no-cov
```

- [ ] **Step 4: Implement validation and gates**

In `materialize_media_matrix.py`, add `_check_hdr_video` called from
`_check_video`. Use `HEVC_VIDEO_CODECS` from `media_matrix` and reject:

- codec not in `HEVC_VIDEO_CODECS`,
- `color_space` not in `{None, "bt2020"}`,
- `color_range` not in `{None, "limited"}`,
- any non-null `vfr_cadence`,
- any non-null `field_order`.

Create `materializer/capability_gates.py`:

```python
def assert_capable_for_hdr_video(scenario: Scenario, caps: Capabilities) -> None:
    for asset in iter_assets(scenario):
        if asset.video is None or asset.video.hdr_mode is None:
            continue
        if caps.ready_for.materialize_hdr_video:
            return
        raise CapabilityGateError(
            "HDR video materialization requires FFmpeg with libx265 10-bit and setparams",
            asset_id=asset.id,
            field="ready_for.materialize_hdr_video",
            payload={
                "capability": "ready_for.materialize_hdr_video",
                "required_encoder": "libx265",
                "required_filter": "setparams",
                "required_pixel_format": "yuv420p10le",
                "hdr_mode": asset.video.hdr_mode.value,
            },
        )
```

Call it after `assert_capable_for_static_materialize(caps)` in materialize,
wall-clock run, and replay prefix materialization.

- [ ] **Step 5: Verify focused tests pass**

Run the same focused command with `--no-cov`.

### Task 4: FFmpeg Args, Evidence, And Real Media

**Files:**
- Modify: `src/chaos_librarian/materializer/content_sources.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Modify: `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- Modify: `tests/materializer/test_content_sources.py`
- Modify: `tests/materializer/test_ffmpeg_builder.py`
- Create: `tests/fixtures/scenarios/hdr-video.yaml`
- Modify: `tests/integration/test_materialize_real.py`

- [ ] **Step 1: Write failing unit tests**

Add `hdr_mode` to video request helpers. In content-source tests, assert HDR10
and HLG produce different recipe digests from SDR and from each other.

In ffmpeg builder tests, assert:

```python
assert "-vf" in argv
assert "setparams=color_primaries=bt2020" in argv[argv.index("-vf") + 1]
assert "format=yuv420p10le" in argv[argv.index("-vf") + 1]
assert "-x265-params" in argv
assert "transfer=smpte2084" in argv[argv.index("-x265-params") + 1]
assert "master-display=" in argv[argv.index("-x265-params") + 1]
assert "max-cll=1000,400" in argv[argv.index("-x265-params") + 1]
```

Add an HLG test asserting `transfer=arib-std-b67` and no `master-display`.
Add a test that `hdr_mode` suppresses separate SDR `-colorspace` and
`-color_range` args when compatible SDR fields are present.

- [ ] **Step 2: Write failing real ffprobe tests**

Create `tests/fixtures/scenarios/hdr-video.yaml` with `codec: hevc` and
`hdr_mode: hdr10`.

Add integration coverage that skips when
`detect_capabilities().ready_for.materialize_hdr_video` is false. For HDR10,
assert stream metadata:

```python
{
    "pix_fmt": "yuv420p10le",
    "color_range": "tv",
    "color_space": "bt2020nc",
    "color_transfer": "smpte2084",
    "color_primaries": "bt2020",
}
```

Assert first-frame side data includes both `Mastering display metadata` and
`Content light level metadata`. For HLG, replace the fixture mode with `hlg` and
assert `color_transfer == "arib-std-b67"` and no promised HDR10 side data.

- [ ] **Step 3: Verify tests fail**

Run:

```bash
uv run pytest tests/materializer/test_content_sources.py \
  tests/materializer/test_ffmpeg_builder.py \
  tests/integration/test_materialize_real.py::test_materialize_hdr_signaling_reports_metadata \
  -q --no-cov
```

- [ ] **Step 4: Implement request plumbing and ffmpeg args**

Extend `VideoSourceRequest` with `hdr_mode`, pass it from preflight/synthesis,
and include it in `_request_payload`.

In `ffmpeg.py`, add HDR constants:

```python
_HDR_FILTERS = {
    VideoHdrMode.HDR10: "setparams=color_primaries=bt2020:color_trc=smpte2084:colorspace=bt2020nc:range=tv,format=yuv420p10le",
    VideoHdrMode.HLG: "setparams=color_primaries=bt2020:color_trc=arib-std-b67:colorspace=bt2020nc:range=tv,format=yuv420p10le",
}
```

Add `_HDR_X265_PARAMS` for HDR10 and HLG using the probed x265 params from the
design doc. `_hdr_video_args` rejects non-HEVC codecs and incompatible SDR
color fields defensively, then returns an argv slice in this shape:

```python
["-vf", _HDR_FILTERS[video.hdr_mode], "-x265-params", _HDR_X265_PARAMS[video.hdr_mode]]
```

In `_build_video_command`, append `_hdr_video_args(video)` before interlaced and
color args. Make `_color_signal_args` return `[]` when `hdr_mode` is set.

- [ ] **Step 5: Verify focused tests pass**

Run the same focused command with `--no-cov`.

### Task 5: Schemas, Docs, Reviews, And Final Gates

**Files:**
- Modify: `schemas/scenario.schema.json`
- Modify: `schemas/capabilities.schema.json`
- Modify: `docs/contract/schema-reference.md`
- Modify: all current Scenario version references in tests/fixtures

- [ ] **Step 1: Sweep current versions**

Run:

```bash
rg -n 'schema_version: 15|"schema_version": 15|schema_version=15|schema_version == 15|SCENARIO_SCHEMA_VERSION == 15|scenario \\| 15' \
  tests src docs/contract schemas
rg -n 'CAPABILITIES_SCHEMA_VERSION == 3|schema_version: Literal\\[3\\]|schema_version=3|schema_version == 3|capabilities \\| 3' \
  tests src docs/contract schemas
```

Move current Scenario references to 16 and capabilities references to 4.
Preserve historical prose that intentionally describes prior versions.

- [ ] **Step 2: Regenerate schemas**

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
uv run python -m chaos_librarian.schema_export --check
```

- [ ] **Step 3: Adversarial code review**

Review the full working tree diff for:

- host capability false positives,
- command args that fail to produce probe-visible HDR metadata,
- schema version drift,
- unsupported HDR combinations reaching ffmpeg,
- missing materialize/run/replay gates.

Address concrete findings. Run no more than three adversarial review passes.

- [ ] **Step 4: Simplification review**

Review for duplicated capability subprocess probes, unnecessary HDR abstractions,
and test helpers that can be safely narrowed. Address only high-value findings.

- [ ] **Step 5: Final verification**

Run:

```bash
uv run python -m chaos_librarian.schema_export --check
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run pytest -q
git diff --check
```

- [ ] **Step 6: Commit, push, PR, monitor, merge, close**

Commit implementation after the gates pass:

```bash
git commit -m "Implement HDR video signaling recipes"
git push -u origin feat/issue-132-hdr-signaling
gh pr create --base main --head feat/issue-132-hdr-signaling \
  --title "Add HDR video signaling recipes" \
  --body $'## Summary\n- add Scenario v16 HDR10/HLG signaling for HEVC video tracks\n- report HDR readiness through capabilities and gate unsupported hosts\n- materialize probe-visible HDR10/HLG metadata with ffprobe coverage\n\n## Verification\n- uv run python -m chaos_librarian.schema_export --check\n- uv run ruff check .\n- uv run ruff format --check .\n- uv run ty check src tests\n- uv run pytest -q\n\nCloses #132'
gh pr checks <pr> --watch --interval 10
gh pr merge <pr> --merge --delete-branch
```

Before committing, run `git status --short`, review the changed path list, and
stage only the #132 implementation, schema, fixture, test, and documentation
paths.
