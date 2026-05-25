# Issues 94-95 HEVC And Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add HEVC/H.265 static synthesis and make unsupported static
materialize media fields fail validation before materialize runtime.

**Architecture:** Add a neutral `chaos_librarian.media_matrix` module for
supported static media values and FFmpeg encoder lookup. Validation uses it for
`E_MATERIALIZE_UNSUPPORTED`; the materializer uses it to build FFmpeg commands
and capability gates.

**Tech Stack:** Python 3.13, Pydantic v2, Typer, pytest, FFmpeg/ffprobe.

---

### Task 1: Shared Static Media Matrix And Validation Rule

**Files:**
- Create: `src/chaos_librarian/media_matrix.py`
- Create: `src/chaos_librarian/validation/rules/materialize_media_matrix.py`
- Modify: `src/chaos_librarian/validation/codes.py`
- Modify: `src/chaos_librarian/validation/semantic.py`
- Modify: `src/chaos_librarian/contract/scenario.py`
- Modify: `tests/validation/rules/test_materialize_media_matrix.py`
- Add: `tests/fixtures/scenarios/invalid/materialize-video-resolution-small.yaml`
- Add: `tests/fixtures/scenarios/invalid/materialize-video-codec-av1.yaml`
- Add: `tests/fixtures/scenarios/invalid/materialize-video-source-noise.yaml`

- [x] **Step 1: Write failing validation tests and fixtures**

Create tests that call `run_validation(prepare_run_input(path))` and assert:

```python
assert report.ok is False
assert report.issues[0].code == "E_MATERIALIZE_UNSUPPORTED"
assert report.issues[0].path.endswith(".video.resolution")
```

Use a second test for `video.codec: av1`, and a positive test for
`video.codec: hevc`, `resolution: sd`, `container: mkv`, and AAC audio. Use a
third negative test for `video.source: noise`.

Run:

```bash
uv run pytest tests/validation/rules/test_materialize_media_matrix.py -q --no-cov
uv run pytest tests/validation/test_invalid_corpus.py -q --no-cov
```

Expected: new tests fail because no rule or code exists yet.

- [x] **Step 2: Add shared matrix constants**

Create `src/chaos_librarian/media_matrix.py` with:

```python
from __future__ import annotations

from typing import Final

SUPPORTED_CONTAINERS: Final = frozenset({"mkv", "mp4"})
SUPPORTED_RESOLUTIONS: Final = frozenset({"sd", "hd", "1080p"})
SUPPORTED_VIDEO_SOURCES: Final = frozenset({"color_bars", "mandelbrot", "solid_color"})
SUPPORTED_VIDEO_CODECS: Final = frozenset({"h264", "h265", "hevc"})
SUPPORTED_AUDIO_CODECS: Final = frozenset({"aac"})
VIDEO_ENCODER_BY_CODEC: Final = {
    "h264": "libx264",
    "h265": "libx265",
    "hevc": "libx265",
}
HEVC_VIDEO_CODECS: Final = frozenset({"h265", "hevc"})
```

- [x] **Step 3: Add validation code and rule**

Add `E_MATERIALIZE_UNSUPPORTED: Final = "E_MATERIALIZE_UNSUPPORTED"` to
`validation/codes.py` and register it in `tests/validation/test_codes.py`.

Implement `rule_materialize_media_matrix()` by walking `iter_assets_with_loc`.
For each well-shaped asset:

- check `container`;
- check `video.source`, `video.codec`, and `video.resolution` when `video` is a mapping;
- check every `audio[index].codec`.

Report via `Reporter.error()` at the exact field location. Register the rule in
`validation/semantic.py` after path-safety and before sidecar rules.

- [x] **Step 4: Run validation tests**

Run:

```bash
uv run pytest \
  tests/validation/rules/test_materialize_media_matrix.py \
  tests/validation/test_invalid_corpus.py \
  tests/validation/test_codes.py \
  -q --no-cov
```

Expected: tests pass after fixture updates from Task 4.
Also update the `VideoSource.NOISE` comment in `contract/scenario.py` so it no
longer claims that value passes validation.

### Task 2: HEVC FFmpeg Builder Support

**Files:**
- Modify: `src/chaos_librarian/materializer/tooling/ffmpeg.py`
- Modify: `tests/materializer/test_ffmpeg_builder.py`

- [x] **Step 1: Add failing builder tests**

Add tests asserting `video.codec: hevc` and `video.codec: h265` both put
`libx265` after `-c:v`, while `h264` still uses `libx264`.

Run:

```bash
uv run pytest tests/materializer/test_ffmpeg_builder.py -q --no-cov
```

Expected: HEVC tests fail because the builder still rejects non-H.264 codecs.

- [x] **Step 2: Use shared matrix in builder**

Import `SUPPORTED_*` and `VIDEO_ENCODER_BY_CODEC` from
`chaos_librarian.media_matrix`. Replace local matrix constants and emit:

```python
argv.extend(["-c:v", VIDEO_ENCODER_BY_CODEC[video.codec], "-preset", "medium"])
```

Run the same builder tests and expect pass.

### Task 3: Capabilities Schema V3 And HEVC Readiness

**Files:**
- Modify: `src/chaos_librarian/contract/__init__.py`
- Modify: `src/chaos_librarian/contract/capabilities.py`
- Modify: `src/chaos_librarian/materializer/tooling/capabilities.py`
- Modify: `src/chaos_librarian/cli/commands/capabilities.py`
- Modify: `docs/contract/schema-reference.md`
- Modify: capabilities tests that instantiate `ReadyFor`
- Regenerate: `schemas/capabilities.schema.json`

- [x] **Step 1: Add failing capabilities tests**

Add mocked detection tests for FFmpeg encoders:

```python
assert detect_capabilities().ready_for.materialize_hevc_video is True
assert "materialize_hevc_video" in result.stdout
```

Also update contract tests to expect schema version 3 and require the new field.

Run:

```bash
uv run pytest \
  tests/materializer/test_capabilities.py \
  tests/contract/test_capabilities.py \
  tests/cli/test_capabilities.py \
  tests/contract/test_contract_constants.py \
  -q --no-cov
```

Expected: tests fail until schema/model/detection changes land.

- [x] **Step 2: Implement HEVC readiness detection**

Probe `ffmpeg -hide_banner -encoders` only when baseline FFmpeg is available.
Treat `libx265` as the required encoder for deterministic HEVC synthesis.
Populate `ReadyFor.materialize_hevc_video`.

- [x] **Step 3: Regenerate schemas**

Run:

```bash
uv run python -m chaos_librarian.schema_export --write
uv run python -m chaos_librarian.schema_export --check
```

Expected: schema export is clean and `capabilities.schema.json` is v3.

### Task 4: Materialize HEVC Gate, Fixture Updates, And Real Integration

**Files:**
- Modify: `src/chaos_librarian/materializer/run.py`
- Add: `tests/fixtures/scenarios/hevc-mkv.yaml`
- Modify: `tests/fixtures/scenarios/duplicate-variant.yaml`
- Modify: `tests/fixtures/scenarios/slow-copy.yaml`
- Modify: integration/materializer tests for HEVC real path

- [x] **Step 1: Add failing materialize tests**

Add a unit test that patches capabilities with `materialize_hevc_video=False`
and asserts a HEVC scenario raises `CapabilityGateError` before run-dir
allocation. Add a real integration test that skips unless
`detect_capabilities().ready_for.materialize_hevc_video` is true, materializes
`hevc-mkv.yaml`, and asserts a current manifest video stream reports `hevc`.

- [x] **Step 2: Implement scenario HEVC capability gate**

In `materializer/run.py`, after baseline capability gating and before run-dir
allocation, scan scenario assets. If any declared video codec is `hevc` or
`h265` and `caps.ready_for.materialize_hevc_video` is false, raise
`CapabilityGateError` with a payload naming `ready_for.materialize_hevc_video`.

- [x] **Step 3: Update valid fixtures**

Update old plan-only media values so the valid fixture corpus remains clean:

- `duplicate-variant.yaml`: make the UHD variant materialize-supported by using
  HEVC, `sd` or `1080p`, and AAC audio;
- `slow-copy.yaml`: use a supported source/resolution pair.

- [x] **Step 4: Run focused verification**

Run:

```bash
uv run pytest \
  tests/materializer/test_ffmpeg_builder.py \
  tests/materializer/test_capabilities.py \
  tests/contract/test_capabilities.py \
  tests/cli/test_capabilities.py \
  tests/validation/rules/test_materialize_media_matrix.py \
  tests/validation/test_invalid_corpus.py \
  tests/integration/test_materialize_real.py \
  -q --no-cov
uv run ruff check .
uv run ruff format --check .
uv run ty check src tests
uv run python -m chaos_librarian.schema_export --check
```

Expected: all focused tests and gates pass.
