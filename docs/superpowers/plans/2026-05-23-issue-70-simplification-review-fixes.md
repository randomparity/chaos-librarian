# Issue 70 Simplification Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce duplicated content-source and Phase-A synthesis plumbing introduced on the Issue 70 branch while preserving materialize/run/replay contracts.

**Architecture:** Keep public JSON contracts unchanged. Move track-specific source resolution behind video/audio request dataclasses, let preflight request only FFmpeg inputs, centralize Phase-A collection in `synthesis.py`, and make content-cache file storage hash while copying.

**Tech Stack:** Python 3.13, Pydantic v2 contracts, Typer CLI, pytest, ruff, ty, JSON Schema export gate.

---

### Task 1: Source Resolution Shape And Preflight Evidence

**Files:**
- Modify: `src/chaos_librarian/materializer/content_sources.py`
- Modify: `src/chaos_librarian/materializer/preflight.py`
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Modify: `tests/materializer/test_content_sources.py`

- [ ] **Step 1: Add red tests**

Add a test proving preflight does not build replay evidence:

```python
def test_preflight_asset_does_not_build_content_source_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_recipe_digest(**_kwargs):
        raise AssertionError("preflight should not compute replay evidence")

    monkeypatch.setattr(content_sources, "_recipe_digest", fail_recipe_digest)
    preflight_asset(
        _video(),
        [_audio()],
        [],
        "mkv",
    )
```

Update source tests to import `AudioSourceRequest` and `VideoSourceRequest`, then replace `_video_request()` / `_audio_request()` with track-specific request builders. Delete mismatch-only tests because the resolver now derives `source` from the enum.

- [ ] **Step 2: Run red tests**

Run: `uv run pytest tests/materializer/test_content_sources.py -q --no-cov`

Expected: the new preflight test fails with `AssertionError: preflight should not compute replay evidence`.

- [ ] **Step 3: Implement track-specific requests**

In `content_sources.py`, replace `SourceRequest` with:

```python
@dataclass(frozen=True, slots=True)
class VideoSourceRequest:
    asset_id: str
    seed: int
    duration_s: float
    width: int
    height: int
    fps: int
    track_index: None = None


@dataclass(frozen=True, slots=True)
class AudioSourceRequest:
    asset_id: str
    track_index: int
    seed: int
    duration_s: float
    channels: str
```

Add `resolve_video_input()` and `resolve_audio_input()` helpers that call provider input-only methods. Keep `resolve_video_source()` and `resolve_audio_source()` returning `SourceResolution` for synthesis.

- [ ] **Step 4: Route preflight through input-only helpers**

In `preflight.py`, build `VideoSourceRequest` / `AudioSourceRequest` with dummy `asset_id="preflight"`, `seed=0`, and `duration_s=1.0`, but call `resolve_video_input()` and `resolve_audio_input()` so no evidence digest is produced.

- [ ] **Step 5: Route synthesis through evidence helpers**

In `synthesis.py`, build `VideoSourceRequest` / `AudioSourceRequest` with real asset, seed, and duration values, then call `resolve_video_source()` and `resolve_audio_source()` so materialize reports and replay bundles still carry evidence.

- [ ] **Step 6: Verify task**

Run: `uv run pytest tests/materializer/test_content_sources.py -q --no-cov`

Expected: all selected tests pass.

### Task 2: Builtin Provider Registration

**Files:**
- Modify: `src/chaos_librarian/materializer/content_sources.py`
- Modify: `tests/materializer/test_content_sources.py`

- [ ] **Step 1: Simplify provider model**

Replace `_BuiltinLavfiVideoProvider`, `_BuiltinLavfiAudioProvider`, `_registered_providers()`, and `_merge_provider_capabilities()` with one `_BuiltinLavfiProvider` that owns both recipe maps. Its `capability()` returns the sorted union of `audio:*` and `video:*` sources.

- [ ] **Step 2: Keep direct resolver maps**

Keep `_VIDEO_PROVIDERS` and `_AUDIO_PROVIDERS` as source-to-provider maps pointing to the single builtin provider object so unregistered source rejection remains simple.

- [ ] **Step 3: Update tests**

Delete the fake same-name provider merge test. Keep tests that assert one `builtin-lavfi` provider and the exact source tuple:

```python
assert provider.sources == (
    "audio:channel_tones",
    "audio:silence",
    "audio:sine",
    "video:color_bars",
    "video:mandelbrot",
    "video:solid_color",
)
```

- [ ] **Step 4: Verify task**

Run: `uv run pytest tests/materializer/test_content_sources.py tests/materializer/test_capabilities.py tests/cli/test_capabilities.py -q --no-cov`

Expected: all selected tests pass.

### Task 3: Shared Phase-A Collection

**Files:**
- Modify: `src/chaos_librarian/materializer/synthesis.py`
- Modify: `src/chaos_librarian/materializer/run.py`
- Modify: `src/chaos_librarian/materializer/replay.py`
- Modify: `src/chaos_librarian/materializer/wall_clock.py`
- Create: `tests/materializer/test_synthesis.py`

- [ ] **Step 1: Add red helper coverage**

Add a focused test that imports `materialize_assets_phase_a` and verifies it collects invocations, materialized assets, and content-source evidence while stamping the manifest. The test should monkeypatch `synthesis.materialize_one_asset` to avoid ffmpeg.

- [ ] **Step 2: Run red test**

Run: `uv run pytest tests/materializer/test_synthesis.py::test_materialize_assets_phase_a_collects_and_stamps_manifest -q --no-cov`

Expected: import failure or attribute error because `materialize_assets_phase_a` does not exist yet.

- [ ] **Step 3: Implement shared result**

In `synthesis.py`, add:

```python
@dataclass(slots=True)
class PhaseAResult:
    invocations: list[ToolInvocation] = field(default_factory=list)
    materialized_assets: list[MaterializedAsset] = field(default_factory=list)
    content_sources: list[ContentSourceEvidence] = field(default_factory=list)
    probed_by_asset: dict[str, ProbedMedia] = field(default_factory=dict)
    sidecar_hashes_by_asset: dict[str, dict[tuple[str, str], str]] = field(default_factory=dict)
```

Add `materialize_assets_phase_a()` that loops over `iter_assets(scenario)`, calls `materialize_one_asset()`, appends each field, and optionally stamps `augment_manifest()` on the supplied manifest with each asset's skip languages.

- [ ] **Step 4: Use shared helper in modes**

In `run.py`, replace the inline Phase-A loop with `materialize_assets_phase_a(stamp_manifest=True)`.

In `replay.py`, replace `_synthesize_phase_a()` and `_stamp_phase_a_asset()` usage with `materialize_assets_phase_a(stamp_manifest=True)`.

In `wall_clock.py`, replace `_synthesize_phase_a()` and `_stamp_phase_a_metadata()` internals with `materialize_assets_phase_a(stamp_manifest=True)`, reusing the result's `probed_by_asset` and `sidecar_hashes_by_asset` when rebuilding prefix artifacts.

- [ ] **Step 5: Verify task**

Run: `uv run pytest tests/materializer/test_synthesis.py tests/materializer/test_run.py tests/materializer/test_replay.py tests/materializer/test_wall_clock.py tests/integration/test_wall_clock_run.py -q --no-cov`

Expected: all selected tests pass.

### Task 4: Content Cache Single-Pass Store

**Files:**
- Modify: `src/chaos_librarian/materializer/content_cache.py`
- Modify: `tests/materializer/test_content_cache.py`

- [ ] **Step 1: Update red test**

Replace the monkeypatched `cache_key_for_path` mutation test with a direct mismatched-key test:

```python
def test_store_file_rejects_digest_mismatch_and_removes_temp(tmp_path: Path) -> None:
    cache = ContentCache(tmp_path / "cache")
    source = tmp_path / "source.bin"
    source.write_bytes(b"actual")
    key = cache_key_for_bytes(b"expected")

    with pytest.raises(ValueError, match="content hash mismatch"):
        cache.store_file(cache_key=key, source_path=source)

    destination = cache.path_for(cache_key=key)
    assert not destination.exists()
    assert list(destination.parent.glob("*.tmp")) == []
```

- [ ] **Step 2: Run red test**

Run: `uv run pytest tests/materializer/test_content_cache.py::test_store_file_hashes_while_copying -q --no-cov`

Expected: failure with `AssertionError: store_file should not pre-hash the source path`.

- [ ] **Step 3: Implement single-pass copy**

In `ContentCache.store_file()`, remove the pre-copy `cache_key_for_path(source_path)` pass. Compute `copied_hash` while copying to the sibling temp file, compare it with `cache_key`, replace the final file only on match, and return `CacheRecord(cache_key=cache_key, content_hash=copied_hash, path=path)`.

- [ ] **Step 4: Verify task**

Run: `uv run pytest tests/materializer/test_content_cache.py -q --no-cov`

Expected: all selected tests pass.

### Task 5: Final Verification And Commit

**Files:**
- Modify: generated schemas only if contract model output drifts.

- [ ] **Step 1: Format**

Run: `uv run ruff format src/chaos_librarian/materializer tests/materializer tests/integration/test_wall_clock_run.py`

- [ ] **Step 2: Targeted tests**

Run: `uv run pytest tests/materializer/test_content_sources.py tests/materializer/test_content_cache.py tests/materializer/test_synthesis.py tests/materializer/test_run.py tests/materializer/test_replay.py tests/materializer/test_wall_clock.py tests/integration/test_wall_clock_run.py tests/materializer/test_capabilities.py tests/cli/test_capabilities.py -q --no-cov`

- [ ] **Step 3: Static checks**

Run: `uv run ruff check . && uv run ruff format --check . && uv run ty check src tests`

- [ ] **Step 4: Schema drift gate**

Run: `uv run python -m chaos_librarian.schema_export --check`

- [ ] **Step 5: Commit**

Run:

```bash
git status --short
git add docs/superpowers/plans/2026-05-23-issue-70-simplification-review-fixes.md src/chaos_librarian/materializer/content_sources.py src/chaos_librarian/materializer/content_cache.py src/chaos_librarian/materializer/preflight.py src/chaos_librarian/materializer/synthesis.py src/chaos_librarian/materializer/run.py src/chaos_librarian/materializer/replay.py src/chaos_librarian/materializer/wall_clock.py tests/materializer/test_content_sources.py tests/materializer/test_content_cache.py tests/materializer/test_synthesis.py
git commit -m "refactor(materializer): simplify content source plumbing"
```

Expected: one commit on `feat/gh-issue-70`.

## Self-Review

- Spec coverage: covers every accepted simplification review finding with code and verification steps.
- Placeholder scan: no TBD/TODO/fill-in-later language.
- Type consistency: all new helpers and dataclasses live in `synthesis.py` or `content_sources.py` and are referenced consistently by task steps.
