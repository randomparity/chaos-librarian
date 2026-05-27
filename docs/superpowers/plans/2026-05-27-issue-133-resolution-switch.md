# Issue 133 Resolution-Switching Video Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one deterministic H.264 MPEG-TS recipe that switches from `sd` to `hd` mid-stream and exposes the sequence in replay evidence.

**Architecture:** Add an explicit `VideoResolutionSequence` scenario field and route that narrow mode through a special Phase-A synthesis branch. The branch generates two MPEG-TS H.264 segments, concat-demuxes them with stream copy, records all FFmpeg invocations, and stores `resolution_sequence` on content-source evidence.

**Tech Stack:** Pydantic v2 contracts, Typer CLI capabilities output, FFmpeg/FFprobe, pytest, ruff, ty, schema export.

---

## Task 1: Contract, Evidence, And Capability Surface

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `src/chaos_librarian/contract/capabilities.py`
- Modify: `src/chaos_librarian/contract/content_sources.py`
- Modify: `src/chaos_librarian/materializer/content_sources.py`
- Modify: `src/chaos_librarian/materializer/tooling/capabilities.py`
- Modify: `src/chaos_librarian/cli/commands/capabilities.py`
- Test: `tests/contract/test_scenario.py`
- Test: `tests/contract/test_capabilities.py`
- Test: `tests/contract/test_contract_constants.py`
- Test: `tests/materializer/test_content_sources.py`
- Test: `tests/materializer/test_capabilities.py`
- Test: `tests/cli/test_capabilities.py`

- [ ] **Step 1: Write failing contract and capability tests**

Add tests that expect:

```python
assert SCENARIO_SCHEMA_VERSION == 17
assert CAPABILITIES_SCHEMA_VERSION == 5
assert MATERIALIZATION_SCHEMA_VERSION == 11
assert REPLAY_BUNDLE_SCHEMA_VERSION == 9
```

Add `VideoResolutionSequence.SD_TO_HD.value == "sd_to_hd"` and `VideoTrack` round-trip tests
for `resolution_sequence="sd_to_hd"`. Add a `ContentSourceEvidence` round-trip test with
`resolution_sequence="sd_to_hd"`. Add `ReadyFor.materialize_resolution_switch_video` to
valid Capabilities payloads and assert it is required.

Run:

```bash
uv run pytest tests/contract/test_scenario.py \
  tests/contract/test_capabilities.py \
  tests/contract/test_contract_constants.py -q --no-cov
```

Expected: FAIL because the enum, fields, and version bumps do not exist.

- [ ] **Step 2: Implement the contract fields**

Implement:

```python
SCENARIO_SCHEMA_VERSION: Final = 17
MATERIALIZATION_SCHEMA_VERSION: Final = 11
REPLAY_BUNDLE_SCHEMA_VERSION: Final = 9
CAPABILITIES_SCHEMA_VERSION: Final = 5

class VideoResolutionSequence(enum.StrEnum):
    SD_TO_HD = "sd_to_hd"

class VideoTrack(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    source: VideoSource
    codec: str
    resolution: str
    vfr_cadence: VideoVfrCadence | None = None
    field_order: VideoFieldOrder | None = None
    color_space: VideoColorSpace | None = None
    color_range: VideoColorRange | None = None
    hdr_mode: VideoHdrMode | None = None
    resolution_sequence: VideoResolutionSequence | None = None

class ContentSourceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_id: str
    track_kind: ContentTrackKind
    source: str
    provider: str
    recipe_digest: str = Field(pattern=SHA256_URI_PATTERN)
    color_space: VideoColorSpace | None = None
    color_range: VideoColorRange | None = None
    resolution_sequence: VideoResolutionSequence | None = None
    track_index: int | None = Field(default=None, ge=0)
    cache_disposition: CacheDisposition

class ReadyFor(BaseModel):
    model_config = ConfigDict(extra="forbid")
    materialize_static: bool
    materialize_filesystem_mutations: bool
    materialize_media_mutations: bool
    materialize_hevc_video: bool
    materialize_hdr_video: bool
    materialize_resolution_switch_video: bool
```

Run the same contract tests. Expected: PASS.

- [ ] **Step 3: Write failing content-source and capability tests**

Add `VideoSourceRequest.resolution_sequence` tests:

```python
default = resolve_video_source(source=VideoSource.COLOR_BARS, request=_video_request())
switched = resolve_video_source(
    source=VideoSource.COLOR_BARS,
    request=_video_request(resolution_sequence=VideoResolutionSequence.SD_TO_HD),
)
assert switched.evidence.resolution_sequence is VideoResolutionSequence.SD_TO_HD
assert switched.evidence.recipe_digest != default.evidence.recipe_digest
```

Extend capability tests so `detect_capabilities()` reports
`ready_for.materialize_resolution_switch_video` true only when FFmpeg/FFprobe meet the
minimum and `ffmpeg -encoders` includes `libx264`. Assert the provider lists
`video:resolution_sequence:sd_to_hd` only when true.

Run:

```bash
uv run pytest tests/materializer/test_content_sources.py \
  tests/materializer/test_capabilities.py \
  tests/cli/test_capabilities.py -q --no-cov
```

Expected: FAIL because request/evidence payloads and capability detection are not wired.

- [ ] **Step 4: Implement content-source and capability reporting**

Add:

```python
RESOLUTION_SEQUENCE_CAPABILITY_SOURCES = (
    f"video:resolution_sequence:{sequence.value}" for sequence in VideoResolutionSequence
)
```

Thread `resolution_sequence_available` through `collect_content_source_capabilities()`.
Add `resolution_sequence` to `VideoSourceRequest`, `_builtin_evidence()`, and
`_request_payload()`. In capability detection, compute:

```python
libx264_available = _ffmpeg_encoder_available(ffmpeg, "libx264")
resolution_switch_available = ffmpeg_ok and ffprobe_ok and libx264_available
```

Set `ReadyFor.materialize_resolution_switch_video=resolution_switch_available` and print it
in the human capabilities output.

Run the tests from Step 3. Expected: PASS.

Do not commit yet. Contract model changes require regenerated schemas and current-version
fixture/test updates in the same implementation commit.

## Task 2: Validation And Entry-Point Gates

**Files:**
- Modify: `src/chaos_librarian/media_matrix.py`
- Modify: `src/chaos_librarian/validation/rules/materialize_media_matrix.py`
- Modify: `src/chaos_librarian/materializer/capability_gates.py`
- Modify: `src/chaos_librarian/materializer/run.py`
- Modify: `src/chaos_librarian/materializer/wall_clock.py`
- Modify: `src/chaos_librarian/materializer/replay.py`
- Test: `tests/validation/rules/test_materialize_media_matrix.py`
- Test: `tests/materializer/test_run.py`
- Test: `tests/materializer/test_wall_clock.py`
- Test: `tests/materializer/test_replay.py`

- [ ] **Step 1: Write failing semantic validation tests**

Add a helper scenario with `container: ts`, `codec: h264`, `source: color_bars`,
`resolution: sd`, `resolution_sequence: sd_to_hd`, and no audio/subtitles. Assert it validates
cleanly.

Add rejection tests for:

```text
container != ts
video.codec != h264
video.source != color_bars
video.resolution != sd
audio present
subtitles present
vfr_cadence present
field_order present
color_space or color_range present
hdr_mode present
```

Run:

```bash
uv run pytest tests/validation/rules/test_materialize_media_matrix.py -q --no-cov
```

Expected: FAIL because the rule does not know the new recipe.

- [ ] **Step 2: Implement semantic validation**

Add `ts` to the supported container set only for the resolution-switch recipe. Implement
`_check_resolution_switch_video()` in `materialize_media_matrix.py` and call it from the
movie/episode video asset path. Emit `E_MATERIALIZE_UNSUPPORTED` at the specific field that
causes rejection.

Run the validation test. Expected: PASS.

- [ ] **Step 3: Write failing capability-gate tests**

Add materialize, wall-clock, and replay tests that patch capabilities with
`materialize_resolution_switch_video=False`, use a valid resolution-switch scenario, and assert
`CapabilityGateError.field == "ready_for.materialize_resolution_switch_video"` before any run
directory is allocated.

Run:

```bash
uv run pytest tests/materializer/test_run.py \
  tests/materializer/test_wall_clock.py \
  tests/materializer/test_replay.py -q --no-cov
```

Expected: FAIL because the gate is missing.

- [ ] **Step 4: Implement the shared gate**

Add:

```python
def assert_capable_for_resolution_switch_video(
    scenario: Scenario, caps: Capabilities
) -> None:
    for asset in iter_assets(scenario):
        if asset.video is None or asset.video.resolution_sequence is None:
            continue
        if caps.ready_for.materialize_resolution_switch_video:
            return
        raise CapabilityGateError(
            "resolution-switch video materialization requires FFmpeg with libx264",
            asset_id=asset.id,
            field="ready_for.materialize_resolution_switch_video",
            payload={
                "capability": "ready_for.materialize_resolution_switch_video",
                "required_encoder": "libx264",
                "resolution_sequence": asset.video.resolution_sequence.value,
            },
        )
```

Call it after `assert_capable_for_static_materialize()` in materialize, wall-clock run, and replay.

Run the tests from Steps 1 and 3. Expected: PASS.

Do not commit yet. Keep this task's changes staged only after Task 4 regenerates schemas and
updates all current-version references.

## Task 3: FFmpeg Commands And Phase-A Synthesis

**Files:**
- Modify: `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Test: `tests/materializer/test_ffmpeg_builder.py`
- Test: `tests/materializer/test_content_sources.py`
- Test: `tests/materializer/test_synthesis.py`

- [ ] **Step 1: Write failing FFmpeg builder tests**

Add tests for:

```python
segment = build_resolution_switch_segment_command(
    video_input=FFmpegInput(lavfi="smptebars=size=640x480:rate=24", extra_flags=("-t", "0.5")),
    output_path=tmp_path / "segment.ts",
)
assert "-f" in segment
assert "mpegts" in segment
assert segment[segment.index("-c:v") + 1] == "libx264"

concat = build_resolution_switch_concat_command(
    concat_list_path=tmp_path / "concat.txt",
    output_path=tmp_path / "asset.ts",
)
assert concat[:6] == ["ffmpeg", "-hide_banner", "-y", "-f", "concat", "-safe"]
assert concat[concat.index("-c") + 1] == "copy"
```

Run:

```bash
uv run pytest tests/materializer/test_ffmpeg_builder.py -q --no-cov
```

Expected: FAIL because the builders do not exist.

- [ ] **Step 2: Implement FFmpeg builders**

Add exported helpers:

```python
def build_resolution_switch_segment_command(
    *, video_input: FFmpegInput, output_path: Path
) -> list[str]:
    argv: list[str] = ["ffmpeg", "-hide_banner", "-y"]
    argv.extend(_video_input_args(video_input))
    argv.extend(["-map", "0:v:0", "-c:v", "libx264", "-preset", "medium"])
    argv.extend(["-x264-params", "keyint=12:min-keyint=12:scenecut=0"])
    argv.extend(["-an", "-f", "mpegts"])
    argv.extend(_BITEXACT_OUTPUT_FLAGS)
    argv.append(str(output_path))
    return argv

def build_resolution_switch_concat_command(
    *, concat_list_path: Path, output_path: Path
) -> list[str]:
    argv = ["ffmpeg", "-hide_banner", "-y", "-f", "concat", "-safe", "0"]
    argv.extend(["-i", str(concat_list_path), "-c", "copy"])
    argv.extend(_BITEXACT_OUTPUT_FLAGS)
    argv.append(str(output_path))
    return argv
```

Use `libx264`, `-preset medium`, `-x264-params keyint=12:min-keyint=12:scenecut=0`, `-an`,
`-f mpegts`, and existing bitexact flags.

Run the builder tests. Expected: PASS.

- [ ] **Step 3: Write failing synthesis tests**

Add a `materialize_one_asset()` test for a `ts` asset with
`resolution_sequence: sd_to_hd`. Patch `run_ffmpeg` to write bytes for each command and return
successful `ToolInvocation`s. Patch `probe_file` to return a `ProbedMedia` video stream. Assert:

```python
assert len(result.prelude_invocations) == 2
assert result.invocation.command[result.invocation.command.index("-c") + 1] == "copy"
assert result.materialized_asset.invocation_index == 2
assert result.content_sources[0].resolution_sequence is VideoResolutionSequence.SD_TO_HD
```

Add a `materialize_assets_phase_a()` test that confirms all three invocations are appended in
order and the materialized asset points at the final invocation index.

Run:

```bash
uv run pytest tests/materializer/test_synthesis.py -q --no-cov
```

Expected: FAIL because `MaterializeAssetResult` and synthesis do not support prelude
invocations.

- [ ] **Step 4: Implement synthesis branch**

Add a `prelude_invocations` field to `MaterializeAssetResult` as a variadic tuple of
`ToolInvocation` values with default `()`.
In `materialize_assets_phase_a()`, replace the current enumerate-based invocation numbering with
a loop that sets `invocation_index = len(phase_a.invocations)` for each asset, appends
`prelude_invocations`, then appends `invocation`.

In `materialize_one_asset()`, branch to `_materialize_resolution_switch_asset()` when
`asset.video.resolution_sequence is not None`. Use a temporary directory under the output parent,
build two segment commands for `sd` and `hd`, write the concat list, run the concat command, then
probe/hash the final output.

Run:

```bash
uv run pytest tests/materializer/test_ffmpeg_builder.py \
  tests/materializer/test_synthesis.py \
  tests/materializer/test_content_sources.py -q --no-cov
```

Expected: PASS.

Do not commit yet. The implementation commit happens after Task 4's schema export and final
verification.

## Task 4: Fixtures, Real Verification, Schemas, And Final Gates

**Files:**
- Create: `tests/fixtures/scenarios/resolution-switch-video.yaml`
- Modify: `tests/integration/test_materialize_real.py`
- Modify: `docs/contract/schema-reference.md`
- Modify: `schemas/*.schema.json`
- Modify: tests and fixtures that pin current schema versions

- [ ] **Step 1: Add fixture and real ffprobe test**

Create `tests/fixtures/scenarios/resolution-switch-video.yaml` with:

```yaml
schema_version: 17
scenario_id: resolution-switch-video
seed: 133
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
movies:
  - id: movie_resolution_switch
    title: Resolution Switch
    layout: movie_flat
    variants:
      - id: variant_sd_to_hd
        label: sd-to-hd
        bundle:
          id: bundle_sd_to_hd
          assets:
            - id: asset_resolution_switch_main
              role: main
              container: ts
              duration_seconds: 1.0
              video:
                source: color_bars
                codec: h264
                resolution: sd
                resolution_sequence: sd_to_hd
series: []
artists: []
timeline: []
```

Add an integration test that skips unless
`detect_capabilities().ready_for.materialize_resolution_switch_video` is true. Materialize the
fixture, run `ffprobe -show_entries frame=width,height`, and assert the set contains
`(640, 480)` and `(1280, 720)`.

Run:

```bash
uv run pytest tests/integration/test_materialize_real.py::test_materialize_resolution_switch_video_reports_frame_dimensions -q --no-cov
```

Expected: PASS on hosts with the capability, SKIP otherwise.

- [ ] **Step 2: Update current schema-version corpus**

Run:

```bash
rg -n 'schema_version: 16|"schema_version": 16|schema_version=16|SCENARIO_SCHEMA_VERSION == 16' tests src docs/contract
rg -n 'CAPABILITIES_SCHEMA_VERSION == 4|schema_version: Literal\[4\]|schema_version=4' tests src docs/contract
rg -n 'MATERIALIZATION_SCHEMA_VERSION == 10|schema_version: Literal\[10\]|schema_version=10' tests src docs/contract
rg -n 'REPLAY_BUNDLE_SCHEMA_VERSION == 8|schema_version: Literal\[8\]|schema_version=8' tests src docs/contract
```

Update current-contract references to Scenario 17, Capabilities 5, Materialization 11, and Replay
Bundle 9. Do not rewrite historical sprint plans/specs except this issue's plan and design.

- [ ] **Step 3: Regenerate schemas**

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
uv run python -m chaos_librarian.schema_export --check
```

Expected: first command writes schemas; second reports all schemas up-to-date.

- [ ] **Step 4: Run final verification**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run pytest -q
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 5: Commit and open PR**

```bash
git add docs schemas src tests
git commit -m "Add resolution-switch video recipe"
git push -u origin feat/issue-133-resolution-switch
gh pr create --base main --head feat/issue-133-resolution-switch \
  --title "Add resolution-switch video recipe" \
  --body "## Summary
- add Scenario v17 resolution_sequence and explicit content-source evidence
- add Capabilities v5 reporting and pre-allocation gates for resolution switching
- materialize H.264 MPEG-TS sd_to_hd files and verify frame dimensions with ffprobe

## Verification
- uv run python -m chaos_librarian.schema_export --check
- uv run ruff check .
- uv run ruff format --check .
- uv run ty check src tests
- uv run pytest -q
- git diff --check

Closes #133"
```

After CI passes, merge the PR and confirm issue #133 is closed.
