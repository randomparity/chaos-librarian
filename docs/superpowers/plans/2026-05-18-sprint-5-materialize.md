# Sprint 5 — Materializer Capability Detection And Static Materialization

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship the `capabilities` and `materialize` CLI commands plus the supporting `materializer/` package so chaos-librarian produces real on-disk media libraries from static (empty-timeline) scenarios with bit-exact, probe-verified output.

**Architecture:** A new `materializer/` package sits alongside the pure plan-only `engine/`, importing it but never the reverse. Materialization is an 8-step orchestrator: timeline-scope check → containment → capability gate → engine pass → matrix pre-flight → per-asset synthesis loop → atomic metadata write → return. Subprocess concerns (ffmpeg, ffprobe) live behind narrow wrappers so the orchestrator stays mock-testable.

**Tech Stack:** Python 3.13, Pydantic v2, Typer (existing CLI shell), Sprint 1 validation pipeline, Sprint 2 determinism package, Sprint 3 engine, Sprint 4 step/replay/reports. New runtime use of `packaging.version.Version` (already transitively present via `pip`/`setuptools` — explicit add to project deps). No other new dependencies.

**Source spec:** [`docs/specs/chaos-librarian-design.md`](../../specs/chaos-librarian-design.md) — §"Materialize Mode", §"Content Sources", §"Materializer Backends", §"Sprint 5", §"Schema Contract", §"Filesystem Safety".

**Design doc:** [`docs/superpowers/specs/2026-05-18-sprint-5-design.md`](../specs/2026-05-18-sprint-5-design.md) — load-bearing for every task; revised after the Codex adversarial review (commit `f5901f6`). Read it before starting any task; do not deviate from its decisions silently.

**Branch:** `feat/sprint-5` (already exists; the design-doc revision commit `f5901f6 docs(sprint-5): address Codex adversarial review` is its tip).

---

## Open Design Decisions Baked Into This Plan

These resolve gaps the spec deliberately left for the implementer. Push back via PR comment if you disagree before merging.

1. **`MaterializationStatus` → `Outcome` rename.** Sprint 0's `MaterializationReport.status: MaterializationStatus` becomes `outcome: Outcome` with values `success | unsupported | tool_failed | tool_missing | containment_violation`. `Outcome.SUCCESS` is new (Sprint 0 used the absence of failures); the rest preserve their string values. The old enum class is deleted, not aliased.

2. **`ToolchainInfo` is a structured Pydantic model, not a `dict[str, str]`.** Lives in `contract/materialization.py` (new model alongside the other materialize types). `MaterializationReport.toolchain: ToolchainInfo` and `MaterializeReplayBundle.toolchain: ToolchainInfo` both reference it. The field has `ffmpeg`, `ffprobe`, `mkvtoolnix`, all `str | None = None`. This swap is structural and is covered by the `MATERIALIZATION_SCHEMA_VERSION` bump (Task 5) and the `REPLAY_BUNDLE_SCHEMA_VERSION` bump (Task 6).

3. **`MaterializeReplayBundle.applied_events: Literal[0] = 0`.** Sprint 5 timelines are always empty; the variant pins the value at the schema level. Sprint 6 will widen it back to `int = Field(ge=0)`.

4. **Sentinel `state` defaults to `"complete"`.** Plan-only (`engine.writer.write_fixture`) doesn't pass a state argument — the model default fires and Sprint 0's bit-identical-plan-only guarantee is preserved. Materialize writes the sentinel twice: once with `state="in_progress"` at run-dir allocation, once with `state="complete"` in the final atomic batch (or after caught-failure cleanup).

5. **Capability detection JSON indent.** Mirror the spec's worked example: `caps.model_dump_json(indent=2, exclude_none=True)`. This deviates from the no-indent convention `plan`/`step` use, but the spec is explicit and human-debugging of `capabilities --json` is the main consumer.

6. **`replay <materialize-bundle>` exit and payload.** Discriminated-union parse succeeds (the variant exists at v3). When the resulting bundle is `MaterializeReplayBundle`, the CLI exits 1 with stderr JSON `{"error": "materialize_replay_not_implemented", "message": "materialize replay lands in Sprint 9 (voom-v2 adapter)", "execution_mode": "<value>"}`. The Sprint 4 `_emit_step_error`-style stderr helper carries it (or its replay-equivalent).

7. **`inspect` surfaces sentinel `state`.** Both human and JSON modes include the new field; the JSON payload gains a `"sentinel": {"state": "..."}` block. The CLI does not refuse `in_progress` from `inspect` — that's `step`'s and `materialize <existing>`'s job (exit 7).

8. **Lazy run-dir allocation enforcement.** Steps 1-5 of the orchestrator NEVER call `mkdir` on `out_dir`. Step 6 (`begin_materialize_run`) is the only filesystem-touching primitive before synthesis. The Layer 3 orchestrator tests assert `not out_dir.exists()` on every pre-flight failure.

9. **Atomic metadata writes go file-by-file, not via staging-rename.** Plan-only's `engine.writer.write_fixture` uses a staging directory because nothing has been written to `out_dir` yet. Materialize cannot — `library/` is already in place during synthesis. The materializer's `finalize_materialize_run` writes each metadata file via `.tmp + rename` (atomic per file) and flips the sentinel last. The crash window between "manifest.current.json present" and "sentinel state=complete" is microseconds (single rename); the contract still treats sentinel `state="complete"` as the trust signal.

10. **Reports in materialize output.** Sprint 4's `engine.reports.build_report_set` runs in materialize too, populating the new `AssetSnapshot.content_hash` and `AssetSnapshot.probed` fields from the augmented manifest. The `reports/` tree shape is unchanged from Sprint 4.

11. **`packaging` is explicit.** Add `packaging>=24` to `pyproject.toml`'s `[project] dependencies`. It's the only new runtime import.

---

## File Structure

### To create

```
src/chaos_librarian/materializer/__init__.py             # public re-exports
src/chaos_librarian/materializer/capabilities.py         # detect + version normalize
src/chaos_librarian/materializer/errors.py               # MaterializationError hierarchy
src/chaos_librarian/materializer/recipes.py              # FFmpegInput + 7 recipe fns
src/chaos_librarian/materializer/ffmpeg.py               # BITEXACT_FLAGS, build_command, run_ffmpeg
src/chaos_librarian/materializer/probe.py                # ffprobe wrapper -> ProbedMedia
src/chaos_librarian/materializer/writer.py               # begin/finalize/cleanup helpers
src/chaos_librarian/materializer/run.py                  # materialize_scenario orchestrator
src/chaos_librarian/contract/capabilities.py             # Capabilities + ToolStatus + ReadyFor
src/chaos_librarian/contract/canonicalize.py             # cross-toolchain manifest canonicalize
tests/materializer/__init__.py                           # empty marker
tests/materializer/test_capabilities.py                  # Layer 2 (mocked subprocess)
tests/materializer/test_recipes.py                       # Layer 2 (pure fns)
tests/materializer/test_ffmpeg_builder.py                # Layer 2 (matrix coverage)
tests/materializer/test_probe.py                         # Layer 2 (mocked subprocess)
tests/materializer/test_writer.py                        # Layer 3 helper sanity
tests/materializer/test_run.py                           # Layer 3 (mocked orchestrator)
tests/integration/__init__.py                            # empty marker
tests/integration/test_materialize_real.py               # Layer 4 (real ffmpeg, skipif)
tests/contract/test_capabilities.py                      # contract roundtrip
tests/contract/test_canonicalize.py                      # helper sanity
tests/cli/test_capabilities.py                           # Layer 5
tests/cli/test_materialize.py                            # Layer 5
tests/fixtures/scenarios/static-library.yaml             # Sprint 5 matrix fixture
```

### To modify

```
src/chaos_librarian/contract/__init__.py                 # +CAPABILITIES; bump 6 versions
src/chaos_librarian/contract/scenario.py                 # VideoSource/AudioSource/SubtitleSource
src/chaos_librarian/contract/manifest.py                 # ProbedMedia, ProbedStream; v2 fields
src/chaos_librarian/contract/run_sentinel.py             # state field; v2
src/chaos_librarian/contract/materialization.py          # filled v2 with Outcome + ToolchainInfo
src/chaos_librarian/contract/replay_bundle.py            # v3 base + Literal[0] on materialize
src/chaos_librarian/contract/reports.py                  # AssetSnapshot v2 fields
src/chaos_librarian/schema_export.py                     # +capabilities entry
src/chaos_librarian/cli/app.py                           # real capabilities + materialize bodies
src/chaos_librarian/engine/writer.py                     # _emit_sentinel passes state through
pyproject.toml                                           # +packaging>=24 dep
tests/contract/test_contract_constants.py                # +CAPABILITIES + sprint-4 constants
tests/contract/test_schema_export.py                     # 11 -> 12 schemas
tests/contract/test_run_sentinel.py                      # state coverage
tests/contract/test_materialization.py                   # v2 shape
tests/contract/test_replay_bundle.py                     # v3 + Literal[0] coverage
tests/contract/test_reports.py                           # v2 fields coverage
tests/cli/test_inspect.py                                # state surface
tests/cli/test_step.py                                   # in_progress refusal
tests/cli/test_replay.py                                 # materialize-bundle not-implemented
```

### Auto-regenerated (committed alongside the contract task that bumped them)

```
schemas/capabilities.schema.json     # NEW v1
schemas/manifest.schema.json         # REGEN v2
schemas/materialization.schema.json  # REGEN v2
schemas/replay-bundle.schema.json    # REGEN v3
schemas/scenario.schema.json         # REGEN v2
schemas/asset-report.schema.json     # REGEN v2
schemas/run-sentinel.schema.json     # REGEN v2
```

### Not touched

- `src/chaos_librarian/engine/{plan,step,resolution,state,events,journal_io,reports,diff}.py` — Sprint 5 only reuses `engine.run_plan` (called with `steps_limit=0` for static scenarios) and `engine.reports.build_report_set`. No engine logic changes.
- `src/chaos_librarian/validation/` — Sprint 5 reuses the existing pipeline unchanged; the scenario v2 enums are inert at validate-time.
- Other contract modules (`journal.py`, `paths.py`, `validation.py`) — no Sprint 5 changes.

---

## Conventions Recap

- `from __future__ import annotations` at the top of every source/test module.
- Absolute imports only (`from chaos_librarian.x.y import Z`).
- Google-style docstrings on non-trivial public APIs.
- Every `BaseModel` carries `model_config = ConfigDict(extra="forbid")`.
- `schema_version` is `Literal[N]` hardcoded — never `Literal[CONSTANT]`; `ty` rejects the indirect form. The constants in `contract/__init__.py` are `Final = N` (no `[int]`) so `ty` infers `Literal[N]`.
- Enums are `class X(enum.StrEnum):`, never `class X(str, enum.Enum):` (ruff UP042).
- Negative Pydantic tests build a `dict` and call `Model.model_validate(payload)` — never construct via kwargs with `# type: ignore`.
- Typer Path args use `Annotated[Path, typer.Argument(...)]`, never `Path = typer.Argument(...)` (ruff B008).
- Test files mirror source layout: `tests/<sub>/test_<module>.py`.
- Rule 9 tests carry a class- or function-level docstring including `WHY:` so future readers understand intent.
- Function size ≤100 lines, cyclomatic complexity ≤8, ≤5 positional params, 100-char line length.
- After any contract change: run `--write`, commit the regenerated schemas in the **same** commit, then run `--check` to confirm clean.
- One commit per task. Subject lines use conventional commits (`feat(scope): ...`, `fix(scope): ...`, `test(scope): ...`, `docs(scope): ...`). Body explains WHY.
- Stay on `feat/sprint-5`. No worktree, no sub-branch.

---

## Task 0: Confirm branch and clean working tree

**Files:** none (branch operation only).

This sanity gate verifies the starting point before implementation. The design-doc revision commit `f5901f6` is the tip; the Sprint 4 PR (#10) is merged into main.

- [ ] **Step 1: Confirm branch and tree state**

Run: `git status && git rev-parse --abbrev-ref HEAD && git log --oneline -1`
Expected: working tree clean, branch `feat/sprint-5`, HEAD is `f5901f6 docs(sprint-5): address Codex adversarial review` (or a later sprint-5 commit if one has been added).

- [ ] **Step 2: Sanity-check the existing suite passes**

Run: `uv sync && uv run pytest -q`
Expected: install completes; every existing test passes.

- [ ] **Step 3: Confirm the drift gate is clean against current code**

Run: `uv run python -m chaos_librarian.schema_export --check`
Expected: `All 11 schemas up-to-date.`

No commit at this task.

---

## Task 1: Scenario v2 — source enums on Video/Audio/Subtitle tracks

**Files:**

- Modify: `src/chaos_librarian/contract/__init__.py:16` — bump `SCENARIO_SCHEMA_VERSION` 1 → 2.
- Modify: `src/chaos_librarian/contract/scenario.py` — add three enums; narrow `VideoTrack.source`; add `source` to `AudioTrack` and `SubtitleTrack` with defaults; bump `Scenario.schema_version: Literal[2]`.
- Modify: `tests/contract/test_scenario.py` — extend with enum-narrowing and default-source cases.
- Auto-regenerated: `schemas/scenario.schema.json`.

The existing six fixture scenarios all populate `VideoTrack.source` with one of `mandelbrot`, `color_bars`, or `noise`. Adding the enum locks the set to `{mandelbrot, color_bars, solid_color, noise}` (`solid_color` is new; `noise` stays in the enum because `slow-copy.yaml` uses it, even though Sprint 5's materializer rejects it as `E_MATERIALIZE_UNSUPPORTED`). Audio and subtitle source fields are NEW with defaults (`AudioSource.SINE`, `SubtitleSource.GENERATED_SRT`), so existing fixtures continue to parse without edits.

- [ ] **Step 1: Write failing tests**

Append to `tests/contract/test_scenario.py`:

```python
from chaos_librarian.contract.scenario import (
    AudioSource,
    AudioTrack,
    SubtitleSource,
    SubtitleTrack,
    VideoSource,
    VideoTrack,
)


def test_video_track_source_accepts_enum_values():
    """WHY: Sprint 5 narrows VideoTrack.source from str to a fixed enum.

    The schema authors must not silently typo `mandlebrot` and have it
    pass; an unknown value must raise ValidationError at parse time.
    """
    track = VideoTrack(source=VideoSource.MANDELBROT, codec="h264", resolution="hd")
    assert track.source is VideoSource.MANDELBROT


def test_video_track_source_rejects_unknown_value():
    payload = {"source": "mandlebrot", "codec": "h264", "resolution": "hd"}
    with pytest.raises(ValidationError):
        VideoTrack.model_validate(payload)


def test_audio_track_source_defaults_to_sine():
    """WHY: existing fixtures don't set AudioTrack.source; the default
    must preserve their parse without edits."""
    track = AudioTrack(codec="aac", channels="stereo", language="eng")
    assert track.source is AudioSource.SINE


def test_subtitle_track_source_defaults_to_generated_srt():
    track = SubtitleTrack(codec="srt", language="eng", mode="sidecar")
    assert track.source is SubtitleSource.GENERATED_SRT


def test_scenario_schema_version_is_two():
    from chaos_librarian.contract import SCENARIO_SCHEMA_VERSION

    assert SCENARIO_SCHEMA_VERSION == 2
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/contract/test_scenario.py -v`
Expected: ImportError on `AudioSource`/`SubtitleSource`/`VideoSource`; `SCENARIO_SCHEMA_VERSION == 2` fails.

- [ ] **Step 3: Bump the constant**

Edit `src/chaos_librarian/contract/__init__.py:16`:

```python
SCENARIO_SCHEMA_VERSION: Final = 2
```

- [ ] **Step 4: Add the enums and narrow the fields**

Edit `src/chaos_librarian/contract/scenario.py`. Add after the existing `TimelineActionName` enum block:

```python
class VideoSource(enum.StrEnum):
    """Synthesis recipe for the video stream of an asset."""

    MANDELBROT = "mandelbrot"
    COLOR_BARS = "color_bars"
    SOLID_COLOR = "solid_color"
    NOISE = "noise"  # Sprint 6+ in materialize; passes validate today.


class AudioSource(enum.StrEnum):
    """Synthesis recipe for an audio stream."""

    SINE = "sine"
    SILENCE = "silence"
    CHANNEL_TONES = "channel_tones"


class SubtitleSource(enum.StrEnum):
    """Synthesis recipe for a subtitle track."""

    GENERATED_SRT = "generated_srt"
```

Change `VideoTrack`:

```python
class VideoTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: VideoSource
    codec: str
    resolution: str
```

Change `AudioTrack`:

```python
class AudioTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: AudioSource = AudioSource.SINE
    codec: str
    channels: str
    language: str
```

Change `SubtitleTrack`:

```python
class SubtitleTrack(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: SubtitleSource = SubtitleSource.GENERATED_SRT
    codec: str
    language: str
    mode: Literal["embedded", "sidecar"]
```

Change `Scenario.schema_version`:

```python
schema_version: Literal[2]
```

- [ ] **Step 5: Update any in-line `schema_version: 1` literals in `Scenario.model_validate(...)` examples or fixtures used by docstrings**

Search and update: `rg "schema_version.: 1" src/chaos_librarian/contract/scenario.py`
Expected: no inline literals in the source file. If any docstring example shows `schema_version: 1`, bump to `2`.

- [ ] **Step 6: Run the focused test suite — passes**

Run: `uv run pytest tests/contract/test_scenario.py tests/contract/test_sample_scenarios.py -v`
Expected: all green. `test_sample_scenarios.py` is the smoke loader over every fixture; defaulted audio/subtitle sources mean no fixture edits are needed for it to pass.

- [ ] **Step 7: Regenerate schemas**

Run: `uv run python -m chaos_librarian.schema_export --write`
Expected: `Wrote 11 schemas to .../schemas`. `git diff schemas/scenario.schema.json` shows the three new enum definitions and the `Literal[2]` `schema_version`.

- [ ] **Step 8: Confirm drift gate is clean**

Run: `uv run python -m chaos_librarian.schema_export --check`
Expected: `All 11 schemas up-to-date.`

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest -q`
Expected: every test passes.

- [ ] **Step 10: Lint and type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 11: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/scenario.py \
        schemas/scenario.schema.json \
        tests/contract/test_scenario.py
git commit -m "$(cat <<'EOF'
feat(contract): bump scenario v2 with audio/subtitle source enums

Sprint 5 needs source-driven recipe dispatch on every track type.
VideoTrack.source narrows from str to a fixed enum (mandelbrot,
color_bars, solid_color, noise). AudioTrack and SubtitleTrack gain
source fields with defaults (AudioSource.SINE, SubtitleSource.
GENERATED_SRT) so the existing six fixtures continue to parse without
edits. Adds the v2 schema artifact.

Refs sprint 5 design doc Decision 9.
EOF
)"
```

---

## Task 2: Manifest v2 — `ProbedMedia`, `ManifestVersion.probed`, `ManifestSidecar.content_hash`

**Files:**

- Modify: `src/chaos_librarian/contract/__init__.py:17` — bump `MANIFEST_SCHEMA_VERSION` 1 → 2.
- Modify: `src/chaos_librarian/contract/manifest.py` — add `ProbedStream`, `ProbedMedia`; extend `ManifestVersion`, `ManifestSidecar`; bump `Manifest.schema_version: Literal[2]`.
- Modify: `tests/contract/test_manifest.py` — coverage for the new fields and the `exclude_none=True` round-trip invariant.
- Auto-regenerated: `schemas/manifest.schema.json`.

`content_hash: str | None = None` already exists on `ManifestVersion` (Sprint 0 placed it forward-compatibly). Sprint 5 adds `probed: ProbedMedia | None = None` next to it. Both stay `None` in plan-only — `exclude_none=True` keeps the serialized JSON bit-identical for the existing Sprint 3 plan-only contract. `ManifestSidecar` gains `content_hash: str | None = None` per Finding 1 of the adversarial review (SRT sidecar hash provenance).

- [ ] **Step 1: Write failing tests**

Append to `tests/contract/test_manifest.py`:

```python
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestSidecar,
    ManifestVersion,
    ProbedMedia,
    ProbedStream,
)


def test_probed_stream_video_only_fields():
    """WHY: Stream subtype fields (width/height/fps for video, channels for
    audio, default/forced for subtitle) must coexist on one model so the
    same `streams[]` array can hold heterogeneous entries from ffprobe."""
    stream = ProbedStream(kind="video", codec="h264", width=1920, height=1080, fps=24.0)
    assert stream.channels is None
    assert stream.sample_rate is None


def test_probed_media_round_trip():
    media = ProbedMedia(
        container="matroska,webm",
        duration_seconds=2.0,
        size_bytes=12345,
        streams=[
            ProbedStream(kind="video", codec="h264", width=640, height=480, fps=24.0),
            ProbedStream(kind="audio", codec="aac", channels=2, sample_rate=48000),
        ],
    )
    payload = media.model_dump_json(exclude_none=True)
    loaded = ProbedMedia.model_validate_json(payload)
    assert loaded == media


def test_manifest_version_probed_defaults_none():
    """WHY: plan-only manifests must stay bit-identical post-v2 bump.
    The default None plus exclude_none=True in the writer guarantees that."""
    version = ManifestVersion(id="v0", asset_id="a0", index=0)
    payload = version.model_dump(exclude_none=True)
    assert "probed" not in payload
    assert "content_hash" not in payload


def test_manifest_sidecar_content_hash_optional():
    sidecar = ManifestSidecar(id="s0", asset_id="a0", kind="srt", path="library/a/0.srt")
    assert sidecar.content_hash is None
    payload = sidecar.model_dump(exclude_none=True)
    assert "content_hash" not in payload


def test_manifest_schema_version_is_two():
    from chaos_librarian.contract import MANIFEST_SCHEMA_VERSION

    assert MANIFEST_SCHEMA_VERSION == 2
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/contract/test_manifest.py -v`
Expected: ImportError on `ProbedMedia`/`ProbedStream`; `MANIFEST_SCHEMA_VERSION == 2` fails.

- [ ] **Step 3: Bump the constant**

Edit `src/chaos_librarian/contract/__init__.py:17`:

```python
MANIFEST_SCHEMA_VERSION: Final = 2
```

- [ ] **Step 4: Add `ProbedStream` and `ProbedMedia`**

Edit `src/chaos_librarian/contract/manifest.py`. Add to the imports if missing: `from typing import Literal`. Add these classes near the top (after the existing module docstring, before the existing manifest types):

```python
class ProbedStream(BaseModel):
    """One stream from ``ffprobe -show_streams``.

    Optional fields are populated only for the matching ``kind``; ffprobe
    silently omits the others, and ``exclude_none=True`` keeps the serialized
    output compact.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["video", "audio", "subtitle"]
    codec: str
    language: str | None = None
    width: int | None = None         # video-only
    height: int | None = None        # video-only
    fps: float | None = None         # video-only
    channels: int | None = None      # audio-only
    sample_rate: int | None = None   # audio-only
    default: bool | None = None      # subtitle-only
    forced: bool | None = None       # subtitle-only


class ProbedMedia(BaseModel):
    """Output of ``ffprobe -show_format -show_streams`` mapped into a model."""

    model_config = ConfigDict(extra="forbid")

    container: str
    duration_seconds: float
    size_bytes: int
    streams: list[ProbedStream]
```

- [ ] **Step 5: Extend `ManifestVersion` and `ManifestSidecar`**

In the same file, change `ManifestVersion`:

```python
class ManifestVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    asset_id: str
    index: int
    content_hash: str | None = None
    probed: ProbedMedia | None = None
```

Change `ManifestSidecar`:

```python
class ManifestSidecar(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    asset_id: str
    kind: str
    path: str
    content_hash: str | None = None
```

Change `Manifest.schema_version`:

```python
schema_version: Literal[2]
```

- [ ] **Step 6: Run focused tests — pass**

Run: `uv run pytest tests/contract/test_manifest.py -v`
Expected: all green.

- [ ] **Step 7: Regenerate schemas**

Run: `uv run python -m chaos_librarian.schema_export --write`
Expected: `Wrote 11 schemas to .../schemas`. `git diff schemas/manifest.schema.json` shows the new `ProbedMedia`/`ProbedStream` definitions and the `Literal[2]` `schema_version`.

- [ ] **Step 8: Drift gate clean**

Run: `uv run python -m chaos_librarian.schema_export --check`
Expected: `All 11 schemas up-to-date.`

- [ ] **Step 9: Full suite and lint/type**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all clean.

- [ ] **Step 10: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/manifest.py \
        schemas/manifest.schema.json \
        tests/contract/test_manifest.py
git commit -m "$(cat <<'EOF'
feat(contract): bump manifest v2 with ProbedMedia + sidecar content_hash

ManifestVersion gains probed: ProbedMedia | None = None (content_hash
already at v1). ManifestSidecar gains content_hash: str | None = None
per the adversarial-review fix for SRT sidecar hash provenance.

Plan-only serialization stays bit-identical thanks to exclude_none=True
in the writer. Materialize manifests populate both fields.

Refs sprint 5 design doc Decision 5 + Finding 1.
EOF
)"
```

---

## Task 3: RunSentinel v2 — `state` field plus CLI surface

**Files:**

- Modify: `src/chaos_librarian/contract/__init__.py:22` — bump `RUN_SENTINEL_SCHEMA_VERSION` 1 → 2.
- Modify: `src/chaos_librarian/contract/run_sentinel.py` — add `state` field; `schema_version: Literal[2]`.
- Modify: `tests/contract/test_run_sentinel.py` — default / explicit-value / unknown-value coverage.
- Modify: `src/chaos_librarian/engine/writer.py:_emit_sentinel` — passes `state` through (default `complete` keeps plan-only behavior).
- Modify: `src/chaos_librarian/cli/app.py` — `inspect` surfaces sentinel state; `step` refuses `in_progress` with `E_SENTINEL_IN_PROGRESS` exit 7.
- Modify: `tests/cli/test_inspect.py` — state-surface assertions.
- Modify: `tests/cli/test_step.py` — in-progress refusal assertion.
- Auto-regenerated: `schemas/run-sentinel.schema.json`.

Per Finding 2 of the adversarial review, the sentinel needs a `state` field so future tooling can detect interrupted materialize runs. The default `"complete"` keeps Sprint 0 plan-only behavior; only the (Sprint 5) materializer will ever write `"in_progress"`.

- [ ] **Step 1: Write failing contract tests**

Append to `tests/contract/test_run_sentinel.py`:

```python
def test_sentinel_state_defaults_to_complete():
    """WHY: plan-only writes the sentinel via the model default; the value
    must be 'complete' so existing fixtures continue to pass inspect."""
    sentinel = RunSentinel(
        run_id=uuid.uuid4(),
        schema_version=RUN_SENTINEL_SCHEMA_VERSION,
        created_by="chaos-librarian/0.1.0",
    )
    assert sentinel.state == "complete"


def test_sentinel_state_accepts_in_progress():
    sentinel = RunSentinel(
        run_id=uuid.uuid4(),
        schema_version=RUN_SENTINEL_SCHEMA_VERSION,
        created_by="chaos-librarian/0.1.0",
        state="in_progress",
    )
    assert sentinel.state == "in_progress"


def test_sentinel_rejects_unknown_state():
    payload = {
        "run_id": str(uuid.uuid4()),
        "schema_version": RUN_SENTINEL_SCHEMA_VERSION,
        "created_by": "chaos-librarian/0.1.0",
        "state": "halfway",
    }
    with pytest.raises(ValidationError):
        RunSentinel.model_validate(payload)


def test_sentinel_schema_version_is_two():
    assert RUN_SENTINEL_SCHEMA_VERSION == 2
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/contract/test_run_sentinel.py -v`
Expected: assertion failures and ValidationError surprises (because the unknown-state case currently passes — `state` field doesn't exist).

- [ ] **Step 3: Bump the constant and add the field**

Edit `src/chaos_librarian/contract/__init__.py:22`:

```python
RUN_SENTINEL_SCHEMA_VERSION: Final = 2
```

Edit `src/chaos_librarian/contract/run_sentinel.py`:

```python
class RunSentinel(BaseModel):
    """Top-level ``.chaos-librarian-run`` sentinel file."""

    model_config = ConfigDict(extra="forbid")

    run_id: uuid.UUID
    # ty rejects ``Literal[CONSTANT]`` (PEP 586 indirect form); hardcode.
    schema_version: Literal[2]
    created_by: str
    created_at: datetime | None = None
    state: Literal["in_progress", "complete"] = "complete"
```

- [ ] **Step 4: Update `engine/writer.py:_emit_sentinel`**

The existing `_emit_sentinel` writes whatever sentinel it's handed. The field is on the model with a default, so the function body needs no change. Verify by running:

```
rg "_emit_sentinel" src/chaos_librarian/engine
```

Expected: one call site in `write_fixture` passing `artifacts.sentinel`. Confirm `artifacts.sentinel` is built without an explicit `state` (so the default fires). If `PlanArtifacts` or `_build_sentinel` exists elsewhere, ensure no caller passes a different value yet.

- [ ] **Step 5: Run contract tests — pass**

Run: `uv run pytest tests/contract/test_run_sentinel.py -v`
Expected: all green.

- [ ] **Step 6: Regenerate schemas**

Run: `uv run python -m chaos_librarian.schema_export --write`
Expected: `Wrote 11 schemas to .../schemas`. `git diff schemas/run-sentinel.schema.json` shows the new `state` enum and `Literal[2]` version.

- [ ] **Step 7: Write CLI tests — `inspect` surfaces state**

Append to `tests/cli/test_inspect.py`. Use the existing fixture conventions:

```python
def test_inspect_reports_complete_state(tmp_path: Path) -> None:
    """WHY: every plan-only run-dir reports state=complete; agents read
    the field to distinguish completed runs from interrupted materialize."""
    out = tmp_path / "run"
    plan_result = runner.invoke(
        app,
        ["plan", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out)],
    )
    assert plan_result.exit_code == 0, plan_result.stdout + plan_result.stderr

    result = runner.invoke(app, ["inspect", str(out), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["sentinel"]["state"] == "complete"


def test_inspect_reports_in_progress_state(tmp_path: Path) -> None:
    """WHY: an interrupted materialize run leaves the sentinel at
    state=in_progress; inspect must surface that so an agent can clean it."""
    out = tmp_path / "interrupted"
    plan_result = runner.invoke(
        app,
        ["plan", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out)],
    )
    assert plan_result.exit_code == 0
    sentinel_path = out / ".chaos-librarian-run"
    sentinel = RunSentinel.model_validate_json(sentinel_path.read_text())
    sentinel_in_progress = sentinel.model_copy(update={"state": "in_progress"})
    sentinel_path.write_text(
        sentinel_in_progress.model_dump_json(indent=2, exclude_none=True) + "\n"
    )

    result = runner.invoke(app, ["inspect", str(out), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["sentinel"]["state"] == "in_progress"
```

Add the necessary imports at the top of the file if not present:

```python
from chaos_librarian.contract.run_sentinel import RunSentinel
```

- [ ] **Step 8: Write CLI test — `step` refuses `in_progress`**

Append to `tests/cli/test_step.py`:

```python
def test_step_refuses_in_progress_sentinel(tmp_path: Path) -> None:
    """WHY: a partial materialize run-dir must not be advanced by step;
    step exits 7 with E_SENTINEL_IN_PROGRESS so an agent surfaces it."""
    out = tmp_path / "run"
    plan_result = runner.invoke(
        app,
        ["plan", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out)],
    )
    assert plan_result.exit_code == 0
    sentinel_path = out / ".chaos-librarian-run"
    sentinel = RunSentinel.model_validate_json(sentinel_path.read_text())
    in_progress = sentinel.model_copy(update={"state": "in_progress"})
    sentinel_path.write_text(
        in_progress.model_dump_json(indent=2, exclude_none=True) + "\n"
    )

    result = runner.invoke(app, ["step", str(out), "--json"])
    assert result.exit_code == 7
    payload = json.loads(result.stderr)
    assert payload["error"] == "E_SENTINEL_IN_PROGRESS"
```

Add the `RunSentinel` import to `test_step.py` if missing.

- [ ] **Step 9: Run failing CLI tests**

Run: `uv run pytest tests/cli/test_inspect.py tests/cli/test_step.py -v`
Expected: new tests fail — `inspect` JSON doesn't include `sentinel.state`; `step` doesn't refuse `in_progress`.

- [ ] **Step 10: Wire `state` into `inspect` output**

Find the `inspect` JSON-payload assembler in `src/chaos_librarian/cli/app.py` (search for the function building the inspect-mode dict). Add a `"sentinel"` key:

```python
payload["sentinel"] = {
    "state": sentinel.state,
    "created_at": sentinel.created_at.isoformat() if sentinel.created_at else None,
    "run_id": str(sentinel.run_id),
}
```

For human mode, append a line:

```python
typer.echo(f"sentinel:    state={sentinel.state}, run_id={sentinel.run_id}")
```

(Match the exact field-by-field layout the existing `inspect` human output uses; preserve column alignment.)

- [ ] **Step 11: Wire `step` refusal**

Find the `_verify_sentinel` (or equivalent) helper in `cli/app.py` and the `step` command body. After parsing the sentinel and before calling `step_fixture`, add:

```python
if sentinel.state == "in_progress":
    _emit_step_error(
        "E_SENTINEL_IN_PROGRESS",
        f"sentinel state is in_progress; clean the run-dir before stepping: {run_dir}",
        json_output=json_output,
    )
    raise typer.Exit(code=7)
```

`_emit_step_error` already writes to stderr; the exit code is 7 per the spec error model.

- [ ] **Step 12: Run focused tests — pass**

Run: `uv run pytest tests/cli/test_inspect.py tests/cli/test_step.py -v`
Expected: all green.

- [ ] **Step 13: Drift gate + full suite**

Run: `uv run python -m chaos_librarian.schema_export --check && uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all clean.

- [ ] **Step 14: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/run_sentinel.py \
        src/chaos_librarian/cli/app.py \
        schemas/run-sentinel.schema.json \
        tests/contract/test_run_sentinel.py \
        tests/cli/test_inspect.py \
        tests/cli/test_step.py
git commit -m "$(cat <<'EOF'
feat(contract): bump run-sentinel v2 with state field; wire CLI surface

RunSentinel gains state: Literal['in_progress', 'complete'] = 'complete'
so future tooling can detect interrupted materialize runs without a
separate marker file. inspect surfaces the field in JSON and human
output; step refuses in_progress with E_SENTINEL_IN_PROGRESS (exit 7).
Plan-only callers continue to use the default 'complete' value, keeping
Sprint 0's bit-identical fixture guarantee.

Refs sprint 5 design doc Decision 13 + Finding 2.
EOF
)"
```

---

## Task 4: Capabilities contract module

**Files:**

- Create: `src/chaos_librarian/contract/capabilities.py` — `Capabilities`, `ToolStatus`, `ReadyFor` models.
- Modify: `src/chaos_librarian/contract/__init__.py` — add `CAPABILITIES_SCHEMA_VERSION: Final = 1`.
- Create: `tests/contract/test_capabilities.py` — round-trip + exclude_none invariants.
- Auto-regenerated: scheduled in Task 8 alongside the other contract bumps and the export-list change.

The contract for `capabilities --json`. Mirrors the spec's exact JSON shape (Decision 4). Schema export wiring lands in Task 8 to batch with the export-list edit.

- [ ] **Step 1: Add the version constant**

Edit `src/chaos_librarian/contract/__init__.py`. Add after `BUNDLE_REPORT_SCHEMA_VERSION`:

```python
CAPABILITIES_SCHEMA_VERSION: Final = 1
```

- [ ] **Step 2: Write failing tests**

Create `tests/contract/test_capabilities.py`:

```python
"""Contract round-trip tests for Capabilities."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import CAPABILITIES_SCHEMA_VERSION
from chaos_librarian.contract.capabilities import (
    Capabilities,
    ReadyFor,
    ToolStatus,
)


def _ok_tool(version: str = "7.1.1", path: str = "/usr/bin/ffmpeg") -> ToolStatus:
    return ToolStatus(found=True, version=version, path=path, meets_minimum=True)


def test_capabilities_round_trip():
    """WHY: external consumers parse this JSON via their own JSON Schema
    consumer; a round-trip with exclude_none=True is the contract."""
    caps = Capabilities(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        ffmpeg=_ok_tool(),
        ffprobe=_ok_tool(path="/usr/bin/ffprobe"),
        mkvtoolnix=ToolStatus(found=False, version=None, path=None, meets_minimum=False),
        platform="darwin-arm64",
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=False,
        ),
    )
    payload = caps.model_dump_json(indent=2, exclude_none=True)
    loaded = Capabilities.model_validate_json(payload)
    assert loaded == caps


def test_tool_status_optional_fields_omitted_when_none():
    """WHY: when a tool is not found, version/path must serialize as None
    (or be absent under exclude_none) — not as empty strings."""
    tool = ToolStatus(found=False, version=None, path=None, meets_minimum=False)
    rendered = json.loads(tool.model_dump_json(exclude_none=True))
    assert rendered == {"found": False, "meets_minimum": False}


def test_capabilities_schema_version_pinned():
    payload = {
        "schema_version": 99,
        "ffmpeg": _ok_tool().model_dump(),
        "ffprobe": _ok_tool(path="/usr/bin/ffprobe").model_dump(),
        "mkvtoolnix": ToolStatus(found=False, version=None, path=None, meets_minimum=False).model_dump(),
        "platform": "darwin-arm64",
        "ready_for": ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=False,
        ).model_dump(),
    }
    with pytest.raises(ValidationError):
        Capabilities.model_validate(payload)
```

- [ ] **Step 3: Run failing tests**

Run: `uv run pytest tests/contract/test_capabilities.py -v`
Expected: ImportError — module does not exist.

- [ ] **Step 4: Create the contract module**

Create `src/chaos_librarian/contract/capabilities.py`:

```python
"""Capability-detection report schema.

Output of ``chaos-librarian capabilities --json``. Materialize re-runs
the same detection at startup and refuses (exit 4) if the gate regresses.
See ``docs/superpowers/specs/2026-05-18-sprint-5-design.md`` §"Capability
Detection".
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class ToolStatus(BaseModel):
    """Detection outcome for one external tool."""

    model_config = ConfigDict(extra="forbid")

    found: bool
    version: str | None = None
    path: str | None = None
    meets_minimum: bool


class ReadyFor(BaseModel):
    """Forward-looking signals — which materialize modes the toolchain supports.

    Sprint 5 only consults ``materialize_static``. The other two flags are
    populated so adapter authors can skip Sprint 6/7 tests cleanly.
    """

    model_config = ConfigDict(extra="forbid")

    materialize_static: bool
    materialize_filesystem_mutations: bool
    materialize_media_mutations: bool


class Capabilities(BaseModel):
    """Full ``capabilities --json`` payload."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    ffmpeg: ToolStatus
    ffprobe: ToolStatus
    mkvtoolnix: ToolStatus
    platform: str
    ready_for: ReadyFor
```

- [ ] **Step 5: Run focused tests — pass**

Run: `uv run pytest tests/contract/test_capabilities.py -v`
Expected: all green. Schema-export drift will not yet detect anything because the export list hasn't been edited; Task 8 handles that.

- [ ] **Step 6: Lint/type focused**

Run: `uv run ruff check src/chaos_librarian/contract/capabilities.py tests/contract/test_capabilities.py && uv run ty check src/chaos_librarian/contract/capabilities.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/capabilities.py \
        tests/contract/test_capabilities.py
git commit -m "$(cat <<'EOF'
feat(contract): add Capabilities model for capabilities --json

Sprint 5 CLI emits a structured Capabilities payload describing
ffmpeg/ffprobe/mkvtoolnix availability plus forward-looking ready_for
flags. Schema export wiring lands in the schema-regen task with the
other v2 bumps to keep the drift gate landing in one commit.

Refs sprint 5 design doc Decision 4.
EOF
)"
```

---

## Task 5: MaterializationReport v2 — `Outcome`, `ToolchainInfo`, asset/failure records

**Files:**

- Modify: `src/chaos_librarian/contract/__init__.py:21` — bump `MATERIALIZATION_SCHEMA_VERSION` 1 → 2.
- Modify: `src/chaos_librarian/contract/materialization.py` — replace Sprint 0 stub with the filled-in v2 shape.
- Modify: `tests/contract/test_materialization.py` — coverage of every new type.
- Auto-regenerated: `schemas/materialization.schema.json` (in Task 8).

The Sprint 0 stub had `status: MaterializationStatus` and an empty invocations list. Sprint 5 fills it out per spec §"Composition flow" and §"Failure cleanup". The rename `status → outcome` brings the value `success` into the enum (Sprint 0 implicitly meant "no failures present"). `ToolchainInfo` is a structured Pydantic model used both here and by `MaterializeReplayBundle` (Task 6).

- [ ] **Step 1: Write failing tests**

Replace `tests/contract/test_materialization.py` contents with:

```python
"""Contract round-trip tests for MaterializationReport v2."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from chaos_librarian.contract import MATERIALIZATION_SCHEMA_VERSION
from chaos_librarian.contract.materialization import (
    MaterializationFailure,
    MaterializationReport,
    MaterializedAsset,
    Outcome,
    ToolchainInfo,
    ToolInvocation,
)


def _minimal_report(**overrides: object) -> MaterializationReport:
    defaults: dict[str, object] = {
        "schema_version": MATERIALIZATION_SCHEMA_VERSION,
        "run_id": uuid.uuid4(),
        "outcome": Outcome.SUCCESS,
        "platform": "darwin-arm64",
        "started_at": datetime(2026, 5, 18, 0, 0, 0, tzinfo=UTC),
        "finished_at": datetime(2026, 5, 18, 0, 0, 1, tzinfo=UTC),
        "toolchain": ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
    }
    defaults.update(overrides)
    return MaterializationReport.model_validate(defaults)


def test_minimal_success_report_round_trips():
    """WHY: success-path materialize writes invocations + materialized; the
    minimal report (no failures) must round-trip cleanly."""
    report = _minimal_report(
        materialized=[
            MaterializedAsset(
                asset_id="a0",
                location_path="library/movie/main.mkv",
                content_hash="sha256:" + "0" * 64,
                size_bytes=1234,
                duration_seconds=2.0,
                invocation_index=0,
            ),
        ],
        invocations=[
            ToolInvocation(
                tool="ffmpeg",
                version="7.1.1",
                command=["ffmpeg", "-version"],
                exit_code=0,
                duration_ns=1_000_000,
            ),
        ],
    )
    blob = report.model_dump_json(exclude_none=True)
    assert MaterializationReport.model_validate_json(blob) == report


def test_failure_report_records_per_asset_failure():
    """WHY: spec failure model records asset_id, stage, exit_code,
    stderr_tail, invocation_index — every materialize tool failure surfaces
    these via materialization.json so an agent can debug without grep."""
    report = _minimal_report(
        outcome=Outcome.TOOL_FAILED,
        failures=[
            MaterializationFailure(
                asset_id="a0",
                stage="ffmpeg",
                exit_code=1,
                stderr_tail="x264 [error]: bad input",
                invocation_index=0,
            ),
        ],
    )
    blob = report.model_dump_json(exclude_none=True)
    loaded = MaterializationReport.model_validate_json(blob)
    assert loaded.failures[0].stage == "ffmpeg"


def test_outcome_enum_accepts_all_documented_values():
    for value in (
        Outcome.SUCCESS,
        Outcome.UNSUPPORTED,
        Outcome.TOOL_FAILED,
        Outcome.TOOL_MISSING,
        Outcome.CONTAINMENT_VIOLATION,
    ):
        assert _minimal_report(outcome=value).outcome is value


def test_unknown_outcome_value_rejected():
    payload = {
        "schema_version": MATERIALIZATION_SCHEMA_VERSION,
        "run_id": str(uuid.uuid4()),
        "outcome": "broken",
        "platform": "darwin-arm64",
        "started_at": "2026-05-18T00:00:00Z",
        "finished_at": "2026-05-18T00:00:01Z",
        "toolchain": {"ffmpeg": "7.1.1"},
    }
    with pytest.raises(ValidationError):
        MaterializationReport.model_validate(payload)


def test_materialization_schema_version_is_two():
    assert MATERIALIZATION_SCHEMA_VERSION == 2
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/contract/test_materialization.py -v`
Expected: ImportError on `Outcome` / `MaterializedAsset` / `MaterializationFailure` / `ToolchainInfo`.

- [ ] **Step 3: Bump the constant**

Edit `src/chaos_librarian/contract/__init__.py:21`:

```python
MATERIALIZATION_SCHEMA_VERSION: Final = 2
```

- [ ] **Step 4: Replace the contract module**

Overwrite `src/chaos_librarian/contract/materialization.py`:

```python
"""Materialization report schema (v2).

Filled out for Sprint 5: started_at/finished_at, platform, structured
ToolchainInfo, per-asset MaterializedAsset records, per-failure
MaterializationFailure records, and an Outcome enum that includes
``success`` (Sprint 0 used the absence of failures as the success signal).
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Outcome(enum.StrEnum):
    """High-level materialize result.

    ``unsupported`` covers both timeline-rejection and matrix-rejection.
    ``tool_failed`` covers both ffmpeg subprocess errors and ffprobe parse
    failures.
    """

    SUCCESS = "success"
    UNSUPPORTED = "unsupported"
    TOOL_FAILED = "tool_failed"
    TOOL_MISSING = "tool_missing"
    CONTAINMENT_VIOLATION = "containment_violation"


class ToolchainInfo(BaseModel):
    """Versions of the external tools used during materialization.

    Shared with ``MaterializeReplayBundle`` so consumers see one shape.
    Every field is optional because a tool may be missing on a system that
    nevertheless succeeded at static materialize (mkvtoolnix in Sprint 5).
    """

    model_config = ConfigDict(extra="forbid")

    ffmpeg: str | None = None
    ffprobe: str | None = None
    mkvtoolnix: str | None = None


class ToolInvocation(BaseModel):
    """One subprocess invocation captured for the replay bundle and report."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    version: str
    command: list[str]
    exit_code: int
    duration_ns: int


class MaterializedAsset(BaseModel):
    """Per-asset success record."""

    model_config = ConfigDict(extra="forbid")

    asset_id: str
    location_path: str
    content_hash: str
    size_bytes: int
    duration_seconds: float
    invocation_index: int


class MaterializationFailure(BaseModel):
    """Per-failure record.

    ``asset_id`` is None for non-per-asset stages (e.g. capability
    regression). ``invocation_index`` indexes into ``invocations`` when the
    failure came from a subprocess call.
    """

    model_config = ConfigDict(extra="forbid")

    asset_id: str | None
    stage: str
    exit_code: int | None
    stderr_tail: str
    invocation_index: int | None


class MaterializationReport(BaseModel):
    """Top-level ``materialization.json`` body."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[2]
    run_id: uuid.UUID
    outcome: Outcome
    platform: str
    started_at: datetime
    finished_at: datetime
    toolchain: ToolchainInfo
    invocations: list[ToolInvocation] = Field(default_factory=list)
    materialized: list[MaterializedAsset] = Field(default_factory=list)
    failures: list[MaterializationFailure] = Field(default_factory=list)
```

- [ ] **Step 5: Run focused tests — pass**

Run: `uv run pytest tests/contract/test_materialization.py -v`
Expected: all green.

- [ ] **Step 6: Lint and type-check focused**

Run: `uv run ruff check src/chaos_librarian/contract/materialization.py tests/contract/test_materialization.py && uv run ty check src/chaos_librarian/contract/materialization.py`
Expected: clean.

- [ ] **Step 7: Full suite (drift gate still red — Task 8 closes it)**

Run: `uv run pytest -q --deselect tests/contract/test_schema_export.py`
Expected: every test except schema-export tests passes. The schema-export ones are expected to fail until Task 8 regenerates and pins the new schema set; that's by design — bundling schema regen with the export-list edit keeps Task 8 a single coherent commit.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/materialization.py \
        tests/contract/test_materialization.py
git commit -m "$(cat <<'EOF'
feat(contract): bump materialization v2 with Outcome + structured types

Replaces the Sprint 0 stub. status -> outcome (adds success value);
adds platform, started_at, finished_at, structured ToolchainInfo,
MaterializedAsset and MaterializationFailure records. Schema export
+ drift gate land in the schema-regen task to keep the regenerated
JSON Schema file in the same commit as the export list edit.

Refs sprint 5 design doc §Composition flow + §Failure cleanup.
EOF
)"
```

---

## Task 6: ReplayBundle v3 — `Literal[0]` applied_events, structured ToolchainInfo

**Files:**

- Modify: `src/chaos_librarian/contract/__init__.py:19` — bump `REPLAY_BUNDLE_SCHEMA_VERSION` 2 → 3.
- Modify: `src/chaos_librarian/contract/replay_bundle.py` — base class `schema_version: Literal[3]`; `MaterializeReplayBundle.applied_events: Literal[0] = 0`; `MaterializeReplayBundle.toolchain: ToolchainInfo`.
- Modify: `tests/contract/test_replay_bundle.py` — coverage for the new constraints.
- Auto-regenerated: `schemas/replay-bundle.schema.json` (in Task 8).

`MaterializeReplayBundle` already exists at v2; Sprint 5 pins `applied_events` at zero (Sprint 5's timeline is always empty) and promotes `toolchain` from `dict[str, str]` to the structured `ToolchainInfo` model added in Task 5.

- [ ] **Step 1: Write failing tests**

Append to `tests/contract/test_replay_bundle.py`:

```python
from chaos_librarian.contract import REPLAY_BUNDLE_SCHEMA_VERSION
from chaos_librarian.contract.materialization import ToolchainInfo
from chaos_librarian.contract.replay_bundle import (
    ExecutionMode,
    MaterializeReplayBundle,
)


def _materialize_payload(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "schema_version": REPLAY_BUNDLE_SCHEMA_VERSION,
        "chaos_librarian_version": "0.1.0",
        "scenario": "schema_version: 2\nscenario_id: x\n",
        "run_id": "00000000-0000-4000-8000-000000000000",
        "resolved_seed": 1,
        "applied_events": 0,
        "journal_digest": "0" * 64,
        "execution_mode": "materialize",
        "created_at": "2026-05-18T00:00:00Z",
        "toolchain": {"ffmpeg": "7.1.1"},
    }
    base.update(overrides)
    return base


def test_materialize_bundle_rejects_nonzero_applied_events():
    """WHY: Sprint 5 timelines are always empty; the schema must lock
    applied_events at 0 so a future code regression that emits a non-zero
    value is caught at parse time, not silently round-tripped."""
    payload = _materialize_payload(applied_events=1)
    with pytest.raises(ValidationError):
        MaterializeReplayBundle.model_validate(payload)


def test_materialize_bundle_accepts_zero_applied_events():
    bundle = MaterializeReplayBundle.model_validate(_materialize_payload())
    assert bundle.applied_events == 0


def test_materialize_bundle_toolchain_is_structured():
    """WHY: Sprint 5 unifies the toolchain shape with MaterializationReport
    via ToolchainInfo; the bundle's toolchain must be the same model."""
    bundle = MaterializeReplayBundle.model_validate(_materialize_payload())
    assert isinstance(bundle.toolchain, ToolchainInfo)
    assert bundle.toolchain.ffmpeg == "7.1.1"


def test_materialize_bundle_toolchain_rejects_unknown_tool():
    payload = _materialize_payload(toolchain={"ffmpeg": "7.1.1", "imagemagick": "7.0"})
    with pytest.raises(ValidationError):
        MaterializeReplayBundle.model_validate(payload)


def test_replay_bundle_schema_version_is_three():
    assert REPLAY_BUNDLE_SCHEMA_VERSION == 3
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/contract/test_replay_bundle.py -v`
Expected: `applied_events=1` round-trips today; `toolchain` is `dict` not `ToolchainInfo`; constant assertion fails.

- [ ] **Step 3: Bump the constant**

Edit `src/chaos_librarian/contract/__init__.py:19`:

```python
REPLAY_BUNDLE_SCHEMA_VERSION: Final = 3
```

- [ ] **Step 4: Update the contract module**

Edit `src/chaos_librarian/contract/replay_bundle.py`. Add `ToolchainInfo` to the imports:

```python
from chaos_librarian.contract.materialization import ToolchainInfo
```

Change `_ReplayBundleBase.schema_version`:

```python
schema_version: Literal[3]
```

Replace `MaterializeReplayBundle`:

```python
class MaterializeReplayBundle(_ReplayBundleBase):
    """Replay bundle in materialize or run mode.

    ``applied_events`` is pinned to 0 in Sprint 5 because every materialize
    timeline is empty; the base class constraint will widen again in Sprint 6.
    ``created_at`` and ``toolchain`` are both required (non-null).
    """

    execution_mode: Literal[ExecutionMode.MATERIALIZE, ExecutionMode.RUN]
    applied_events: Literal[0] = 0
    created_at: datetime
    toolchain: ToolchainInfo
```

- [ ] **Step 5: Run focused tests — pass**

Run: `uv run pytest tests/contract/test_replay_bundle.py -v`
Expected: all green.

- [ ] **Step 6: Lint/type focused**

Run: `uv run ruff check src/chaos_librarian/contract/replay_bundle.py tests/contract/test_replay_bundle.py && uv run ty check src/chaos_librarian/contract/replay_bundle.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/replay_bundle.py \
        tests/contract/test_replay_bundle.py
git commit -m "$(cat <<'EOF'
feat(contract): bump replay-bundle v3 with Literal[0] materialize events

MaterializeReplayBundle.applied_events: Literal[0] = 0 locks the
Sprint 5 contract: every materialize timeline is empty, and the schema
must reject a regression that emits a non-zero count rather than
silently round-trip it. toolchain promotes from dict[str, str] to the
structured ToolchainInfo added in Task 5. Schema regen lands with the
other v2/v3 bumps in the schema-regen task.

Refs sprint 5 design doc Decision 11.
EOF
)"
```

---

## Task 7: AssetReport v2 — `content_hash` and `probed` on `AssetSnapshot`

**Files:**

- Modify: `src/chaos_librarian/contract/__init__.py:23` — bump `ASSET_REPORT_SCHEMA_VERSION` 1 → 2.
- Modify: `src/chaos_librarian/contract/reports.py` — `AssetSnapshot` gains `content_hash` and `probed`; `AssetReport.schema_version: Literal[2]`.
- Modify: `tests/contract/test_reports.py` — coverage for the new fields and the report-set v1 stability for Work/Variant/Bundle.
- Auto-regenerated: `schemas/asset-report.schema.json` (in Task 8).

Per spec Decision 12 only `AssetReport` bumps. The other three report classes stay at v1 because they carry id lists, not embedded snapshots.

- [ ] **Step 1: Write failing tests**

Append to `tests/contract/test_reports.py`:

```python
from chaos_librarian.contract import (
    ASSET_REPORT_SCHEMA_VERSION,
    BUNDLE_REPORT_SCHEMA_VERSION,
    VARIANT_REPORT_SCHEMA_VERSION,
    WORK_REPORT_SCHEMA_VERSION,
)
from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream
from chaos_librarian.contract.reports import AssetSnapshot


def test_asset_snapshot_carries_content_hash_and_probed():
    """WHY: adapter consumers see materialized facts on AssetReport without
    joining back through manifest.versions[]; if the fields aren't carried,
    consumers re-implement the join and drift apart."""
    snap = AssetSnapshot(
        location_path="library/movie/main.mkv",
        version_id="v0",
        version_index=0,
        content_hash="sha256:" + "0" * 64,
        probed=ProbedMedia(
            container="matroska,webm",
            duration_seconds=2.0,
            size_bytes=12345,
            streams=[ProbedStream(kind="video", codec="h264", width=640, height=480, fps=24.0)],
        ),
    )
    blob = snap.model_dump_json(exclude_none=True)
    loaded = AssetSnapshot.model_validate_json(blob)
    assert loaded == snap


def test_asset_snapshot_omits_new_fields_when_none():
    """WHY: plan-only reports stay byte-stable post-bump; the writer's
    exclude_none=True relies on the defaults being None."""
    snap = AssetSnapshot(location_path=None, version_id="v0", version_index=0)
    rendered = snap.model_dump(exclude_none=True)
    assert "content_hash" not in rendered
    assert "probed" not in rendered


def test_asset_report_schema_version_is_two():
    assert ASSET_REPORT_SCHEMA_VERSION == 2


def test_other_report_schema_versions_stay_at_one():
    """WHY: only AssetReport bumps; Work/Variant/Bundle carry id lists, not
    embedded snapshots. If one of them silently bumps to 2, voom-v2 will
    fail at the discriminator."""
    assert WORK_REPORT_SCHEMA_VERSION == 1
    assert VARIANT_REPORT_SCHEMA_VERSION == 1
    assert BUNDLE_REPORT_SCHEMA_VERSION == 1
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/contract/test_reports.py -v`
Expected: `content_hash`/`probed` reject (extra="forbid" rejects unknown fields); `ASSET_REPORT_SCHEMA_VERSION == 2` fails.

- [ ] **Step 3: Bump the constant**

Edit `src/chaos_librarian/contract/__init__.py:23`:

```python
ASSET_REPORT_SCHEMA_VERSION: Final = 2
```

- [ ] **Step 4: Extend `AssetSnapshot`**

Edit `src/chaos_librarian/contract/reports.py`. Add to imports:

```python
from chaos_librarian.contract.manifest import ProbedMedia
```

Change `AssetSnapshot`:

```python
class AssetSnapshot(BaseModel):
    """A point-in-time view of one asset's location + version binding."""

    model_config = ConfigDict(extra="forbid")

    location_path: str | None  # None if the asset is currently deleted
    version_id: str
    version_index: int
    content_hash: str | None = None
    probed: ProbedMedia | None = None
```

Change `AssetReport.schema_version`:

```python
schema_version: Literal[2]
```

Leave `WorkReport`, `VariantReport`, `BundleReport` untouched.

- [ ] **Step 5: Run focused tests — pass**

Run: `uv run pytest tests/contract/test_reports.py -v`
Expected: all green.

- [ ] **Step 6: Lint/type focused**

Run: `uv run ruff check src/chaos_librarian/contract/reports.py tests/contract/test_reports.py && uv run ty check src/chaos_librarian/contract/reports.py`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/contract/__init__.py \
        src/chaos_librarian/contract/reports.py \
        tests/contract/test_reports.py
git commit -m "$(cat <<'EOF'
feat(contract): bump asset-report v2 with content_hash + probed snapshot

AssetSnapshot gains content_hash + probed so adapter consumers see the
materialized facts without joining back through manifest.versions[].
Work/Variant/Bundle reports stay at v1 because they carry id lists, not
snapshots — Sprint 4's reports module docstring anticipates this.

Refs sprint 5 design doc Decision 12.
EOF
)"
```

---

## Task 8: Schema export — register capabilities, regenerate all bumped schemas, close drift gate

**Files:**

- Modify: `src/chaos_librarian/schema_export.py` — add `("capabilities.schema.json", Capabilities)` to `MODELS`.
- Modify: `tests/contract/test_schema_export.py` — bump the pinned set from 11 → 12 entries.
- Modify: `tests/contract/test_contract_constants.py` — add `CAPABILITIES_SCHEMA_VERSION` to the import list and to the version count check; also add the four sprint-4 report constants the digest noted are missing today.
- Auto-regenerated: `schemas/capabilities.schema.json` (new), `schemas/manifest.schema.json`, `schemas/materialization.schema.json`, `schemas/replay-bundle.schema.json`, `schemas/scenario.schema.json`, `schemas/asset-report.schema.json`, `schemas/run-sentinel.schema.json` (all REGEN to v2/v3).

This task closes the drift gate that Tasks 1-7 left open. The capabilities schema gets its first export here; the six bumped schemas land their v2/v3 versions.

- [ ] **Step 1: Update the export-list pin in the schema-export test**

Edit `tests/contract/test_schema_export.py`. Find the pinned set and change to:

```python
EXPECTED_SCHEMAS: Final = {
    "asset-report.schema.json",
    "bundle-report.schema.json",
    "capabilities.schema.json",
    "journal.schema.json",
    "manifest.schema.json",
    "materialization.schema.json",
    "replay-bundle.schema.json",
    "run-sentinel.schema.json",
    "scenario.schema.json",
    "validation.schema.json",
    "variant-report.schema.json",
    "work-report.schema.json",
}
```

(Verify by reading the existing top-of-file: this preserves the file's `Final[set[str]]` style; adapt if the existing constant uses a different shape.)

- [ ] **Step 2: Update the contract-constants test**

Edit `tests/contract/test_contract_constants.py`. Add `CAPABILITIES_SCHEMA_VERSION` and the four report constants to the imports and to the `versions` list assertion. The full updated check looks like:

```python
from chaos_librarian.contract import (
    ASSET_REPORT_SCHEMA_VERSION,
    BUNDLE_REPORT_SCHEMA_VERSION,
    CAPABILITIES_SCHEMA_VERSION,
    JOURNAL_SCHEMA_VERSION,
    MANIFEST_SCHEMA_VERSION,
    MATERIALIZATION_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
    RUN_SENTINEL_SCHEMA_VERSION,
    SCENARIO_SCHEMA_VERSION,
    VALIDATION_SCHEMA_VERSION,
    VARIANT_REPORT_SCHEMA_VERSION,
    WORK_REPORT_SCHEMA_VERSION,
)


def test_all_schema_versions_are_positive_ints():
    """WHY: each Final = N must infer Literal[N] in ty and serialize as int."""
    versions = [
        ASSET_REPORT_SCHEMA_VERSION,
        BUNDLE_REPORT_SCHEMA_VERSION,
        CAPABILITIES_SCHEMA_VERSION,
        JOURNAL_SCHEMA_VERSION,
        MANIFEST_SCHEMA_VERSION,
        MATERIALIZATION_SCHEMA_VERSION,
        REPLAY_BUNDLE_SCHEMA_VERSION,
        RUN_SENTINEL_SCHEMA_VERSION,
        SCENARIO_SCHEMA_VERSION,
        VALIDATION_SCHEMA_VERSION,
        VARIANT_REPORT_SCHEMA_VERSION,
        WORK_REPORT_SCHEMA_VERSION,
    ]
    assert all(isinstance(v, int) and v >= 1 for v in versions)
```

- [ ] **Step 3: Run failing tests**

Run: `uv run pytest tests/contract/test_schema_export.py tests/contract/test_contract_constants.py -v`
Expected: schema-export tests fail because `capabilities.schema.json` is missing and the bumped schema files don't match.

- [ ] **Step 4: Register `Capabilities` in the schema export**

Edit `src/chaos_librarian/schema_export.py`. Add to the imports:

```python
from chaos_librarian.contract.capabilities import Capabilities
```

Add to the `MODELS` list (alphabetical or matching existing order):

```python
("capabilities.schema.json", Capabilities),
```

- [ ] **Step 5: Regenerate every schema**

Run: `uv run python -m chaos_librarian.schema_export --write`
Expected: `Wrote 12 schemas to .../schemas`. `git status --short` shows seven schema files changed (one new, six modified).

- [ ] **Step 6: Confirm the drift gate is clean**

Run: `uv run python -m chaos_librarian.schema_export --check`
Expected: `All 12 schemas up-to-date.`

- [ ] **Step 7: Verify discriminator presence on the regenerated unions**

Run: `uv run pytest tests/contract/test_schema_export.py -v`
Expected: all green — including the `test_journal_schema_has_oneof_on_phase` and `test_replay_bundle_schema_has_oneof_on_execution_mode` discriminator assertions.

- [ ] **Step 8: Sanity-check the materialization schema contains the new types**

Run: `rg "MaterializedAsset|MaterializationFailure|ToolchainInfo" schemas/materialization.schema.json`
Expected: at least three hits each — confirms the v2 fill-in landed in the regenerated artifact.

- [ ] **Step 9: Full suite + lint + type**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: every test passes; lint and type clean.

- [ ] **Step 10: Commit**

```bash
git add src/chaos_librarian/schema_export.py \
        schemas/capabilities.schema.json \
        schemas/manifest.schema.json \
        schemas/materialization.schema.json \
        schemas/replay-bundle.schema.json \
        schemas/scenario.schema.json \
        schemas/asset-report.schema.json \
        schemas/run-sentinel.schema.json \
        tests/contract/test_schema_export.py \
        tests/contract/test_contract_constants.py
git commit -m "$(cat <<'EOF'
feat(schema-export): register capabilities + regen 6 bumped schemas

Closes the drift gate Tasks 1-7 left open. Adds capabilities.schema.json
(v1) and regenerates manifest, materialization, replay-bundle, scenario,
asset-report, and run-sentinel at their new versions. Schema set grows
from 11 to 12.

Also adds CAPABILITIES_SCHEMA_VERSION + the four Sprint 4 report
constants to test_contract_constants.py — the report constants were
present in __init__.py but never asserted by the constants test.

Refs sprint 5 design doc §Generated artifacts + §Layer 1 contract drift gate.
EOF
)"
```

---

## Task 9: Canonicalization helper

**Files:**

- Create: `src/chaos_librarian/contract/canonicalize.py` — pure helper over `Manifest`.
- Create: `tests/contract/test_canonicalize.py` — strip + preserve coverage.

The canonicalization rule strips fields that legitimately vary across toolchains (`content_hash`, `probed`, `wall_clock_time`, `run_id`, `toolchain`) so two manifests produced by different ffmpeg builds compare equal modulo bytes. Sprint 9's voom-v2 adapter will be its first cross-toolchain consumer; Sprint 5 only proves the helper doesn't strip too much.

- [ ] **Step 1: Write failing tests**

Create `tests/contract/test_canonicalize.py`:

```python
"""Layer 4 sibling — canonicalize() strips volatile fields without losing
structural ones."""

from __future__ import annotations

from chaos_librarian.contract.canonicalize import canonicalize
from chaos_librarian.contract.manifest import (
    Manifest,
    ManifestAsset,
    ManifestBundle,
    ManifestLocation,
    ManifestSidecar,
    ManifestVariant,
    ManifestVersion,
    ManifestWork,
    ProbedMedia,
    ProbedStream,
)


def _manifest(*, content_hash: str | None, probed: ProbedMedia | None) -> Manifest:
    return Manifest(
        schema_version=2,
        works=[ManifestWork(id="w0", title="Title")],
        variants=[ManifestVariant(id="va0", work_id="w0", label="hd")],
        bundles=[ManifestBundle(id="b0", variant_id="va0")],
        assets=[
            ManifestAsset(
                id="a0", bundle_id="b0", role="main", container="mkv", duration_seconds=2.0
            )
        ],
        versions=[
            ManifestVersion(
                id="v0",
                asset_id="a0",
                index=0,
                content_hash=content_hash,
                probed=probed,
            )
        ],
        locations=[ManifestLocation(id="l0", asset_id="a0", path="library/w0/va0/main.mkv")],
        sidecars=[
            ManifestSidecar(
                id="s0",
                asset_id="a0",
                kind="srt",
                path="library/w0/va0/main.eng.srt",
                content_hash="sha256:" + "f" * 64,
            )
        ],
    )


def test_canonicalize_strips_content_hash_and_probed():
    """WHY: cross-toolchain hash comparison is meaningless; only the
    structural shape (works/variants/bundles/assets/versions/locations/
    sidecars + their ids and paths) is comparable."""
    left = _manifest(
        content_hash="sha256:" + "0" * 64,
        probed=ProbedMedia(
            container="matroska,webm",
            duration_seconds=2.0,
            size_bytes=12345,
            streams=[ProbedStream(kind="video", codec="h264", width=640, height=480, fps=24.0)],
        ),
    )
    right = _manifest(content_hash=None, probed=None)
    assert canonicalize(left) == canonicalize(right)


def test_canonicalize_preserves_structural_fields():
    """WHY: a too-aggressive strip would make every manifest compare equal."""
    m = _manifest(content_hash=None, probed=None)
    out = canonicalize(m)
    assert [w["id"] for w in out["works"]] == ["w0"]
    assert out["assets"][0]["container"] == "mkv"
    assert out["locations"][0]["path"] == "library/w0/va0/main.mkv"
    assert out["sidecars"][0]["path"] == "library/w0/va0/main.eng.srt"


def test_canonicalize_strips_sidecar_content_hash():
    """WHY: sidecar bytes also differ across toolchains (subtle UTF-8 BOM
    handling, newline conventions); the structural sidecar entry stays."""
    m = _manifest(content_hash=None, probed=None)
    out = canonicalize(m)
    assert "content_hash" not in out["sidecars"][0]
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/contract/test_canonicalize.py -v`
Expected: ImportError — module does not exist.

- [ ] **Step 3: Create the helper**

Create `src/chaos_librarian/contract/canonicalize.py`:

```python
"""Cross-toolchain manifest canonicalization.

Strips fields that legitimately vary across ffmpeg/ffprobe builds so two
manifests produced by different toolchains compare equal on structure.

Stripped fields:
- ``versions[].content_hash``, ``versions[].probed``
- ``sidecars[].content_hash``

Sprint 5 ships this pure helper; Sprint 9's voom-v2 adapter is its first
cross-toolchain consumer. Plan-only equivalence (same toolchain, same
seed) is byte-exact and does NOT need canonicalization.
"""

from __future__ import annotations

from typing import Any

from chaos_librarian.contract.manifest import Manifest


def canonicalize(manifest: Manifest) -> dict[str, Any]:
    """Return a dict suitable for == comparison across toolchains.

    The returned shape is a JSON-compatible dict (lists/dicts/primitives);
    callers should NOT round-trip it back through ``Manifest.model_validate``
    (the stripped fields would fail re-parse if a stricter schema requires
    them in the future).
    """
    blob = manifest.model_dump(mode="json", exclude_none=True)
    for version in blob.get("versions", []):
        version.pop("content_hash", None)
        version.pop("probed", None)
    for sidecar in blob.get("sidecars", []):
        sidecar.pop("content_hash", None)
    return blob
```

- [ ] **Step 4: Run focused tests — pass**

Run: `uv run pytest tests/contract/test_canonicalize.py -v`
Expected: all green.

- [ ] **Step 5: Lint/type/full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/contract/canonicalize.py \
        tests/contract/test_canonicalize.py
git commit -m "$(cat <<'EOF'
feat(contract): add canonicalize() for cross-toolchain manifest equality

Pure helper over Manifest that strips fields that legitimately vary
across ffmpeg/ffprobe builds (versions[].content_hash, versions[].probed,
sidecars[].content_hash). Returns a dict[str, Any] for == comparison.

Sprint 9's voom-v2 adapter will be the first cross-toolchain consumer;
Sprint 5 only proves the helper does not strip structural fields by
accident.

Refs sprint 5 design doc §Testing strategy Layer 4 sibling test.
EOF
)"
```

---

## Task 10: Materializer error hierarchy

**Files:**

- Create: `src/chaos_librarian/materializer/__init__.py` — empty marker; real re-exports land in Task 18.
- Create: `src/chaos_librarian/materializer/errors.py` — base + 6 subclasses.
- Create: `tests/materializer/__init__.py` — empty marker.
- Create: `tests/materializer/test_errors.py` — shape + base coverage.

Establishes the exception base used by every materializer module. The CLI's `materialize` try/except ladder (Task 20) converts each subclass to its exit code and JSON payload.

- [ ] **Step 1: Create empty markers**

Create `src/chaos_librarian/materializer/__init__.py`:

```python
"""Materializer package — synthesis, subprocess wrappers, run orchestrator.

Public API re-exports land in a follow-up task after the orchestrator
ships; this initial commit only carries the error hierarchy.
"""

from __future__ import annotations
```

Create `tests/materializer/__init__.py`:

```python
```

(empty file — pytest needs it as a package marker)

- [ ] **Step 2: Write failing tests**

Create `tests/materializer/test_errors.py`:

```python
"""Materializer error hierarchy — every subclass carries an error_code."""

from __future__ import annotations

import pytest

from chaos_librarian.materializer.errors import (
    CapabilityGateError,
    ContainmentViolationError,
    MaterializationError,
    ProbeParseError,
    ScenarioValidationError,
    TimelineUnsupportedError,
    ToolFailedError,
    UnsupportedMaterializationError,
)


def test_every_subclass_carries_an_error_code():
    """WHY: the CLI handler dispatches on the subclass and reads error_code
    into the stdout JSON payload; if any subclass forgets to set it, the
    agent sees a payload missing the field."""
    for cls in (
        TimelineUnsupportedError,
        UnsupportedMaterializationError,
        ToolFailedError,
        ProbeParseError,
        ContainmentViolationError,
        CapabilityGateError,
        ScenarioValidationError,
    ):
        assert issubclass(cls, MaterializationError)
        instance = cls.__new__(cls)
        assert hasattr(cls, "error_code")
        assert cls.error_code.startswith("E_MATERIALIZE_") or cls.error_code in {
            "E_PATH_CONTAINMENT",
            "E_MATERIALIZE_CAPABILITY_GATE",
        }


def test_base_error_holds_payload():
    """WHY: every error carries the structured payload the CLI emits as
    --json stdout; missing fields default to None so the payload shape is
    consistent across error types."""
    err = MaterializationError(
        message="x",
        error_code="E_MATERIALIZE_UNSUPPORTED",
        asset_id="a0",
        field="audio[0].codec",
        payload={"supported": ["aac"]},
    )
    assert err.error_code == "E_MATERIALIZE_UNSUPPORTED"
    assert err.payload["supported"] == ["aac"]


def test_tool_failed_carries_invocation():
    """WHY: the ToolFailedError uniquely carries the failing ToolInvocation
    so the CLI can record it in materialization.json — failing the assertion
    would mean we lose subprocess stderr at the exit boundary."""
    from chaos_librarian.contract.materialization import ToolInvocation

    invocation = ToolInvocation(
        tool="ffmpeg",
        version="7.1.1",
        command=["ffmpeg", "-i", "..."],
        exit_code=1,
        duration_ns=1_000_000,
    )
    err = ToolFailedError(
        message="ffmpeg failed",
        asset_id="a0",
        field=None,
        payload={"stderr_tail": "x264 error"},
        invocation=invocation,
    )
    assert err.invocation.exit_code == 1


def test_scenario_validation_error_carries_report():
    """WHY: the materialize entry validates the scenario explicitly before
    any run-dir allocation (Finding 1). When semantic validation fails, the
    orchestrator raises ScenarioValidationError carrying the full
    ValidationReport so the CLI can serialize it into the stdout JSON
    payload at exit 3 — the same shape as `plan`'s reference behavior."""
    from chaos_librarian.contract.validation import (
        ValidationIssue,
        ValidationReport,
        ValidationSeverity,
    )

    report = ValidationReport(
        schema_version=1,
        ok=False,
        scenario_id="bad",
        issues=[
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="E_PATH_CONTAINMENT",
                message="asset path escapes library/",
                line=None,
                column=None,
                path=None,
            )
        ],
    )
    err = ScenarioValidationError(
        "scenario failed semantic validation",
        payload={"validation_report": report.model_dump(mode="json", exclude_none=True)},
        validation_report=report,
    )
    assert err.error_code == "E_MATERIALIZE_VALIDATION_FAILED"
    assert err.validation_report.ok is False
    assert err.validation_report.issues[0].code == "E_PATH_CONTAINMENT"
```

- [ ] **Step 3: Run failing tests**

Run: `uv run pytest tests/materializer/test_errors.py -v`
Expected: ImportError — module does not exist.

- [ ] **Step 4: Create the errors module**

Create `src/chaos_librarian/materializer/errors.py`:

```python
"""Exception hierarchy raised by the materializer.

Every concrete subclass carries an ``error_code`` class attribute matching
the spec's error model. The CLI handler dispatches on subclass identity
and reads ``error_code`` / ``asset_id`` / ``field`` / ``payload`` into the
stdout JSON.
"""

from __future__ import annotations

from typing import ClassVar

from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.validation import ValidationReport


class MaterializationError(Exception):
    """Base for every materializer-raised error."""

    error_code: ClassVar[str] = "E_MATERIALIZE_UNKNOWN"

    def __init__(
        self,
        message: str,
        *,
        error_code: str | None = None,
        asset_id: str | None = None,
        field: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        super().__init__(message)
        if error_code is not None:
            self.error_code = error_code
        self.message = message
        self.asset_id = asset_id
        self.field = field
        self.payload: dict[str, object] = dict(payload or {})


class TimelineUnsupportedError(MaterializationError):
    """Scenario has a non-empty timeline — Sprint 5 rejects."""

    error_code: ClassVar[str] = "E_MATERIALIZE_TIMELINE_UNSUPPORTED"


class UnsupportedMaterializationError(MaterializationError):
    """Container/codec/resolution/channels combination outside Sprint 5 matrix."""

    error_code: ClassVar[str] = "E_MATERIALIZE_UNSUPPORTED"


class ToolFailedError(MaterializationError):
    """ffmpeg subprocess exited non-zero."""

    error_code: ClassVar[str] = "E_MATERIALIZE_TOOL_FAILED"

    def __init__(self, *args: object, invocation: ToolInvocation, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.invocation = invocation


class ProbeParseError(MaterializationError):
    """ffprobe stdout could not be parsed into ProbedMedia."""

    error_code: ClassVar[str] = "E_MATERIALIZE_PROBE_PARSE_FAILED"


class ContainmentViolationError(MaterializationError):
    """A scenario path resolved outside ``<run-dir>/library/``."""

    error_code: ClassVar[str] = "E_PATH_CONTAINMENT"


class CapabilityGateError(MaterializationError):
    """ffmpeg or ffprobe missing or below minimum at materialize startup."""

    error_code: ClassVar[str] = "E_MATERIALIZE_CAPABILITY_GATE"


class ScenarioValidationError(MaterializationError):
    """Scenario passed YAML parse but failed semantic validation.

    Raised by the orchestrator's pre-allocation gate (Finding 1) so the
    materialize entry mirrors ``plan``'s validate-before-act behavior. The
    CLI handler dispatches this to exit 3, matching ``plan``'s convention.
    """

    error_code: ClassVar[str] = "E_MATERIALIZE_VALIDATION_FAILED"

    def __init__(
        self,
        *args: object,
        validation_report: ValidationReport,
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]
        self.validation_report = validation_report
```

- [ ] **Step 5: Run focused tests — pass**

Run: `uv run pytest tests/materializer/test_errors.py -v`
Expected: all green.

- [ ] **Step 6: Lint/type focused**

Run: `uv run ruff check src/chaos_librarian/materializer/ tests/materializer/ && uv run ty check src/chaos_librarian/materializer/`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/materializer/__init__.py \
        src/chaos_librarian/materializer/errors.py \
        tests/materializer/__init__.py \
        tests/materializer/test_errors.py
git commit -m "$(cat <<'EOF'
feat(materializer): add error hierarchy for materialize-mode CLI dispatch

Six concrete subclasses of MaterializationError, each carrying an
error_code class attribute matching the spec's error model. The CLI
materialize handler will dispatch on subclass identity and read
error_code/asset_id/field/payload into the --json stdout payload.

ToolFailedError uniquely carries the failing ToolInvocation so we don't
lose subprocess stderr at the exit boundary.

Refs sprint 5 design doc §Error model.
EOF
)"
```

---

## Task 11: Capability detection — `materializer/capabilities.py`

**Files:**

- Modify: `pyproject.toml` — add `packaging>=24` to dependencies.
- Create: `src/chaos_librarian/materializer/capabilities.py` — `detect_capabilities`, `_canonical_version_from_tool_output`, `assert_capable_for_static_materialize`.
- Create: `tests/materializer/test_capabilities.py` — Layer 2 unit coverage (mocked subprocess + the seven version-normalization cases from Finding 4).

Implements the spec's detection algorithm (steps 1-5) with the version-normalization helper added by Finding 4 of the adversarial review. `subprocess.run` is monkeypatched at the module boundary so the tests are pure.

- [ ] **Step 1: Add the `packaging` dependency**

Edit `pyproject.toml`. Find the `[project] dependencies = [...]` array and add `"packaging>=24"`. Pin the same way other deps are pinned (exact `==` if the project uses that convention; otherwise `>=24`).

Run: `uv sync`
Expected: lockfile updates; new package installed.

- [ ] **Step 2: Write failing tests**

Create `tests/materializer/test_capabilities.py`:

```python
"""Layer 2 — capability detection with subprocess mocked at the boundary."""

from __future__ import annotations

import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Final

import pytest
from packaging.version import Version

from chaos_librarian.materializer import capabilities as cap_mod
from chaos_librarian.materializer.capabilities import (
    MIN_VERSIONS,
    _canonical_version_from_tool_output,
    assert_capable_for_static_materialize,
    detect_capabilities,
)
from chaos_librarian.materializer.errors import CapabilityGateError

OK_FFMPEG: Final = "ffmpeg version 7.1.1 Copyright (c) 2000-2024 the FFmpeg developers"
OK_FFPROBE: Final = "ffprobe version 7.1.1 Copyright (c) 2000-2024 the FFmpeg developers"
OK_MKV: Final = "mkvmerge v80.0 ('Roundabout') 64-bit"
OLD_FFMPEG: Final = "ffmpeg version 6.1.1 Copyright (c) 2000-2023 the FFmpeg developers"


def _stub_subprocess_run(returns: dict[str, str]) -> object:
    """Build a subprocess.run stub indexed by argv[0]."""

    def stub(argv: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        tool = Path(argv[0]).name
        stdout = returns.get(tool, "")
        return subprocess.CompletedProcess(args=argv, returncode=0, stdout=stdout, stderr="")

    return stub


def _stub_which(paths: dict[str, str]) -> object:
    def stub(name: str) -> str | None:
        return paths.get(name)

    return stub


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("7.1.1", Version("7.1.1")),
        ("n7.1-0ubuntu1", Version("7.1")),
        ("7.0.2-3ubuntu1", Version("7.0.2")),
        ("n7.0 Copyright (c) ...", Version("7.0")),
        ("6.1.1", Version("6.1.1")),
    ],
)
def test_canonical_version_accepts_distro_tagged_strings(raw: str, expected: Version) -> None:
    """WHY: Ubuntu packages ship versions like 'n7.1-0ubuntu1' which
    packaging.version.Version rejects raw; the helper must normalize so a
    working Ubuntu FFmpeg passes the gate."""
    assert _canonical_version_from_tool_output(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "N-118412-g0ce1c8f7c5 (git build)",
        "<garbage>",
        "",
    ],
)
def test_canonical_version_returns_none_on_malformed_input(raw: str) -> None:
    """WHY: git-snapshot builds and unparseable strings must be reported as
    found-but-malformed, not raise — the caller marks meets_minimum=False."""
    assert _canonical_version_from_tool_output(raw) is None


def test_detect_capabilities_all_present_above_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cap_mod,
        "shutil_which",
        _stub_which(
            {"ffmpeg": "/usr/bin/ffmpeg", "ffprobe": "/usr/bin/ffprobe", "mkvmerge": "/usr/bin/mkvmerge"}
        ),
    )
    monkeypatch.setattr(
        cap_mod.subprocess,
        "run",
        _stub_subprocess_run({"ffmpeg": OK_FFMPEG, "ffprobe": OK_FFPROBE, "mkvmerge": OK_MKV}),
    )
    caps = detect_capabilities()
    assert caps.ffmpeg.meets_minimum
    assert caps.ffprobe.meets_minimum
    assert caps.mkvtoolnix.meets_minimum
    assert caps.ready_for.materialize_static
    assert caps.ready_for.materialize_media_mutations


def test_detect_capabilities_ffmpeg_below_minimum(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cap_mod,
        "shutil_which",
        _stub_which({"ffmpeg": "/usr/bin/ffmpeg", "ffprobe": "/usr/bin/ffprobe"}),
    )
    monkeypatch.setattr(
        cap_mod.subprocess,
        "run",
        _stub_subprocess_run({"ffmpeg": OLD_FFMPEG, "ffprobe": OK_FFPROBE}),
    )
    caps = detect_capabilities()
    assert caps.ffmpeg.found and not caps.ffmpeg.meets_minimum
    assert not caps.ready_for.materialize_static


def test_detect_capabilities_mkvtoolnix_missing_static_still_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WHY: Sprint 5's static materialize doesn't need mkvtoolnix; absent
    mkvmerge must not block materialize_static."""
    monkeypatch.setattr(
        cap_mod,
        "shutil_which",
        _stub_which({"ffmpeg": "/usr/bin/ffmpeg", "ffprobe": "/usr/bin/ffprobe"}),
    )
    monkeypatch.setattr(
        cap_mod.subprocess,
        "run",
        _stub_subprocess_run({"ffmpeg": OK_FFMPEG, "ffprobe": OK_FFPROBE}),
    )
    caps = detect_capabilities()
    assert caps.ready_for.materialize_static
    assert not caps.ready_for.materialize_media_mutations
    assert not caps.mkvtoolnix.found


def test_detect_capabilities_subprocess_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        cap_mod,
        "shutil_which",
        _stub_which({"ffmpeg": "/usr/bin/ffmpeg"}),
    )

    def raise_timeout(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=5)

    monkeypatch.setattr(cap_mod.subprocess, "run", raise_timeout)
    caps = detect_capabilities()
    assert not caps.ffmpeg.meets_minimum
    assert caps.ffmpeg.version is None


def test_assert_capable_raises_on_regression() -> None:
    from chaos_librarian.contract.capabilities import Capabilities, ReadyFor, ToolStatus

    caps = Capabilities(
        schema_version=1,
        ffmpeg=ToolStatus(found=False, meets_minimum=False),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="darwin-arm64",
        ready_for=ReadyFor(
            materialize_static=False,
            materialize_filesystem_mutations=False,
            materialize_media_mutations=False,
        ),
    )
    with pytest.raises(CapabilityGateError):
        assert_capable_for_static_materialize(caps)


def test_min_versions_constant_matches_spec() -> None:
    assert MIN_VERSIONS["ffmpeg"] == Version("7.0")
    assert MIN_VERSIONS["ffprobe"] == Version("7.0")
    assert MIN_VERSIONS["mkvtoolnix"] == Version("80")
```

- [ ] **Step 3: Run failing tests**

Run: `uv run pytest tests/materializer/test_capabilities.py -v`
Expected: ImportError — module does not exist.

- [ ] **Step 4: Create the capabilities module**

Create `src/chaos_librarian/materializer/capabilities.py`:

```python
"""Capability detection — ffmpeg, ffprobe, mkvtoolnix.

Used by ``chaos-librarian capabilities`` and by ``chaos-librarian
materialize`` (which re-runs the gate at startup and refuses on regression).
"""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Final

from packaging.version import InvalidVersion, Version

from chaos_librarian.contract import CAPABILITIES_SCHEMA_VERSION
from chaos_librarian.contract.capabilities import (
    Capabilities,
    ReadyFor,
    ToolStatus,
)
from chaos_librarian.materializer.errors import CapabilityGateError

MIN_VERSIONS: Final[dict[str, Version]] = {
    "ffmpeg": Version("7.0"),
    "ffprobe": Version("7.0"),
    "mkvtoolnix": Version("80"),
}

_VERSION_RE: Final[dict[str, re.Pattern[str]]] = {
    "ffmpeg": re.compile(r"^ffmpeg version (\S+)"),
    "ffprobe": re.compile(r"^ffprobe version (\S+)"),
    "mkvmerge": re.compile(r"^mkvmerge v(\S+)"),
}

# Indirection so tests can monkeypatch shutil.which at the module boundary.
shutil_which = shutil.which


def _canonical_version_from_tool_output(raw: str) -> Version | None:
    """Normalize a tool's reported version into a comparable ``Version``.

    Handles distro-tagged strings like ``n7.1-0ubuntu1`` and
    ``7.0.2-3ubuntu1`` by extracting the upstream MAJOR[.MINOR[.PATCH]]
    triplet. Git-snapshot builds (``N-118412-g0ce1c8f7c5``) and
    unparseable strings return ``None`` (caller treats as
    ``meets_minimum=False``).
    """
    match = re.match(r"^[nN]?(\d+(?:\.\d+){0,2})", raw)
    if not match:
        return None
    try:
        return Version(match.group(1))
    except InvalidVersion:
        return None


def _probe_one(name: str, *, regex_key: str) -> ToolStatus:
    path = shutil_which(name)
    if path is None:
        return ToolStatus(found=False, version=None, path=None, meets_minimum=False)
    try:
        result = subprocess.run(
            [path, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return ToolStatus(found=True, version=None, path=path, meets_minimum=False)
    first_line = (result.stdout or "").splitlines()[0] if result.stdout else ""
    pattern = _VERSION_RE[regex_key]
    match = pattern.match(first_line)
    if not match:
        return ToolStatus(found=True, version=None, path=path, meets_minimum=False)
    raw = match.group(1)
    parsed = _canonical_version_from_tool_output(raw)
    if parsed is None:
        return ToolStatus(found=True, version=None, path=path, meets_minimum=False)
    minimum_key = {"ffmpeg": "ffmpeg", "ffprobe": "ffprobe", "mkvmerge": "mkvtoolnix"}[regex_key]
    return ToolStatus(
        found=True,
        version=str(parsed),
        path=path,
        meets_minimum=parsed >= MIN_VERSIONS[minimum_key],
    )


def detect_capabilities() -> Capabilities:
    """Probe ffmpeg, ffprobe, mkvmerge and return a Capabilities report."""
    ffmpeg = _probe_one("ffmpeg", regex_key="ffmpeg")
    ffprobe = _probe_one("ffprobe", regex_key="ffprobe")
    mkv = _probe_one("mkvmerge", regex_key="mkvmerge")
    ffmpeg_ok = ffmpeg.meets_minimum
    ffprobe_ok = ffprobe.meets_minimum
    mkv_ok = mkv.meets_minimum
    return Capabilities(
        schema_version=CAPABILITIES_SCHEMA_VERSION,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        mkvtoolnix=mkv,
        platform=f"{platform.system().lower()}-{platform.machine().lower()}",
        ready_for=ReadyFor(
            materialize_static=ffmpeg_ok and ffprobe_ok,
            materialize_filesystem_mutations=ffmpeg_ok and ffprobe_ok,
            materialize_media_mutations=ffmpeg_ok and ffprobe_ok and mkv_ok,
        ),
    )


def assert_capable_for_static_materialize(caps: Capabilities) -> None:
    """Raise ``CapabilityGateError`` (exit 4) if ffmpeg or ffprobe failed."""
    if caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum:
        return
    missing: list[str] = []
    if not caps.ffmpeg.meets_minimum:
        missing.append("ffmpeg")
    if not caps.ffprobe.meets_minimum:
        missing.append("ffprobe")
    raise CapabilityGateError(
        f"required tool(s) missing or below minimum: {', '.join(missing)}",
        payload={"capabilities": caps.model_dump(mode="json", exclude_none=True)},
    )
```

- [ ] **Step 5: Run focused tests — pass**

Run: `uv run pytest tests/materializer/test_capabilities.py -v`
Expected: all green.

- [ ] **Step 6: Lint/type/full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock \
        src/chaos_librarian/materializer/capabilities.py \
        tests/materializer/test_capabilities.py
git commit -m "$(cat <<'EOF'
feat(materializer): capability detection with distro-version normalize

Implements detect_capabilities + assert_capable_for_static_materialize.
The version-normalize helper handles Ubuntu-packaged FFmpeg strings
(n7.1-0ubuntu1, 7.0.2-3ubuntu1) so packaging.version.Version doesn't
reject them. Git-snapshot builds (N-118412-g0ce1c8f7c5) return None and
the tool is reported found-but-malformed.

Adds packaging>=24 to runtime deps.

Refs sprint 5 design doc §Capability Detection + Finding 4.
EOF
)"
```

---

## Task 12: Content recipes — video sources

**Files:**

- Create: `src/chaos_librarian/materializer/recipes.py` — `FFmpegInput` + `recipe_mandelbrot`, `recipe_color_bars`, `recipe_solid_color`; deterministic seed helpers.
- Create: `tests/materializer/test_recipes.py` — Layer 2 video-source coverage. Audio and SRT cases extend this file in Tasks 13-14.

Pure functions over `(width, height, fps, duration_s, seed)`. No subprocess. Sprint 5's bit-exactness depends on these producing identical lavfi expressions for identical seeds.

- [ ] **Step 1: Write failing tests**

Create `tests/materializer/test_recipes.py`:

```python
"""Layer 2 — content recipes. Pure functions, no subprocess."""

from __future__ import annotations

import pytest

from chaos_librarian.materializer.recipes import (
    FFmpegInput,
    recipe_color_bars,
    recipe_mandelbrot,
    recipe_solid_color,
)


def test_mandelbrot_emits_stable_lavfi_for_seed():
    """WHY: bit-exactness across runs requires that the same seed produce
    the same lavfi expression byte-for-byte. Inline the expected value so
    a future change to the seed-to-scale mapping is caught by this test."""
    fi = recipe_mandelbrot(width=1920, height=1080, fps=24, duration_s=2.0, seed=42)
    assert isinstance(fi, FFmpegInput)
    assert fi.lavfi is not None
    assert fi.lavfi.startswith("mandelbrot=size=1920x1080:rate=24:start_scale=")
    assert ("-t", "2.0") in tuple(_pairs(fi.extra_flags))


def test_mandelbrot_seed_changes_start_scale():
    fi_a = recipe_mandelbrot(width=640, height=480, fps=24, duration_s=1.0, seed=1)
    fi_b = recipe_mandelbrot(width=640, height=480, fps=24, duration_s=1.0, seed=2)
    assert fi_a.lavfi != fi_b.lavfi


def test_color_bars_emits_smptebars():
    """WHY: color_bars uses smptebars, NOT testsrc — voom-v2 distinguishes
    these visually and the choice is locked at the contract level."""
    fi = recipe_color_bars(width=1280, height=720, fps=24, duration_s=1.5, seed=1)
    assert fi.lavfi == "smptebars=size=1280x720:rate=24"
    assert ("-t", "1.5") in tuple(_pairs(fi.extra_flags))


def test_solid_color_hex_derives_from_seed():
    """WHY: deterministic seeded color choice is the only Sprint 5 visual
    knob for solid_color; same seed must yield same hex."""
    fi_a = recipe_solid_color(width=640, height=480, fps=24, duration_s=1.0, seed=7)
    fi_b = recipe_solid_color(width=640, height=480, fps=24, duration_s=1.0, seed=7)
    assert fi_a.lavfi == fi_b.lavfi
    assert "color=c=#" in fi_a.lavfi
    fi_c = recipe_solid_color(width=640, height=480, fps=24, duration_s=1.0, seed=8)
    assert fi_a.lavfi != fi_c.lavfi


def _pairs(flags: tuple[str, ...]) -> list[tuple[str, str]]:
    return list(zip(flags[::2], flags[1::2], strict=True))


@pytest.mark.parametrize(
    "recipe",
    [recipe_mandelbrot, recipe_color_bars, recipe_solid_color],
)
def test_every_video_recipe_carries_duration_flag(recipe: object) -> None:
    """WHY: ffmpeg lavfi sources are infinite without -t; if a recipe
    forgets to add it, materialize produces an infinite stream and times
    out. Locked at the recipe level."""
    fi = recipe(width=640, height=480, fps=24, duration_s=3.0, seed=1)  # type: ignore[operator]
    assert "-t" in fi.extra_flags
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/materializer/test_recipes.py -v`
Expected: ImportError — module does not exist.

- [ ] **Step 3: Create the recipes module**

Create `src/chaos_librarian/materializer/recipes.py`:

```python
"""Seed-driven content recipes — pure ffmpeg lavfi expressions.

Every recipe is a pure function over (dimensions, fps, duration, seed).
The orchestrator calls each recipe once per asset and hands the result
to ``ffmpeg.build_command``.

No subprocess work happens here.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class FFmpegInput:
    """One ffmpeg input + the extra flags that go with it.

    Exactly one of ``lavfi`` / ``file_path`` is set; the SRT-sidecar case
    uses ``file_path`` (read from a separately-written file).
    """

    lavfi: str | None = None
    file_path: Path | None = None
    extra_flags: tuple[str, ...] = ()


def _scale_from_seed(seed: int) -> float:
    """Deterministic 0.0-1.0 mapping for mandelbrot start_scale.

    The mapping is intentionally simple — bit-exactness requires only that
    the mapping be a pure function of ``seed``.
    """
    # uses 4 decimal places to keep the resulting lavfi string short and stable
    return round((abs(seed) % 1000) / 1000.0 + 1.5, 4)


def _hex_from_seed(seed: int) -> str:
    """Deterministic six-char hex color for solid_color."""
    return f"{abs(seed) % 0xFFFFFF:06x}"


def recipe_mandelbrot(
    *, width: int, height: int, fps: int, duration_s: float, seed: int
) -> FFmpegInput:
    """Mandelbrot zoom — visually rich, deterministic from seed."""
    start_scale = _scale_from_seed(seed)
    return FFmpegInput(
        lavfi=f"mandelbrot=size={width}x{height}:rate={fps}:start_scale={start_scale}",
        extra_flags=("-t", str(duration_s)),
    )


def recipe_color_bars(
    *, width: int, height: int, fps: int, duration_s: float, seed: int
) -> FFmpegInput:
    """SMPTE bars — visually distinctive, seed is ignored (deterministic)."""
    del seed  # bars are fully determined by dimensions + fps
    return FFmpegInput(
        lavfi=f"smptebars=size={width}x{height}:rate={fps}",
        extra_flags=("-t", str(duration_s)),
    )


def recipe_solid_color(
    *, width: int, height: int, fps: int, duration_s: float, seed: int
) -> FFmpegInput:
    """A single seeded color filling the frame."""
    hex_color = _hex_from_seed(seed)
    return FFmpegInput(
        lavfi=f"color=c=#{hex_color}:s={width}x{height}:r={fps}",
        extra_flags=("-t", str(duration_s)),
    )
```

- [ ] **Step 4: Run focused tests — pass**

Run: `uv run pytest tests/materializer/test_recipes.py -v`
Expected: all green.

- [ ] **Step 5: Lint/type focused**

Run: `uv run ruff check src/chaos_librarian/materializer/recipes.py tests/materializer/test_recipes.py && uv run ty check src/chaos_librarian/materializer/recipes.py`
Expected: clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/materializer/recipes.py \
        tests/materializer/test_recipes.py
git commit -m "$(cat <<'EOF'
feat(materializer): add video content recipes

Three pure functions over (width, height, fps, duration_s, seed)
returning FFmpegInput with a lavfi expression and a -t duration flag.
mandelbrot derives start_scale from seed; solid_color derives hex from
seed; color_bars is fully deterministic.

Audio and SRT recipes land in follow-up tasks to keep diffs small.

Refs sprint 5 design doc §Content Sources And Recipes.
EOF
)"
```

---

## Task 13: Content recipes — audio sources

**Files:**

- Modify: `src/chaos_librarian/materializer/recipes.py` — append `recipe_sine`, `recipe_silence`, `recipe_channel_tones`.
- Modify: `tests/materializer/test_recipes.py` — extend with audio coverage.

- [ ] **Step 1: Write failing tests**

Append to `tests/materializer/test_recipes.py`:

```python
from chaos_librarian.materializer.recipes import (
    recipe_channel_tones,
    recipe_silence,
    recipe_sine,
)


def test_sine_frequency_derives_from_seed():
    fi = recipe_sine(channels="mono", duration_s=2.0, seed=440)
    assert fi.lavfi is not None
    assert fi.lavfi.startswith("sine=frequency=")
    assert ":sample_rate=48000" in fi.lavfi
    assert ":duration=2.0" in fi.lavfi


def test_silence_uses_channel_layout():
    fi = recipe_silence(channels="5.1", duration_s=1.0, seed=0)
    assert fi.lavfi == "anullsrc=channel_layout=5.1:sample_rate=48000"
    assert ("-t", "1.0") in tuple(_pairs(fi.extra_flags))


def test_channel_tones_emits_one_frequency_per_channel():
    """WHY: channel_tones is the materializer's debugging signal — each
    channel carries a distinct frequency so a downstream listener can tell
    them apart. Stereo must produce exactly two frequencies."""
    fi = recipe_channel_tones(channels="stereo", duration_s=1.0, seed=1)
    assert fi.lavfi is not None
    # Stereo => 2 sine sources merged with amerge or join
    assert fi.lavfi.count("sine=frequency=") == 2


def test_channel_tones_5_1_emits_six_frequencies():
    fi = recipe_channel_tones(channels="5.1", duration_s=1.0, seed=1)
    assert fi.lavfi.count("sine=frequency=") == 6
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/materializer/test_recipes.py::test_sine_frequency_derives_from_seed tests/materializer/test_recipes.py::test_silence_uses_channel_layout tests/materializer/test_recipes.py::test_channel_tones_emits_one_frequency_per_channel tests/materializer/test_recipes.py::test_channel_tones_5_1_emits_six_frequencies -v`
Expected: ImportError on the three new symbols.

- [ ] **Step 3: Add the audio recipes**

Append to `src/chaos_librarian/materializer/recipes.py`:

```python
_CHANNEL_COUNTS = {"mono": 1, "stereo": 2, "5.1": 6}
# Distinct base frequencies — pattern: doubles per channel.
_CHANNEL_TONE_BASE = (220, 440, 880, 1760, 3520, 7040)


def _frequency_from_seed(seed: int) -> int:
    """Map seed to a sine frequency in the 100-1000 Hz human-audible band."""
    return 100 + (abs(seed) % 901)


def recipe_sine(*, channels: str, duration_s: float, seed: int) -> FFmpegInput:
    """A single sine tone — frequency derived from seed; channel layout
    set via the lavfi source so the muxer sees the right channel count."""
    del channels  # sine is mono-by-construction; ffmpeg upmixes via the muxer
    freq = _frequency_from_seed(seed)
    return FFmpegInput(
        lavfi=f"sine=frequency={freq}:duration={duration_s}:sample_rate=48000",
        extra_flags=(),
    )


def recipe_silence(*, channels: str, duration_s: float, seed: int) -> FFmpegInput:
    """anullsrc — zero-amplitude audio at the requested channel layout."""
    del seed  # silence is fully determined by channels + duration
    return FFmpegInput(
        lavfi=f"anullsrc=channel_layout={channels}:sample_rate=48000",
        extra_flags=("-t", str(duration_s)),
    )


def recipe_channel_tones(*, channels: str, duration_s: float, seed: int) -> FFmpegInput:
    """One distinct sine frequency per channel — debugging signal.

    Frequencies start from the seed-derived base and double per channel.
    """
    count = _CHANNEL_COUNTS[channels]
    base_index = abs(seed) % len(_CHANNEL_TONE_BASE)
    sources = []
    for offset in range(count):
        freq = _CHANNEL_TONE_BASE[(base_index + offset) % len(_CHANNEL_TONE_BASE)]
        sources.append(f"sine=frequency={freq}:duration={duration_s}:sample_rate=48000")
    if count == 1:
        lavfi = sources[0]
    else:
        # amerge requires inputs= count; build the amerge filter graph inline
        sep = "|".join(sources)
        lavfi = f"{sep}|amerge=inputs={count}"
    return FFmpegInput(lavfi=lavfi, extra_flags=())
```

- [ ] **Step 4: Run focused tests — pass**

Run: `uv run pytest tests/materializer/test_recipes.py -v`
Expected: all green. If the amerge filter-graph syntax for `channel_tones` produces extra `sine=frequency=` substrings (e.g. due to filter labels), adjust the assertion in `test_channel_tones_*` to count via a regex anchored on the literal token, not bare `count`.

- [ ] **Step 5: Lint/type/full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/materializer/recipes.py \
        tests/materializer/test_recipes.py
git commit -m "$(cat <<'EOF'
feat(materializer): add audio content recipes

Three pure functions: sine (single tone, seed -> frequency), silence
(anullsrc), channel_tones (one distinct frequency per channel, doubling
pattern). Channel counts are read off the scenario's channel-layout
string (mono/stereo/5.1).

Refs sprint 5 design doc §Content Sources And Recipes.
EOF
)"
```

---

## Task 14: Content recipes — SRT payload

**Files:**

- Modify: `src/chaos_librarian/materializer/recipes.py` — append `srt_payload(language, duration_s, seed) -> str`.
- Modify: `tests/materializer/test_recipes.py` — bytes-stable assertion.

The SRT subtitle case is different from the lavfi sources: the orchestrator writes the returned bytes to a sidecar file. ffmpeg never sees the .srt directly in Sprint 5 (sidecar mode).

- [ ] **Step 1: Write failing test**

Append to `tests/materializer/test_recipes.py`:

```python
from chaos_librarian.materializer.recipes import srt_payload


def test_srt_payload_is_deterministic_for_seed():
    """WHY: SRT bytes must be bit-stable across runs for the manifest
    sidecar content_hash to compare equal. Inline the expected value so a
    future format change is caught."""
    body = srt_payload(language="eng", duration_s=2.0, seed=42)
    expected = (
        "1\n"
        "00:00:00,000 --> 00:00:02,000\n"
        "chaos-librarian fixture subtitle (lang=eng, seed=42)\n"
        "\n"
    )
    assert body == expected


def test_srt_payload_seed_changes_body():
    a = srt_payload(language="eng", duration_s=1.0, seed=1)
    b = srt_payload(language="eng", duration_s=1.0, seed=2)
    assert a != b


def test_srt_payload_duration_formats_to_3dp_milliseconds():
    """WHY: SRT timestamps are HH:MM:SS,mmm — a fractional duration must
    serialize without floating-point noise."""
    body = srt_payload(language="eng", duration_s=2.5, seed=1)
    assert "00:00:02,500" in body
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/materializer/test_recipes.py -v -k srt`
Expected: ImportError on `srt_payload`.

- [ ] **Step 3: Add the helper**

Append to `src/chaos_librarian/materializer/recipes.py`:

```python
def _srt_timestamp(seconds: float) -> str:
    """Format ``HH:MM:SS,mmm`` from a float of seconds."""
    total_ms = round(seconds * 1000)
    hh, rem = divmod(total_ms, 3_600_000)
    mm, rem = divmod(rem, 60_000)
    ss, ms = divmod(rem, 1000)
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def srt_payload(*, language: str, duration_s: float, seed: int) -> str:
    """Return SRT body for one subtitle cue spanning [0, duration_s).

    Single-cue, single-line body that includes the seed so adapters can
    distinguish fixtures at a glance. Trailing blank line required by SRT.
    """
    return (
        "1\n"
        f"00:00:00,000 --> {_srt_timestamp(duration_s)}\n"
        f"chaos-librarian fixture subtitle (lang={language}, seed={seed})\n"
        "\n"
    )
```

- [ ] **Step 4: Run focused tests — pass**

Run: `uv run pytest tests/materializer/test_recipes.py -v`
Expected: all green.

- [ ] **Step 5: Lint/type/full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/materializer/recipes.py \
        tests/materializer/test_recipes.py
git commit -m "$(cat <<'EOF'
feat(materializer): add srt_payload helper for sidecar subtitle bytes

Deterministic single-cue SRT body. Orchestrator writes the bytes to
library/<path>.srt as a sidecar file; ffmpeg never sees the SRT directly
in Sprint 5 (sidecar mode). Bytes are seed-stable so the sidecar
content_hash compares equal across runs of the same scenario+seed.

Refs sprint 5 design doc §Content Sources And Recipes.
EOF
)"
```

---

## Task 15: FFmpeg command builder

**Files:**

- Create: `src/chaos_librarian/materializer/ffmpeg.py` — `BITEXACT_FLAGS`, `build_command`, `run_ffmpeg`.
- Create: `tests/materializer/test_ffmpeg_builder.py` — Layer 2 matrix coverage (18 supported cells + unsupported-combo rejections).

`build_command` is pure (returns argv); `run_ffmpeg` is the subprocess wrapper that captures stderr_tail and times execution. Bit-exact flags are mandatory on every invocation.

- [ ] **Step 1: Write failing tests**

Create `tests/materializer/test_ffmpeg_builder.py`:

```python
"""Layer 2 — FFmpeg command builder matrix coverage."""

from __future__ import annotations

from pathlib import Path

import pytest

from chaos_librarian.contract.scenario import (
    AudioSource,
    AudioTrack,
    SubtitleSource,
    SubtitleTrack,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.ffmpeg import (
    BITEXACT_FLAGS,
    build_command,
)
from chaos_librarian.materializer.recipes import (
    recipe_color_bars,
    recipe_sine,
)


def _video(resolution: str = "hd") -> VideoTrack:
    return VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution=resolution)


def _audio(channels: str = "stereo") -> AudioTrack:
    return AudioTrack(
        source=AudioSource.SINE, codec="aac", channels=channels, language="eng"
    )


@pytest.mark.parametrize("container", ["mkv", "mp4"])
@pytest.mark.parametrize("resolution", ["sd", "hd", "1080p"])
@pytest.mark.parametrize("channels", ["mono", "stereo", "5.1"])
def test_matrix_cell_produces_argv_with_bitexact_flags(
    container: str, resolution: str, channels: str, tmp_path: Path
) -> None:
    """WHY: 2 containers × 3 resolutions × 3 channel layouts = 18 cells that
    must all produce a stable argv. BITEXACT_FLAGS must appear in every cell
    so cross-run determinism holds."""
    video = _video(resolution=resolution)
    audio = _audio(channels=channels)
    output = tmp_path / f"asset.{container}"
    video_input = recipe_color_bars(
        width=640, height=480, fps=24, duration_s=2.0, seed=1
    )
    audio_input = recipe_sine(channels=channels, duration_s=2.0, seed=1)
    argv = build_command(
        video=video,
        video_input=video_input,
        audios=[audio],
        audio_inputs=[audio_input],
        output_path=output,
    )
    assert argv[0] == "ffmpeg"
    for flag in BITEXACT_FLAGS:
        assert flag in argv
    assert str(output) in argv


def test_unsupported_audio_codec_rejected(tmp_path: Path) -> None:
    """WHY: Sprint 5 supports only aac; opus must raise before any subprocess
    starts so the orchestrator can record E_MATERIALIZE_UNSUPPORTED with
    field='audio[0].codec'."""
    video = _video()
    audio = AudioTrack(source=AudioSource.SINE, codec="opus", channels="stereo", language="eng")
    output = tmp_path / "asset.mkv"
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=video,
            video_input=recipe_color_bars(
                width=640, height=480, fps=24, duration_s=1.0, seed=1
            ),
            audios=[audio],
            audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
            output_path=output,
        )
    assert exc.value.field == "audio[0].codec"
    assert exc.value.payload["supported"] == ["aac"]


def test_unsupported_container_rejected(tmp_path: Path) -> None:
    video = _video()
    output = tmp_path / "asset.webm"
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=video,
            video_input=recipe_color_bars(
                width=640, height=480, fps=24, duration_s=1.0, seed=1
            ),
            audios=[_audio()],
            audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
            output_path=output,
        )
    assert exc.value.field == "container"


def test_unsupported_resolution_rejected(tmp_path: Path) -> None:
    video = VideoTrack(source=VideoSource.COLOR_BARS, codec="h264", resolution="4k")
    output = tmp_path / "asset.mkv"
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=video,
            video_input=recipe_color_bars(
                width=3840, height=2160, fps=24, duration_s=1.0, seed=1
            ),
            audios=[_audio()],
            audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
            output_path=output,
        )
    assert exc.value.field == "video.resolution"


def test_unsupported_video_source_rejected(tmp_path: Path) -> None:
    """WHY: noise is a valid scenario source (slow-copy.yaml uses it) but
    Sprint 5's materializer rejects it; the check belongs in the builder
    because that's where source-to-recipe dispatch lives."""
    video = VideoTrack(source=VideoSource.NOISE, codec="h264", resolution="hd")
    output = tmp_path / "asset.mkv"
    with pytest.raises(UnsupportedMaterializationError) as exc:
        build_command(
            video=video,
            video_input=recipe_color_bars(
                width=1280, height=720, fps=24, duration_s=1.0, seed=1
            ),
            audios=[_audio()],
            audio_inputs=[recipe_sine(channels="stereo", duration_s=1.0, seed=1)],
            output_path=output,
        )
    assert exc.value.field == "video.source"
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/materializer/test_ffmpeg_builder.py -v`
Expected: ImportError — module does not exist.

- [ ] **Step 3: Create the builder module**

Create `src/chaos_librarian/materializer/ffmpeg.py`:

```python
"""FFmpeg argv builder and subprocess wrapper.

``build_command`` is pure — given a video track, an audio list, and the
output path, returns the argv tuple. Unsupported combinations raise
``UnsupportedMaterializationError`` with the exact scenario field name.

``run_ffmpeg`` is the subprocess wrapper. Captures stderr_tail and times
execution. Never lets ffmpeg inherit stdin.
"""

from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Final

from chaos_librarian.contract.materialization import ToolInvocation
from chaos_librarian.contract.scenario import (
    AudioSource,
    AudioTrack,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.materializer.errors import UnsupportedMaterializationError
from chaos_librarian.materializer.recipes import FFmpegInput

BITEXACT_FLAGS: Final[tuple[str, ...]] = (
    "-fflags", "+bitexact",
    "-flags", "+bitexact",
    "-map_metadata", "-1",
    "-metadata", "creation_time=1970-01-01T00:00:00Z",
)

_SUPPORTED_CONTAINERS: Final = frozenset({"mkv", "mp4"})
_SUPPORTED_RESOLUTIONS: Final = frozenset({"sd", "hd", "1080p"})
_SUPPORTED_VIDEO_CODECS: Final = frozenset({"h264"})
_SUPPORTED_AUDIO_CODECS: Final = frozenset({"aac"})
_SUPPORTED_VIDEO_SOURCES: Final = frozenset(
    {VideoSource.MANDELBROT, VideoSource.COLOR_BARS, VideoSource.SOLID_COLOR}
)
_SUPPORTED_AUDIO_SOURCES: Final = frozenset(
    {AudioSource.SINE, AudioSource.SILENCE, AudioSource.CHANNEL_TONES}
)

_CONTAINER_FROM_EXTENSION: Final = {".mkv": "mkv", ".mp4": "mp4"}


def _require(value: object, supported: frozenset[object], field: str) -> None:
    if value not in supported:
        raise UnsupportedMaterializationError(
            f"{field}={value!r} is not supported in Sprint 5",
            field=field,
            payload={"supported": sorted(str(v) for v in supported)},
        )


def build_command(
    *,
    video: VideoTrack,
    video_input: FFmpegInput,
    audios: list[AudioTrack],
    audio_inputs: list[FFmpegInput],
    output_path: Path,
) -> list[str]:
    """Build the ffmpeg argv for one asset.

    The caller has already turned the scenario's source enums into
    FFmpegInput recipes; this function focuses on muxing + codec wiring.
    """
    container = _CONTAINER_FROM_EXTENSION.get(output_path.suffix)
    if container is None:
        raise UnsupportedMaterializationError(
            f"unknown container extension: {output_path.suffix!r}",
            field="container",
            payload={"supported": sorted(_SUPPORTED_CONTAINERS)},
        )
    _require(container, _SUPPORTED_CONTAINERS, "container")
    _require(video.source, _SUPPORTED_VIDEO_SOURCES, "video.source")
    _require(video.codec, _SUPPORTED_VIDEO_CODECS, "video.codec")
    _require(video.resolution, _SUPPORTED_RESOLUTIONS, "video.resolution")
    for index, audio in enumerate(audios):
        _require(audio.source, _SUPPORTED_AUDIO_SOURCES, f"audio[{index}].source")
        _require(audio.codec, _SUPPORTED_AUDIO_CODECS, f"audio[{index}].codec")
    if video_input.lavfi is None:
        raise UnsupportedMaterializationError(
            "video FFmpegInput must carry a lavfi expression",
            field="video.source",
            payload={},
        )
    argv: list[str] = ["ffmpeg", "-hide_banner", "-y", *BITEXACT_FLAGS]
    argv.extend(["-f", "lavfi", "-i", video_input.lavfi])
    argv.extend(video_input.extra_flags)
    for audio_input in audio_inputs:
        if audio_input.lavfi is None:
            raise UnsupportedMaterializationError(
                "audio FFmpegInput must carry a lavfi expression",
                field="audio.source",
                payload={},
            )
        argv.extend(["-f", "lavfi", "-i", audio_input.lavfi])
        argv.extend(audio_input.extra_flags)
    argv.extend(["-c:v", "libx264", "-preset", "medium"])
    argv.extend(["-c:a", "aac"])
    argv.append("-shortest")
    argv.append(str(output_path))
    return argv


def run_ffmpeg(
    argv: list[str],
    *,
    ffmpeg_version: str,
    timeout_s: float = 60.0,
) -> ToolInvocation:
    """Invoke ffmpeg. Returns a ToolInvocation regardless of exit code.

    Stderr tail (last 2 KB, UTF-8 lossy) is recorded on the invocation's
    command list as the final element prefixed with ``__stderr_tail__``
    so callers can extract it without a second subprocess round-trip.
    """
    start = time.monotonic_ns()
    completed = subprocess.run(  # noqa: S603 — argv comes from internal builder
        argv,
        capture_output=True,
        timeout=timeout_s,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    duration_ns = time.monotonic_ns() - start
    stderr_bytes = completed.stderr or b""
    stderr_tail = stderr_bytes[-2048:].decode("utf-8", errors="replace")
    command = [*argv, f"__stderr_tail__{stderr_tail}"]
    return ToolInvocation(
        tool="ffmpeg",
        version=ffmpeg_version,
        command=command,
        exit_code=completed.returncode,
        duration_ns=duration_ns,
    )
```

- [ ] **Step 4: Run focused tests — pass**

Run: `uv run pytest tests/materializer/test_ffmpeg_builder.py -v`
Expected: all 18 parametrized matrix cases pass; all four unsupported-combination assertions pass.

- [ ] **Step 5: Lint/type/full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/materializer/ffmpeg.py \
        tests/materializer/test_ffmpeg_builder.py
git commit -m "$(cat <<'EOF'
feat(materializer): add ffmpeg command builder + subprocess wrapper

build_command is pure — given a video track + audios + output path,
returns argv with BITEXACT_FLAGS on every cell of the Sprint 5 matrix
(2 containers × 1 video codec × 3 resolutions × 1 audio codec × 3
channel layouts = 18 supported cells). Out-of-matrix combinations raise
UnsupportedMaterializationError with the exact scenario field name.

run_ffmpeg captures stderr_tail (last 2 KB UTF-8 lossy) on the
ToolInvocation so the orchestrator never spawns a second subprocess to
recover it. Stdin is set to DEVNULL.

Refs sprint 5 design doc §FFmpeg Command Builder.
EOF
)"
```

---

## Task 16: ffprobe wrapper

**Files:**

- Create: `src/chaos_librarian/materializer/probe.py` — `probe_file(path) -> ProbedMedia`.
- Create: `tests/materializer/test_probe.py` — Layer 2 unit coverage with subprocess mocked.

Invokes `ffprobe -show_format -show_streams -of json` and maps the JSON into `ProbedMedia`. Unparseable output raises `ProbeParseError` (caller surfaces it as `E_MATERIALIZE_PROBE_PARSE_FAILED`).

- [ ] **Step 1: Write failing tests**

Create `tests/materializer/test_probe.py`:

```python
"""Layer 2 — ffprobe wrapper with subprocess mocked."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from chaos_librarian.materializer import probe as probe_mod
from chaos_librarian.materializer.errors import ProbeParseError
from chaos_librarian.materializer.probe import probe_file

_GOOD_PROBE = json.dumps(
    {
        "format": {
            "format_name": "matroska,webm",
            "duration": "2.000000",
            "size": "12345",
        },
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 640,
                "height": 480,
                "r_frame_rate": "24/1",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "sample_rate": "48000",
                "tags": {"language": "eng"},
            },
        ],
    }
)


def _patch_run(monkeypatch: pytest.MonkeyPatch, stdout: str, returncode: int = 0) -> None:
    def stub(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=["ffprobe"], returncode=returncode, stdout=stdout, stderr=""
        )

    monkeypatch.setattr(probe_mod.subprocess, "run", stub)


def test_probe_file_parses_video_and_audio_streams(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: ffprobe-to-ProbedMedia is the only place these fields move
    from JSON strings into typed model attributes; if the mapping breaks,
    the manifest gets garbage values and the Layer 4 smoke test fails
    much later. Catch it here."""
    _patch_run(monkeypatch, _GOOD_PROBE)
    media = probe_file(tmp_path / "fake.mkv")
    assert media.container == "matroska,webm"
    assert media.duration_seconds == 2.0
    assert media.size_bytes == 12345
    video = next(s for s in media.streams if s.kind == "video")
    assert video.codec == "h264"
    assert video.width == 640 and video.height == 480
    assert video.fps == 24.0
    audio = next(s for s in media.streams if s.kind == "audio")
    assert audio.channels == 2
    assert audio.sample_rate == 48000
    assert audio.language == "eng"


def test_probe_file_raises_on_non_zero_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_run(monkeypatch, stdout="", returncode=1)
    with pytest.raises(ProbeParseError):
        probe_file(tmp_path / "broken.mkv")


def test_probe_file_raises_on_unparseable_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _patch_run(monkeypatch, stdout="not json")
    with pytest.raises(ProbeParseError):
        probe_file(tmp_path / "broken.mkv")


def test_probe_file_ignores_subtitle_streams(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Sprint 5 explicitly does NOT add subtitle streams to
    asset.probed.streams[] — sidecar SRTs are separate files and
    embedded subtitles arrive in Sprint 7. If a future ffprobe reports
    one in a Sprint 5 fixture, we drop it silently here."""
    probe = json.loads(_GOOD_PROBE)
    probe["streams"].append({"codec_type": "subtitle", "codec_name": "srt"})
    _patch_run(monkeypatch, json.dumps(probe))
    media = probe_file(tmp_path / "fake.mkv")
    assert all(s.kind != "subtitle" for s in media.streams)
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/materializer/test_probe.py -v`
Expected: ImportError — module does not exist.

- [ ] **Step 3: Create the probe module**

Create `src/chaos_librarian/materializer/probe.py`:

```python
"""ffprobe wrapper.

Runs ``ffprobe -show_format -show_streams -of json`` and maps the result
into ``ProbedMedia``. Unparseable output raises ``ProbeParseError``.
Sprint 5 deliberately drops subtitle streams (sidecars are separate
files; embedded subtitles arrive in Sprint 7).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream
from chaos_librarian.materializer.errors import ProbeParseError

_PROBE_TIMEOUT_S = 15.0


def _fps_from_rate(rate: str | None) -> float | None:
    if rate is None:
        return None
    if "/" in rate:
        num, den = rate.split("/", 1)
        try:
            return float(num) / float(den) if float(den) else None
        except (ValueError, ZeroDivisionError):
            return None
    try:
        return float(rate)
    except ValueError:
        return None


def _stream_from_json(blob: dict[str, object]) -> ProbedStream | None:
    codec_type = blob.get("codec_type")
    codec = str(blob.get("codec_name") or "")
    if codec_type == "video":
        return ProbedStream(
            kind="video",
            codec=codec,
            width=int(blob["width"]) if "width" in blob else None,
            height=int(blob["height"]) if "height" in blob else None,
            fps=_fps_from_rate(str(blob.get("r_frame_rate"))) if "r_frame_rate" in blob else None,
            language=_language_tag(blob),
        )
    if codec_type == "audio":
        return ProbedStream(
            kind="audio",
            codec=codec,
            channels=int(blob["channels"]) if "channels" in blob else None,
            sample_rate=int(blob["sample_rate"]) if "sample_rate" in blob else None,
            language=_language_tag(blob),
        )
    # subtitle streams are dropped — see module docstring.
    return None


def _language_tag(blob: dict[str, object]) -> str | None:
    tags = blob.get("tags") if isinstance(blob.get("tags"), dict) else None
    if tags is None:
        return None
    raw = tags.get("language")
    return str(raw) if raw is not None else None


def probe_file(path: Path) -> ProbedMedia:
    """Run ffprobe and return the parsed ProbedMedia."""
    argv = [
        "ffprobe",
        "-hide_banner",
        "-v", "error",
        "-show_format",
        "-show_streams",
        "-of", "json",
        str(path),
    ]
    try:
        completed = subprocess.run(  # noqa: S603 — argv is internal
            argv,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_S,
            check=False,
            stdin=subprocess.DEVNULL,
        )
    except subprocess.TimeoutExpired as exc:
        raise ProbeParseError(
            f"ffprobe timeout on {path}",
            payload={"path": str(path), "timeout_s": _PROBE_TIMEOUT_S},
        ) from exc
    if completed.returncode != 0:
        raise ProbeParseError(
            f"ffprobe exit {completed.returncode} on {path}",
            payload={"path": str(path), "stderr": (completed.stderr or "")[-2048:]},
        )
    try:
        blob = json.loads(completed.stdout or "")
    except json.JSONDecodeError as exc:
        raise ProbeParseError(
            f"ffprobe stdout was not valid JSON for {path}",
            payload={"path": str(path), "stdout_head": (completed.stdout or "")[:512]},
        ) from exc
    fmt = blob.get("format") or {}
    streams_raw = blob.get("streams") or []
    parsed_streams: list[ProbedStream] = []
    for entry in streams_raw:
        if not isinstance(entry, dict):
            continue
        stream = _stream_from_json(entry)
        if stream is not None:
            parsed_streams.append(stream)
    try:
        return ProbedMedia(
            container=str(fmt.get("format_name") or ""),
            duration_seconds=float(fmt.get("duration", 0.0)),
            size_bytes=int(fmt.get("size", 0)),
            streams=parsed_streams,
        )
    except (ValueError, TypeError) as exc:
        raise ProbeParseError(
            f"failed to map ffprobe JSON into ProbedMedia for {path}",
            payload={"path": str(path)},
        ) from exc
```

- [ ] **Step 4: Run focused tests — pass**

Run: `uv run pytest tests/materializer/test_probe.py -v`
Expected: all green.

- [ ] **Step 5: Lint/type/full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/materializer/probe.py \
        tests/materializer/test_probe.py
git commit -m "$(cat <<'EOF'
feat(materializer): add ffprobe wrapper producing ProbedMedia

probe_file shells out to ffprobe -show_format -show_streams -of json,
maps the result into ProbedMedia, drops subtitle streams (Sprint 5
contract — sidecars are separate files, embedded subtitles in Sprint 7),
and raises ProbeParseError on non-zero exit, JSON decode failure, or
field-mapping failure.

Refs sprint 5 design doc §Manifest Augmentation.
EOF
)"
```

---

## Task 17: Materializer writer — atomic begin/finalize/cleanup

**Files:**

- Create: `src/chaos_librarian/materializer/writer.py` — `begin_materialize_run`, `finalize_materialize_run`, `cleanup_failed_run`, atomic-write primitive.
- Create: `tests/materializer/test_writer.py` — sentinel flip + atomic-rename sanity.

The materializer writer can't use plan-only's staging-rename pattern because `library/` is written into the final location during synthesis. This task ships file-by-file atomic writes plus the sentinel flip.

- [ ] **Step 1: Write failing tests**

Create `tests/materializer/test_writer.py`:

```python
"""Layer 3 — materializer writer atomicity + sentinel flip."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

from chaos_librarian.contract import RUN_SENTINEL_SCHEMA_VERSION
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.materializer.writer import (
    SENTINEL_FILENAME,
    begin_materialize_run,
)


def _sentinel(state: str) -> RunSentinel:
    return RunSentinel(
        run_id=uuid.uuid4(),
        schema_version=RUN_SENTINEL_SCHEMA_VERSION,
        created_by="chaos-librarian-test",
        created_at=datetime(2026, 5, 18, 0, 0, 0, tzinfo=UTC),
        state=state,
    )


def test_begin_creates_run_dir_with_in_progress_sentinel(tmp_path: Path) -> None:
    """WHY: the in_progress sentinel is the marker that future tooling
    uses to detect interrupted materialize runs (Finding 2). It must be
    on disk before any ffmpeg subprocess starts."""
    out_dir = tmp_path / "run"
    sentinel = _sentinel("in_progress")
    begin_materialize_run(out_dir, sentinel)
    assert out_dir.exists()
    assert (out_dir / "library").is_dir()
    sentinel_path = out_dir / SENTINEL_FILENAME
    assert sentinel_path.exists()
    payload = json.loads(sentinel_path.read_text())
    assert payload["state"] == "in_progress"


def test_begin_refuses_existing_out_dir(tmp_path: Path) -> None:
    out_dir = tmp_path / "run"
    out_dir.mkdir()
    sentinel = _sentinel("in_progress")
    try:
        begin_materialize_run(out_dir, sentinel)
    except FileExistsError:
        return
    raise AssertionError("begin_materialize_run should refuse existing dirs")


def test_cleanup_failed_run_writes_full_metadata(tmp_path: Path) -> None:
    """WHY: Finding 4 — ``clean`` requires ``replay.json`` and ``inspect``
    requires both ``replay.json`` and ``manifest.current.json``. A failure
    run-dir missing those files crashes the tooling. ``cleanup_failed_run``
    must emit every metadata file ``finalize_materialize_run`` does so the
    two run-dir shapes are uniform for downstream consumers."""
    import uuid as uuid_mod
    from datetime import UTC, datetime
    from chaos_librarian.contract import (
        MATERIALIZATION_SCHEMA_VERSION,
        REPLAY_BUNDLE_SCHEMA_VERSION,
    )
    from chaos_librarian.contract.manifest import Manifest
    from chaos_librarian.contract.materialization import (
        MaterializationReport,
        Outcome,
        ToolchainInfo,
    )
    from chaos_librarian.contract.replay_bundle import (
        ExecutionMode,
        MaterializeReplayBundle,
    )
    from chaos_librarian.contract.validation import ValidationReport
    from chaos_librarian.materializer.writer import (
        begin_materialize_run,
        cleanup_failed_run,
    )

    out_dir = tmp_path / "failed_run"
    in_progress = _sentinel("in_progress")
    begin_materialize_run(out_dir, in_progress)
    # Drop a synthetic byte under library/ so the wipe is observable.
    (out_dir / "library" / "stale.bin").write_bytes(b"x")

    run_id = uuid_mod.uuid4()
    manifest = Manifest(
        schema_version=2, works=[], variants=[], bundles=[], assets=[],
        versions=[], locations=[], sidecars=[],
    )
    validation_report = ValidationReport(
        schema_version=1, ok=True, scenario_id="static", issues=[],
    )
    materialization_report = MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION, run_id=run_id,
        outcome=Outcome.TOOL_FAILED, platform="test",
        started_at=datetime(2026, 5, 18, 0, 0, 0, tzinfo=UTC),
        finished_at=datetime(2026, 5, 18, 0, 0, 1, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
        invocations=[], materialized=[], failures=[],
    )
    replay_bundle = MaterializeReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.1.0",
        scenario="schema_version: 2\nscenario_id: static\n",
        run_id=run_id, resolved_seed=1, journal_digest="0" * 64,
        execution_mode=ExecutionMode.MATERIALIZE,
        created_at=datetime(2026, 5, 18, 0, 0, 1, tzinfo=UTC),
        toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
    )
    cleanup_failed_run(
        out_dir,
        initial_manifest=manifest,
        current_manifest=manifest,
        journal_lines=[],
        validation_report=validation_report,
        materialization_report=materialization_report,
        replay_bundle=replay_bundle,
        scenario_yaml_bytes=b"schema_version: 2\nscenario_id: static\n",
        sentinel=_sentinel("complete"),
    )
    # library/ wiped to empty, sentinel flipped.
    assert list((out_dir / "library").iterdir()) == []
    sentinel_payload = json.loads((out_dir / SENTINEL_FILENAME).read_text())
    assert sentinel_payload["state"] == "complete"
    # Every metadata file inspect/clean read exists.
    for name in (
        "scenario.yaml",
        "manifest.initial.json",
        "manifest.current.json",
        "journal.jsonl",
        "validation.json",
        "materialization.json",
        "replay.json",
    ):
        assert (out_dir / name).exists(), name
```

(Tests for `finalize_materialize_run` live in the orchestrator test file Task 18 since it's best exercised via the full pipeline.)

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/materializer/test_writer.py -v`
Expected: ImportError — module does not exist.

- [ ] **Step 3: Create the writer module**

Create `src/chaos_librarian/materializer/writer.py`:

```python
"""Materialize-mode atomic write helpers.

Unlike ``engine.writer`` (plan-only, single staging-rename), materialize
writes the library tree in-place during synthesis. This module brackets
that: ``begin_materialize_run`` creates the run-dir and writes an
in-progress sentinel; ``finalize_materialize_run`` writes the rest of
the metadata atomically and flips the sentinel to ``complete``;
``cleanup_failed_run`` wipes ``library/`` on caught failure and writes
the failure-decorated metadata.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Final

from pydantic import BaseModel

from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.contract.materialization import MaterializationReport
from chaos_librarian.contract.replay_bundle import MaterializeReplayBundle
from chaos_librarian.contract.reports import (
    AssetReport,
    BundleReport,
    VariantReport,
    WorkReport,
)
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.validation import ValidationReport

SENTINEL_FILENAME: Final = ".chaos-librarian-run"


def _canonical(model: BaseModel) -> str:
    return model.model_dump_json(indent=2, by_alias=True, exclude_none=True) + "\n"


def _atomic_write_text(target: Path, content: str) -> None:
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_text(content)
    tmp.replace(target)


def _atomic_write_bytes(target: Path, content: bytes) -> None:
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(content)
    tmp.replace(target)


def begin_materialize_run(out_dir: Path, sentinel: RunSentinel) -> None:
    """Create ``out_dir`` with an in-progress sentinel.

    Library subdir is created here too because ffmpeg requires its parent.
    Raises ``FileExistsError`` if ``out_dir`` exists.
    """
    out_dir.mkdir(parents=True)
    (out_dir / "library").mkdir()
    _atomic_write_text(out_dir / SENTINEL_FILENAME, _canonical(sentinel))


def finalize_materialize_run(
    out_dir: Path,
    *,
    initial_manifest: Manifest,
    current_manifest: Manifest,
    journal_lines: list[str],
    validation_report: ValidationReport,
    materialization_report: MaterializationReport,
    replay_bundle: MaterializeReplayBundle,
    scenario_yaml_bytes: bytes,
    sentinel: RunSentinel,
    asset_reports: dict[str, AssetReport],
    work_reports: dict[str, WorkReport],
    variant_reports: dict[str, VariantReport],
    bundle_reports: dict[str, BundleReport],
) -> None:
    """Write metadata atomically and replace the sentinel with state='complete'."""
    _atomic_write_bytes(out_dir / "scenario.yaml", scenario_yaml_bytes)
    _atomic_write_text(out_dir / "manifest.initial.json", _canonical(initial_manifest))
    _atomic_write_text(out_dir / "manifest.current.json", _canonical(current_manifest))
    _atomic_write_text(out_dir / "journal.jsonl", "".join(journal_lines))
    _atomic_write_text(out_dir / "validation.json", _canonical(validation_report))
    _atomic_write_text(out_dir / "materialization.json", _canonical(materialization_report))
    _atomic_write_text(out_dir / "replay.json", _canonical(replay_bundle))
    _write_reports(out_dir, asset_reports, work_reports, variant_reports, bundle_reports)
    # Sentinel last — the moment readers can trust the dir.
    _atomic_write_text(out_dir / SENTINEL_FILENAME, _canonical(sentinel))


def cleanup_failed_run(
    out_dir: Path,
    *,
    initial_manifest: Manifest,
    current_manifest: Manifest,
    journal_lines: list[str],
    validation_report: ValidationReport,
    materialization_report: MaterializationReport,
    replay_bundle: MaterializeReplayBundle,
    scenario_yaml_bytes: bytes,
    sentinel: RunSentinel,
) -> None:
    """Wipe ``library/``, write every metadata file, and flip the sentinel
    to ``complete``.

    The failure run-dir must be readable by ``inspect`` and removable by
    ``clean`` (Finding 4). Both commands hard-require ``replay.json`` and
    ``manifest.current.json``; emitting them on caught failure keeps the
    failure run-dir uniform with the success run-dir from a tooling
    perspective — ``inspect <failed-run>`` shows the same shape, just with
    ``outcome != "success"``. ``current_manifest`` is the un-augmented
    plan-only manifest (no ``content_hash`` / ``probed`` fields populated).

    Reports under ``reports/`` are deliberately NOT written here: Sprint
    4's ``build_report_set`` runs over the un-augmented manifest cleanly,
    but emitting them on a failed run is correctness-neutral and adds
    complexity. Skip them — the spec's failure-outcome rule only requires
    the metadata files that ``inspect`` and ``clean`` consume.
    """
    library = out_dir / "library"
    if library.exists():
        shutil.rmtree(library)
    library.mkdir()  # empty placeholder so the run-dir shape stays stable
    _atomic_write_bytes(out_dir / "scenario.yaml", scenario_yaml_bytes)
    _atomic_write_text(out_dir / "manifest.initial.json", _canonical(initial_manifest))
    _atomic_write_text(out_dir / "manifest.current.json", _canonical(current_manifest))
    _atomic_write_text(out_dir / "journal.jsonl", "".join(journal_lines))
    _atomic_write_text(out_dir / "validation.json", _canonical(validation_report))
    _atomic_write_text(out_dir / "materialization.json", _canonical(materialization_report))
    _atomic_write_text(out_dir / "replay.json", _canonical(replay_bundle))
    # Sentinel last — the moment readers can trust the dir.
    _atomic_write_text(out_dir / SENTINEL_FILENAME, _canonical(sentinel))


def _write_reports(
    out_dir: Path,
    assets: dict[str, AssetReport],
    works: dict[str, WorkReport],
    variants: dict[str, VariantReport],
    bundles: dict[str, BundleReport],
) -> None:
    reports_dir = out_dir / "reports"
    for sub in ("assets", "works", "variants", "bundles"):
        (reports_dir / sub).mkdir(parents=True, exist_ok=True)
    for asset_id, report in assets.items():
        _atomic_write_text(reports_dir / "assets" / f"{asset_id}.json", _canonical(report))
    for work_id, report in works.items():
        _atomic_write_text(reports_dir / "works" / f"{work_id}.json", _canonical(report))
    for variant_id, report in variants.items():
        _atomic_write_text(reports_dir / "variants" / f"{variant_id}.json", _canonical(report))
    for bundle_id, report in bundles.items():
        _atomic_write_text(reports_dir / "bundles" / f"{bundle_id}.json", _canonical(report))
```

- [ ] **Step 4: Run focused tests — pass**

Run: `uv run pytest tests/materializer/test_writer.py -v`
Expected: all green.

- [ ] **Step 5: Lint/type/full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/materializer/writer.py \
        tests/materializer/test_writer.py
git commit -m "$(cat <<'EOF'
feat(materializer): add begin/finalize/cleanup writer helpers

begin_materialize_run creates the run-dir + library/ + in-progress
sentinel. finalize_materialize_run writes every metadata file via
.tmp+rename and flips the sentinel to state=complete last (the moment
readers can trust the dir). cleanup_failed_run wipes library/, writes
the failure-decorated materialization.json, and flips the sentinel —
caught failures terminate with state=complete because they exited
cleanly with a recorded failure.

Refs sprint 5 design doc §Atomic Write And Failure Cleanup.
EOF
)"
```

---

## Task 18: Materializer orchestrator — `materializer/run.py` + Layer 3 tests

**Files:**

- Modify: `src/chaos_librarian/materializer/__init__.py` — re-export public surface.
- Create: `src/chaos_librarian/materializer/run.py` — `materialize_scenario`, `MaterializeArtifacts`.
- Create: `tests/materializer/test_run.py` — Layer 3 mocked orchestrator coverage.

The 8-step pipeline. `run_ffmpeg` and `probe_file` are patched at the module boundary so the tests are pure (no real ffmpeg). Asserts: lazy run-dir allocation, error-path cleanup, success path populates manifest.

- [ ] **Step 1: Update the package `__init__.py`**

Edit `src/chaos_librarian/materializer/__init__.py`:

```python
"""Materializer package — synthesis, subprocess wrappers, run orchestrator.

Public re-exports.
"""

from __future__ import annotations

from chaos_librarian.materializer.capabilities import (
    assert_capable_for_static_materialize,
    detect_capabilities,
)
from chaos_librarian.materializer.errors import (
    CapabilityGateError,
    ContainmentViolationError,
    MaterializationError,
    ProbeParseError,
    ScenarioValidationError,
    TimelineUnsupportedError,
    ToolFailedError,
    UnsupportedMaterializationError,
)
from chaos_librarian.materializer.run import (
    MaterializeArtifacts,
    materialize_scenario,
)

__all__ = [
    "CapabilityGateError",
    "ContainmentViolationError",
    "MaterializationError",
    "MaterializeArtifacts",
    "ProbeParseError",
    "ScenarioValidationError",
    "TimelineUnsupportedError",
    "ToolFailedError",
    "UnsupportedMaterializationError",
    "assert_capable_for_static_materialize",
    "detect_capabilities",
    "materialize_scenario",
]
```

- [ ] **Step 2: Write failing orchestrator tests**

Create `tests/materializer/test_run.py`:

```python
"""Layer 3 — orchestrator with run_ffmpeg and probe_file mocked."""

from __future__ import annotations

import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest

from chaos_librarian.contract.manifest import ProbedMedia, ProbedStream
from chaos_librarian.contract.materialization import (
    Outcome,
    ToolInvocation,
)
from chaos_librarian.materializer import run as run_mod
from chaos_librarian.materializer.errors import (
    ScenarioValidationError,
    TimelineUnsupportedError,
    ToolFailedError,
    UnsupportedMaterializationError,
)
from chaos_librarian.materializer.run import materialize_scenario

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"
INVALID_FIXTURE_DIR = FIXTURE_DIR / "invalid"


@pytest.fixture(autouse=True)
def _patch_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    """All Layer 3 tests assume capabilities pass; only behavior we care
    about is the orchestrator's own logic."""
    from chaos_librarian.contract.capabilities import (
        Capabilities,
        ReadyFor,
        ToolStatus,
    )

    caps = Capabilities(
        schema_version=1,
        ffmpeg=ToolStatus(found=True, version="7.1.1", path="/x/ffmpeg", meets_minimum=True),
        ffprobe=ToolStatus(found=True, version="7.1.1", path="/x/ffprobe", meets_minimum=True),
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test",
        ready_for=ReadyFor(
            materialize_static=True,
            materialize_filesystem_mutations=True,
            materialize_media_mutations=False,
        ),
    )
    monkeypatch.setattr(run_mod, "detect_capabilities", lambda: caps)


def _patch_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make run_ffmpeg + probe_file both succeed for every asset."""

    def fake_run(argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0):
        # write a single byte to the output path so content_hash is stable
        output = Path(argv[-1])
        output.write_bytes(b"x")
        return ToolInvocation(
            tool="ffmpeg",
            version=ffmpeg_version,
            command=argv,
            exit_code=0,
            duration_ns=1_000_000,
        )

    def fake_probe(_path: Path) -> ProbedMedia:
        return ProbedMedia(
            container="matroska,webm",
            duration_seconds=1.0,
            size_bytes=1,
            streams=[ProbedStream(kind="video", codec="h264", width=640, height=480, fps=24.0)],
        )

    monkeypatch.setattr(run_mod, "run_ffmpeg", fake_run)
    monkeypatch.setattr(run_mod, "probe_file", fake_probe)


def test_orchestrator_refuses_non_empty_timeline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Sprint 5 supports only static scenarios. The orchestrator
    rejects with E_MATERIALIZE_TIMELINE_UNSUPPORTED before any subprocess
    starts, and the spec's lazy-allocation guarantee means no run-dir
    exists on exit."""
    _patch_success(monkeypatch)
    out = tmp_path / "run"
    with pytest.raises(TimelineUnsupportedError):
        materialize_scenario(FIXTURE_DIR / "slow-copy.yaml", out)
    assert not out.exists()


def test_orchestrator_refuses_unsupported_audio_codec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Sprint 5 matrix rejects opus at pre-flight; the run-dir must
    not be created (lazy allocation guarantee, Finding 3)."""
    _patch_success(monkeypatch)
    scenario = tmp_path / "opus.yaml"
    scenario.write_text(_STATIC_SCENARIO_OPUS)
    out = tmp_path / "run"
    with pytest.raises(UnsupportedMaterializationError) as exc:
        materialize_scenario(scenario, out)
    assert exc.value.field == "audio[0].codec"
    assert not out.exists()


def test_orchestrator_records_ffmpeg_failure_and_wipes_library(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: a synthesis-time failure leaves a partial run-dir with the
    sentinel at state=complete (caught failure), library/ wiped, and
    materialization.json populated with the failure record."""
    def fake_run(argv: list[str], *, ffmpeg_version: str, timeout_s: float = 60.0):
        return ToolInvocation(
            tool="ffmpeg",
            version=ffmpeg_version,
            command=argv,
            exit_code=1,
            duration_ns=500_000,
        )

    monkeypatch.setattr(run_mod, "run_ffmpeg", fake_run)
    monkeypatch.setattr(run_mod, "probe_file", lambda _p: pytest.fail("probe should not be called"))
    scenario = tmp_path / "static.yaml"
    scenario.write_text(_STATIC_SCENARIO)
    out = tmp_path / "run"
    with pytest.raises(ToolFailedError):
        materialize_scenario(scenario, out)
    assert out.exists()
    assert (out / ".chaos-librarian-run").exists()
    assert list((out / "library").iterdir()) == []  # wiped
    materialization = (out / "materialization.json").read_text()
    assert '"outcome": "tool_failed"' in materialization


def test_orchestrator_success_path_populates_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: the success path's contract is content_hash + probed populated
    for every asset version, and content_hash populated for every sidecar
    (Finding 3) in manifest.current.json."""
    _patch_success(monkeypatch)
    scenario = tmp_path / "static.yaml"
    scenario.write_text(_STATIC_SCENARIO)
    out = tmp_path / "run"
    artifacts = materialize_scenario(scenario, out)
    assert artifacts.materialization_report.outcome is Outcome.SUCCESS
    for version in artifacts.current_manifest.versions:
        assert version.content_hash is not None
        assert version.probed is not None
    assert artifacts.current_manifest.sidecars, (
        "_STATIC_SCENARIO declares a sidecar SRT; the manifest must reflect it"
    )
    for sidecar in artifacts.current_manifest.sidecars:
        assert sidecar.content_hash is not None
        assert sidecar.content_hash.startswith("sha256:")


def test_orchestrator_refuses_semantically_invalid_scenario(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Finding 1 — Sprint 5 must not produce filesystem writes for
    scenarios that fail semantic validation (path containment, unsafe
    path components, etc.). The validation gate runs before any run-dir
    allocation. Any invalid fixture suffices; the gate's behavior is
    uniform across semantic-error codes."""
    _patch_success(monkeypatch)
    invalid = INVALID_FIXTURE_DIR / "path-escape.yaml"
    out = tmp_path / "must_not_exist"
    with pytest.raises(ScenarioValidationError) as exc:
        materialize_scenario(invalid, out)
    assert exc.value.validation_report.ok is False
    assert not out.exists()


def test_orchestrator_rejects_embedded_subtitle_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Finding 2 — Sprint 5 supports sidecar-only; embedded lands in
    Sprint 7. Falling through silently would produce media missing the
    requested subtitles."""
    _patch_success(monkeypatch)
    scenario = tmp_path / "embedded.yaml"
    scenario.write_text(_STATIC_SCENARIO_WITH_EMBEDDED_SUBS)
    out = tmp_path / "run"
    with pytest.raises(UnsupportedMaterializationError) as exc:
        materialize_scenario(scenario, out)
    assert exc.value.field == "subtitle[0].mode"
    assert not out.exists()


def test_orchestrator_rejects_unsupported_subtitle_codec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Finding 2 — Sprint 5 supports SRT only; ASS/SSA would otherwise
    fall through preflight and ``write_text`` SRT bytes under an ``.ass``
    filename, silently producing wrong content."""
    _patch_success(monkeypatch)
    scenario = tmp_path / "ass.yaml"
    scenario.write_text(_STATIC_SCENARIO_WITH_ASS_SUBS)
    out = tmp_path / "run"
    with pytest.raises(UnsupportedMaterializationError) as exc:
        materialize_scenario(scenario, out)
    assert exc.value.field == "subtitle[0].codec"
    assert not out.exists()


def test_orchestrator_probes_each_asset_exactly_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """WHY: Finding 5 — re-probing wastes a subprocess per asset and
    (previously) used a run-dir-relative path that misresolved against
    the CLI cwd. Lock the call count and absolute-path invariant to
    catch a regression that re-introduces the second probe_file call."""
    _patch_success(monkeypatch)
    calls: list[Path] = []

    def counting_probe(path: Path) -> ProbedMedia:
        calls.append(path)
        return ProbedMedia(
            container="matroska,webm", duration_seconds=1.0, size_bytes=1,
            streams=[ProbedStream(kind="video", codec="h264", width=640, height=480, fps=24.0)],
        )

    monkeypatch.setattr(run_mod, "probe_file", counting_probe)
    scenario = tmp_path / "static.yaml"
    scenario.write_text(_STATIC_SCENARIO)
    out = tmp_path / "run"
    materialize_scenario(scenario, out)
    assert len(calls) == 1  # one asset in _STATIC_SCENARIO
    assert all(path.is_absolute() for path in calls)


_STATIC_SCENARIO = """
schema_version: 2
scenario_id: static-test
seed: 1
duration_scale: short
library:
  roots:
    - id: r0
      path: library
works:
  - id: w0
    title: Static
    variants:
      - id: va0
        label: hd
        bundle:
          id: b0
          assets:
            - id: a0
              role: main
              container: mkv
              duration_seconds: 1.0
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
              subtitles:
                - codec: srt
                  language: eng
                  mode: sidecar
                  source: generated_srt
timeline: []
"""

_STATIC_SCENARIO_OPUS = _STATIC_SCENARIO.replace("codec: aac", "codec: opus")

_STATIC_SCENARIO_WITH_EMBEDDED_SUBS = _STATIC_SCENARIO.replace(
    "mode: sidecar",
    "mode: embedded",
)

_STATIC_SCENARIO_WITH_ASS_SUBS = _STATIC_SCENARIO.replace(
    "codec: srt",
    "codec: ass",
)
```

- [ ] **Step 3: Run failing tests**

Run: `uv run pytest tests/materializer/test_run.py -v`
Expected: ImportError on `materialize_scenario` / `MaterializeArtifacts`.

- [ ] **Step 4: Create the orchestrator**

Create `src/chaos_librarian/materializer/run.py`:

```python
"""Materialize orchestrator — the 8-step pipeline.

Lazy run-dir allocation (Finding 3): steps 1-5 run entirely in memory.
Step 6 is the only filesystem-touching primitive before synthesis. The
materializer raises the spec's error hierarchy on any failure; the CLI
handler converts them to exit codes.
"""

from __future__ import annotations

import hashlib
import platform as platform_mod
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from chaos_librarian.contract import (
    MATERIALIZATION_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
    RUN_SENTINEL_SCHEMA_VERSION,
)
from chaos_librarian.contract.manifest import Manifest, ManifestSidecar, ProbedMedia
from chaos_librarian.contract.materialization import (
    MaterializationFailure,
    MaterializationReport,
    MaterializedAsset,
    Outcome,
    ToolchainInfo,
    ToolInvocation,
)
from chaos_librarian.contract.replay_bundle import (
    ExecutionMode,
    MaterializeReplayBundle,
)
from chaos_librarian.contract.run_sentinel import RunSentinel
from chaos_librarian.contract.scenario import (
    AudioSource,
    AudioTrack,
    Scenario,
    SubtitleSource,
    SubtitleTrack,
    VideoSource,
    VideoTrack,
)
from chaos_librarian.engine import (
    PlanArtifacts,
    run_plan,
)
from chaos_librarian.engine.reports import build_report_set
from chaos_librarian.materializer.capabilities import (
    assert_capable_for_static_materialize,
    detect_capabilities,
)
from chaos_librarian.materializer.errors import (
    ProbeParseError,
    ScenarioValidationError,
    TimelineUnsupportedError,
    ToolFailedError,
    UnsupportedMaterializationError,
)
from chaos_librarian.materializer.ffmpeg import build_command, run_ffmpeg
from chaos_librarian.materializer.probe import probe_file
from chaos_librarian.materializer.recipes import (
    FFmpegInput,
    recipe_channel_tones,
    recipe_color_bars,
    recipe_mandelbrot,
    recipe_silence,
    recipe_sine,
    recipe_solid_color,
    srt_payload,
)
from chaos_librarian.materializer.writer import (
    begin_materialize_run,
    cleanup_failed_run,
    finalize_materialize_run,
)
from chaos_librarian.validation import run_validation
from chaos_librarian.validation.input import prepare_run_input

_RESOLUTION_PIXELS = {
    "sd": (640, 480),
    "hd": (1280, 720),
    "1080p": (1920, 1080),
}
_FPS_DEFAULT = 24

_VIDEO_RECIPES = {
    VideoSource.MANDELBROT: recipe_mandelbrot,
    VideoSource.COLOR_BARS: recipe_color_bars,
    VideoSource.SOLID_COLOR: recipe_solid_color,
}
_AUDIO_RECIPES = {
    AudioSource.SINE: recipe_sine,
    AudioSource.SILENCE: recipe_silence,
    AudioSource.CHANNEL_TONES: recipe_channel_tones,
}


@dataclass(frozen=True, slots=True)
class MaterializeArtifacts:
    """Return value of ``materialize_scenario``."""

    current_manifest: Manifest
    materialization_report: MaterializationReport
    replay_bundle: MaterializeReplayBundle


def materialize_scenario(scenario_path: Path, out_dir: Path) -> MaterializeArtifacts:
    """Run the 8-step pipeline. Raises on any failure (caught by the CLI)."""
    started_at = datetime.now(UTC)
    run_input = prepare_run_input(scenario_path)
    scenario = Scenario.model_validate(run_input.raw_data)
    if scenario.timeline:
        raise TimelineUnsupportedError(
            "Sprint 5 materialize accepts static scenarios only; remove timeline events.",
            field="timeline",
            payload={"event_count": len(scenario.timeline)},
        )
    # Step 2 — semantic validation (Finding 1). Mirrors the `plan` CLI:
    # prepare_run_input does NOT run validation and run_plan does NOT
    # re-check `validation_report.ok`, so the materialize entry point
    # must gate explicitly before any run-dir allocation.
    validation_report = run_validation(run_input)
    if not validation_report.ok:
        raise ScenarioValidationError(
            "scenario failed semantic validation; refusing to materialize",
            payload={
                "validation_report": validation_report.model_dump(
                    mode="json", exclude_none=True
                ),
            },
            validation_report=validation_report,
        )
    # Step 3 — capability gate (re-run for materialize entry point).
    caps = detect_capabilities()
    assert_capable_for_static_materialize(caps)
    # Step 4 — engine pass (steps_limit=0; static timeline).
    plan_artifacts = run_plan(
        run_input=run_input,
        validation_report=validation_report,
        steps_limit=0,
    )
    # Step 5 — matrix pre-flight on every asset (subtitles included; Finding 2).
    for asset in _iter_assets(scenario):
        _preflight_asset(asset.video, asset.audio, asset.subtitles, asset.container)
    # Step 6 — begin run-dir.
    run_id = uuid.uuid4()
    sentinel_in_progress = RunSentinel(
        run_id=run_id,
        schema_version=RUN_SENTINEL_SCHEMA_VERSION,
        created_by="chaos-librarian/sprint-5",
        created_at=started_at,
        state="in_progress",
    )
    begin_materialize_run(out_dir, sentinel_in_progress)
    invocations: list[ToolInvocation] = []
    materialized: list[MaterializedAsset] = []
    try:
        for invocation_index, asset in enumerate(_iter_assets(scenario)):
            invocation, materialized_asset, probed, sidecar_hashes = _materialize_one_asset(
                asset, scenario.seed, out_dir, caps, invocation_index
            )
            invocations.append(invocation)
            materialized.append(materialized_asset)
            _augment_manifest(
                plan_artifacts.current_manifest,
                asset,
                materialized_asset,
                probed,
                sidecar_hashes,
            )
    except ToolFailedError as exc:
        invocations.append(exc.invocation)
        _finalize_failure(
            exc,
            out_dir=out_dir,
            outcome=Outcome.TOOL_FAILED,
            started_at=started_at,
            run_id=run_id,
            caps=caps,
            invocations=invocations,
            materialized=materialized,
            run_input=run_input,
            validation_report=validation_report,
            plan_artifacts=plan_artifacts,
        )
        raise
    except ProbeParseError as exc:
        _finalize_failure(
            exc,
            out_dir=out_dir,
            outcome=Outcome.TOOL_FAILED,
            started_at=started_at,
            run_id=run_id,
            caps=caps,
            invocations=invocations,
            materialized=materialized,
            run_input=run_input,
            validation_report=validation_report,
            plan_artifacts=plan_artifacts,
        )
        raise
    # Step 7 — atomic metadata write, sentinel flips to complete.
    finished_at = datetime.now(UTC)
    materialization_report = _build_report(
        outcome=Outcome.SUCCESS,
        run_id=run_id,
        caps=caps,
        started_at=started_at,
        finished_at=finished_at,
        invocations=invocations,
        materialized=materialized,
        failures=[],
    )
    replay_bundle = _build_replay_bundle(
        run_id=run_id,
        scenario_yaml_bytes=run_input.raw_bytes,
        plan_artifacts=plan_artifacts,
        caps=caps,
        created_at=finished_at,
    )
    sentinel_complete = sentinel_in_progress.model_copy(update={"state": "complete"})
    reports = build_report_set(
        plan_artifacts.initial_manifest,
        plan_artifacts.current_manifest,
        plan_artifacts.journal,
    )
    finalize_materialize_run(
        out_dir,
        initial_manifest=plan_artifacts.initial_manifest,
        current_manifest=plan_artifacts.current_manifest,
        journal_lines=plan_artifacts.journal_lines,
        validation_report=validation_report,
        materialization_report=materialization_report,
        replay_bundle=replay_bundle,
        scenario_yaml_bytes=run_input.raw_bytes,
        sentinel=sentinel_complete,
        asset_reports=reports.assets,
        work_reports=reports.works,
        variant_reports=reports.variants,
        bundle_reports=reports.bundles,
    )
    return MaterializeArtifacts(
        current_manifest=plan_artifacts.current_manifest,
        materialization_report=materialization_report,
        replay_bundle=replay_bundle,
    )


def _preflight_asset(
    video: VideoTrack | None,
    audios: list[AudioTrack],
    subtitles: list[SubtitleTrack],
    container: str,
) -> None:
    """Run build_command in a dry mode — raises UnsupportedMaterializationError fast.

    Implementation note: rather than duplicating the matrix tables, call
    build_command against a placeholder output path; it does all the matrix
    rejection work. Catch and re-raise so the orchestrator surface is stable.

    Subtitle checks are inline (Finding 2): Sprint 5 supports exactly one
    combination — ``codec=srt, source=generated_srt, mode=sidecar``. Without
    these gates, ``mode=embedded`` or ``codec=ass`` would fall through and
    the materialize "success" would silently drop the requested subtitles.
    """
    if video is None:
        raise UnsupportedMaterializationError(
            "Sprint 5 requires every asset to declare a video track.",
            field="video", payload={},
        )
    width, height = _RESOLUTION_PIXELS.get(video.resolution, (0, 0))
    video_recipe = _VIDEO_RECIPES.get(video.source)
    if video_recipe is None:
        raise UnsupportedMaterializationError(
            f"video source {video.source!r} not supported in Sprint 5",
            field="video.source",
            payload={"supported": sorted(s.value for s in _VIDEO_RECIPES)},
        )
    audio_inputs: list[FFmpegInput] = []
    for audio in audios:
        recipe = _AUDIO_RECIPES.get(audio.source)
        if recipe is None:
            raise UnsupportedMaterializationError(
                f"audio source {audio.source!r} not supported in Sprint 5",
                field="audio.source",
                payload={"supported": sorted(s.value for s in _AUDIO_RECIPES)},
            )
        audio_inputs.append(recipe(channels=audio.channels, duration_s=1.0, seed=0))
    for index, sub in enumerate(subtitles):
        if sub.codec != "srt":
            raise UnsupportedMaterializationError(
                f"subtitle codec {sub.codec!r} not supported in Sprint 5",
                field=f"subtitle[{index}].codec",
                payload={"supported": ["srt"]},
            )
        if sub.source is not SubtitleSource.GENERATED_SRT:
            raise UnsupportedMaterializationError(
                f"subtitle source {sub.source!r} not supported in Sprint 5",
                field=f"subtitle[{index}].source",
                payload={"supported": [SubtitleSource.GENERATED_SRT.value]},
            )
        if sub.mode != "sidecar":
            raise UnsupportedMaterializationError(
                f"subtitle mode {sub.mode!r} not supported in Sprint 5 "
                "(embedded lands in Sprint 7)",
                field=f"subtitle[{index}].mode",
                payload={"supported": ["sidecar"]},
            )
    video_input = video_recipe(width=width or 1, height=height or 1, fps=_FPS_DEFAULT, duration_s=1.0, seed=0)
    build_command(
        video=video,
        video_input=video_input,
        audios=audios,
        audio_inputs=audio_inputs,
        output_path=Path(f"/tmp/preflight.{container}"),
    )


def _iter_assets(scenario: Scenario):
    """Iterate all assets in scenario order."""
    for work in scenario.works:
        for variant in work.variants:
            for asset in variant.bundle.assets:
                yield asset


def _materialize_one_asset(
    asset, seed: int, out_dir: Path, caps, invocation_index: int
) -> tuple[
    ToolInvocation,
    MaterializedAsset,
    ProbedMedia,
    dict[tuple[str, str], str],
]:
    """Synthesize one asset, returning everything ``_augment_manifest`` needs.

    Returns a 4-tuple of (ffmpeg invocation, materialized asset record,
    probed-media result for the produced file, sidecar hashes keyed by
    ``(asset_id, language)``). Returning probed (Finding 5) lets the
    orchestrator stop re-probing the wrong path; returning sidecar_hashes
    (Finding 3) lets ``_augment_manifest`` populate
    ``ManifestSidecar.content_hash``.
    """
    library_dir = out_dir / "library"
    output_path = library_dir / f"{asset.id}.{asset.container}"
    width, height = _RESOLUTION_PIXELS[asset.video.resolution]
    video_recipe = _VIDEO_RECIPES[asset.video.source]
    video_input = video_recipe(
        width=width, height=height, fps=_FPS_DEFAULT,
        duration_s=asset.duration_seconds, seed=seed,
    )
    audio_inputs: list[FFmpegInput] = []
    for audio in asset.audio:
        recipe = _AUDIO_RECIPES[audio.source]
        audio_inputs.append(
            recipe(channels=audio.channels, duration_s=asset.duration_seconds, seed=seed)
        )
    argv = build_command(
        video=asset.video,
        video_input=video_input,
        audios=asset.audio,
        audio_inputs=audio_inputs,
        output_path=output_path,
    )
    invocation = run_ffmpeg(argv, ffmpeg_version=caps.ffmpeg.version or "unknown")
    if invocation.exit_code != 0:
        raise ToolFailedError(
            f"ffmpeg exit {invocation.exit_code} for asset {asset.id}",
            asset_id=asset.id, field=None,
            payload={"stderr_tail": _extract_stderr_tail(invocation), "exit_code": invocation.exit_code},
            invocation=invocation,
        )
    # Sidecar SRT subtitles. Preflight already rejected non-sidecar modes
    # (Finding 2), so every subtitle here is sidecar; hash the bytes so
    # ``_augment_manifest`` can populate ``ManifestSidecar.content_hash``
    # (Finding 3).
    sidecar_hashes: dict[tuple[str, str], str] = {}
    for sub in asset.subtitles:
        sidecar_path = library_dir / f"{asset.id}.{sub.language}.srt"
        body = srt_payload(
            language=sub.language, duration_s=asset.duration_seconds, seed=seed
        )
        sidecar_path.write_text(body)
        sidecar_hashes[(asset.id, sub.language)] = (
            "sha256:" + hashlib.sha256(body.encode()).hexdigest()
        )
    probed = probe_file(output_path)
    content_hash = "sha256:" + hashlib.sha256(output_path.read_bytes()).hexdigest()
    materialized_asset = MaterializedAsset(
        asset_id=asset.id,
        location_path=str(output_path.relative_to(out_dir)),
        content_hash=content_hash,
        size_bytes=output_path.stat().st_size,
        duration_seconds=probed.duration_seconds,
        invocation_index=invocation_index,
    )
    return invocation, materialized_asset, probed, sidecar_hashes


def _extract_stderr_tail(invocation: ToolInvocation) -> str:
    for token in invocation.command:
        if token.startswith("__stderr_tail__"):
            return token[len("__stderr_tail__"):]
    return ""


def _augment_manifest(
    manifest: Manifest,
    asset,
    materialized: MaterializedAsset,
    probed: ProbedMedia,
    sidecar_hashes: dict[tuple[str, str], str],
) -> None:
    """Stamp ``content_hash`` + ``probed`` onto the version record and
    propagate sidecar hashes onto the matching ``ManifestSidecar`` rows.

    Finding 3: every materialized sidecar's bytes are hashed at write time
    and surfaced here so the manifest's sidecar contract matches the
    success-path test in Task 22.

    Finding 5: ``probed`` is passed in by ``_materialize_one_asset``
    (which already ran ffprobe on the absolute output path). Re-probing
    via ``probe_file(Path(materialized.location_path))`` would dispatch
    against a run-dir-relative string and either miss the file or resolve
    against an unrelated local ``library/`` from the CLI cwd.
    """
    version = next(v for v in manifest.versions if v.asset_id == asset.id)
    version.content_hash = materialized.content_hash
    version.probed = probed
    for sidecar in manifest.sidecars:
        if sidecar.asset_id != asset.id:
            continue
        hash_for_lang = _find_sidecar_hash(sidecar, sidecar_hashes)
        if hash_for_lang is not None:
            sidecar.content_hash = hash_for_lang


def _find_sidecar_hash(
    sidecar: ManifestSidecar, hashes: dict[tuple[str, str], str]
) -> str | None:
    """Match a ``ManifestSidecar`` to its hash by ``asset_id`` + language.

    The Sprint 1/3 engine populates ``ManifestSidecar.path`` containing
    the language tag (``<asset>.<lang>.srt``). If the engine does not
    carry language out-of-band, fall back to substring-matching the path;
    Sprint 5's matrix is one SRT per asset so there is no ambiguity.
    Implementation note: verify the engine's sidecar emission shape when
    wiring this up — if a future engine adds a ``language`` field on
    ``ManifestSidecar``, prefer matching on that.
    """
    for (asset_id, language), value in hashes.items():
        if sidecar.asset_id == asset_id and language in sidecar.path:
            return value
    return None


def _build_report(
    *, outcome: Outcome, run_id: uuid.UUID, caps, started_at: datetime,
    finished_at: datetime, invocations: list[ToolInvocation],
    materialized: list[MaterializedAsset], failures: list[MaterializationFailure],
) -> MaterializationReport:
    return MaterializationReport(
        schema_version=MATERIALIZATION_SCHEMA_VERSION,
        run_id=run_id,
        outcome=outcome,
        platform=caps.platform,
        started_at=started_at,
        finished_at=finished_at,
        toolchain=ToolchainInfo(
            ffmpeg=caps.ffmpeg.version,
            ffprobe=caps.ffprobe.version,
            mkvtoolnix=caps.mkvtoolnix.version,
        ),
        invocations=invocations,
        materialized=materialized,
        failures=failures,
    )


def _build_replay_bundle(
    *, run_id: uuid.UUID, scenario_yaml_bytes: bytes,
    plan_artifacts: PlanArtifacts, caps, created_at: datetime,
) -> MaterializeReplayBundle:
    return MaterializeReplayBundle(
        schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
        chaos_librarian_version="0.1.0",
        scenario=scenario_yaml_bytes.decode(),
        run_id=run_id,
        resolved_seed=plan_artifacts.replay_bundle.resolved_seed,
        journal_digest=plan_artifacts.replay_bundle.journal_digest,
        execution_mode=ExecutionMode.MATERIALIZE,
        created_at=created_at,
        toolchain=ToolchainInfo(
            ffmpeg=caps.ffmpeg.version,
            ffprobe=caps.ffprobe.version,
            mkvtoolnix=caps.mkvtoolnix.version,
        ),
    )


def _finalize_failure(
    exc, *, out_dir: Path, outcome: Outcome, started_at: datetime, run_id: uuid.UUID,
    caps, invocations: list[ToolInvocation], materialized: list[MaterializedAsset],
    run_input, validation_report, plan_artifacts: PlanArtifacts,
) -> None:
    """Assemble every metadata file ``cleanup_failed_run`` requires.

    Finding 4: the failed run-dir must remain readable by ``inspect`` and
    removable by ``clean``. Both commands hard-require ``replay.json``;
    ``inspect`` additionally hard-requires ``manifest.current.json``. The
    un-augmented plan-only manifest from ``plan_artifacts`` is correct
    here — synthesis aborted, so no version has ``content_hash``/``probed``.
    """
    finished_at = datetime.now(UTC)
    failure = MaterializationFailure(
        asset_id=getattr(exc, "asset_id", None),
        stage="ffmpeg" if outcome is Outcome.TOOL_FAILED else "ffprobe",
        exit_code=getattr(getattr(exc, "invocation", None), "exit_code", None),
        stderr_tail=str(exc.payload.get("stderr_tail", "")),
        invocation_index=len(invocations) - 1 if invocations else None,
    )
    report = _build_report(
        outcome=outcome, run_id=run_id, caps=caps, started_at=started_at,
        finished_at=finished_at, invocations=invocations, materialized=materialized,
        failures=[failure],
    )
    replay_bundle = _build_replay_bundle(
        run_id=run_id,
        scenario_yaml_bytes=run_input.raw_bytes,
        plan_artifacts=plan_artifacts,
        caps=caps,
        created_at=finished_at,
    )
    sentinel_complete = RunSentinel(
        run_id=run_id,
        schema_version=RUN_SENTINEL_SCHEMA_VERSION,
        created_by="chaos-librarian/sprint-5",
        created_at=started_at,
        state="complete",
    )
    cleanup_failed_run(
        out_dir,
        initial_manifest=plan_artifacts.initial_manifest,
        current_manifest=plan_artifacts.current_manifest,
        journal_lines=plan_artifacts.journal_lines,
        validation_report=validation_report,
        materialization_report=report,
        replay_bundle=replay_bundle,
        scenario_yaml_bytes=run_input.raw_bytes,
        sentinel=sentinel_complete,
    )
```

Implementation note: `_iter_assets` is the local helper above; there is no `Scenario.iter_assets` method. Every asset iteration in this module routes through `_iter_assets`.

Verified against the current repo (commit `f5901f6`): `engine.run_plan` accepts `validation_report=` as a kwarg (see `src/chaos_librarian/engine/plan.py:58-87`) and `RunInput` exposes `raw_bytes` / `raw_data` only (see `src/chaos_librarian/validation/input.py:20-28`). There is no `RunInput.scenario` or `RunInput.scenario_yaml_bytes` attribute, so the orchestrator parses the scenario via `Scenario.model_validate(run_input.raw_data)` and uses `run_input.raw_bytes` for the YAML bytes embedded in the replay bundle. Confirm `PlanArtifacts.journal_lines` exists with the expected shape when wiring up; if the engine instead exposes typed entries (`journal`), serialize them via Sprint 4's writer helper before calling `finalize_materialize_run` / `cleanup_failed_run`.

- [ ] **Step 5: Run focused tests — pass**

Run: `uv run pytest tests/materializer/test_run.py -v`
Expected: all green. Adjust the orchestrator's API consumption (`prepare_run_input`, `run_plan`, `build_report_set`) if signatures differ; the tests are intentionally minimal so the only thing they exercise is the orchestrator's own control flow.

- [ ] **Step 6: Lint/type/full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all clean.

- [ ] **Step 7: Commit**

```bash
git add src/chaos_librarian/materializer/__init__.py \
        src/chaos_librarian/materializer/run.py \
        tests/materializer/test_run.py
git commit -m "$(cat <<'EOF'
feat(materializer): add materialize_scenario orchestrator

8-step pipeline: timeline scope -> containment -> capability gate ->
engine pass -> matrix pre-flight -> per-asset synthesis loop -> atomic
metadata write -> return. Lazy run-dir allocation: steps 1-5 never
touch the filesystem; on any pre-flight rejection out_dir does not
exist. Synthesis failures wipe library/, write the failure-decorated
materialization.json, and flip the sentinel to state=complete.

Public re-exports land in materializer/__init__.py.

Refs sprint 5 design doc §Composition flow.
EOF
)"
```

---

## Task 19: Wire up `capabilities` CLI command

**Files:**

- Modify: `src/chaos_librarian/cli/app.py` — real `capabilities` body (replace `_stub`).
- Create: `tests/cli/test_capabilities.py` — Layer 5 CLI integration coverage.

Both human and JSON output use the indented form per spec Decision 4. Exit code is 0 when ffmpeg AND ffprobe both meet minimums, 4 otherwise.

- [ ] **Step 1: Write failing tests**

Create `tests/cli/test_capabilities.py`:

```python
"""Layer 5 — capabilities CLI integration tests with detect mocked."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.capabilities import (
    Capabilities,
    ReadyFor,
    ToolStatus,
)

runner = CliRunner()


def _caps(*, all_ok: bool = True) -> Capabilities:
    ffmpeg = ToolStatus(
        found=True, version="7.1.1", path="/x/ffmpeg",
        meets_minimum=all_ok,
    )
    ffprobe = ToolStatus(
        found=True, version="7.1.1", path="/x/ffprobe",
        meets_minimum=all_ok,
    )
    return Capabilities(
        schema_version=1,
        ffmpeg=ffmpeg,
        ffprobe=ffprobe,
        mkvtoolnix=ToolStatus(found=False, meets_minimum=False),
        platform="test-arch",
        ready_for=ReadyFor(
            materialize_static=all_ok,
            materialize_filesystem_mutations=all_ok,
            materialize_media_mutations=False,
        ),
    )


def test_capabilities_exit_zero_on_minimum_met(monkeypatch):
    """WHY: agents read `capabilities --json` to decide whether to attempt
    materialize. Exit 0 with a JSON payload (Capabilities round-trip
    compatible) is the spec contract."""
    import chaos_librarian.cli.app as app_mod

    monkeypatch.setattr(app_mod, "detect_capabilities", lambda: _caps(all_ok=True))
    result = runner.invoke(app, ["capabilities", "--json"])
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    Capabilities.model_validate(payload)
    assert payload["ready_for"]["materialize_static"] is True


def test_capabilities_exit_four_when_ffmpeg_missing(monkeypatch):
    """WHY: a regressed toolchain must surface as exit 4 with the same
    JSON payload — humans and agents see the structured reason regardless
    of exit code."""
    import chaos_librarian.cli.app as app_mod

    monkeypatch.setattr(app_mod, "detect_capabilities", lambda: _caps(all_ok=False))
    result = runner.invoke(app, ["capabilities", "--json"])
    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    assert payload["ready_for"]["materialize_static"] is False


def test_capabilities_human_output_formats_each_tool(monkeypatch):
    import chaos_librarian.cli.app as app_mod

    monkeypatch.setattr(app_mod, "detect_capabilities", lambda: _caps(all_ok=True))
    result = runner.invoke(app, ["capabilities"])
    assert result.exit_code == 0
    assert "ffmpeg" in result.stdout
    assert "ffprobe" in result.stdout
    assert "mkvtoolnix" in result.stdout
```

- [ ] **Step 2: Run failing tests**

Run: `uv run pytest tests/cli/test_capabilities.py -v`
Expected: `_stub` raises Exit(code=1); JSON parse fails because output is the "not yet implemented" stderr message.

- [ ] **Step 3: Replace the `capabilities` stub**

Edit `src/chaos_librarian/cli/app.py`. Add a top-level import:

```python
from chaos_librarian.materializer import detect_capabilities
```

Replace the `capabilities` body (find it via `rg "def capabilities" src/chaos_librarian/cli/app.py`):

```python
@app.command()
def capabilities(
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Detect available media tools (ffmpeg, ffprobe, mkvtoolnix)."""
    caps = detect_capabilities()
    if json_output:
        typer.echo(caps.model_dump_json(indent=2, exclude_none=True))
    else:
        _render_capabilities_human(caps)
    exit_code = 0 if (caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum) else 4
    raise typer.Exit(code=exit_code)


def _render_capabilities_human(caps) -> None:
    typer.echo(f"platform:   {caps.platform}")
    for name, tool in (("ffmpeg", caps.ffmpeg), ("ffprobe", caps.ffprobe), ("mkvtoolnix", caps.mkvtoolnix)):
        if not tool.found:
            typer.echo(f"  {name}:     missing")
            continue
        status = "OK" if tool.meets_minimum else "BELOW MINIMUM"
        typer.echo(f"  {name}:     {tool.version} ({tool.path}) [{status}]")
    typer.echo("ready_for:")
    typer.echo(f"  materialize_static:               {caps.ready_for.materialize_static}")
    typer.echo(f"  materialize_filesystem_mutations: {caps.ready_for.materialize_filesystem_mutations}")
    typer.echo(f"  materialize_media_mutations:      {caps.ready_for.materialize_media_mutations}")
```

(The exact indentation / column alignment can be polished to match the project's other human-output commands; do not change the JSON body.)

- [ ] **Step 4: Run focused tests — pass**

Run: `uv run pytest tests/cli/test_capabilities.py -v`
Expected: all green.

- [ ] **Step 5: Lint/type/full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all clean.

- [ ] **Step 6: Commit**

```bash
git add src/chaos_librarian/cli/app.py tests/cli/test_capabilities.py
git commit -m "$(cat <<'EOF'
feat(cli): wire up real capabilities command

Replaces the Sprint 0 stub. Exit 0 when ffmpeg and ffprobe both meet
their minimums (mkvtoolnix is optional in Sprint 5), exit 4 otherwise.
JSON body is the full Capabilities payload in both success and failure
cases — agents see the structured reason regardless of exit code.

Refs sprint 5 design doc Decision 3 + Decision 4.
EOF
)"
```

---

## Task 20: Wire up `materialize` CLI + handle `replay <materialize-bundle>`

**Files:**

- Modify: `src/chaos_librarian/cli/app.py` — real `materialize` body; `replay` rejects materialize bundles cleanly.
- Modify: `tests/cli/test_replay.py` — materialize-bundle not-implemented assertion.
- Create: `tests/cli/test_materialize.py` — Layer 5 with `materialize_scenario` mocked.

Wires the orchestrator into the CLI surface. Maps each `MaterializationError` subclass to its exit code + stdout JSON payload per the spec error model. `replay` rejects materialize bundles with exit 1 instead of silently parsing them as plan-only.

- [ ] **Step 1: Write failing tests — `materialize` CLI**

Create `tests/cli/test_materialize.py`:

```python
"""Layer 5 — materialize CLI with materialize_scenario mocked."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

import chaos_librarian.cli.app as app_mod
from chaos_librarian.cli.app import app
from chaos_librarian.contract import (
    MATERIALIZATION_SCHEMA_VERSION,
    REPLAY_BUNDLE_SCHEMA_VERSION,
)
from chaos_librarian.contract.manifest import Manifest, ProbedMedia, ProbedStream
from chaos_librarian.contract.materialization import (
    MaterializationReport,
    Outcome,
    ToolchainInfo,
)
from chaos_librarian.contract.replay_bundle import (
    ExecutionMode,
    MaterializeReplayBundle,
)
from chaos_librarian.materializer import MaterializeArtifacts
from chaos_librarian.materializer.errors import (
    CapabilityGateError,
    ScenarioValidationError,
    TimelineUnsupportedError,
    UnsupportedMaterializationError,
)

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _success(tmp_path: Path) -> MaterializeArtifacts:
    return MaterializeArtifacts(
        current_manifest=Manifest(
            schema_version=2, works=[], variants=[], bundles=[], assets=[],
            versions=[], locations=[], sidecars=[],
        ),
        materialization_report=MaterializationReport(
            schema_version=MATERIALIZATION_SCHEMA_VERSION,
            run_id=uuid.uuid4(), outcome=Outcome.SUCCESS, platform="test",
            started_at=datetime.now(UTC), finished_at=datetime.now(UTC),
            toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
        ),
        replay_bundle=MaterializeReplayBundle(
            schema_version=REPLAY_BUNDLE_SCHEMA_VERSION,
            chaos_librarian_version="0.1.0",
            scenario="schema_version: 2\nscenario_id: x\n",
            run_id=uuid.uuid4(), resolved_seed=1, journal_digest="0" * 64,
            execution_mode=ExecutionMode.MATERIALIZE,
            created_at=datetime.now(UTC),
            toolchain=ToolchainInfo(ffmpeg="7.1.1", ffprobe="7.1.1"),
        ),
    )


def test_materialize_exit_zero_on_success(monkeypatch, tmp_path: Path) -> None:
    out = tmp_path / "run"
    out.mkdir()  # mocked orchestrator does not allocate
    monkeypatch.setattr(app_mod, "materialize_scenario", lambda *_a, **_k: _success(tmp_path))
    result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out / "x"), "--json"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert payload["outcome"] == "success"


def test_materialize_exit_four_on_capability_gate(monkeypatch, tmp_path: Path) -> None:
    def raise_gate(*_a, **_k):
        raise CapabilityGateError(
            "ffmpeg missing",
            payload={"capabilities": {"ffmpeg": {"found": False}}},
        )

    monkeypatch.setattr(app_mod, "materialize_scenario", raise_gate)
    out = tmp_path / "no_caps"
    result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out), "--json"],
    )
    assert result.exit_code == 4
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "E_MATERIALIZE_CAPABILITY_GATE"


def test_materialize_exit_five_on_unsupported_lazy_allocation(
    monkeypatch, tmp_path: Path
) -> None:
    """WHY: lazy allocation guarantee (Finding 3) — pre-synthesis failures
    leave NO on-disk artifact and the stdout JSON omits
    materialization_report_path."""
    def raise_unsupported(*_a, **_k):
        raise UnsupportedMaterializationError(
            "opus not supported",
            asset_id="a0", field="audio[0].codec",
            payload={"supported": ["aac"]},
        )

    monkeypatch.setattr(app_mod, "materialize_scenario", raise_unsupported)
    out = tmp_path / "absent"
    result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out), "--json"],
    )
    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "E_MATERIALIZE_UNSUPPORTED"
    assert "materialization_report_path" not in payload
    assert not out.exists()


def test_materialize_exit_five_on_timeline(monkeypatch, tmp_path: Path) -> None:
    def raise_timeline(*_a, **_k):
        raise TimelineUnsupportedError(
            "no timeline allowed", field="timeline", payload={"event_count": 1}
        )

    monkeypatch.setattr(app_mod, "materialize_scenario", raise_timeline)
    out = tmp_path / "absent"
    result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "slow-copy.yaml"), "--out", str(out), "--json"],
    )
    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "E_MATERIALIZE_TIMELINE_UNSUPPORTED"


def test_materialize_exit_three_on_validation_failure(
    monkeypatch, tmp_path: Path
) -> None:
    """WHY: Finding 1 — the materialize entry must mirror ``plan``'s
    exit-3 convention for semantic-validation failures so agents can
    disambiguate "scenario rejected" from "tool failed". The stdout JSON
    carries E_MATERIALIZE_VALIDATION_FAILED and omits
    materialization_report_path (no run-dir allocated)."""
    from chaos_librarian.contract.validation import (
        ValidationIssue,
        ValidationReport,
        ValidationSeverity,
    )

    bad_report = ValidationReport(
        schema_version=1, ok=False, scenario_id="bad",
        issues=[
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                code="E_PATH_CONTAINMENT",
                message="asset path escapes library/",
                line=None, column=None, path=None,
            )
        ],
    )

    def raise_validation(*_a, **_k):
        raise ScenarioValidationError(
            "scenario failed semantic validation; refusing to materialize",
            payload={
                "validation_report": bad_report.model_dump(
                    mode="json", exclude_none=True
                ),
            },
            validation_report=bad_report,
        )

    monkeypatch.setattr(app_mod, "materialize_scenario", raise_validation)
    out = tmp_path / "absent"
    result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out), "--json"],
    )
    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "E_MATERIALIZE_VALIDATION_FAILED"
    assert "materialization_report_path" not in payload
    assert not out.exists()
```

- [ ] **Step 2: Run failing tests — `materialize`**

Run: `uv run pytest tests/cli/test_materialize.py -v`
Expected: every test fails — the stub returns exit 1.

- [ ] **Step 3: Write failing test — `replay <materialize-bundle>`**

Append to `tests/cli/test_replay.py`:

```python
def test_replay_refuses_materialize_bundle(tmp_path: Path) -> None:
    """WHY: Sprint 5 ships the MaterializeReplayBundle variant for schema
    stability but does NOT implement materialize replay. The CLI must
    refuse with exit 1 and a structured payload so agents know to expect
    this in Sprint 9, not silently parse it as plan-only."""
    bundle_path = tmp_path / "replay.json"
    bundle_path.write_text(
        json.dumps(
            {
                "schema_version": 3,
                "chaos_librarian_version": "0.1.0",
                "scenario": "schema_version: 2\nscenario_id: x\n",
                "run_id": "00000000-0000-4000-8000-000000000001",
                "resolved_seed": 1,
                "applied_events": 0,
                "journal_digest": "0" * 64,
                "execution_trace": [],
                "execution_mode": "materialize",
                "created_at": "2026-05-18T00:00:00Z",
                "toolchain": {"ffmpeg": "7.1.1"},
            }
        )
    )
    result = runner.invoke(app, ["replay", str(bundle_path), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stderr)
    assert payload["error"] == "materialize_replay_not_implemented"
    assert payload["execution_mode"] == "materialize"
```

- [ ] **Step 4: Wire `materialize` in the CLI**

Edit `src/chaos_librarian/cli/app.py`. Add imports:

```python
from chaos_librarian.materializer import (
    CapabilityGateError,
    ContainmentViolationError,
    MaterializationError,
    ProbeParseError,
    ScenarioValidationError,
    TimelineUnsupportedError,
    ToolFailedError,
    UnsupportedMaterializationError,
    materialize_scenario,
)
```

Update `src/chaos_librarian/materializer/__init__.py` to re-export `ScenarioValidationError` alongside the other concrete error classes (it's defined in Task 10 but added to `__all__` here when the orchestrator first lands).

Replace the `materialize` body (find via `rg "def materialize" src/chaos_librarian/cli/app.py`):

```python
@app.command()
def materialize(
    scenario: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    out: Annotated[Path, typer.Option("--out", callback=_validate_new_out_path)],
    json_output: Annotated[bool, typer.Option("--json")] = False,
) -> None:
    """Materialize a scenario (creates real media files)."""
    try:
        artifacts = materialize_scenario(scenario, out)
    except CapabilityGateError as exc:
        _emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=4) from exc
    except ScenarioValidationError as exc:
        # Mirror `plan`'s exit code (3) for semantic-validation failures so
        # downstream agents key off the same convention (Finding 1).
        _emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=3) from exc
    except TimelineUnsupportedError as exc:
        _emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=5) from exc
    except UnsupportedMaterializationError as exc:
        _emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=5) from exc
    except ToolFailedError as exc:
        _emit_materialize_error(exc, json_output=json_output, run_dir=out)
        raise typer.Exit(code=5) from exc
    except ProbeParseError as exc:
        _emit_materialize_error(exc, json_output=json_output, run_dir=out)
        raise typer.Exit(code=5) from exc
    except ContainmentViolationError as exc:
        _emit_materialize_error(exc, json_output=json_output, run_dir=None)
        raise typer.Exit(code=7) from exc

    if json_output:
        typer.echo(artifacts.materialization_report.model_dump_json(indent=2, exclude_none=True))
    else:
        typer.echo(f"materialize: wrote {out}")


def _emit_materialize_error(
    exc: MaterializationError,
    *,
    json_output: bool,
    run_dir: Path | None,
) -> None:
    payload: dict[str, object] = {
        "error_code": exc.error_code,
        "message": exc.message,
    }
    if exc.asset_id is not None:
        payload["asset_id"] = exc.asset_id
    if exc.field is not None:
        payload["field"] = exc.field
    payload.update(exc.payload)
    if run_dir is not None:
        payload["materialization_report_path"] = str(run_dir / "materialization.json")
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True))
    else:
        typer.echo(f"chaos-librarian: materialize failed ({exc.error_code})", err=True)
        typer.echo(f"  message: {exc.message}", err=True)
        if exc.asset_id is not None:
            typer.echo(f"  asset:   {exc.asset_id}", err=True)
        if exc.field is not None:
            typer.echo(f"  field:   {exc.field}", err=True)
        if run_dir is not None:
            typer.echo(f"  report:  {run_dir / 'materialization.json'}", err=True)
```

- [ ] **Step 5: Wire `replay` materialize-bundle detection**

Edit `src/chaos_librarian/cli/app.py`. Find the `replay` command body. After parsing the bundle (replace the existing PlanOnly-only assumption with):

```python
from chaos_librarian.contract.replay_bundle import (
    MaterializeReplayBundle,
    PlanOnlyReplayBundle,
    ReplayBundle,
)
from pydantic import TypeAdapter

_REPLAY_BUNDLE_ADAPTER: Final = TypeAdapter(ReplayBundle)


# Inside the replay command body, after reading the bundle path's text:
parsed = _REPLAY_BUNDLE_ADAPTER.validate_json(bundle_bytes)
if isinstance(parsed, MaterializeReplayBundle):
    _emit_step_error(
        "materialize_replay_not_implemented",
        "materialize replay lands in Sprint 9 (voom-v2 adapter)",
        json_output=json_output,
        extra={"execution_mode": parsed.execution_mode.value},
    )
    raise typer.Exit(code=1)
```

(Adapt to existing replay-handler structure — the existing handler likely already calls `PlanOnlyReplayBundle.model_validate_json`; swap to the discriminated `TypeAdapter` so both variants parse and dispatch by isinstance.)

- [ ] **Step 6: Run focused tests — pass**

Run: `uv run pytest tests/cli/test_materialize.py tests/cli/test_replay.py -v`
Expected: all green.

- [ ] **Step 7: Lint/type/full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all clean.

- [ ] **Step 8: Commit**

```bash
git add src/chaos_librarian/cli/app.py \
        tests/cli/test_materialize.py \
        tests/cli/test_replay.py
git commit -m "$(cat <<'EOF'
feat(cli): wire up materialize and materialize-bundle replay refusal

materialize maps each MaterializationError subclass to its spec exit
code (4 / 5 / 7) and stdout JSON payload. materialization_report_path
is omitted for pre-synthesis failures per Finding 3.

replay now parses the bundle via the discriminated TypeAdapter and
refuses MaterializeReplayBundle inputs with exit 1 +
materialize_replay_not_implemented payload. Sprint 9's voom-v2 adapter
will lift this; the bundle variant exists at v3 so the schema artifact
is stable for Sprint 6+ readers.

Refs sprint 5 design doc §Error model + Decision 2.
EOF
)"
```

---

## Task 21: Static-library scenario fixture

**Files:**

- Create: `tests/fixtures/scenarios/static-library.yaml` — three-asset Sprint 5 matrix fixture.

The smoke test (Task 22) materializes this fixture against a real ffmpeg. Three assets exercise: mkv+h264+aac stereo, mp4+h264+aac 5.1, mkv+h264+aac+SRT sidecar. Every value falls inside Sprint 5's matrix.

- [ ] **Step 1: Add the fixture file**

Create `tests/fixtures/scenarios/static-library.yaml`:

```yaml
schema_version: 2
scenario_id: static-library
seed: 1
duration_scale: short
library:
  roots:
    - id: root_main
      path: library
works:
  - id: w_movie
    title: Static Library Smoke Test
    variants:
      - id: va_hd
        label: hd
        bundle:
          id: b_hd
          assets:
            - id: a_hd_main
              role: main
              container: mkv
              duration_seconds: 2.0
              video:
                source: color_bars
                codec: h264
                resolution: hd
              audio:
                - source: sine
                  codec: aac
                  channels: stereo
                  language: eng
      - id: va_1080
        label: 1080p
        bundle:
          id: b_1080
          assets:
            - id: a_1080_main
              role: main
              container: mp4
              duration_seconds: 2.0
              video:
                source: solid_color
                codec: h264
                resolution: "1080p"
              audio:
                - source: channel_tones
                  codec: aac
                  channels: "5.1"
                  language: eng
      - id: va_sd_subs
        label: sd-subs
        bundle:
          id: b_sd_subs
          assets:
            - id: a_sd_main
              role: main
              container: mkv
              duration_seconds: 2.0
              video:
                source: mandelbrot
                codec: h264
                resolution: sd
              audio:
                - source: sine
                  codec: aac
                  channels: mono
                  language: eng
              subtitles:
                - source: generated_srt
                  codec: srt
                  language: eng
                  mode: sidecar
timeline: []
```

- [ ] **Step 2: Validate the fixture parses against scenario v2**

Run: `uv run pytest tests/contract/test_sample_scenarios.py -v`
Expected: every existing fixture plus `static-library.yaml` validates against `Scenario` v2.

- [ ] **Step 3: Smoke-validate via the CLI plan command**

Run: `uv run chaos-librarian validate tests/fixtures/scenarios/static-library.yaml`
Expected: exit 0; validation report `ok: true`.

- [ ] **Step 4: Lint and final commit**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/scenarios/static-library.yaml
git commit -m "$(cat <<'EOF'
test(fixtures): add static-library Sprint 5 matrix fixture

Three assets covering mkv+h264+aac stereo, mp4+h264+aac 5.1, and
mkv+h264+aac+SRT sidecar — every cell inside Sprint 5's matrix. The
empty timeline is required by static-materialize. Used by Layer 4
integration tests in the next task.
EOF
)"
```

---

## Task 22: Layer 4 integration tests — success paths against real ffmpeg

**Files:**

- Create: `tests/integration/test_materialize_real.py` — smoke / bit-exact / cross-mode / capabilities-real tests.

Real ffmpeg / ffprobe. Skipped on systems where ffmpeg < 7.0 (CI must install a sufficient version). The smoke test asserts the Finding 1 contract: sidecar files exist + content_hash agreement + no subtitle entries in `asset.probed.streams[]`.

- [ ] **Step 1: Write the smoke test and bitexact test**

Create `tests/integration/test_materialize_real.py`:

```python
"""Layer 4 — real ffmpeg integration tests. Skipped if ffmpeg < 7.0."""

from __future__ import annotations

import hashlib
import json
import subprocess
import uuid
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chaos_librarian.cli.app import app
from chaos_librarian.contract.canonicalize import canonicalize
from chaos_librarian.contract.manifest import Manifest
from chaos_librarian.materializer.capabilities import (
    MIN_VERSIONS,
    detect_capabilities,
)

runner = CliRunner()
FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "scenarios"


def _ffmpeg_meets_minimum() -> bool:
    caps = detect_capabilities()
    return caps.ffmpeg.meets_minimum and caps.ffprobe.meets_minimum


pytestmark = pytest.mark.skipif(
    not _ffmpeg_meets_minimum(),
    reason=f"ffmpeg/ffprobe >= {MIN_VERSIONS['ffmpeg']} not available",
)


def test_materialize_static_library_smoke(tmp_path: Path) -> None:
    """WHY: end-to-end smoke — every asset must exist, probe successfully,
    content_hash must match the file bytes, no failures, AND (Finding 1)
    sidecars must exist with content_hash matching file bytes, with NO
    subtitle entries in asset.probed.streams[]."""
    out = tmp_path / "smoke"
    result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "static-library.yaml"), "--out", str(out), "--json"],
    )
    assert result.exit_code == 0, result.stdout + result.stderr
    manifest = Manifest.model_validate_json((out / "manifest.current.json").read_text())
    materialization = json.loads((out / "materialization.json").read_text())
    assert materialization["outcome"] == "success"
    assert materialization["failures"] == []

    for version in manifest.versions:
        location = next(loc for loc in manifest.locations if loc.asset_id == version.asset_id)
        path = out / location.path
        assert path.exists()
        assert version.content_hash is not None
        actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        assert version.content_hash == actual
        assert version.probed is not None
        assert all(s.kind != "subtitle" for s in version.probed.streams)

    for sidecar in manifest.sidecars:
        path = out / sidecar.path
        assert path.exists()
        assert sidecar.content_hash is not None
        actual = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        assert sidecar.content_hash == actual


def test_materialize_bitexact_same_toolchain(tmp_path: Path) -> None:
    """WHY: bit-exact determinism within a fixed toolchain is the Sprint 5
    contract; two runs of the same scenario+seed must produce identical
    content_hash values for every asset."""
    out_a = tmp_path / "a"
    out_b = tmp_path / "b"
    for out in (out_a, out_b):
        result = runner.invoke(
            app,
            ["materialize", str(FIXTURE_DIR / "static-library.yaml"), "--out", str(out)],
        )
        assert result.exit_code == 0, result.stdout + result.stderr
    manifest_a = Manifest.model_validate_json((out_a / "manifest.current.json").read_text())
    manifest_b = Manifest.model_validate_json((out_b / "manifest.current.json").read_text())
    hashes_a = sorted((v.asset_id, v.content_hash) for v in manifest_a.versions)
    hashes_b = sorted((v.asset_id, v.content_hash) for v in manifest_b.versions)
    assert hashes_a == hashes_b


def test_materialize_cross_mode_logical_oracle_ids(tmp_path: Path) -> None:
    """WHY: plan-only and materialize must produce the same logical-oracle
    structure for the same scenario+seed; the canonicalize() helper proves
    the manifests match modulo stripped fields (content_hash + probed)."""
    plan_out = tmp_path / "plan"
    mat_out = tmp_path / "mat"
    plan_result = runner.invoke(
        app, ["plan", str(FIXTURE_DIR / "static-library.yaml"), "--out", str(plan_out)]
    )
    assert plan_result.exit_code == 0, plan_result.stdout + plan_result.stderr
    mat_result = runner.invoke(
        app, ["materialize", str(FIXTURE_DIR / "static-library.yaml"), "--out", str(mat_out)]
    )
    assert mat_result.exit_code == 0, mat_result.stdout + mat_result.stderr
    plan_manifest = Manifest.model_validate_json((plan_out / "manifest.current.json").read_text())
    mat_manifest = Manifest.model_validate_json((mat_out / "manifest.current.json").read_text())
    assert canonicalize(plan_manifest) == canonicalize(mat_manifest)
    assert (plan_out / "journal.jsonl").read_text() == (mat_out / "journal.jsonl").read_text()


def test_capabilities_real() -> None:
    """WHY: the capabilities CLI is the agent's entry point for capability
    probing — round-trip the JSON through Capabilities to lock the
    contract."""
    completed = subprocess.run(
        ["uv", "run", "chaos-librarian", "capabilities", "--json"],
        check=False, capture_output=True, text=True, timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
    from chaos_librarian.contract.capabilities import Capabilities

    Capabilities.model_validate_json(completed.stdout)
```

- [ ] **Step 2: Run the layer-4 tests**

Run: `uv run pytest tests/integration/test_materialize_real.py -v`
Expected: all green on a host with ffmpeg ≥ 7.0; skipped (with the configured reason) otherwise.

If a test fails because the asset doesn't probe correctly, capture the failing manifest / materialization JSON and trace back — the most likely causes are (a) the FFmpeg builder produced argv that ffmpeg rejects on the host's libx264 build, or (b) the recipe lavfi syntax is too aggressive for older ffmpeg. Fix the builder rather than relaxing the test.

- [ ] **Step 3: Lint/type/full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all clean.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/__init__.py tests/integration/test_materialize_real.py
git commit -m "$(cat <<'EOF'
test(integration): Layer 4 success-path materialize tests

Real ffmpeg/ffprobe required (skip-if-not-installed). Covers:
- end-to-end smoke (every asset exists, hashes match, sidecars hashed,
  no subtitle streams in asset.probed per Finding 1)
- same-toolchain bit-exactness (two runs produce identical content_hash)
- cross-mode logical oracle equality (canonicalize() strips volatile
  fields and the two manifests compare equal)
- real capabilities subprocess round-trip
EOF
)"
```

(If `tests/integration/__init__.py` did not exist before this task, create it as an empty file in the same commit.)

---

## Task 23: Layer 4 failure paths + interrupted-recovery (Finding 2)

**Files:**

- Modify: `tests/integration/test_materialize_real.py` — three more tests covering unsupported_codec, tool_failure, and interrupted_recovery.

These exercise the failure-cleanup contract and the new `state` sentinel surface. The interrupted-recovery test patches ffmpeg to simulate a SIGTERM mid-run, then walks the `inspect`/`step`/`clean` CLI surface against the state="in_progress" sentinel.

- [ ] **Step 1: Write the failure-path tests**

Append to `tests/integration/test_materialize_real.py`:

```python
import signal
import os


def test_materialize_unsupported_codec(tmp_path: Path) -> None:
    """WHY: lazy allocation (Finding 3) — pre-synthesis rejection must
    leave NO on-disk artifact; the stdout JSON must omit
    materialization_report_path."""
    bad_yaml = (FIXTURE_DIR / "static-library.yaml").read_text().replace(
        "codec: aac", "codec: opus", 1
    )
    scenario_path = tmp_path / "opus.yaml"
    scenario_path.write_text(bad_yaml)
    out = tmp_path / "no_run_dir_please"
    result = runner.invoke(
        app, ["materialize", str(scenario_path), "--out", str(out), "--json"]
    )
    assert result.exit_code == 5
    payload = json.loads(result.stdout)
    assert payload["error_code"] == "E_MATERIALIZE_UNSUPPORTED"
    assert "materialization_report_path" not in payload
    assert not out.exists()


def test_materialize_tool_failure(tmp_path: Path, monkeypatch) -> None:
    """WHY: a synthesis-time tool failure must wipe library/, write a
    failure-decorated materialization.json, and flip the sentinel to
    state=complete (caught failure)."""
    fake_ffmpeg = tmp_path / "ffmpeg-fail"
    fake_ffmpeg.write_text("#!/bin/sh\nexit 1\n")
    fake_ffmpeg.chmod(0o755)
    fake_path = f"{tmp_path}:{os.environ.get('PATH', '')}"
    monkeypatch.setenv("PATH", fake_path)
    # Rename our shim into a bin dir prefix
    (tmp_path / "ffmpeg").symlink_to(fake_ffmpeg)

    out = tmp_path / "failed"
    result = runner.invoke(
        app, ["materialize", str(FIXTURE_DIR / "static-library.yaml"), "--out", str(out), "--json"]
    )
    assert result.exit_code == 5
    assert (out / ".chaos-librarian-run").exists()
    sentinel = json.loads((out / ".chaos-librarian-run").read_text())
    assert sentinel["state"] == "complete"
    assert list((out / "library").iterdir()) == []
    report = json.loads((out / "materialization.json").read_text())
    assert report["outcome"] == "tool_failed"
    assert report["failures"]
    # Finding 4: the failed run-dir must remain readable by `inspect` and
    # removable by `clean`; both commands hard-require replay.json and
    # manifest.current.json on disk.
    for required in ("replay.json", "manifest.current.json"):
        assert (out / required).exists(), required


def test_inspect_works_against_failed_run(tmp_path: Path, monkeypatch) -> None:
    """WHY: Finding 4 — ``inspect`` reads ``replay.json`` and
    ``manifest.current.json`` unguarded; a failed run-dir missing either
    file crashes the command with exit 1. ``cleanup_failed_run`` must
    emit both so the standard inspect surface keeps working post-failure."""
    fake_ffmpeg = tmp_path / "ffmpeg-fail"
    fake_ffmpeg.write_text("#!/bin/sh\nexit 1\n")
    fake_ffmpeg.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")
    (tmp_path / "ffmpeg").symlink_to(fake_ffmpeg)

    out = tmp_path / "failed_for_inspect"
    materialize_result = runner.invoke(
        app,
        ["materialize", str(FIXTURE_DIR / "static-library.yaml"), "--out", str(out), "--json"],
    )
    assert materialize_result.exit_code == 5

    inspect_result = runner.invoke(app, ["inspect", str(out), "--json"])
    assert inspect_result.exit_code == 0, inspect_result.stdout + inspect_result.stderr
    inspect_payload = json.loads(inspect_result.stdout)
    assert "materialization" in inspect_payload or "outcome" in str(inspect_payload)

    clean_result = runner.invoke(app, ["clean", str(out)])
    assert clean_result.exit_code == 0, clean_result.stdout + clean_result.stderr
    assert not out.exists()


def test_materialize_interrupted_recovery(tmp_path: Path) -> None:
    """WHY: Finding 2 — uncaught signals leave state=in_progress; inspect
    surfaces it, step refuses with E_SENTINEL_IN_PROGRESS exit 7, clean
    accepts the dir."""
    out = tmp_path / "partial"
    # Build a partial run-dir by running plan then mutating the sentinel
    # to state=in_progress (a real signal-interrupted materialize is
    # harder to simulate cross-platform; the contract is on the sentinel
    # state alone, so the construction here is faithful).
    plan_result = runner.invoke(
        app, ["plan", str(FIXTURE_DIR / "bundle-sidecars.yaml"), "--out", str(out)]
    )
    assert plan_result.exit_code == 0
    sentinel_path = out / ".chaos-librarian-run"
    blob = json.loads(sentinel_path.read_text())
    blob["state"] = "in_progress"
    sentinel_path.write_text(json.dumps(blob, indent=2) + "\n")

    inspect_result = runner.invoke(app, ["inspect", str(out), "--json"])
    assert inspect_result.exit_code == 0
    assert json.loads(inspect_result.stdout)["sentinel"]["state"] == "in_progress"

    step_result = runner.invoke(app, ["step", str(out), "--json"])
    assert step_result.exit_code == 7
    step_payload = json.loads(step_result.stderr)
    assert step_payload["error"] == "E_SENTINEL_IN_PROGRESS"

    clean_result = runner.invoke(app, ["clean", str(out)])
    assert clean_result.exit_code == 0
    assert not out.exists()
```

- [ ] **Step 2: Run the failure tests**

Run: `uv run pytest tests/integration/test_materialize_real.py -v`
Expected: all green. If `test_materialize_tool_failure` doesn't pick up the fake ffmpeg because `chaos-librarian` invokes ffmpeg via `shutil.which` at startup (cached in `capabilities`), restructure the test to monkeypatch `chaos_librarian.materializer.capabilities.shutil_which` and `chaos_librarian.materializer.ffmpeg.run_ffmpeg` directly via a `pytest-subtests`-style indirection — the contract under test is the orchestrator's behavior on a non-zero exit, not the shell PATH dance.

- [ ] **Step 3: Lint/type/full suite**

Run: `uv run pytest -q && uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: all clean.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_materialize_real.py
git commit -m "$(cat <<'EOF'
test(integration): Layer 4 failure paths + interrupted-recovery

- unsupported_codec asserts lazy allocation (no on-disk artifact, no
  materialization_report_path in stdout JSON) per Finding 3.
- tool_failure asserts library/ wiped, sentinel state=complete (caught
  failure), materialization.json present with outcome=tool_failed.
- interrupted_recovery asserts the full inspect/step/clean surface
  against an in_progress sentinel per Finding 2.
EOF
)"
```

---

## Task 24: Final verification sweep

**Files:** none (verification only).

The closing gate that confirms everything from Tasks 1-23 is coherent.

- [ ] **Step 1: Full suite**

Run: `uv run pytest -q`
Expected: every test passes, no skips except the Layer 4 ones that require real ffmpeg (which should NOT skip on the developer's machine if ffmpeg ≥ 7.0 is installed).

- [ ] **Step 2: Drift gate**

Run: `uv run python -m chaos_librarian.schema_export --check`
Expected: `All 12 schemas up-to-date.`

- [ ] **Step 3: Lint + type-check**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`
Expected: clean.

- [ ] **Step 4: Pre-commit hooks**

Run: `prek run --all-files`
Expected: every hook passes (ruff format, ruff check, uv-lock, drift gate).

- [ ] **Step 5: CLI surface smoke**

Run: `uv run chaos-librarian --help`
Expected: lists every Sprint 0-5 command including the now-real `capabilities` and `materialize`. No `--stub` markers.

- [ ] **Step 6: Verify branch contents against main**

Run: `git diff --stat main...HEAD | tail`
Expected: every modified path is under `src/chaos_librarian/`, `tests/`, `schemas/`, `docs/superpowers/`, or `pyproject.toml` / `uv.lock`. No surprise changes (e.g. to `.github/workflows/` or top-level docs).

- [ ] **Step 7: Read the spec one more time against the diff**

Manually scan `docs/superpowers/specs/2026-05-18-sprint-5-design.md` against `git log --oneline main..HEAD`. For each spec section — Goal, Decisions, Capability Detection, Content Sources, FFmpeg Command Builder, Manifest Augmentation, Atomic Write, Error Model, Testing Strategy, Exit Criteria — point to the commit that implements it. Note any gap and decide whether it needs a follow-up commit or is intentional (e.g. canonicalization tests against a second toolchain — Sprint 9).

- [ ] **Step 8: Done — no commit at this task**

Open a PR against `main` titled `feat(sprint-5): materializer capabilities + static materialize` once the audit is clean. PR body should describe what shipped at the level of "what's in the diff", not the brainstorm history.

---

## Adversarial Review Log

The Codex adversarial review of this plan (2026-05-18) returned a `needs-attention` verdict with five findings (1 critical, 4 high). Each is resolved by the edits in this revision; the plan now reflects those resolutions.

- **Finding 1 (CRITICAL) — Materialize path bypasses validation.** The original orchestrator entry accessed non-existent `run_input.scenario` / `run_input.scenario_yaml_bytes` attributes and threaded `run_input.validation_report` into `run_plan` (also non-existent) — `prepare_run_input` does NOT run semantic validation and `run_plan` explicitly does not re-check `validation_report.ok`. An invalid scenario would have reached `library/` writes. Resolution: Task 18 parses via `Scenario.model_validate(run_input.raw_data)`, runs `run_validation(run_input)` explicitly, and raises a new `ScenarioValidationError` (Task 10) carrying the full `ValidationReport`. Task 20's CLI handler dispatches that subclass to exit 3, mirroring `plan`'s convention. The `run_input.raw_bytes` attribute (the real name) is used for the YAML bytes embedded in the replay bundle and `finalize_materialize_run` / `cleanup_failed_run` calls.
- **Finding 2 (HIGH) — Unsupported subtitle modes silently succeed.** The original `_preflight_asset(video, audios, container)` ignored subtitles; `_materialize_one_asset` then wrote SRT bytes only when `sub.mode == "sidecar"` and never checked `sub.codec` or `sub.source`. A scenario with `mode: embedded` or `codec: ass` would have ended with a "successful" materialize missing the requested subtitles. Resolution: Task 18 widens `_preflight_asset` to `_preflight_asset(video, audios, subtitles, container)` and adds three inline checks — `codec != "srt"`, `source is not SubtitleSource.GENERATED_SRT`, and `mode != "sidecar"` each raise `UnsupportedMaterializationError` with the appropriate `subtitle[N].<field>` field path. Two new Layer 3 tests (`test_orchestrator_rejects_embedded_subtitle_mode`, `test_orchestrator_rejects_unsupported_subtitle_codec`) pin the behavior.
- **Finding 3 (HIGH) — Sidecar hashes are never written to the manifest.** The original sidecar block wrote SRT bytes but never hashed them or surfaced the digest onto `ManifestSidecar.content_hash`. Task 22's success-path smoke test would have failed when it asserted `sidecar.content_hash` matched `sha256(file_bytes)`. Resolution: Task 18's `_materialize_one_asset` hashes each sidecar's bytes at write-time and returns a `sidecar_hashes` dict keyed on `(asset_id, language)`. `_augment_manifest` accepts the dict and copies the digest onto every matching `ManifestSidecar`. The Layer 3 success-path test (`test_orchestrator_success_path_populates_manifest`) now asserts `sidecar.content_hash` is populated.
- **Finding 4 (HIGH) — Caught failures leave run-dir that `clean`/`inspect` cannot handle.** The original `cleanup_failed_run` wrote only `materialization.json` + sentinel. The current CLI's `clean` (`src/chaos_librarian/cli/app.py:486-542`) requires `replay.json` (exits 7 with `fixture_inconsistent` if missing) and `inspect` (`src/chaos_librarian/cli/app.py:384-447`) unguardedly reads both `replay.json` and `manifest.current.json` (crashes with exit 1 on `FileNotFoundError`). Resolution: Task 17 extends `cleanup_failed_run`'s signature to write every metadata file `finalize_materialize_run` does, keeping the failed run-dir uniform with the success run-dir from a tooling perspective. Task 18's `_finalize_failure` is updated to assemble the un-augmented manifest, replay bundle, validation report, and scenario bytes; Task 23 adds a `test_inspect_works_against_failed_run` sibling test and extends `test_materialize_tool_failure` to assert clean+inspect succeed against the failed dir.
- **Finding 5 (HIGH) — Manifest augmentation probes the wrong path.** The original `_augment_manifest` called `probe_file(Path(materialized.location_path))` where `location_path` is run-dir-relative (e.g. `library/a_hd_main.mkv`). From the CLI cwd this either misses the file or resolves against an unrelated local `library/`. Resolution: Task 18's `_materialize_one_asset` returns the `ProbedMedia` it already computed (no second probe). `_augment_manifest` takes `probed` as a parameter and stamps it directly. A new Layer 3 test (`test_orchestrator_probes_each_asset_exactly_once`) locks the call count at one per asset and asserts every probe path is absolute, catching any regression that re-introduces the second probe.

---

## Self-Review Summary

- **Spec coverage:** every decision in the design doc maps to a task — Task 1 (Decision 9), Task 2 (Decision 5 + Finding 1 of the spec review), Task 3 (Decision 13 + Finding 2 of the spec review), Task 4 (Decision 4), Task 5 (Decision-level fill-in + Finding 3 outcome enum), Task 6 (Decision 11), Task 7 (Decision 12), Task 8 (Layer 1 drift gate), Task 9 (Layer 4 sibling canonicalize), Tasks 10-18 (Decisions 1, 2, 7, 8, 10 + §Composition flow), Tasks 19-20 (CLI surface), Task 21 (Decision 1 fixture), Tasks 22-23 (Layer 4 + Finding 2 recovery).
- **Placeholder scan:** all code blocks are paste-ready, no `TBD`/`TODO`/`...` markers in the body of any step. The Task 18 orchestrator references a couple of internal helpers (`_iter_assets`, `_extract_stderr_tail`, `_find_sidecar_hash`) that are defined in the same module — kept inline rather than in separate modules to keep the file count down.
- **Type consistency:** every method/field name used in later tasks matches its definition (e.g. `MaterializeArtifacts.materialization_report` is the name used in both Task 18 and Task 20, `_canonical_version_from_tool_output` matches the spec edit and the Task 11 test).
- **Adversarial review status:** all five Codex findings (1 critical, 4 high) from the 2026-05-18 review are addressed by the revisions cataloged in the "Adversarial Review Log" section above; the orchestrator now validates before allocation, preflight covers subtitles, sidecar hashes propagate to the manifest, `cleanup_failed_run` emits every file `inspect`/`clean` consume, and `_augment_manifest` uses the cached probed result on an absolute path.

